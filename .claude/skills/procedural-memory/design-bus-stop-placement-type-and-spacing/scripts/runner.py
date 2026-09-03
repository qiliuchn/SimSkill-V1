"""Run one scenario cell (plain SUMO or TraCI+TSP) and reduce it to metrics.

Person-delay accounting is the point of this module: every result carries BOTH
vehicle-delay and person-delay (bus riders weighted by actual occupancy), plus
completion / teleport / stop-service validity counters.
"""
import os
import sys
import json
import glob
import shutil
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import asdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from scenario import Cfg, build_scenario, SUMO, SUMO_HOME  # noqa: E402

TSP_SKILL = "/Users/liuqi/Desktop/simskill/.claude/skills/procedural-memory/implement-transit-signal-priority/scripts"


# ---------------------------------------------------------------- parsing ---
def parse_tripinfo(path, cfg, occ_car):
    """Return (car metrics, bus-vehicle metrics, rider metrics, validity)."""
    root = ET.parse(path).getroot()
    w0, w1 = cfg.warmup, cfg.demand_end
    cars = {"n": 0, "n_unfinished": 0, "dur": 0.0, "loss": 0.0, "wait": 0.0,
            "n_art": 0, "dur_art": 0.0, "loss_art": 0.0,
            "n_cross": 0, "loss_cross": 0.0}
    buses = {"n": 0, "n_unfinished": 0, "dur": 0.0, "loss": 0.0}
    for ti in root.findall("tripinfo"):
        dep = float(ti.get("depart"))
        vt = ti.get("vType")
        unfinished = ti.get("arrival") is None or float(ti.get("arrival")) < 0
        if not (w0 <= dep < w1):
            continue
        dur = float(ti.get("duration"))
        loss = float(ti.get("timeLoss"))
        if vt == "bus":
            buses["n"] += 1
            buses["n_unfinished"] += int(unfinished)
            buses["dur"] += dur
            buses["loss"] += loss
        else:
            cars["n"] += 1
            cars["n_unfinished"] += int(unfinished)
            cars["dur"] += dur
            cars["loss"] += loss
            cars["wait"] += float(ti.get("waitingTime", 0.0))
            vid = ti.get("id")
            if vid.startswith("eb") or vid.startswith("wb"):
                cars["n_art"] += 1
                cars["dur_art"] += dur
                cars["loss_art"] += loss
            else:
                cars["n_cross"] += 1
                cars["loss_cross"] += loss

    riders = {"n": 0, "n_incomplete": 0, "access": 0.0, "wait": 0.0, "inveh": 0.0,
              "egress": 0.0, "total": 0.0, "ride_len": 0.0, "access_len": 0.0,
              "egress_len": 0.0, "access_lens": [], "totals": [],
              "n_still_waiting": 0, "n_still_riding": 0, "records": {}}
    for pi in root.findall("personinfo"):
        dep = float(pi.get("depart"))
        if not (w0 <= dep < w1):
            continue
        stages = list(pi)
        rides = [i for i, c in enumerate(stages) if c.tag == "ride"]
        if not rides:
            riders["n_incomplete"] += 1
            riders["n_still_waiting"] += 1
            continue
        ri = rides[0]
        r = stages[ri]
        if r.get("arrival") is None or float(r.get("arrival")) < 0:
            riders["n_incomplete"] += 1
            riders["n_still_riding"] += 1
            continue
        acc = sum(float(c.get("duration", 0)) for c in stages[:ri])
        acc_len = sum(float(c.get("routeLength", 0) or 0) for c in stages[:ri])
        egr = sum(float(c.get("duration", 0) or 0) for c in stages[ri + 1:])
        egr_len = sum(float(c.get("routeLength", 0) or 0) for c in stages[ri + 1:])
        wait = float(r.get("waitingTime", 0))
        inveh = float(r.get("duration"))
        rl = float(r.get("routeLength"))
        tot = acc + wait + inveh + egr
        riders["n"] += 1
        riders["access"] += acc
        riders["wait"] += wait
        riders["inveh"] += inveh
        riders["egress"] += egr
        riders["total"] += tot
        riders["ride_len"] += rl
        riders["access_len"] += acc_len
        riders["egress_len"] += egr_len
        riders["access_lens"].append(acc_len)
        riders["totals"].append(tot)
        riders["records"][pi.get("id")] = (round(acc, 1), round(wait, 1), round(inveh, 1),
                                           round(egr, 1), round(tot, 1), round(acc_len, 1),
                                           round(egr_len, 1), round(rl, 1))

    return cars, buses, riders


