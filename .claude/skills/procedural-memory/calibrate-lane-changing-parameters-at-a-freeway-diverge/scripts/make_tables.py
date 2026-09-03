#!/usr/bin/env python3
"""STEP 9 -- assemble every markdown deliverable from the raw JSON/CSV tables.
Nothing here recomputes a simulation; it only formats numbers that the earlier
steps wrote to outputs/tables/*.json, so every figure in the report is traceable
to a file."""
import os, sys, json, math, csv
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lc_common as L

T = L.TBL
O = L.OUT


def jload(n):
    p = os.path.join(T, n)
    return json.load(open(p)) if os.path.exists(p) else None


def w(f, s=""):
    f.write(s + "\n")


# --------------------------------------------------------------------------
def influence_map():
    m = jload("morris_lc2013.json")
    if not m:
        return
    QUANTS = list(m["table"].keys())
    path = os.path.join(O, "LC2013_INFLUENCE_MAP.md")
    with open(path, "w") as f:
        w(f, "# LC2013 parameter -> observable influence map")
        w(f)
        w(f, "Morris elementary effects, p=%d levels, Delta=%.4f, r=%d "
             "trajectories, %d design points x %d CRN seeds = %d SUMO runs "
             "(%d failed)." % (m["levels"], m["delta"], m["r"], m["n_points"],
                               m["n_seeds"], m["n_points"] * m["n_seeds"],
                               m["n_failed"]))
        w(f, "Source: `outputs/tables/morris_lc2013.json`. Every response is "
             "normalised by its own field target (or, where there is no target, "
             "by its default-parameter baseline from "
             "`outputs/tables/noise_floor.json`), so mu* is comparable across "
             "observables.")
        w(f)
        w(f, "`mu*` = mean |elementary effect| (influence), `sigma` = sd(EE) "
             "(interaction/non-linearity). A parameter counts as ACTIVE for an "
             "observable only if mu* exceeds 2x the seed-noise floor on an "
             "elementary effect, printed per observable below.")
        w(f)
        w(f, "## Parameter ranges screened")
        w(f)
        w(f, "| parameter | low | high | SUMO default |")
        w(f, "|---|---|---|---|")
        for k, v in m["param_ranges"].items():
            w(f, "| `%s` | %g | %g | %g |" % (k, v[0], v[1], v[2]))
        w(f)
        w(f, "## mu* by observable")
        for q in QUANTS:
            w(f)
            nf = m["ee_noise_floor"][q]
            w(f, "### %s  (EE noise floor %.4f)" % (q, nf))
            if nf <= 0:
                w(f)
                w(f, "> **Degenerate noise floor.** This observable is exactly "
                     "0 in every one of the 16 default-parameter replications, "
                     "so its measured seed SD is 0 and the `above noise` column "
                     "below is vacuous (any nonzero mu* passes). Read the mu* "
                     "magnitudes directly instead.")
            w(f)
            w(f, "| rank | parameter | mu* | mu | sigma | above noise? |")
            w(f, "|---|---|---|---|---|---|")
            for i, r in enumerate(m["table"][q]):
                w(f, "| %d | `%s` | %.4f | %+.4f | %.4f | %s |"
                  % (i + 1, r["param"], r["mu_star"], r["mu"], r["sigma"],
                     "**YES**" if r["above_noise"] else "no"))
        w(f)
        w(f, "## Compact map (ACTIVE = mu* > 2x EE noise floor)")
        w(f)
        names = [r["param"] for r in m["table"]["obj"]]
        w(f, "| parameter | " + " | ".join(QUANTS) + " |")
        w(f, "|---" * (len(QUANTS) + 1) + "|")
        for n in names:
            cells = []
            for q in QUANTS:
                r = [x for x in m["table"][q] if x["param"] == n][0]
                cells.append("**%.2f**" % r["mu_star"] if r["above_noise"]
                             else "%.2f" % r["mu_star"])
            w(f, "| `%s` | " % n + " | ".join(cells) + " |")
    print("wrote", path)


