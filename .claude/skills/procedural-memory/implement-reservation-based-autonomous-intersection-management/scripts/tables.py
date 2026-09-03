#!/usr/bin/env python3
"""Render analysis/results.json into markdown tables (analysis/tables.md)."""
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R = json.load(open(os.path.join(BASE, "analysis/results.json")))
D = ["300", "600", "900", "1200", "1500"]
CTRL = [("fixed", "Fixed (tuned)"), ("actuated", "Actuated"),
        ("maxpressure", "Max-pressure"), ("aimfcfs", "AIM-FCFS"),
        ("aimbatch", "AIM-batch"), ("awsc", "AWSC")]
L = []


def w(s=""):
    L.append(s)


def ci(x):
    return "%.1f ± %.1f" % (x["mean"], x["hw"]) if x else "-"


# ---------------------------------------------------------------- s0 / webster
w("## Table 1 — Fixed-time cycle-length sweep (mean delay, s; 3 CRN seeds)")
w()
w("| demand veh/h/appr | best structure | best cycle (s) | best delay | worst tested | Webster C_opt (p2) |")
w("|---|---|---|---|---|---|")
wj = {}
p = os.path.join(BASE, "net/plans/webster.json")
if os.path.exists(p):
    wj = json.load(open(p))
for d in D:
    tbl = R["cycle_sweep"].get(d, [])
    if not tbl:
        continue
    b, wr = tbl[0], tbl[-1]
    key = "p2_%s_webster" % d
    co = wj.get(key, {}).get("C_opt")
    w("| %s | %s | %d | %.1f | %.1f | %s |" % (d, b[1], b[2], b[0], wr[0],
                                               "%.1f" % co if co else "n/a"))
w()

# --------------------------------------------------------------------- s1
w("## Table 2 — Main comparison: mean delay (timeLoss + departDelay), s, mean ± 95% CI over 5 CRN seeds")
w()
w("| demand | " + " | ".join(n for _, n in CTRL) + " |")
w("|---" * (len(CTRL) + 1) + "|")
for d in D:
    row = R["s1"][d]["controllers"]
    w("| %s | " % d + " | ".join(ci(row[c]["delay"]) if c in row else "-"
                                 for c, _ in CTRL) + " |")
w()

w("## Table 3 — Paired CRN difference vs ACTUATED (negative = better than actuated)")
w()
w("| demand | arm | Δ delay (s) | Δ % | 95% CI | significant | per-seed sign agreement |")
w("|---|---|---|---|---|---|---|")
for d in D:
    for c, _n in CTRL:
        pr = R["s1"][d]["paired_vs_actuated"].get(c)
        if not pr:
            continue
        w("| %s | %s | %+.1f | %+.0f%% | [%+.1f, %+.1f] | %s | %.0f%% |"
          % (d, c, pr["mean_diff"], pr["pct"], pr["ci"][0], pr["ci"][1],
             "yes" if pr["sig"] else "no", 100 * pr["sign_agree"]))
w()

w("## Table 4 — Validity accounting for every s1 arm (summed over 5 seeds)")
w()
w("| demand | arm | loaded | arrived | still running | never inserted | teleports | teleports(jam) | collisions | in-junction collisions |")
w("|---|---|---|---|---|---|---|---|---|---|")
for d in D:
    for c, _n in CTRL:
        r = R["s1"][d]["controllers"].get(c)
        if not r:
            continue
        s = r["safety"]
        w("| %s | %s | %d | %d | %d | %d | %d | %d | %d | %d |"
          % (d, c, s["loaded"], s["arrived"], s["still_running"],
             s["never_inserted"], s["teleports_total"], s["teleports_jam"],
             s["collisions_total"], s["collisions_junction"]))
w()

# --------------------------------------------------------------------- cap
cp = os.path.join(BASE, "analysis/capacity.json")
if os.path.exists(cp):
    C = json.load(open(cp))
    w("## Table 5 — Saturation throughput probe (demand 2500 veh/h/approach, served flow in t=600-1500 s)")
    w()
    w("| controller | served flow (veh/h) |")
    w("|---|---|")
    for k, v in sorted(C.items(), key=lambda x: -x[1]["mean_veh_per_h"]):
        w("| %s | %.0f |" % (k, v["mean_veh_per_h"]))
    w()

# --------------------------------------------------------------------- s2
w("## Table 6 — Safety-buffer negative control (AIM-batch, 3 CRN seeds)")
w()
w("| demand | buffer (s) | mean delay ± CI | arrived | collisions | teleports |")
w("|---|---|---|---|---|---|")
for d, row in R["s2"].items():
    for k, v in row.items():
        if v is None:
            continue
        if k == "AWSC_reference":
            w("| %s | *AWSC reference* | %s | - | - | - |" % (d, ci(v["delay"])))
            continue
        s = v["safety"]
        w("| %s | %s | %s | %d | %d | %d |" % (d, k, ci(v["delay"]), s["arrived"],
                                               s["collisions_total"], s["teleports_total"]))
w()

