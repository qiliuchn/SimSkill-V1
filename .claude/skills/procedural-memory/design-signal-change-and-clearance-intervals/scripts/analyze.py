"""Load every sweep cell, build the H1-H6 tests, decision curves and Pareto frontier."""
import csv
import glob
import json
import math
import os
import statistics as st
from collections import Counter, defaultdict

from common import ANA_DIR, RUN_DIR, FIG_DIR
import analytic
import stats_util as SU

GO = {"CLEARED_ON_YELLOW", "RED_RUN"}
STOPS = {"STOPPED_CLEAN", "STOPPED_HARD", "STOPPED_SEVERE",
         "STOPPED_CLEAN_NOSTOP", "STOPPED_HARD_NOSTOP", "STOPPED_SEVERE_NOSTOP"}
HARD = 3.0
SEVERE = 4.5


def load_runs(prefix):
    out = []
    for p in sorted(glob.glob(os.path.join(RUN_DIR, prefix + "*", "metrics.json"))):
        d = json.load(open(p))
        d["_dir"] = os.path.dirname(p)
        out.append(d)
    return out


def load_log(rundir):
    p = os.path.join(rundir, "decision_log.csv")
    if not os.path.exists(p):
        return []
    rows = []
    for r in csv.DictReader(open(p)):
        for k in ("dist0", "speed0", "maxdecel", "maxdecel_resp", "stop_dist", "ttsl"):
            r[k] = float(r[k]) if r[k] not in ("", None) else None
        rows.append(r)
    return rows


def classify_collisions(rundir, warmup=240.0, arm_len=390.0):
    """Split the collision log by mechanism. Collisions on an approach lane at a position
    close to the upstream (fringe) end are INSERTION artifacts, not signal-related, and are
    reported separately rather than folded into the safety metric."""
    p = os.path.join(rundir, "collisions.xml")
    out = dict(n_total=0, n_junction=0, n_approach=0, n_insertion=0, n_after_warmup=0,
               junction_involving_nc=0, records=[])
    if not os.path.exists(p):
        return out
    import xml.etree.ElementTree as ET
    try:
        for _, el in ET.iterparse(p, events=("end",)):
            if el.tag != "collision":
                continue
            t = float(el.get("time"))
            lane = el.get("lane") or ""
            pos = float(el.get("pos", 0))
            out["n_total"] += 1
            if t >= warmup:
                out["n_after_warmup"] += 1
            if lane.startswith(":"):
                out["n_junction"] += 1
                if "_nc" in (el.get("colliderType", "") + el.get("victimType", "")):
                    out["junction_involving_nc"] += 1
                out["records"].append(dict(t=t, lane=lane, pos=pos,
                                           collider=el.get("collider"),
                                           victim=el.get("victim"),
                                           ctype=el.get("colliderType"),
                                           vtype=el.get("victimType"),
                                           kind="junction"))
            elif pos > arm_len - 40:
                out["n_insertion"] += 1
            else:
                out["n_approach"] += 1
            el.clear()
    except ET.ParseError:
        pass
    return out


def run_key(d):
    c = d["cfg"]
    return dict(driver=c.get("_driver"), y=c.get("yellow"), ar=c.get("allred"),
                v=c.get("_v"), dem=c.get("_dem"), seed=c.get("seed"),
                lanes=c.get("_lanes"), W=c.get("_W"), truck=c.get("_truck"),
                grade=c.get("_grade"), ttt=c.get("_ttt"), sweep=c.get("_sweep"))


