#!/usr/bin/env python3
"""Per-run metric extraction + the authoritative TSTT decomposition.

AUTHORITATIVE DEFINITIONS (used identically in every table, figure and narrative,
per the `build-diamond-interchange-with-signal-offset-spillback` reconciliation rule):

  TSTT  = total vehicle-hours spent inside the network (edgeData `sampledSeconds`
          over ALL edges including internal junction edges)
          + origin-insertion vehicle-hours (integral of the count of vehicles
            waiting for insertion, sampled every 10 s, over the whole run).
  TSD   = Total System DELAY, the same four-way split but using edgeData
          `timeLoss` for the in-network parts (delay relative to the vehicle's
          own desired speed) and the full insertion integral for the origin part.

  Facility classes (by edge id):
    mainline : ml_*, o*_off  and internal edges of the m_* freeway junctions
    ramp     : r*_stor, r*_mrg and internal edges of the r*_met meter junctions
    surface  : r*_sapp, r*_sout, r*_capp, r*_cout and internal edges of r*_term
    origin   : the insertion queue (not an edge)

  RAMP-STORAGE-EXCEEDED FLAG: a control interval in which the E2 detector on a
  ramp's storage segment reports >= 0.95 of the segment's vehicle capacity.
"""
import json
import math
import os
import sys
import xml.etree.ElementTree as ET

import numpy as np

RAMPS = ["r1", "r2", "r3"]
STATIONS = [f"s{i:02d}" for i in range(1, 13)]
R_MAX = 1800.0
CTRL_DT = 30.0


def classify(eid):
    if eid.startswith(":"):
        j = eid[1:]
        if j.startswith("m_"):
            return "mainline"
        if any(j.startswith(f"{r}_met") for r in RAMPS):
            return "ramp"
        if any(j.startswith(f"{r}_term") for r in RAMPS):
            return "surface"
        return "other"
    if eid.startswith("ml_") or eid.endswith("_off"):
        return "mainline"
    if eid.endswith("_stor") or eid.endswith("_mrg"):
        return "ramp"
    if eid.endswith(("_sapp", "_sout", "_capp", "_cout")):
        return "surface"
    return "other"


def veh_class(vid):
    if vid.startswith("ml_"):
        return "fwy_mainline_origin"
    if vid.startswith(("r1_", "r2_", "r3_")):
        return "fwy_ramp_origin"
    return "surface"


def parse_edgedata(path):
    out = {c: dict(vs=0.0, tl=0.0) for c in ("mainline", "ramp", "surface", "other")}
    for iv in ET.parse(path).getroot():
        for e in iv.findall("edge"):
            c = classify(e.get("id"))
            out[c]["vs"] += float(e.get("sampledSeconds", 0.0))
            out[c]["tl"] += float(e.get("timeLoss", 0.0))
    return out


def parse_tripinfo(path):
    agg = {}
    tele_free_ok = True
    per_veh = {}
    for ti in ET.parse(path).getroot():
        if ti.tag != "tripinfo":
            continue
        vid = ti.get("id")
        c = veh_class(vid)
        a = agg.setdefault(c, dict(n=0, done=0, dur=0.0, tl=0.0, dd=0.0, wt=0.0, rl=0.0))
        arr = float(ti.get("arrival", -1))
        dur = float(ti.get("duration"))
        a["n"] += 1
        a["done"] += 1 if arr >= 0 else 0
        a["dur"] += dur
        a["tl"] += float(ti.get("timeLoss"))
        a["dd"] += float(ti.get("departDelay"))
        a["wt"] += float(ti.get("waitingTime"))
        a["rl"] += float(ti.get("routeLength"))
        per_veh[vid] = (dur, float(ti.get("timeLoss")), float(ti.get("departDelay")), arr >= 0)
    return agg, per_veh


def parse_summary(path):
    last = None
    for s in ET.parse(path).getroot():
        last = s
    return dict(loaded=int(last.get("loaded")), inserted=int(last.get("inserted")),
                running=int(last.get("running")), ended=int(last.get("ended")),
                teleports=int(last.get("teleports")), t_end=float(last.get("time")))


