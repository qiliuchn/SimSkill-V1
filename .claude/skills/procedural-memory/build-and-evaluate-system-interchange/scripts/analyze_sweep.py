#!/usr/bin/env python3
"""
Analyse the demand sweep: locate breakdown and sustained capacity per design, quantify
the weaving mechanism, and produce the comparison tables + plots.

METRIC DEFINITIONS (used identically in every table, plot and narrative in this study)
--------------------------------------------------------------------------------------
interchange throughput   vehicles COMPLETING their trip per hour during the measurement
                         window 600-2400 s, from summary output `ended`.
EB-A discharge flow      E1 flow summed over the 3 lanes of the most downstream EB-A
                         station (+3000 m), same window.
weaving-section speed    space-mean (harmonic, weighted by nVehSeen) speed over ALL lanes
                         of the weaving section's E2 detectors.
weaving-section density  q / v_space per lane, from the same detectors.
spillback fraction       fraction of 60 s intervals in the window in which the queue on
                         the WORST lane of a section reaches >=85% of that section's
                         length -- i.e. it has run out of storage and is discharging into
                         whatever lies upstream.  Worst-of-lanes, not per-lane mean,
                         because a queue filling ANY lane obstructs the upstream junction.
sustained capacity       the PEAK of the seed-mean throughput-vs-demand curve, NOT the
                         throughput at the heaviest demand tested (an oversaturated
                         network serves less than its own capacity).
breakdown demand         the lowest demand at which seed-mean weaving-section speed falls
                         below 50% of its free-flow value (measured at scale 0.50).
"""
import json
import math
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EPISODE = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
TAB = os.path.join(EPISODE, "outputs", "tables")
FIG = os.path.join(EPISODE, "outputs", "figures")
VARIANTS = ["clover", "cd", "flyover"]
LABEL = {"clover": "Full cloverleaf",
         "cd": "Cloverleaf + C-D roads",
         "flyover": "Par-clo + directional flyover"}
HEAVY_LEFT = "A-West|B-North"
WEAVE_PARTNER = "B-North|A-East"
THROUGH = "A-West|A-East"


