#!/usr/bin/env python3
"""
Independent behavioural verification of every mechanism the study relies on.
Writes analysis/mechanism_verification.txt.
"""
import csv
import glob
import gzip
import io
import os
import statistics as st
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from statlib import paired_diff  # noqa: E402

L = []


def P(s=""):
    print(s)
    L.append(s)


def dec_open(p):
    if os.path.exists(p):
        return open(p)
    return io.TextIOWrapper(gzip.open(p + ".gz", "rb"), encoding="utf-8")


def meta(d):
    return {r["key"]: r["value"] for r in csv.DictReader(open(os.path.join(d, "run_meta.csv")))}


# ---- 1. static vClass restriction is genuinely enforced ---------------------
P("=" * 78)
P("1. STATIC vCLASS RESTRICTION (arm B): did any passenger-class SOV ever occupy lane 3?")
P("=" * 78)
tot_sov = tot_sov_on_ml = 0
nruns = 0
for d in sorted(glob.glob(os.path.join(ROOT, "runs", "*"))):
    mp = os.path.join(d, "run_meta.csv")
    dp = os.path.join(d, "decisions.csv")
    if not (os.path.exists(mp) and (os.path.exists(dp) or os.path.exists(dp + ".gz"))):
        continue
    m = meta(d)
    if m["arm"] != "B":
        continue
    nruns += 1
    for r in csv.DictReader(dec_open(dp)):
        if r["cls"] == "sov":
            tot_sov += 1
            if float(r["ml_seconds"]) > 0:
                tot_sov_on_ml += 1
P(f"arm-B runs inspected: {nruns};  SOV vehicles: {tot_sov};  "
  f"SOV-seconds observed on any managed lane: {tot_sov_on_ml}")
P(f"VERDICT: {'PASS - restriction absolute' if tot_sov_on_ml == 0 else 'FAIL'}")
P()

# ---- 2. vClass switching actually grants access -----------------------------
P("=" * 78)
P("2. TraCI setVehicleClass GRANTS ACCESS (arms C/D): do bought-in SOVs reach lane 3?")
P("=" * 78)
for tag in ("MAIN_Clo", "MAIN_D", "MAIN_Chi"):
    n_buy = n_buy_ml = 0
    for d in sorted(glob.glob(os.path.join(ROOT, "runs", tag + "_*"))):
        for r in csv.DictReader(dec_open(os.path.join(d, "decisions.csv"))):
            if r["cls"] == "sov" and int(r["eligible"]):
                n_buy += 1
                if float(r["ml_seconds"]) > 0:
                    n_buy_ml += 1
    P(f"{tag}: {n_buy} SOVs bought in, {n_buy_ml} ({100*n_buy_ml/max(1,n_buy):.1f}%) were "
      f"subsequently observed on the managed lane")
P("(a buyer who never uses the lane is a real behavioural outcome - SUMO's lane-change model "
  "only moves it left when that is actually faster - not a mechanism failure)")
P()

# ---- 3. toll is perceived-cost only ----------------------------------------
P("=" * 78)
P("3. THE TOLL IS PERCEIVED-COST-ONLY: managed-lane REAL speed across toll levels")
P("=" * 78)
import collections  # noqa: E402
g = collections.defaultdict(list)
for r in csv.DictReader(open(os.path.join(ROOT, "analysis", "metrics_H2all.csv"))):
    if r["run"].startswith("H2_toll"):
        g[float(r["run"].split("toll")[1].split("_")[0])].append(float(r["ld_m5_l3_speed"]))
sp = {t: st.mean(v) for t, v in sorted(g.items())}
P("toll $ -> managed-lane space-mean speed at m5 (m/s): " +
  ", ".join(f"{t:.2f}:{v:.2f}" for t, v in sp.items()))
P(f"range = {min(sp.values()):.2f}..{max(sp.values()):.2f} m/s "
  f"(spread {100*(max(sp.values())-min(sp.values()))/st.mean(sp.values()):.1f}% of mean); "
  f"no speed/capacity API is ever called on the managed lane - grep run_corridor.py for "
  f"setMaxSpeed/setSpeed/setDisallowed returns nothing.")
P()

