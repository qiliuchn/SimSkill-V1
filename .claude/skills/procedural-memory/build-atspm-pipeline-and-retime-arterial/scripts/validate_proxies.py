#!/usr/bin/env python3
"""Validate the event-log-derived ATSPM proxies against simulator GROUND TRUTH.

Proxy side  (outputs/atspm/*_<tag>.csv)  -- derived from the event log alone.
Truth side  (outputs/logs/gt_*_<tag>.csv, tripinfo_<tag>.xml) -- never seen by
            atspm_analysis.py.

CHECK A  Split failure.  Ground truth: "the queue did not clear" = the halting-
         vehicle count on that movement's lane group NEVER reached zero at any
         1 Hz sample inside the green interval.  Confusion matrix for the field-
         standard flag (GOR5&ROR5) and for the occupancy-continuity-refined flag.

CHECK B  Platoon Ratio vs measured control delay.  Truth: SUMO's own timeLoss
         accumulated by each vehicle while on that approach link (excluding the
         left-turn movement) = approach control delay.  Reported as (i) the
         across-approach correlation of PR vs mean delay and (ii) the within-
         approach per-cycle correlation of AoG vs delay.

CHECK C  Where the proxies mislead: detector length, spillback, permissive lefts.
"""
import argparse
import csv
import os
import xml.etree.ElementTree as ET
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
PHASE_GROUP = {1: ("EB", "L"), 2: ("WB", "T"), 3: ("SB", "L"), 4: ("NB", "T"),
               5: ("WB", "L"), 6: ("EB", "T"), 7: ("NB", "L"), 8: ("SB", "T")}
COORD_PHASE = {"EB": 6, "WB": 2}
STORAGE_VEH = {"minor": 320.0 / 7.5, "arterial_left": 400.0 / 7.5}


def read_csv(p):
    with open(p) as f:
        return list(csv.DictReader(f))


