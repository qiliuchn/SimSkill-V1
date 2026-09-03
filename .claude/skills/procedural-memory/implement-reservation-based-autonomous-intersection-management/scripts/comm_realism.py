#!/usr/bin/env python3
"""Communication-realism digest: the naive controller (runs/s6) against the
latency- and sensor-error-compensated controller (runs/s6c, runs/s6d)."""
import os
import sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(os.path.dirname(HERE))
from analyze import run_metrics, mean_ci      # noqa: E402


def blk(title, pat, vals):
    print("=== %s ===" % title)
    for v in vals:
        ms, coll, tel, jam, still, arr, n = [], 0, 0, 0, 0, 0, 0
        for s in (101, 102, 103):
            m = run_metrics(pat % (v, s))
            if not m:
                continue
            n += 1
            ms.append(m["mean_delay"])
            coll += m.get("collisions") or 0
            tel += m.get("teleports_log") or 0
            jam += m.get("teleports_jam") or 0
            still += m.get("still_running") or 0
            arr += m["arrived"]
        if ms:
            mu, h, _ = mean_ci(ms)
            print("  %-6.2f n=%d delay=%7.1f +/- %6.1f COLL=%-4d tele=%-3d jam=%-2d "
                  "still=%d arrived=%d" % (v, n, mu, h, coll, tel, jam, still, arr))


blk("latency, NO compensation", "runs/s6/lat%.1f_d900_s%d",
    [0.0, 0.2, 0.4, 0.6, 1.0, 1.5, 2.0, 3.0])
blk("latency, WITH compensation", "runs/s6c/latcomp%.1f_d900_s%d",
    [0.2, 0.6, 0.8, 1.0, 1.2, 1.5, 3.0])
blk("position noise, NO compensation", "runs/s6/noise%.1f_d900_s%d",
    [0.0, 1.0, 2.5, 5.0, 8.0, 12.0, 20.0])
blk("position noise, WITH 3-sigma margin", "runs/s6d/noisecomp%.1f_d900_s%d",
    [1.0, 2.5, 5.0, 8.0, 20.0])
