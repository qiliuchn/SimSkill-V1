#!/usr/bin/env python3
"""Final summary plot + human-readable results table.

Puts the reactive-rerouting penetration curve on the same axes as the two
reference points it should be judged against:
  * the best achievable STATIC route split (a coordinated planner), and
  * the duaIterate dynamic-user-equilibrium run,
plus the duaIterate convergence trace, which is shown because it did NOT
converge to Wardrop and that needs to be visible rather than asserted away.
"""
import argparse
import csv
import glob
import gzip
import math
import os
import re
import statistics
import xml.etree.ElementTree as ET
from collections import defaultdict

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def read_results(path):
    d = defaultdict(dict)
    with open(path) as f:
        for r in csv.DictReader(f):
            d[(r["scenario"], float(r["penetration"]))][r["metric"]] = (
                float(r["mean"]), float(r["ci95_halfwidth"]), int(r["n_seeds"]))
    return d


def dua_trace(dua_dir):
    out = []
    for d in sorted(glob.glob(os.path.join(dua_dir, "[0-9][0-9][0-9]"))):
        it = os.path.basename(d)
        rf = os.path.join(d, "demand_%s.rou.xml.gz" % it)
        tf = os.path.join(d, "tripinfo_%s.xml" % it)
        if not (os.path.exists(rf) and os.path.exists(tf)):
            continue
        rm = {}
        with gzip.open(rf, "rb") as f:
            for _, el in ET.iterparse(f, events=("end",)):
                if el.tag == "vehicle":
                    r = el.find("route")
                    if r is not None:
                        rm[el.get("id")] = "alt" if " AP " in " " + r.get("edges") + " " else "main"
                    el.clear()
        tot, per = [], {"main": [], "alt": []}
        for ti in ET.parse(tf).getroot().findall("tripinfo"):
            v = float(ti.get("duration")) + float(ti.get("departDelay"))
            tot.append(v)
            r = rm.get(ti.get("id"))
            if r:
                per[r].append(float(ti.get("duration")))
        n_alt = sum(1 for x in rm.values() if x == "alt")
        gap = ((statistics.mean(per["alt"]) - statistics.mean(per["main"]))
               if per["alt"] and per["main"] else float("nan"))
        out.append((int(it), n_alt / max(1, len(rm)), statistics.mean(tot), gap))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--static", required=True)
    ap.add_argument("--dua-dir", required=True)
    ap.add_argument("--plotdir", required=True)
    ap.add_argument("--outdir", required=True)
    a = ap.parse_args()

    res = read_results(a.results)
    pens = sorted(set(p for (s, p) in res if s == "incident_fast"))

    # static split reference
    st = defaultdict(list)
    with open(a.static) as f:
        for r in csv.DictReader(f):
            st[float(r["alt_share"])].append(float(r["mean_total_tt_s"]))
    st_x = sorted(st)
    st_y = [statistics.mean(st[k]) for k in st_x]
    best_static_x = st_x[int(np.argmin(st_y))]
    best_static_y = min(st_y)

    tr = dua_trace(a.dua_dir)
    dua_final_tt = tr[-1][2] if tr else float("nan")
    dua_final_share = tr[-1][1] if tr else float("nan")

    fig, axes = plt.subplots(1, 3, figsize=(16, 4.6))

    ax = axes[0]
    for s, col, mk, lab in (("incident_fast", "#3b6ea5", "o", "reactive rerouting (fast adapt.)"),
                            ("incident_smooth", "#c86b3c", "^", "reactive rerouting (smoothed)")):
        mus = [res[(s, p)]["mean_tt_all"][0] for p in pens]
        hws = [res[(s, p)]["mean_tt_all"][1] for p in pens]
        ax.plot(pens, mus, mk + "-", color=col, lw=2, ms=5, label=lab)
        ax.fill_between(pens, np.array(mus) - hws, np.array(mus) + hws, color=col, alpha=.18, lw=0)
    ax.axhline(best_static_y, color="#2f8f6b", ls="--", lw=1.6,
               label="best STATIC split (%.0f%% alt): %.1f s" % (100 * best_static_x, best_static_y))
    ax.axhline(dua_final_tt, color="#8a5fb0", ls=":", lw=1.8,
               label="duaIterate DUE (iter 59): %.1f s" % dua_final_tt)
    ax.axhline(res[("incident_fast", 0.0)]["mean_tt_all"][0], color="#999999", ls="-.", lw=1.3,
               label="do nothing (p=0): %.1f s" % res[("incident_fast", 0.0)]["mean_tt_all"][0])
    ax.set_xlabel("rerouting-device market penetration")
    ax.set_ylabel("network-wide mean total travel time [s]")
    ax.set_title("Reactive rerouting vs coordinated references", fontsize=10)
    ax.grid(alpha=.25); ax.legend(fontsize=7.5)

    ax = axes[1]
    ax.plot(st_x, st_y, "o-", color="#2f8f6b", lw=2, ms=4)
    ax.axvline(best_static_x, color="#2f8f6b", ls="--", lw=1.2)
    ax.set_xlabel("fraction of vehicles statically assigned to the alternate")
    ax.set_ylabel("network-wide mean total travel time [s]")
    ax.set_title("Static-split envelope: the alternate is a\ncongestible resource with an interior optimum", fontsize=10)
    ax.set_yscale("log")
    ax.grid(alpha=.25, which="both")

    ax = axes[2]
    it = [x[0] for x in tr]
    ax.plot(it, [x[1] for x in tr], "-", color="#3b6ea5", lw=1.8, label="alternate share")
    ax.set_xlabel("duaIterate iteration")
    ax.set_ylabel("alternate share", color="#3b6ea5")
    ax2 = ax.twinx()
    ax2.plot(it, [x[3] for x in tr], "-", color="#c86b3c", lw=1.5, label="alt - main cost gap")
    ax2.axhline(0, color="k", lw=.8)
    ax2.set_ylabel("mean route-cost gap alt-main [s]", color="#c86b3c")
    ax.set_title("duaIterate convergence: split still drifting,\ncost gap never closes (Wardrop NOT met)", fontsize=10)
    ax.grid(alpha=.25)
    fig.tight_layout()
    fig.savefig(os.path.join(a.plotdir, "reference_comparison_and_due_convergence.png"), dpi=140)
    plt.close(fig)

    # ------------- markdown results table -------------
    L = []
    L.append("# Results table\n")
    L.append("Demand 2500 veh/h over 3600 s; incident = one of two lanes of edge CB closed 900-2400 s.")
    L.append("All travel times are **total experienced time** = tripinfo `duration` + `departDelay`, in seconds.")
    L.append("`+/-` is a 95% t confidence half-width over 10 Common-Random-Number seeds.\n")
    L.append("## Main sweep -- scenario `incident_fast` (aggressive travel-time adaptation)\n")
    L.append("| penetration | equipped TT (cohort) | unequipped TT (cohort) | private gap (unequipped-equipped) | cohort TT (everyone) | network-wide TT | alternate share |")
    L.append("|---|---|---|---|---|---|---|")
    for p in pens:
        c = res[("incident_fast", p)]
        eq = c["mean_tt_cohort_equipped"]; un = c["mean_tt_cohort_unequipped"]
        f = lambda t: "-" if math.isnan(t[0]) else "%.1f +/- %.1f" % (t[0], t[1])
        gap = "-" if (math.isnan(eq[0]) or math.isnan(un[0])) else "%+.1f" % (un[0] - eq[0])
        L.append("| %.2f | %s | %s | %s | %s | %s | %.3f |"
                 % (p, f(eq), f(un), gap, f(c["mean_tt_cohort_all"]), f(c["mean_tt_all"]),
                    c["alt_share_overall"][0]))
    L.append("")
    L.append("## Scenario comparison -- incident-exposed cohort mean total TT [s]\n")
    L.append("| penetration | incident_fast | incident_smooth | incident_rnd (random-factor 1.4) | noincident_fast |")
    L.append("|---|---|---|---|---|")
    for p in pens:
        row = []
        for s in ("incident_fast", "incident_smooth", "incident_rnd", "noincident_fast"):
            t = res[(s, p)]["mean_tt_cohort_all"]
            row.append("%.1f +/- %.1f" % (t[0], t[1]))
        L.append("| %.2f | %s |" % (p, " | ".join(row)))
    L.append("")
    L.append("## Route-split oscillation (measured from 30 s route-split time series)\n")
    L.append("| penetration | sd(alt share) fast | sd smoothed | masd fast | masd smoothed |")
    L.append("|---|---|---|---|---|")
    for p in pens:
        if p == 0.0:
            continue
        a1 = res[("incident_fast", p)]; a2 = res[("incident_smooth", p)]
        L.append("| %.2f | %.3f +/- %.3f | %.3f +/- %.3f | %.3f +/- %.3f | %.3f +/- %.3f |"
                 % (p, a1["osc_sd"][0], a1["osc_sd"][1], a2["osc_sd"][0], a2["osc_sd"][1],
                    a1["osc_masd"][0], a1["osc_masd"][1], a2["osc_masd"][0], a2["osc_masd"][1]))
    L.append("")
    L.append("## Reference points (network-wide mean total TT, whole run)\n")
    L.append("| configuration | alternate share | network-wide mean TT [s] |")
    L.append("|---|---|---|")
    L.append("| do nothing (no device, incident) | 0.000 | %.1f |" % res[("incident_fast", 0.0)]["mean_tt_all"][0])
    L.append("| best reactive penetration (p=0.50, fast) | %.3f | %.1f |"
             % (res[("incident_fast", 0.5)]["alt_share_overall"][0], res[("incident_fast", 0.5)]["mean_tt_all"][0]))
    L.append("| full penetration (p=1.00, fast) | %.3f | %.1f |"
             % (res[("incident_fast", 1.0)]["alt_share_overall"][0], res[("incident_fast", 1.0)]["mean_tt_all"][0]))
    L.append("| best STATIC split (coordinated planner) | %.3f | %.1f |" % (best_static_x, best_static_y))
    L.append("| duaIterate DUE, iteration 59 (not converged) | %.3f | %.1f |" % (dua_final_share, dua_final_tt))
    L.append("| no incident at all (p=0) | 0.000 | %.1f |" % res[("noincident_fast", 0.0)]["mean_tt_all"][0])
    txt = "\n".join(L) + "\n"
    with open(os.path.join(a.outdir, "results_table.md"), "w") as f:
        f.write(txt)
    print(txt)


if __name__ == "__main__":
    main()
