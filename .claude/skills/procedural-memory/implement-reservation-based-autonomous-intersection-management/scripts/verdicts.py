#!/usr/bin/env python3
"""Compact console digest of analysis/results.json: the numbers each hypothesis
verdict in FINDINGS.md is written from."""
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R = json.load(open(os.path.join(BASE, "analysis/results.json")))
D = ["300", "600", "900", "1200", "1500"]


def g(x, k="mean"):
    return x[k] if x else float("nan")


print("=== S1 mean delay (s) ===")
CT = ["fixed", "actuated", "maxpressure", "aimfcfs", "aimbatch", "awsc"]
print("%-6s" % "dem" + "".join("%-16s" % c for c in CT))
for d in D:
    r = R["s1"][d]["controllers"]
    print("%-6s" % d + "".join(
        "%-16s" % (("%.1f±%.1f" % (r[c]["delay"]["mean"], r[c]["delay"]["hw"]))
                   if c in r else "-") for c in CT))

print("\n=== S1 safety/validity (summed over 5 seeds) ===")
for d in D:
    for c in CT:
        r = R["s1"][d]["controllers"].get(c)
        if r:
            s = r["safety"]
            print("  d=%-5s %-12s coll=%-3d tele=%-4d jam=%-3d still=%-4d loaded=%-5d arrived=%d"
                  % (d, c, s["collisions_total"], s["teleports_total"],
                     s["teleports_jam"], s["still_running"], s["loaded"], s["arrived"]))

print("\n=== H1: paired CRN diff vs actuated (negative = AIM better) ===")
for d in D:
    for c, p in R["s1"][d]["paired_vs_actuated"].items():
        if c.startswith("aim"):
            print("  d=%-5s %-10s %+8.1f s (%+6.1f%%) CI[%+.1f,%+.1f] sig=%s"
                  % (d, c, p["mean_diff"], p["pct"], p["ci"][0], p["ci"][1], p["sig"]))

print("\n=== negative control: safety-buffer sweep (AIM-batch) ===")
for d, row in R["s2"].items():
    print(" demand", d)
    for k in sorted([x for x in row if x != "AWSC_reference"], key=float):
        v = row[k]
        print("   buf=%-5s delay=%7.1f ± %.1f  arrived=%.0f coll=%d"
              % (k, v["delay"]["mean"], v["delay"]["hw"],
                 v["throughput"]["mean"], v["safety"]["collisions_total"]))
    ref = row.get("AWSC_reference")
    if ref:
        print("   AWSC reference delay=%.1f" % ref["delay"]["mean"])

print("\n=== H2: penetration sweep ===")
for d, row in R["s3"].items():
    ref = row.get("actuated_reference")
    print(" demand", d, "actuated ref delay=%.1f" % (ref["delay"]["mean"] if ref else -1))
    for k in sorted([x for x in row if x.replace(".", "").isdigit()], key=float):
        v = row[k]
        p = v.get("paired_vs_actuated")
        s = v["safety"]
        print("   pen=%-5s delay=%8.1f ± %6.1f arrived=%6.1f coll=%d tele=%d jam=%d still=%d %s"
              % (k, v["delay"]["mean"], v["delay"]["hw"], v["throughput"]["mean"],
                 s["collisions_total"], s["teleports_total"], s["teleports_jam"],
                 s["still_running"],
                 ("paired %+.1f s sig=%s" % (p["mean_diff"], p["sig"])) if p else ""))
        print("        by class:", {kk: round(vv, 1) for kk, vv in (v.get("by_class") or {}).items()},
              (v.get("by_class_n") or {}))

print("\n=== H3: unbalanced 80/20, FCFS vs batch ===")
for d in D:
    row = R["s4"].get(d) or {}
    if not row:
        continue
    print(" demand", d)
    for c in ("aimfcfs", "aimbatch", "actuated"):
        if c in row:
            v = row[c]
            print("   %-10s delay=%8.1f gini=%.3f armRatio=%.2f major=%.1f minor=%.1f "
                  "minor/major=%.2f p95=%.1f coll=%d still=%d"
                  % (c, v["delay"]["mean"], v["gini"]["mean"], v["arm_ratio"]["mean"],
                     v["major_delay"], v["minor_delay"], v["minor_over_major"],
                     v["p95"]["mean"], v["safety"]["collisions_total"],
                     v["safety"]["still_running"]))
    for k in ("paired_batch_vs_fcfs_delay", "paired_batch_vs_fcfs_gini"):
        if k in row:
            p = row[k]
            print("   %-28s %+8.3f CI[%+.3f,%+.3f] sig=%s"
                  % (k, p["mean_diff"], p["ci"][0], p["ci"][1], p["sig"]))

print("\n=== H4: SSM ===")
for d, row in R["s5"].items():
    print(" demand", d)
    for c, v in row.items():
        print("   %-10s delay=%7.1f conflicts=%7.1f cross=%6.1f ttc<1.5=%6.1f "
              "crossTtc<1.5=%5.1f ttc<1.0=%5.1f pet<1.0=%5.1f minTTC=%s maxDRAC=%.2f "
              "f111=%.1f (artifact %.1f / other %.1f)"
              % (c, v.get("delay", {}).get("mean", float("nan")), v["n_conflicts"],
                 v["crossing"], v["ttc_lt_1_5"], v["crossing_ttc_lt_1_5"],
                 v["ttc_lt_1_0"], v["pet_lt_1_0"], v["min_ttc"], v["max_drac"],
                 v["flag111"], v["flag111_opposing_left_artifact"], v["flag111_other"]))

print("\n=== communication realism ===")
for kind in ("latency", "noise"):
    print(" ", kind)
    for k in sorted(R["s6"][kind], key=float):
        v = R["s6"][kind][k]
        s = v["safety"]
        print("   %-6s delay=%8.1f ± %6.1f arrived=%6.1f COLL=%-3d tele=%-3d jam=%d still=%d"
              % (k, v["delay"]["mean"], v["delay"]["hw"], v["throughput"]["mean"],
                 s["collisions_total"], s["teleports_total"], s["teleports_jam"],
                 s["still_running"]))

print("\n=== interlock negative control ===")
print(json.dumps(R["verify"], indent=1))
print("\n=== saturation / best plans ===")
print(R["saturation"], R["best_fixed_plan"])
