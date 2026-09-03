#!/usr/bin/env python3
"""
Run one experimental arm (one network variant x one demand level x one seed x one
freight configuration) and collect every instrument the study needs:

  tripinfo          per-vehicle travel time / delay, split by vType
  stop-output       per-stop dwell, parking flag, container load/unload counts
  summary           running-vehicle time series + CUMULATIVE teleport count
  edgeData x5       all / truck-only / car-only movement, emissions, harmonoise
  collision-output  collisions
  SUMO log          teleport + emergency-braking warnings

Everything is written under outputs/runs/<arm-id>/.
"""
import os, sys, json, shutil, argparse, math
import xml.etree.ElementTree as ET
from common import *   # noqa
import gen_freight as gf

FREIGHT_VTYPES = "van rigid semi"


def write_meandata(path, begin=0, end=SIM_END, night=None):
    extra = ""
    if night:
        d0, d1, n0, n1 = night
        extra = (f'  <edgeData id="noiseD" file="ed_noise_day.xml"   begin="{d0}" end="{d1}" '
                 f'excludeEmpty="false" type="harmonoise"/>\n'
                 f'  <edgeData id="noiseN" file="ed_noise_night.xml" begin="{n0}" end="{n1}" '
                 f'excludeEmpty="false" type="harmonoise"/>\n'
                 f'  <edgeData id="carD"   file="ed_car_day.xml"   begin="{d0}" end="{d1}" '
                 f'excludeEmpty="false" vTypes="car"/>\n'
                 f'  <edgeData id="carN"   file="ed_car_night.xml" begin="{n0}" end="{n1}" '
                 f'excludeEmpty="false" vTypes="car"/>\n')
    open(path, "w").write(f"""<additional>
{extra}
  <edgeData id="all"   file="ed_all.xml"   begin="{begin}" end="{end}" excludeEmpty="false"/>
  <edgeData id="trk"   file="ed_truck.xml" begin="{begin}" end="{end}" excludeEmpty="false" vTypes="{FREIGHT_VTYPES}"/>
  <edgeData id="car"   file="ed_car.xml"   begin="{begin}" end="{end}" excludeEmpty="false" vTypes="car"/>
  <edgeData id="emi"   file="ed_emi.xml"   begin="{begin}" end="{end}" excludeEmpty="true" type="emissions"/>
  <edgeData id="emit"  file="ed_emi_trk.xml" begin="{begin}" end="{end}" excludeEmpty="true" type="emissions" vTypes="{FREIGHT_VTYPES}"/>
  <edgeData id="noise" file="ed_noise.xml" begin="{begin}" end="{end}" excludeEmpty="false" type="harmonoise"/>
  <edgeData id="hvy"   file="ed_heavy.xml" begin="{begin}" end="{end}" excludeEmpty="false" vTypes="rigid semi"/>
  <edgeData id="vanm"  file="ed_van.xml"   begin="{begin}" end="{end}" excludeEmpty="false" vTypes="van"/>
  <edgeData id="emih"  file="ed_emi_hvy.xml" begin="{begin}" end="{end}" excludeEmpty="true" type="emissions" vTypes="rigid semi"/>
</additional>
""")


def run(arm_id, net_tag, level, seed, freight_rou=None, freight_add=None,
        sim_end=SIM_END, extra_car_files=(), tll=None, overwrite=False, night=None):
    d = os.path.join(RUNS, arm_id)
    done = os.path.join(d, "DONE")
    if os.path.exists(done) and not overwrite:
        return d
    os.makedirs(d, exist_ok=True)
    cidx = json.load(open(os.path.join(DEMAND, "car_index.json")))
    ci = cidx["index"][level][str(seed)]
    netf = os.path.join(NET, "%s.net.xml" % net_tag)

    routes = [ci["arterial"], ci["dispersed"]] + list(extra_car_files)
    if freight_rou:
        routes.append(freight_rou)

    adds = [os.path.join(DEMAND, "vtypes.add.xml")]
    if freight_add:
        adds.append(freight_add)
    if tll is None:
        tll = cidx.get("tll")
    if tll and os.path.exists(tll):
        adds.append(tll)
    md = os.path.join(d, "meandata.add.xml")
    write_meandata(md, 0, sim_end, night=night)
    adds.append(md)

    cmd = [SUMO, "-n", netf, "-r", ",".join(routes), "-a", ",".join(adds),
           "-e", str(sim_end), "--step-length", "1",
           "--tripinfo-output", os.path.join(d, "tripinfo.xml"),
           "--tripinfo-output.write-unfinished", "true",
           "--stop-output", os.path.join(d, "stopinfo.xml"),
           "--summary-output", os.path.join(d, "summary.xml"),
           "--collision-output", os.path.join(d, "collisions.xml"),
           "--device.emissions.probability", "1.0",
           "--time-to-teleport", str(TIME_TO_TELEPORT),
           "--seed", str(seed),
           "--emergencydecel.warning-threshold", "0.7",
           "--no-step-log", "true", "--duration-log.statistics", "true",
           "--ignore-route-errors", "true",
           "--log", os.path.join(d, "sumo.log")]
    r = sh(cmd, cwd=d)
    meta = dict(arm=arm_id, net=net_tag, level=level, seed=seed,
                freight_rou=freight_rou, sim_end=sim_end, returncode=r.returncode,
                stderr_tail=(r.stderr or "")[-3000:])
    json.dump(meta, open(os.path.join(d, "run_meta.json"), "w"), indent=1)
    if r.returncode == 0:
        open(done, "w").write("ok")
    else:
        print("ARM FAILED", arm_id, (r.stderr or "")[-800:])
    return d


