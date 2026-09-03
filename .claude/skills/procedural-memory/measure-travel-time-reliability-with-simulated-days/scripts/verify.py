#!/usr/bin/env python3
"""
Independent verification of the things a reviewer should not have to take on
trust.  Writes outputs/verification_report.txt.

  V1  the day-draw generator really produces the claimed distributions
  V2  Common Random Numbers really hold (FULL == DEMAND on no-incident days)
  V3  the closingLaneReroute incident does NOT contaminate the un-equipped
      arms (no route repair without the rerouting device)
  V4  the equipped/unequipped partition in C_info is real, checked against
      tripinfo's own `devices` attribute, not against the vType tag
  V5  route classification from vehroute-output uses the LAST route of the
      routeDistribution, and the size of the first-route misclassification
  V6  teleport accounting: summary's cumulative attribute vs the warning log
  V7  the incident closure actually bites (edgeData speed on the closed edge)
"""
import glob
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

import numpy as np
from scipy import stats

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "work")
OUT = os.path.abspath(os.path.join(ROOT, "..", "..", "outputs"))
SC = ["A_base", "B_capacity", "C_info", "D_shoulder"]
L = []


def say(s=""):
    print(s)
    L.append(str(s))


def npz(b, s, t):
    return np.load(os.path.join(WORK, "runs", b, s, t, "corr_tt.npz"),
                   allow_pickle=True)


