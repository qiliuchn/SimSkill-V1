#!/usr/bin/env python3
"""
Characterise what --time-to-teleport -1 actually does: permanent deadlock,
unbounded queues, or eventual recovery?

Reads each run's `summary` time series and reports, for the last 3600s of the
horizon: change in running count, change in arrivals, and mean network speed --
a frozen `running`, zero further arrivals and ~0 speed is a permanent deadlock.
"""
import argparse
import csv
import json
import os
import sys
import xml.etree.ElementTree as ET


def series(sumfile):
    out = []
    for _, el in ET.iterparse(sumfile, events=("end",)):
        if el.tag == "step":
            out.append((float(el.get("time")), int(el.get("running")),
                        int(el.get("arrived")), int(el.get("waiting")),
                        float(el.get("meanSpeed")), int(el.get("teleports"))))
            el.clear()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--outcsv", required=True)
    ap.add_argument("--tscsv", required=True)
    args = ap.parse_args()
    W = args.work
    rows = []
    ts_dump = []
    for level in ["LOW", "OS-A", "OS-B"]:
        for ttt in ["-1", "60", "300", "900"]:
            for seed in range(1, 6):
                d = os.path.join(W, "runs", "sweep",
                                 "%s_kc_on_ttt%s_s%d" % (level, ttt, seed))
                f = os.path.join(d, "summary.xml")
                if not os.path.exists(f):
                    continue
                s = series(f)
                T = s[-1][0]
                # last 3600 s window
                win = [x for x in s if x[0] >= T - 3600]
                d_run = win[-1][1] - win[0][1]
                d_arr = win[-1][2] - win[0][2]
                d_tel = win[-1][5] - win[0][5]
                spd = sum(x[4] * x[1] for x in win if x[1] > 0)
                den = sum(x[1] for x in win if x[1] > 0)
                # first time running stops changing for >=1800 s
                frozen_at = None
                for i, x in enumerate(s):
                    j = i
                    while j < len(s) and s[j][0] - x[0] < 1800:
                        j += 1
                    if j >= len(s):
                        break
                    seg = s[i:j]
                    if max(y[1] for y in seg) == min(y[1] for y in seg) and x[1] > 0:
                        frozen_at = x[0]
                        break
                rows.append(dict(level=level, ttt=ttt, seed=seed, horizon=T,
                                 final_running=s[-1][1], final_waiting=s[-1][3],
                                 final_arrived=s[-1][2],
                                 delta_running_last3600=d_run,
                                 arrivals_last3600=d_arr,
                                 teleports_last3600=d_tel,
                                 meanspeed_last3600=round(spd / den, 4) if den else 0.0,
                                 running_frozen_since=frozen_at))
                if seed == 1:
                    for x in s[::30]:  # every 300 s
                        ts_dump.append(dict(level=level, ttt=ttt, seed=seed, t=x[0],
                                            running=x[1], arrived=x[2], waiting=x[3],
                                            meanSpeed=x[4], teleports=x[5]))
    with open(args.outcsv, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    with open(args.tscsv, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(ts_dump[0].keys()))
        w.writeheader()
        w.writerows(ts_dump)

    print("%-6s %-5s %8s %9s %9s %10s %11s %12s" %
          ("level", "ttt", "finRun", "finWait", "arr@last", "arr_L3600", "spd_L3600", "frozenSince"))
    from collections import defaultdict
    g = defaultdict(list)
    for r in rows:
        g[(r["level"], r["ttt"])].append(r)
    for k in sorted(g, key=lambda k: (["LOW", "OS-A", "OS-B"].index(k[0]),
                                      ["-1", "60", "300", "900"].index(k[1]))):
        v = g[k]
        fz = [r["running_frozen_since"] for r in v if r["running_frozen_since"] is not None]
        print("%-6s %-5s %8.1f %9.1f %9.1f %10.1f %11.3f %12s" % (
            k[0], k[1],
            sum(r["final_running"] for r in v) / len(v),
            sum(r["final_waiting"] for r in v) / len(v),
            sum(r["final_arrived"] for r in v) / len(v),
            sum(r["arrivals_last3600"] for r in v) / len(v),
            sum(r["meanspeed_last3600"] for r in v) / len(v),
            ("%.0f (%d/%d seeds)" % (sum(fz) / len(fz), len(fz), len(v))) if fz else "-"))


if __name__ == "__main__":
    sys.exit(main())
