#!/usr/bin/env python3
"""
POSITIVE verification that the delivery stop mechanic does what the experiment
assumes - checked against raw FCD / stop-output / laneData, not assumed.

Variant A must show: van speed == 0, physically ON travel lane ECURB_0, for the
full dwell; cars evicted from ECURB_0; forced lane changes out of it.
Variant B must show: van NEVER dwells on a travel lane (it disappears from FCD
while parked in the bay, and its zero-speed time on ECURB_1/ECURB_2 is ~0).

Usage: python3 verify_blocking.py RUN_DIR_A RUN_DIR_B > verification.txt
"""
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict


def load_fcd(path):
    """-> {vid: [(t, lane, speed, pos)]}, and per-timestep lane->set(vids)"""
    tr = defaultdict(list)
    lane_pop = defaultdict(lambda: defaultdict(set))
    for ts in ET.parse(path).getroot():
        t = float(ts.get("time"))
        for v in ts.findall("vehicle"):
            vid = v.get("id")
            lane = v.get("lane")
            sp = float(v.get("speed"))
            tr[vid].append((t, lane, sp, float(v.get("pos"))))
            lane_pop[t][lane].add(vid)
    return tr, lane_pop


def dwell_runs(samples, thresh=0.1):
    """Contiguous zero-speed runs -> list of (t0, t1, lane)."""
    runs, cur = [], None
    for t, lane, sp, pos in samples:
        if sp <= thresh:
            if cur and cur[2] == lane and abs(t - cur[1] - 1.0) < 1e-6:
                cur = (cur[0], t, lane)
            else:
                if cur:
                    runs.append(cur)
                cur = (t, t, lane)
        else:
            if cur:
                runs.append(cur)
            cur = None
    if cur:
        runs.append(cur)
    return runs


def report(tag, run_dir, travel_lanes, bay_lane):
    print("=" * 74)
    print(f"{tag}   run dir: {run_dir}")
    print("=" * 74)
    tr, lane_pop = load_fcd(f"{run_dir}/fcd.xml")
    vans = {k: v for k, v in tr.items() if k.startswith("van.")}
    cars = {k: v for k, v in tr.items() if k.startswith("car.")}
    print(f"vans seen in FCD: {len(vans)}   cars seen in FCD: {len(cars)}")

    # ---- 1. where and for how long is each van at ZERO speed?
    per_lane = defaultdict(float)
    longruns = []
    for vid, s in vans.items():
        for t0, t1, lane in dwell_runs(s):
            per_lane[lane] += (t1 - t0 + 1.0)
            if t1 - t0 >= 30:
                longruns.append((vid, t0, t1, lane))
    print("\n[1] van vehicle-seconds at speed<=0.1 m/s, by lane (from FCD):")
    for lane, sec in sorted(per_lane.items(), key=lambda x: -x[1]):
        kind = ("TRAVEL LANE" if lane in travel_lanes else
                ("BAY LANE" if lane == bay_lane else "other"))
        print(f"      {lane:12s} {sec:9.0f} s   <- {kind}")
    tl = sum(v for k, v in per_lane.items() if k in travel_lanes)
    print(f"      TOTAL on travel lanes: {tl:.0f} s")
    print(f"\n[2] van zero-speed runs >= 30 s: {len(longruns)}")
    for vid, t0, t1, lane in longruns[:6]:
        print(f"      {vid:10s} t={t0:7.0f}..{t1:7.0f} ({t1-t0+1:5.0f} s) "
              f"lane={lane}")
    if len(longruns) > 6:
        print(f"      ... {len(longruns)-6} more")

    # ---- 3. FCD gaps = time the van is absent from the road entirely
    print("\n[3] FCD absence gaps per van (a parked vehicle is removed from the")
    print("    network, so an off-line bay dwell shows up as a GAP, not as a")
    print("    zero-speed sample on a lane):")
    gaps = []
    for vid, s in vans.items():
        for (t0, l0, _, _), (t1, _, _, _) in zip(s, s[1:]):
            if t1 - t0 > 1.5:
                gaps.append((vid, t0, t1, t1 - t0, l0))
    gaps.sort(key=lambda g: -g[3])
    print(f"    total gaps: {len(gaps)}, total gap seconds: "
          f"{sum(g[3] for g in gaps):.0f}")
    for g in gaps[:4]:
        print(f"      {g[0]:10s} absent {g[1]:.0f}->{g[2]:.0f} "
              f"({g[3]:.0f} s), last seen on {g[4]}")

    # ---- 4. during a long van dwell, what happens on the blocked lane?
    if longruns:
        vid, t0, t1, lane = longruns[len(longruns) // 2]
        print(f"\n[4] snapshot during a representative dwell "
              f"({vid}, lane {lane}, t={t0:.0f}..{t1:.0f}):")
        for t in [t0 + 10, t0 + 40, t0 + 70]:
            if t in lane_pop:
                occ = {ln: len(s) for ln, s in lane_pop[t].items()
                       if ln.startswith("ECURB")}
                print(f"      t={t:7.0f}  ECURB lane occupancy {occ}")
    # ---- 5. car presence on each ECURB lane over the whole run
    carsec = defaultdict(float)
    for vid, s in cars.items():
        for t, lane, sp, pos in s:
            if lane and lane.startswith("ECURB"):
                carsec[lane] += 1.0
    print("\n[5] CAR vehicle-seconds per ECURB lane (from FCD):")
    for lane in sorted(carsec):
        print(f"      {lane:12s} {carsec[lane]:9.0f} s")

    # ---- 6. stop-output cross-check
    print("\n[6] stop-output cross-check (SUMO's own writeback):")
    n = 0
    for st in ET.parse(f"{run_dir}/stops.xml").getroot():
        if not (st.get("id") or "").startswith("van."):
            continue
        n += 1
        if n <= 3:
            print(f"      id={st.get('id')} lane={st.get('lane')} "
                  f"parking={st.get('parking')} "
                  f"parkingArea={st.get('parkingArea')} "
                  f"started={st.get('started')} ended={st.get('ended')}")
    print(f"      ({n} van stops total)")

    # ---- 7. forced lane changes out of the right travel lane in ECURB
    right = travel_lanes[0]
    cnt = defaultdict(int)
    for ch in ET.parse(f"{run_dir}/lanechange.xml").getroot():
        if ch.get("type") != "car":
            continue
        if (ch.get("from") or "").startswith("ECURB"):
            cnt[(ch.get("from"), ch.get("to"), ch.get("reason"))] += 1
    print("\n[7] CAR lane changes originating on ECURB (from lanechange-output):")
    for k, v in sorted(cnt.items(), key=lambda x: -x[1]):
        mark = "  <== off the right travel lane" if k[0] == right else ""
        print(f"      {k[0]} -> {k[1]:10s} reason={k[2]:22s} n={v}{mark}")
    return tl, per_lane


if __name__ == "__main__":
    a, b = sys.argv[1], sys.argv[2]
    tlA, _ = report("VARIANT A  (no curb facility -> double parking expected)",
                    a, ["ECURB_0", "ECURB_1"], None)
    tlB, _ = report("VARIANT B  (dedicated loading bay -> no lane blocking)",
                    b, ["ECURB_1", "ECURB_2"], "ECURB_0")
    print("=" * 74)
    print("VERDICT")
    print("=" * 74)
    print(f"  van zero-speed seconds ON A TRAVEL LANE:  variant A = {tlA:.0f} s"
          f",  variant B = {tlB:.0f} s")
    print("  PASS" if tlA > 1000 and tlB < 100 else "  FAIL - investigate")
