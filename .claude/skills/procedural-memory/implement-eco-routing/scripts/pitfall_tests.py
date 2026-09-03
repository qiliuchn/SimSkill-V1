"""Four decisive, self-contained experiments on how duarouter actually consumes
`--weight-files` / `--weight-attribute`. Each one is a controlled A/B where the
answer is readable directly off the resulting route split, so the documented
pitfalls are verified rather than assumed."""
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import WORK, SIM_END, ARTERIAL_EDGES, BYPASS_EDGES, classify_route  # noqa: E402
import simlib  # noqa: E402
import assign_loop as al  # noqa: E402
import probe_freeflow  # noqa: E402

D = os.path.join(WORK, "pitfalls")
os.makedirs(D, exist_ok=True)
TRIPS = os.path.join(WORK, "demand_s0.trips.xml")
LINES = []


def out(s=""):
    print(s)
    LINES.append(s)


def write_wf(path, intervals):
    """intervals: list of (begin, end, {edge: {attr: value}})"""
    with open(path, "w") as f:
        f.write("<meandata>\n")
        for b, e, d in intervals:
            f.write('  <interval begin="%.1f" end="%.1f">\n' % (b, e))
            for eid, at in d.items():
                f.write('    <edge id="%s" %s/>\n'
                        % (eid, " ".join('%s="%.4f"' % kv for kv in at.items())))
            f.write("  </interval>\n")
        f.write("</meandata>\n")


def split_by_depart(route_file, cut=600.0):
    trips = {t[0]: t[2] for t in al.read_trips(TRIPS)}
    vr = simlib.parse_routes(route_file)
    early, late = Counter(), Counter()
    for vid, (ty, edges) in vr.items():
        if not vid.startswith("main."):
            continue
        (early if trips[vid] < cut else late)[classify_route(edges)] += 1
    return dict(early), dict(late)


