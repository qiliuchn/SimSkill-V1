#!/usr/bin/env python3
"""
Emulate the FIELD COUNT.

From a completed run, export
  (a) a realistic turning-movement-count CSV from the STOP-BAR detectors only
      (intersection, approach, movement, 15-min bin start, clock, vehicle count,
       heavy-vehicle count) -- i.e. DEPARTURES across the stop bar, exactly what
       a TMC / video count / ATSPM records, and
  (b) an ATR-style profile from one mid-block station per direction, which the
      design-hour step consumes.

It also writes the TRUE (nominal) per-movement demand table for the same bins.
That table is available ONLY because this is a synthetic experiment; nothing in
counts_to_demand.py is allowed to read it.
"""
import argparse
import csv
import os

from common import RUNS, OUT, BIN, N_BINS, JUNCTIONS, parse_e1
import demand as D


def movement_counts(run_dir):
    """{(J, app, mvt, bin): (total, heavy)} from the stop-bar movement loops."""
    e1 = parse_e1(os.path.join(run_dir, "e1_movement.xml"))
    tot, hv = {}, {}
    for det, rows in e1.items():
        pre, j, app, m, _k = det.split("_")
        for (b0, b1, n, _f, _o) in rows:
            b = int(b0 // BIN)
            if b >= N_BINS:
                continue
            (tot if pre == "mv" else hv)[(j, app, m, b)] = \
                (tot if pre == "mv" else hv).get((j, app, m, b), 0) + n
    return {k: (v, hv.get(k, 0)) for k, v in tot.items()}


def lane_counts(run_dir):
    e1 = parse_e1(os.path.join(run_dir, "e1_stopbar.xml"))
    out = {}
    for det, rows in e1.items():
        _p, j, app, lane = det.split("_")
        for (b0, b1, n, _f, _o) in rows:
            b = int(b0 // BIN)
            if b < N_BINS:
                out[(j, app, b)] = out.get((j, app, b), 0) + n
    return out


def atr_counts(run_dir):
    e1 = parse_e1(os.path.join(run_dir, "e1_atr.xml"))
    tot, hv = {}, {}
    for det, rows in e1.items():
        parts = det.split("_")
        pre, d = parts[0], parts[1]
        for (b0, b1, n, _f, _o) in rows:
            b = int(b0 // BIN)
            if b >= N_BINS:
                continue
            tgt = tot if pre == "atr" else hv
            tgt[(d, b)] = tgt.get((d, b), 0) + n
    return {k: (v, hv.get(k, 0)) for k, v in tot.items()}


def clock(b):
    t = b * BIN
    return "%02d:%02d" % (t // 3600, (t % 3600) // 60)


def write_tmc(run_dir, out_csv):
    mc = movement_counts(run_dir)
    with open(out_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["intersection", "approach", "movement", "bin_start_s",
                    "bin_start_clock", "veh_count", "heavy_count"])
        for (j, app, m, b) in sorted(mc, key=lambda k: (k[0], k[1], k[2], k[3])):
            t, h = mc[(j, app, m, b)]
            w.writerow([j, app, m, b * BIN, clock(b), t, h])
    return mc


def write_atr(run_dir, out_csv):
    ac = atr_counts(run_dir)
    with open(out_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["station", "direction", "bin_start_s", "bin_start_clock",
                    "veh_count", "heavy_count"])
        for (d, b) in sorted(ac):
            t, h = ac[(d, b)]
            w.writerow(["ATR_%s" % d, d, b * BIN, clock(b), t, h])
    return ac


def write_truth(arm, out_csv):
    tm = D.true_movement_volumes(arm)
    with open(out_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["intersection", "approach", "movement", "bin_start_s",
                    "bin_start_clock", "true_demand_veh"])
        for (j, app, m) in sorted(tm):
            for b in range(N_BINS):
                w.writerow([j, app, m, b * BIN, clock(b), "%.3f" % tm[(j, app, m)][b]])
    return tm


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True)
    ap.add_argument("--run", default=None)
    a = ap.parse_args()
    rd = os.path.join(RUNS, a.run or ("gt_" + a.arm))
    mc = write_tmc(rd, os.path.join(OUT, "tmc_counts_%s.csv" % a.arm))
    ac = write_atr(rd, os.path.join(OUT, "atr_profile_%s.csv" % a.arm))
    tm = write_truth(a.arm, os.path.join(OUT, "true_demand_%s.csv" % a.arm))
    lc = lane_counts(rd)

    print("arm = %s   run = %s" % (a.arm, rd))
    print("%-22s %10s %10s %8s" % ("movement", "true dem", "stop-bar", "ratio"))
    for j in JUNCTIONS:
        for app in ("EB", "WB", "NB", "SB"):
            for m in ("L", "T", "R"):
                td = sum(tm[(j, app, m)])
                sc = sum(mc.get((j, app, m, b), (0, 0))[0] for b in range(N_BINS))
                print("%-22s %10.1f %10d %8.3f" % ("%s %s %s" % (j, app, m),
                                                   td, sc, sc / td if td else 0))
    # movement-loop vs lane-loop cross-check
    bad = 0
    for j in JUNCTIONS:
        for app in ("EB", "WB", "NB", "SB"):
            a1 = sum(mc.get((j, app, m, b), (0, 0))[0] for m in "LTR" for b in range(N_BINS))
            a2 = sum(lc.get((j, app, b), 0) for b in range(N_BINS))
            if a1 != a2:
                bad += 1
                print("MISMATCH %s %s movement-loops=%d lane-loops=%d" % (j, app, a1, a2))
    print("movement-loop vs lane-loop cross-check: %d mismatched approaches of 12" % bad)
