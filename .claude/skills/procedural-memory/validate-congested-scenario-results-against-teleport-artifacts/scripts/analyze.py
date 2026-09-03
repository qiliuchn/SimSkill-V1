#!/usr/bin/env python3
"""Compact the sweep cells into per-cell and aggregated CSVs + a readable report."""
import argparse
import csv
import json
import math
import os
from collections import defaultdict

TTT_ORDER = ["-1", "30", "60", "120", "300", "600", "900"]

CELL_COLS = ["level", "netarm", "ttt", "seed", "loaded", "inserted", "completed",
             "teleports_cum", "teleport_vehicles", "teleports_per_completed",
             "tele_affected_share_of_completed", "clearance_time",
             "peak_running", "end_running", "end_waiting", "mean_net_speed",
             "all_mean_duration", "all_mean_timeloss", "all_mean_waiting",
             "free_n", "free_mean_duration", "free_mean_timeloss",
             "aff_n", "aff_mean_duration", "aff_mean_timeloss", "wall_s"]

AGG_METRICS = ["completed", "teleports_cum", "teleport_vehicles",
               "teleports_per_completed", "tele_affected_share_of_completed",
               "clearance_time", "peak_running", "end_running", "end_waiting",
               "mean_net_speed", "all_mean_duration", "all_mean_timeloss",
               "free_n", "free_mean_duration", "free_mean_timeloss",
               "aff_mean_duration"]


def mean(xs):
    xs = [x for x in xs if x is not None and not (isinstance(x, float) and math.isnan(x))]
    return sum(xs) / len(xs) if xs else None


def sd(xs):
    xs = [x for x in xs if x is not None and not (isinstance(x, float) and math.isnan(x))]
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


T975 = {2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776, 6: 2.571, 7: 2.447, 8: 2.365,
        9: 2.306, 10: 2.262}