# --------------------------------------------------------------- extraction --
def _f(x, dflt=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return dflt


def extract(d, addrs_by_id=None, ledger=None):
    """Parse one run directory into a flat metric dict + per-tour ledger rows."""
    import build_network as bn
    out = {"dir": d}
    arts, locs = set(bn.arterial_edges()), set(bn.local_edges())

    # ---- tripinfo --------------------------------------------------------
    cars = dict(n=0, dur=0.0, loss=0.0, len=0.0, wait=0.0, arrived=0)
    frt = dict(n=0, dur=0.0, loss=0.0, len=0.0, wait=0.0, stop=0.0, arrived=0)
    per_veh = {}
    byvt = {}
    unfinished = dict(car=0, freight=0)
    emis = dict(CO2=0.0, NOx=0.0, PMx=0.0, fuel=0.0)
    emis_frt = dict(CO2=0.0, NOx=0.0, PMx=0.0, fuel=0.0)
    tif = os.path.join(d, "tripinfo.xml")
    container_ids_delivered = set()
    if os.path.exists(tif):
        for el in ET.parse(tif).getroot():
            if el.tag == "containerinfo":
                container_ids_delivered.add(el.get("id"))
                continue
            if el.tag != "tripinfo":
                continue
            vt = el.get("vType")
            arrived = _f(el.get("arrival"), -1) >= 0
            rec = dict(dur=_f(el.get("duration")), loss=_f(el.get("timeLoss")),
                       len=_f(el.get("routeLength")), wait=_f(el.get("waitingTime")),
                       stop=_f(el.get("stopTime")), arrived=arrived, vtype=vt)
            per_veh[el.get("id")] = rec
            byvt.setdefault(vt, dict(n=0, len=0.0, dur=0.0, loss=0.0, stop=0.0, arrived=0))
            b = byvt[vt]
            b["n"] += 1; b["len"] += rec["len"]; b["dur"] += rec["dur"]
            b["loss"] += rec["loss"]; b["stop"] += rec["stop"]; b["arrived"] += int(arrived)
            tgt = cars if vt == "car" else frt
            tgt["n"] += 1
            tgt["arrived"] += int(arrived)
            for k in ("dur", "loss", "len", "wait"):
                tgt[k] += rec[k]
            if vt != "car":
                tgt["stop"] += rec["stop"]
            if not arrived:
                unfinished["car" if vt == "car" else "freight"] += 1
            for ch in el:
                if ch.tag == "emissions":
                    for k, a in (("CO2", "CO2_abs"), ("NOx", "NOx_abs"),
                                 ("PMx", "PMx_abs"), ("fuel", "fuel_abs")):
                        emis[k] += _f(ch.get(a))
                        if vt != "car":
                            emis_frt[k] += _f(ch.get(a))
    out["car_n"] = cars["n"]; out["car_arrived"] = cars["arrived"]
    out["car_unfinished"] = unfinished["car"]
    out["car_mean_timeloss"] = cars["loss"] / max(1, cars["n"])
    out["car_total_timeloss_h"] = cars["loss"] / 3600.0
    out["car_mean_duration"] = cars["dur"] / max(1, cars["n"])
    out["car_vkt_km"] = cars["len"] / 1000.0
    out["frt_n"] = frt["n"]; out["frt_arrived"] = frt["arrived"]
    out["frt_unfinished"] = unfinished["freight"]
    out["frt_vkt_km"] = frt["len"] / 1000.0
    out["frt_total_timeloss_h"] = frt["loss"] / 3600.0
    out["frt_total_stop_h"] = frt["stop"] / 3600.0
    out["frt_total_duration_h"] = frt["dur"] / 3600.0
    for vt, b in byvt.items():
        out["n_%s" % vt] = b["n"]
        out["vkt_km_%s" % vt] = b["len"] / 1000.0
        out["dur_h_%s" % vt] = b["dur"] / 3600.0
        out["arrived_%s" % vt] = b["arrived"]
    for k in emis:
        out["emis_%s_kg" % k] = emis[k] / 1e6
        out["emis_frt_%s_kg" % k] = emis_frt[k] / 1e6

    # ---- edgeData: truck presence, VKT by facility -----------------------
    def read_ed(fn, attrs=("sampledSeconds",)):
        p = os.path.join(d, fn)
        res = {}
        if not os.path.exists(p):
            return res
        for iv in ET.parse(p).getroot():
            for e in iv:
                res[e.get("id")] = {a: _f(e.get(a)) for a in attrs}
                res[e.get("id")]["_raw"] = dict(e.attrib)
        return res

    import sumolib
    net = sumolib.net.readNet(os.path.join(NET, os.path.basename(
        json.load(open(os.path.join(d, "run_meta.json")))["net"]) + ".net.xml"))
    elen = {e.getID(): e.getLength() for e in net.getEdges() if not e.getID().startswith(":")}

    ed_trk = read_ed("ed_truck.xml", ("sampledSeconds", "speed", "left", "arrived", "departed"))
    trk_vkm = {}
    for eid_, v in ed_trk.items():
        if eid_ not in elen:
            continue
        # veh-km on the edge = sampledSeconds * meanSpeed  (m) -> km
        trk_vkm[eid_] = v["sampledSeconds"] * v.get("speed", 0.0) / 1000.0
    out["trk_vkm_local"] = sum(v for k, v in trk_vkm.items() if k in locs)
    out["trk_vkm_arterial"] = sum(v for k, v in trk_vkm.items() if k in arts)
    out["trk_vkm_total"] = sum(trk_vkm.values())
    out["trk_edgesecs_local"] = sum(v["sampledSeconds"] for k, v in ed_trk.items() if k in locs)
    out["trk_edgesecs_arterial"] = sum(v["sampledSeconds"] for k, v in ed_trk.items() if k in arts)
    out["_trk_vkm_by_edge"] = trk_vkm
    for lab, fn in (("hvy", "ed_heavy.xml"), ("van", "ed_van.xml")):
        e2 = read_ed(fn, ("sampledSeconds", "speed"))
        vkm = {k: v["sampledSeconds"] * v.get("speed", 0.0) / 1000.0
               for k, v in e2.items() if k in elen}
        out["%s_vkm_local" % lab] = sum(v for k, v in vkm.items() if k in locs)
        out["%s_vkm_arterial" % lab] = sum(v for k, v in vkm.items() if k in arts)
        out["%s_vkm_total" % lab] = sum(vkm.values())
        out["%s_edgesecs_local" % lab] = sum(v["sampledSeconds"] for k, v in e2.items() if k in locs)
        if lab == "hvy":
            out["_hvy_vkm_by_edge"] = vkm
    e3 = read_ed("ed_emi_hvy.xml", ("CO2_abs", "NOx_abs", "PMx_abs"))
    out["edge_hvyCO2_kg_local"] = sum(v["CO2_abs"] for k, v in e3.items() if k in locs) / 1e6
    out["edge_hvyNOx_kg_local"] = sum(v["NOx_abs"] for k, v in e3.items() if k in locs) / 1e6
    out["edge_hvyCO2_kg_total"] = sum(v["CO2_abs"] for v in e3.values()) / 1e6

    ed_car = read_ed("ed_car.xml", ("sampledSeconds", "speed", "timeLoss", "waitingTime"))
    out["car_edge_timeloss_h_local"] = sum(v["_raw"].get("timeLoss") and _f(v["_raw"]["timeLoss"]) or 0.0
                                           for k, v in ed_car.items() if k in locs) / 3600.0
    out["car_edge_timeloss_h_arterial"] = sum(_f(v["_raw"].get("timeLoss")) for k, v in ed_car.items()
                                              if k in arts) / 3600.0

    # ---- harmonoise ------------------------------------------------------
    ed_n = read_ed("ed_noise.xml", ("noise", "sampledSeconds"))
    def energy_mean(keys):
        vals = [ed_n[k]["noise"] for k in keys if k in ed_n and ed_n[k]["noise"] > 0]
        if not vals:
            return 0.0
        return 10.0 * math.log10(sum(10 ** (v / 10.0) for v in vals) / len(vals))
    out["noise_local_dB"] = energy_mean(locs)
    out["noise_arterial_dB"] = energy_mean(arts)
    # residential noise EXPOSURE: energy-summed over local edges, length-weighted
    tot = 0.0
    for k in locs:
        if k in ed_n and ed_n[k]["noise"] > 0:
            tot += (10 ** (ed_n[k]["noise"] / 10.0)) * elen.get(k, 0.0)
    out["noise_exposure_local"] = 10 * math.log10(tot) if tot > 0 else 0.0
    out["_noise_by_edge"] = {k: v["noise"] for k, v in ed_n.items()}
    for lab, fn in (("day", "ed_noise_day.xml"), ("night", "ed_noise_night.xml")):
        e2 = read_ed(fn, ("noise", "sampledSeconds"))
        if not e2:
            continue
        vals = [e2[k]["noise"] for k in locs if k in e2 and e2[k]["noise"] > 0]
        out["noise_local_%s_dB" % lab] = (10 * math.log10(sum(10 ** (v / 10.0) for v in vals) / len(vals))
                                          if vals else 0.0)
        tot2 = sum((10 ** (e2[k]["noise"] / 10.0)) * elen.get(k, 0.0)
                   for k in locs if k in e2 and e2[k]["noise"] > 0)
        out["noise_exposure_local_%s" % lab] = 10 * math.log10(tot2) if tot2 > 0 else 0.0
    if "noise_local_day_dB" in out and "noise_local_night_dB" in out:
        # Lden-style night penalty: night noise weighted +10 dB(A)
        _iday = 10 ** (out["noise_local_day_dB"] / 10.0)
        _inight = 10 ** ((out["noise_local_night_dB"] + 10.0) / 10.0)
        out["noise_local_night_weighted_dB"] = 10 * math.log10((_iday + _inight) / 2.0)

    # ---- edge emissions --------------------------------------------------
    ed_e = read_ed("ed_emi.xml", ("CO2_abs", "NOx_abs", "PMx_abs"))
    out["edge_CO2_kg_local"] = sum(v["CO2_abs"] for k, v in ed_e.items() if k in locs) / 1e6
    out["edge_CO2_kg_total"] = sum(v["CO2_abs"] for v in ed_e.values()) / 1e6
    ed_et = read_ed("ed_emi_trk.xml", ("CO2_abs", "NOx_abs", "PMx_abs"))
    out["edge_frtCO2_kg_local"] = sum(v["CO2_abs"] for k, v in ed_et.items() if k in locs) / 1e6
    out["edge_frtNOx_kg_local"] = sum(v["NOx_abs"] for k, v in ed_et.items() if k in locs) / 1e6
    out["edge_frtPMx_kg_local"] = sum(v["PMx_abs"] for k, v in ed_et.items() if k in locs) / 1e6

    # ---- summary: teleports (CUMULATIVE -> read the LAST value) ----------
    sm = os.path.join(d, "summary.xml")
    tel, maxrun, lastrun = 0, 0, 0
    series = []
    if os.path.exists(sm):
        for st in ET.parse(sm).getroot():
            tel = int(_f(st.get("teleports")))
            run_ = int(_f(st.get("running")))
            maxrun = max(maxrun, run_)
            lastrun = run_
            series.append((_f(st.get("time")), run_, int(_f(st.get("ended")))))
    out["teleports"] = tel
    out["max_running"] = maxrun
    out["running_at_end"] = lastrun
    out["_running_series"] = series[::30]

    # ---- collisions / emergency braking ----------------------------------
    cf = os.path.join(d, "collisions.xml")
    out["collisions"] = 0
    if os.path.exists(cf):
        try:
            out["collisions"] = len(list(ET.parse(cf).getroot()))
        except ET.ParseError:
            out["collisions"] = -1
    lg = os.path.join(d, "sumo.log")
    out["emergency_braking"] = 0
    out["teleport_warnings"] = 0
    if os.path.exists(lg):
        txt = open(lg, errors="replace").read()
        out["emergency_braking"] = txt.count("emergency braking")
        out["teleport_warnings"] = txt.count("teleporting")

    # ---- stop-output: container ledger + dwell/blocking ------------------
    sf = os.path.join(d, "stopinfo.xml")
    stops = []
    if os.path.exists(sf):
        for s in ET.parse(sf).getroot():
            stops.append(dict(veh=s.get("id"), vtype=s.get("type"), lane=s.get("lane"),
                              cs=s.get("containerStop"), parking=s.get("parking"),
                              started=_f(s.get("started")), ended=_f(s.get("ended")),
                              loaded=int(_f(s.get("loadedContainers"))),
                              unloaded=int(_f(s.get("unloadedContainers"))),
                              initial=int(_f(s.get("initialContainers")))))
    out["n_stops_executed"] = len(stops)
    out["n_delivery_stops_executed"] = sum(1 for s in stops if s["cs"] and s["cs"].startswith("cs_"))
    out["containers_loaded"] = sum(s["loaded"] for s in stops)
    out["containers_unloaded"] = sum(s["unloaded"] for s in stops)
    out["blocking_stop_seconds"] = sum((s["ended"] - s["started"]) for s in stops
                                       if s["parking"] == "0" and s["cs"] and s["cs"].startswith("cs_"))
    out["bay_stop_seconds"] = sum((s["ended"] - s["started"]) for s in stops
                                  if s["parking"] == "1" and s["cs"] and s["cs"].startswith("cs_"))
    out["n_blocking_stops"] = sum(1 for s in stops if s["parking"] == "0" and s["cs"]
                                  and s["cs"].startswith("cs_"))
    out["_stops"] = stops

    # ---- ledger reconciliation ------------------------------------------
    if ledger:
        offered = ledger["n_containers_offered"]
        out["containers_offered"] = offered
        out["containers_delivered_tripinfo"] = len(container_ids_delivered)
        out["parcels_by_design"] = ledger["parcels_offered_by_design"]
        out["addresses_unservable"] = len(ledger["unservable"])
        out["parcels_unservable"] = sum(u["parcels"] for u in ledger["unservable"])
        out["tours_planned"] = len(ledger["tours"])
        out["tours_emitted"] = ledger["n_vehicles_emitted"]
        out["tours_not_emitted"] = sum(1 for t in ledger["tours"] if not t["emitted"])
        exec_by_veh = {}
        for s in stops:
            if s["cs"] and s["cs"].startswith("cs_"):
                exec_by_veh.setdefault(s["veh"], []).append(s)
        rows = []
        for t in ledger["tours"]:
            if not t["emitted"]:
                rows.append(dict(tour=t["id"], vtype=t["vtype"], emitted=False,
                                 reason=t.get("reason"), planned_stops=len(t.get("addrs", [])),
                                 planned_parcels=t.get("planned_parcels", 0),
                                 stops_done=0, parcels_delivered=0, completed=False,
                                 drive_h=0.0, dwell_h=0.0, delay_h=0.0, vkt_km=0.0))
                continue
            ex = exec_by_veh.get(t["id"], [])
            pv = per_veh.get(t["id"], {})
            dwell = sum(s["ended"] - s["started"] for s in ex)
            rows.append(dict(tour=t["id"], vtype=t["vtype"], emitted=True, reason=None,
                             planned_stops=len(t["addrs"]),
                             planned_parcels=t["parcels"],
                             stops_done=len(ex),
                             parcels_delivered=sum(s["unloaded"] for s in ex),
                             completed=bool(pv.get("arrived", False)),
                             drive_h=max(0.0, (pv.get("dur", 0.0) - pv.get("stop", 0.0))) / 3600.0,
                             dwell_h=pv.get("stop", 0.0) / 3600.0,
                             delay_h=pv.get("loss", 0.0) / 3600.0,
                             vkt_km=pv.get("len", 0.0) / 1000.0,
                             night=t.get("night", False),
                             n_bays=t.get("n_bays", 0)))
        out["_tour_rows"] = rows
        out["tours_completed"] = sum(1 for r in rows if r["completed"])
        out["tours_still_running"] = sum(1 for r in rows if r["emitted"] and not r["completed"])
        out["parcels_delivered"] = sum(r["parcels_delivered"] for r in rows)
        out["parcels_undelivered"] = out["parcels_by_design"] - out["parcels_delivered"]
        out["stops_executed_ledger"] = sum(r["stops_done"] for r in rows)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()
    if a.test:
        import time
        addrs = json.load(open(os.path.join(DEMAND, "addresses.json")))
        lg = gf.generate(os.path.join(NET, "d_strict_0.net.xml"), addrs,
                         os.path.join(DEMAND, "t_stops.add.xml"),
                         os.path.join(DEMAND, "t_frt.rou.xml"), seed=1,
                         ledger_path=os.path.join(DEMAND, "t_ledger.json"))
        t0 = time.time()
        d = run("TEST_mid", "d_strict_0", "mid", 1,
                os.path.join(DEMAND, "t_frt.rou.xml"),
                os.path.join(DEMAND, "t_stops.add.xml"), overwrite=True)
        print("runtime %.1f s" % (time.time() - t0))
        m = extract(d, ledger=lg)
        for k, v in sorted(m.items()):
            if not k.startswith("_"):
                print("  %-32s %s" % (k, v))
