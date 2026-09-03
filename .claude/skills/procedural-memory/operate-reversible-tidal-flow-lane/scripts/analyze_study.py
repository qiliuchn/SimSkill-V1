#!/usr/bin/env python3
"""Aggregate the policy comparison and the split sweep into tables + the plot.

Because every policy at a given (split, seed) is driven by the SAME demand file
(Common Random Numbers, see `quantify-sumo-run-to-run-variability`), the
policy contrasts are reported as PAIRED differences with paired-t confidence
intervals, alongside the per-cell means with their own CIs.

Writes:
  outputs/analysis/sweep_table.csv
  outputs/analysis/day_table.csv
  outputs/analysis/paired_contrasts.csv
  outputs/analysis/study_summary.json
  outputs/plots/net_delay_vs_split.png
"""
import csv
import json
import math
import os
import statistics as st
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ANADIR, PLOTDIR, ensure_dirs

# two-sided t critical values, alpha = 0.05
T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447,
       7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228, 14: 2.145, 19: 2.093}
PER_LANE_CAP_VPH = 1032.0   # measured, outputs/analysis/capacity_measurement.json


def ci95(vals):
    n = len(vals)
    if n < 2:
        return (st.mean(vals) if vals else 0.0), 0.0
    m = st.mean(vals)
    s = st.stdev(vals)
    t = T95.get(n - 1, 1.96)
    return m, t * s / math.sqrt(n)


def load(mode):
    p = os.path.join(ANADIR, f"{mode}_runs.json")
    if not os.path.exists(p):
        return []
    return [r for r in json.load(open(p)) if "error" not in r]


def sweep_tables():
    rows = load("sweep")
    if not rows:
        return None
    cells = defaultdict(list)
    for r in rows:
        cells[(round(r["split"], 2), r["policy"])].append(r)

    table = []
    for (sp, pol), rs in sorted(cells.items()):
        ph = [r["person_hours_delay_corridor"] for r in rs]
        m, h = ci95(ph)
        eb, _ = ci95([r["ph_delay_EB"] for r in rs])
        wb, _ = ci95([r["ph_delay_WB"] for r in rs])
        table.append(dict(
            split_major_pct=int(sp * 100), policy=pol, n_seeds=len(rs),
            ph_delay_corridor_mean=round(m, 2), ph_delay_corridor_ci95=round(h, 2),
            ph_delay_EB_mean=round(eb, 2), ph_delay_WB_mean=round(wb, 2),
            changeovers_mean=round(st.mean([r["n_changeovers"] for r in rs]), 2),
            clearance_s_mean=round(st.mean(
                [c["clearance_s"] for r in rs for c in r["changeovers"]]), 1)
                if any(r["changeovers"] for r in rs) else 0.0,
            arrived_mean=round(st.mean([r["arrived_corridor"] for r in rs]), 1),
            never_inserted_mean=round(st.mean([r["never_inserted_corridor"] for r in rs]), 1),
            unfinished_mean=round(st.mean([r["unfinished_corridor"] for r in rs]), 1),
            teleports_mean=round(st.mean([r["teleports"] for r in rs]), 1),
            headon_steps_total=sum(r["headon_steps"] for r in rs)))

    # paired contrasts, matched on seed
    by = defaultdict(dict)
    for r in rows:
        by[(round(r["split"], 2), r["seed"])][r["policy"]] = r
    contrasts = []
    for treat, base in (("B", "A"), ("C", "A"), ("C", "B")):
        for sp in sorted({k[0] for k in by}):
            d = [by[k][treat]["person_hours_delay_corridor"]
                 - by[k][base]["person_hours_delay_corridor"]
                 for k in by if k[0] == sp and treat in by[k] and base in by[k]]
            if not d:
                continue
            m, h = ci95(d)
            contrasts.append(dict(
                contrast=f"{treat} - {base}", split_major_pct=int(sp * 100),
                n_pairs=len(d), mean_diff_person_hours=round(m, 2),
                ci95_halfwidth=round(h, 2), lo=round(m - h, 2), hi=round(m + h, 2),
                significant=bool(abs(m) > h),
                favours=("reversal" if m < 0 else "no reversal") if abs(m) > h else "tie",
                per_seed_diffs=[round(x, 2) for x in d]))
    return table, contrasts


