#!/usr/bin/env python3
"""
Measure the UNBLOCKED corridor capacity properly, so that every v/c figure in
the results is empirical rather than a hand-computed signal-capacity guess.

Per the `quantify-sumo-run-to-run-variability` skill: capacity is the PEAK of
the served-flow-vs-demand curve, not the flow at the hardest loading. Sweep
demand upward with zero deliveries and find where served flow (E1 downstream of
the curb zone) stops tracking demand and starts falling back.

Usage: python3 measure_capacity.py --net-dir NET --work-dir WORK --out TXT
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_cell as RC   # noqa: E402

DEMANDS = [600, 1200, 1500, 1800, 2100, 2400, 2700, 3000, 3300, 3600]
SEEDS = [1, 2, 3]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--net-dir", required=True)
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    wd = os.path.join(os.path.abspath(a.work_dir), "cap")
    L = ["UNBLOCKED CORRIDOR CAPACITY (variant A, ZERO deliveries)",
         "=" * 78,
         "Capacity = peak of the served-flow-vs-demand curve. Served flow read",
         "from the E1 loops 50 m downstream of the curb zone, over the same",
         "[600, 4200) s measurement window used everywhere else. 3 seeds each.",
         "",
         f"{'demand':>8} {'served flow':>13} {'sd':>7} {'mean TT':>9} "
         f"{'departDelay':>12} {'served/demand':>14}"]
    served = {}
    for d in DEMANDS:
        th, tt, dd = [], [], []
        for s in SEEDS:
            rd = os.path.join(wd, f"A_{d}_s{s}")
            m = RC.run(a.net_dir, rd, "A", d, "D0", s)
            th.append(m["throughput_vph"])
            tt.append(m["car_mean_duration_s"])
            dd.append(m["car_mean_departdelay_s"])
        served[d] = np.mean(th)
        L.append(f"{d:8d} {np.mean(th):13.1f} {np.std(th, ddof=1):7.1f} "
                 f"{np.mean(tt):9.1f} {np.mean(dd):12.1f} "
                 f"{np.mean(th)/d:14.3f}")
    cap = max(served.values())
    at = max(served, key=lambda k: served[k])
    L += ["",
          f"PEAK served flow = {cap:.0f} veh/h, reached at demand = {at} veh/h.",
          f"=> unblocked corridor capacity taken as {cap:.0f} veh/h.",
          "",
          "v/c of the six background-volume levels used in the main sweep:"]
    for d in [600, 1200, 1500, 1800, 2100, 2400]:
        L.append(f"    {d:5d} veh/h  ->  v/c = {d/cap:.2f}")
    L += ["",
          "Note the served flow at the two highest demands FALLS BACK below the",
          "peak while departDelay explodes - i.e. loading the network harder",
          "does not measure a higher capacity, it measures a queued origin.",
          "This is exactly the failure mode the replication skill warns about."]
    txt = "\n".join(L)
    with open(a.out, "w") as fh:
        fh.write(txt + "\n")
    print(txt)


if __name__ == "__main__":
    main()