def parse_summary(path):
    root = ET.parse(path).getroot()
    steps = root.findall("step")
    if not steps:
        return {"teleports": 0, "max_running": 0, "final_running": 0, "end_t": 0.0}
    tel = max(int(s.get("teleports", 0)) for s in steps)
    return {"teleports": tel,
            "max_running": max(int(s.get("running", 0)) for s in steps),
            "final_running": int(steps[-1].get("running", 0)),
            "end_t": float(steps[-1].get("time"))}


def parse_stopinfo(path, stop_ids, n_buses):
    root = ET.parse(path).getroot()
    rows = sorted([s.attrib for s in root if s.attrib.get("busStop")],
                  key=lambda r: (r["id"], float(r["started"])))
    # a bay re-entry penalty is authored as a SECOND consecutive stop at the same
    # busStop -> merge consecutive (bus, busStop) events into one service event
    merged = []
    for r in rows:
        if r.get("busStop") is None:
            continue
        if merged and merged[-1]["id"] == r["id"] and merged[-1]["busStop"] == r["busStop"] \
                and float(r["started"]) - float(merged[-1]["ended"]) <= 3.0:
            m = merged[-1]
            m["ended"] = r["ended"]
            m["loadedPersons"] = str(int(m["loadedPersons"]) + int(r["loadedPersons"]))
            m["unloadedPersons"] = str(int(m["unloadedPersons"]) + int(r["unloadedPersons"]))
            continue
        merged.append(dict(r))
    served = {}
    dwell = []
    pax = []
    blocked = 0.0
    for r in merged:
        served.setdefault(r["id"], []).append(r["busStop"])
        d = float(r["ended"]) - float(r["started"])
        dwell.append(d)
        pax.append(int(r["loadedPersons"]) + int(r["unloadedPersons"]))
        blocked += float(r.get("blockedDuration", 0) or 0)
    rows = merged
    missing = 0
    for b, lst in served.items():
        missing += len(set(stop_ids) - set(lst))
    return {"n_stop_events": len(dwell),
            "expected_stop_events": n_buses * len(stop_ids),
            "buses_seen": len(served),
            "missed_stop_services": missing,
            "mean_dwell": (sum(dwell) / len(dwell)) if dwell else 0.0,
            "total_dwell": sum(dwell),
            "mean_pax_per_stop": (sum(pax) / len(pax)) if pax else 0.0,
            "total_blocked": blocked,
            "rows": rows}


