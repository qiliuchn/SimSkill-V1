#!/usr/bin/env python3
"""
07_e1_estimators.py -- the loop-detector estimators, evaluated against ground truth.

ESTIMATOR A  corridor travel time from spot speeds:
             time-mean spot speed  vs  harmonic (space-mean) correction.
ESTIMATOR B  INSTANTANEOUS (snapshot of concurrent link speeds at departure)
             vs EXPERIENCED travel time: hysteresis loop, lead/lag error split
             by congestion-building vs congestion-clearing phase.
ESTIMATOR D  queue length from (i) input-output cumulative counts and
             (ii) occupancy threshold (single detector and full ladder).

Also: offline re-aggregation of the 30 s base intervals to 60 s / 300 s, verified
against SUMO's own native 300 s detectors.
"""
import csv
import json
import math
import os
import xml.etree.ElementTree as ET
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
SCEN = os.path.abspath(os.path.join(HERE, "..", "scenario"))
RUNS = os.path.abspath(os.path.join(HERE, "..", "..", "runs"))
RES = os.path.abspath(os.path.join(HERE, "..", "results"))

E1 = os.path.join(RUNS, "master", "e1_out.xml")
CYCLE, OFF_J3 = 90, 58
SETBACKS = [40, 80, 120, 160, 200, 250, 320]
V_FREE = 13.89
SPACING_JAM = 7.5      # m per queued vehicle (length 5.0 + minGap 2.5)
BUILD = (2400, 3600)   # congestion-building window
CLEAR = (3600, 4600)   # congestion-clearing window


# ------------------------------------------------------------------ utilities
def load_e1():
    """id -> list of dicts sorted by begin"""
    out = defaultdict(list)
    for _, el in ET.iterparse(E1, events=("end",)):
        if el.tag != "interval":
            continue
        d = {k: el.get(k) for k in el.keys()}
        out[d["id"]].append(dict(
            begin=float(d["begin"]), end=float(d["end"]),
            n=int(d["nVehContrib"]), nEnt=int(d["nVehEntered"]),
            flow=float(d["flow"]), occ=float(d["occupancy"]),
            speed=float(d["speed"]), hms=float(d["harmonicMeanSpeed"])))
        el.clear()
    for k in out:
        out[k].sort(key=lambda r: r["begin"])
    return out


def reaggregate(rows, factor):
    """Combine `factor` consecutive base intervals.  Exact re-aggregation rules:
       counts sum; flow = sum(n)/duration*3600; occupancy = duration-weighted mean;
       time-mean speed = count-weighted mean of sub-interval time-mean speeds;
       harmonic mean speed = sum(n)/sum(n/hms).   (-1 = no vehicles -> skipped.)"""
    out = []
    for i in range(0, len(rows) - factor + 1, factor):
        grp = rows[i:i + factor]
        n = sum(g["n"] for g in grp)
        dur = grp[-1]["end"] - grp[0]["begin"]
        occ = sum(g["occ"] * (g["end"] - g["begin"]) for g in grp) / dur
        if n > 0:
            sp = sum(g["n"] * g["speed"] for g in grp if g["n"] > 0) / n
            hm = n / sum(g["n"] / g["hms"] for g in grp if g["n"] > 0 and g["hms"] > 0)
        else:
            sp = hm = -1.0
        out.append(dict(begin=grp[0]["begin"], end=grp[-1]["end"], n=n, dur=dur,
                        flow=n / dur * 3600.0, occ=occ, speed=sp, hms=hm,
                        nEnt=sum(g["nEnt"] for g in grp)))
    return out


def link_lengths():
    """effective per-link length ell_i = edge eb_i + the internal edge after it,
       so that sum(ell_i) == the EB corridor distance used in ground truth."""
    tree = ET.parse(os.path.join(SCEN, "arterial.net.xml"))
    root = tree.getroot()
    edges = {}
    for e in root.findall("edge"):
        ls = e.findall("lane")
        edges[e.get("id")] = float(ls[0].get("length")) if ls else 0.0
    ell = []
    for i in range(6):
        L = edges[f"eb_{i}"]
        if i < 5:
            # internal connector eb_i -> eb_{i+1} at J(i+1)
            cand = [v for k, v in edges.items()
                    if k.startswith(f":J{i+1}_") and not k.startswith(f":J{i+1}_c")]
            internal = 0.0
            for e in root.findall("edge"):
                if e.get("function") != "internal":
                    continue
                # find the internal edge whose lane connects eb_i to eb_{i+1}
                for lane in e.findall("lane"):
                    pass
            # simpler: derive from connection geometry via junction shape length
            internal = None
        ell.append(L)
    return ell, edges


