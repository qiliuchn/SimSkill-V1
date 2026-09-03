"""Turn the threshold sweep into the reportable AID comparison: DR at matched FAR budgets,
MTTD / localization at those operating points, DR-FAR curves, and the failure-mode analysis."""
import os, sys, json, csv
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import *
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

RES = os.path.join(RESULTS_DIR, "sweep_all.json")
ALGOS = ["california8", "california8b", "snd", "ewma", "fixed_occ", "fixed_speed"]
NICE = {"california8": "California #8", "california8b": "California #8 (2-stage)", "snd": "SND", "ewma": "EWMA",
        "fixed_occ": "fixed occupancy", "fixed_speed": "fixed speed"}
BUDGETS = [0.0, 0.01, 0.05, 0.10, 0.50]     # false alarms per detector-hour
os.makedirs(PLOTS_DIR, exist_ok=True)


def load():
    rows = json.load(open(RES))
    out = {}
    for r in rows:
        out.setdefault((r["level"], r["spacing"], r["algo"]), []).append(r)
    return out


def best_at(rows, budget):
    """Highest-DR operating point subject to FAR_per_unit_hour <= budget; ties -> lower FAR,
    then lower MTTD."""
    ok = [r for r in rows if r["FAR_per_unit_hour"] <= budget + 1e-12]
    if not ok:
        return None
    return sorted(ok, key=lambda r: (-r["DR"], r["FAR_per_unit_hour"],
                                     r["MTTD"] if r["MTTD"] is not None else 1e9))[0]


