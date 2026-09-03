#!/usr/bin/env python3
"""Re-calibrate every station's critical occupancy ON THE CORRIDOR ITSELF.

The mainline-only sweep in calibrate_occupancy.py (all ramps closed) does NOT
transfer: with the three on-ramp merges active, the station just upstream of the
lane drop sits inside a permanent merge-turbulence zone and reads 7% occupancy /
16 m/s at a demand where the mainline-only sweep read 4% / 32 m/s.  A controller
whose setpoint came from the mainline-only sweep therefore meters continuously at
every demand level, which is a controller-configuration error, not a finding
about metering.

Method: pool every 30 s interval from every `nocontrol` run across all demand
levels and seeds, bin by that station's own occupancy, and read off the
occupancy bin where that station's own flow peaks.
"""
import glob
import json
import os
import sys

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
STATIONS = [f"s{i:02d}" for i in range(1, 13)]


def main():
    pts = {s: [] for s in STATIONS}
    n = 0
    for d in sorted(glob.glob(os.path.join(ROOT, "outputs", "runs", "core", "nocontrol_d*"))):
        p = os.path.join(d, "ctl.json")
        if not os.path.exists(p):
            continue
        n += 1
        for x in json.load(open(p))["log"]:
            if x["t"] < 300:
                continue
            for s in STATIONS:
                if x["flow"][s] > 0:
                    pts[s].append((x["occ"][s], x["flow"][s], x["spd"][s]))
    print(f"pooled {n} no-control runs")
    res = {}
    edges = np.array([0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 15, 18, 21, 24, 27, 30, 34, 38, 45, 60, 100])
    for s in STATIONS:
        a = np.array(pts[s])
        if len(a) < 50:
            continue
        occ, flow = a[:, 0], a[:, 1]
        idx = np.digitize(occ, edges)
        rows = []
        for b in range(1, len(edges)):
            m = idx == b
            if m.sum() < 20:
                continue
            rows.append((float(np.mean(occ[m])), float(np.percentile(flow[m], 85)),
                         float(np.mean(flow[m])), int(m.sum())))
        if not rows:
            continue
        # capacity = the occupancy bin where the 85th-percentile flow peaks
        best = max(rows, key=lambda r: r[1])
        res[s] = dict(crit_occ=best[0], cap_flow_p85=best[1], cap_flow_mean=best[2],
                      n=best[3], curve=rows)
        print(f"  {s}: critical occ {best[0]:5.2f}%  capacity {best[1]:6.0f} veh/h "
              f"(p85, n={best[3]})   curve " +
              " ".join(f"{r[0]:.0f}%:{r[1]:.0f}" for r in rows))
    out = os.path.join(ROOT, "outputs", "tables", "corridor_calibration.json")
    json.dump(res, open(out, "w"), indent=1)
    print("\nwrote", out)


if __name__ == "__main__":
    main()
