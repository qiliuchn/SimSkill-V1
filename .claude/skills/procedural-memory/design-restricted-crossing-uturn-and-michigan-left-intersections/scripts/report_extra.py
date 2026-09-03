#!/usr/bin/env python3
"""Tables for the crossover-control test, the SSM/conflict check and the
rerouting robustness check -> results/tables_extra.md"""
import json
import os
import statistics as st
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RES = os.path.join(ROOT, "results")
sys.path.insert(0, HERE)
from analyze import analyze_run  # noqa: E402

O = []


def w(s=""):
    O.append(s)


def main():
    # ---- crossover control ------------------------------------------------
    xr = os.path.join(ROOT, "runs_xsig")
    rows = []
    if os.path.isdir(xr):
        for n in sorted(os.listdir(xr)):
            d = os.path.join(xr, n)
            if os.path.exists(os.path.join(d, "DONE")):
                r, _ = analyze_run(d)
                r["mode"] = n.split("_")[0]
                rows.append(r)
    g = defaultdict(list)
    for r in rows:
        g[(int(r["D"]), int(r["Q"]), round(r["m"], 2), r["variant"], r["mode"])].append(r)
    w("## T10. Crossover control: unsignalized yield vs signalized crossover\n")
    w("| D | Q | m | variant | crossover control | mean total time s | completed | "
      "still-running | teleports | XW U-turn maxjam m | XW overflow frac |")
    w("|---|---|---|---|---|---|---|---|---|---|---|")
    for k in sorted(g):
        rs = g[k]
        w(f"| {k[0]} | {k[1]} | {k[2]:.2f} | {k[3]} | {k[4]} | "
          f"{st.mean([x['mean_totaltime_s'] for x in rs]):.1f} | "
          f"{st.mean([x['completed'] for x in rs]):.0f} | "
          f"{st.mean([x['unfinished'] for x in rs]):.0f} | "
          f"{st.mean([x['teleports'] for x in rs]):.1f} | "
          f"{st.mean([x['ut_XW_maxjam_m'] for x in rs]):.0f} | "
          f"{st.mean([x['ut_XW_overflow_frac'] for x in rs]):.3f} |")
    w()
    # paired yield->xsig effect
    w("\n### Paired effect of signalizing the crossovers (same seed, + = worse)\n")
    w("| D | Q | m | variant | d mean total time s | d completed |")
    w("|---|---|---|---|---|---|")
    bys = defaultdict(dict)
    for r in rows:
        bys[(int(r["D"]), int(r["Q"]), round(r["m"], 2), r["variant"], int(r["seed"]))][r["mode"]] = r
    agg = defaultdict(list)
    for k, v in bys.items():
        if "yield" in v and "xsig" in v:
            agg[k[:4]].append((v["xsig"]["mean_totaltime_s"] - v["yield"]["mean_totaltime_s"],
                               v["xsig"]["completed"] - v["yield"]["completed"]))
    for k in sorted(agg):
        d = agg[k]
        w(f"| {k[0]} | {k[1]} | {k[2]:.2f} | {k[3]} | {st.mean([x[0] for x in d]):+.1f} | "
          f"{st.mean([x[1] for x in d]):+.0f} |")
    w()

    # ---- conflict points ---------------------------------------------------
    cp = json.load(open(os.path.join(RES, "conflict_points.json")))
    w("\n## T11. Movement-level conflict points counted from the compiled net\n")
    w("| variant | main junction crossing | merging | diverging | main junction TOTAL | "
      "system crossing | merging | diverging | system TOTAL |")
    w("|---|---|---|---|---|---|---|---|---|")
    for v in ("conv", "rcut", "mut"):
        j = cp[v]["per_junction"]["J"]
        s = cp[v]["system_total"]
        w(f"| {v} | {j['crossing']} | {j['merging']} | {j['diverging']} | **{j['total']}** | "
          f"{s['crossing']} | {s['merging']} | {s['diverging']} | **{s['total']}** |")
    w()

    # ---- SSM ---------------------------------------------------------------
    p = os.path.join(RES, "ssm_summary.json")
    if os.path.exists(p):
        ssm = json.load(open(p))
        gg = defaultdict(list)
        for r in ssm:
            gg[(int(r["D"]), int(r["Q"]), round(r["m"], 2), r["variant"])].append(r)
        w("\n## T12. Simulated surrogate-safety conflicts (SSM device, deduplicated)\n")
        w("| D | Q | m | variant | veh-km | conflicts | per 1000 veh-km | severe TTC<1.5s /1000vkm | "
          "severe PET<1.0s /1000vkm | at main junction | at crossovers | on links | type111 degenerate |")
        w("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for k in sorted(gg):
            rs = gg[k]
            def mn(f):
                return st.mean([f(r) for r in rs])
            w(f"| {k[0]} | {k[1]} | {k[2]:.2f} | {k[3]} | {mn(lambda r: r['veh_km']):.0f} | "
              f"{mn(lambda r: r['n_conflicts']):.0f} | {mn(lambda r: r['total_rate_per_1000vkm']):.2f} | "
              f"{mn(lambda r: r['severe_TTC_rate_per_1000vkm']):.2f} | "
              f"{mn(lambda r: r['severe_PET_rate_per_1000vkm']):.2f} | "
              f"{mn(lambda r: r['by_region'].get('J',0)):.0f} | "
              f"{mn(lambda r: r['by_region'].get('XW',0)+r['by_region'].get('XE',0)):.0f} | "
              f"{mn(lambda r: r['by_region'].get('link',0)):.0f} | "
              f"{mn(lambda r: r['n_type111_degenerate']):.1f} |")
        w()

    # ---- rerouting robustness ---------------------------------------------
    p = os.path.join(RES, "reroute_check.json")
    if os.path.exists(p):
        rr = json.load(open(p))
        gg = defaultdict(list)
        for r in rr:
            if "error" in r:
                continue
            gg[(r["D"], r["Q"], r["m"])].append(r)
        w("\n## T13. Would conventional-network drivers voluntarily use the U-turn detour?\n")
        w("(conventional design, congestion-aware rerouting device on 100% of vehicles)\n")
        w("| D | Q | m | vehicles | chose a U-turn crossover | share | mean total time s |")
        w("|---|---|---|---|---|---|---|")
        for k in sorted(gg):
            rs = gg[k]
            w(f"| {k[0]} | {k[1]} | {k[2]:.2f} | {st.mean([r['n_veh'] for r in rs]):.0f} | "
              f"{st.mean([r['n_chose_uturn'] for r in rs]):.1f} | "
              f"{st.mean([r['share_uturn'] for r in rs]):.4f} | "
              f"{st.mean([r['mean_totaltime_s'] for r in rs]):.1f} |")
        w()

    with open(os.path.join(RES, "tables_extra.md"), "w") as f:
        f.write("\n".join(O) + "\n")
    print("\n".join(O))


if __name__ == "__main__":
    main()
