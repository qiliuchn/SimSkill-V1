#!/usr/bin/env python3
"""
Empirical warm-up / initialisation-bias check, per the replication skill's
insistence that a warm-up truncation be justified (and that a genuine steady
state may not exist at every demand level) rather than picked arbitrarily.

Runs a small dedicated set of replications (summary.xml kept), then for each
(variant, volume, cell) applies:
  * MSER-5 on the running-vehicle-count series from `summary` output;
  * a direct BIAS quantification - mean car travel time for departures in
    [d, 4200) as d is swept, so the actual cost/benefit of truncating at
    600 s is measured instead of assumed.

Note `summary`'s meanSpeed == -1 is a sentinel for "no running vehicles" and is
excluded rather than averaged in.

Usage: python3 warmup_check.py --net-dir NET --work-dir WORK --out TXT
"""
import argparse
import os
import sys
import xml.etree.ElementTree as ET

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scenario as SC   # noqa: E402
import run_cell as RC   # noqa: E402


def mser5(y, batch=5):
    """MSER-5 (White 1997). Returns (best truncation index in ORIGINAL units,
    whether the optimum pinned to the search boundary -> non-stationary)."""
    n = len(y) // batch
    b = np.array([np.mean(y[i * batch:(i + 1) * batch]) for i in range(n)])
    best, bestd = None, None
    hi = n // 2
    for d in range(0, hi):
        tail = b[d:]
        m = tail.mean()
        stat = np.sum((tail - m) ** 2) / (len(tail) ** 2)
        if best is None or stat < best:
            best, bestd = stat, d
    pinned = bestd >= hi - 1
    return bestd * batch, pinned


def series(run_dir):
    t, run, spd = [], [], []
    for st in ET.parse(os.path.join(run_dir, "summary.xml")).getroot():
        tt = float(st.get("time"))
        t.append(tt)
        run.append(float(st.get("running")))
        ms = float(st.get("meanSpeed", -1))
        spd.append(np.nan if ms == -1 else ms)   # -1 is a SENTINEL, not a speed
    return np.array(t), np.array(run), np.array(spd)


def travel_time_by_truncation(run_dir, cuts):
    dep, dur = [], []
    for tr in ET.parse(os.path.join(run_dir, "tripinfo.xml")).getroot():
        if not tr.get("id").startswith("car."):
            continue
        dep.append(float(tr.get("depart")))
        dur.append(float(tr.get("duration")))
    dep, dur = np.array(dep), np.array(dur)
    out = {}
    for c in cuts:
        m = (dep >= c) & (dep < SC.MEAS_END)
        out[c] = (dur[m].mean() if m.any() else float("nan"), int(m.sum()))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--net-dir", required=True)
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    wd = os.path.join(os.path.abspath(a.work_dir), "warmup")
    os.makedirs(wd, exist_ok=True)
    lines = []
    P = lines.append
    P("WARM-UP / STEADY-STATE DIAGNOSTIC")
    P("=" * 78)
    P("MSER-5 on the running-vehicle-count series from summary output, plus a")
    P("direct measurement of how mean car travel time changes with the")
    P("truncation point. Series sampled every 1 s; MSER-5 batch = 5 s.")
    P("")
    cuts = [0, 150, 300, 450, 600, 900, 1200, 1800]
    for variant in ["A", "B"]:
        for vol in SC.VOLUMES:
            for cell in ["D0", "D30"]:
                per_seed_d, pinned_any = [], 0
                tt = {c: [] for c in cuts}
                for seed in (101, 102, 103, 104, 105):
                    rd = os.path.join(wd, f"{variant}_{vol}_{cell}_s{seed}")
                    if not os.path.exists(os.path.join(rd, "summary.xml")):
                        RC.run(a.net_dir, rd, variant, vol, cell, seed)
                    t, run, spd = series(rd)
                    # restrict to the loading period; the post-4800 s drain is
                    # not part of the system we are trying to warm up into
                    m = t < SC.MEAS_END
                    d, pin = mser5(run[m])
                    per_seed_d.append(d)
                    pinned_any += int(pin)
                    for c, (mu, n) in travel_time_by_truncation(rd, cuts).items():
                        tt[c].append(mu)
                P(f"variant {variant}  volume {vol:5d}  cell {cell}")
                P(f"    MSER-5 truncation point per seed (s): {per_seed_d}"
                  f"   median={int(np.median(per_seed_d))} s")
                P(f"    optimum pinned to search boundary (=> NON-STATIONARY, "
                  f"no steady state) in {pinned_any}/5 seeds")
                row = "  ".join(f"d={c}:{np.mean(v):7.2f}"
                                for c, v in tt.items())
                P(f"    mean car travel time (s) vs truncation d: {row}")
                base = np.mean(tt[600])
                worst = max(abs(np.mean(v) - base) for c, v in tt.items()
                            if c >= 300)
                P(f"    |bias| of the chosen d=600 s vs any d>=300 s: "
                  f"{worst:.2f} s ({100*worst/base:.2f}% of the mean)")
                P("")
    with open(a.out, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
