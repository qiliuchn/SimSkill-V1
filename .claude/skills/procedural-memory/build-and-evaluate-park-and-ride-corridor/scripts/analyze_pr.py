#!/usr/bin/env python3
"""Analyse a park-and-ride corridor run.

Reads <personinfo> from tripinfo.xml and classifies every traveller, then
decomposes door-to-door time into drive / walk-access / wait / ride / egress.
Also reads edgeData for corridor link volumes and delay, and traci_metrics.json
for lot occupancy.
"""
import argparse
import json
import os
import xml.etree.ElementTree as ET

CBD_GATE = ["A2_CBD01", "CBD01_CBD11", "CBD01_CBD02", "CBD01_CBD00"]
ARTERIAL = ["ST_A0", "A0_A1", "A1_A2", "A2_CBD01"]


def f(e, k, d=0.0):
    v = e.get(k)
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def classify(pi):
    legs = list(pi)
    car = [l for l in legs if l.tag == "ride" and not (l.get("vehicle") or "").startswith("BRT")]
    pt = [l for l in legs if l.tag == "ride" and (l.get("vehicle") or "").startswith("BRT")]
    if car and pt:
        mode = "park_and_ride"
    elif car:
        mode = "drive_alone"
    elif pt:
        mode = "walk_transit"
    else:
        mode = "walk_only"
    # decomposition
    first_pt = legs.index(pt[0]) if pt else len(legs)
    last_pt = legs.index(pt[-1]) if pt else -1
    drive = sum(f(l, "duration") for l in car)
    ride = sum(f(l, "duration") for l in pt)
    wait = sum(f(l, "waitingTime") for l in pt)
    access = sum(f(l, "duration") for i, l in enumerate(legs)
                 if l.tag in ("walk", "access") and i < first_pt)
    egress = sum(f(l, "duration") for i, l in enumerate(legs)
                 if l.tag in ("walk", "access") and i > last_pt)
    if not pt:  # no PT leg: all walking is egress-side of the car leg
        access, egress = 0.0, sum(f(l, "duration") for l in legs if l.tag in ("walk", "access"))
    total = f(pi, "duration", -1.0)
    dead = [l for l in pt if (l.get("vehicle") or "") == "NULL"]
    return {"id": pi.get("id"), "mode": mode, "depart": f(pi, "depart"),
            "complete": total > 0, "no_vehicle_ride": len(dead) > 0,
            "total": total, "drive": drive, "access": access,
            "wait": wait, "ride": ride, "egress": egress,
            "carveh": car[0].get("vehicle") if car else None,
            "n_legs": len(legs)}


def read_persons(tripinfo):
    root = ET.parse(tripinfo).getroot()
    return [classify(e) for e in root if e.tag == "personinfo"]


def read_edgedata(path, edges):
    """Return {edge: {volume, traveltime, timeLoss, density}} summed/averaged over intervals."""
    if not os.path.exists(path):
        return {}
    out = {}
    for iv in ET.parse(path).getroot().iter("interval"):
        for e in iv.iter("edge"):
            eid = e.get("id")
            if edges and eid not in edges:
                continue
            d = out.setdefault(eid, {"entered": 0.0, "sampledSeconds": 0.0,
                                     "timeLoss": 0.0, "tt_wsum": 0.0, "tt_w": 0.0})
            d["entered"] += f(e, "entered")
            d["sampledSeconds"] += f(e, "sampledSeconds")
            d["timeLoss"] += f(e, "timeLoss")
            n = f(e, "entered")
            d["tt_wsum"] += f(e, "traveltime") * n
            d["tt_w"] += n
    for eid, d in out.items():
        d["traveltime_mean"] = d["tt_wsum"] / d["tt_w"] if d["tt_w"] else 0.0
    return out


