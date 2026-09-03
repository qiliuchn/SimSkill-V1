"""
Verify a SUMO <calibrator>'s live flow enforcement using its own calstats
output (the authoritative source for realized vs. aspired flow/speed and
insert/remove/cleared counts -- no need to re-derive flow from a detector),
cross-checked against GEH, and optionally against an otherwise-identical
UNCALIBRATED baseline run's E1 detector output (baseline runs have no
calibrator, hence no calstats file, so realized flow there is read from a
plain E1 induction-loop detector instead).

Usage:
    python verify_calibrator.py \
        --calstats out/cal_calstats.xml \
        --baseline-e1-output out/base_e1.xml \
        --out-csv comparison.csv
"""

import argparse
import csv
import math
import xml.etree.ElementTree as ET
from collections import defaultdict


def parse_args():
    p = argparse.ArgumentParser(description="Verify a SUMO calibrator's live flow enforcement via GEH.")
    p.add_argument("--calstats", required=True, help="The calibrator's own calstats output (--calibrator-output / the calibrator's output= attribute)")
    p.add_argument("--baseline-e1-output", default=None, help="E1 detector output for an otherwise-identical UNCALIBRATED run, for comparison (baseline runs have no calstats)")
    p.add_argument("--out-csv", default="comparison.csv")
    return p.parse_args()


def geh(observed, expected):
    if observed + expected == 0:
        return 0.0
    return math.sqrt(2 * (observed - expected) ** 2 / (observed + expected))


def load_calstats(path):
    """[(begin, end, aspired_flow, realized_flow, aspired_speed, realized_speed,
    inserted, removed, cleared), ...] -- one row per interval, merging duplicate
    (begin,end) rows (SUMO can emit a trailing near-empty interval at simulation
    end for a calibrator that had no more work to do)."""
    root = ET.parse(path).getroot()
    by_window = {}
    for iv in root.findall("interval"):
        key = (float(iv.get("begin")), float(iv.get("end")))
        row = {
            "aspiredFlow": float(iv.get("aspiredFlow")), "flow": float(iv.get("flow")),
            "aspiredSpeed": float(iv.get("aspiredSpeed")), "speed": float(iv.get("speed")),
            "inserted": int(iv.get("inserted")), "removed": int(iv.get("removed")),
            "cleared": int(iv.get("cleared")), "nVehContrib": int(iv.get("nVehContrib")),
        }
        # prefer the row with actual activity if the window appears twice
        if key not in by_window or row["nVehContrib"] > by_window[key]["nVehContrib"]:
            by_window[key] = row
    return by_window


def realized_flow_per_interval(e1_path, windows):
    """Sum an E1 detector's per-sub-interval flow (veh/h) into each target window."""
    totals = defaultdict(float)
    n = defaultdict(int)
    for _, iv in ET.iterparse(e1_path, events=("end",)):
        if iv.tag != "interval":
            continue
        b = float(iv.get("begin"))
        f = float(iv.get("flow") or 0.0)
        for (begin, end) in windows:
            if begin <= b < end:
                totals[(begin, end)] += f
                n[(begin, end)] += 1
        iv.clear()
    return {w: totals[w] / n[w] for w in totals if n[w]}


def main():
    args = parse_args()
    by_window = load_calstats(args.calstats)
    windows = sorted(by_window)

    base_flow = realized_flow_per_interval(args.baseline_e1_output, windows) if args.baseline_e1_output else {}

    rows = [["begin", "end", "target_vph", "calibrated_realized_vph", "calibrated_GEH", "pass_GEH<5",
              "inserted", "removed", "cleared", "baseline_realized_vph", "baseline_GEH"]]
    print(f"{'interval':<14}{'target':>8}{'cal_flow':>10}{'cal_GEH':>9}{'pass':>6}{'ins':>5}{'rem':>5}{'clr':>5}{'base_flow':>11}{'base_GEH':>10}")
    for (begin, end) in windows:
        r = by_window[(begin, end)]
        cg = geh(r["flow"], r["aspiredFlow"])
        bf = base_flow.get((begin, end))
        bg = geh(bf, r["aspiredFlow"]) if bf is not None else None
        rows.append([begin, end, r["aspiredFlow"], r["flow"], f"{cg:.2f}", cg < 5,
                     r["inserted"], r["removed"], r["cleared"],
                     bf if bf is not None else "", f"{bg:.2f}" if bg is not None else ""])
        print(f"{begin:.0f}-{end:.0f}s{'':<5}{r['aspiredFlow']:>8.0f}{r['flow']:>10.1f}{cg:>9.2f}{str(cg < 5):>6}"
              f"{r['inserted']:>5d}{r['removed']:>5d}{r['cleared']:>5d}"
              f"{(bf or 0):>11.1f}{(bg or 0):>10.2f}")

    with open(args.out_csv, "w", newline="") as f:
        csv.writer(f).writerows(rows)
    print(f"\nWrote {args.out_csv}")


if __name__ == "__main__":
    main()
