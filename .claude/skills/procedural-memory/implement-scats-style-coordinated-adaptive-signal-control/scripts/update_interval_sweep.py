#!/usr/bin/env python3
"""Sub-goal 3, part B: run the FULL adaptive controller (sub-goal 1) on the
UNPRED demand regime with the adaptation-tick interval swept over
{1, 2, 5, 10, 20} cycles, to see whether an interior optimum exists (too
frequent = the controller is in permanent transition; too rare = a stale
plan that stops tracking demand)."""
import csv
import os
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CTRL = os.path.join(ROOT, "controller")
sys.path.insert(0, CTRL)
sys.path.insert(0, os.path.join(ROOT, "demand"))
import run_adaptive  # noqa: E402

INTERVALS = [1, 2, 5, 10, 20]
SEED = 1
REGIME = "unpred"


def tripinfo_stats(path, t0=300.0):
    n, tl, wt = 0, [], []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "tripinfo":
            dep = float(el.get("depart"))
            if dep >= t0:
                n += 1
                tl.append(float(el.get("timeLoss")))
                wt.append(float(el.get("waitingTime")))
            el.clear()
    return dict(n=n, mean_timeloss=sum(tl) / n if n else float("nan"),
               mean_wait=sum(wt) / n if n else float("nan"))


def main():
    rows = []
    for k in INTERVALS:
        outdir = os.path.join(HERE, "sweep", "k%d" % k)
        print("=== update_interval_cycles =", k, "===")
        run_adaptive.run(SEED, REGIME, outdir, update_interval_cycles=k)
        st = tripinfo_stats(os.path.join(outdir, "tripinfo.xml"))
        rows.append(dict(k=k, **st))
        print("  n=%d mean_timeloss=%.2f mean_wait=%.2f" % (st["n"], st["mean_timeloss"], st["mean_wait"]))
    with open(os.path.join(HERE, "update_interval_results.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["k", "n", "mean_timeloss", "mean_wait"])
        w.writeheader()
        w.writerows(rows)
    print("\nDESIGN CURVE (net benefit vs update interval, k=cycles between adaptations):")
    best = min(rows, key=lambda r: r["mean_timeloss"])
    for r in rows:
        flag = "  <-- best" if r["k"] == best["k"] else ""
        print("  k=%2d  mean_timeloss=%7.2f  mean_wait=%7.2f%s" % (r["k"], r["mean_timeloss"], r["mean_wait"], flag))


if __name__ == "__main__":
    main()
