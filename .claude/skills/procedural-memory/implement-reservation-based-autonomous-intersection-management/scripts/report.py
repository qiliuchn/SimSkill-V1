#!/usr/bin/env python3
"""Aggregate every stage of the AIM study into results.json + markdown tables."""
import json
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from analyze import run_metrics, mean_ci, paired          # noqa: E402
from ssm_analyze import analyze as ssm_analyze            # noqa: E402

DEMANDS = [300, 600, 900, 1200, 1500]
SEEDS = [101, 102, 103, 104, 105]
S3 = [101, 102, 103]
PEN = [0.0, 0.05, 0.10, 0.25, 0.50, 1.00]
BUF = [0.2, 0.6, 1.5, 3.0, 5.0, 8.0]
LAT = [0.0, 0.2, 0.4, 0.6, 1.0, 1.5, 2.0, 3.0]
NOI = [0.0, 1.0, 2.5, 5.0, 8.0, 12.0, 20.0]
CTRL = ["fixed", "actuated", "maxpressure", "aimfcfs", "aimbatch", "awsc"]


def M(p, meta=None):
    return run_metrics(os.path.join(BASE, p), meta)


def loadmeta(p):
    fp = os.path.join(BASE, p)
    return json.load(open(fp)) if os.path.exists(fp) else None


def collect(pattern, seeds, meta=None):
    out = []
    for s in seeds:
        m = M(pattern % s, meta)
        if m:
            out.append(m)
    return out


def agg(ms, key="mean_delay"):
    v = [m[key] for m in ms]
    mu, h, ci = mean_ci(v)
    return {"mean": mu, "hw": h, "ci": ci, "n": len(v), "values": v}


def safety(ms):
    return {"collisions_total": sum(m.get("collisions") or 0 for m in ms),
            "collisions_junction": sum(m.get("collisions_junction") or 0 for m in ms),
            "teleports_total": sum(m.get("teleports_summary") or 0 for m in ms),
            "teleports_jam": sum(m.get("teleports_jam") or 0 for m in ms),
            "still_running": sum(m.get("still_running") or 0 for m in ms),
            "never_inserted": sum(m.get("never_inserted") or 0 for m in ms),
            "loaded": sum(m.get("loaded") or 0 for m in ms),
            "arrived": sum(m["arrived"] for m in ms)}