def main():
    days = json.load(open(os.path.join(WORK, "days.json")))
    n = len(days)
    mult = np.array([d["mult"] for d in days])
    inc = np.array([d["incident"] for d in days], bool)

    say("=" * 74)
    say("V1  DAY-DRAW GENERATOR -- realised vs target distributions")
    say("=" * 74)
    cv = 0.20
    sig = np.sqrt(np.log(1 + cv ** 2))
    mu = -sig ** 2 / 2
    ks = stats.kstest(np.log(mult), stats.norm(mu, sig).cdf)
    say(f"  demand multiplier: target lognormal E=1.000 CV={cv:.3f} "
        f"(mu_log={mu:+.5f}, sigma_log={sig:.5f})")
    say(f"    realised  E={mult.mean():.4f}  CV="
        f"{mult.std(ddof=1)/mult.mean():.4f}  "
        f"mean_log={np.log(mult).mean():+.5f}  "
        f"sd_log={np.log(mult).std(ddof=1):.5f}")
    say(f"    KS test of log(m) vs N(mu_log, sigma_log): D={ks.statistic:.4f} "
        f"p={ks.pvalue:.3f}  -> {'consistent' if ks.pvalue > .05 else 'REJECT'}")
    k = int(inc.sum())
    bt = stats.binomtest(k, n, 0.25)
    say(f"  incident indicator: target Bernoulli(0.25); realised {k}/{n} = "
        f"{k/n:.4f}")
    say(f"    exact binomial test p={bt.pvalue:.3f}, 95% CI "
        f"[{bt.proportion_ci().low:.4f}, {bt.proportion_ci().high:.4f}]")
    st = np.array([d["inc_start"] for d in days if d["incident"]])
    du = np.array([d["inc_dur"] for d in days if d["incident"]])
    k1 = stats.kstest((st - 600) / 2100, stats.uniform().cdf)
    k2 = stats.kstest((du - 600) / 1200, stats.uniform().cdf)
    say(f"  incident start  ~ U(600,2700): realised min={st.min():.0f} "
        f"max={st.max():.0f} mean={st.mean():.0f}  KS p={k1.pvalue:.3f}")
    say(f"  incident duration ~ U(600,1800): realised min={du.min():.0f} "
        f"max={du.max():.0f} mean={du.mean():.0f}  KS p={k2.pvalue:.3f}")
    l1 = sum(1 for d in days if d["inc_lanes"] == 1)
    l2 = sum(1 for d in days if d["inc_lanes"] == 2)
    c1 = stats.chisquare([l1, l2], [0.6 * k, 0.4 * k])
    e1 = sum(1 for d in days if d["inc_edge"] == "CB1")
    e2 = sum(1 for d in days if d["inc_edge"] == "CB2")
    c2 = stats.chisquare([e1, e2], [0.5 * k, 0.5 * k])
    say(f"  lanes closed {{1:0.6, 2:0.4}}: realised {l1}/{l2}  "
        f"chi2 p={c1.pvalue:.3f}")
    say(f"  location {{CB1,CB2}} uniform: realised {e1}/{e2}  "
        f"chi2 p={c2.pvalue:.3f}")
    allint = all(float(d["inc_start"]).is_integer()
                 and float(d["inc_start"] + d["inc_dur"]).is_integer()
                 for d in days if d["incident"])
    say(f"  all incident begin/end times are integer seconds: {allint}   "
        "(REQUIRED: SUMO 1.27.1 silently no-ops a rerouter interval with a "
        "fractional begin, and never lifts one with a fractional end)")

    say()
    say("=" * 74)
    say("V2  COMMON RANDOM NUMBERS -- FULL vs DEMAND on no-incident days")
    say("=" * 74)
    worst = 0.0
    nchk = 0
    for s in SC:
        for i, d in enumerate(days):
            if d["incident"]:
                continue
            a = npz("FULL", s, "day%03d" % i)
            b = npz("DEMAND", s, "day%03d" % i)
            if len(a["dur"]) != len(b["dur"]):
                worst = np.inf
                continue
            worst = max(worst, float(np.abs(a["dur"] - b["dur"]).max()))
            nchk += 1
    say(f"  {nchk} (scenario, no-incident day) pairs checked; max per-vehicle "
        f"travel-time difference = {worst:.6f} s")
    say("  -> the incident is the ONLY thing that differs between the FULL "
        "and DEMAND blocks" if worst == 0 else "  -> MISMATCH")

    say()
    say("=" * 74)
    say("V3  BASELINE NON-CONTAMINATION -- lane closure must not reroute "
        "un-equipped vehicles")
    say("=" * 74)
    import csv
    cells = {}
    for r in csv.DictReader(open(os.path.join(WORK, "cells.csv"))):
        cells[(r["block"], r["scenario"], int(r["day"]))] = r
    for s in SC:
        diffs = []
        for i, d in enumerate(days):
            if not d["incident"]:
                continue
            a = float(cells[("FULL", s, i)]["ap_entered"])
            b = float(cells[("DEMAND", s, i)]["ap_entered"])
            diffs.append(a - b)
        diffs = np.array(diffs)
        eq = float(cells[("FULL", s, 0)]["equip"])
        say(f"  {s:<12} equip={eq:.2f}  detour entries on incident days, "
            f"FULL - DEMAND: mean={diffs.mean():+8.2f}  "
            f"max|.|={np.abs(diffs).max():8.2f}")
    say("  Un-equipped arms (equip=0) must show ~0 change: a lane DROP keeps "
        "every static route valid, so SUMO performs no silent route repair.")

    say()
    say("=" * 74)
    say("V4  EQUIPPED PARTITION -- from tripinfo's own `devices` attribute")
    say("=" * 74)
    for s in SC:
        tot = eqn = 0
        for i in range(min(30, len(days))):
            dv = npz("FULL", s, "day%03d" % i)["devices"]
            tot += len(dv)
            # the rerouting device appears in tripinfo as "routing_<vehid>"
            eqn += sum(1 for x in dv if "routing_" in str(x))
        say(f"  {s:<12} target equip={float(cells[('FULL', s, 0)]['equip']):.2f}"
            f"  realised={eqn/tot:.4f}  (n={tot} corridor vehicles, "
            "first 30 days)")

    say()
    say("=" * 74)
    say("V5  ROUTE CLASSIFICATION -- last vs first route of routeDistribution")
    say("=" * 74)
    for s in SC:
        for i in range(3):
            p = os.path.join(WORK, "runs", "FULL", s, "day%03d" % i,
                             "vehroutes.xml")
            if not os.path.exists(p):
                continue
            first_alt = last_alt = mis = tot = 0
            for _, el in ET.iterparse(p, events=("end",)):
                if el.tag != "vehicle" or not el.get("id", "").startswith(
                        "corr"):
                    if el.tag == "vehicle":
                        el.clear()
                    continue
                tot += 1
                rd = el.find("routeDistribution")
                if rd is not None:
                    rs = rd.findall("route")
                    f_ = "AP" in rs[0].get("edges").split()
                    l_ = "AP" in rs[-1].get("edges").split()
                else:
                    r = el.find("route")
                    f_ = l_ = "AP" in r.get("edges").split()
                first_alt += f_
                last_alt += l_
                mis += (f_ != l_)
                el.clear()
            ed = float(cells[("FULL", s, i)]["ap_entered"])
            say(f"  {s:<12} day{i}  corridor veh={tot:5d}  detour by LAST "
                f"route={last_alt:5d}  by FIRST route={first_alt:5d}  "
                f"misclassified={mis:5d}  edgeData AP entered={ed:.0f}")

    say()
    say("=" * 74)
    say("V6  TELEPORT ACCOUNTING -- summary cumulative attribute vs log")
    say("=" * 74)
    tot_s = tot_l = 0
    for s in SC:
        a = sum(int(cells[("FULL", s, i)]["teleports"])
                for i in range(len(days)))
        b = 0
        for i in range(len(days)):
            lp = os.path.join(WORK, "runs", "FULL", s, "day%03d" % i,
                              "sumo.log")
            with open(lp, errors="ignore") as f:
                b += sum(1 for ln in f if ln.startswith(
                    "Warning: Teleporting vehicle"))
        tot_s += a
        tot_l += b
        say(f"  {s:<12} summary(max over steps)={a:4d}   warning-log "
            f"teleport lines={b:4d}")
    say(f"  totals: summary={tot_s}, log={tot_l}. tripinfo itself has NO "
        "teleport field, so vehicle-level teleport ids come from the log.")

    say()
    say("=" * 74)
    say("V7  THE CLOSURE BITES, AND THE QUEUE STAYS DOWNSTREAM OF THE "
        "DIVERGE")
    say("=" * 74)
    say("  The closed edge itself does NOT slow down much -- it discharges at "
        "its\n  reduced capacity.  The signature of a working closure is a "
        "density jump\n  on the closed edge and a queue stored on the "
        "main-exclusive approach AC.\n  Per `simulate-incident-rerouting` "
        "that queue must NOT reach the diverge at A\n  (i.e. OA occupancy "
        "must stay low), or diverters get trapped.")
    shown = 0
    order = sorted([i for i, d in enumerate(days)
                    if d["incident"] and d["inc_lanes"] == 2],
                   key=lambda i: -days[i]["mult"])
    for i in order:
        d = days[i]
        if shown >= 4:
            break
        row = {}
        for blk in ("FULL", "DEMAND"):
            p = os.path.join(WORK, "runs", blk, "A_base", "day%03d" % i,
                             "edgedata.xml")
            acc = {e: [] for e in (d["inc_edge"], "AC", "OA")}
            t = 0.0
            for ev, el in ET.iterparse(p, events=("start", "end")):
                if ev == "start" and el.tag == "interval":
                    t = float(el.get("begin"))
                elif ev == "end" and el.tag == "edge" and el.get("id") in acc:
                    if d["inc_start"] <= t < d["inc_start"] + d["inc_dur"]:
                        acc[el.get("id")].append(
                            (float(el.get("occupancy")),
                             float(el.get("density")),
                             float(el.get("speed"))))
            row[blk] = {k: (np.mean([x[0] for x in v]) if v else np.nan,
                            np.mean([x[1] for x in v]) if v else np.nan,
                            np.mean([x[2] for x in v]) if v else np.nan)
                        for k, v in acc.items()}
        say(f"  day{i:03d} mult={d['mult']:.3f} {d['inc_edge']} "
            f"2 lanes closed {d['inc_start']:.0f}-"
            f"{d['inc_start']+d['inc_dur']:.0f}s   (mean over the window)")
        for e in (d["inc_edge"], "AC", "OA"):
            f_, g_ = row["FULL"][e], row["DEMAND"][e]
            # SUMO edgeData `density` is veh/km for the WHOLE edge, so on the
            # closed edge it falls simply because two lanes are empty; the
            # meaningful quantity is density per OPEN lane.
            openf = 3 - (d["inc_lanes"] if e == d["inc_edge"] else 0)
            say(f"      {e:<4} occupancy {g_[0]:6.2f}% -> {f_[0]:6.2f}%   "
                f"edge density {g_[1]:7.2f} -> {f_[1]:7.2f} veh/km   "
                f"per OPEN lane {g_[1]/3:6.2f} -> {f_[1]/openf:6.2f}   "
                f"speed {g_[2]:5.2f} -> {f_[2]:5.2f} m/s")
        shown += 1

    say()
    say("=" * 74)
    say("V8  INCIDENT EFFECT SIGN -- honest note on non-monotone days")
    say("=" * 74)
    for s in SC:
        deltas = []
        for i, d in enumerate(days):
            if not d["incident"]:
                continue
            a = npz("FULL", s, "day%03d" % i)
            b = npz("DEMAND", s, "day%03d" % i)
            deltas.append(float((a["dur"] + a["departdelay"]).mean()
                                - (b["dur"] + b["departdelay"]).mean()))
        deltas = np.array(deltas)
        say(f"  {s:<12} incident days={len(deltas)}  mean effect="
            f"{deltas.mean():+8.2f}s  median={np.median(deltas):+8.2f}s  "
            f"max={deltas.max():+8.1f}s  "
            f"days where the incident REDUCED the daily mean: "
            f"{int((deltas < 0).sum())}")
    say("  A negative incident effect is possible (a lane closure can meter "
        "the\n  arrival pattern at a downstream constraint); these days are "
        "kept, not\n  discarded -- they are part of the realised "
        "distribution.")

    say()
    say("=" * 74)
    say("V9  SPILLBACK PAST THE DIVERGE -- a design limitation, quantified")
    say("=" * 74)
    say("  `simulate-incident-rerouting` requires the incident queue to be "
        "stored on\n  the main-exclusive edge AC and NOT to reach the diverge "
        "at A.  On the most\n  heavily loaded days that requirement is "
        "violated by RECURRENT congestion\n  (independently of any incident), "
        "which caps how much diversion scenario C\n  can physically achieve. "
        "Counted below as days with max OA occupancy > 20%.")
    for s in SC:
        oa = np.array([float(cells[("FULL", s, i)]["oa_occ_max"])
                       for i in range(len(days))])
        oad = np.array([float(cells[("DEMAND", s, i)]["oa_occ_max"])
                        for i in range(len(days))])
        say(f"  {s:<12} FULL: {int((oa > 20).sum()):3d}/{len(days)} days "
            f"(max {oa.max():5.1f}%)   DEMAND (no incidents): "
            f"{int((oad > 20).sum()):3d}/{len(days)} days "
            f"(max {oad.max():5.1f}%)")

    os.makedirs(OUT, exist_ok=True)
    open(os.path.join(OUT, "verification_report.txt"), "w").write(
        "\n".join(L) + "\n")
    say("\nwrote " + os.path.join(OUT, "verification_report.txt"))


if __name__ == "__main__":
    main()
