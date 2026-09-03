#!/usr/bin/env python3
"""Aggregate every cell x seed into a per-cell results table with 95 % CIs.

Every number written here is derived from one of:
  <tag>_traci.json        TraCI instrumentation (this study's primary instrument)
  <tag>_instant.xml       instantInductionLoop stop-line passages (independent
                          cross-check of the on-red / on-green turn counts)
  <tag>_tripinfo.xml      tripinfo / personinfo (whole-trip and pedestrian delay)
  <tag>_ssm.xml           SSM device (vehicle-vehicle merge conflicts)
  <tag>_summary.xml       teleports / collisions / running counts
"""
import glob
import json
import math
import os
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

import numpy as np
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from linkmap import LinkMap
from run_cell import parse_program, analytic_state

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
OUT = os.path.join(BASE, "outputs")
RUNS = os.path.join(OUT, "runs")
WARMUP = 600.0
WIN_END = 3600.0
WIN_H = (WIN_END - WARMUP) / 3600.0          # 0.8333 h analysis window
MOVES = {"N": {"r": "W", "s": "S", "l": "E"}, "E": {"r": "N", "s": "W", "l": "S"},
         "S": {"r": "E", "s": "N", "l": "W"}, "W": {"r": "S", "s": "E", "l": "N"}}
CELLS = [("A_excl", "NTOR_noLPI"), ("A_excl", "RTOR_noLPI"),
         ("A_excl", "NTOR_LPI"), ("A_excl", "RTOR_LPI"),
         ("B_shared", "NTOR_noLPI"), ("B_shared", "RTOR_noLPI")]


def ci95(v):
    v = np.asarray([x for x in v if x is not None and not (isinstance(x, float) and math.isnan(x))],
                   dtype=float)
    if len(v) == 0:
        return (float("nan"),) * 4
    m = v.mean()
    if len(v) < 2:
        return m, 0.0, m, m
    h = stats.t.ppf(0.975, len(v) - 1) * v.std(ddof=1) / math.sqrt(len(v))
    return m, h, m - h, m + h


def veh_move(vid):
    b = vid.split(".")[0]
    return b[2], b[3]


def parse_instant(path, prefix):
    """Right-turn passages seen by an instantInductionLoop whose id starts with
    `prefix` ('inst_in_' = 2 m upstream of the line; 'instv_' = 1 m along the
    right turn's internal via lane, i.e. immediately downstream of the line)."""
    ev = []
    if not os.path.exists(path):
        return ev
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag != "instantOut":
            continue
        if el.get("state") == "enter" and el.get("id", "").startswith(prefix):
            vid = el.get("vehID")
            try:
                appr, mov = veh_move(vid)
            except Exception:
                el.clear(); continue
            want = f"inst_in_{appr}_1" if prefix == "inst_in_" else f"instv_{appr}"
            if mov == "r" and el.get("id") == want:
                ev.append((float(el.get("time")), appr, vid, float(el.get("speed"))))
        el.clear()
    return ev


def parse_tripinfo(path):
    veh, ped = [], []
    if not os.path.exists(path):
        return veh, ped
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "tripinfo":
            veh.append({"id": el.get("id"), "depart": float(el.get("depart")),
                        "timeLoss": float(el.get("timeLoss")),
                        "waitingTime": float(el.get("waitingTime")),
                        "duration": float(el.get("duration"))})
            el.clear()
        elif el.tag == "personinfo":
            w = el.find("walk")
            if w is not None:
                ped.append({"depart": float(el.get("depart")),
                            "timeLoss": float(w.get("timeLoss")),
                            "waitingTime": float(w.get("waitingTime")),
                            "duration": float(w.get("duration"))})
            el.clear()
    return veh, ped


def parse_ssm(path):
    """Merge conflicts (encounter types 6,7,8,19) in which the EGO is a
    right-turning vehicle merging into the receiving street."""
    n_merge_rt, n_any_rt, ttcs = 0, 0, []
    if not os.path.exists(path):
        return 0, 0, []
    # NB: clear() only on <conflict>; clearing every element would wipe the
    # <minTTC> child's attributes before the parent's end-event fires.
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag != "conflict":
            continue
        ego, foe = el.get("ego"), el.get("foe")
        try:
            ea, em = veh_move(ego); fa, fm = veh_move(foe)
        except Exception:
            el.clear(); continue
        if em == "r":
            n_any_rt += 1
            m = el.find("minTTC")
            typ = m.get("type") if m is not None else None
            if typ in ("6", "7", "8", "19") and MOVES[ea]["r"] == MOVES[fa][fm]:
                n_merge_rt += 1
                if m is not None and m.get("value") not in (None, "NA"):
                    ttcs.append(float(m.get("value")))
        el.clear()
    return n_merge_rt, n_any_rt, ttcs