def ms(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return (None, None)
    return (st.mean(xs), st.pstdev(xs) if len(xs) > 1 else 0.0)


def load(tag="base"):
    """Merge every sweep_*.json shard present (the sweep was extended upward in a second
    batch once it became clear the two mitigation designs had not yet peaked)."""
    rows = []
    for t in (tag, "high"):
        p = os.path.join(TAB, "sweep_%s.json" % t)
        if os.path.exists(p):
            rows += json.load(open(p))
    by = {}
    for r in rows:
        by.setdefault((r["variant"], r["scale"]), []).append(r)
    return rows, by


def dig(r, *path, default=None):
    cur = r
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return cur if cur is not None else default


def weave_group(r):
    """Name of the E2 group covering the carriageway where the study's heavy weaving
    pair meets.  In the flyover variant EB-A has no weaving pair at all, so its
    'weaving section' entry is the merge section that replaced it."""
    return "e2_weaveEB"


def summarise(by):
    out = {}
    for (v, sc), rs in sorted(by.items()):
        d = {}
        d["demand_vph"] = rs[0]["demand_total_vph"]
        d["n_seeds"] = len(rs)
        for key, path in [
            ("throughput", ("network_throughput_vph",)),
            ("q_out_EB", ("q_out_EB_vph",)),
            ("q_out_NB", ("q_out_NB_vph",)),
            ("mean_timeloss", ("mean_timeloss_s",)),
            ("teleports", ("teleports",)),
            ("collisions", ("collisions",)),
            ("not_inserted", ("not_inserted",)),
        ]:
            m, s = ms([dig(r, *path) for r in rs])
            d[key], d[key + "_sd"] = m, s
        wg = weave_group(rs[0])
        for key, path in [
            ("weave_speed", ("e2", wg, "mean_speed_ms")),
            ("weave_occ", ("e2", wg, "mean_occupancy_pct")),
            ("weave_spill", ("e2", wg, "spillback_fraction")),
            ("loopoff_spill", ("e2", "e2_loopoffEB", "spillback_fraction")),
            ("loopon_spill", ("e2", "e2_looponEB", "spillback_fraction")),
            ("loopoff_jam", ("e2", "e2_loopoffEB", "max_jam_len_m")),
            ("loopon_jam", ("e2", "e2_looponEB", "max_jam_len_m")),
            ("upstr_spill", ("e2", "e2_upstrEB", "spillback_fraction")),
            ("wbweave_spill", ("e2", "e2_weaveWB", "spillback_fraction")),
            ("wbweave_speed", ("e2", "e2_weaveWB", "mean_speed_ms")),
        ]:
            m, s = ms([dig(r, *path) for r in rs])
            d[key], d[key + "_sd"] = m, s
        # weaving density from the same detectors: k = q/(v*lanes)
        lanes = dig(rs[0], "e2", wg, "lanes", default=1)
        if d["weave_speed"] and d["q_out_EB"]:
            d["weave_density_veh_km_lane"] = round(
                d["q_out_EB"] / max(d["weave_speed"] * 3.6, 0.1) / lanes, 1)
        for mv, nm in [(HEAVY_LEFT, "heavyleft"), (WEAVE_PARTNER, "weavepair"),
                       (THROUGH, "through")]:
            for fld, sfx in [("mean_timeloss_s", "tl"), ("mean_duration_s", "dur"),
                             ("mean_route_len_m", "len")]:
                m, s = ms([dig(r, "movement", mv, fld) for r in rs])
                d["%s_%s" % (nm, sfx)] = m
        out[(v, sc)] = d
    return out


def analyse(summ):
    res = {}
    for v in VARIANTS:
        pts = sorted([(sc, d) for (vv, sc), d in summ.items() if vv == v])
        if not pts:
            continue
        free_v = pts[0][1]["weave_speed"]
        cap = max((d["throughput"] or 0) for _, d in pts)
        cap_sc = [sc for sc, d in pts if (d["throughput"] or 0) == cap][0]
        # breakdown: first demand where weaving speed < 50% of free-flow
        bd = None
        for sc, d in pts:
            if d["weave_speed"] is not None and free_v and d["weave_speed"] < 0.5 * free_v:
                bd = sc
                break
        # the demand at which served throughput first falls >5% short of demand
        bd_q = None
        for sc, d in pts:
            if d["throughput"] and d["demand_vph"] and d["throughput"] < 0.95 * d["demand_vph"]:
                bd_q = sc
                break
        res[v] = dict(
            free_flow_weave_speed_ms=round(free_v, 2) if free_v else None,
            sustained_capacity_vph=round(cap, 1),
            capacity_at_scale=cap_sc,
            capacity_at_demand_vph=dict(pts)[cap_sc]["demand_vph"],
            breakdown_scale_speed_criterion=bd,
            breakdown_scale_throughput_criterion=bd_q,
            throughput_at_1_20=dict(pts).get(1.20, {}).get("throughput"),
            max_teleports=max((d["teleports"] or 0) for _, d in pts),
            max_collisions=max((d["collisions"] or 0) for _, d in pts),
        )
    return res


# ------------------------------------------------------------------ output
def write_tables(summ, res):
    os.makedirs(TAB, exist_ok=True)
    # -- sweep table
    cols = ["variant", "scale", "demand_vph", "n_seeds", "throughput", "throughput_sd",
            "q_out_EB", "weave_speed", "weave_occ", "weave_density_veh_km_lane",
            "weave_spill", "loopoff_spill", "loopon_spill", "upstr_spill",
            "loopoff_jam", "mean_timeloss", "heavyleft_tl", "weavepair_tl", "through_tl",
            "teleports", "collisions", "not_inserted"]
    p = os.path.join(TAB, "sweep_summary.csv")
    with open(p, "w") as fh:
        fh.write(",".join(cols) + "\n")
        for (v, sc), d in sorted(summ.items()):
            row = [v, "%.2f" % sc]
            for c in cols[2:]:
                x = d.get(c)
                row.append("" if x is None else ("%.3f" % x if isinstance(x, float) else str(x)))
            fh.write(",".join(row) + "\n")

    # -- headline design comparison
    p2 = os.path.join(TAB, "design_comparison.csv")
    hdr = ["metric"] + [LABEL[v] for v in VARIANTS]
    def at(v, sc, key):
        return summ.get((v, sc), {}).get(key)
    rows = [
        ("Sustained capacity (veh/h, peak of throughput-demand curve)",
         [res[v]["sustained_capacity_vph"] for v in VARIANTS]),
        ("Demand at which capacity peaks (veh/h)",
         [res[v]["capacity_at_demand_vph"] for v in VARIANTS]),
        ("Breakdown demand scale (weaving speed < 50% free-flow)",
         [res[v]["breakdown_scale_speed_criterion"] for v in VARIANTS]),
        ("Breakdown demand scale (served < 95% of demand)",
         [res[v]["breakdown_scale_throughput_criterion"] for v in VARIANTS]),
        ("Weaving-section speed at scale 1.00 (m/s)", [at(v, 1.00, "weave_speed") for v in VARIANTS]),
        ("Weaving-section speed at scale 1.20 (m/s)", [at(v, 1.20, "weave_speed") for v in VARIANTS]),
        ("Weaving-section occupancy at scale 1.00 (%)", [at(v, 1.00, "weave_occ") for v in VARIANTS]),
        ("EB-A discharge flow at scale 1.20 (veh/h)", [at(v, 1.20, "q_out_EB") for v in VARIANTS]),
        ("Loop-off ramp spillback fraction at scale 1.20", [at(v, 1.20, "loopoff_spill") for v in VARIANTS]),
        ("Loop-on ramp spillback fraction at scale 1.20", [at(v, 1.20, "loopon_spill") for v in VARIANTS]),
        ("Mainline-upstream spillback fraction at scale 1.20", [at(v, 1.20, "upstr_spill") for v in VARIANTS]),
        ("Network mean time loss at scale 1.00 (s)", [at(v, 1.00, "mean_timeloss") for v in VARIANTS]),
        ("Network mean time loss at scale 1.20 (s)", [at(v, 1.20, "mean_timeloss") for v in VARIANTS]),
        ("Heavy left A-West->B-North time loss @1.00 (s)", [at(v, 1.00, "heavyleft_tl") for v in VARIANTS]),
        ("Heavy left A-West->B-North time loss @1.20 (s)", [at(v, 1.20, "heavyleft_tl") for v in VARIANTS]),
        ("Weaving partner B-North->A-East time loss @1.20 (s)", [at(v, 1.20, "weavepair_tl") for v in VARIANTS]),
        ("Through A-West->A-East time loss @1.20 (s)", [at(v, 1.20, "through_tl") for v in VARIANTS]),
        ("Heavy-left route length (m)", [at(v, 1.00, "heavyleft_len") for v in VARIANTS]),
        ("Through route length (m)", [at(v, 1.00, "through_len") for v in VARIANTS]),
        ("Max teleports over sweep", [res[v]["max_teleports"] for v in VARIANTS]),
        ("Max collisions over sweep", [res[v]["max_collisions"] for v in VARIANTS]),
    ]
    with open(p2, "w") as fh:
        fh.write(",".join('"%s"' % h for h in hdr) + "\n")
        for name, vals in rows:
            fh.write('"%s",' % name + ",".join(
                "" if x is None else ("%.2f" % x if isinstance(x, float) else str(x))
                for x in vals) + "\n")

    md = ["| Metric | " + " | ".join(LABEL[v] for v in VARIANTS) + " |",
          "|---|" + "---|" * len(VARIANTS)]
    for name, vals in rows:
        md.append("| %s | " % name + " | ".join(
            "-" if x is None else ("%.2f" % x if isinstance(x, float) else str(x))
            for x in vals) + " |")
    open(os.path.join(TAB, "design_comparison.md"), "w").write("\n".join(md) + "\n")
    return p, p2


def plots(summ, res):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib unavailable -- skipping plots")
        return
    os.makedirs(FIG, exist_ok=True)
    colors = {"clover": "#c0392b", "cd": "#2980b9", "flyover": "#27ae60"}

    def series(v, key):
        pts = sorted([(d["demand_vph"], d.get(key)) for (vv, sc), d in summ.items() if vv == v])
        return [p[0] for p in pts if p[1] is not None], [p[1] for p in pts if p[1] is not None]

    fig, ax = plt.subplots(2, 2, figsize=(13, 9))
    a = ax[0][0]
    for v in VARIANTS:
        x, y = series(v, "throughput")
        e = series(v, "throughput_sd")[1]
        a.errorbar(x, y, yerr=e, marker="o", ms=4, capsize=3, color=colors[v], label=LABEL[v])
    lim = max(max(series(v, "demand_vph")[1] or [0]) for v in VARIANTS)
    a.plot([0, lim], [0, lim], "k--", lw=1, label="served = demand")
    a.set_xlabel("total OD demand (veh/h)"); a.set_ylabel("interchange throughput (veh/h)")
    a.set_title("Discharge vs demand: breakdown and sustained capacity"); a.legend(fontsize=8); a.grid(alpha=.3)

    a = ax[0][1]
    for v in VARIANTS:
        x, y = series(v, "weave_speed")
        e = series(v, "weave_speed_sd")[1]
        a.errorbar(x, y, yerr=e, marker="s", ms=4, capsize=3, color=colors[v], label=LABEL[v])
    a.set_xlabel("total OD demand (veh/h)"); a.set_ylabel("space-mean speed (m/s)")
    a.set_title("Weaving section (EB-A) speed"); a.legend(fontsize=8); a.grid(alpha=.3)

    a = ax[1][0]
    for v in VARIANTS:
        for key, lsty, lab in [("loopoff_spill", "-", "loop-off ramp"),
                               ("upstr_spill", "--", "mainline upstream of weave")]:
            x, y = series(v, key)
            if x:
                a.plot(x, y, lsty, marker=".", color=colors[v],
                       label="%s: %s" % (LABEL[v][:14], lab))
    a.set_xlabel("total OD demand (veh/h)"); a.set_ylabel("spillback fraction")
    a.set_title("Queue spillback (>=85% of section filled)"); a.legend(fontsize=7); a.grid(alpha=.3)

    a = ax[1][1]
    for v in VARIANTS:
        for key, lsty, lab in [("through_tl", "-", "through A-W->A-E"),
                               ("heavyleft_tl", "--", "heavy left A-W->B-N"),
                               ("weavepair_tl", ":", "weave pair B-N->A-E")]:
            x, y = series(v, key)
            if x:
                a.plot(x, y, lsty, marker=".", color=colors[v],
                       label="%s: %s" % (LABEL[v][:14], lab))
    a.set_xlabel("total OD demand (veh/h)"); a.set_ylabel("mean time loss (s)")
    a.set_title("Time loss by movement"); a.legend(fontsize=6); a.grid(alpha=.3)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "sweep_overview.png"), dpi=130)
    print("wrote", os.path.join(FIG, "sweep_overview.png"))


def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else "base"
    rows, by = load(tag)
    summ = summarise(by)
    res = analyse(summ)
    p1, p2 = write_tables(summ, res)
    with open(os.path.join(TAB, "capacity_analysis.json"), "w") as fh:
        json.dump(res, fh, indent=1)
    plots(summ, res)
    print(json.dumps(res, indent=1))
    print("\ntables ->", p1, "\n         ", p2)


if __name__ == "__main__":
    main()
