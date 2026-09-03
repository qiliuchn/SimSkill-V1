"""H3 confirmation: surrogate safety near the taper, at the FINE step length.

The main control matrix runs at dt=0.5 s, where the discretization study showed
near-taper hard-braking counts sit 45.8 % below the dt=0.25 s reference.  Safety LEVELS
are therefore not reportable from that matrix.  This experiment re-runs the three merge
arms at dt=0.25 s with the SSM device attached, and reports:

  * SSM TTC/DRAC conflict counts restricted to the work-zone approach
  * the SSM encounter-type-111 count, which is LABELLED "collision" but does NOT mean
    SUMO registered a crash -- cross-checked against --collision-output and the summary
    `collisions` attribute (gotcha from `analyze-intersection-safety-with-ssm` /
    `choose-time-discretization-and-integration-method`)
  * the live hard-braking event counter from the TraCI harness
"""
import json
import os
import xml.etree.ElementTree as ET
from collections import defaultdict

import numpy as np

import wz_common as W
import batch
import analyze
import stats_util as S

OUTD = os.path.join(W.OUT, "safety")
os.makedirs(OUTD, exist_ok=True)
ARMS = {"donothing": "priority", "early": "priority", "late": "zipper",
        "dynamic": "zipper"}
DEMANDS = (3200, 4000)
SEEDS = (1, 2, 3)
STEP = 0.25


def cells():
    cs = []
    for q in DEMANDS:
        for sd in SEEDS:
            for arm, merge in ARMS.items():
                cs.append(dict(label=f"ssm_{arm}_q{q}_s{sd}", outroot=OUTD, arm=arm,
                               rep="geom", merge=merge, peak=q, seed=sd,
                               demand_seed=300 + sd, step=STEP, ssm=True,
                               params=dict(lanes_closed=1), tagname=arm))
    return cs


def read_ssm(path):
    """Conflict counts from an SSM device output file."""
    if not os.path.exists(path):
        return dict(n_conflicts=0, n_severe=0, n_type111=0, min_ttc=np.nan,
                    max_drac=np.nan)
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return dict(n_conflicts=0, n_severe=0, n_type111=0, min_ttc=np.nan,
                    max_drac=np.nan)
    ttcs, dracs, n111, n = [], [], 0, 0
    for c in root.iter("conflict"):
        n += 1
        et = c.find("typeSpan")
        if et is not None and "111" in (et.text or ""):
            n111 += 1
        m = c.find("minTTC")
        if m is not None and m.get("value") not in (None, "NA"):
            try:
                ttcs.append(float(m.get("value")))
            except ValueError:
                pass
        d = c.find("maxDRAC")
        if d is not None and d.get("value") not in (None, "NA"):
            try:
                dracs.append(float(d.get("value")))
            except ValueError:
                pass
    return dict(n_conflicts=n, n_severe=int(sum(1 for v in ttcs if v < 1.5)),
                n_type111=n111,
                min_ttc=float(min(ttcs)) if ttcs else np.nan,
                max_drac=float(max(dracs)) if dracs else np.nan,
                n_ttc_values=len(ttcs))


if __name__ == "__main__":
    cs = cells()
    print(f"{len(cs)} safety cells at dt={STEP}s with the SSM device")
    res = batch.run_cells(cs, os.path.join(OUTD, "safety_results.json"), nproc=6)
    for r in res:
        if r.get("ok"):
            r.update(read_ssm(os.path.join(r["rundir"], "ssm.xml")))
    json.dump(res, open(os.path.join(OUTD, "safety_results.json"), "w"),
              indent=1, default=float)

    g = defaultdict(list)
    for r in res:
        if r.get("ok"):
            g[(r["peak"], r["arm"])].append(r)
    L = ["# H3 -- surrogate safety near the work-zone taper (dt = 0.25 s, SSM device)", "",
         "| demand | arm | WZ cap (pc/h/ln) | SSM conflicts | severe (TTC<1.5s) | min TTC | max DRAC | SSM type-111 | SUMO collisions (collision-output / summary) | hard-brake events (near taper) |",
         "|---:|---|---:|---:|---:|---:|---:|---:|---|---:|"]
    for q in DEMANDS:
        for arm in ARMS:
            rs = g.get((q, arm), [])
            if not rs:
                continue
            f = lambda m: float(np.nanmean([r.get(m, np.nan) for r in rs]))
            L.append(f"| {q} | {arm} | {f('cap'):.0f} | {f('n_conflicts'):.0f} | "
                     f"{f('n_severe'):.0f} | {f('min_ttc'):.2f} | {f('max_drac'):.2f} | "
                     f"{f('n_type111'):.1f} | {f('n_collisions'):.1f} / "
                     f"{f('collisions'):.1f} | {f('hard_brakes'):.0f} "
                     f"({f('hard_brakes_taper'):.0f}) |")
    L += ["", "## Capacity-safety exchange rate for LATE vs EARLY merge (CRN-paired)", "",
          "| demand | d cap (pc/h/ln) | p | d severe conflicts | p | d near-taper hard brakes | p | events per +100 pc/h/ln |",
          "|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for q in DEMANDS:
        def col(arm, m):
            return {r["seed"]: r.get(m, np.nan) for r in g.get((q, arm), [])}
        for m in ("cap",):
            pass
        ca, ce = col("late", "cap"), col("early", "cap")
        sa, se = col("late", "n_severe"), col("early", "n_severe")
        ha, he = col("late", "hard_brakes_taper"), col("early", "hard_brakes_taper")
        xs = sorted(set(ca) & set(ce))
        dc = S.paired([ca[s] for s in xs], [ce[s] for s in xs])
        ds = S.paired([sa[s] for s in xs], [se[s] for s in xs])
        dh = S.paired([ha[s] for s in xs], [he[s] for s in xs])
        ex = dh["diff"] / (dc["diff"] / 100.0) if dc["diff"] else np.nan
        L.append(f"| {q} | {dc['diff']:+.0f} | {dc['p']:.3f} | {ds['diff']:+.1f} | "
                 f"{ds['p']:.3f} | {dh['diff']:+.0f} | {dh['p']:.3f} | {ex:+.1f} |")
    out = os.path.join(W.TABLES, "SAFETY_H3.md")
    with open(out, "w") as f:
        f.write("\n".join(L) + "\n")
    print("\n".join(L))
    print("\nwrote", out)