def parse_summary(path):
    tel, coll, ended = 0, 0, 0.0
    if not os.path.exists(path):
        return tel, coll, ended
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "step":
            tel = max(tel, int(el.get("teleports", 0)))
            coll = max(coll, int(el.get("collisions", 0)))
            ended = float(el.get("time"))
        el.clear()
    return tel, coll, ended


def analyze_run(variant, cell, regime, seed):
    tag = f"{variant}__{cell}__{regime}__s{seed}"
    d = os.path.join(RUNS, regime, f"{variant}__{cell}")
    pfx = os.path.join(d, tag)
    tj = pfx + "_traci.json"
    if not os.path.exists(tj):
        return None
    T = json.load(open(tj))
    lm = LinkMap(os.path.join(OUT, "net", f"{variant}.net.xml"))
    ph, C, _ = parse_program(os.path.join(OUT, "programs", f"{variant}.{cell}.tll.xml"))
    right_li = {k: int(v) for k, v in T["right_link_index"].items()}

    r = {"variant": variant, "cell": cell, "regime": regime, "seed": seed,
         "analytic_state_mismatches": T["analytic_state_mismatches"],
         "teleports_traci": T["teleports"]}

    # ---------- 1. right-turn volume, TraCI ----------
    te = [e for e in T["turn_events"] if WARMUP <= e["t"] < WIN_END]
    on_red = [e for e in te if e["char"] in "rs"]
    on_red_r = [e for e in te if e["char"] == "r"]      # red-light running: must be 0
    on_grn = [e for e in te if e["char"] in "gG"]
    on_yel = [e for e in te if e["char"] == "y"]
    r["rt_total_vph"] = len(te) / WIN_H
    r["rt_onred_vph"] = len(on_red) / WIN_H
    r["rt_ongreen_vph"] = len(on_grn) / WIN_H
    r["rt_onyellow_vph"] = len(on_yel) / WIN_H
    r["rt_onred_share"] = len(on_red) / len(te) if te else float("nan")
    r["rt_onred_count"] = len(on_red)
    r["rt_hard_red_count"] = len(on_red_r)
    r["rt_total_count"] = len(te)
    for lab, sel in (("onred", on_red), ("ongreen", on_grn)):
        sp = np.array([e["speed"] for e in sel]) if sel else np.array([])
        ms = np.array([e["minspeed15"] for e in sel if e["minspeed15"] >= 0])
        r[f"stopline_speed_{lab}"] = float(sp.mean()) if len(sp) else float("nan")
        r[f"minappr_speed_{lab}"] = float(ms.mean()) if len(ms) else float("nan")
        r[f"stopfrac_{lab}"] = float((ms < 0.3).mean()) if len(ms) else float("nan")

    # ---------- 2. independent detector cross-check ----------
    # (a) upstream loop (2 m before the line): volume cross-check only.  It
    #     cannot time the DEPARTURE from the stop line, because a vehicle held
    #     at the line has already passed it.
    # (b) via-lane loop (1 m past the line, on the internal lane): times the
    #     actual stop-line crossing.  Classified with the ANALYTIC program
    #     reconstruction - no TraCI involved on this path.
    up = [e for e in parse_instant(pfx + "_instant.xml", "inst_in_")
          if WARMUP <= e[0] < WIN_END]
    via = [e for e in parse_instant(pfx + "_instantvia.xml", "instv_")
           if WARMUP <= e[0] < WIN_END]

    def classify(ev):
        red = grn = oth = 0
        cls = {}
        for (t, appr, vid, sp) in ev:
            ch = analytic_state(ph, C, t)[right_li[appr]]
            c = "red" if ch in "rs" else "green" if ch in "gG" else "yellow"
            cls[vid] = c
            red += c == "red"; grn += c == "green"; oth += c == "yellow"
        return red, grn, oth, cls

    ured, ugrn, uoth, _ = classify(up)
    vred, vgrn, voth, vcls = classify(via)
    r["det_up_rt_total_count"] = len(up)
    r["det_up_rt_onred_count"] = ured
    r["det_rt_total_count"] = len(via)
    r["det_rt_onred_count"] = vred
    r["det_rt_ongreen_count"] = vgrn
    r["det_rt_onyellow_count"] = voth
    r["det_rt_onred_vph"] = vred / WIN_H
    r["det_vs_traci_total_diff"] = len(via) - len(te)
    r["det_vs_traci_onred_diff"] = vred - len(on_red)
    r["detup_vs_traci_total_diff"] = len(up) - len(te)
    traci_cls = {e["veh"]: ("red" if e["char"] in "rs" else
                            "green" if e["char"] in "gG" else "yellow") for e in te}
    common = set(traci_cls) & set(vcls)
    r["det_traci_common"] = len(common)
    r["det_traci_class_disagree"] = sum(1 for v in common if traci_cls[v] != vcls[v])

    # ---------- 3. control delay ----------
    seg = [s for s in T["segment"] if len(s) == 5 and WARMUP <= s[3] < WIN_END and s[2]]
    def cd(sel):
        v = np.array([s[1] - s[2] for s in sel])
        return (float(v.mean()), float(np.percentile(v, 95)), len(v)) if len(v) else \
               (float("nan"), float("nan"), 0)
    rt = [s for s in seg if s[0][1] == "r"]
    r["cd_rt_mean"], r["cd_rt_p95"], r["cd_rt_n"] = cd(rt)
    thr = [s for s in seg if s[0][1] == "s"]
    r["cd_thru_mean"], r["cd_thru_p95"], _ = cd(thr)
    lf = [s for s in seg if s[0][1] == "l"]
    r["cd_left_mean"], r["cd_left_p95"], _ = cd(lf)
    r["cd_int_mean"], r["cd_int_p95"], r["cd_int_n"] = cd(seg)
    # approach-level = every movement of the approaches, same thing here
    r["cd_appr_mean"] = r["cd_int_mean"]

    # ---------- 4. pedestrians ----------
    xe = {int(k): v for k, v in T["xing_entries"].items()}
    xw = {int(k): v for k, v in T["xing_waits"].items()}
    r["ped_xing_total"] = sum(xe.values())
    r["ped_xing_vph_per_crossing"] = sum(xe.values()) / 4.0 / (T["demand_end"] / 3600.0)
    allw = [w for k in xw for w in xw[k]]
    r["ped_cross_wait_mean"] = float(np.mean(allw)) if allw else float("nan")
    r["ped_cross_wait_p95"] = float(np.percentile(allw, 95)) if allw else float("nan")
    for a in "NESW":
        li = lm.leg_xing[a]
        r[f"ped_wait_{a}"] = float(np.mean(xw[li])) if xw.get(li) else float("nan")
        r[f"ped_vol_{a}"] = xe.get(li, 0)

    veh, ped = parse_tripinfo(pfx + "_tripinfo.xml")
    pw = [p for p in ped if WARMUP <= p["depart"] < WIN_END]
    r["ped_timeloss_mean"] = float(np.mean([p["timeLoss"] for p in pw])) if pw else float("nan")
    r["ped_timeloss_p95"] = float(np.percentile([p["timeLoss"] for p in pw], 95)) if pw else float("nan")
    r["ped_waitingtime_mean"] = float(np.mean([p["waitingTime"] for p in pw])) if pw else float("nan")
    r["ped_n"] = len(pw)
    vw = [v for v in veh if WARMUP <= v["depart"] < WIN_END]
    r["veh_timeloss_mean"] = float(np.mean([v["timeLoss"] for v in vw])) if vw else float("nan")
    rtv = [v for v in vw if veh_move(v["id"])[1] == "r"]
    r["veh_timeloss_rt_mean"] = float(np.mean([v["timeLoss"] for v in rtv])) if rtv else float("nan")
    r["veh_completed"] = len(vw)

    # ---------- 5. ped-vehicle conflict exposure ----------
    cf = [c for c in T["conflicts"] if WARMUP <= c["t0"] < WIN_END]
    sev = [c for c in cf if c["min_ttc"] < 2.0 and c["max_vspeed"] >= 1.0]
    r["pedveh_episodes"] = len(cf)
    r["pedveh_conflicts"] = len(sev)
    r["pedveh_conflicts_onred"] = sum(1 for c in sev if c["on_red"])
    r["pedveh_conflicts_ongreen"] = sum(1 for c in sev if not c["on_red"])
    r["pedveh_conflicts_per_h"] = len(sev) / WIN_H
    r["pedveh_conflicts_per_1000rt"] = 1000.0 * len(sev) / len(te) if te else float("nan")
    # ENCROACHMENT subset: the vehicle was physically PAST the stop line (on the
    # right turn's internal via lane) when it came closest to the pedestrian.
    # Only present in runs made with the extended instrument.
    enc = [c for c in cf if c.get("encroach_ttc", 1e9) < 2.0 and c.get("encroach_dist", 1e9) <= 8.0]
    r["pedveh_encroach"] = len(enc) if any("encroach_ttc" in c for c in cf) else float("nan")
    r["pedveh_encroach_onred"] = (sum(1 for c in enc if c["on_red"])
                                  if any("encroach_ttc" in c for c in cf) else float("nan"))
    r["pedveh_encroach_ongreen"] = (sum(1 for c in enc if not c["on_red"])
                                    if any("encroach_ttc" in c for c in cf) else float("nan"))
    r["pedveh_encroach_per_h"] = (len(enc) / WIN_H
                                  if any("encroach_ttc" in c for c in cf) else float("nan"))
    r["pedveh_min_dist_mean"] = float(np.mean([c["min_dist"] for c in sev])) if sev else float("nan")
    r["pedveh_min_ttc_mean"] = float(np.mean([c["min_ttc"] for c in sev])) if sev else float("nan")
    r["pedveh_yield_stops"] = sum(1 for c in cf if c["min_vspeed"] < 0.3)

    # ---------- 6. SSM vehicle-vehicle merge conflicts on the turn ----------
    nm, na, ttcs = parse_ssm(pfx + "_ssm.xml")
    r["ssm_rt_merge_conflicts"] = nm
    r["ssm_rt_any_conflicts"] = na
    r["ssm_rt_merge_per_h"] = nm / (T["end"] / 3600.0)
    r["ssm_rt_merge_minttc_mean"] = float(np.mean(ttcs)) if ttcs else float("nan")

    tel, coll, ended = parse_summary(pfx + "_summary.xml")
    r["teleports"] = tel
    r["collisions"] = coll

    # ---------- 7. saturation-flow headways (capacity regime) ----------
    if regime == "capacity":
        by_ap = defaultdict(list)
        for (t, appr, vid, sp) in via:
            by_ap[appr].append(t)
        hg, hr = [], []
        for appr, ts in by_ap.items():
            ts.sort()
            li = right_li[appr]
            for i in range(1, len(ts)):
                h = ts[i] - ts[i - 1]
                if h > 12.0:
                    continue
                c0 = analytic_state(ph, C, ts[i - 1])[li]
                c1 = analytic_state(ph, C, ts[i])[li]
                if c0 in "gG" and c1 in "gG":
                    hg.append(h)
                elif c0 in "rs" and c1 in "rs":
                    hr.append(h)
        r["sat_headway_green_med"] = float(np.median(hg)) if hg else float("nan")
        r["sat_flow_green_vphpl"] = 3600.0 / np.median(hg) if hg else float("nan")
        r["sat_headway_red_med"] = float(np.median(hr)) if hr else float("nan")
        r["sat_flow_red_vphpl"] = 3600.0 / np.median(hr) if hr else float("nan")
        r["n_headway_green"] = len(hg)
        r["n_headway_red"] = len(hr)
    return r