def mcc(tp, fp, fn, tn):
    d = np.sqrt(float(tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    return (tp * tn - fp * fn) / d if d > 0 else float("nan")


def cm_report(name, pred, act):
    tp = int(np.sum(pred & act)); fp = int(np.sum(pred & ~act))
    fn = int(np.sum(~pred & act)); tn = int(np.sum(~pred & ~act))
    prec = tp / (tp + fp) if tp + fp else float("nan")
    rec = tp / (tp + fn) if tp + fn else float("nan")
    f1 = 2 * prec * rec / (prec + rec) if prec == prec and rec == rec and prec + rec > 0 else float("nan")
    print(f"  {name}")
    print(f"      TP={tp:5d}  FP={fp:5d}  FN={fn:5d}  TN={tn:5d}   n={len(pred)}")
    print(f"      precision={prec:.3f}  recall={rec:.3f}  F1={f1:.3f}  "
          f"accuracy={(tp+tn)/len(pred):.3f}  MCC={mcc(tp,fp,fn,tn):.3f}")
    return dict(tp=tp, fp=fp, fn=fn, tn=tn, precision=prec, recall=rec, f1=f1,
                accuracy=(tp + tn) / len(pred), mcc=mcc(tp, fp, fn, tn))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--warmup", type=float, default=600.0)
    args = ap.parse_args()
    L, A = os.path.join(ROOT, "outputs", "logs"), os.path.join(ROOT, "outputs", "atspm")

    # ---------- ground-truth queue, indexed by (sig, dir, group) -> arrays ----------
    q = defaultdict(lambda: ([], []))
    for r in read_csv(os.path.join(L, f"gt_queue_{args.tag}.csv")):
        k = (r["signal_id"], r["approach_dir"], r["group"])
        q[k][0].append(float(r["t"])); q[k][1].append(int(r["halting"]))
    Q = {k: (np.array(v[0]), np.array(v[1])) for k, v in q.items()}

    cyc = read_csv(os.path.join(A, f"cycles_{args.tag}.csv"))
    veh_all = read_csv(os.path.join(L, f"gt_veh_{args.tag}.csv"))
    print(f"\n{'='*96}\nPROXY VALIDATION vs GROUND TRUTH  (run '{args.tag}')\n{'='*96}")

    # stop-bar crossing times, per (signal, phase): the phase's movements are the
    # left-turn flow for a left phase, or everything-but-the-left for a through phase.
    cross = defaultdict(list)
    for v in veh_all:
        sig, d = v["signal_id"], v["approach_dir"]
        mv, tc = v["movement"], float(v["t_cross_stopbar"])
        pL = {"EB": 1, "WB": 5, "SB": 3, "NB": 7}[d]
        pT = {"EB": 6, "WB": 2, "SB": 8, "NB": 4}[d]
        cross[(sig, pL if mv == f"{d}L_{sig}" else pT)].append(tc)
    cross = {k: np.array(sorted(v)) for k, v in cross.items()}

    # ---------------- CHECK A: split failure ----------------
    rows = []
    for r in cyc:
        sig, p = r["signal_id"], int(r["phase"])
        d, g = PHASE_GROUP[p]
        t, h = Q[(sig, d, g)]
        gs, ge, rs = (float(r["green_start_s"]), float(r["green_end_s"]), float(r["red_start_s"]))
        m = (t >= gs) & (t <= ge)
        if m.sum() < 2 or (sig, p) not in cross:
            continue
        # PRIMARY ground truth: every vehicle standing in the queue when green began
        # must cross the stop bar before the green (plus yellow) ends. Halting counts
        # alone cannot do this -- a queue that starts MOVING shows zero halting long
        # before it has actually cleared the stop bar.
        i0 = np.searchsorted(t, gs, "right") - 1
        nq = int(h[max(i0, 0)])
        X = cross[(sig, p)]
        nserved = int(np.searchsorted(X, rs, "right") - np.searchsorted(X, gs, "left"))
        qres = int(h[m][-1])
        rows.append(dict(sig=sig, phase=p, mv=r["movement"], detlen=float(r["det_length_m"]),
                         std=int(r["split_failure"]), ref=int(r["sf_refined"]),
                         sus=int(r["sf_sustained"]),
                         gt=int(nserved < nq),                            # GT-A (primary)
                         gt_neverzero=int(not bool((h[m] == 0).any())),   # GT-B
                         gt_res2=int(qres >= 1),                          # GT-C
                         nq=nq, nserved=nserved,
                         qmax=int(h[m].max()), qres=qres,
                         gor=float(r["GOR5"]), ror=float(r["ROR5"]), tail=float(r["occ_tail10"])))
    std = np.array([r["std"] for r in rows], bool)
    ref = np.array([r["ref"] for r in rows], bool)
    sus = np.array([r["sus"] for r in rows], bool)
    gt = np.array([r["gt"] for r in rows], bool)
    gt1 = np.array([r["gt_neverzero"] for r in rows], bool)
    gt3 = np.array([r["gt_res2"] for r in rows], bool)
    print(f"\nCHECK A -- SPLIT FAILURE, all {len(rows)} phase-green instances "
          f"(4 signals x 8 phases x ~72 cycles)")
    print("  The ground-truth definition matters; three are reported.")
    print(f"    GT-A queued-at-green-start vehicles NOT all served  [PRIMARY]  : {100*gt.mean():5.1f}%")
    print(f"    GT-B halting count never reached 0 during green (gridlock only) : {100*gt1.mean():5.1f}%")
    print(f"    GT-C >=1 vehicle still HALTED when green ended                  : {100*gt3.mean():5.1f}%")
    res = {}
    print("\n  --- against GT-A (primary) ---")
    res["standard"] = cm_report("field-standard  GOR5>=0.80 AND ROR5>=0.80", std, gt)
    res["sustained"] = cm_report("standard + 3-of-5-consecutive-cycles rule", sus, gt)
    res["refined"] = cm_report("refined: standard + occupancy continuity across end of green", ref, gt)
    print("\n  --- sensitivity of the field-standard flag to the ground-truth definition ---")
    res["standard_vs_GTB"] = cm_report("vs GT-B (gridlock only)", std, gt1)
    res["standard_vs_GTC"] = cm_report("vs GT-C (residual halted)", std, gt3)

    print("\n  per-movement-class breakdown (field-standard flag):")
    print(f"      {'class':26s} {'n':>5s} {'gt_fail%':>9s} {'std_fail%':>10s} {'FP':>5s} {'FN':>5s} "
          f"{'ref_FP':>7s} {'ref_FN':>7s}")
    for label, sel in (("arterial through (15 m)", lambda r: r["phase"] in (2, 6)),
                       ("cross-st through (15 m)", lambda r: r["phase"] in (4, 8)),
                       ("left turns (30 m det)", lambda r: r["phase"] in (1, 3, 5, 7))):
        idx = [i for i, r in enumerate(rows) if sel(r)]
        s, g_, rf = std[idx], gt[idx], ref[idx]
        print(f"      {label:26s} {len(idx):5d} {100*g_.mean():8.1f}% {100*s.mean():9.1f}% "
              f"{int(np.sum(s & ~g_)):5d} {int(np.sum(~s & g_)):5d} "
              f"{int(np.sum(rf & ~g_)):7d} {int(np.sum(~rf & g_)):7d}")

    with open(os.path.join(ROOT, "outputs", "tables", f"split_failure_validation_{args.tag}.csv"),
              "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)

    # ---------------- CHECK B: platoon ratio vs control delay ----------------
    veh = read_csv(os.path.join(L, f"gt_veh_{args.tag}.csv"))
    coord = read_csv(os.path.join(A, f"coordination_{args.tag}.csv"))
    pcd = read_csv(os.path.join(A, f"pcd_points_{args.tag}.csv"))
    by_appr = defaultdict(list)
    for v in veh:
        if float(v["t_cross_stopbar"]) < args.warmup:
            continue
        d = v["approach_dir"]
        if d not in ("EB", "WB") or v["movement"] == f"{d}L_{v['signal_id']}":
            continue
        by_appr[(v["signal_id"], d)].append((float(v["t_cross_stopbar"]), float(v["link_timeloss_s"])))

    print("\nCHECK B -- PLATOON RATIO vs MEASURED CONTROL DELAY (coordinated through movement)")
    print(f"  {'sig':4s} {'dir':4s} {'AoG%':>6s} {'PR':>6s} {'n_veh':>7s} "
          f"{'mean delay s':>13s} {'p85 delay s':>12s}")
    prs, dls, aogs = [], [], []
    percyc = []
    for c in coord:
        k = (c["signal_id"], c["direction"])
        if k not in by_appr:
            continue
        dl = np.array([x[1] for x in by_appr[k]])
        prs.append(float(c["PR_raw"])); dls.append(dl.mean()); aogs.append(float(c["AoG_pct_raw"]))
        print(f"  {k[0]:4s} {k[1]:4s} {float(c['AoG_pct_raw']):6.1f} {float(c['PR_raw']):6.2f} "
              f"{len(dl):7d} {dl.mean():13.2f} {np.percentile(dl,85):12.2f}")
    prs, dls, aogs = map(np.array, (prs, dls, aogs))
    print(f"\n  across-approach Pearson r(PR, mean control delay)  = {np.corrcoef(prs, dls)[0,1]:+.3f}"
          f"   (n={len(prs)} approaches)")
    print(f"  across-approach Pearson r(AoG%, mean control delay) = {np.corrcoef(aogs, dls)[0,1]:+.3f}")

    # within-approach, per cycle
    cyc_aog = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    cyc_start = defaultdict(dict)
    for p in pcd:
        k = (p["signal_id"], p["direction"]); ci = int(p["cycle_idx"])
        cyc_aog[k][ci][0] += int(p["on_green"]); cyc_aog[k][ci][1] += 1
        cyc_start[k][ci] = float(p["cycle_start_s"])
    print(f"\n  within-approach per-cycle correlation of AoG vs mean control delay:")
    print(f"      {'sig':4s} {'dir':4s} {'cycles':>7s} {'r(AoG,delay)':>13s}")
    rs_all = []
    for k in sorted(cyc_aog):
        cis = sorted(c for c in cyc_aog[k] if cyc_aog[k][c][1] >= 5)
        starts = np.array([cyc_start[k][c] for c in cis])
        aog_c = np.array([cyc_aog[k][c][0] / cyc_aog[k][c][1] for c in cis])
        arr = np.array(sorted(by_appr[k]))
        idx = np.searchsorted(starts, arr[:, 0], "right") - 1
        dmean = np.full(len(cis), np.nan)
        for i in range(len(cis)):
            sel = idx == i
            if sel.sum() >= 3:
                dmean[i] = arr[sel, 1].mean()
        ok = ~np.isnan(dmean)
        r = np.corrcoef(aog_c[ok], dmean[ok])[0, 1]
        rs_all.append(r)
        print(f"      {k[0]:4s} {k[1]:4s} {int(ok.sum()):7d} {r:+13.3f}")
    print(f"      {'mean within-approach r':26s} {np.mean(rs_all):+.3f}")

    # ---------------- CHECK C: where the proxies mislead ----------------
    print("\nCHECK C -- WHERE THE PROXIES MISLEAD")
    fp30 = [r for r in rows if r["detlen"] == 30.0 and r["std"] and not r["gt"]]
    tp30 = [r for r in rows if r["detlen"] == 30.0 and r["std"] and r["gt"]]
    fp15 = [r for r in rows if r["detlen"] == 15.0 and r["std"] and not r["gt"]]
    print(f"\n  (1) SHORT QUEUE ON A LONG DETECTOR")
    print(f"      30 m left-turn detectors: {len(fp30)} false positives, {len(tp30)} true positives")
    if fp30:
        print(f"      ground-truth max queue in those FALSE-positive cycles: "
              f"median {np.median([r['qmax'] for r in fp30]):.1f} veh, "
              f"mean {np.mean([r['qmax'] for r in fp30]):.2f} veh, "
              f"{100*np.mean([r['qmax']<=2 for r in fp30]):.0f}% had <=2 vehicles")
    print(f"      15 m through detectors  : {len(fp15)} false positives"
          + (f", median gt max queue {np.median([r['qmax'] for r in fp15]):.1f} veh" if fp15 else ""))

    print(f"\n  (2) SPILLBACK / STORAGE SATURATION")
    for sig, d, g, lab in (("J2", "NB", "T", "J2 NB through (320 m stub, ~42 veh storage)"),
                           ("J2", "NB", "L", "J2 NB left bay"),
                           ("J1", "EB", "L", "J1 EB left bay (400+ m)")):
        t, h = Q[(sig, d, g)]
        m = t >= args.warmup
        print(f"      {lab:48s} max queue {h[m].max():3d} veh  "
              f"p95 {np.percentile(h[m],95):5.1f}  mean {h[m].mean():5.1f}")

    print(f"\n  (3) PERMISSIVE LEFT TURNS (J3 arterial lefts are protected-permissive;")
    print(f"      J0/J1/J2 arterial lefts are fully protected)")
    print(f"      {'signal':7s} {'phase':6s} {'greens':7s} {'std_fail%':10s} {'gt_fail%':9s} "
          f"{'FP':>4s} {'FN':>4s} {'mean gt qmax':>13s}")
    for sig in ("J0", "J1", "J2", "J3"):
        for p in (1, 5):
            sub = [r for r in rows if r["sig"] == sig and r["phase"] == p]
            if not sub:
                continue
            s = np.array([r["std"] for r in sub], bool); g_ = np.array([r["gt"] for r in sub], bool)
            print(f"      {sig:7s} {p:<6d} {len(sub):7d} {100*s.mean():9.1f}% {100*g_.mean():8.1f}% "
                  f"{int(np.sum(s&~g_)):4d} {int(np.sum(~s&g_)):4d} "
                  f"{np.mean([r['qmax'] for r in sub]):13.2f}")
    print("      NOTE: at J3 the protected left phase is SKIPPED on cycles where the")
    print("      permissive movement already cleared demand -> fewer green instances")
    print("      than cycles, and the ATSPM record for that phase is simply absent.")

    # ---------------- aggregate network ground truth ----------------
    tri = ET.parse(os.path.join(L, f"tripinfo_{args.tag}.xml")).getroot()
    dur, tl, wt, n = [], [], [], 0
    art = []
    for t in tri.findall("tripinfo"):
        if float(t.get("depart")) < args.warmup:
            continue
        n += 1
        dur.append(float(t.get("duration"))); tl.append(float(t.get("timeLoss")))
        wt.append(float(t.get("waitingTime")))
        if t.get("id").split(".")[0].startswith(("EBT", "WBT")):
            art.append(float(t.get("timeLoss")))
    print(f"\nAGGREGATE GROUND TRUTH (tripinfo, departures after warmup)")
    print(f"  completed trips = {n}   mean duration = {np.mean(dur):.2f} s   "
          f"mean timeLoss = {np.mean(tl):.2f} s   mean waiting = {np.mean(wt):.2f} s")
    print(f"  full-corridor through vehicles (EBT+WBT): n={len(art)}  "
          f"mean timeLoss = {np.mean(art):.2f} s")

    import json
    with open(os.path.join(ROOT, "outputs", "tables", f"validation_{args.tag}.json"), "w") as f:
        json.dump({"split_failure": res,
                   "r_PR_vs_delay": float(np.corrcoef(prs, dls)[0, 1]),
                   "r_AoG_vs_delay": float(np.corrcoef(aogs, dls)[0, 1]),
                   "mean_within_approach_r": float(np.mean(rs_all)),
                   "trips": n, "mean_timeLoss": float(np.mean(tl)),
                   "mean_duration": float(np.mean(dur)),
                   "corridor_through_timeLoss": float(np.mean(art)),
                   "n_corridor_through": len(art)}, f, indent=2)


if __name__ == "__main__":
    main()
