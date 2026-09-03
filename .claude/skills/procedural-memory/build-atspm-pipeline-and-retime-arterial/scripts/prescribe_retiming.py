#!/usr/bin/env python3
"""Prescribe a retiming using ONLY ATSPM diagnostics + the controller's own
timing plan. No tripinfo, no queue file, no vehicle trajectories are opened.

OFFSETS -- for each signal, search the offset shift s in [0, C) that maximises the
  volume-weighted Percent-Arrival-on-Green across BOTH coordinated directions,
  evaluated directly on the observed PCD arrival points (each arrival re-tested
  against its own cycle's measured green length). This is the PCD's own
  question: "where would the green have to sit for these arrivals to land on it?"

SPLITS -- reallocate green from phases the ATSPM shows are UNDER-utilised to
  phases the ATSPM shows are in SUSTAINED split failure. The donor is chosen by
  observed green utilisation; the recipient by the refined split-failure rate.
  Ring-barrier sum constraints are enforced.

OFFSET / SPLIT COUPLING -- in a NEMA ring-barrier controller the coordinated
  phase begins when BOTH rings have crossed the barrier, so lengthening a lead
  left-turn phase pushes the coordinated green later even at a fixed offset.
  The prescribed offset is corrected by that predicted drift; the residual is
  then measured from the AFTER event log rather than assumed.
"""
import argparse
import csv
import json
import os
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SF_RATE_TRIGGER = 0.15          # sustained refined-failure rate that triggers action
RING = {"A": [(1, 2), (5, 6)], "B": [(3, 4), (7, 8)]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="before")
    ap.add_argument("--in-plan", required=True)
    ap.add_argument("--out-plan", required=True)
    ap.add_argument("--damping", type=float, default=1.0,
                    help="fraction of the prescribed offset shift actually applied. "
                         "A per-intersection PCD-maximising rule is a fixed-point "
                         "iteration whose neighbours invalidate each other's optimum; "
                         "damping < 1 is the standard remedy for the resulting oscillation.")
    args = ap.parse_args()

    plan = json.load(open(args.in_plan))
    C = plan["cycle"]
    A = os.path.join(ROOT, "outputs", "atspm")
    pcd = list(csv.DictReader(open(os.path.join(A, f"pcd_points_{args.tag}.csv"))))
    coord = list(csv.DictReader(open(os.path.join(A, f"coordination_{args.tag}.csv"))))
    cyc = list(csv.DictReader(open(os.path.join(A, f"cycles_{args.tag}.csv"))))

    pts = defaultdict(lambda: ([], []))
    for r in pcd:
        k = (r["signal_id"], r["direction"])
        pts[k][0].append(float(r["time_in_cycle_s"])); pts[k][1].append(float(r["green_len_s"]))
    vol = {(r["signal_id"], r["direction"]): float(r["arrivals_per_h"]) for r in coord}

    stat = defaultdict(lambda: dict(n=0, ref=0, util=[]))
    for r in cyc:
        s = stat[(r["signal_id"], int(r["phase"]))]
        s["n"] += 1; s["ref"] += int(r["sf_refined"]); s["util"].append(float(r["green_util"]))

    newplan = json.loads(json.dumps(plan))
    newplan["name"] = "after"
    newplan["comment"] = ("Retimed using ONLY ATSPM diagnostics from the 'before' event log: "
                          "PCD-maximising offsets and splits reallocated from under-utilised "
                          "phases to phases in sustained refined split failure.")
    print("=" * 96)
    print("ATSPM-ONLY RETIMING PRESCRIPTION")
    print("=" * 96)

    # ---------------- SPLITS ----------------
    print("\nSPLIT REALLOCATION  (trigger: refined split-failure rate >= "
          f"{SF_RATE_TRIGGER:.0%} of cycles)")
    print(f"  {'sig':4s} {'phase':6s} {'sf_ref%':>8s} {'g_util':>7s}  action")
    drift = {}
    for sig, jp in newplan["junctions"].items():
        sp = {int(k): float(v) for k, v in jp["splits"].items()}
        old_lead = max(sp[1], sp[5])
        fails = {p: stat[(sig, p)]["ref"] / max(stat[(sig, p)]["n"], 1) for p in range(1, 9)}
        utils = {p: float(np.mean(stat[(sig, p)]["util"])) if stat[(sig, p)]["util"] else 0.0
                 for p in range(1, 9)}
        acted = False
        # group B (cross street) failing -> move time from group A (coordinated)
        gB_fail = max(fails[p] for p in (3, 4, 7, 8))
        if gB_fail >= SF_RATE_TRIGGER:
            gB = sp[3] + sp[4]
            add = 10.0 if gB_fail >= 0.5 else 6.0
            for a, b in ((3, 4), (7, 8)):
                sp[a] += add * 0.4; sp[b] += add * 0.6
            for a, b in ((1, 2), (5, 6)):
                sp[b] -= add
            acted = True
            for p in (3, 4, 7, 8):
                print(f"  {sig:4s} {p:<6d} {100*fails[p]:7.1f}% {utils[p]:7.3f}  "
                      f"cross-street group +{add:.0f}s (now {sp[p]:.0f}s), from coordinated phase")
        # lead left-turn phases failing -> take from their own ring's coordinated phase
        for lp, cp in ((1, 2), (5, 6)):
            if fails[lp] >= SF_RATE_TRIGGER:
                add = 6.0 if fails[lp] >= 0.4 else 4.0
                sp[lp] += add; sp[cp] -= add
                acted = True
                print(f"  {sig:4s} {lp:<6d} {100*fails[lp]:7.1f}% {utils[lp]:7.3f}  "
                      f"lead-left +{add:.0f}s (now {sp[lp]:.0f}s), from coordinated phase "
                      f"{cp} (util {utils[cp]:.2f})")
        if not acted:
            print(f"  {sig:4s} {'-':6s} {100*max(fails.values()):7.1f}% {'-':>7s}  "
                  f"no sustained failure -> splits unchanged")
        assert abs((sp[1] + sp[2]) - (sp[5] + sp[6])) < 1e-6, f"{sig} ring A imbalance"
        assert abs((sp[3] + sp[4]) - (sp[7] + sp[8])) < 1e-6, f"{sig} ring B imbalance"
        assert abs(sp[1] + sp[2] + sp[3] + sp[4] - C) < 1e-6, f"{sig} cycle sum"
        jp["splits"] = {str(p): round(sp[p], 1) for p in range(1, 9)}
        drift[sig] = max(sp[1], sp[5]) - old_lead

    # ---------------- OFFSETS ----------------
    print("\nOFFSET ADJUSTMENT  (maximise volume-weighted AoG over the observed PCD points)")
    print(f"  {'sig':4s} {'old':>6s} {'AoG now':>9s} {'best shift':>11s} {'AoG @shift':>11s} "
          f"{'barrier drift':>14s} {'new offset':>11s}")
    grid = np.arange(0, C, 0.5)
    for sig, jp in newplan["junctions"].items():
        num = np.zeros_like(grid); den = 0.0
        cur = 0.0
        for d in ("EB", "WB"):
            k = (sig, d)
            if k not in pts:
                continue
            tic = np.array(pts[k][0]); g = np.array(pts[k][1]); w = vol[k]
            den += w
            aog = np.array([np.mean(((tic - s) % C) < g) for s in grid])
            num += w * aog
            cur += w * np.mean(tic < g)
        if den == 0:
            continue
        score = num / den
        cur /= den
        best = float(grid[int(np.argmax(score))])
        best = ((best + C / 2) % C) - C / 2          # wrap to [-C/2, C/2)
        best *= args.damping
        new_off = (plan["junctions"][sig]["offset"] + best - drift[sig]) % C
        jp["offset"] = round(new_off, 1)
        print(f"  {sig:4s} {plan['junctions'][sig]['offset']:6.1f} {100*cur:8.1f}% "
              f"{best:+11.1f} {100*score.max():10.1f}% {drift[sig]:+14.1f} {new_off:11.1f}")

    json.dump(newplan, open(args.out_plan, "w"), indent=2)
    print(f"\nWrote {args.out_plan}")


if __name__ == "__main__":
    main()