def main():
    D = load()
    # ---------------------------------------------------------------- Table 1: DR @ FAR budget
    p = os.path.join(RESULTS_DIR, "table1_dr_at_matched_far.csv")
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["demand", "spacing_m", "algorithm", "FAR_budget_per_det_hour", "DR",
                    "FAR_achieved_per_det_hour", "FAR_per_control_day", "MTTD_s",
                    "MTTD_median_s", "LOC_err_stations", "n_units", "params"])
        for level in DEMAND_LEVELS:
            for spacing in (250, 500, 1000):
                for algo in ALGOS:
                    rows = D[(level, spacing, algo)]
                    for b in BUDGETS:
                        r = best_at(rows, b)
                        if r is None:
                            w.writerow([level, spacing, algo, b, "", "", "", "", "", "", "", ""])
                            continue
                        w.writerow([level, spacing, algo, b, f"{r['DR']:.3f}",
                                    f"{r['FAR_per_unit_hour']:.4f}", f"{r['FAR_per_day']:.3f}",
                                    "" if r["MTTD"] is None else f"{r['MTTD']:.1f}",
                                    "" if r["MTTD_median"] is None else f"{r['MTTD_median']:.1f}",
                                    "" if r["LOC_mean"] is None else f"{r['LOC_mean']:.2f}",
                                    r["n_units"], json.dumps(r["params"])])
    print("wrote", p)

    # ------------------------------------------------- Table 2: FAR / MTTD at matched DR
    # The matched-FAR view asks "who detects most"; this asks "who is cheapest and fastest
    # once a required detection rate is fixed" -- the view in which a comparative algorithm's
    # spatial discrimination should pay off if it pays off anywhere.
    p2 = os.path.join(RESULTS_DIR, "table2_far_mttd_at_matched_dr.csv")
    DRT = [0.70, 0.80, 0.90, 0.95]
    with open(p2, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["demand", "spacing_m", "algorithm", "DR_target", "DR_achieved",
                    "min_FAR_per_det_hour", "FAR_per_control_day", "MTTD_s",
                    "LOC_err_stations", "params"])
        for level in DEMAND_LEVELS:
            for spacing in (250, 500, 1000):
                for algo in ALGOS:
                    rows = D[(level, spacing, algo)]
                    for t in DRT:
                        ok = [r for r in rows if r["DR"] >= t]
                        if not ok:
                            w.writerow([level, spacing, algo, t, "", "", "", "", "", ""])
                            continue
                        r = sorted(ok, key=lambda r: (r["FAR_per_unit_hour"],
                                                      r["MTTD"] if r["MTTD"] else 1e9))[0]
                        w.writerow([level, spacing, algo, t, f"{r['DR']:.3f}",
                                    f"{r['FAR_per_unit_hour']:.4f}", f"{r['FAR_per_day']:.3f}",
                                    "" if r["MTTD"] is None else f"{r['MTTD']:.1f}",
                                    "" if r["LOC_mean"] is None else f"{r['LOC_mean']:.2f}",
                                    json.dumps(r["params"])])
    print("wrote", p2)
    print("\n=== min FAR/det-hr (MTTD s) at matched DR >= 0.80, spacing 500 m ===")
    for level in DEMAND_LEVELS:
        line = f"  {level:9s}"
        for algo in ALGOS:
            ok = [r for r in D[(level, 500, algo)] if r["DR"] >= 0.80]
            if not ok:
                line += f"  {NICE[algo]}: unreachable"
            else:
                r = sorted(ok, key=lambda r: (r["FAR_per_unit_hour"], r["MTTD"] or 1e9))[0]
                line += f"  {NICE[algo]}: {r['FAR_per_unit_hour']:.4f} ({r['MTTD']:.0f}s)"
        print(line)

    # ---------------------------------------------------------------- console headline table
    print("\n=== DR (MTTD s / loc err stations) at matched FAR budgets, spacing 500 m ===")
    for level in DEMAND_LEVELS:
        print(f"\n-- demand={level}")
        hdr = "  algorithm      " + "".join(f"{'FAR<=' + str(b):>22s}" for b in BUDGETS)
        print(hdr)
        for algo in ALGOS:
            rows = D[(level, 500, algo)]
            line = f"  {NICE[algo]:14s}"
            for b in BUDGETS:
                r = best_at(rows, b)
                if r is None:
                    line += f"{'--':>22s}"
                else:
                    m = "-" if r["MTTD"] is None else f"{r['MTTD']:.0f}"
                    l = "-" if r["LOC_mean"] is None else f"{r['LOC_mean']:.1f}"
                    line += f"{f'{r[chr(68)+chr(82)]:.2f} ({m}s/{l})':>22s}"
            print(line)

    # ---------------------------------------------------------------- DR-FAR curves
    for level in DEMAND_LEVELS:
        fig, axes = plt.subplots(1, 3, figsize=(15, 4.4), sharey=True)
        for ax, spacing in zip(axes, (250, 500, 1000)):
            for algo in ALGOS:
                rows = sorted(D[(level, spacing, algo)], key=lambda r: r["FAR_per_unit_hour"])
                fr = [r for r in rows if r["on_frontier"]]
                x = [r["FAR_per_unit_hour"] for r in fr]
                y = [r["DR"] for r in fr]
                ax.step(x, y, where="post", marker="o", ms=3.5, label=NICE[algo])
            ax.set_xscale("symlog", linthresh=1e-3)
            ax.set_xlabel("false alarms per detector-hour (control days)")
            ax.set_title(f"station spacing {spacing} m")
            ax.grid(alpha=.3)
            ax.set_ylim(-0.03, 1.03)
        axes[0].set_ylabel("detection rate")
        axes[0].legend(fontsize=8, loc="lower right")
        fig.suptitle(f"DR-FAR tradeoff, demand = {level} "
                     f"({sum(DEMAND_LEVELS[level])} veh/h = "
                     f"{100*sum(DEMAND_LEVELS[level])/BOTTLENECK_CAPACITY:.0f}% of bottleneck capacity)")
        fig.tight_layout()
        q = os.path.join(PLOTS_DIR, f"dr_far_{level}.png")
        fig.savefig(q, dpi=130); plt.close(fig)
        print("wrote", q)

    # ---------------------------------------------------------------- failure-mode analysis
    fm = []
    for level in DEMAND_LEVELS:
        for spacing in (250, 500, 1000):
            for algo in ALGOS:
                r = best_at(D[(level, spacing, algo)], 0.05)
                if r is None or "per_day" not in r:
                    continue
                for d in r["per_day"]:
                    fm.append(dict(level=level, spacing=spacing, algo=algo, **d))
    p = os.path.join(RESULTS_DIR, "failure_modes.csv")
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(fm[0].keys()))
        w.writeheader()
        w.writerows(fm)
    print("wrote", p, len(fm), "rows")

    # stratified DR at FAR<=0.05
    print("\n=== DR at FAR<=0.05/det-hr, stratified by severity (lanes blocked) ===")
    for spacing in (250, 500, 1000):
        print(f"\n-- spacing {spacing} m")
        print("  algorithm        " + "".join(f"{lv + ' 1ln':>11s}{lv + ' 2ln':>11s}" for lv in DEMAND_LEVELS))
        for algo in ALGOS:
            line = f"  {NICE[algo]:16s}"
            for level in DEMAND_LEVELS:
                sub = [d for d in fm if d["level"] == level and d["spacing"] == spacing
                       and d["algo"] == algo]
                for nb in (1, 2):
                    s = [d for d in sub if d["n_block"] == nb]
                    line += f"{(sum(d['detected'] for d in s)/len(s) if s else float('nan')):>11.2f}"
            print(line)

    # distance-to-upstream-station effect (the "never queues past the nearest detector" mode)
    print("\n=== DR vs distance from incident to nearest upstream station (FAR<=0.05) ===")
    for level in DEMAND_LEVELS:
        sub = [d for d in fm if d["level"] == level and d["spacing"] == 500
               and d["algo"] == "california8"]
        for lo, hi in ((0, 150), (150, 300), (300, 450), (450, 600)):
            s = [d for d in sub if lo <= d["dist_to_upstream_station"] < hi]
            if s:
                print(f"  {level:9s} {lo:3d}-{hi:3d} m: n={len(s):3d} DR={sum(d['detected'] for d in s)/len(s):.2f}")
    return D, fm


if __name__ == "__main__":
    main()