def summarize(persons, end_time=25000.0):
    done = [p for p in persons if p["complete"]]
    undone = [p for p in persons if not p["complete"]]
    modes = {}
    for p in done:
        m = modes.setdefault(p["mode"], [])
        m.append(p)
    n = len(done)
    rows = []
    for m, ps in sorted(modes.items()):
        k = len(ps)
        rows.append({"mode": m, "n": k, "share": k / n if n else 0,
                     "mean_total_s": sum(x["total"] for x in ps) / k,
                     "mean_drive_s": sum(x["drive"] for x in ps) / k,
                     "mean_access_s": sum(x["access"] for x in ps) / k,
                     "mean_wait_s": sum(x["wait"] for x in ps) / k,
                     "mean_ride_s": sum(x["ride"] for x in ps) / k,
                     "mean_egress_s": sum(x["egress"] for x in ps) / k})
    # person-hours: completed persons contribute their duration; never-arriving
    # persons contribute (sim end - depart), a LOWER BOUND on their real cost.
    ph_done = sum(p["total"] for p in done) / 3600.0
    ph_undone = sum(max(0.0, end_time - p["depart"]) for p in undone) / 3600.0
    return {"n_persons": len(persons), "n_completed": n, "n_never_arrived": len(undone),
            "never_arrived_modes": {m: sum(1 for p in undone if p["mode"] == m)
                                    for m in set(p["mode"] for p in undone)},
            "n_no_vehicle_ride": sum(1 for p in persons if p["no_vehicle_ride"]),
            "by_mode": rows,
            "person_hours_completed": ph_done,
            "person_hours_total_lb": ph_done + ph_undone,
            "mean_total_s": sum(p["total"] for p in done) / n if n else 0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    d = a.run_dir
    persons = read_persons(os.path.join(d, "tripinfo.xml"))
    tmp = os.path.join(d, "traci_metrics.json")
    et = json.load(open(tmp))["end_time"] if os.path.exists(tmp) else 25000.0
    res = summarize(persons, et)
    res["label"] = a.label
    res["arterial"] = read_edgedata(os.path.join(d, "edgedata.xml"), set(ARTERIAL))
    res["cbd_gate"] = read_edgedata(os.path.join(d, "edgedata.xml"), set(CBD_GATE))
    tm = os.path.join(d, "traci_metrics.json")
    if os.path.exists(tm):
        m = json.load(open(tm))
        res["teleports"] = m["teleports"]
        res["peak_occupancy"] = m["peak_occupancy"]
        res["lot_counts"] = m["lot_counts"]
        res["stranded_persons_n"] = m["stranded_persons_n"]
        res["occupancy_series"] = {"t": m["sample_times"], "occ": m["occupancy"]}
    with open(a.out, "w") as fh:
        json.dump({"persons": persons, "summary": res}, fh)
    pr = {r["mode"]: r for r in res["by_mode"]}
    print("[%s] n=%d completed=%d never_arrived=%d(noVeh=%d)  PH_done=%.1f PH_lb=%.1f  mean=%.0fs  teleports=%s"
          % (a.label, res["n_persons"], res["n_completed"], res["n_never_arrived"],
             res["n_no_vehicle_ride"], res["person_hours_completed"],
             res["person_hours_total_lb"], res["mean_total_s"], res.get("teleports")))
    if res["n_never_arrived"]:
        print("   never-arrived by attempted mode:", res["never_arrived_modes"])
    for r in res["by_mode"]:
        print("   %-14s n=%4d share=%.3f total=%6.0fs  drive=%5.0f access=%5.0f wait=%5.0f ride=%5.0f egress=%5.0f"
              % (r["mode"], r["n"], r["share"], r["mean_total_s"], r["mean_drive_s"],
                 r["mean_access_s"], r["mean_wait_s"], r["mean_ride_s"], r["mean_egress_s"]))
    if "peak_occupancy" in res:
        print("   peak occupancy:", res["peak_occupancy"], " lot use:", res["lot_counts"])


if __name__ == "__main__":
    main()