def per_run_stats(d):
    """Every per-run quantity used downstream, computed once."""
    k = run_key(d)
    rows = load_log(d["_dir"])
    m, s = d["metrics"], d["ssm"]
    n = len(rows)
    oc = Counter(r["outcome"] for r in rows)
    ngo = sum(oc[o] for o in GO)
    nred = oc["RED_RUN"]
    nstop = sum(v for o, v in oc.items() if o in STOPS)
    hard = sum(1 for r in rows if (r["maxdecel_resp"] or 0) >= HARD)
    sev = sum(1 for r in rows if (r["maxdecel_resp"] or 0) >= SEVERE)
    veh = (m["completed"] or 0) + (m["still_running_at_end"] or 0)
    k.update(
        n_decision=n, n_go=ngo, n_red=nred, n_stop=nstop,
        n_hard=hard, n_severe=sev,
        rlr_per_1000_decisions=1000.0 * nred / n if n else None,
        rlr_per_1000_veh=1000.0 * nred / veh if veh else None,
        hard_per_1000_decisions=1000.0 * hard / n if n else None,
        severe_per_1000_decisions=1000.0 * sev / n if n else None,
        # rear-end conflict rate from the SSM device, exposure-normalised
        rear_ttc15_per_1000_veh=1000.0 * s["ttc_lt_15"] / veh if veh else None,
        rear_conf_per_1000_veh=1000.0 * s["n_rear"] / veh if veh else None,
        br_gt3_frac=s["n_br_gt_3"] / s["n_veh_global"] if s["n_veh_global"] else None,
        max_drac=s["max_drac"], min_ttc=s["min_ttc"],
        # right-angle exposure
        jpet_overlap=d["jpet_overlap"], jpet_lt_1=d["jpet_lt_1"], jpet_lt_2=d["jpet_lt_2"],
        jpet_min=d["jpet_min"], jpet_passages=d["jpet_passages"],
        overlap_per_1000_veh=1000.0 * d["jpet_overlap"] / veh if veh else None,
        jpet_lt1_per_1000_veh=1000.0 * d["jpet_lt_1"] / veh if veh else None,
        # efficiency
        completed=m["completed"], still_running=m["still_running_at_end"],
        mean_timeloss=m["mean_timeloss"], mean_duration=m["mean_duration"],
        timeloss_robust=m["mean_timeloss_censoring_robust"],
        teleports=m["teleports"], collisions=m["collision_records"],
        collision_junction=m["collision_junction"],
        emg_stop_red=m.get("emg_stop_red"), emg_brake=m.get("emg_brake"),
        emg_stop_max_decel=m.get("emg_stop_max_decel"),
        stat_emergencyStops=m.get("stat_emergencyStops"),
        truck_share_realized=m.get("realized_truck_share"),
        noncomp_share_realized=m.get("realized_noncomp_share"),
    )
    cc = classify_collisions(d["_dir"])
    k.update(col_total=cc["n_total"], col_junction=cc["n_junction"],
             col_approach=cc["n_approach"], col_insertion=cc["n_insertion"],
             col_junction_nc=cc["junction_involving_nc"],
             col_junction_per_1000_veh=1000.0 * cc["n_junction"] / veh if veh else None)
    k["_collision_records"] = cc["records"]
    return k, rows


def group(runs, keys):
    g = defaultdict(list)
    for r in runs:
        g[tuple(r[k] for k in keys)].append(r)
    return g


def agg(cells, metric):
    """Mean + 95% t-CI over the CRN seed replications of one cell."""
    return SU.mean_ci([c[metric] for c in cells])


def seed_vector(cells, metric):
    return [c[metric] for c in sorted(cells, key=lambda x: x["seed"])]


# ----------------------------------------------------------------- stop/go curve

