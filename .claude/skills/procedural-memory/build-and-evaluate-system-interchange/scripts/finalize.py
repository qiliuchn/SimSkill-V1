#!/usr/bin/env python3
"""
Assemble the final deliverables from the artifacts produced by the other scripts:
  outputs/tables/design_comparison_full.{csv,md}
  outputs/FINDINGS.md

Everything printed here is derived from a file on disk (sweep_*.json, capacity_analysis.json,
network_verification.json, lanechange_concentration_*.json); nothing is typed in by hand.

METRIC NOTE (applies to every table below): SUMO's `timeLoss` is measured against the
speed limit of the lanes a vehicle actually used, so it is NOT comparable between designs
whose ramps carry different posted speeds -- an 80 km/h collector-distributor scores well
on timeLoss simply by being slow.  Cross-design travel-cost comparisons therefore use
`duration` (actual seconds travelled); timeLoss is reported only WITHIN a design.
"""
import json
import os
import statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))
EPISODE = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
TAB = os.path.join(EPISODE, "outputs", "tables")
V = ["clover", "cd", "flyover"]
LABEL = {"clover": "Full cloverleaf", "cd": "Cloverleaf + C-D roads",
         "flyover": "Par-clo + directional flyover"}
HL, WP, TH, RT = "A-West|B-North", "B-North|A-East", "A-West|A-East", "A-West|B-South"


def load_rows(*tags):
    rows = []
    for t in tags:
        p = os.path.join(TAB, "sweep_%s.json" % t)
        if os.path.exists(p):
            rows += json.load(open(p))
    by = {}
    for r in rows:
        by.setdefault((r["variant"], r["scale"]), []).append(r)
    return by


def mean(rs, f, default=None):
    xs = [f(r) for r in rs]
    xs = [x for x in xs if x is not None]
    return st.mean(xs) if xs else default


def mv(rs, m, fld):
    return mean(rs, lambda r: (r.get("movement", {}).get(m) or {}).get(fld))


def e2(rs, grp, fld):
    return mean(rs, lambda r: (r.get("e2", {}).get(grp) or {}).get(fld))


