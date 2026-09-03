#!/usr/bin/env python3
"""Reduce one run directory to a metrics dict (all numbers derived from raw XML)."""
import os, json, math, statistics, collections
import xml.etree.ElementTree as ET
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from battery_reduce import reduce_battery, cs_totals
import scenario as SC

RESERVE = 0.20          # feasibility reserve state of charge
LATE_TOL = 60.0         # s: a departure later than schedule+tol counts as "missed"


def _f(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def stop_events(rundir):
    rows = []
    for s in ET.parse(os.path.join(rundir, "stopinfo.xml")).getroot():
        if not s.get("id", "").startswith("bus_"):
            continue
        rows.append(dict(veh=s.get("id"), stop=s.get("busStop", ""),
                         started=_f(s.get("started")), ended=_f(s.get("ended")),
                         arrival=_f(s.get("arrivalPos")),
                         loaded=int(s.get("loadedPersons", 0)),
                         unloaded=int(s.get("unloadedPersons", 0)),
                         delay=_f(s.get("delay"), 0.0)))
    rows.sort(key=lambda r: (r["veh"], r["started"]))
    return rows


def schedule_metrics(rundir, cell):
    """Terminal schedule adherence + en-route headway regularity, from stop-output."""
    sched = cell["sched"]                     # "b|c|E"/"b|c|W" -> scheduled departure
    ev = stop_events(rundir)
    byveh = collections.defaultdict(list)
    for r in ev:
        byveh[r["veh"]].append(r)
    term_rows = []
    for veh, rows in byveh.items():
        b = int(veh.split("_")[1])
        ci = {"E": 0, "W": 0}
        for r in rows:
            if r["stop"].startswith("bs_TE_"):
                side = "E"
            elif r["stop"].startswith("bs_TW_"):
                side = "W"
            else:
                continue
            c = ci[side]; ci[side] += 1
            key = f"{b}|{c}|{side}"
            sd = sched.get(key)
            if sd is None:
                continue
            term_rows.append(dict(veh=veh, bus=b, cycle=c, side=side, stop=r["stop"],
                                  arr=r["started"], dep=r["ended"], sched_dep=sd,
                                  dwell=r["ended"] - r["started"],
                                  dep_dev=r["ended"] - sd,
                                  slack=sd - r["started"]))
    late = [t for t in term_rows if t["dep_dev"] > LATE_TOL]
    # en-route headway CV at each stop (successive bus arrivals at the same stop)
    hw = collections.defaultdict(list)
    per_stop = collections.defaultdict(list)
    for r in ev:
        if r["stop"].startswith("bs_EB_") or r["stop"].startswith("bs_WB_"):
            per_stop[r["stop"]].append(r["started"])
    cvs = {}
    for sid, ts in per_stop.items():
        ts = sorted(ts)
        h = [b - a for a, b in zip(ts, ts[1:])]
        h = [x for x in h if 0 < x < 3 * SC.HEADWAY]      # drop cycle-boundary gaps
        if len(h) >= 5:
            cvs[sid] = statistics.pstdev(h) / statistics.mean(h)
            hw[sid] = h
    allh = [x for v in hw.values() for x in v]
    return dict(
        terminal_events=term_rows,
        n_terminal_events=len(term_rows),
        mean_dep_dev_s=round(statistics.mean([t["dep_dev"] for t in term_rows]), 2) if term_rows else None,
        p90_dep_dev_s=round(sorted(t["dep_dev"] for t in term_rows)[int(0.9 * (len(term_rows) - 1))], 2) if term_rows else None,
        max_dep_dev_s=round(max((t["dep_dev"] for t in term_rows), default=0), 2),
        n_missed_departures=len(late),
        mean_terminal_dwell_s=round(statistics.mean([t["dwell"] for t in term_rows]), 2) if term_rows else None,
        headway_cv_pooled=round(statistics.pstdev(allh) / statistics.mean(allh), 4) if len(allh) > 5 else None,
        headway_mean_s=round(statistics.mean(allh), 2) if allh else None,
        headway_cv_by_stop={k: round(v, 4) for k, v in sorted(cvs.items())},
    )


def validity(rundir, cell):
    err = open(os.path.join(rundir, "sumo_stderr.txt")).read()
    tel = err.count("Teleporting vehicle")
    tel_bus = err.count("Teleporting vehicle 'bus_")
    skipped = err.count("skips stop")
    depleted = err.count("is depleted")
    ti = ET.parse(os.path.join(rundir, "tripinfo.xml")).getroot()
    buses = [t for t in ti if t.tag == "tripinfo" and t.get("id", "").startswith("bus_")]
    cars = [t for t in ti if t.tag == "tripinfo" and t.get("vType") == "car"]
    pers = [t for t in ti if t.tag == "personinfo"]
    unfinished = [t for t in ti if t.tag == "tripinfo" and _f(t.get("arrival"), -1) < 0]
    ev = stop_events(rundir)
    per_bus_stops = collections.Counter(r["veh"] for r in ev)
    nbus, ncyc, stride = cell["cfg"]["nbus"], cell["cfg"]["ncyc"], cell["cfg"]["stop_stride"]
    expected = ncyc * (2 * len(range(0, 12, stride)) + 2)
    complete = sum(1 for b in range(nbus) if per_bus_stops.get(f"bus_{b}", 0) == expected)
    car_dur = [_f(t.get("duration")) for t in cars if _f(t.get("arrival"), -1) >= 0]
    car_tl = [_f(t.get("timeLoss")) for t in cars if _f(t.get("arrival"), -1) >= 0]
    ride_wait, ride_dur, n_rides = [], [], 0
    n_ride_missing = 0
    for p in pers:
        st = list(p)
        rides = [s for s in st if s.tag == "ride"]
        if not rides:
            n_ride_missing += 1
        for s in rides:
            n_rides += 1
            ride_wait.append(_f(s.get("waitingTime")))
            ride_dur.append(_f(s.get("duration")))
    return dict(
        teleports_total=tel, teleports_bus=tel_bus, stops_skipped=skipped,
        battery_depleted_warnings=depleted,
        n_bus_tripinfo=len(buses), n_car_tripinfo=len(cars), n_personinfo=len(pers),
        n_unfinished_vehicles=len(unfinished),
        expected_stops_per_bus=expected,
        buses_completing_full_block=complete, n_buses=nbus,
        bus_stop_counts={k: v for k, v in sorted(per_bus_stops.items())},
        car_mean_duration_s=round(statistics.mean(car_dur), 2) if car_dur else None,
        car_mean_timeloss_s=round(statistics.mean(car_tl), 2) if car_tl else None,
        n_cars_completed=len(car_dur),
        n_rides=n_rides, n_persons_without_ride=n_ride_missing,
        ride_mean_wait_s=round(statistics.mean(ride_wait), 2) if ride_wait else None,
        ride_mean_duration_s=round(statistics.mean(ride_dur), 2) if ride_dur else None,
    )


def energy_metrics(rundir, cell, keep_traces=False):
    cfg = cell["cfg"]
    bat = reduce_battery(os.path.join(rundir, "battery.xml"), aux_w=cfg["aux_w"])
    cst, sessions = cs_totals(os.path.join(rundir, "chargingstations.xml"))
    cap_wh = cfg["cap_kwh"] * 1000.0
    out = {}
    per_bus = {}
    for vid, v in bat.items():
        d_tot = sum(v["dist_m"].values()) / 1000.0
        net = v["total_consumed_wh"] - v["total_regen_wh"]
        soc_min_wh = min(x[1] for x in v["trace"])
        # unclamped ("virtual") SOC trajectory reconstructed from cumulative counters
        virt = [(t, v["cap0_wh"] - tc + tr + cc) for (t, cap, tc, tr, cc, cs) in v["trace"]]
        vmin = min(x[1] for x in virt)
        per_bus[vid] = dict(
            dist_km=round(d_tot, 3),
            dist_EB_km=round(v["dist_m"]["EB"] / 1000.0, 3),
            dist_WB_km=round(v["dist_m"]["WB"] / 1000.0, 3),
            gross_consumed_kwh=round(v["total_consumed_wh"] / 1000.0, 3),
            regen_kwh=round(v["total_regen_wh"] / 1000.0, 3),
            net_energy_kwh=round(net / 1000.0, 3),
            aux_kwh=round(v["aux_energy_wh"] / 1000.0, 3),
            traction_gross_kwh=round((v["total_consumed_wh"] - v["aux_energy_wh"]) / 1000.0, 3),
            charged_kwh=round(v["credited_charge_wh"] / 1000.0, 3),
            uncredited_charge_kwh=round(v["uncredited_charge_wh"] / 1000.0, 4),
            balance_residual_wh=v["balance_residual_wh"],
            kwh_per_km=round(net / 1000.0 / d_tot, 4) if d_tot else None,
            kwh_per_km_EB=round((v["cons_wh"]["EB"] - v["regen_wh"]["EB"]) / 1000.0 /
                                (v["dist_m"]["EB"] / 1000.0), 4) if v["dist_m"]["EB"] else None,
            kwh_per_km_WB=round((v["cons_wh"]["WB"] - v["regen_wh"]["WB"]) / 1000.0 /
                                (v["dist_m"]["WB"] / 1000.0), 4) if v["dist_m"]["WB"] else None,
            time_total_s=round(sum(v["time_s"].values()), 1),
            move_time_s=v["move_time_s"], stop_time_s=v["stop_time_s"],
            soc_start=round(v["cap0_wh"] / cap_wh, 4),
            soc_end=round(v["final_cap_wh"] / cap_wh, 4),
            soc_min=round(soc_min_wh / cap_wh, 4),
            soc_min_virtual=round(vmin / cap_wh, 4),
            soc_min_time=[t for t, s in virt if s == vmin][0],
            steps_soc_zero=v["n_steps_soc_zero"],
            first_zero_t=v["first_zero_t"],
            stations_used=v["charging_stations_used"],
        )
        if keep_traces:
            per_bus[vid]["trace"] = v["trace"]
            per_bus[vid]["virtual_trace"] = [(t, round(s, 1)) for t, s in virt]
    socmins = [b["soc_min_virtual"] for b in per_bus.values()]
    kwhkm = [b["kwh_per_km"] for b in per_bus.values()]
    out["per_bus"] = per_bus
    out["fleet"] = dict(
        n_buses=len(per_bus),
        dist_km=round(sum(b["dist_km"] for b in per_bus.values()), 2),
        gross_consumed_kwh=round(sum(b["gross_consumed_kwh"] for b in per_bus.values()), 2),
        regen_kwh=round(sum(b["regen_kwh"] for b in per_bus.values()), 2),
        net_energy_kwh=round(sum(b["net_energy_kwh"] for b in per_bus.values()), 2),
        aux_kwh=round(sum(b["aux_kwh"] for b in per_bus.values()), 2),
        traction_gross_kwh=round(sum(b["traction_gross_kwh"] for b in per_bus.values()), 2),
        charged_kwh=round(sum(b["charged_kwh"] for b in per_bus.values()), 2),
        max_balance_residual_wh=round(max(abs(b["balance_residual_wh"]) for b in per_bus.values()), 4),
        mean_kwh_per_km=round(statistics.mean(kwhkm), 4),
        mean_kwh_per_km_EB=round(statistics.mean(b["kwh_per_km_EB"] for b in per_bus.values()), 4),
        mean_kwh_per_km_WB=round(statistics.mean(b["kwh_per_km_WB"] for b in per_bus.values()), 4),
        regen_share_of_gross=round(sum(b["regen_kwh"] for b in per_bus.values()) /
                                   sum(b["gross_consumed_kwh"] for b in per_bus.values()), 4),
        aux_share_of_net=round(sum(b["aux_kwh"] for b in per_bus.values()) /
                               sum(b["net_energy_kwh"] for b in per_bus.values()), 4),
        min_soc_over_fleet=round(min(socmins), 4),
        n_buses_below_reserve=sum(1 for s in socmins if s < RESERVE),
        n_buses_depleted=sum(1 for b in per_bus.values() if b["steps_soc_zero"] > 0),
        feasible=bool(min(socmins) >= RESERVE),
    )
    out["charging_stations"] = cst
    out["n_sessions"] = len(sessions)
    out["sessions"] = sessions
    # cross-check: chargingstations-output total vs credited battery charge
    cs_sum = sum(v["total_wh"] for v in cst.values())
    bat_sum = sum(b["charged_kwh"] * 1000.0 for b in per_bus.values())
    out["charge_ledger_check"] = dict(
        chargingstations_output_wh=round(cs_sum, 2),
        battery_credited_wh=round(bat_sum, 2),
        diff_wh=round(cs_sum - bat_sum, 2),
        battery_reported_wh=round(sum(b["charged_kwh"] * 1000 + b["uncredited_charge_kwh"] * 1000
                                      for b in per_bus.values()), 2),
    )
    return out


def charger_contention(rundir, cell):
    """Occupancy conflicts at the terminal berths, from stop-output + cs sessions."""
    ev = stop_events(rundir)
    berths = collections.defaultdict(list)
    for r in ev:
        if r["stop"].startswith("bs_TE_") or r["stop"].startswith("bs_TW_"):
            berths[r["stop"]].append((r["started"], r["ended"], r["veh"]))
    occ = {}
    conflicts = 0
    for sid, iv in berths.items():
        iv.sort()
        busy = sum(e - s for s, e, _ in iv)
        ov = 0
        for i in range(1, len(iv)):
            if iv[i][0] < iv[i - 1][1]:
                ov += 1
        conflicts += ov
        occ[sid] = dict(n_uses=len(iv), busy_s=round(busy, 1),
                        utilisation=round(busy / (SC.SIM_END - SC.T0), 4),
                        overlaps=ov)
    # which pull-ins actually received charge?
    _, sessions = cs_totals(os.path.join(rundir, "chargingstations.xml"))
    # a single pull-in can be split into several chargingstations-output sessions;
    # collapse sessions that belong to the same berth visit
    pullin_windows = [(r["veh"], r["started"], r["ended"]) for r in ev if r["stop"].startswith("bs_T")]
    charged_pullin_keys = set()
    for s in sessions:
        for veh, a, b in pullin_windows:
            if veh == s["veh"] and a - 5 <= s["begin"] <= b + 5:
                charged_pullin_keys.add((veh, a))
                break
    charged_pullins = collections.Counter(v for v, _ in charged_pullin_keys)
    n_term_pullins = sum(1 for r in ev if r["stop"].startswith("bs_T"))
    return dict(berth_occupancy=occ, berth_overlaps=conflicts,
                n_terminal_pullins=n_term_pullins,
                n_charge_sessions=len(sessions),
                charge_sessions_per_bus=dict(charged_pullins),
                n_pullins_charged=len(charged_pullin_keys),
                frac_pullins_charged=round(len(charged_pullin_keys) / n_term_pullins, 4) if n_term_pullins else None)


def run_metrics(rundir, keep_traces=False):
    cell = json.load(open(os.path.join(rundir, "cell.json")))
    m = dict(cfg=cell["cfg"])
    m["validity"] = validity(rundir, cell)
    m["energy"] = energy_metrics(rundir, cell, keep_traces=keep_traces)
    sch = schedule_metrics(rundir, cell)
    if not keep_traces:
        sch.pop("terminal_events")
    m["schedule"] = sch
    m["contention"] = charger_contention(rundir, cell)
    if not keep_traces:
        m["energy"].pop("sessions", None)
    return m


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("rundir")
    ap.add_argument("--traces", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    m = run_metrics(a.rundir, keep_traces=a.traces)
    if a.out:
        json.dump(m, open(a.out, "w"), indent=1)
    slim = {k: v for k, v in m.items()}
    slim["energy"] = {k: v for k, v in m["energy"].items() if k not in ("per_bus", "sessions")}
    slim["schedule"] = {k: v for k, v in m["schedule"].items() if k != "terminal_events"}
    print(json.dumps(slim, indent=1)[:6000])
