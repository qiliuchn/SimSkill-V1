#!/usr/bin/env python3
"""Render every results table into results/tables.md (source for FINDINGS.md)."""
import csv
import json
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RES = os.path.join(ROOT, "results")
sys.path.insert(0, HERE)
from summarize import load, key, mean, sd, paired, paired_class  # noqa: E402

VARS = ["conv", "rcut", "mut"]
CLASSES = ["ART_THRU", "ART_LEFT", "ART_RIGHT", "MIN_THRU", "MIN_LEFT", "MIN_RIGHT"]
O = []


def w(s=""):
    O.append(s)


def fmt(x, n=1):
    return "n/a" if x != x else f"{x:.{n}f}"


def corr(a, b):
    n = len(a)
    ma, mb = mean(a), mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    return num / (da * db) if da and db else float("nan")


def main():
    runs = load(os.path.join(RES, "results_runs.csv"))
    classes = load(os.path.join(RES, "results_classes.csv"))
    base = [r for r in runs if r["tag"] == "base"]
    cells = sorted({key(r) for r in base})

    byc = defaultdict(lambda: defaultdict(list))
    for r in base:
        byc[key(r)][r["variant"]].append(r)

    # ---------- T2 signal plans -----------------------------------------
    w("## T2. Independently sized Webster plans (phase count is a consequence of geometry)\n")
    w("| cell (D,Q,m) | conv phases / cycle s / Y | rcut phases / cycle s / Y | mut phases / cycle s / Y |")
    w("|---|---|---|---|")
    for c in cells:
        row = [f"| D{c[0]} Q{c[1]} m{c[2]:.2f} "]
        for v in VARS:
            rs = byc[c][v]
            if not rs:
                row.append("| - ")
                continue
            row.append(f"| {int(rs[0]['n_phases'])} / {rs[0]['cycle_s']:.0f} / {rs[0]['Y_flow_ratio']:.3f} ")
        w("".join(row) + "|")
    w()

    # ---------- T3 network-level ----------------------------------------
    w("\n## T3. Network-level result per cell (mean over 5 CRN seeds; completed trips only)\n")
    w("| D | Q | m | variant | phases | mean total time s | mean dist m | VMT km | VHT h | "
      "completed | still-running | never-inserted | teleports |")
    w("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for c in cells:
        if len(byc[c]) < 3:
            continue
        for v in VARS:
            rs = byc[c][v]
            if not rs:
                continue
            w(f"| {c[0]} | {c[1]} | {c[2]:.2f} | {v} | {int(rs[0]['n_phases'])} | "
              f"{fmt(mean([x['mean_totaltime_s'] for x in rs]))} | "
              f"{fmt(mean([x['mean_distance_m'] for x in rs]), 0)} | "
              f"{fmt(mean([x['VMT_km'] for x in rs]), 0)} | "
              f"{fmt(mean([x['VHT_h'] for x in rs]), 1)} | "
              f"{fmt(mean([x['completed'] for x in rs]), 0)} | "
              f"{fmt(mean([x['unfinished'] for x in rs]), 0)} | "
              f"{fmt(mean([x['never_inserted'] for x in rs]), 0)} | "
              f"{fmt(mean([x['teleports'] for x in rs]), 1)} |")
    w()

    # ---------- T4 paired CRN differences --------------------------------
    w("\n## T4. Paired (CRN) difference vs conventional; + = worse\n")
    w("| D | Q | m | alt | d mean total time s | 95% CI | d VMT % | d VHT % | d dist % | paired t |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    for c in cells:
        for alt in ("rcut", "mut"):
            p = paired(runs, c, "mean_totaltime_s", alt)
            pv = paired(runs, c, "VMT_km", alt)
            ph = paired(runs, c, "VHT_h", alt)
            pd = paired(runs, c, "mean_distance_m", alt)
            if not p:
                continue
            ci = p["ci95"]
            w(f"| {c[0]} | {c[1]} | {c[2]:.2f} | {alt} | {p['mean_diff']:+.2f} | "
              f"[{ci[0]:+.2f}, {ci[1]:+.2f}] | "
              f"{100*pv['mean_diff']/pv['base_mean']:+.2f} | "
              f"{100*ph['mean_diff']/ph['base_mean']:+.2f} | "
              f"{100*pd['mean_diff']/pd['base_mean']:+.2f} | "
              f"{p['t']:+.2f} |")
    w()

    # ---------- T5 per movement class ------------------------------------
    w("\n## T5. Per OD movement class (mean over seeds; distance AND time)\n")
    for c in cells:
        w(f"\n### cell D={c[0]} m Q={c[1]} veh/h minor-share={c[2]:.2f}\n")
        w("| class | routed | conv dist m | rcut dist m | mut dist m | conv time s | rcut time s | mut time s |"
          " rcut d time | mut d time |")
        w("|---|---|---|---|---|---|---|---|---|---|")
        for cl in CLASSES:
            g = {}
            for v in VARS:
                rs = [r for r in classes if r["tag"] == "base" and key(r) == c
                      and r["variant"] == v and r["movement_class"] == cl]
                if rs:
                    g[v] = (mean([x["mean_distance_m"] for x in rs]),
                            mean([x["mean_totaltime_s"] for x in rs]),
                            mean([x["routed"] for x in rs]))
            if len(g) < 3:
                continue
            pr = paired_class(classes, c, cl, "mean_totaltime_s", "rcut")
            pm = paired_class(classes, c, cl, "mean_totaltime_s", "mut")
            if pr is None or pm is None:
                continue
            w(f"| {cl} | {g['conv'][2]:.0f} | " +
              " | ".join(fmt(g[v][0], 0) for v in VARS) + " | " +
              " | ".join(fmt(g[v][1], 1) for v in VARS) +
              f" | {pr['mean_diff']:+.1f} | {pm['mean_diff']:+.1f} |")
    w()

    # ---------- T6 crossover instrumentation ------------------------------
    w("\n## T6. U-turn crossover as a bottleneck (median lane, demand hour + drain)\n")
    w("| D | Q | m | variant | storage m | XW maxjam m | XW jam/storage | XW overflow frac | "
      "XW mean timeloss s | XW max halt s | thru-lane maxjam m (XW) | XE maxjam m | XE overflow frac |")
    w("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for c in cells:
        for v in VARS:
            rs = byc[c][v]
            if not rs:
                continue
            w(f"| {c[0]} | {c[1]} | {c[2]:.2f} | {v} | {fmt(mean([x['ut_XW_storage_m'] for x in rs]),0)} | "
              f"{fmt(mean([x['ut_XW_maxjam_m'] for x in rs]),0)} | "
              f"{fmt(mean([x['ut_XW_jamratio'] for x in rs]),2)} | "
              f"{fmt(mean([x['ut_XW_overflow_frac'] for x in rs]),3)} | "
              f"{fmt(mean([x['ut_XW_timeloss_s'] for x in rs]),1)} | "
              f"{fmt(mean([x['ut_XW_maxhalt_s'] for x in rs]),0)} | "
              f"{fmt(mean([x['thru_XW_maxjam_m'] for x in rs]),0)} | "
              f"{fmt(mean([x['ut_XE_maxjam_m'] for x in rs]),0)} | "
              f"{fmt(mean([x['ut_XE_overflow_frac'] for x in rs]),3)} |")
    w()

    # ---------- T7 thresholds ---------------------------------------------
    w("\n## T7. Threshold scan\n")
    w("### 7a. minor-street demand share (D=400 m)\n")
    w("| Q | m | d total time rcut | sig? | d total time mut | sig? |")
    w("|---|---|---|---|---|---|")
    for c in [x for x in cells if x[0] == 400]:
        pr = paired(runs, c, "mean_totaltime_s", "rcut")
        pm = paired(runs, c, "mean_totaltime_s", "mut")
        if not pr:
            continue
        w(f"| {c[1]} | {c[2]:.2f} | {pr['mean_diff']:+.2f} | "
          f"{'yes' if abs(pr['t'])>pr['tcrit'] else 'no'} | {pm['mean_diff']:+.2f} | "
          f"{'yes' if abs(pm['t'])>pm['tcrit'] else 'no'} |")
    w("\n### 7b. crossover spacing\n")
    w("| Q | m | D | d total time rcut | d total time mut | rcut XW overflow | mut XW overflow |")
    w("|---|---|---|---|---|---|---|")
    for c in sorted(cells, key=lambda x: (x[1], x[2], x[0])):
        if len({y[0] for y in cells if y[1] == c[1] and y[2] == c[2]}) < 3:
            continue
        pr = paired(runs, c, "mean_totaltime_s", "rcut")
        pm = paired(runs, c, "mean_totaltime_s", "mut")
        if not pr:
            continue
        w(f"| {c[1]} | {c[2]:.2f} | {c[0]} | {pr['mean_diff']:+.2f} | {pm['mean_diff']:+.2f} | "
          f"{fmt(mean([x['ut_XW_overflow_frac'] for x in byc[c]['rcut']]),3)} | "
          f"{fmt(mean([x['ut_XW_overflow_frac'] for x in byc[c]['mut']]),3)} |")
    w()

    # ---------- T8 CRN variance-reduction ---------------------------------
    w("\n## T8. Replication / CRN diagnostics (metric: mean total time)\n")
    w("| D | Q | m | alt | sd conv | sd alt | corr(paired) | sd of paired diff | "
      "sd of unpaired diff | CRN variance-reduction factor |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    for c in cells:
        bys = defaultdict(dict)
        for r in base:
            if key(r) == c:
                bys[int(r["seed"])][r["variant"]] = r["mean_totaltime_s"]
        seeds = sorted(s for s in bys if len(bys[s]) == 3)
        if len(seeds) < 3:
            continue
        a = [bys[s]["conv"] for s in seeds]
        for alt in ("rcut", "mut"):
            b = [bys[s][alt] for s in seeds]
            d = [y - x for x, y in zip(a, b)]
            vu = sd(a) ** 2 + sd(b) ** 2
            vp = sd(d) ** 2
            w(f"| {c[0]} | {c[1]} | {c[2]:.2f} | {alt} | {fmt(sd(a),2)} | {fmt(sd(b),2)} | "
              f"{fmt(corr(a,b),3)} | {fmt(math.sqrt(vp),3)} | {fmt(math.sqrt(vu),3)} | "
              f"{fmt(vu/vp,2) if vp>0 else 'inf'} |")
    w()

    # ---------- T9 teleport sensitivity ------------------------------------
    w("\n## T9. Teleport-artifact sensitivity (same cells, three --time-to-teleport settings)\n")
    w("| tag (ttt) | D | Q | m | variant | teleports | completed | still-running | "
      "never-inserted | mean total time s |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    tt = defaultdict(list)
    for r in runs:
        if r["tag"].startswith("ttt") or (r["tag"] == "base" and
                                          key(r) in {(400, 3600, 0.30), (100, 3600, 0.50)}):
            tag = "base(300)" if r["tag"] == "base" else r["tag"]
            tt[(tag, key(r), r["variant"])].append(r)
    for k in sorted(tt, key=lambda k: (k[1], k[2], k[0])):
        rs = tt[k]
        rs = [r for r in rs if int(r["seed"]) <= 3]
        if not rs:
            continue
        w(f"| {k[0]} | {k[1][0]} | {k[1][1]} | {k[1][2]:.2f} | {k[2]} | "
          f"{fmt(mean([x['teleports'] for x in rs]),1)} | {fmt(mean([x['completed'] for x in rs]),0)} | "
          f"{fmt(mean([x['unfinished'] for x in rs]),0)} | {fmt(mean([x['never_inserted'] for x in rs]),0)} | "
          f"{fmt(mean([x['mean_totaltime_s'] for x in rs]))} |")
    w()

    with open(os.path.join(RES, "tables.md"), "w") as f:
        f.write("\n".join(O) + "\n")
    print("wrote", os.path.join(RES, "tables.md"), len(O), "lines")


if __name__ == "__main__":
    main()
