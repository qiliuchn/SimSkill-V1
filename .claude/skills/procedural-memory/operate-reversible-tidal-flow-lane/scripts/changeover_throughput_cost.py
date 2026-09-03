#!/usr/bin/env python3
"""Quantify the throughput actually lost to the changeover dead time.

Two independent accountings:

  (1) CAPACITY-BASED UPPER BOUND.  Between t_request and t_grant no vehicle in
      either direction may enter the reversible lane, so the forgone entries
      are  clearance_s x measured per-lane capacity (1032 veh/h, from
      analysis/capacity_measurement.json).

  (2) DIRECT MEASUREMENT.  Corridor arrivals in the changeover window, policy B
      minus policy A at the SAME seed and the same demand file (CRN), so the
      difference is attributable to the changeover and nothing else.

Writes outputs/analysis/changeover_throughput_cost.json
"""
import json
import os
import statistics as st
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ANADIR, ensure_dirs

PER_LANE_CAP_VPH = 1032.0
TAIL = 300.0    # seconds of settling counted after the grant


def arrivals(rundir):
    out = []
    for ev, el in ET.iterparse(os.path.join(rundir, "tripinfo.xml"), events=("end",)):
        if el.tag == "tripinfo":
            vid = el.get("id")
            if vid.startswith("EB.") or vid.startswith("WB."):
                a = float(el.get("arrival"))
                if a >= 0:
                    out.append((a, vid.split(".")[0]))
            el.clear()
    return out


def main():
    ensure_dirs()
    rows = [r for r in json.load(open(os.path.join(ANADIR, "day_runs.json")))
            if "error" not in r]
    by = defaultdict(dict)
    for r in rows:
        by[r["seed"]][r["policy"]] = r

    per_seed = []
    for seed, d in sorted(by.items()):
        if "A" not in d or "B" not in d:
            continue
        a_arr = arrivals(d["A"]["outdir"])
        b_arr = arrivals(d["B"]["outdir"])
        windows = []
        for c in d["B"]["changeovers"]:
            t0, t1 = c["t_request"], c["t_grant"] + TAIL
            na = sum(1 for t, _ in a_arr if t0 <= t < t1)
            nb = sum(1 for t, _ in b_arr if t0 <= t < t1)
            windows.append(dict(
                t_request=t0, t_grant=c["t_grant"], clearance_s=c["clearance_s"],
                loser=c["loser"], gainer=c["gainer"],
                window_s=t1 - t0,
                corridor_arrivals_policy_A=na, corridor_arrivals_policy_B=nb,
                measured_arrivals_delta_B_minus_A=nb - na,
                capacity_upper_bound_forgone_entries=round(
                    c["clearance_s"] * PER_LANE_CAP_VPH / 3600.0, 1)))
        per_seed.append(dict(
            seed=seed, n_changeovers=len(windows), windows=windows,
            total_dead_time_s=sum(w["clearance_s"] for w in windows),
            total_capacity_upper_bound_forgone=round(
                sum(w["capacity_upper_bound_forgone_entries"] for w in windows), 1),
            total_measured_arrivals_delta=sum(
                w["measured_arrivals_delta_B_minus_A"] for w in windows),
            whole_day_arrivals_A=len(a_arr), whole_day_arrivals_B=len(b_arr),
            whole_day_arrivals_delta=len(b_arr) - len(a_arr)))

    res = dict(
        per_lane_capacity_vph=PER_LANE_CAP_VPH,
        settling_tail_s=TAIL,
        per_seed=per_seed,
        summary=dict(
            mean_total_dead_time_s=round(st.mean(
                [p["total_dead_time_s"] for p in per_seed]), 1),
            mean_capacity_upper_bound_forgone_entries=round(st.mean(
                [p["total_capacity_upper_bound_forgone"] for p in per_seed]), 1),
            mean_measured_arrivals_delta_in_changeover_windows=round(st.mean(
                [p["total_measured_arrivals_delta"] for p in per_seed]), 1),
            mean_whole_day_arrivals_delta_B_minus_A=round(st.mean(
                [p["whole_day_arrivals_delta"] for p in per_seed]), 1)))
    out = os.path.join(ANADIR, "changeover_throughput_cost.json")
    with open(out, "w") as f:
        json.dump(res, f, indent=2)
    print(json.dumps(res["summary"], indent=2))
    for p in per_seed:
        print(f"seed {p['seed']}: dead {p['total_dead_time_s']}s  "
              f"upper-bound forgone {p['total_capacity_upper_bound_forgone']}  "
              f"measured delta in windows {p['total_measured_arrivals_delta']}  "
              f"whole-day delta {p['whole_day_arrivals_delta']}")
    print("\nwrote", out)


if __name__ == "__main__":
    main()