def ci95(xs):
    xs = [x for x in xs if x is not None and not (isinstance(x, float) and math.isnan(x))]
    n = len(xs)
    if n < 2:
        return None
    s = sd(xs)
    return T975.get(n - 1, 1.96) * s / math.sqrt(n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)
    res = json.load(open(args.results))

    # ---- per-cell CSV ----
    with open(os.path.join(args.outdir, "cells_raw.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CELL_COLS, extrasaction="ignore")
        w.writeheader()
        for r in sorted(res, key=lambda r: (r["level"], r["netarm"],
                                            TTT_ORDER.index(str(r["ttt"])), r["seed"])):
            w.writerow(r)

    # ---- aggregate over seeds ----
    groups = defaultdict(list)
    for r in res:
        groups[(r["level"], r["netarm"], str(r["ttt"]))].append(r)

    rows = []
    for (level, arm, ttt), g in groups.items():
        row = {"level": level, "netarm": arm, "ttt": ttt, "n_seeds": len(g),
               "n_seeds_cleared": sum(1 for r in g if r["clearance_time"] is not None)}
        for m in AGG_METRICS:
            vals = [r[m] for r in g]
            mu = mean(vals)
            row[m + "_mean"] = round(mu, 4) if mu is not None else ""
            c = ci95(vals)
            row[m + "_ci95"] = round(c, 4) if c is not None else ""
        rows.append(row)
    rows.sort(key=lambda r: (r["level"], r["netarm"], TTT_ORDER.index(r["ttt"])))
    cols = ["level", "netarm", "ttt", "n_seeds", "n_seeds_cleared"] + \
           [m + s for m in AGG_METRICS for s in ("_mean", "_ci95")]
    with open(os.path.join(args.outdir, "cells_agg.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    # ---- readable report ----
    out = []
    P = out.append
    for level in ["LOW", "OS-A", "OS-B"]:
        P("\n" + "=" * 108)
        P("LEVEL %s  --  teleport sweep (keep-clear ON network), 5 seeds, CRN "
          "(identical routes+sumo seed across ttt arms)" % level)
        P("=" * 108)
        P("%-6s %8s %8s %8s %9s %9s %9s %10s %10s %10s %8s" %
          ("ttt", "compl", "teleCum", "teleVeh", "tel/comp", "affShare",
           "clrTime", "allDur", "freeDur", "affDur", "netSpd"))
        for ttt in TTT_ORDER:
            g = groups.get((level, "kc_on", ttt))
            if not g:
                continue
            def m(k):
                v = mean([r[k] for r in g])
                return "-" if v is None else v
            def f(k, p=1):
                v = m(k)
                return ("%.*f" % (p, v)) if v != "-" else "-"
            ncl = sum(1 for r in g if r["clearance_time"] is not None)
            P("%-6s %8.1f %8.1f %8.1f %9.3f %9.3f %9s %10s %10s %10s %8.2f" %
              (ttt, m("completed"), m("teleports_cum"), m("teleport_vehicles"),
               m("teleports_per_completed") or 0, m("tele_affected_share_of_completed") or 0,
               (f("clearance_time", 0) + "(%d/5)" % ncl) if ncl else "never(0/5)",
               f("all_mean_duration"), f("free_mean_duration"), f("aff_mean_duration"),
               m("mean_net_speed")))

        # per-seed directional agreement vs ttt=300 (default)
        P("")
        P("per-seed direction of effect vs. ttt=300 baseline (same seed, CRN):")
        base = {r["seed"]: r for r in groups.get((level, "kc_on", "300"), [])}
        for ttt in TTT_ORDER:
            if ttt == "300":
                continue
            g = groups.get((level, "kc_on", ttt))
            if not g:
                continue
            parts = []
            for k, lab in [("completed", "compl"), ("all_mean_duration", "allDur"),
                           ("free_mean_duration", "freeDur"), ("mean_net_speed", "spd")]:
                up = dn = eq = 0
                for r in g:
                    b = base.get(r["seed"])
                    if b is None or r[k] is None or b[k] is None:
                        continue
                    if r[k] > b[k] * 1.0001:
                        up += 1
                    elif r[k] < b[k] * 0.9999:
                        dn += 1
                    else:
                        eq += 1
                parts.append("%s +%d/-%d/=%d" % (lab, up, dn, eq))
            P("  ttt=%-4s  %s" % (ttt, "   ".join(parts)))

    # ---- keep-clear comparison ----
    P("\n" + "=" * 108)
    P("KEEP-CLEAR comparison: kc_on (SUMO default, junction box kept clear) vs "
      "kc_off (blocking permitted)")
    P("=" * 108)
    P("%-6s %-5s %-7s %8s %8s %9s %10s %10s %9s %8s" %
      ("level", "ttt", "arm", "compl", "teleCum", "clr(n/5)", "allDur", "freeDur",
       "endRun", "netSpd"))
    for level in ["LOW", "OS-A", "OS-B"]:
        for ttt in ["300", "-1"]:
            for arm in ["kc_on", "kc_off"]:
                g = groups.get((level, arm, ttt))
                if not g:
                    continue
                def m(k):
                    v = mean([r[k] for r in g])
                    return v
                ncl = sum(1 for r in g if r["clearance_time"] is not None)
                ct = m("clearance_time")
                P("%-6s %-5s %-7s %8.1f %8.1f %9s %10s %10s %9.1f %8.2f" %
                  (level, ttt, arm, m("completed"), m("teleports_cum"),
                   ("%.0f(%d/5)" % (ct, ncl)) if ct else "never(0/5)",
                   "%.1f" % m("all_mean_duration") if m("all_mean_duration") else "-",
                   "%.1f" % m("free_mean_duration") if m("free_mean_duration") else "-",
                   m("end_running"), m("mean_net_speed")))
            # per-seed direction
            gon = {r["seed"]: r for r in groups.get((level, "kc_on", ttt), [])}
            gof = {r["seed"]: r for r in groups.get((level, "kc_off", ttt), [])}
            if gon and gof:
                parts = []
                for k, lab in [("completed", "compl"), ("all_mean_duration", "allDur"),
                               ("mean_net_speed", "spd"), ("teleports_cum", "tele")]:
                    up = dn = eq = 0
                    for s in gon:
                        a, b = gof.get(s), gon.get(s)
                        if a is None or a[k] is None or b[k] is None:
                            continue
                        if a[k] > b[k]:
                            up += 1
                        elif a[k] < b[k]:
                            dn += 1
                        else:
                            eq += 1
                    parts.append("%s kcoff-higher:%d lower:%d tie:%d" % (lab, up, dn, eq))
                P("       per-seed (kc_off vs kc_on): " + " | ".join(parts))
    txt = "\n".join(out)
    print(txt)
    with open(os.path.join(args.outdir, "sweep_report.txt"), "w") as fh:
        fh.write(txt + "\n")


if __name__ == "__main__":
    main()
