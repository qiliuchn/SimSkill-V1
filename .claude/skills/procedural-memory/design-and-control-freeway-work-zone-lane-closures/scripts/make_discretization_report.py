"""Turn the discretization sweep into the decision document."""
import json
import os
from collections import defaultdict

import numpy as np

import wz_common as W
import stats_util as S

D = os.path.join(W.OUT, "discretization")
res = json.load(open(os.path.join(D, "discretization_results.json")))
probe, conv = res["probe"], res["convergence"]

METRICS = ["cap", "mean_duration", "mean_timeloss", "hard_brakes",
           "hard_brakes_taper", "CO2_kg", "TSTT_vh", "completed"]

by = defaultdict(list)
for r in conv:
    by[(r["step"], r["family"], r["method"])].append(r)

lines = ["# Time-discretization decision (work-zone testbed)", "",
         "Method: `choose-time-discretization-and-integration-method` +",
         "[[sumo-time-discretization]], executed on THIS scenario, not cited.", "",
         "## (A) Integrator probe -- single deterministic vehicle, a=2.6 m/s^2, x(t)=0.5*a*t^2",
         "", "| dt (s) | method | position error at t=1 s (m) | settled offset (m) | predicted Euler offset v*dt/2 (m) |",
         "|---|---|---:|---:|---:|"]
for r in probe:
    so = "n/a" if r["settled_offset"] is None else f"{r['settled_offset']:+.4f}"
    lines.append(f"| {r['step']} | {r['method']} | {r['err_at_1s']:+.4f} | {so} | "
                 f"{r['predicted_euler_offset']:.3f} |")

lines += ["", "## (B) Convergence sweep, work-zone testbed (1 lane closed, 3600 veh/h peak, 3 CRN seeds)",
          "",
          "Reference cell = dt 0.25 s, ballistic, actionStepLength pinned at 1.0 s.",
          "The (Euler, pinned) cell does not exist below dt=1 s: a vType actionStepLength",
          "strictly greater than --step-length force-enables ballistic.", "",
          "| dt | family | method | asl | WZ cap (veh/h/ln) | mean dur (s) | hard-brake events | near-taper | CO2 (kg) | completed | wall (s) |",
          "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|"]
tbl = {}
for k in sorted(by, key=lambda x: (-x[0], x[1], x[2])):
    rs = by[k]
    m = {mm: float(np.mean([r[mm] for r in rs])) for mm in METRICS}
    tbl[k] = m
    lines.append(f"| {k[0]} | {k[1]} | {k[2]} | {rs[0]['asl']} | {m['cap']:.0f} | "
                 f"{m['mean_duration']:.0f} | {m['hard_brakes']:.0f} | "
                 f"{m['hard_brakes_taper']:.0f} | {m['CO2_kg']:.0f} | "
                 f"{m['completed']:.0f} | {np.mean([r['wall'] for r in rs]):.0f} |")

ref = tbl.get((0.25, "pinned", "ballistic"))
if ref:
    lines += ["", "### Deviation from the reference cell (%)", "",
              "| dt | family | method | " + " | ".join(METRICS) + " |",
              "|---|---|---|" + "---:|" * len(METRICS)]
    for k in sorted(tbl, key=lambda x: (-x[0], x[1], x[2])):
        dev = [100 * (tbl[k][m] - ref[m]) / ref[m] if ref[m] else np.nan for m in METRICS]
        lines.append(f"| {k[0]} | {k[1]} | {k[2]} | " +
                     " | ".join(f"{d:+.1f}" for d in dev) + " |")

    # the central reaction-time-vs-numerics split
    lines += ["", "### The reaction-time confound, isolated", ""]
    for m in ("cap", "mean_duration", "hard_brakes"):
        a = tbl.get((1.0, "tied", "ballistic"), {}).get(m)
        b = tbl.get((0.25, "tied", "ballistic"), {}).get(m)
        c = tbl.get((1.0, "pinned", "ballistic"), {}).get(m)
        d = tbl.get((0.25, "pinned", "ballistic"), {}).get(m)
        if None in (a, b, c, d):
            continue
        lines.append(f"- **{m}**: dt 1.0 -> 0.25 s with actionStepLength TIED: "
                     f"{a:.0f} -> {b:.0f} ({100*(b-a)/a:+.1f}%); with it PINNED at 1.0 s: "
                     f"{c:.0f} -> {d:.0f} ({100*(d-c)/c:+.1f}%).")

json.dump({f"dt{k[0]}_{k[1]}_{k[2]}": v for k, v in tbl.items()},
          open(os.path.join(D, "convergence_table.json"), "w"), indent=1, default=str)
out = os.path.join(W.TABLES, "DISCRETIZATION_DECISION.md")
with open(out, "w") as f:
    f.write("\n".join(lines) + "\n")
print("\n".join(lines))
print("\nwrote", out)