def stopgo_curve(rows, bin_m=5.0, dmax=200.0):
    b = defaultdict(lambda: [0, 0])
    for r in rows:
        d = r["dist0"]
        if d is None or d < 0 or d > dmax:
            continue
        if r["outcome"] not in GO | STOPS:
            continue
        i = int(d // bin_m)
        b[i][1] += 1
        if r["outcome"] in GO:
            b[i][0] += 1
    out = []
    for i in sorted(b):
        k, n = b[i]
        p, lo, hi = SU.wilson(k, n)
        out.append(dict(d_lo=i * bin_m, d_mid=(i + 0.5) * bin_m, d_hi=(i + 1) * bin_m,
                        n=n, k_go=k, p_go=p, ci_lo=lo, ci_hi=hi))
    return out


def indecision_zone(curve, plo=0.05, phi=0.95, nmin=8):
    """Distance range over which the go-probability is strictly between plo and phi."""
    ds = [c["d_mid"] for c in curve if c["n"] >= nmin and plo < c["p_go"] < phi]
    if not ds:
        return dict(lo=None, hi=None, width=0.0, n_bins=0)
    return dict(lo=min(ds), hi=max(ds), width=max(ds) - min(ds), n_bins=len(ds))


def main():
    res = {}
    # sweep G (saturated demand) shares sweep A's shape and is analysed with it
    runsA = [per_run_stats(d) for d in load_runs("A_")] + \
            [per_run_stats(d) for d in load_runs("G_")]
    runsA2 = [per_run_stats(d) for d in load_runs("A2_")]
    runsB = [per_run_stats(d) for d in load_runs("B_")]
    runsC = [per_run_stats(d) for d in load_runs("C_")]
    runsF = [per_run_stats(d) for d in load_runs("F_")]
    print("loaded A=%d A2=%d B=%d C=%d F=%d" % (len(runsA), len(runsA2), len(runsB),
                                                len(runsC), len(runsF)))
    statsA = [r for r, _ in runsA]
    res["n_runs"] = dict(A=len(runsA), A2=len(runsA2), B=len(runsB), C=len(runsC), F=len(runsF))

    # ---------- validity: teleports / still-running / collisions across ALL runs ----------
    allr = [r for r, _ in runsA + runsA2 + runsB + runsC + runsF]
    res["validity"] = dict(
        n_runs=len(allr),
        total_teleports=sum(r["teleports"] or 0 for r in allr),
        runs_with_teleport=sum(1 for r in allr if (r["teleports"] or 0) > 0),
        total_still_running=sum(r["still_running"] or 0 for r in allr),
        runs_with_still_running=sum(1 for r in allr if (r["still_running"] or 0) > 0),
        max_still_running_frac=max(((r["still_running"] or 0) /
                                    max(1, (r["completed"] or 0) + (r["still_running"] or 0)))
                                   for r in allr),
        total_collisions=sum(r["collisions"] or 0 for r in allr),
        total_junction_collisions=sum(r["collision_junction"] or 0 for r in allr),
        runs_with_collision=sum(1 for r in allr if (r["collisions"] or 0) > 0),
        total_emergency_stops_red=sum(r["emg_stop_red"] or 0 for r in allr),
        collisions_junction=sum(r["col_junction"] or 0 for r in allr),
        collisions_approach=sum(r["col_approach"] or 0 for r in allr),
        collisions_insertion_artifact=sum(r["col_insertion"] or 0 for r in allr),
        junction_collisions_involving_noncompliant=sum(r["col_junction_nc"] or 0
                                                       for r in allr),
        max_emergency_stop_decel=max((r["emg_stop_max_decel"] or 0) for r in allr),
    )

    # ---------- H1: dilemma zone existence, RLR vs speed and yellow ----------
    h1 = {}
    for (drv, v, dem), cells in group(statsA, ["driver", "v", "dem"]).items():
        by_y = group(cells, ["y"])
        row = {}
        for (y,), cs in sorted(by_y.items()):
            an_def = analytic.zone(v, y, 1.0, 20.8, t_pr=0.0, a=4.5)
            an_ite = analytic.zone(v, y, 1.0, 20.8, t_pr=1.0, a=3.05)
            row[y] = dict(
                rlr_per_1000_veh=agg(cs, "rlr_per_1000_veh"),
                rlr_per_1000_dec=agg(cs, "rlr_per_1000_decisions"),
                n_red_total=sum(c["n_red"] for c in cs),
                n_decision_total=sum(c["n_decision"] for c in cs),
                hard_per_1000_dec=agg(cs, "hard_per_1000_decisions"),
                severe_per_1000_dec=agg(cs, "severe_per_1000_decisions"),
                emg_stop_red=agg(cs, "emg_stop_red"),
                overlap_per_1000_veh=agg(cs, "overlap_per_1000_veh"),
                jpet_lt1_per_1000_veh=agg(cs, "jpet_lt1_per_1000_veh"),
                rear_ttc15_per_1000_veh=agg(cs, "rear_ttc15_per_1000_veh"),
                rear_conf_per_1000_veh=agg(cs, "rear_conf_per_1000_veh"),
                mean_timeloss=agg(cs, "mean_timeloss"),
                completed=agg(cs, "completed"),
                collisions=agg(cs, "collisions"),
                col_junction_per_1000_veh=agg(cs, "col_junction_per_1000_veh"),
                col_insertion=agg(cs, "col_insertion"),
                analytic_sumo_default=dict(x_s=an_def["x_s"], x_c=an_def["x_c"],
                                           zone=an_def["zone_type"],
                                           width=an_def["zone_width"]),
                analytic_ite=dict(x_s=an_ite["x_s"], x_c=an_ite["x_c"],
                                  zone=an_ite["zone_type"], width=an_ite["zone_width"]),
                ite_yellow=analytic.ite_yellow(v),
            )
        h1["%s|v=%.2f|%s" % (drv, v, dem)] = row
    res["H1"] = h1

    # H1 speed gradient at a below-ITE yellow, and CRN-paired ITE-yellow vs short yellow
    grad = {}
    for drv in ("DEF", "ITE"):
        for dem in ("low", "high"):
            pts = []
            for v in (13.89, 19.44, 25.0):
                cs = [r for r in statsA if r["driver"] == drv and r["v"] == v
                      and r["dem"] == dem and r["y"] == 2.0]
                if cs:
                    pts.append((v, agg(cs, "rlr_per_1000_veh")))
            grad["%s|%s|y=2" % (drv, dem)] = [(v, a["mean"], a["hw"]) for v, a in pts]
            # paired: ITE-formula yellow vs y=2 at each speed
            for v in (13.89, 19.44, 25.0):
                yite = min((2.0, 3.0, 4.0, 5.0, 6.0),
                           key=lambda yy: abs(yy - analytic.ite_yellow(v)))
                a2 = [r for r in statsA if r["driver"] == drv and r["v"] == v
                      and r["dem"] == dem and r["y"] == 2.0]
                ai = [r for r in statsA if r["driver"] == drv and r["v"] == v
                      and r["dem"] == dem and r["y"] == yite]
                if a2 and ai:
                    grad["paired_%s|%s|v=%.2f_y2_vs_y%.1f" % (drv, dem, v, yite)] = SU.paired(
                        seed_vector(a2, "rlr_per_1000_veh"),
                        seed_vector(ai, "rlr_per_1000_veh"))
    res["H1_speed_gradient"] = grad

    # ---------- stop/go curves ----------
    curves = {}
    bykey = defaultdict(list)
    for r, rows in runsA:
        if r["dem"] != "low":
            continue
        bykey[(r["driver"], r["v"], r["y"])] += rows
    for (drv, v, y), rows in sorted(bykey.items()):
        c = stopgo_curve(rows)
        iz = indecision_zone(c)
        curves["%s|v=%.2f|y=%.1f" % (drv, v, y)] = dict(
            curve=c, indecision=iz, n=len(rows),
            x_s_sumo_kinematic=analytic.x_stop(v, 0.0, 4.5 if drv == "DEF" else 3.05),
            x_s_ite=analytic.x_stop(v, 1.0, 3.05),
            x_c_stopline=v * y,
            analytic_zone_default=analytic.zone(v, y, 1.0, 20.8, 0.0, 4.5),
            analytic_zone_ite=analytic.zone(v, y, 1.0, 20.8, 1.0, 3.05))
    res["stopgo_curves"] = curves

    # ---------- H2: non-monotonicity in yellow ----------
    h2 = {}
    for (drv, v, dem), cells in group(statsA, ["driver", "v", "dem"]).items():
        ys = sorted(set(c["y"] for c in cells))
        seq = {}
        for m in ("rear_ttc15_per_1000_veh", "rear_conf_per_1000_veh",
                  "hard_per_1000_decisions", "severe_per_1000_decisions",
                  "overlap_per_1000_veh", "jpet_lt1_per_1000_veh",
                  "rlr_per_1000_veh", "mean_timeloss", "completed", "br_gt3_frac",
                  "col_junction_per_1000_veh"):
            seq[m] = [(y, agg([c for c in cells if c["y"] == y], m)) for y in ys]
        # argmin / monotonicity verdicts
        verdict = {}
        for m, sq in seq.items():
            vals = [(y, a["mean"]) for y, a in sq if a["mean"] is not None]
            if len(vals) < 3:
                continue
            ymin = min(vals, key=lambda t: t[1])
            ymax = max(vals, key=lambda t: t[1])
            diffs = [vals[i + 1][1] - vals[i][1] for i in range(len(vals) - 1)]
            mono_inc = all(d >= 0 for d in diffs)
            mono_dec = all(d <= 0 for d in diffs)
            verdict[m] = dict(argmin_y=ymin[0], min=ymin[1], argmax_y=ymax[0], max=ymax[1],
                              monotone_increasing=mono_inc, monotone_decreasing=mono_dec,
                              interior_min=(ymin[0] not in (vals[0][0], vals[-1][0])))
            # is the interior minimum significant vs both endpoints? (CRN paired)
            if verdict[m]["interior_min"]:
                cm = [c for c in cells if c["y"] == ymin[0]]
                for endp in (vals[0][0], vals[-1][0]):
                    ce = [c for c in cells if c["y"] == endp]
                    verdict[m]["paired_vs_y%.1f" % endp] = SU.paired(
                        seed_vector(cm, m), seed_vector(ce, m))
        # explicit CRN-paired endpoint contrasts for EVERY metric (shortest vs longest
        # yellow, and shortest vs the ITE-formula yellow), regardless of monotonicity
        yite = min(ys, key=lambda yy: abs(yy - analytic.ite_yellow(v)))
        endp = {}
        c_lo = [c for c in cells if c["y"] == ys[0]]
        c_hi = [c for c in cells if c["y"] == ys[-1]]
        c_ite = [c for c in cells if c["y"] == yite]
        for m in seq:
            endp[m] = dict(
                y_lo=ys[0], y_hi=ys[-1], y_ite=yite,
                lo_to_hi=SU.paired(seed_vector(c_lo, m), seed_vector(c_hi, m)),
                lo_to_ite=SU.paired(seed_vector(c_lo, m), seed_vector(c_ite, m)))
        h2["%s|v=%.2f|%s" % (drv, v, dem)] = dict(series={k: [(y, a) for y, a in sq]
                                                          for k, sq in seq.items()},
                                                  verdict=verdict, endpoints=endp)
    res["H2"] = h2

    # ---------- non-compliance decomposition (A2) ----------
    a2 = {}
    for (drv,), cells in group([r for r, _ in runsA2], ["driver"]).items():
        ys = sorted(set(c["y"] for c in cells))
        a2[drv] = {("y%.1f" % y): dict(
            rlr_per_1000_veh=agg([c for c in cells if c["y"] == y], "rlr_per_1000_veh"),
            hard_per_1000_dec=agg([c for c in cells if c["y"] == y], "hard_per_1000_decisions"),
            emg_stop_red=agg([c for c in cells if c["y"] == y], "emg_stop_red"),
            overlap_per_1000_veh=agg([c for c in cells if c["y"] == y], "overlap_per_1000_veh"),
            mean_timeloss=agg([c for c in cells if c["y"] == y], "mean_timeloss"),
            collisions=agg([c for c in cells if c["y"] == y], "collisions"),
            noncomp_share_realized=agg([c for c in cells if c["y"] == y],
                                       "noncomp_share_realized"),
        ) for y in ys}
    res["A2_noncompliance"] = a2

    # ---------- H4: all-red exchange rate ----------
    h4 = {}
    for (v, lanes), cells in group([r for r, _ in runsB], ["v", "lanes"]).items():
        ars = sorted(set(c["ar"] for c in cells))
        W = cells[0]["W"]
        row = dict(W=W, ite_allred=analytic.ite_allred(v, W),
                   ite_yellow=analytic.ite_yellow(v), series={})
        for m in ("overlap_per_1000_veh", "jpet_lt1_per_1000_veh", "rlr_per_1000_veh",
                  "mean_timeloss", "completed", "collisions", "rear_ttc15_per_1000_veh",
                  "hard_per_1000_decisions", "col_junction_per_1000_veh"):
            row["series"][m] = [(ar, agg([c for c in cells if c["ar"] == ar], m))
                                for ar in ars]
        # marginal exchange rate per second of all-red (CRN paired, successive)
        row["marginal"] = {}
        for i in range(len(ars) - 1):
            a0, a1 = ars[i], ars[i + 1]
            c0 = [c for c in cells if c["ar"] == a0]
            c1 = [c for c in cells if c["ar"] == a1]
            row["marginal"]["%.0f->%.0f" % (a0, a1)] = dict(
                d_overlap=SU.paired(seed_vector(c0, "overlap_per_1000_veh"),
                                    seed_vector(c1, "overlap_per_1000_veh")),
                d_jpet_lt1=SU.paired(seed_vector(c0, "jpet_lt1_per_1000_veh"),
                                     seed_vector(c1, "jpet_lt1_per_1000_veh")),
                d_timeloss=SU.paired(seed_vector(c0, "mean_timeloss"),
                                     seed_vector(c1, "mean_timeloss")),
                d_completed=SU.paired(seed_vector(c0, "completed"),
                                      seed_vector(c1, "completed")))
        # exchange rate: right-angle overlaps avoided per second of all-red, against the
        # delay each second costs -- and the break-even, i.e. how many overlaps must be
        # worth one vehicle-second of delay for that step to pay
        row["exchange"] = {}
        for st, d in row["marginal"].items():
            do = d["d_overlap"]["diff"]
            dt = d["d_timeloss"]["diff"]
            row["exchange"][st] = dict(
                overlaps_avoided_per_1000veh=(-do if do is not None else None),
                delay_cost_s_per_veh=dt,
                overlaps_avoided_per_second_of_delay=((-do / dt) if (do is not None
                                                                     and dt) else None),
                significant_safety_gain=d["d_overlap"].get("sig"))
        h4["v=%.2f|lanes=%d" % (v, lanes)] = row
    res["H4"] = h4

    # ---------- H5: trucks and grade ----------
    h5 = {}
    for (ts, g, y), cells in group([r for r, _ in runsC], ["truck", "grade", "y"]).items():
        h5["t=%.2f|g=%+.0f|y=%.1f" % (ts, g, y)] = {
            m: agg(cells, m) for m in
            ("rlr_per_1000_veh", "hard_per_1000_decisions", "severe_per_1000_decisions",
             "overlap_per_1000_veh", "mean_timeloss", "completed", "emg_stop_red",
             "truck_share_realized", "collisions")}
    # CRN-paired truck and grade main effects at each yellow
    h5p = {}
    cc = [r for r, _ in runsC]
    for y in (3.0, 5.0):
        for m in ("rlr_per_1000_veh", "hard_per_1000_decisions", "emg_stop_red",
                  "mean_timeloss"):
            a = [c for c in cc if c["truck"] == 0.0 and c["grade"] == 0.0 and c["y"] == y]
            bt = [c for c in cc if c["truck"] == 0.30 and c["grade"] == 0.0 and c["y"] == y]
            bg = [c for c in cc if c["truck"] == 0.0 and c["grade"] == -4.0 and c["y"] == y]
            bb = [c for c in cc if c["truck"] == 0.30 and c["grade"] == -4.0 and c["y"] == y]
            if a and bt:
                h5p["y%.1f|%s|truck_effect" % (y, m)] = SU.paired(
                    seed_vector(a, m), seed_vector(bt, m))
            if a and bg:
                h5p["y%.1f|%s|grade_effect" % (y, m)] = SU.paired(
                    seed_vector(a, m), seed_vector(bg, m))
            if a and bb:
                h5p["y%.1f|%s|both" % (y, m)] = SU.paired(
                    seed_vector(a, m), seed_vector(bb, m))
    res["H5"] = dict(cells=h5, paired=h5p)
    # truck stop/go curves
    tcurves = {}
    bykey = defaultdict(list)
    for r, rows in runsC:
        bykey[(r["truck"], r["grade"], r["y"])] += rows
    for (ts, g, y), rows in sorted(bykey.items()):
        for vt in ("car", "truck"):
            sub = [x for x in rows if x["vtype"].startswith(vt)]
            if len(sub) < 30:
                continue
            tcurves["t%.2f|g%+.0f|y%.1f|%s" % (ts, g, y, vt)] = dict(
                curve=stopgo_curve(sub), indecision=indecision_zone(stopgo_curve(sub)),
                n=len(sub))
    res["H5_curves"] = tcurves

    # ---------- H6: capacity-optimal vs safety-optimal ----------
    h6 = {}
    for (drv, v, dem), cells in group(statsA, ["driver", "v", "dem"]).items():
        ys = sorted(set(c["y"] for c in cells))
        cap = [(y, agg([c for c in cells if c["y"] == y], "mean_timeloss")) for y in ys]
        thr = [(y, agg([c for c in cells if c["y"] == y], "completed")) for y in ys]
        # composite safety index: normalised sum of RLR, right-angle overlap, rear-end TTC<1.5
        # Composite safety index: each component is scaled by its own maximum ACROSS the
        # yellow sweep of this cell, so the index is comparable WITHIN a cell only.
        # Components that are identically zero across the whole sweep (e.g. red-light
        # running under the compliant SUMO-default fleet) are DEGENERATE and are dropped
        # rather than contributing a constant zero, which would otherwise dilute the index.
        WEIGHTS = {"rlr_per_1000_veh": 1.0, "overlap_per_1000_veh": 3.0,
                   "col_junction_per_1000_veh": 3.0,
                   "rear_ttc15_per_1000_veh": 1.0, "hard_per_1000_decisions": 1.0}
        comp, degenerate = {}, []
        for m in WEIGHTS:
            vals = [(y, agg([c for c in cells if c["y"] == y], m)["mean"]) for y in ys]
            mx = max((x for _, x in vals if x is not None), default=0)
            if not mx:
                degenerate.append(m)
                continue
            comp[m] = [(y, (x / mx if x is not None else None)) for y, x in vals]
        safety, safety_w = [], []
        for i, y in enumerate(ys):
            parts = [(comp[m][i][1], WEIGHTS[m]) for m in comp if comp[m][i][1] is not None]
            safety.append((y, sum(p for p, _ in parts) / len(parts) if parts else None))
            wsum = sum(w for _, w in parts)
            safety_w.append((y, sum(p * w for p, w in parts) / wsum if wsum else None))
        capv = [(y, a["mean"]) for y, a in cap if a["mean"] is not None]
        h6["%s|v=%.2f|%s" % (drv, v, dem)] = dict(
            capacity_optimal_y=min(capv, key=lambda t: t[1])[0] if capv else None,
            timeloss_by_y=capv,
            throughput_by_y=[(y, a["mean"]) for y, a in thr],
            safety_index_by_y=safety,
            safety_optimal_y=min([s for s in safety if s[1] is not None],
                                 key=lambda t: t[1])[0] if any(s[1] is not None
                                                               for s in safety) else None,
            safety_index_weighted_by_y=safety_w,
            safety_optimal_y_weighted=min([s for s in safety_w if s[1] is not None],
                                          key=lambda t: t[1])[0] if any(
                                              s[1] is not None for s in safety_w) else None,
            degenerate_components=degenerate,
            components={m: comp[m] for m in comp})
    res["H6"] = h6

    # ---------- Pareto frontier over (yellow, all-red) from sweep B ----------
    par = {}
    for (v, lanes), cells in group([r for r, _ in runsB], ["v", "lanes"]).items():
        pts = []
        for ar in sorted(set(c["ar"] for c in cells)):
            cs = [c for c in cells if c["ar"] == ar]
            pts.append(dict(y=cs[0]["y"], ar=ar,
                            timeloss=agg(cs, "mean_timeloss")["mean"],
                            completed=agg(cs, "completed")["mean"],
                            overlap=agg(cs, "overlap_per_1000_veh")["mean"],
                            jpet_lt1=agg(cs, "jpet_lt1_per_1000_veh")["mean"],
                            rlr=agg(cs, "rlr_per_1000_veh")["mean"]))
        par["v=%.2f|lanes=%d" % (v, lanes)] = pts
    res["pareto_B"] = par
    # (yellow, all-red) joint frontier -- sweep A gives the yellow axis at ar=1
    joint = {}
    for (drv, v, dem), cells in group(statsA, ["driver", "v", "dem"]).items():
        joint["%s|v=%.2f|%s" % (drv, v, dem)] = [
            dict(y=y, ar=1.0,
                 timeloss=agg([c for c in cells if c["y"] == y], "mean_timeloss")["mean"],
                 safety_rlr=agg([c for c in cells if c["y"] == y],
                                "rlr_per_1000_veh")["mean"],
                 safety_overlap=agg([c for c in cells if c["y"] == y],
                                    "overlap_per_1000_veh")["mean"],
                 rear=agg([c for c in cells if c["y"] == y],
                          "rear_ttc15_per_1000_veh")["mean"])
            for y in sorted(set(c["y"] for c in cells))]
    res["pareto_A"] = joint

    # ---------- F: teleport sensitivity ----------
    f = {}
    for (ttt, dem, y), cells in group([r for r, _ in runsF], ["ttt", "dem", "y"]).items():
        f["ttt=%s|%s|y=%.1f" % (ttt, dem, y)] = {
            m: agg(cells, m) for m in ("teleports", "completed", "still_running",
                                       "mean_timeloss", "timeloss_robust",
                                       "rlr_per_1000_veh", "overlap_per_1000_veh")}
    res["F_teleport"] = f

    json.dump(res, open(os.path.join(ANA_DIR, "results.json"), "w"), indent=2, default=str)
    print("wrote results.json")

    # flat CSV of every run for independent re-checking
    allrows = [r for r, _ in runsA + runsA2 + runsB + runsC + runsF]
    for r in allrows:
        r.pop("_collision_records", None)
    cols = sorted(set().union(*[set(r) for r in allrows]))
    with open(os.path.join(ANA_DIR, "all_runs.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(allrows)
    print("wrote all_runs.csv (%d runs)" % len(allrows))
    return res


if __name__ == "__main__":
    main()
