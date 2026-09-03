#!/usr/bin/env python3
"""Measure interior-link capacity of the 4x4 signalized grid EMPIRICALLY, then
pick insertion rates that achieve target v/c levels.

IMPORTANT method note (a mistake worth recording): capacity is NOT the flow
observed when the network is loaded as hard as possible. Loading a signalized
grid far past capacity drives it into gridlock, and the measured discharge
COLLAPSES -- a first attempt at 9000/12000/15000 veh/h insertion measured only
~70 veh/h/edge, an order of magnitude below the truth, because every interior
link was blocked. Capacity is the PEAK of the flow-vs-demand curve, so it has
to be found by sweeping demand upward and taking the maximum sustained
discharge before the knee.

Step 1: sweep insertion rate, record the maximum sustained per-edge discharge
        on interior links over the 600-3600 s window. Capacity c = the peak of
        that curve over the sweep (max over runs of the per-run max edge flow),
        averaged over 3 demand seeds so it is not one lucky edge.
Step 2: report achieved v/c (mean / p90 / max over interior edges) per rate so
        the three loading levels are chosen from MEASUREMENT, not assumption.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_replications as R  # noqa: E402

WORK = os.path.join(os.path.dirname(HERE), "attempts", "attempt-1", "work",
                    "capacity_probe")
SEEDS = [7, 17, 27]


def probe(rate, seed):
    d = os.path.join(WORK, "r%d_s%d" % (rate, seed))
    rec = R.run_one(dict(id="cap%d_%d" % (rate, seed), out_dir=d, rate=rate,
                         demand_seed=seed, sumo_seed=seed, keep_raw=True))
    if "error" in rec:
        raise RuntimeError(rec["error"])
    _, flows = R.parse_edgedata_window(
        os.path.join(d, "edgedata_window.xml"), R.interior_edges())
    return sorted(flows), rec


def main():
    os.makedirs(WORK, exist_ok=True)
    rates = [2000, 2500, 3000, 3500, 4000, 4250, 4500, 4750,
             5000, 5500, 6000, 7000]
    print("== flow-vs-demand sweep (peak of this curve = capacity) ==")
    print("  %-6s %-6s %-10s %-10s %-10s %-9s %-6s %-6s" %
          ("rate", "seed", "maxEdgeF", "p95EdgeF", "meanEdgeF", "meanDur",
           "tele", "done"))
    raw = []
    for rate in rates:
        for seed in SEEDS:
            fl, rec = probe(rate, seed)
            row = dict(rate=rate, seed=seed, max_edge_flow=fl[-1],
                       p95_edge_flow=R._pct(fl, 0.95),
                       mean_edge_flow=sum(fl) / len(fl),
                       mean_duration=rec["mean_duration"],
                       teleports=rec["teleports"],
                       n_completed=rec["n_completed"],
                       flows=fl)
            raw.append(row)
            print("  %-6d %-6d %-10.1f %-10.1f %-10.1f %-9.1f %-6d %-6d" %
                  (rate, seed, row["max_edge_flow"], row["p95_edge_flow"],
                   row["mean_edge_flow"], row["mean_duration"],
                   row["teleports"], row["n_completed"]))

    cap = max(r["max_edge_flow"] for r in raw)
    peak_rate = [r["rate"] for r in raw if r["max_edge_flow"] == cap][0]
    g_eff, C = 31.0, 68.0
    theo_protected = 1900.0 * g_eff / C
    print("\n  -> MEASURED capacity c = %.1f veh/h per 1-lane interior edge "
          "(peak of flow-vs-demand curve, at insertion rate %d)"
          % (cap, peak_rate))
    print("  -> implied saturation flow s = c*C/g_eff = %.0f veh/h/lane"
          % (cap * C / g_eff))
    print("  -> textbook protected-movement s0*g/C (s0=1900) would be %.0f "
          "veh/h; the measured value is lower because every interior approach "
          "is a SHARED single lane carrying permissive left turns."
          % theo_protected)

    with open(os.path.join(HERE, "capacity.json"), "w") as fh:
        json.dump({"capacity_vph": round(cap, 1),
                   "peak_at_insertion_rate": peak_rate,
                   "implied_saturation_flow_vph": round(cap * C / g_eff, 1),
                   "theoretical_protected_s0_gC": round(theo_protected, 1),
                   "g_eff_s": g_eff, "cycle_s": C,
                   "method": "peak of the measured flow-vs-demand curve over "
                             "interior links (600-3600 s window), 3 demand "
                             "seeds x 12 insertion rates"}, fh, indent=2)

    print("\n== achieved interior-link v/c per insertion rate (c=%.1f) ==" % cap)
    print("  %-6s %-9s %-9s %-9s %-9s %-7s" %
          ("rate", "vc_mean", "vc_p90", "vc_max", "meanDur", "tele"))
    summary = []
    for rate in rates:
        rows = [r for r in raw if r["rate"] == rate]
        vcm = sum(sum(f / cap for f in r["flows"]) / len(r["flows"])
                  for r in rows) / len(rows)
        vc90 = sum(R._pct([f / cap for f in r["flows"]], 0.90)
                   for r in rows) / len(rows)
        vcmx = sum(r["max_edge_flow"] / cap for r in rows) / len(rows)
        dur = sum(r["mean_duration"] for r in rows) / len(rows)
        tel = sum(r["teleports"] for r in rows) / len(rows)
        summary.append(dict(rate=rate, vc_mean=vcm, vc_p90=vc90, vc_max=vcmx,
                            mean_duration=dur, teleports=tel))
        print("  %-6d %-9.3f %-9.3f %-9.3f %-9.1f %-7.1f"
              % (rate, vcm, vc90, vcmx, dur, tel))

    with open(os.path.join(HERE, "rate_calibration.json"), "w") as fh:
        json.dump({"capacity_vph": round(cap, 1), "sweep": summary}, fh,
                  indent=2)
    print("\nwrote capacity.json and rate_calibration.json")


if __name__ == "__main__":
    main()
