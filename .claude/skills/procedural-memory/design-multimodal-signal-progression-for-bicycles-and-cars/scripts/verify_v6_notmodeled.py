#!/usr/bin/env python3
"""V6: what SUMO's default bicycle representation does NOT do -- measured.

Each claim is turned into a counting test on raw FCD, run twice: with SUMO's
default lane-based model and with the sublane model enabled
(--lateral-resolution), so the absence is shown to be a property of the *model
choice* and not of the demand.

  (a) overtaking inside a bicycle lane   -> order inversions between the first
      and last signal, bikes only
  (b) riding two abreast                 -> timesteps with >=2 bikes on the SAME
      lane within +-1.5 m longitudinally
  (c) filtering to the stop line         -> mixed variant: bikes passing stopped
      cars on the same lane while queued
  (d) bike boxes / advanced stop lines   -> structural: no SUMO element exists;
      documented with the closest expressible approximations.

Writes data/v6_notmodeled.json.
"""
import json
import os
import sys
from collections import defaultdict
from itertools import combinations

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bikelib as B      # noqa: E402
import fcdbike           # noqa: E402
import scenario as S     # noqa: E402

WIN0, WIN1 = 1200.0, 2400.0
LATRES = ["--lateral-resolution", "0.4"]


def inversions(recs, mode, first=0, last=-1):
    r = [x for x in recs if x["mode"] == mode and
         x["t_cross"][first] is not None and x["t_cross"][last] is not None]
    out = {}
    for d in ("EB", "WB"):
        g = [x for x in r if x["dir"] == d]
        tot = inv = 0
        for a, b in combinations(g, 2):
            da = a["t_cross"][first] - b["t_cross"][first]
            db = a["t_cross"][last] - b["t_cross"][last]
            if abs(da) < 1e-6:
                continue
            tot += 1
            if da * db < 0:
                inv += 1
        out[d] = dict(n_vehicles=len(g), pairs=tot, inversions=inv,
                      inversion_rate=round(inv / float(tot), 5) if tot else None)
    return out


def abreast(fcd, dx=1.5):
    """Timesteps in which >=2 bicycles share a lane within +-dx longitudinally."""
    import xml.etree.ElementTree as ET
    hits, samples, examples = 0, 0, []
    lat_spread = []
    for _, el in ET.iterparse(fcd, events=("end",)):
        if el.tag != "timestep":
            continue
        t = float(el.get("time"))
        by_lane = defaultdict(list)
        for v in el:
            vid = v.get("id")
            md = fcdbike.classify(vid)
            if md is None or md[0] != "bike":
                continue
            lane = v.get("lane") or ""
            if lane.startswith(":"):
                continue
            by_lane[lane].append((float(v.get("x")), float(v.get("y")), vid))
        for lane, vs in by_lane.items():
            samples += len(vs)
            vs.sort()
            for (x1, y1, i1), (x2, y2, i2) in zip(vs, vs[1:]):
                if abs(x2 - x1) <= dx:
                    hits += 1
                    lat_spread.append(abs(y2 - y1))
                    if len(examples) < 15:
                        examples.append(dict(t=t, lane=lane, a=i1, b=i2,
                                             dx=round(abs(x2 - x1), 3),
                                             dy=round(abs(y2 - y1), 3)))
        el.clear()
    return dict(bike_lane_samples=samples, abreast_pairs=hits,
                mean_lateral_sep_m=(round(sum(lat_spread) / len(lat_spread), 3)
                                    if lat_spread else None),
                examples=examples)