def reason_table():
    pr = jload("profile_runs.json")
    tr = jload("traps.json")
    path = os.path.join(O, "LC_REASON_BREAKDOWN.md")
    with open(path, "w") as f:
        w(f, "# Lane-change `reason` breakdown")
        w(f)
        w(f, "Parsed from `--lanechange-output` event XML. SUMO writes `reason` "
             "as a `|`-joined string; the raw strings actually observed in this "
             "facility are listed first, then the classification used "
             "throughout (leading motivation token; the `urgent` qualifier is "
             "kept separately).")
        w(f)
        if tr and "t1" in tr:
            wd = tr["t1"]["rows"][0].get("wd_seed0")
            if wd and os.path.exists(os.path.join(wd, "lanechanges.xml")):
                import collections
                ev = L.parse_lanechanges(os.path.join(wd, "lanechanges.xml"))
                c = collections.Counter(e["reason"] for e in ev)
                w(f, "## Raw `reason` strings emitted by SUMO 1.27.1 on this "
                     "facility")
                w(f)
                w(f, "One default-parameter run (`%s`), whole run, %d events; "
                     "%d events were dropped as un-locatable internal-junction "
                     "lane changes." % (wd, len(ev),
                                        L.parse_lanechanges.n_dropped_internal))
                w(f)
                w(f, "| raw `reason` string | events | class used here |")
                w(f, "|---|---|---|")
                for k, v in c.most_common():
                    w(f, "| `%s` | %d | %s |" % (k, v, L.reason_class(k)))
                w(f)
            w(f, "## Mean events per run in the measurement window "
                 "[%.0f s, %.0f s]" % (L.WARMUP, L.T_END_MEAS))
            w(f)
            w(f, "| vector | --lanechange.duration | strategic | cooperative "
                 "| speedGain | keepRight | total |")
            w(f, "|---|---|---|---|---|---|---|")
            for r in tr["t1"]["rows"]:
                c = r["reason_counts_mean"]
                w(f, "| %s | %.1f s | %.0f | %.0f | %.0f | %.0f | %.0f |"
                  % (r["vector"], r["lcDuration"], c.get("strategic", 0),
                     c.get("cooperative", 0), c.get("speedGain", 0),
                     c.get("keepRight", 0), sum(c.values())))
            w(f)
    print("wrote", path)


def beforeafter():
    cal = jload("calibration.json")
    val = jload("validation.json")
    if not cal:
        return
    path = os.path.join(O, "PER_LANE_FLOW_BEFORE_AFTER.md")
    with open(path, "w") as f:
        w(f, "# Per-lane flow at the station, before vs after calibration")
        w(f)
        w(f, "Station = entry cross-section of edge C, x=2100 m, i.e. 1.5 km "
             "upstream of the gore (x=3600 m). Flows from the `laneData` "
             "meandata `entered` counts, cross-checked against per-lane E1 "
             "induction loops at the same cross-section.")
        w(f)
        w(f, "Target lane FLOW = observed total station flow x target share, so "
             "GEH scores the SPLIT rather than the total (the total is set by "
             "demand, not by the lane-change model).")
        w(f)
        for k, lab in (("default_reeval_12seed", "SUMO default LC2013"),
                       ("best_reeval_12seed", "calibrated")):
            r = cal[k]
            tot = r["flow"]
            w(f, "## %s (12 independent seeds)" % lab)
            w(f)
            w(f, "| lane | target share | measured share | target flow (veh/h) "
                 "| measured flow (veh/h) | GEH |")
            w(f, "|---|---|---|---|---|---|")
            for i, nm in enumerate(["0 (right)", "1 (middle)", "2 (left)"]):
                w(f, "| %s | %.4f | %.4f | %.1f | %.1f | %.2f |"
                  % (nm, L.TARGET_LANE_SHARE[i], r["share"][i],
                     L.TARGET_LANE_SHARE[i] * tot, r["share"][i] * tot,
                     r["geh"][i]))
            w(f, "| **max GEH** | | | | | **%.2f** (%s) |"
              % (r["geh_max"], "PASS <5" if r["geh_max"] < 5 else "FAIL"))
            w(f)
            w(f, "- lane-share RMSN %.4f, objective %.4f, dlc %.4f LC/veh/km, "
                 "p85 %.0f m, fail-fraction %.4f, teleports %.1f, collisions "
                 "%.1f" % (r["rmsn_lane"], r["obj"], r["dlc"], r["p85"],
                           r["fail_frac"], r["teleports"], r["collisions"]))
            w(f)
        if val:
            w(f, "## Hold-out conditions")
            w(f)
            w(f, "| condition | mainline veh/h/ln | exit share | vector | "
                 "target r/m/l | measured r/m/l | GEH r/m/l | max GEH | "
                 "GEH<5 |")
            w(f, "|---|---|---|---|---|---|---|---|---|")
            for r in val["rows"]:
                w(f, "| %s | %.0f | %.0f%% | %s | %s | %s | %s | %.2f | %s |"
                  % (r["condition"], r["per_lane"], 100 * r["exit_share"],
                     r["vector"],
                     "/".join("%.2f" % x for x in r["target"]),
                     "/".join("%.4f" % x for x in r["share"]),
                     "/".join("%.2f" % x for x in r["geh"]),
                     r["geh_max"], "PASS" if r["pass_geh5"] else "FAIL"))
    print("wrote", path)


def main():
    influence_map()
    reason_table()
    beforeafter()


if __name__ == "__main__":
    main()