def day_table():
    rows = load("day")
    if not rows:
        return None
    out = []
    by_pol = defaultdict(list)
    for r in rows:
        by_pol[r["policy"]].append(r)
    for pol, rs in sorted(by_pol.items()):
        ph = [r["person_hours_delay_corridor"] for r in rs]
        m, h = ci95(ph)
        allch = [c for r in rs for c in r["changeovers"]]
        out.append(dict(
            policy=pol, n_seeds=len(rs),
            ph_delay_corridor_mean=round(m, 2), ph_delay_corridor_ci95=round(h, 2),
            ph_delay_EB_mean=round(st.mean([r["ph_delay_EB"] for r in rs]), 2),
            ph_delay_WB_mean=round(st.mean([r["ph_delay_WB"] for r in rs]), 2),
            changeovers_per_day_mean=round(st.mean([r["n_changeovers"] for r in rs]), 2),
            changeovers_per_day_min=min(r["n_changeovers"] for r in rs),
            changeovers_per_day_max=max(r["n_changeovers"] for r in rs),
            mean_clearance_s=round(st.mean([c["clearance_s"] for c in allch]), 1) if allch else 0.0,
            max_clearance_s=max([c["clearance_s"] for c in allch]) if allch else 0.0,
            total_dead_time_s_mean=round(st.mean(
                [sum(c["clearance_s"] for c in r["changeovers"]) for r in rs]), 1),
            forgone_lane_entries_mean=round(st.mean(
                [sum(c["clearance_s"] for c in r["changeovers"]) for r in rs])
                * PER_LANE_CAP_VPH / 3600.0, 1),
            all_grants_at_zero_occupancy=all(c["occ_at_grant"] == 0 for c in allch),
            arrived_mean=round(st.mean([r["arrived_corridor"] for r in rs]), 1),
            never_inserted_mean=round(st.mean([r["never_inserted_corridor"] for r in rs]), 1),
            teleports_mean=round(st.mean([r["teleports"] for r in rs]), 1),
            headon_steps_total=sum(r["headon_steps"] for r in rs)))
    # paired contrasts
    by_seed = defaultdict(dict)
    for r in rows:
        by_seed[r["seed"]][r["policy"]] = r
    contrasts = []
    for treat, base in (("B", "A"), ("C", "A"), ("C", "B")):
        d = [by_seed[s][treat]["person_hours_delay_corridor"]
             - by_seed[s][base]["person_hours_delay_corridor"]
             for s in by_seed if treat in by_seed[s] and base in by_seed[s]]
        if not d:
            continue
        m, h = ci95(d)
        contrasts.append(dict(contrast=f"{treat} - {base}", n_pairs=len(d),
                              mean_diff_person_hours=round(m, 2),
                              ci95_halfwidth=round(h, 2),
                              lo=round(m - h, 2), hi=round(m + h, 2),
                              significant=bool(abs(m) > h),
                              per_seed_diffs=[round(x, 2) for x in d]))
    return out, contrasts


def breakeven(contrasts, label="B - A"):
    pts = sorted([(c["split_major_pct"], c["mean_diff_person_hours"])
                  for c in contrasts if c["contrast"] == label])
    for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
        if y0 > 0 >= y1:
            return round(x0 + (x1 - x0) * y0 / (y0 - y1), 1), pts
    return None, pts