# ---------------------------------------------------------------- running ---
def run_cell(cfg, outdir, seed, tsp="none", keep=(), extra_opts=None):
    """tsp: none | conditional | aggressive"""
    if os.path.isdir(outdir):
        shutil.rmtree(outdir)
    os.makedirs(outdir, exist_ok=True)
    sc = build_scenario(cfg, outdir, seed)
    trip = os.path.join(outdir, "tripinfo.xml")
    summ = os.path.join(outdir, "summary.xml")
    stops = os.path.join(outdir, "stopinfo.xml")
    err = os.path.join(outdir, "err.txt")
    opts = ["-n", sc["net"], "-a", sc["busstops"],
            "-r", f'{sc["cars"]},{sc["buses"]},{sc["persons"]}',
            "--tripinfo-output", trip, "--summary-output", summ,
            "--stop-output", stops,
            "--tripinfo-output.write-unfinished", "true",
            "--duration-log.statistics", "true", "--no-step-log", "true",
            "--time-to-teleport", "300", "--seed", str(seed),
            "-e", str(int(cfg.sim_end)),
            "--pedestrian.striping.stripe-width", "0.65",
            "--default.action-step-length", "1.0"]
    if "fcdbus" in keep:
        opts += ["--fcd-output", os.path.join(outdir, "fcd.xml"),
                 "--fcd-output.attributes", "id,x,speed,lane,type",
                 "--device.fcd.probability", "0"]
    if "fcd" in keep:
        opts += ["--fcd-output", os.path.join(outdir, "fcd.xml"),
                 "--fcd-output.filter-shapes", ""] if False else \
                ["--fcd-output", os.path.join(outdir, "fcd.xml"), "--device.fcd.period", "1"]
    if "lanechange" in keep:
        opts += ["--lanechange-output", os.path.join(outdir, "lanechange.xml"),
                 "--lanechange-output.started", "true", "--lanechange-output.ended", "true"]
    e2 = None
    if "e2" in keep:
        # E2 detector spanning each full EB arterial link -> max jam length, for the
        # spillback test (methodology from design-arterial-...-bandwidth / diamond)
        import sumolib
        _net = sumolib.net.readNet(sc["net"])
        lane_len = {}
        e2 = os.path.join(outdir, "e2.add.xml")
        rows = ['<additional>']
        for eid, xa, xb, _ in sc["info"]["eb_spans"]:
            if not eid.startswith("AE_J"):
                continue
            for li in range(1, cfg.lanes_art + 1):
                L = _net.getLane(f"{eid}_{li}").getLength()
                lane_len[f"e2_{eid}_{li}"] = L
                rows.append(f'  <laneAreaDetector id="e2_{eid}_{li}" lane="{eid}_{li}" '
                            f'pos="0" endPos="{L - 0.2:.2f}" '
                            f'file="{os.path.abspath(os.path.join(outdir, "e2.xml"))}" '
                            f'period="300" '
                            f'begin="{cfg.warmup}" end="{cfg.demand_end}"/>')
        rows.append('</additional>')
        open(e2, "w").write("\n".join(rows))
        opts[opts.index("-a") + 1] += "," + e2
    if extra_opts:
        opts += list(extra_opts)

    grants = None
    if tsp == "none":
        with open(err, "w") as fe:
            r = subprocess.run([SUMO] + opts, stdout=subprocess.DEVNULL, stderr=fe)
        rc = r.returncode
    else:
        sys.path.insert(0, TSP_SKILL)
        import tsp_controller as TC
        import importlib
        importlib.reload(TC)
        import traci
        sig_ids = [f"J{j}" for j in range(1, cfg.n_signals + 1)]
        params = {"min_green": 10.0, "max_green": 62.0, "ext_threshold": 8.0,
                  "clear_buffer": 2.0, "grant_limit": 1, "recovery_max": 18.0,
                  "agg_min_green": 3.0, "agg_max_green": 70.0}
        log = []
        traci.start([SUMO] + opts, label=f"tsp{os.getpid()}_{abs(hash(outdir))%10**6}")
        try:
            sigs = {t: TC.SignalTSP(traci, t, tsp, cfg.cycle, params, log) for t in sig_ids}
            while (traci.simulation.getMinExpectedNumber() > 0
                   or traci.person.getIDCount() > 0):
                if traci.simulation.getTime() >= cfg.sim_end:
                    break
                traci.simulationStep()
                now = traci.simulation.getTime()
                reqs = TC.collect_requests(traci, sig_ids, 140.0, "bus")
                for t, s in sigs.items():
                    s.step(now, reqs[t])
            grants = {"total": sum(s.total_grants for s in sigs.values()),
                      "ext": sum(s.ext_count for s in sigs.values()),
                      "trunc": sum(s.trunc_count for s in sigs.values()),
                      "blocked": sum(s.blocked_by_limit for s in sigs.values()),
                      "per_signal": {t: s.total_grants for t, s in sigs.items()}}
        finally:
            traci.close()
        open(err, "w").write("")
        rc = 0

    if rc != 0 or not os.path.exists(trip):
        raise RuntimeError(f"sumo failed rc={rc}\n" + open(err).read()[-3000:])

    cars, busv, riders = parse_tripinfo(trip, cfg, cfg.car_occupancy)
    su = parse_summary(summ)
    si = parse_stopinfo(stops, [s["id"] for s in sc["stops"]], sc["n_buses"])
    errtxt = open(err).read() if os.path.exists(err) else ""
    tel_warn = errtxt.count("teleporting")

    car_ph = cars["dur"] * cfg.car_occupancy / 3600.0
    car_dh = cars["loss"] * cfg.car_occupancy / 3600.0
    rid_ph = riders["total"] / 3600.0
    ff_ride = (riders["ride_len"] / cfg.speed_art) if riders["n"] else 0.0
    rid_dh = (riders["total"] - ff_ride - riders["access"] - riders["egress"]) / 3600.0
    # rider delay = wait + (in-vehicle - free-flow in-vehicle); access/egress walk
    # is reported separately (it is a level-of-service cost, not congestion delay)

    m = {
        "cfg": asdict(cfg), "seed": seed, "tsp": tsp,
        "n_cars": cars["n"], "cars_unfinished": cars["n_unfinished"],
        "car_mean_dur": cars["dur"] / max(cars["n"], 1),
        "car_mean_loss": cars["loss"] / max(cars["n"], 1),
        "car_art_mean_loss": cars["loss_art"] / max(cars["n_art"], 1),
        "car_cross_mean_loss": cars["loss_cross"] / max(cars["n_cross"], 1),
        "n_art_cars": cars["n_art"], "n_cross_cars": cars["n_cross"],
        "n_buses_meas": busv["n"], "bus_mean_dur": busv["dur"] / max(busv["n"], 1),
        "bus_mean_loss": busv["loss"] / max(busv["n"], 1),
        "n_riders": riders["n"], "riders_incomplete": riders["n_incomplete"],
        "riders_still_waiting": riders["n_still_waiting"],
        "riders_still_riding": riders["n_still_riding"],
        "rider_mean_access": riders["access"] / max(riders["n"], 1),
        "rider_mean_wait": riders["wait"] / max(riders["n"], 1),
        "rider_mean_inveh": riders["inveh"] / max(riders["n"], 1),
        "rider_mean_egress": riders["egress"] / max(riders["n"], 1),
        "rider_mean_total": riders["total"] / max(riders["n"], 1),
        "rider_mean_access_len": riders["access_len"] / max(riders["n"], 1),
        "rider_mean_egress_len": riders["egress_len"] / max(riders["n"], 1),
        "rider_access_lens": riders["access_lens"],
        "rider_totals": riders["totals"],
        "person_records": riders["records"],
        "n_persons_skipped": sc["n_skipped"],
        "car_person_hours": car_ph, "car_delay_hours": car_dh,
        "rider_person_hours": rid_ph, "rider_delay_hours": rid_dh,
        "total_person_hours": car_ph + rid_ph,
        "total_delay_hours": car_dh + rid_dh,
        "veh_delay_hours": (cars["loss"] + busv["loss"]) / 3600.0,
        "teleports": su["teleports"], "teleport_warnings": tel_warn,
        "max_running": su["max_running"], "final_running": su["final_running"],
        "sim_end_t": su["end_t"],
        "stop_events": si["n_stop_events"], "stop_events_expected": si["expected_stop_events"],
        "missed_stop_services": si["missed_stop_services"],
        "mean_dwell": si["mean_dwell"], "total_dwell": si["total_dwell"],
        "mean_pax_per_stop": si["mean_pax_per_stop"],
        "stop_blocked_time": si["total_blocked"],
        "n_persons_loaded": sc["n_persons"], "n_buses_total": sc["n_buses"],
        "corridor_len_m": sc["info"]["eb_spans"][-1][2] - sc["info"]["eb_spans"][0][1],
        "bus_mean_occupancy": (riders["ride_len"] /
                               max(busv["n"] * (sc["info"]["eb_spans"][-1][2]
                                                - sc["info"]["eb_spans"][0][1]), 1e-9)),
        "n_stops": len(sc["stops"]),
        "reentry_n": len(sc.get("reentry_waits", [])),
        "reentry_mean_wait": (sum(sc["reentry_waits"]) / len(sc["reentry_waits"]))
        if sc.get("reentry_waits") else 0.0,
        "grants": grants,
        "outdir": outdir,
    }
    if e2 is not None and os.path.exists(os.path.join(outdir, "e2.xml")):
        er = ET.parse(os.path.join(outdir, "e2.xml")).getroot()
        jam_iv = []
        for iv in er.findall("interval"):
            if not (cfg.warmup <= float(iv.get("begin")) < cfg.demand_end):
                continue
            jam_iv.append(iv)
        agg = {}
        for iv in jam_iv:
            k = iv.get("id")
            a = agg.setdefault(k, {"maxJ": 0.0, "sumMean": 0.0, "n": 0, "tl": 0.0})
            a["maxJ"] = max(a["maxJ"], float(iv.get("maxJamLengthInMeters", 0)))
            a["sumMean"] += float(iv.get("meanMaxJamLengthInMeters", 0))
            a["tl"] += float(iv.get("meanTimeLoss", 0) or 0)
            a["n"] += 1
        jam = []
        for k, a in agg.items():
            L = lane_len.get(k, cfg.block_len)
            jam.append({"id": k, "lane_len": round(L, 2),
                        "maxJamLengthInMeters": a["maxJ"],
                        "meanMaxJamLengthInMeters": a["sumMean"] / max(a["n"], 1),
                        "storage_ratio": a["maxJ"] / L,
                        "mean_storage_ratio": (a["sumMean"] / max(a["n"], 1)) / L,
                        "meanTimeLoss": a["tl"] / max(a["n"], 1)})
        for iv in []:
            L = lane_len.get(iv.get("id"), cfg.block_len)
            jam.append({"id": iv.get("id"), "lane_len": round(L, 2),
                        "begin": float(iv.get("begin")), "end": float(iv.get("end")),
                        "maxJamLengthInMeters": float(iv.get("maxJamLengthInMeters", 0)),
                        "meanMaxJamLengthInMeters": float(iv.get("meanMaxJamLengthInMeters", 0)),
                        "storage_ratio": float(iv.get("maxJamLengthInMeters", 0)) / L,
                        "mean_storage_ratio": float(iv.get("meanMaxJamLengthInMeters", 0)) / L,
                        "meanTimeLoss": float(iv.get("meanTimeLoss", 0) or 0)})
        m_extra = {"max_jam_m": max((j["maxJamLengthInMeters"] for j in jam), default=0.0),
                   "mean_jam_m": max((j["meanMaxJamLengthInMeters"] for j in jam), default=0.0),
                   "max_mean_storage_ratio": max((j["mean_storage_ratio"] for j in jam), default=0.0),
                   "max_storage_ratio": max((j["storage_ratio"] for j in jam), default=0.0),
                   "n_links_spillback": sum(1 for j in jam if j["storage_ratio"] > 0.95),
                   "e2": jam}
    else:
        m_extra = {}
    m.update(m_extra)
    with open(os.path.join(outdir, "metrics.json"), "w") as f:
        json.dump(m, f, indent=1)
    if "fcd" not in keep and "fcdbus" not in keep:
        for p in glob.glob(os.path.join(outdir, "fcd.xml")):
            os.remove(p)
    return m