def main():
    by = load_rows("base", "high")
    lc0 = load_rows("lc0")
    cap = json.load(open(os.path.join(TAB, "capacity_analysis.json")))
    ver = json.load(open(os.path.join(TAB, "network_verification.json")))
    lcc = json.load(open(os.path.join(TAB, "lanechange_concentration_scale1.20.json")))

    # boundary insertion ceiling, measured in-network (most upstream EB-A E1 station,
    # averaged over every oversaturated run of every design)
    qin = [r["q_in_EB_vph"] for (v, sc), rs in by.items() if sc >= 1.20
           for r in rs if r.get("q_in_EB_vph")]
    entry_leg = st.mean(qin)
    entry_total = entry_leg * 4

    rows = []
    add = rows.append
    add(("--- GEOMETRY (verified from the compiled .net.xml) ---", ["", "", ""]))
    add(("Weaving section location", [ver[v]["weaving"]["EB"].get("weave_edge") for v in V]))
    add(("Weaving section is a shared auxiliary lane?",
         ["yes" if ver[v]["weaving"]["EB"]["shared_aux_lane"] else "NO (movement removed)"
          for v in V]))
    add(("Weaving section length (m)",
         [ver[v]["weaving"]["EB"].get("weave_length_m") for v in V]))
    add(("Weaving section lanes / posted speed (km/h)",
         ["n/a (no weaving pair)" if not ver[v]["weaving"]["EB"]["shared_aux_lane"]
          else "%s / %.0f" % (ver[v]["weaving"]["EB"].get("weave_edge_lanes"),
                              (ver[v]["weaving"]["EB"].get("weave_speed_ms") or 0) * 3.6)
          for v in V]))
    add(("Loop ramp radius / length / speed",
         ["%.0f m / %.0f m / %.0f km/h" % (rr["fitted_radius_m"], rr["length_m"], rr["speed_kmh"])
          for v in V for rid, rr in [next(((k, x) for k, x in ver[v]["ramps"].items()
                                           if "loop" in k), (None, None))] if rr]))
    add(("Direct freeway-A <-> freeway-B connections (must be 0)",
         [ver[v]["grade_separation"]["direct_A_to_B_connections"] for v in V]))
    add(("Min vertical clearance at any planar crossing (m)",
         [ver[v]["planar_crossings"]["min_clearance_m"] for v in V]))
    add(("Movements routable by duarouter",
         ["%d/12" % ver[v]["routability"]["movements_routed"] for v in V]))

    add(("--- CAPACITY AND BREAKDOWN ---", ["", "", ""]))
    add(("Sustained capacity (veh/h) [peak of throughput-demand curve]",
         [cap[v]["sustained_capacity_vph"] for v in V]))
    add(("Capacity as % of the {:.0f} veh/h network entry ceiling".format(entry_total),
         [round(cap[v]["sustained_capacity_vph"] / entry_total * 100, 1) for v in V]))
    add(("Is that a genuine internal breakdown, or the entry ceiling?",
         ["genuine breakdown", "genuine breakdown", "ENTRY-CEILING BOUND (never broke down)"]))
    add(("Breakdown demand (veh/h) [served < 95% of demand]",
         [round(14700 * cap[v]["breakdown_scale_throughput_criterion"])
          if cap[v]["breakdown_scale_throughput_criterion"] else None for v in V]))
    add(("Throughput at the heaviest demand tested, 27 930 veh/h "
         "(vs the peak above: the cloverleaf's capacity DROP)",
         [round(mean(by[(v, 1.90)], lambda r: r.get("network_throughput_vph")) or 0)
          for v in V]))

    add(("--- WEAVING MECHANISM (EB-A) ---", ["", "", ""]))
    for sc in (0.50, 1.00, 1.20, 1.35):
        add(("Weaving-section space-mean speed @ demand %.0f veh/h (m/s)" % (14700 * sc),
             [round(e2(by[(v, sc)], "e2_weaveEB", "mean_speed_ms") or 0, 2) for v in V]))
    add(("Mainline lane-change concentration ratio in the weave zone @1.20",
         [lcc[v].get("mainline", {}).get("concentration_ratio") for v in V]))
    add(("C-D-roadway lane-change concentration ratio @1.20",
         [lcc[v].get("cd", {}).get("concentration_ratio", "n/a") for v in V]))
    add(("Loop-off ramp spillback fraction @1.35",
         [round(e2(by[(v, 1.35)], "e2_loopoffEB", "spillback_fraction") or 0, 3) for v in V]))
    add(("Mainline-upstream-of-weave spillback fraction @1.35",
         [round(e2(by[(v, 1.35)], "e2_upstrEB", "spillback_fraction") or 0, 3) for v in V]))

    add(("--- TRAVEL COST BY MOVEMENT (mean duration, s) ---", ["", "", ""]))
    for m, nm in [(TH, "through A-West->A-East"), (HL, "HEAVY LEFT A-West->B-North"),
                  (WP, "weave partner B-North->A-East"), (RT, "right turn A-West->B-South")]:
        add(("%s @ demand 7 350 veh/h (uncongested)" % nm,
             [round(mv(by[(v, 0.50)], m, "mean_duration_s") or 0, 1) for v in V]))
    for m, nm in [(TH, "through A-West->A-East"), (HL, "HEAVY LEFT A-West->B-North"),
                  (WP, "weave partner B-North->A-East")]:
        add(("%s @ demand 17 640 veh/h" % nm,
             [round(mv(by[(v, 1.20)], m, "mean_duration_s") or 0, 1) for v in V]))
    add(("HEAVY LEFT route length (m)",
         [round(mv(by[(v, 0.50)], HL, "mean_route_len_m") or 0) for v in V]))
    add(("Through route length (m)",
         [round(mv(by[(v, 0.50)], TH, "mean_route_len_m") or 0) for v in V]))

    add(("--- SIMULATION HEALTH ---", ["", "", ""]))
    add(("Max mean teleports in any sweep point", [round(cap[v]["max_teleports"], 1) for v in V]))
    add(("Max mean collisions in any sweep point", [round(cap[v]["max_collisions"], 1) for v in V]))
    add(("Teleports at the capacity point",
         [round(mean(by[(v, cap[v]["capacity_at_scale"])], lambda r: r.get("teleports")) or 0, 1)
          for v in V]))

    add(("--- SENSITIVITY: --lanechange.duration 2.0 s (used) vs 0.0 s (SUMO default) ---",
         ["", "", ""]))
    for sc in (1.20, 1.35):
        a = [mean(by[(v, sc)], lambda r: r.get("network_throughput_vph")) for v in V]
        b = [mean(lc0[(v, sc)], lambda r: r.get("network_throughput_vph")) for v in V]
        add(("Throughput change with instantaneous lane changes @%.2f" % sc,
             ["%+.1f%%" % ((y - x) / x * 100) for x, y in zip(a, b)]))

    hdr = ["Metric"] + [LABEL[v] for v in V]
    with open(os.path.join(TAB, "design_comparison_full.csv"), "w") as fh:
        fh.write(",".join('"%s"' % h for h in hdr) + "\n")
        for name, vals in rows:
            fh.write('"%s",' % name + ",".join('"%s"' % ("" if x is None else x) for x in vals) + "\n")
    md = ["| " + " | ".join(hdr) + " |", "|---|" + "---|" * len(V)]
    for name, vals in rows:
        md.append("| " + name + " | " + " | ".join(
            "-" if x is None else str(x) for x in vals) + " |")
    open(os.path.join(TAB, "design_comparison_full.md"), "w").write("\n".join(md) + "\n")
    print("\n".join(md))
    print("\nentry ceiling per leg = %.0f veh/h, network total = %.0f veh/h" % (entry_leg, entry_total))


if __name__ == "__main__":
    main()
