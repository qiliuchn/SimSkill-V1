#!/usr/bin/env python3
"""Robustness re-analysis of the retained tripinfo files.

Threat: every run is a TERMINATING simulation -- demand is generated up to
t=3000 s and the run ends at t=3000 s, so vehicles departing in roughly the last
mean-trip-duration of the horizon physically cannot complete and therefore never
appear in tripinfo. Aggregating over departures in [600, 3000) is thus a
right-censored sample.

This script re-aggregates the SAME retained tripinfo files over the strictly
uncensored departure window [600, 2400) -- 2400 + a ~350 s worst-case trip is
still inside the 3000 s horizon -- and checks whether any headline conclusion
changes sign or significance. It also reports the completed / still-running /
teleport accounting per arm so the reader can see the censoring is BALANCED
across the arms a paired CRN comparison differences out.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arterial_lib as A     # noqa: E402
import expbase as B          # noqa: E402

WINDOWS = [(600.0, 3000.0), (600.0, 2400.0), (600.0, 2100.0)]


def redo(dirs, cohorts=("thruE", "thruW", "all")):
    """dir -> {window -> {cohort -> stats}} from the retained tripinfo.xml."""
    out = {}
    for tag, d in dirs.items():
        tp = os.path.join(d, "tripinfo.xml")
        sm = os.path.join(d, "summary.xml")
        if not os.path.exists(tp):
            out[tag] = None
            continue
        rows = A.parse_tripinfo(tp)
        tele = A.teleport_ids(open(os.path.join(d, "stderr.log")).read()) \
            if os.path.exists(os.path.join(d, "stderr.log")) else set()
        summ = A.parse_summary(sm) if os.path.exists(sm) else {}
        rec = dict(summary=summ, n_teleport=len(tele))
        for w in WINDOWS:
            st = A.stats(rows, t0=w[0], t1=w[1], teleported=tele)
            rec["%.0f-%.0f" % w] = {c: st.get(c) for c in cohorts}
        out[tag] = rec
    return out


def paired_benefit(rows_a, rows_b, key, cohort, w):
    a = [r[w][cohort][key] for r in rows_a]
    b = [r[w][cohort][key] for r in rows_b]
    return A.paired(a, b)


def main():
    rep = {}

    # ---- H6, L=300 m: does the benefit reversal survive uncensoring? -------
    h6 = {}
    for q in (700, 1100, 1500, 1900, 2100):
        for tag in ("maxband", "uncoord"):
            per = []
            for s in (1, 2, 3, 4):
                d = os.path.join(B.WORK, "h6", "L300_q%d_%s_s%d" % (q, tag, s))
                r = redo({"x": d})["x"]
                if r:
                    per.append(r)
            h6[(q, tag)] = per
    out6 = []
    for q in (700, 1100, 1500, 1900, 2100):
        a, b = h6[(q, "maxband")], h6[(q, "uncoord")]
        if not a or not b or len(a) != len(b):
            continue
        row = dict(L=300, thru=q, n_rep=len(a))
        for w in ("600-3000", "600-2400", "600-2100"):
            for coh, key, lab in (("thruE", "timeLoss", "dTLthruE"),
                                  ("all", "timeLoss", "dTLall")):
                d = paired_benefit(a, b, key, coh, w)
                row["%s_%s" % (lab, w)] = round(d["mean"], 3)
                row["%s_%s_hw" % (lab, w)] = round(d["hw"], 3)
                row["%s_%s_p" % (lab, w)] = round(d["p"], 5)
        row["completed_maxband"] = round(
            a[0]["summary"]["arrived"] / a[0]["summary"]["inserted"], 4)
        row["completed_uncoord"] = round(
            b[0]["summary"]["arrived"] / b[0]["summary"]["inserted"], 4)
        row["teleports_maxband"] = sum(r["n_teleport"] for r in a)
        row["teleports_uncoord"] = sum(r["n_teleport"] for r in b)
        out6.append(row)
    A.write_csv(os.path.join(B.DATA, "robustness_h6_window.csv"), out6)
    rep["h6"] = out6

    # ---- reconciliation cases ---------------------------------------------
    cases = ["best_resonant_coord", "best_resonant_uncoord",
             "worst_detuned_coord", "worst_detuned_uncoord",
             "base_oneway_sumopt", "base_twoway_maxband"]
    outR = []
    for c in cases:
        per = []
        for s in B.SEEDS:
            d = os.path.join(B.WORK, "recon", "%s_s%d" % (c, s))
            r = redo({"x": d})["x"]
            if r:
                per.append(r)
        if not per:
            continue
        row = dict(case=c, n_rep=len(per))
        for w in ("600-3000", "600-2400"):
            for coh in ("thruE", "thruW", "all"):
                m, hw, sd, n = A.tconf([p[w][coh]["timeLoss"] for p in per])
                row["tl_%s_%s" % (coh, w)] = round(m, 3)
                row["tl_%s_%s_hw" % (coh, w)] = round(hw, 3)
                m2, hw2, _, _ = A.tconf([p[w][coh]["zero_stop"] for p in per])
                row["zerostop_%s_%s" % (coh, w)] = round(m2, 4)
        row["completed_share"] = round(
            per[0]["summary"]["arrived"] / per[0]["summary"]["inserted"], 4)
        row["still_running_at_end"] = per[0]["summary"].get("running")
        row["teleports_total"] = sum(p["n_teleport"] for p in per)
        outR.append(row)
    A.write_csv(os.path.join(B.DATA, "robustness_reconciliation_window.csv"), outR)
    rep["reconciliation"] = outR

    json.dump(rep, open(os.path.join(B.DATA, "robustness.json"), "w"), indent=1)
    print("=== H6 L=300: coordination benefit (uncoord - coord), s/veh ===")
    for r in out6:
        print("q=%4d  thruE: full %+7.2f+/-%5.2f (p=%.4g) | uncensored "
              "%+7.2f+/-%5.2f (p=%.4g)   ALL: full %+6.2f | uncensored %+6.2f "
              "| completed %.3f/%.3f tele %d/%d"
              % (r["thru"], r["dTLthruE_600-3000"], r["dTLthruE_600-3000_hw"],
                 r["dTLthruE_600-3000_p"], r["dTLthruE_600-2400"],
                 r["dTLthruE_600-2400_hw"], r["dTLthruE_600-2400_p"],
                 r["dTLall_600-3000"], r["dTLall_600-2400"],
                 r["completed_maxband"], r["completed_uncoord"],
                 r["teleports_maxband"], r["teleports_uncoord"]))
    print("\n=== reconciliation cases: censored vs uncensored window ===")
    for r in outR:
        print("%-24s thruE tl %.2f -> %.2f | zero-stop(all-trip) %.3f -> %.3f "
              "| completed %.4f still_running %s tele %d"
              % (r["case"], r["tl_thruE_600-3000"], r["tl_thruE_600-2400"],
                 r["zerostop_thruE_600-3000"], r["zerostop_thruE_600-2400"],
                 r["completed_share"], r["still_running_at_end"],
                 r["teleports_total"]))


if __name__ == "__main__":
    main()