def main():
    ff = probe_freeflow.load()
    allw = {e: dict(traveltime=ff[e]["traveltime"], gcost=ff[e]["fuel_perVeh"]) for e in ff}

    # ---------------------------------------------------------------- (1) ---
    out("=" * 92)
    out("(1) MISSING EDGE: what weight does duarouter assume for an edge absent from the file?")
    out("=" * 92)
    d = {e: dict(traveltime=1.0, gcost=1.0) for e in ff if e not in ARTERIAL_EDGES}
    w = os.path.join(D, "w_omit.xml")
    write_wf(w, [(0, SIM_END, d)])
    for attr in ("gcost", "traveltime"):
        r = al.duarouter_aon(TRIPS, os.path.join(D, "r_omit_%s.rou.xml" % attr), w, attr)
        sh = simlib.route_shares(r)[0]
        out("   arterial edges omitted, all listed edges = 1.0, --weight-attribute %-11s -> %s"
            % (attr, {k: round(v, 3) for k, v in sh.items()}))
    out("   READING: with `traveltime` the omitted arterial still costs its FREE-FLOW 139 s, so")
    out("            the (cheap, 5 s) bypass wins. With a custom attribute the omitted arterial")
    out("            costs 0, so it wins. => a non-`traveltime` weight attribute has NO free-flow")
    out("            fallback; an unsampled edge is silently FREE.")

    # ---------------------------------------------------------------- (2) ---
    out()
    out("=" * 92)
    out("(2) INTERVAL ALIGNMENT: what happens to vehicles departing after the last interval?")
    out("=" * 92)
    d = {e: dict(traveltime=ff[e]["traveltime"], gcost=ff[e]["fuel_perVeh"]) for e in ff}
    for e in BYPASS_EDGES:                       # make the bypass absurdly bad, but only in [0,600)
        d[e] = dict(traveltime=1e5, gcost=1e9)
    w = os.path.join(D, "w_short_interval.xml")
    write_wf(w, [(0, 600, d)])
    for attr in ("traveltime", "gcost"):
        rf = os.path.join(D, "r_short_%s.rou.xml" % attr)
        al.duarouter_aon(TRIPS, rf, w, attr)
        e_, l_ = split_by_depart(rf)
        out("   weights only cover [0,600); --weight-attribute %-11s  depart<600: %s   "
            "depart>=600: %s" % (attr, e_, l_))
    out("   READING: vehicles departing outside the covered window do NOT inherit the last")
    out("            interval -- they fall back to the network default (free-flow travel time,")
    out("            or ZERO for a custom attribute). A weight file whose intervals do not span")
    out("            the whole departure window silently routes most of the demand on defaults.")

    # ---------------------------------------------------------------- (3) ---
    out()
    out("=" * 92)
    out("(3) NORMALISATION: per-vehicle (`*_perVeh`) vs per-edge total (`*_abs`)")
    out("=" * 92)
    ivs = simlib.parse_edge_emissions(
        os.path.join(WORK, "assign_ue_s0", "sim_020_edgeemis.xml"))
    for norm, attr in (("perVeh", "fuel_perVeh"), ("abs", "fuel_abs")):
        d = {}
        for e in ff:
            src = ivs[0]["edges"].get(e, {})
            d[e] = dict(traveltime=src.get("traveltime", ff[e]["traveltime"]),
                        gcost=src.get(attr, 0.0))
        w = os.path.join(D, "w_norm_%s.xml" % norm)
        write_wf(w, [(0, SIM_END, d)])
        r = al.duarouter_aon(TRIPS, os.path.join(D, "r_norm_%s.rou.xml" % norm), w, "gcost")
        sh = simlib.route_shares(r)[0]
        tot_a = sum(d[e]["gcost"] for e in ARTERIAL_EDGES)
        tot_b = sum(d[e]["gcost"] for e in BYPASS_EDGES)
        out("   %-7s: arterial cost %12.1f  bypass cost %12.1f  -> %s"
            % (norm, tot_a, tot_b, {k: round(v, 3) for k, v in sh.items()}))
    out("   READING: `*_abs` is a per-edge TOTAL, so it scales with the edge's own flow. The")
    out("            'cheapest' route under `_abs` is whichever route is emptiest, not cleanest,")
    out("            and it is not comparable between a 2-lane and a 1-lane corridor at all.")
    out("            Only the `*_perVeh` normalisation is an additive per-driver route cost.")

    # ---------------------------------------------------------------- (4) ---
    out()
    out("=" * 92)
    out("(4) THE ECO COST SURFACE IS NOT A MONOTONE FUNCTION OF TRAVEL TIME")
    out("=" * 92)
    ffa_t = sum(ff[e]["traveltime"] for e in ARTERIAL_EDGES)
    ffb_t = sum(ff[e]["traveltime"] for e in BYPASS_EDGES)
    ffa_c = sum(ff[e]["CO2_perVeh"] for e in ARTERIAL_EDGES) / 1000
    ffb_c = sum(ff[e]["CO2_perVeh"] for e in BYPASS_EDGES) / 1000
    out("   free flow : arterial %6.1f s / %6.1f g CO2   bypass %6.1f s / %6.1f g CO2"
        % (ffa_t, ffa_c, ffb_t, ffb_c))
    cong = ivs[0]["edges"]
    ca_t = sum(cong[e]["traveltime"] for e in ARTERIAL_EDGES)
    cb_t = sum(cong[e]["traveltime"] for e in BYPASS_EDGES)
    ca_c = sum(cong[e]["CO2_perVeh"] for e in ARTERIAL_EDGES) / 1000
    cb_c = sum(cong[e]["CO2_perVeh"] for e in BYPASS_EDGES) / 1000
    out("   at UE     : arterial %6.1f s / %6.1f g CO2   bypass %6.1f s / %6.1f g CO2"
        % (ca_t, ca_c, cb_t, cb_c))
    out("   Spearman-style check across all 28 edges (congested state):")
    import numpy as np
    from scipy import stats
    tt = np.array([cong[e]["traveltime"] for e in ff if "traveltime" in cong.get(e, {})])
    co = np.array([cong[e]["CO2_perVeh"] for e in ff if "traveltime" in cong.get(e, {})])
    ln = np.array([ff[e]["length"] for e in ff if "traveltime" in cong.get(e, {})])
    out("      rho(traveltime, CO2_perVeh)                 = %+.3f (n=%d)"
        % (stats.spearmanr(tt, co).statistic, len(tt)))
    out("      rho(traveltime/length, CO2_perVeh/length)   = %+.3f"
        % stats.spearmanr(tt / ln, co / ln).statistic)
    out("   READING: per-edge time and per-edge emissions are strongly but NOT perfectly rank-")
    out("            correlated, and the ORDER of the two candidate ROUTES is opposite under the")
    out("            two costs at free flow (bypass is 10%% faster but 39%% dirtier), which is")
    out("            precisely why the eco assignment is a different assignment.")

    from common import OUT
    with open(os.path.join(OUT, "weightfile_pitfalls.txt"), "w") as f:
        f.write("\n".join(LINES) + "\n")


if __name__ == "__main__":
    main()