def internal_lengths(root):
    """map (fromEdge,toEdge) -> internal edge length, from <connection via=...>"""
    lane_len = {}
    for e in root.findall("edge"):
        for lane in e.findall("lane"):
            lane_len[lane.get("id")] = float(lane.get("length"))
    out = {}
    for c in root.findall("connection"):
        via = c.get("via")
        if via and via in lane_len:
            out[(c.get("from"), c.get("to"))] = lane_len[via]
    return out


def effective_lengths():
    root = ET.parse(os.path.join(SCEN, "arterial.net.xml")).getroot()
    edges = {}
    for e in root.findall("edge"):
        ls = e.findall("lane")
        if ls and e.get("function") != "internal":
            edges[e.get("id")] = float(ls[0].get("length"))
    inter = internal_lengths(root)
    ell = []
    for i in range(6):
        L = edges[f"eb_{i}"]
        if i < 5:
            L += inter.get((f"eb_{i}", f"eb_{i+1}"), 0.0)
        ell.append(L)
    return ell


# --------------------------------------------------------- ground-truth loads
def load_gt_linkstate():
    d = {}
    for r in csv.DictReader(open(os.path.join(RES, "gt_linkstate.csv"))):
        if r["space_mean_speed"]:
            d[(int(r["bin"]), int(r["link"]))] = (float(r["space_mean_speed"]),
                                                  float(r["veh_seconds"]))
    return d


def load_gt_corridor():
    rows = []
    for r in csv.DictReader(open(os.path.join(RES, "gt_corridor.csv"))):
        if r["completed"] == "1" and r["corridor_tt"]:
            rows.append((float(r["enter"]), float(r["corridor_tt"]), r["veh"]))
    rows.sort()
    return rows


