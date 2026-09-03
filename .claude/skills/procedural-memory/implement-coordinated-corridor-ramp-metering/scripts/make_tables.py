#!/usr/bin/env python3
"""Build the deliverable TSTT decomposition table (markdown + csv)."""
import csv
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
TAB = os.path.join(ROOT, "outputs", "tables")
ARMS = ["nocontrol", "fixed", "alinea", "bnalinea", "coord", "coord_flush", "negctrl"]
LBL = {"nocontrol": "no control", "fixed": "fixed-rate", "alinea": "isolated ALINEA",
       "bnalinea": "bottleneck-ALINEA (r3 only)", "coord": "coordinated (HERO-style)",
       "coord_flush": "coordinated + queue flush", "negctrl": "negative control"}


def load():
    rows = []
    for r in csv.DictReader(open(os.path.join(TAB, "runs.csv"))):
        d = {}
        for k, v in r.items():
            if k in ("tag", "arm", "ramp_wait_per_veh"):
                d[k] = v
            else:
                try:
                    d[k] = float(v) if v not in ("", "None") else None
                except ValueError:
                    d[k] = v
        d["group"] = r["tag"].split("/")[0]
        rows.append(d)
    return rows


def main():
    rows = [r for r in load() if r["group"] == "core"]
    dems = sorted({r["demand"] for r in rows})
    L = []
    L.append("# Total System Travel Time / Delay decomposition by control arm and demand level\n")
    L.append("All values are means over **8 Common-Random-Numbers seeds** (identical route "
             "file and identical `sumo --seed` in every arm at a given seed).\n")
    L.append("**Authoritative definitions** (identical in every document and figure):\n")
    L.append("- `TSTT` = total vehicle-hours spent inside the network "
             "(`edgeData sampledSeconds`, all edges incl. internal junction edges) "
             "**plus** origin-insertion vehicle-hours (integral of the count of vehicles "
             "waiting for insertion, sampled every 10 s).")
    L.append("- `TSD` (Total System **Delay**) = the same four-way split, using `edgeData "
             "timeLoss` for the three in-network parts and the full insertion integral for "
             "the origin part. TSD is the headline system metric: TSTT alone rewards an arm "
             "that simply serves fewer vehicles.")
    L.append("- Facility classes: **mainline** = `ml_*`, `o*_off` + freeway junction internals; "
             "**ramp** = `r*_stor`, `r*_mrg` + meter-junction internals; **surface** = "
             "`r*_sapp`, `r*_sout`, `r*_capp`, `r*_cout` + ramp-terminal internals; "
             "**origin** = vehicles held in SUMO's insertion buffer (never-inserted or "
             "insertion-delayed demand).\n")
    csvrows = []
    for dem in dems:
        L.append(f"\n## Demand multiplier x{dem}  "
                 f"(mainline+ramp demand at the lane drop = {round(5260*dem)} veh/h vs "
                 f"measured bottleneck capacity ~4100 veh/h)\n")
        L.append("| arm | TSD total | mainline | ramp | surface | origin-insertion | "
                 "TSD vs no-control | bottleneck discharge (veh/h) | completed veh | "
                 "never inserted | still running |")
        L.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        base = None
        for arm in ARMS:
            g = [r for r in rows if r["arm"] == arm and abs(r["demand"] - dem) < 1e-9]
            if not g:
                continue
            v = {k: float(np.mean([r[k] for r in g])) for k in
                 ("TSD", "delay_mainline", "delay_ramp", "delay_surface", "delay_origin",
                  "TSTT", "vh_mainline", "vh_ramp", "vh_surface", "vh_origin",
                  "bn_discharge_peak", "n_completed", "n_never_inserted", "n_still_running")}
            if arm == "nocontrol":
                base = v["TSD"]
            rel = 100 * (v["TSD"] - base) / base if base else 0.0
            L.append(f"| {LBL[arm]} | {v['TSD']:.0f} | {v['delay_mainline']:.0f} | "
                     f"{v['delay_ramp']:.1f} | {v['delay_surface']:.1f} | "
                     f"{v['delay_origin']:.1f} | {rel:+.1f}% | {v['bn_discharge_peak']:.0f} | "
                     f"{v['n_completed']:.0f} | {v['n_never_inserted']:.1f} | "
                     f"{v['n_still_running']:.1f} |")
            csvrows.append(dict(demand=dem, arm=arm, **{k: round(x, 3) for k, x in v.items()},
                                TSD_vs_nocontrol_pct=round(rel, 2)))
        L.append("")
        L.append("| arm | TSTT total | mainline | ramp | surface | origin-insertion |")
        L.append("|---|---:|---:|---:|---:|---:|")
        for arm in ARMS:
            g = [r for r in rows if r["arm"] == arm and abs(r["demand"] - dem) < 1e-9]
            if not g:
                continue
            v = {k: float(np.mean([r[k] for r in g])) for k in
                 ("TSTT", "vh_mainline", "vh_ramp", "vh_surface", "vh_origin")}
            L.append(f"| {LBL[arm]} | {v['TSTT']:.0f} | {v['vh_mainline']:.0f} | "
                     f"{v['vh_ramp']:.1f} | {v['vh_surface']:.1f} | {v['vh_origin']:.1f} |")
    open(os.path.join(TAB, "TSTT_DECOMPOSITION.md"), "w").write("\n".join(L) + "\n")
    with open(os.path.join(TAB, "tstt_decomposition.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(csvrows[0]))
        w.writeheader()
        w.writerows(csvrows)
    print("wrote TSTT_DECOMPOSITION.md /.csv")


if __name__ == "__main__":
    main()