def main():
    R = {}

    # ---- saturation / webster --------------------------------------------
    sat = {}
    p = os.path.join(BASE, "runs/satflow/saturation.txt")
    if os.path.exists(p):
        sat = dict(l.strip().split("=") for l in open(p) if "=" in l)
    R["saturation"] = sat
    bp = json.load(open(os.path.join(BASE, "net/plans/best.json")))
    R["best_fixed_plan"] = bp
    swp = os.path.join(BASE, "runs/s0/sweep_table.json")
    R["cycle_sweep"] = json.load(open(swp)) if os.path.exists(swp) else {}

    # ---- s1 main comparison ----------------------------------------------
    s1 = {}
    for d in DEMANDS:
        meta = loadmeta("demand/d%d_s101.rou.meta.json" % d)
        row = {}
        for c in CTRL:
            ms = collect("runs/s1/" + c + "_d%d_s%%d" % d, SEEDS, meta)
            if not ms:
                continue
            row[c] = {"delay": agg(ms), "throughput": agg(ms, "arrived"),
                      "timeloss": agg(ms, "mean_timeloss"),
                      "p95": agg(ms, "p95_delay"),
                      "safety": safety(ms),
                      "by_arm": ms[0]["by_arm"]}
        # CRN paired comparisons vs actuated
        pair = {}
        if "actuated" in row:
            a = row["actuated"]["delay"]["values"]
            for c in row:
                if c == "actuated":
                    continue
                pair[c] = paired(a, row[c]["delay"]["values"])
        s1[d] = {"controllers": row, "paired_vs_actuated": pair}
    R["s1"] = s1

    # ---- s2 buffer negative control ---------------------------------------
    s2 = {}
    for d in (300, 900):
        row = {}
        for b in BUF:
            ms = collect("runs/s2/buf%.1f_d%d_s%%d" % (b, d), S3)
            if ms:
                row["%.1f" % b] = {"delay": agg(ms), "safety": safety(ms),
                                   "throughput": agg(ms, "arrived")}
        awsc = collect("runs/s1/awsc_d%d_s%%d" % d, SEEDS)
        row["AWSC_reference"] = {"delay": agg(awsc)} if awsc else None
        s2[d] = row
    R["s2"] = s2

    # ---- s3 penetration ----------------------------------------------------
    s3 = {}
    for d in (600, 1200):
        row = {}
        for pn in PEN:
            ms = collect("runs/s3/pen%.2f_d%d_s%%d" % (pn, d), SEEDS)
            if ms:
                r = {"delay": agg(ms), "safety": safety(ms),
                     "throughput": agg(ms, "arrived")}
                r["by_class"] = ms[0].get("by_class", {})
                r["by_class_n"] = ms[0].get("by_class_n", {})
                row["%.2f" % pn] = r
        act = collect("runs/s1/actuated_d%d_s%%d" % d, SEEDS)
        row["actuated_reference"] = {"delay": agg(act)} if act else None
        # paired AIM(p) vs actuated
        if act:
            av = [m["mean_delay"] for m in act]
            for k in list(row):
                if k.startswith("actuated"):
                    continue
                ms = collect("runs/s3/pen%s_d%d_s%%d" % (k, d), SEEDS)
                if len(ms) == len(av):
                    row[k]["paired_vs_actuated"] = paired(av, [m["mean_delay"] for m in ms])
        s3[d] = row
    R["s3"] = s3

    # ---- s4 unbalanced demand: FCFS vs batch ------------------------------
    s4 = {}
    for d in DEMANDS:
        meta = loadmeta("demand/d%d_s101_ub.rou.meta.json" % d)
        row = {}
        for c in ("aimfcfs", "aimbatch", "actuated"):
            ms = collect("runs/s4/" + c + "_d%d_s%%d" % d, S3, meta)
            if not ms:
                continue
            major = [st.mean([m["by_arm"][a] for a in ("N", "S") if a in m["by_arm"]]) for m in ms]
            minor = [st.mean([m["by_arm"][a] for a in ("E", "W") if a in m["by_arm"]]) for m in ms]
            row[c] = {"delay": agg(ms), "gini": agg(ms, "gini_delay"),
                      "arm_ratio": agg(ms, "arm_delay_ratio"),
                      "p95": agg(ms, "p95_delay"),
                      "major_delay": mean_ci(major)[0], "minor_delay": mean_ci(minor)[0],
                      "minor_over_major": st.mean([mi / max(ma, 1e-6)
                                                   for mi, ma in zip(minor, major)]),
                      "safety": safety(ms), "throughput": agg(ms, "arrived")}
        if "aimfcfs" in row and "aimbatch" in row:
            row["paired_batch_vs_fcfs_delay"] = paired(row["aimfcfs"]["delay"]["values"],
                                                       row["aimbatch"]["delay"]["values"])
            row["paired_batch_vs_fcfs_gini"] = paired(row["aimfcfs"]["gini"]["values"],
                                                      row["aimbatch"]["gini"]["values"])
        s4[d] = row
    R["s4"] = s4

    # ---- s5 SSM ------------------------------------------------------------
    s5 = {}
    for d in (600, 1200):
        meta = loadmeta("demand/d%d_s101_ssm.rou.meta.json" % d)
        row = {}
        for c in ("fixed", "actuated", "aimfcfs", "aimbatch"):
            agg_ssm, delays = [], []
            for s in S3:
                dd = os.path.join(BASE, "runs/s5/%s_d%d_s%d" % (c, d, s))
                mm = loadmeta("demand/d%d_s%d_ssm.rou.meta.json" % (d, s)) or {}
                a = ssm_analyze(os.path.join(dd, "ssm.xml"), mm)
                if a:
                    agg_ssm.append(a)
                m = run_metrics(dd, mm)
                if m:
                    delays.append(m)
            if not agg_ssm:
                continue
            keys = ["n_conflicts", "following", "merging", "crossing", "flag111",
                    "flag111_opposing_left_artifact", "flag111_other",
                    "ttc_lt_1_5", "ttc_lt_1_0", "crossing_ttc_lt_1_5", "pet_lt_1_0"]
            row[c] = {k: st.mean([a[k] for a in agg_ssm]) for k in keys}
            row[c]["min_ttc"] = min([a["min_ttc"] for a in agg_ssm if a["min_ttc"] is not None]
                                    or [None])
            row[c]["ttc_p05"] = st.mean([a["ttc_p05"] for a in agg_ssm if "ttc_p05" in a] or [0])
            row[c]["ttc_median"] = st.mean([a["ttc_median"] for a in agg_ssm
                                            if "ttc_median" in a] or [0])
            row[c]["max_drac"] = max([a["max_drac"] for a in agg_ssm
                                      if a["max_drac"] is not None] or [0])
            row[c]["pairs111"] = agg_ssm[0]["pairs111"]
            row[c]["artifact_examples"] = agg_ssm[0]["artifact_examples"]
            if delays:
                row[c]["delay"] = agg(delays)
                row[c]["safety"] = safety(delays)
        s5[d] = row
    R["s5"] = s5

    # ---- s6 communication realism -----------------------------------------
    s6 = {"latency": {}, "noise": {}}
    for lat in LAT:
        ms = collect("runs/s6/lat%.1f_d900_s%%d" % lat, S3)
        if ms:
            s6["latency"]["%.1f" % lat] = {"delay": agg(ms), "safety": safety(ms),
                                           "throughput": agg(ms, "arrived")}
    for nz in NOI:
        ms = collect("runs/s6/noise%.1f_d900_s%%d" % nz, S3)
        if ms:
            s6["noise"]["%.1f" % nz] = {"delay": agg(ms), "safety": safety(ms),
                                        "throughput": agg(ms, "arrived")}
    R["s6"] = s6

    # ---- verification runs -------------------------------------------------
    ver = {}
    for n in ("unsafe_d400", "unsafe_d900"):
        m = M("runs/verify/" + n)
        if m:
            ver[n] = {"collisions": m.get("collisions"),
                      "collisions_junction": m.get("collisions_junction"),
                      "arrived": m["arrived"], "delay": m["mean_delay"]}
    R["verify"] = ver

    json.dump(R, open(os.path.join(BASE, "analysis/results.json"), "w"),
              indent=1, default=str)
    print("wrote analysis/results.json")

    # ---- console tables ----------------------------------------------------
    print("\n== S1 mean delay (timeLoss+departDelay), s, mean +/- 95%% CI over %d CRN seeds ==" % len(SEEDS))
    hdr = "%-8s" % "demand" + "".join("%-22s" % c for c in CTRL)
    print(hdr)
    for d in DEMANDS:
        line = "%-8d" % d
        for c in CTRL:
            r = s1[d]["controllers"].get(c)
            line += "%-22s" % ("%.1f +/- %.1f" % (r["delay"]["mean"], r["delay"]["hw"])
                               if r else "-")
        print(line)
    print("\n== S1 paired CRN diff vs ACTUATED (negative = AIM better) ==")
    for d in DEMANDS:
        for c, pr in s1[d]["paired_vs_actuated"].items():
            print("  d=%4d %-12s %+8.1f s (%.0f%%) CI[%+.1f,%+.1f] sig=%s signAgree=%.0f%%"
                  % (d, c, pr["mean_diff"], pr["pct"], pr["ci"][0], pr["ci"][1],
                     pr["sig"], 100 * pr["sign_agree"]))
    print("\n== S1 safety / validity ==")
    for d in DEMANDS:
        for c in CTRL:
            r = s1[d]["controllers"].get(c)
            if r:
                s = r["safety"]
                print("  d=%4d %-12s coll=%d (junction %d) tele=%d(jam %d) loaded=%d arrived=%d "
                      "stillRunning=%d neverInserted=%d"
                      % (d, c, s["collisions_total"], s["collisions_junction"],
                         s["teleports_total"], s["teleports_jam"], s["loaded"],
                         s["arrived"], s["still_running"], s["never_inserted"]))


if __name__ == "__main__":
    main()
