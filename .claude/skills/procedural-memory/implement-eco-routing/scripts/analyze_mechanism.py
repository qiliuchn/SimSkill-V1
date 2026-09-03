"""Why does network CO2 rise with eco-router penetration?

Decomposes the penetration sweep into (a) how many vehicles used each corridor,
(b) how far they drove, and (c) how dirty each corridor became per vehicle-km,
so the rebound can be attributed to a mechanism rather than asserted.
"""
import glob
import json
import os
import statistics
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import WORK, OUT, ARTERIAL_EDGES, BYPASS_EDGES, classify_route  # noqa: E402
import simlib  # noqa: E402

SWEEP = os.path.join(WORK, "sweep")
SEEDS = [0, 1, 2, 3, 4]
PENS = [0.0, 0.25, 0.5, 0.75, 1.0]


def main():
    lines = []

    def out(s=""):
        print(s)
        lines.append(s)

    out("=" * 112)
    out("MECHANISM: per-route-class outcomes vs eco-router penetration (tag=pen, lam=1, "
        "mean over 5 seeds)")
    out("=" * 112)
    out("%-6s %-9s %7s %9s %9s %9s %9s %9s %9s" %
        ("pen", "class", "n", "dur s", "wait s", "km", "CO2 g", "g CO2/km", "g/veh-km"))
    per_pen = {}
    for p in PENS:
        acc = {}
        for s in SEEDS:
            pre = os.path.join(SWEEP, "pen_p%03d_s%d" % (round(p * 100), s))
            ti = simlib.parse_tripinfo(pre + "_tripinfo.xml")
            vr = simlib.parse_routes(pre + "_vehroute.xml")
            for t in ti:
                if not t["id"].startswith("main."):
                    continue
                cls = classify_route(vr.get(t["id"], ("", []))[1])
                acc.setdefault(cls, []).append(t)
        per_pen[p] = acc
        for cls in ("arterial", "bypass", "hybrid"):
            v = acc.get(cls)
            if not v:
                continue
            km = statistics.mean(t["routeLength"] for t in v) / 1000.0
            co2 = statistics.mean(t["CO2"] for t in v) / 1000.0
            out("%-6.0f%% %-9s %7.1f %9.1f %9.1f %9.3f %9.1f %9.1f %9.1f" %
                (p * 100, cls, len(v) / len(SEEDS),
                 statistics.mean(t["duration"] for t in v),
                 statistics.mean(t["waitingTime"] for t in v),
                 km, co2, co2 / km, co2 / km))

    out()
    out("=" * 112)
    out("Network totals and vehicle-km, and the two components of the CO2 change")
    out("=" * 112)
    out("%-6s %12s %12s %14s %14s %12s" %
        ("pen", "main veh-km", "netCO2 kg", "art g/veh-km", "byp g/veh-km", "mean g/vkm"))
    for p in PENS:
        allv = [t for v in per_pen[p].values() for t in v]
        vkm = sum(t["routeLength"] for t in allv) / 1000.0 / len(SEEDS)
        co2 = sum(t["CO2"] for t in allv) / 1e6 / len(SEEDS)

        def rate(cls):
            v = per_pen[p].get(cls)
            if not v:
                return float("nan")
            return sum(t["CO2"] for t in v) / 1000.0 / (sum(t["routeLength"] for t in v) / 1000.0)
        out("%-6.0f%% %12.0f %12.1f %14.1f %14.1f %12.1f" %
            (p * 100, vkm, co2, rate("arterial"), rate("bypass"),
             sum(t["CO2"] for t in allv) / 1000.0 / vkm / len(SEEDS)))

    out()
    out("Shapley-style decomposition of main-OD CO2 vs the 0% baseline:")
    out("   dCO2 = (dVKT) * rate_0   +   VKT_1 * (drate)   [+ interaction]")
    base = [t for v in per_pen[0.0].values() for t in v]
    vkm0 = sum(t["routeLength"] for t in base) / 1e3 / len(SEEDS)
    co20 = sum(t["CO2"] for t in base) / 1e6 / len(SEEDS)
    r0 = co20 * 1000 / vkm0
    for p in PENS[1:]:
        allv = [t for v in per_pen[p].values() for t in v]
        vkm1 = sum(t["routeLength"] for t in allv) / 1e3 / len(SEEDS)
        co21 = sum(t["CO2"] for t in allv) / 1e6 / len(SEEDS)
        r1 = co21 * 1000 / vkm1
        d_vkt = (vkm1 - vkm0) * r0 / 1000.0
        d_rate = vkm0 * (r1 - r0) / 1000.0
        inter = (co21 - co20) - d_vkt - d_rate
        out("   %3.0f%%: total %+7.1f kg = distance effect %+7.1f  +  intensity effect %+7.1f "
            " + interaction %+6.1f" % (p * 100, co21 - co20, d_vkt, d_rate, inter))

    # per-edge emissions intensity on the arterial (stop-and-go signal)
    out()
    out("=" * 112)
    out("Per-EDGE emission intensity from edgeData (mean over seeds), arterial vs bypass")
    out("=" * 112)
    out("%-6s %10s %12s %12s %12s %12s" %
        ("pen", "corridor", "veh (samp)", "mean tt s", "CO2 g/veh", "g CO2/km"))
    from common import NET
    sys.path.insert(0, os.path.join(os.environ["SUMO_HOME"], "tools"))
    import sumolib
    net = sumolib.net.readNet(NET)
    for p in PENS:
        agg = {"arterial": [], "bypass": []}
        for s in SEEDS:
            pre = os.path.join(SWEEP, "pen_p%03d_s%d" % (round(p * 100), s))
            iv = simlib.parse_edge_emissions(pre + "_edgeemis.xml")[0]
            for name, eids in (("arterial", ARTERIAL_EDGES), ("bypass", BYPASS_EDGES)):
                tt = sum(iv["edges"][e].get("traveltime", 0) for e in eids)
                co2 = sum(iv["edges"][e].get("CO2_perVeh", 0) for e in eids) / 1000.0
                ln = sum(net.getEdge(e).getLength() for e in eids) / 1000.0
                agg[name].append((tt, co2, ln))
        for name in ("arterial", "bypass"):
            a = np.array(agg[name])
            out("%-6.0f%% %10s %12s %12.1f %12.1f %12.1f" %
                (p * 100, name, "-", a[:, 0].mean(), a[:, 1].mean(),
                 a[:, 1].mean() / a[0, 2]))

    with open(os.path.join(OUT, "mechanism_analysis.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\nwrote", os.path.join(OUT, "mechanism_analysis.txt"))


if __name__ == "__main__":
    main()
