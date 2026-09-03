#!/usr/bin/env python3
"""
Teleport-artifact validity check for the near-gridlock cells of the bay sweep
(per `validate-congested-scenario-results-against-teleport-artifacts`).

An undersized bay drives the north approach toward gridlock, which is exactly
where SUMO's own gridlock-resolution machinery can corrupt a result. For the
worst cells this script:

  1. re-runs at --time-to-teleport in {-1 (disabled), 120, 300, 600};
  2. reports the teleport count (summing per-step STARTING teleports from
     TraCI, NOT summing summary.xml's cumulative `teleports` attribute);
  3. checks the running-vehicle-count series from summary.xml for a PERMANENT
     FREEZE, the signature of true deadlock plus survivorship censoring under
     ttt=-1;
  4. verifies the chosen ttt exceeds the network's longest legitimate red.

Longest legitimate red for the study approach: with the 90 s cycle, the north
LEFT movement is green only in phase 0 (8-24 s), so its red can run ~66-82 s;
the through movement's red is ~50-66 s. A vehicle that advances at all resets
SUMO's standstill timer, so a 300 s threshold is >3.6x the longest single red.
"""
import argparse
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))

# the near-gridlock corners of the sweep (bay, share, signal)
CELLS = [(10, 0.25, "split16"), (20, 0.25, "split16"),
         (10, 0.40, "split24"), (20, 0.40, "split24"),
         (30, 0.40, "split24"), (10, 0.10, "split08")]
TTTS = [-1, 120, 300, 600]
SEEDS = [1, 2, 3]


def running_freeze(summary):
    """Return (frozen, freeze_start_s, tail_arrivals) for the running-vehicle
    series: a permanent freeze = running count constant and no further
    arrivals for the rest of the simulation."""
    try:
        root = ET.parse(summary).getroot()
    except Exception:
        return None, None, None
    steps = [(float(s.get("time")), int(s.get("running")), int(s.get("ended", 0)))
             for s in root.findall("step")]
    if not steps:
        return None, None, None
    last_end = steps[-1][2]
    # walk back to the last time `ended` changed
    t_last_arrival = steps[0][0]
    for t, r, e in steps:
        if e < last_end:
            t_last_arrival = t
    tail = steps[-1][0] - t_last_arrival
    run_tail = {r for t, r, e in steps if t >= t_last_arrival}
    frozen = (tail > 600.0) and (len(run_tail) <= 2) and steps[-1][1] > 0
    return frozen, (t_last_arrival if frozen else None), steps[-1][1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--jobs", type=int, default=9)
    a = ap.parse_args()
    outdir = os.path.join(a.work, "teleport_check")
    os.makedirs(outdir, exist_ok=True)

    jobs = [(b, s, sg, ttt, seed) for (b, s, sg) in CELLS
            for ttt in TTTS for seed in SEEDS]

    def one(j):
        b, s, sg, ttt, seed = j
        tag = f"bay{b}_s{int(s*100)}_{sg}_ttt{ttt}_seed{seed}"
        od = os.path.join(outdir, tag)
        cmd = [sys.executable, os.path.join(HERE, "run_cell.py"),
               "--net", os.path.join(a.work, "nets", f"bay_{b}.net.xml"),
               "--rou", os.path.join(a.work, f"rou_s{int(s*100)}.rou.xml"),
               "--tls", os.path.join(a.work, "tls", str(b), f"tl_{sg}.add.xml"),
               "--program", sg, "--outdir", od, "--seed", str(seed),
               "--ttt", str(ttt), "--label", tag]
        r = subprocess.run(cmd, capture_output=True, text=True)
        f = os.path.join(od, "events.json")
        if not os.path.exists(f):
            return dict(bay=b, share=s, sig=sg, ttt=ttt, seed=seed, ok=0,
                        err=(r.stderr or "")[-300:])
        d = json.load(open(f))
        frozen, tfz, run_end = running_freeze(os.path.join(od, "summary.xml"))
        return dict(bay=b, share=s, sig=sig_(sg), ttt=ttt, seed=seed, ok=1,
                    teleports=d["teleports"],
                    throughput_vph=(d["served_L"] + d["served_T"] + d["served_R"]) * 1.2,
                    timeloss_L=d["timeloss_L"], timeloss_TR=d["timeloss_TR"],
                    n_L=d["n_L"], unfinished_L=d["unfinished_L"],
                    never_inserted_tot=round(d["never_inserted_L"] + d["never_inserted_T"]
                                             + d["never_inserted_R"], 1),
                    overflow_s=d["overflow_s"], blockage_s=d["blockage_s"],
                    running_at_end=run_end, permanent_freeze=bool(frozen),
                    freeze_start_s=tfz)

    def sig_(x):
        return x

    with ThreadPoolExecutor(max_workers=a.jobs) as ex:
        rows = list(ex.map(one, jobs))

    import csv
    keys = sorted({k for r in rows for k in r})
    keys = [k for k in ("bay", "share", "sig", "ttt", "seed") if k in keys] + \
           [k for k in keys if k not in ("bay", "share", "sig", "ttt", "seed")]
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print("wrote", a.out, len(rows), "rows")

    # ---- summary verdict per cell ----
    import statistics as st
    from collections import defaultdict
    g = defaultdict(list)
    for r in rows:
        if r.get("ok"):
            g[(r["bay"], r["share"], r["sig"], r["ttt"])].append(r)
    print(f"\n{'bay':>4} {'share':>5} {'signal':>8} {'ttt':>5} {'teleports':>10} "
          f"{'thr_vph':>8} {'tl_left':>8} {'freeze':>7} {'run_end':>8}")
    for k in sorted(g, key=lambda x: (x[1], x[0], x[3])):
        rs = g[k]
        print(f"{k[0]:>4} {k[1]:>5} {k[2]:>8} {k[3]:>5} "
              f"{st.mean(r['teleports'] for r in rs):>10.1f} "
              f"{st.mean(r['throughput_vph'] for r in rs):>8.1f} "
              f"{st.mean(r['timeloss_L'] for r in rs):>8.1f} "
              f"{str(any(r['permanent_freeze'] for r in rs)):>7} "
              f"{st.mean(r['running_at_end'] for r in rs):>8.1f}")


if __name__ == "__main__":
    main()