# --------------------------------------------------------------------- s3
w("## Table 7 — H2: HDV penetration sweep (AIM-batch + virtual-signal fallback, 5 CRN seeds)")
w()
w("| demand | CAV penetration | mean delay ± CI | Δ vs actuated | sig | collisions | teleports |")
w("|---|---|---|---|---|---|---|")
for d, row in R["s3"].items():
    ref = row.get("actuated_reference")
    if ref:
        w("| %s | *actuated reference* | %s | - | - | - | - |" % (d, ci(ref["delay"])))
    for k in sorted([x for x in row if not x.startswith("actuated")]):
        v = row[k]
        pr = v.get("paired_vs_actuated")
        s = v["safety"]
        w("| %s | %s | %s | %s | %s | %d | %d |"
          % (d, k, ci(v["delay"]),
             "%+.1f s (%+.0f%%)" % (pr["mean_diff"], pr["pct"]) if pr else "-",
             ("yes" if pr["sig"] else "no") if pr else "-",
             s["collisions_total"], s["teleports_total"]))
w()

# --------------------------------------------------------------------- s4
w("## Table 8 — H3: unbalanced 80/20 demand (major N,S = 1.6x; minor E,W = 0.4x), 3 CRN seeds")
w()
w("| demand | arm | mean delay | major (N,S) | minor (E,W) | minor/major | Gini(delay) | p95 delay | collisions |")
w("|---|---|---|---|---|---|---|---|---|")
for d in D:
    row = R["s4"].get(d, {})
    for c in ("aimfcfs", "aimbatch", "actuated"):
        v = row.get(c)
        if not v:
            continue
        w("| %s | %s | %s | %.1f | %.1f | %.2f | %.3f | %.0f | %d |"
          % (d, c, ci(v["delay"]), v["major_delay"], v["minor_delay"],
             v["minor_over_major"], v["gini"]["mean"], v["p95"]["mean"],
             v["safety"]["collisions_total"]))
    for k, lbl in (("paired_batch_vs_fcfs_delay", "batch−fcfs delay"),
                   ("paired_batch_vs_fcfs_gini", "batch−fcfs Gini")):
        pr = row.get(k)
        if pr:
            w("| %s | *%s* | %+.2f (CI %+.2f,%+.2f) sig=%s | | | | | | |"
              % (d, lbl, pr["mean_diff"], pr["ci"][0], pr["ci"][1],
                 "yes" if pr["sig"] else "no"))
w()

# --------------------------------------------------------------------- s5
w("## Table 9 — H4: surrogate safety measures (SSM device, mean per run over 3 CRN seeds)")
w()
w("| demand | arm | conflicts | following | merging | crossing | type-111 flags | of which opposing-left artifact | genuine 111 | TTC<1.5 s | crossing TTC<1.5 s | min TTC | median TTC | max DRAC | real collisions |")
w("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
for d, row in R["s5"].items():
    for c, v in row.items():
        w("| %s | %s | %.1f | %.1f | %.1f | %.1f | %.1f | %.1f | %.1f | %.1f | %.1f | %s | %.2f | %.2f | %d |"
          % (d, c, v["n_conflicts"], v["following"], v["merging"], v["crossing"],
             v["flag111"], v["flag111_opposing_left_artifact"], v["flag111_other"],
             v["ttc_lt_1_5"], v["crossing_ttc_lt_1_5"],
             "%.2f" % v["min_ttc"] if v.get("min_ttc") is not None else "n/a",
             v.get("ttc_median", 0), v.get("max_drac", 0),
             v.get("safety", {}).get("collisions_total", -1)))
w()

# --------------------------------------------------------------------- s6
w("## Table 10 — Communication realism (AIM-batch, demand 900 veh/h/approach, 3 CRN seeds)")
w()
w("### 10a. Actuation + request latency")
w()
w("| latency (s) | mean delay ± CI | arrived | COLLISIONS | in-junction collisions | teleports |")
w("|---|---|---|---|---|---|")
for k in sorted(R["s6"]["latency"], key=float):
    v = R["s6"]["latency"][k]
    s = v["safety"]
    w("| %s | %s | %d | **%d** | %d | %d |" % (k, ci(v["delay"]), s["arrived"],
                                               s["collisions_total"],
                                               s["collisions_junction"],
                                               s["teleports_total"]))
w()
w("### 10b. Position measurement noise (Gaussian sigma on distance-to-stop-line)")
w()
w("| sigma (m) | mean delay ± CI | arrived | COLLISIONS | in-junction collisions | teleports |")
w("|---|---|---|---|---|---|")
for k in sorted(R["s6"]["noise"], key=float):
    v = R["s6"]["noise"][k]
    s = v["safety"]
    w("| %s | %s | %d | **%d** | %d | %d |" % (k, ci(v["delay"]), s["arrived"],
                                               s["collisions_total"],
                                               s["collisions_junction"],
                                               s["teleports_total"]))
w()

# ------------------------------------------------------------------- verify
w("## Table 11 — Detector negative control: AIM with the safety interlock DISABLED")
w()
w("| run | collisions | in-junction collisions | arrived | mean delay |")
w("|---|---|---|---|---|")
for k, v in R.get("verify", {}).items():
    w("| %s | %s | %s | %d | %.1f |" % (k, v["collisions"], v["collisions_junction"],
                                        v["arrived"], v["delay"]))
w()

out = os.path.join(BASE, "analysis/tables.md")
open(out, "w").write("\n".join(L) + "\n")
print("wrote", out, "(%d lines)" % len(L))