if __name__ == "__main__":
    rows = []
    for regime in ("operational", "capacity"):
        for variant, cell in CELLS:
            for seed in range(1, 11):
                x = analyze_run(variant, cell, regime, seed)
                if x:
                    rows.append(x)
    with open(os.path.join(OUT, "per_run_metrics.json"), "w") as f:
        json.dump(rows, f, indent=1)

    # per-cell aggregation
    keys = sorted({k for r in rows for k in r if isinstance(r[k], (int, float))})
    agg = {}
    for regime in ("operational", "capacity"):
        for variant, cell in CELLS:
            sel = [r for r in rows if r["regime"] == regime and r["variant"] == variant
                   and r["cell"] == cell]
            if not sel:
                continue
            a = {"n_seeds": len(sel)}
            for k in keys:
                if k == "seed":
                    continue
                vals = [r.get(k) for r in sel]
                m, h, lo, hi = ci95(vals)
                a[k] = {"mean": m, "ci95": h, "lo": lo, "hi": hi}
            agg[f"{regime}|{variant}|{cell}"] = a
    with open(os.path.join(OUT, "per_cell_metrics.json"), "w") as f:
        json.dump(agg, f, indent=1)
    print(f"{len(rows)} runs analysed -> per_run_metrics.json / per_cell_metrics.json")
    for k in agg:
        a = agg[k]
        print(f"{k:52s} n={a['n_seeds']} rt_onred_share="
              f"{a['rt_onred_share']['mean']:.3f} rt_total={a['rt_total_vph']['mean']:.0f} "
              f"cd_rt={a['cd_rt_mean']['mean']:.1f} mism={a['analytic_state_mismatches']['mean']:.1f}")