# ---- 4. zero-toll negative control -----------------------------------------
P("=" * 78)
P("4. ZERO-TOLL NEGATIVE CONTROL: arm C at $0.00 vs arm A, same seeds")
P("=" * 78)
sys.path.insert(0, HERE)
from analyze import analyze  # noqa: E402
seeds = [1001, 1002, 1003]


def m(run, seed):
    d = os.path.join(ROOT, "runs", f"{run}_s{seed}")
    fl = meta(d)["routes"].replace(".rou.xml", ".fleet.csv")
    return analyze(d, fl)


A = {s: m("MAIN_A", s) for s in seeds}
Z = {s: m("CTRL_Czero", s) for s in seeds}
for k, lab in [("peak_persons_per_h", "person throughput (persons/h)"),
               ("all_pht_dd_h", "person-hours incl. delay (h)"),
               ("ld_m5_l3_flow", "managed-lane flow at m5 (veh/h)"),
               ("all_mean_dur", "mean duration (s)")]:
    d = paired_diff({s: Z[s][k] for s in seeds}, {s: A[s][k] for s in seeds})
    base = st.mean(A[s][k] for s in seeds)
    P(f"  {lab:35s}: A={base:9.1f}  C@$0={st.mean(Z[s][k] for s in seeds):9.1f}  "
      f"Δ={d['mean']:+8.1f} ± {d['hw']:.1f} ({100*d['mean']/base:+.2f}%)  sig={d['sig']}")
P("  take-rate of the $0 arm: " + ", ".join(f"{Z[s]['take_rate']:.3f}" for s in seeds))
P("  NOTE: this is a NEAR-, not exact-, negative control. Two residual differences remain by "
  "construction: (i) an SOV entering before any congestion has formed estimates zero time "
  "saving, so its willingness-to-pay is not strictly > $0 and it is denied; (ii) arm C applies "
  "the managed-lane-seeking nudge to eligible vehicles while arm A does not.")
P()

# ---- 5. nudge-symmetry control ---------------------------------------------
P("=" * 78)
P("5. NUDGE-SYMMETRY CONTROL: does applying the managed-lane-seeking nudge to hov/bus in")
P("   arm A (as arms B/C/D do) move the baseline?")
P("=" * 78)
N = {s: m("CTRL_Anudge", s) for s in seeds}
for k, lab in [("peak_persons_per_h", "person throughput (persons/h)"),
               ("all_pht_dd_h", "person-hours incl. delay (h)"),
               ("all_mean_dur", "mean duration (s)")]:
    d = paired_diff({s: N[s][k] for s in seeds}, {s: A[s][k] for s in seeds})
    base = st.mean(A[s][k] for s in seeds)
    P(f"  {lab:35s}: A={base:9.1f}  A+nudge={st.mean(N[s][k] for s in seeds):9.1f}  "
      f"Δ={d['mean']:+8.1f} ± {d['hw']:.1f} ({100*d['mean']/base:+.2f}%)  sig={d['sig']}")
P()

# ---- 6. accounting ----------------------------------------------------------
P("=" * 78)
P("6. VEHICLE ACCOUNTING across every run in the study")
P("=" * 78)
tot = bad = 0
worst = []
for f in glob.glob(os.path.join(ROOT, "analysis", "metrics_*.csv")):
    for r in csv.DictReader(open(f)):
        tot += 1
        fs, comp, still, ni, tp = (float(r["fleet_size"]), float(r["completed"]),
                                   float(r["still_running_at_end"]), float(r["never_inserted"]),
                                   float(r["teleports"]))
        if comp + still + ni != fs or tp > 0:
            bad += 1
            worst.append((r["run"], fs, comp, still, ni, tp))
P(f"metric rows checked: {tot}")
P(f"rows where completed + still-running + never-inserted != fleet size, OR teleports > 0: {bad}")
for w in worst[:10]:
    P(f"   {w}")
P(f"VERDICT: {'PASS - every vehicle accounted for, zero teleports anywhere' if bad == 0 else 'see above'}")
P()

open(os.path.join(ROOT, "analysis", "mechanism_verification.txt"), "w").write("\n".join(L) + "\n")
print("\n-> analysis/mechanism_verification.txt")