def passes_stopped_car(fcd, xs):
    """Mixed variant: count (bike, car) pairs where a bike overtakes a car that
    is standing still on the same edge -- i.e. filtering past a queue."""
    import xml.etree.ElementTree as ET
    pos = defaultdict(dict)          # t -> vid -> (x, lane, speed, kind)
    for _, el in ET.iterparse(fcd, events=("end",)):
        if el.tag != "timestep":
            continue
        t = float(el.get("time"))
        for v in el:
            vid = v.get("id")
            md = fcdbike.classify(vid)
            if md is None:
                continue
            lane = v.get("lane") or ""
            if lane.startswith(":"):
                continue
            pos[t][vid] = (float(v.get("x")), lane.rsplit("_", 1)[0],
                           float(v.get("speed")), md[0], md[1])
        el.clear()
    ts = sorted(pos)
    passes = 0
    ex = []
    for t0, t1 in zip(ts, ts[1:]):
        a, b = pos[t0], pos[t1]
        bikes = [k for k in a if a[k][3] == "bike" and k in b]
        cars = [k for k in a if a[k][3] == "car" and k in b and a[k][2] < 0.3]
        for bk in bikes:
            xb0, eb0, _, _, db = a[bk]
            xb1, eb1, _, _, _ = b[bk]
            for cr in cars:
                xc0, ec0, _, _, dc = a[cr]
                if ec0 != eb0 or dc != db:
                    continue
                xc1 = b[cr][0]
                s = 1.0 if db == "EB" else -1.0
                if s * (xb0 - xc0) < 0 and s * (xb1 - xc1) > 0:
                    passes += 1
                    if len(ex) < 15:
                        ex.append(dict(t=t1, bike=bk, car=cr, edge=ec0))
    return dict(bike_passes_standing_car=passes, examples=ex)


def run(variant, tag, extra):
    s = S.scen(variant)
    plan = B.BikePlan(C=90., gX=22., gL=10., n_int=S.N_INT, variant=variant,
                      offs=[0.0] * S.N_INT)
    d = os.path.join(S.WORK, "verify", tag)
    r = S.evaluate(s, plan, d, seed=11, fcd=True, warm=WIN0, keep_fcd=True,
                   end=WIN1, extra=extra)
    return r, plan


def main():
    out = {"note": ("all runs: dedicated/mixed corridor, seed 11, FCD window "
                    "[%d, %d] s, uncoordinated plan (all offsets 0)"
                    % (WIN0, WIN1))}
    sl_eb, sl_wb = S.stoplines("dedicated")
    for tag, extra in (("default", []), ("sublane", LATRES)):
        r, plan = run("dedicated", "v6_ded_" + tag, extra)
        recs = fcdbike.trips(r["fcd"], S.XS, plan.C, t0=WIN0 + 30,
                             xs_eb=sl_eb, xs_wb=sl_wb)
        out["dedicated_" + tag] = dict(
            n_records=len(recs),
            overtaking_bike=inversions(recs, "bike"),
            overtaking_car=inversions(recs, "car"),
            two_abreast=abreast(r["fcd"]),
            sim_wall_note=extra)
        os.remove(r["fcd"])
        print("dedicated/%s  bike inversions %s" %
              (tag, {k: v["inversion_rate"]
                     for k, v in out["dedicated_" + tag]["overtaking_bike"].items()}),
              " abreast pairs", out["dedicated_" + tag]["two_abreast"]["abreast_pairs"])

    sl_eb_m, sl_wb_m = S.stoplines("mixed")
    for tag, extra in (("default", []), ("sublane", LATRES)):
        r, plan = run("mixed", "v6_mix_" + tag, extra)
        recs = fcdbike.trips(r["fcd"], S.XS, plan.C, t0=WIN0 + 30,
                             xs_eb=sl_eb_m, xs_wb=sl_wb_m)
        out["mixed_" + tag] = dict(
            n_records=len(recs),
            overtaking_bike=inversions(recs, "bike"),
            filtering=passes_stopped_car(r["fcd"], S.XS))
        os.remove(r["fcd"])
        print("mixed/%s  filtering passes %d" %
              (tag, out["mixed_" + tag]["filtering"]["bike_passes_standing_car"]))

    out["bike_box_advanced_stop_line"] = dict(
        representable=False,
        reason=("SUMO has no element for an advanced stop line / bike box: a "
                "bike box is a lateral area ahead of the car stop line that "
                "bicycles occupy laterally across the full carriageway width "
                "during red and clear at green. SUMO's lane-based model has no "
                "way to let bicycles legally occupy the space in front of the "
                "car stop line and then disperse laterally."),
        closest_approximations=[
            "a short bicycle-only lane segment upstream of the junction plus a "
            "bicycle-specific signal group given a leading (early-start) green "
            "-- this reproduces the DEPARTURE-ORDER effect of a bike box but "
            "not its STORAGE geometry",
            "a separate bicycle tlLogic link index with a leading bicycle "
            "interval (expressible in this study's BikePlan by giving EBB/WBB "
            "green a few seconds before EBT/WBT)"],
        tested_here=False)

    with open(os.path.join(S.DATA, "v6_notmodeled.json"), "w") as f:
        json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()