def load_gt_links():
    """(link, entry_bin) -> list of experienced link tt"""
    d = defaultdict(list)
    for r in csv.DictReader(open(os.path.join(RES, "gt_links.csv"))):
        d[(int(r["link"]), int(float(r["enter"]) // 30) * 30)].append(float(r["tt"]))
    return d


PRIMARY_Q = "max_extent_1p39"      # back-of-queue extent at the 5 km/h threshold
ALT_Q = "max_anchored_1p39"        # classic stop-bar-anchored max queue


def load_gt_queue_percycle(col=PRIMARY_Q):
    d = {}
    for r in csv.DictReader(open(os.path.join(RES, "gt_queue_percycle.csv"))):
        d[(int(r["junction"]), int(r["cycle_start"]))] = float(r[col])
    return d


def load_gt_queue_series():
    d = defaultdict(dict)
    for r in csv.DictReader(open(os.path.join(RES, "gt_queue.csv"))):
        d[int(r["junction"])][float(r["t"])] = float(r["extent_1p39"])
    return d


# ================================================================ ESTIMATOR A
def estimator_A(e1, ell, gt_ls, out):
    """corridor TT from mid-link spot speeds: time-mean vs harmonic."""
    res = {}
    for agg, factor in [(30, 1), (60, 2), (300, 10)]:
        # per link per interval: combine the two lanes
        stations = {}
        for i in range(6):
            lanes = [reaggregate(e1[f"MID_L{i}_l{ln}"], factor) for ln in range(2)]
            per = []
            for k in range(len(lanes[0])):
                n = sum(l[k]["n"] for l in lanes)
                if n == 0:
                    per.append(None); continue
                # station time-mean spot speed = count-weighted arithmetic mean
                vtm = sum(l[k]["n"] * l[k]["speed"] for l in lanes if l[k]["n"] > 0) / n
                # station space-mean speed = harmonic across all crossings
                vhm = n / sum(l[k]["n"] / l[k]["hms"] for l in lanes if l[k]["n"] > 0)
                per.append(dict(begin=lanes[0][k]["begin"], n=n, vtm=vtm, vhm=vhm))
            stations[i] = per
        rows = []
        nint = min(len(stations[i]) for i in range(6))
        for k in range(nint):
            if any(stations[i][k] is None for i in range(6)):
                continue
            b = stations[0][k]["begin"]
            tt_tm = sum(ell[i] / stations[i][k]["vtm"] for i in range(6))
            tt_hm = sum(ell[i] / stations[i][k]["vhm"] for i in range(6))
            # ground-truth INSTANTANEOUS corridor TT from true link space-mean speeds
            gsp, ok = [], True
            for i in range(6):
                acc = [(gt_ls[(bb, i)]) for bb in range(int(b), int(b) + agg, 30)
                       if (bb, i) in gt_ls]
                if not acc:
                    ok = False; break
                # veh-second-weighted harmonic combine of the 30 s true space-mean speeds
                tot = sum(a[1] for a in acc)
                gsp.append(tot / sum(a[1] / a[0] for a in acc))
            if not ok:
                continue
            tt_gt_inst = sum(ell[i] / gsp[i] for i in range(6))
            rows.append(dict(begin=b, tt_tm=tt_tm, tt_hm=tt_hm, tt_gt_inst=tt_gt_inst,
                             vtm=[stations[i][k]["vtm"] for i in range(6)],
                             vhm=[stations[i][k]["vhm"] for i in range(6)],
                             n=[stations[i][k]["n"] for i in range(6)]))
        res[agg] = rows
        # bias statistics
        d_tm = [r["tt_tm"] - r["tt_gt_inst"] for r in rows]
        d_hm = [r["tt_hm"] - r["tt_gt_inst"] for r in rows]
        d_tmhm = [r["tt_tm"] - r["tt_hm"] for r in rows]
        out[f"A_agg{agg}"] = dict(
            n_intervals=len(rows),
            mean_tt_gt_instantaneous_s=sum(r["tt_gt_inst"] for r in rows) / len(rows),
            mean_tt_timemean_s=sum(r["tt_tm"] for r in rows) / len(rows),
            mean_tt_harmonic_s=sum(r["tt_hm"] for r in rows) / len(rows),
            bias_timemean_s=sum(d_tm) / len(d_tm),
            bias_harmonic_s=sum(d_hm) / len(d_hm),
            bias_timemean_pct=100 * sum(d_tm) / sum(r["tt_gt_inst"] for r in rows),
            bias_harmonic_pct=100 * sum(d_hm) / sum(r["tt_gt_inst"] for r in rows),
            rmse_timemean_s=math.sqrt(sum(x * x for x in d_tm) / len(d_tm)),
            rmse_harmonic_s=math.sqrt(sum(x * x for x in d_hm) / len(d_hm)),
            mean_timemean_minus_harmonic_s=sum(d_tmhm) / len(d_tmhm),
            # robust statistics -- the mean/RMSE are dominated by a few intervals at
            # short aggregation, where a single near-zero crossing blows up L/v
            median_error_timemean_s=sorted(d_tm)[len(d_tm) // 2],
            median_error_harmonic_s=sorted(d_hm)[len(d_hm) // 2],
            mae_timemean_s=sum(abs(x) for x in d_tm) / len(d_tm),
            mae_harmonic_s=sum(abs(x) for x in d_hm) / len(d_hm),
            p95_abs_error_harmonic_s=sorted(abs(x) for x in d_hm)[int(0.95 * len(d_hm))],
            max_abs_error_harmonic_s=max(abs(x) for x in d_hm),
        )
    # ---- bias split by regime (free-flow vs congested), at 60 s aggregation
    rows60 = res[60]
    ff_tt = sum(ell) / V_FREE
    def reg(r):
        # regime from the TRUE instantaneous corridor TT relative to free flow
        return "congested" if r["tt_gt_inst"] > 1.5 * ff_tt else "freeflow"
    for rg in ["freeflow", "congested"]:
        sub = [r for r in rows60 if reg(r) == rg]
        if not sub:
            continue
        g = sum(r["tt_gt_inst"] for r in sub)
        out[f"A_agg60_{rg}"] = dict(
            n=len(sub),
            mean_tt_gt_s=g / len(sub),
            bias_timemean_s=sum(r["tt_tm"] - r["tt_gt_inst"] for r in sub) / len(sub),
            bias_timemean_pct=100 * sum(r["tt_tm"] - r["tt_gt_inst"] for r in sub) / g,
            bias_harmonic_s=sum(r["tt_hm"] - r["tt_gt_inst"] for r in sub) / len(sub),
            bias_harmonic_pct=100 * sum(r["tt_hm"] - r["tt_gt_inst"] for r in sub) / g,
        )
    out["A_freeflow_corridor_tt_s"] = ff_tt

    # ---- bias-vs-speed-variance test (Wardrop: v_time - v_space ~= sigma^2 / v_space)
    wr = []
    for r in res[30]:
        for i in range(6):
            vt, vs = r["vtm"][i], r["vhm"][i]
            if r["n"][i] >= 5 and vs > 0.5:
                wr.append(dict(link=i, begin=r["begin"], vtm=vt, vhm=vs,
                               diff=vt - vs, implied_var=(vt - vs) * vs, n=r["n"][i]))
    # implied speed CV from the Wardrop relation:  v_t - v_s = sigma^2 / v_s
    for x in wr:
        x["cv"] = math.sqrt(max(0.0, x["implied_var"])) / x["vhm"]
    bins = defaultdict(list)
    for x in wr:
        bins[min(9, int(x["cv"] / 0.05))].append(x)
    binned = {}
    for k in sorted(bins):
        g = bins[k]
        binned[f"cv_{0.05*k:.2f}-{0.05*(k+1):.2f}"] = dict(
            n=len(g),
            mean_cv=sum(y["cv"] for y in g) / len(g),
            mean_vhm=sum(y["vhm"] for y in g) / len(g),
            mean_speed_gap_ms=sum(y["diff"] for y in g) / len(g),
            mean_rel_tt_bias_pct=100 * sum((y["vhm"] / y["vtm"]) - 1 for y in g) / len(g))
    out["A_wardrop"] = dict(
        n=len(wr),
        mean_vtm=sum(x["vtm"] for x in wr) / len(wr),
        mean_vhm=sum(x["vhm"] for x in wr) / len(wr),
        frac_vtm_ge_vhm=sum(1 for x in wr if x["vtm"] >= x["vhm"] - 1e-9) / len(wr),
        max_diff_ms=max(x["diff"] for x in wr),
        mean_diff_ms=sum(x["diff"] for x in wr) / len(wr),
        binned_by_implied_speed_cv=binned,
    )
    with open(os.path.join(RES, "estA_speed_bias.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["begin", "link", "v_timemean", "v_harmonic", "diff", "implied_speed_var", "n"])
        for x in wr:
            w.writerow([x["begin"], x["link"], round(x["vtm"], 4), round(x["vhm"], 4),
                        round(x["diff"], 4), round(x["implied_var"], 4), x["n"]])
    with open(os.path.join(RES, "estA_corridor_tt.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["agg", "begin", "tt_timemean", "tt_harmonic", "tt_gt_instantaneous"])
        for agg, rows in res.items():
            for r in rows:
                w.writerow([agg, r["begin"], round(r["tt_tm"], 3), round(r["tt_hm"], 3),
                            round(r["tt_gt_inst"], 3)])
    return res


# ================================================================ ESTIMATOR B
def estimator_B(res_A, ell, gt_ls, gt_corr, out):
    """instantaneous vs experienced corridor travel time; hysteresis + lead/lag."""
    BINW = 60
    exp_by_bin = defaultdict(list)
    for (ent, tt, _v) in gt_corr:
        exp_by_bin[int(ent // BINW) * BINW].append(tt)
    # true instantaneous TT per 60 s bin from GT link space-mean speeds
    inst = {}
    for b in sorted(exp_by_bin):
        gsp, ok = [], True
        for i in range(6):
            acc = [gt_ls[(bb, i)] for bb in range(b, b + BINW, 30) if (bb, i) in gt_ls]
            if not acc:
                ok = False; break
            tot = sum(a[1] for a in acc)
            gsp.append(tot / sum(a[1] / a[0] for a in acc))
        if ok:
            inst[b] = sum(ell[i] / gsp[i] for i in range(6))
    # sensor-based instantaneous (harmonic) at 60 s
    sens = {int(r["begin"]): r["tt_hm"] for r in res_A[60]}

    rows = []
    for b in sorted(exp_by_bin):
        if b not in inst or len(exp_by_bin[b]) < 3:
            continue
        e = sum(exp_by_bin[b]) / len(exp_by_bin[b])
        phase = None   # assigned below, data-driven
        rows.append(dict(begin=b, inst=inst[b], exp=e, sens=sens.get(b),
                         n=len(exp_by_bin[b]), phase=phase))
    # --- DATA-DRIVEN phase labelling: a bin is "build" if the centred 5-bin slope
    #     of the TRUE experienced corridor TT is positive and TT is above the
    #     corridor median, "clear" if the slope is negative and TT above median,
    #     otherwise "offpeak".  No hand-picked congestion window.
    seq0 = sorted(rows, key=lambda r: r["begin"])
    med = sorted(r["exp"] for r in seq0)[len(seq0) // 2]
    for k, r in enumerate(seq0):
        lo, hi = max(0, k - 2), min(len(seq0) - 1, k + 2)
        slope = (seq0[hi]["exp"] - seq0[lo]["exp"]) / max(1, (seq0[hi]["begin"] - seq0[lo]["begin"]))
        r["slope"] = slope
        if r["exp"] <= med:
            r["phase"] = "offpeak"
        else:
            r["phase"] = "build" if slope > 0 else "clear"
    out["B_phase_definition"] = dict(
        method="centred 5-bin slope of true experienced corridor TT; above-median TT only",
        median_experienced_tt_s=med,
        n_build=sum(1 for r in seq0 if r["phase"] == "build"),
        n_clear=sum(1 for r in seq0 if r["phase"] == "clear"),
        n_offpeak=sum(1 for r in seq0 if r["phase"] == "offpeak"),
        build_window_s=[min((r["begin"] for r in seq0 if r["phase"] == "build"), default=None),
                        max((r["begin"] for r in seq0 if r["phase"] == "build"), default=None)],
        clear_window_s=[min((r["begin"] for r in seq0 if r["phase"] == "clear"), default=None),
                        max((r["begin"] for r in seq0 if r["phase"] == "clear"), default=None)])

    with open(os.path.join(RES, "estB_hysteresis.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["begin", "tt_instantaneous_true", "tt_experienced_true",
                    "tt_instantaneous_sensor_harmonic", "n_veh", "phase"])
        for r in rows:
            w.writerow([r["begin"], round(r["inst"], 2), round(r["exp"], 2),
                        round(r["sens"], 2) if r["sens"] else "", r["n"], r["phase"]])

    def stats(sel):
        d = [r["inst"] - r["exp"] for r in rows if r["phase"] in sel]
        e = [r["exp"] for r in rows if r["phase"] in sel]
        if not d:
            return None
        return dict(n=len(d), mean_signed_error_s=sum(d) / len(d),
                    mean_signed_error_pct=100 * sum(d) / sum(e),
                    rmse_s=math.sqrt(sum(x * x for x in d) / len(d)),
                    mean_experienced_s=sum(e) / len(e))
    out["B_instant_vs_experienced"] = dict(
        all=stats({"build", "clear", "offpeak"}),
        building=stats({"build"}), clearing=stats({"clear"}), offpeak=stats({"offpeak"}))

    # best lag: shift instantaneous series forward in time to best match experienced
    ser = {r["begin"]: r for r in rows}
    lag_scan = {}
    for lag in range(-600, 601, 60):
        d = [ser[b]["inst"] - ser[b + lag]["exp"] for b in ser if (b + lag) in ser]
        if len(d) > 20:
            lag_scan[lag] = math.sqrt(sum(x * x for x in d) / len(d))
    best = min(lag_scan, key=lag_scan.get)
    out["B_lag_scan"] = dict(rmse_by_lag_s=lag_scan, best_lag_s=best,
                             rmse_at_zero_lag=lag_scan.get(0), rmse_at_best=lag_scan[best])
    # hysteresis loop area (signed), normalised
    area = 0.0
    seq = sorted(rows, key=lambda r: r["begin"])
    for a, b in zip(seq[:-1], seq[1:]):
        area += 0.5 * (a["inst"] + b["inst"]) * (b["exp"] - a["exp"])
    out["B_hysteresis_loop_signed_area"] = area

    # ---- is the build/clear asymmetry explained by the RATE of change?  The
    #      lead/lag error of an instantaneous estimator should scale with |dTT/dt|.
    def slopestat(sel):
        g = [r for r in seq if r["phase"] in sel]
        if not g:
            return None
        return dict(n=len(g),
                    mean_abs_slope_s_per_s=sum(abs(r["slope"]) for r in g) / len(g),
                    mean_signed_slope_s_per_s=sum(r["slope"] for r in g) / len(g),
                    mean_abs_error_s=sum(abs(r["inst"] - r["exp"]) for r in g) / len(g))
    out["B_error_vs_rate_of_change"] = dict(
        building=slopestat({"build"}), clearing=slopestat({"clear"}),
        offpeak=slopestat({"offpeak"}),
        note=("errors are reported relative to the offpeak (quasi-steady) baseline "
              "offset in the report, since a non-zero steady-state offset exists"))
    return rows


# ================================================================ ESTIMATOR D
def estimator_D(e1, gt_pc, gt_series, out):
    """queue length at J3 EB: input-output counts vs occupancy threshold."""
    nl = 2
    # --- occupancy threshold calibration (choose threshold maximising balanced
    #     accuracy of the binary event "true queue reaches setback d")
    cyc_starts = sorted({c for (j, c) in gt_pc if j == 3})

    def cyc_of(t):
        return OFF_J3 + int((t - OFF_J3) // CYCLE) * CYCLE

    occ_cycle = {}   # (d, cycle_start) -> max 30 s occupancy in that cycle
    cnt_adv = {}     # (d, cycle_start) -> vehicles crossing advance det
    for d in SETBACKS:
        agg = defaultdict(float); cn = defaultdict(int)
        for ln in range(nl):
            for r in e1[f"ADV{d}_J3_l{ln}"]:
                c = cyc_of(r["begin"])
                agg[(d, c)] = max(agg[(d, c)], r["occ"])
                cn[(d, c)] += r["nEnt"]
        occ_cycle.update(agg); cnt_adv.update(cn)

    thr_scan = {}
    for thr in [10, 20, 30, 40, 50, 60, 70, 80, 90]:
        tp = fp = tn = fn = 0
        for c in cyc_starts:
            if (3, c) not in gt_pc:
                continue
            truth = gt_pc[(3, c)] >= 200.0     # true back-of-queue reaches the 200 m loop
            pred = occ_cycle.get((200, c), 0.0) >= thr
            tp += truth and pred; fp += (not truth) and pred
            tn += (not truth) and (not pred); fn += truth and (not pred)
        sens = tp / (tp + fn) if tp + fn else 0
        spec = tn / (tn + fp) if tn + fp else 0
        thr_scan[thr] = dict(sens=sens, spec=spec, bal_acc=(sens + spec) / 2,
                             tp=tp, fp=fp, tn=tn, fn=fn)
    OCC_THR = max(thr_scan, key=lambda t: thr_scan[t]["bal_acc"])
    out["D_occupancy_threshold_scan"] = dict(scan=thr_scan, chosen=OCC_THR)

    # --- occupancy estimators
    rows = []
    for c in cyc_starts:
        if (3, c) not in gt_pc:
            continue
        truth = gt_pc[(3, c)]
        # single-detector saturating estimator at each setback
        single = {}
        for d in SETBACKS:
            o = occ_cycle.get((d, c), 0.0)
            single[d] = d * min(1.0, max(0.0, o / OCC_THR))
        # ladder: deepest engulfed detector, linearly interpolated to the next one
        engulfed = [d for d in SETBACKS if occ_cycle.get((d, c), 0.0) >= OCC_THR]
        if not engulfed:
            ladder = single[SETBACKS[0]]
        else:
            dm = max(engulfed)
            nxt = next((x for x in SETBACKS if x > dm), None)
            if nxt is None:
                ladder = dm
            else:
                o = occ_cycle.get((nxt, c), 0.0)
                ladder = dm + (nxt - dm) * min(1.0, o / OCC_THR)
        rows.append(dict(cycle=c, truth=truth, ladder=ladder, **{f"occ{d}": single[d] for d in SETBACKS},
                         **{f"rawocc{d}": occ_cycle.get((d, c), 0.0) for d in SETBACKS}))

    # --- input-output cumulative-count estimator, per setback
    def io_series(d):
        tau = d / V_FREE
        adv = defaultdict(int); sb = defaultdict(int)
        for ln in range(nl):
            for r in e1[f"ADV{d}_J3_l{ln}"]:
                adv[r["begin"]] += r["nEnt"]
            for r in e1[f"SB_J3_l{ln}"]:
                sb[r["begin"]] += r["nEnt"]
        ts = sorted(set(adv) | set(sb))
        cin = cout = 0; acc = {}
        for t in ts:
            # shift the advance count forward by the free-flow travel time tau
            cin += adv.get(t, 0)
            cout += sb.get(t, 0)
            acc[t + tau] = cin - cout
        return acc

    io_all = {d: io_series(d) for d in SETBACKS}
    for r in rows:
        c = r["cycle"]
        for d in SETBACKS:
            acc = io_all[d]
            vals = [v for t, v in acc.items() if c <= t < c + CYCLE]
            q = max(vals) if vals else 0
            r[f"io{d}"] = max(0.0, q / nl * SPACING_JAM)

    hdr = ["cycle", "truth", "ladder"] + [f"occ{d}" for d in SETBACKS] + \
          [f"io{d}" for d in SETBACKS] + [f"rawocc{d}" for d in SETBACKS]
    with open(os.path.join(RES, "estD_queue.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(hdr)
        for r in rows:
            w.writerow([r["cycle"], round(r["truth"], 2)] +
                       [round(r[k], 2) for k in hdr[2:]])

    def err(key, sel=None):
        sub = [r for r in rows if sel is None or sel(r)]
        if not sub:
            return None
        d = [r[key] - r["truth"] for r in sub]
        return dict(n=len(d), bias_m=sum(d) / len(d),
                    rmse_m=math.sqrt(sum(x * x for x in d) / len(d)),
                    mean_truth_m=sum(r["truth"] for r in sub) / len(sub))
    congested = lambda r: r["truth"] >= 150.0
    free = lambda r: r["truth"] < 60.0
    out["D_queue_estimators"] = {
        "all_cycles": {k: err(k) for k in ["ladder"] + [f"occ{d}" for d in SETBACKS] +
                       [f"io{d}" for d in SETBACKS]},
        "congested_cycles_truth_ge_150m": {k: err(k, congested) for k in
                                           ["ladder"] + [f"occ{d}" for d in SETBACKS] +
                                           [f"io{d}" for d in SETBACKS]},
        "freeflow_cycles_truth_lt_60m": {k: err(k, free) for k in
                                         ["ladder"] + [f"occ{d}" for d in SETBACKS] +
                                         [f"io{d}" for d in SETBACKS]},
        "n_cycles": len(rows),
        "n_congested": sum(1 for r in rows if congested(r)),
        "n_free": sum(1 for r in rows if free(r)),
    }

    # --- BLIND-SPOT HYPOTHESIS: does occupancy-based estimation saturate once the
    #     queue passes the advance detector?
    blind = {}
    for d in SETBACKS:
        engulf = [r for r in rows if r["truth"] > d]
        notyet = [r for r in rows if r["truth"] <= d]
        est_e = [r[f"occ{d}"] for r in engulf]
        blind[d] = dict(
            n_cycles_queue_exceeds_setback=len(engulf),
            frac_cycles_exceeding=len(engulf) / len(rows),
            mean_true_queue_when_exceeding_m=(sum(r["truth"] for r in engulf) / len(engulf))
                                             if engulf else None,
            mean_occ_estimate_when_exceeding_m=(sum(est_e) / len(est_e)) if est_e else None,
            frac_estimates_pinned_at_setback=(sum(1 for x in est_e if x >= d - 1e-6) /
                                              len(est_e)) if est_e else None,
            mean_underestimate_m=(sum(r["truth"] - r[f"occ{d}"] for r in engulf) / len(engulf))
                                 if engulf else None,
            rmse_when_not_exceeding_m=(math.sqrt(sum((r[f"occ{d}"] - r["truth"]) ** 2
                                        for r in notyet) / len(notyet))) if notyet else None,
            detector_never_occupied_frac=sum(1 for r in rows if r[f"rawocc{d}"] < OCC_THR) / len(rows),
        )
    out["D_blind_spot_hypothesis"] = blind
    return rows


# =================================================== FINE POSITIONING ANALYSIS
def fine_positioning(e1, gt_pc, occ_thr, out):
    """Does occupancy-based queue detection depend on WHERE, to the metre, the loop
    sits?  A point loop in a standing queue is covered only if a vehicle body spans
    it; with a stable queue geometry the same loop can land in the recurring
    inter-vehicle gap cycle after cycle.  The 1 m ladder (setbacks 60..260 m on the
    J3 EB approach) measures this directly."""
    cyc = sorted({c for (j, c) in gt_pc if j == 3})
    # cycles in which the true back-of-queue is well past the whole ladder
    deep = [c for c in cyc if gt_pc[(3, c)] >= 300.0]
    rows = []
    for d in range(60, 261):
        vals = []
        for ln in range(2):
            key = f"FINE{d}_J3_l{ln}"
            if key not in e1:
                continue
            per = defaultdict(float)
            for r in e1[key]:
                cc = OFF_J3 + int((r["begin"] - OFF_J3) // CYCLE) * CYCLE
                per[cc] = max(per[cc], r["occ"])
            vals.append(per)
        if not vals:
            continue
        occ_deep = [max(v.get(c, 0.0) for v in vals) for c in deep]
        rows.append(dict(setback=d,
                         mean_max_occ_deep_cycles=sum(occ_deep) / len(occ_deep),
                         frac_deep_cycles_detected=sum(1 for x in occ_deep if x >= occ_thr) / len(occ_deep)))
    with open(os.path.join(RES, "estD_fine_positioning.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["setback_m", "mean_max_occupancy_pct_deep_cycles",
                    "frac_deep_cycles_detected_at_threshold"])
        for r in rows:
            w.writerow([r["setback"], round(r["mean_max_occ_deep_cycles"], 2),
                        round(r["frac_deep_cycles_detected"], 3)])
    occs = [r["mean_max_occ_deep_cycles"] for r in rows]
    dets = [r["frac_deep_cycles_detected"] for r in rows]
    # largest swing between loops <= 5 m apart, on cycles where the queue is
    # unambiguously past every loop in the ladder
    swings = []
    for a, b in zip(rows[:-1], rows[1:]):
        swings.append((abs(a["mean_max_occ_deep_cycles"] - b["mean_max_occ_deep_cycles"]),
                       a["setback"], b["setback"]))
    big = max(swings)
    out["D_fine_positioning"] = dict(
        n_deep_cycles=len(deep),
        deep_cycle_criterion_m=300.0,
        n_positions=len(rows),
        occupancy_range_over_ladder=[min(occs), max(occs)],
        mean_occupancy=sum(occs) / len(occs),
        frac_positions_detecting_all_deep_cycles=sum(1 for x in dets if x >= 0.999) / len(dets),
        frac_positions_detecting_no_deep_cycle=sum(1 for x in dets if x <= 0.001) / len(dets),
        largest_1m_step_occupancy_swing_pct=big[0],
        largest_1m_step_between_setbacks_m=[big[1], big[2]],
        threshold_used_pct=occ_thr,
    )
    return rows


def main():
    e1 = load_e1()
    ell = effective_lengths()
    out = {"corridor_link_lengths_m": [round(x, 2) for x in ell],
           "corridor_length_m": round(sum(ell), 2)}

    # --- verify offline re-aggregation against SUMO's native 300 s detectors
    checks = []
    for i in range(6):
        for ln in range(2):
            off = reaggregate(e1[f"MID_L{i}_l{ln}"], 10)
            nat = e1[f"MIDNAT_L{i}_l{ln}"]
            for a, b in zip(off, nat):
                checks.append((abs(a["n"] - b["n"]), abs(a["occ"] - b["occ"]),
                               abs(a["speed"] - b["speed"]) if b["n"] > 0 else 0.0,
                               abs(a["hms"] - b["hms"]) if b["n"] > 0 else 0.0))
    out["reaggregation_check_vs_native_300s"] = dict(
        n_compared=len(checks),
        max_abs_count_diff=max(c[0] for c in checks),
        max_abs_occupancy_diff=max(c[1] for c in checks),
        max_abs_timemean_speed_diff=max(c[2] for c in checks),
        max_abs_harmonic_speed_diff=max(c[3] for c in checks))
    print("re-aggregation check:", out["reaggregation_check_vs_native_300s"])

    gt_ls = load_gt_linkstate()
    gt_corr = load_gt_corridor()
    res_A = estimator_A(e1, ell, gt_ls, out)
    print("A(60s): time-mean bias %.2f s (%.1f%%), harmonic bias %.2f s (%.1f%%)" % (
        out["A_agg60"]["bias_timemean_s"], out["A_agg60"]["bias_timemean_pct"],
        out["A_agg60"]["bias_harmonic_s"], out["A_agg60"]["bias_harmonic_pct"]))
    estimator_B(res_A, ell, gt_ls, gt_corr, out)
    print("B: build err %.1f s, clear err %.1f s, best lag %d s" % (
        out["B_instant_vs_experienced"]["building"]["mean_signed_error_s"],
        out["B_instant_vs_experienced"]["clearing"]["mean_signed_error_s"],
        out["B_lag_scan"]["best_lag_s"]))
    gt_pc = load_gt_queue_percycle()
    gt_se = load_gt_queue_series()
    estimator_D(e1, gt_pc, gt_se, out)
    print("D: chosen occupancy threshold =", out["D_occupancy_threshold_scan"]["chosen"], "%")
    fine_positioning(e1, gt_pc, out["D_occupancy_threshold_scan"]["chosen"], out)
    fp = out["D_fine_positioning"]
    print(f"   fine ladder: occupancy over 201 positions ranges "
          f"{fp['occupancy_range_over_ladder'][0]:.1f}..{fp['occupancy_range_over_ladder'][1]:.1f}%, "
          f"{100*fp['frac_positions_detecting_no_deep_cycle']:.1f}% of positions NEVER detect a "
          f"deep queue; largest 1 m swing {fp['largest_1m_step_occupancy_swing_pct']:.1f} pp")
    for d in SETBACKS:
        b = out["D_blind_spot_hypothesis"][d]
        print(f"   setback {d:3d} m: cycles exceeded={b['n_cycles_queue_exceeds_setback']:3d} "
              f"pinned={b['frac_estimates_pinned_at_setback']} "
              f"underest={b['mean_underestimate_m']}")

    json.dump(out, open(os.path.join(RES, "e1_estimators.json"), "w"), indent=1, default=str)
    print("wrote", os.path.join(RES, "e1_estimators.json"))


if __name__ == "__main__":
    main()