def plot(table, contrasts, be):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2))
    colors = {"A": "#4C6EF5", "B": "#E8590C", "C": "#2F9E44"}
    names = {"A": "A  static 3+3", "B": "B  fixed schedule",
             "C": "C  demand-responsive"}
    ax = axes[0]
    for pol in ("A", "B", "C"):
        rs = sorted([r for r in table if r["policy"] == pol],
                    key=lambda r: r["split_major_pct"])
        x = [r["split_major_pct"] for r in rs]
        y = [r["ph_delay_corridor_mean"] for r in rs]
        e = [r["ph_delay_corridor_ci95"] for r in rs]
        ax.errorbar(x, y, yerr=e, marker="o", capsize=3, label=names[pol],
                    color=colors[pol], lw=2)
    ax.set_xlabel("major-direction share of a fixed 4600 veh/h total (%)")
    ax.set_ylabel("corridor person-hours of delay\n(BOTH directions, censoring-robust)")
    ax.set_title("Total corridor delay vs directional split")
    ax.grid(alpha=0.3)
    ax.legend()

    ax = axes[1]
    for lab, col in (("B - A", "#E8590C"), ("C - A", "#2F9E44")):
        cs = sorted([c for c in contrasts if c["contrast"] == lab],
                    key=lambda c: c["split_major_pct"])
        x = [c["split_major_pct"] for c in cs]
        y = [c["mean_diff_person_hours"] for c in cs]
        e = [c["ci95_halfwidth"] for c in cs]
        ax.errorbar(x, y, yerr=e, marker="s", capsize=3, color=col, lw=2,
                    label=f"{lab} (paired, 5 seeds)")
    ax.axhline(0, color="k", lw=1)
    if be:
        ax.axvline(be, color="#C92A2A", ls="--", lw=2)
        lo, hi = ax.get_ylim()
        ax.annotate(f"break-even\n{be}% / {100-be:.1f}%", xy=(be, 0),
                    xytext=(be + 1.0, lo + (hi - lo) * 0.16),
                    color="#C92A2A", fontsize=10, fontweight="bold")
    ax.set_xlabel("major-direction share (%)")
    ax.set_ylabel("change in corridor person-hours of delay\n(negative = reversal helps)")
    ax.set_title("Net effect of reversing a lane, both directions charged")
    ax.grid(alpha=0.3)
    ax.legend(loc="lower left")
    fig.suptitle("Reversible (tidal-flow) lane: net corridor benefit vs demand asymmetry",
                 fontsize=13)
    fig.tight_layout()
    p = os.path.join(PLOTDIR, "net_delay_vs_split.png")
    fig.savefig(p, dpi=150)
    print("wrote", p)
    return p


def main():
    ensure_dirs()
    summary = {}
    sw = sweep_tables()
    if sw:
        table, contrasts = sw
        with open(os.path.join(ANADIR, "sweep_table.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(table[0].keys()))
            w.writeheader()
            w.writerows(table)
        with open(os.path.join(ANADIR, "paired_contrasts.csv"), "w", newline="") as f:
            fn = [k for k in contrasts[0].keys() if k != "per_seed_diffs"]
            w = csv.DictWriter(f, fieldnames=fn, extrasaction="ignore")
            w.writeheader()
            w.writerows(contrasts)
        be, pts = breakeven(contrasts, "B - A")
        beC, ptsC = breakeven(contrasts, "C - A")
        summary["sweep_table"] = table
        summary["sweep_contrasts"] = contrasts
        summary["breakeven_split_pct_B_vs_A"] = be
        summary["breakeven_split_pct_C_vs_A"] = beC
        summary["breakeven_bracketing_points_B_vs_A"] = pts
        plot(table, contrasts, be)
        print("\n=== SWEEP (person-hours of delay, both directions) ===")
        for r in table:
            print(f"  {r['split_major_pct']}/{100-r['split_major_pct']}  {r['policy']}  "
                  f"{r['ph_delay_corridor_mean']:9.2f} +-{r['ph_delay_corridor_ci95']:6.2f}  "
                  f"EB {r['ph_delay_EB_mean']:8.2f}  WB {r['ph_delay_WB_mean']:8.2f}  "
                  f"chg {r['changeovers_mean']}  headon {r['headon_steps_total']}")
        print("\n=== PAIRED CONTRASTS ===")
        for c in contrasts:
            print(f"  {c['contrast']}  {c['split_major_pct']}%  "
                  f"{c['mean_diff_person_hours']:9.2f} [{c['lo']:9.2f},{c['hi']:9.2f}]  "
                  f"{'SIG' if c['significant'] else '   '}  {c['favours']}")
        print(f"\nbreak-even (B vs A): {be}%   (C vs A): {beC}%")

    dy = day_table()
    if dy:
        table, contrasts = dy
        with open(os.path.join(ANADIR, "day_table.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(table[0].keys()))
            w.writeheader()
            w.writerows(table)
        summary["day_table"] = table
        summary["day_contrasts"] = contrasts
        print("\n=== FULL DAY ===")
        for r in table:
            print(" ", json.dumps(r))
        print("\n=== DAY PAIRED CONTRASTS ===")
        for c in contrasts:
            print(" ", json.dumps(c))

    with open(os.path.join(ANADIR, "study_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print("\nwrote", os.path.join(ANADIR, "study_summary.json"))


if __name__ == "__main__":
    main()
