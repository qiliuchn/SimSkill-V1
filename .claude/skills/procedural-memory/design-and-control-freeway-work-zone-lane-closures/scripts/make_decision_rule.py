"""The merge-control decision rule, derived from the control matrices rather than asserted.

Produces a table keyed to (lanes closed, demand / work-zone capacity ratio) giving the
arm with the lowest mean TSTT, the margin over the runner-up, and whether that margin is
significant under a CRN-paired test.  A cell whose winner is not significantly better
than `donothing` is reported as "no control justified", which is the honest outcome for
most of the undersaturated range.
"""
import json
import os
from collections import defaultdict

import numpy as np

import wz_common as W
import stats_util as S

ARMS = ["donothing", "early", "late", "dynamic", "vsl"]
# measured queue-discharge capacity per open lane, from CAPACITY.md / the probe
CAP_PER_LANE = {1: 1534.0, 2: 1108.0}
OPEN_LANES = {1: 2, 2: 1}


def load(lc):
    p = os.path.join(W.OUT, "control", f"control_results_lc{lc}.json")
    if not os.path.exists(p):
        return None
    return [r for r in json.load(open(p)) if r.get("ok")]


def rule_rows(lc):
    rows = load(lc)
    if not rows:
        return []
    g = defaultdict(list)
    for r in rows:
        g[(r["peak"], r["arm"])].append(r)
    seeds = sorted({r["seed"] for r in rows})
    demands = sorted({r["peak"] for r in rows})
    wz_cap = CAP_PER_LANE[lc] * OPEN_LANES[lc]
    out = []
    for q in demands:
        means = {a: float(np.mean([x["TSTT_vh"] for x in g[(q, a)]]))
                 for a in ARMS if (q, a) in g}
        order = sorted(means, key=means.get)
        win, second = order[0], order[1]

        def col(a):
            return {x["seed"]: x["TSTT_vh"] for x in g[(q, a)]}
        cw, cs_ = col(win), col(second)
        xs = [s for s in seeds if s in cw and s in cs_]
        vs_second = S.paired([cw[s] for s in xs], [cs_[s] for s in xs])
        cd = col("donothing")
        xs2 = [s for s in seeds if s in cw and s in cd]
        vs_do = S.paired([cw[s] for s in xs2], [cd[s] for s in xs2])
        justified = bool(vs_do["sig"] and vs_do["diff"] < 0)
        out.append(dict(lanes_closed=lc, demand=q, vc=q / wz_cap,
                        winner=win, tstt=means[win], second=second,
                        gap_vs_second=vs_second["diff"], p_second=vs_second["p"],
                        gain_vs_donothing=vs_do["diff"], p_donothing=vs_do["p"],
                        pct_vs_donothing=vs_do["pct"],
                        recommend=(win if justified else "no control justified"),
                        means=means))
    return out


if __name__ == "__main__":
    L = ["# Merge-control decision rule", "",
         "Derived from the CRN control matrices, not asserted.  `v/c` is mainline peak",
         "demand divided by measured work-zone queue-discharge capacity",
         "(1534 pc/h/ln x 2 open lanes = 3068 veh/h at 1 lane closed;",
         "1108 pc/h/ln x 1 open lane = 1108 veh/h at 2 lanes closed).",
         "",
         "A cell is only given a control recommendation when the best arm is",
         "SIGNIFICANTLY better than doing nothing on a paired test; otherwise the honest",
         "recommendation is to deploy nothing.", "",
         "| lanes closed | peak demand (veh/h) | v/c | lowest-TSTT arm | gain vs do-nothing (veh-h) | % | p | vs runner-up | RECOMMENDATION |",
         "|---:|---:|---:|---|---:|---:|---:|---|---|"]
    allrows = []
    for lc in (1, 2):
        rr = rule_rows(lc)
        allrows += rr
        for r in rr:
            L.append(f"| {r['lanes_closed']} | {r['demand']} | {r['vc']:.2f} | "
                     f"{r['winner']} | {r['gain_vs_donothing']:+.1f} | "
                     f"{r['pct_vs_donothing']:+.1f}% | {r['p_donothing']:.3f} | "
                     f"{r['second']} ({r['gap_vs_second']:+.1f}, p={r['p_second']:.3f}) | "
                     f"**{r['recommend']}** |")

    L += ["", "## The rule, stated as thresholds in v/c", ""]
    for lc in (1, 2):
        rr = [r for r in allrows if r["lanes_closed"] == lc]
        if not rr:
            continue
        L.append(f"**{lc} lane{'s' if lc > 1 else ''} closed:**")
        for r in rr:
            L.append(f"  - v/c = {r['vc']:.2f} ({r['demand']} veh/h): {r['recommend']}")
        L.append("")
    json.dump(allrows, open(os.path.join(W.TABLES, "decision_rule.json"), "w"),
              indent=1, default=float)
    out = os.path.join(W.TABLES, "DECISION_RULE.md")
    with open(out, "w") as f:
        f.write("\n".join(L) + "\n")
    print("\n".join(L))
    print("\nwrote", out)