def analyze(rundir):
    ctl = json.load(open(os.path.join(rundir, "ctl.json")))
    meta, log = ctl["meta"], ctl["log"]
    ed = parse_edgedata(os.path.join(rundir, "edgedata.xml"))
    ti, _ = parse_tripinfo(os.path.join(rundir, "tripinfo.xml"))
    sm = parse_summary(os.path.join(rundir, "summary.xml"))

    ins_h = meta["pend_integral_veh_s"] / 3600.0
    R = dict(arm=meta["arm"], seed=meta["seed"], demand=meta["demand"],
             stor_r3=meta["storage"]["r3"], t_end=meta["end"],
             teleports=meta["teleports"], n_teleport_veh=len(meta["teleport_ids"]),
             o_on_bn=meta.get("o_on_bn"), w_flush=meta.get("w_flush"))
    R.update(sm)
    # ---------- TSTT / TSD decomposition ----------
    for c in ("mainline", "ramp", "surface"):
        R[f"vh_{c}"] = ed[c]["vs"] / 3600.0
        R[f"delay_{c}"] = ed[c]["tl"] / 3600.0
    R["vh_origin"] = ins_h
    R["delay_origin"] = ins_h
    R["TSTT"] = sum(R[f"vh_{c}"] for c in ("mainline", "ramp", "surface", "origin"))
    R["TSD"] = sum(R[f"delay_{c}"] for c in ("mainline", "ramp", "surface", "origin"))
    R["TSTT_freeway_users"] = R["vh_mainline"] + R["vh_ramp"] + R["vh_origin"]

    # ---------- vehicle accounting ----------
    R["n_loaded"] = sm["loaded"]
    R["n_never_inserted"] = sm["loaded"] - sm["inserted"]
    R["n_still_running"] = sm["running"]
    R["n_completed"] = sm["ended"]
    for c, a in ti.items():
        R[f"n_{c}"] = a["n"]
        R[f"done_{c}"] = a["done"]
        R[f"meandur_{c}"] = a["dur"] / max(a["n"], 1)
        R[f"meantl_{c}"] = a["tl"] / max(a["n"], 1)
        R[f"meandd_{c}"] = a["dd"] / max(a["n"], 1)

    # ---------- mainline / bottleneck performance ----------
    thr = sum(r["flow"]["s11"] for r in log) * CTRL_DT / 3600.0
    R["bottleneck_veh_served"] = thr
    peak = [r for r in log if 1500 <= r["t"] <= 5400]
    R["bn_discharge_peak"] = sum(r["flow"]["s11"] for r in peak) / max(len(peak), 1)
    R["mean_spd_s10"] = _mean([r["spd"]["s10"] for r in peak])
    R["mean_occ_s10"] = _mean([r["occ"]["s10"] for r in peak])
    # BREAKDOWN ONSET is measured at s09, NOT at s10.  s10 sits ~100 m upstream of
    # the lane drop, inside a permanent merge-turbulence zone that reads 16 m/s even
    # at demands far below capacity, so it can never distinguish "queue present" from
    # "normal merging".  s09 (800 m upstream, just downstream of the r3 merge) is
    # free-flowing until a genuine queue propagates back from the drop.
    R["mean_spd_s09"] = _mean([r["spd"]["s09"] for r in peak])
    R["mean_occ_s09"] = _mean([r["occ"]["s09"] for r in peak])
    R["breakdown_onset"] = None
    for i in range(len(log) - 1):
        a, b = log[i]["spd"]["s09"], log[i + 1]["spd"]["s09"]
        if a is not None and b is not None and a < 20 and b < 20:
            R["breakdown_onset"] = log[i]["t"]
            break
    R["breakdown_duration"] = sum(CTRL_DT for r in log
                                  if r["spd"]["s09"] is not None and r["spd"]["s09"] < 20)
    # max sustained discharge while the corridor upstream of the drop is still
    # free-flowing (= the corridor's own capacity, merges included)
    ff = [r["flow"]["s11"] for r in log
          if r["t"] > 300 and r["spd"]["s09"] is not None and r["spd"]["s09"] > 27]
    R["prebreakdown_discharge_p95"] = float(sorted(ff)[int(0.95 * (len(ff) - 1))]) if ff else None
    cg = [r["flow"]["s11"] for r in log if r["t"] > 900 and r["t"] < 5400
          and r["spd"]["s09"] is not None and r["spd"]["s09"] < 15]
    R["congested_discharge"] = float(np.mean(cg)) if cg else None
    # queue extent: most-upstream station with mean speed < 20 during the peak
    ext = 0
    for si, s in enumerate(STATIONS[:10]):   # s11/s12 are downstream of the drop
        v = _mean([r["spd"][s] for r in peak])
        if v is not None and v < 20:
            ext = max(ext, 10 - si)
    R["queue_extent_stations"] = ext

    # ---------- ramp / surface / control ----------
    tot_cmd_veh = tot_real_veh = 0.0
    ver_n = ver_err = 0.0
    ver_pairs = []
    for r in RAMPS:
        rl = [x["ramp"][r] for x in log]
        S = meta["storage"][r] / 7.5
        R[f"{r}_maxq_ratio"] = max(x["ratio"] for x in rl)
        R[f"{r}_frac_storage_exceeded"] = sum(1 for x in rl if x["ratio"] >= 0.95) / len(rl)
        R[f"{r}_frac_active"] = sum(1 for x in rl if x["active"]) / len(rl)
        R[f"{r}_frac_restrictive"] = sum(1 for x in rl if x["cmd"] < R_MAX - 1) / len(rl)
        nover = sum(1 for x in rl if x["override"])
        nact = sum(1 for x in rl if x["active"] or x["override"])
        R[f"{r}_frac_override_of_active"] = nover / nact if nact else 0.0
        R[f"{r}_frac_override"] = nover / len(rl)
        R[f"{r}_queue_veh_hours"] = sum(x["nveh"] for x in rl) * CTRL_DT / 3600.0
        R[f"{r}_capp_veh_hours"] = sum(x["capp_n"] for x in rl) * CTRL_DT / 3600.0
        R[f"{r}_sapp_veh_hours"] = sum(x["sapp_n"] for x in rl) * CTRL_DT / 3600.0
        R[f"{r}_released"] = sum(x["realized"] for x in rl) * CTRL_DT / 3600.0
        R[f"{r}_arrivals"] = sum(x["arrivals"] for x in rl) * CTRL_DT / 3600.0
        # metering-rate verification: only intervals where the meter was actually
        # restrictive AND a queue was present (otherwise the ramp is demand-limited)
        for x in rl:
            if x["cmd_prev"] < R_MAX - 1 and x["nveh"] >= 2:
                ver_pairs.append((x["cmd_prev"], x["realized"]))
        tot_cmd_veh += sum(min(x["cmd_prev"], R_MAX) for x in rl) * CTRL_DT / 3600.0
        tot_real_veh += sum(x["realized"] for x in rl) * CTRL_DT / 3600.0
    if ver_pairs:
        R["rate_ver_n"] = len(ver_pairs)
        R["rate_ver_cmd_mean"] = sum(c for c, _ in ver_pairs) / len(ver_pairs)
        R["rate_ver_real_mean"] = sum(v for _, v in ver_pairs) / len(ver_pairs)
        R["rate_ver_mape"] = sum(abs(v - c) / c for c, v in ver_pairs) / len(ver_pairs)
    R["ramp_released_total"] = tot_real_veh
    R["surface_capp_veh_hours"] = sum(R[f"{r}_capp_veh_hours"] for r in RAMPS)

    # ---------- equity: per-ramp delay dispersion ----------
    per_ramp_delay = [R[f"{r}_queue_veh_hours"] for r in RAMPS]
    R["ramp_delay_max_over_mean"] = (max(per_ramp_delay) / (sum(per_ramp_delay) / 3)
                                     if sum(per_ramp_delay) > 0 else float("nan"))
    R["ramp_delay_gini"] = gini(per_ramp_delay)
    # per-ramp mean wait per released vehicle (delay actually borne by a ramp user)
    pr = []
    for r in RAMPS:
        rel = max(R[f"{r}_released"], 1.0)
        pr.append(R[f"{r}_queue_veh_hours"] * 3600.0 / rel)
    R["ramp_wait_per_veh"] = pr
    R["ramp_wait_gini"] = gini(pr)
    R["ramp_wait_max_over_mean"] = max(pr) / (sum(pr) / 3) if sum(pr) > 0 else float("nan")
    return R


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def gini(x):
    x = sorted(max(v, 0.0) for v in x)
    n = len(x)
    s = sum(x)
    if s <= 0:
        return 0.0
    return (2 * sum((i + 1) * v for i, v in enumerate(x)) / (n * s)) - (n + 1) / n


if __name__ == "__main__":
    import csv
    root = sys.argv[1]
    rows = []
    for dp, dn, fn in os.walk(root):
        if "ctl.json" in fn:
            try:
                r = analyze(dp)
                r["tag"] = os.path.relpath(dp, root)
                rows.append(r)
            except Exception as e:
                print("ERR", dp, e, file=sys.stderr)
    keys = sorted({k for r in rows for k in r})
    out = sys.argv[2]
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["tag"] + [k for k in keys if k != "tag"])
        w.writeheader()
        for r in rows:
            w.writerow({k: (json.dumps(v) if isinstance(v, list) else v) for k, v in r.items()})
    print(f"{len(rows)} runs -> {out}")
