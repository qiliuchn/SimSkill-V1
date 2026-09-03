#!/usr/bin/env python3
"""Report the generated fleet's occupancy and VOT distributions (deliverable 2)."""
import csv
import glob
import math
import os
import statistics as st
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def pct(v, q):
    v = sorted(v)
    if not v:
        return float("nan")
    k = (len(v) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def report(paths):
    out = []
    for p in paths:
        rows = list(csv.DictReader(open(p)))
        occ = [int(r["occ"]) for r in rows]
        vot = [float(r["vot"]) for r in rows]
        n = len(rows)
        by = {}
        for r in rows:
            by.setdefault(r["cls"], []).append(r)
        out.append(f"### {os.path.basename(p)}")
        out.append(f"vehicles={n}  people={sum(occ)}  mean occupancy={sum(occ)/n:.3f}")
        for cls in ("sov", "hov", "bus"):
            rs = by.get(cls, [])
            if not rs:
                continue
            o = [int(r["occ"]) for r in rs]
            v = [float(r["vot"]) for r in rs]
            occ_hist = {k: o.count(k) for k in sorted(set(o))} if cls != "bus" else {}
            out.append(f"  {cls:4s} n={len(rs):5d} ({100*len(rs)/n:5.2f}%)  people={sum(o):6d} "
                       f"({100*sum(o)/sum(occ):5.2f}%)  occ mean={st.mean(o):6.2f} "
                       f"min={min(o)} max={max(o)}  "
                       + (f"occ hist={occ_hist}  " if occ_hist else "")
                       + f"VOT mean={st.mean(v):6.2f} median={st.median(v):6.2f}")
        out.append(f"  VOT ($/person-h) over all vehicles: mean={st.mean(vot):.2f} "
                   f"median={st.median(vot):.2f} sd={st.pstdev(vot):.2f} "
                   f"p05={pct(vot,.05):.2f} p25={pct(vot,.25):.2f} p50={pct(vot,.50):.2f} "
                   f"p75={pct(vot,.75):.2f} p95={pct(vot,.95):.2f} max={max(vot):.2f}")
        lv = [math.log(x) for x in vot]
        out.append(f"  log(VOT): mean={st.mean(lv):.4f} (=> median ${math.exp(st.mean(lv)):.2f}) "
                   f"sd={st.pstdev(lv):.4f}   [generator: lognormal(mu=ln 25, sigma=0.70)]")
        out.append(f"  VOT quartile edges (Q1|Q2|Q3|Q4 cut points) = "
                   f"{pct(vot,.25):.2f}, {pct(vot,.50):.2f}, {pct(vot,.75):.2f}")
        out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    paths = sys.argv[1:] or sorted(glob.glob(os.path.join(ROOT, "demand", "*_c0.150_x1.35.fleet.csv")))
    txt = report(paths)
    dest = os.path.join(ROOT, "analysis", "fleet_distributions.txt")
    open(dest, "w").write(txt + "\n")
    print(txt)
    print("->", dest)
