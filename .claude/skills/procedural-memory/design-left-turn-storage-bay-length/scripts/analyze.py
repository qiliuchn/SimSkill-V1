#!/usr/bin/env python3
"""
Aggregate the bay-length sweep: per-cell means with 95% t confidence intervals,
critical bay length per left-turn share, design-rule-of-thumb comparison, and
the signal-retiming compensation analysis.
"""
import argparse
import csv
import json
import math
import os
from collections import defaultdict

import numpy as np
from scipy import stats

BAYS = [10, 20, 30, 50, 75, 100, 150, "full"]
NUMBAYS = [10, 20, 30, 50, 75, 100, 150]
SHARES = [0.10, 0.25, 0.40]
SIGS = ["split08", "split16", "split24", "actuated"]
WINDOW = 3000.0     # s of measured demand (600 -> 3600)
VEH_SLOT = 7.5      # m per queued vehicle (length 5.0 + minGap 2.5)


def ci95(v):
    v = np.asarray(v, dtype=float)
    v = v[~np.isnan(v)]
    if len(v) < 2:
        return (float(v.mean()) if len(v) else float("nan"), float("nan"))
    m = v.mean()
    h = stats.t.ppf(0.975, len(v) - 1) * v.std(ddof=1) / math.sqrt(len(v))
    return float(m), float(h)


def load(csv_path):
    rows = list(csv.DictReader(open(csv_path)))
    for r in rows:
        for k, v in list(r.items()):
            if k in ("bay", "sig", "err"):
                continue
            try:
                r[k] = float(v)
            except (ValueError, TypeError):
                r[k] = float("nan")
        r["throughput_vph"] = (r["served_L"] + r["served_T"] + r["served_R"]) * 3600.0 / WINDOW
        r["throughput_L_vph"] = r["served_L"] * 3600.0 / WINDOW
        r["throughput_TR_vph"] = (r["served_T"] + r["served_R"]) * 3600.0 / WINDOW
        # per-cycle failure-mode event rates
        cyc = max(r["cycles"], 1)
        r["overflow_s_per_cycle"] = r["overflow_s"] / cyc
        r["blockage_s_per_cycle"] = r["blockage_s"] / cyc
        r["overflow_cycle_frac"] = r["overflow_cycles"] / cyc
        r["blockage_cycle_frac"] = r["blockage_cycles"] / cyc
        r["thru_blocked_vs_per_cycle"] = r["overflow_thru_blocked_vs"] / cyc
        r["wasted_left_green_frac"] = (r["starved_left_green_s"] / r["left_green_s"]
                                       if r["left_green_s"] else float("nan"))
        r["blocked_left_green_frac"] = (r["blocked_left_green_s"] / r["left_green_s"]
                                        if r["left_green_s"] else float("nan"))
        r["never_inserted_tot"] = (r["never_inserted_L"] + r["never_inserted_T"]
                                   + r["never_inserted_R"])
    return rows


METRICS = ["throughput_vph", "throughput_L_vph", "throughput_TR_vph",
           "timeloss_L", "timeloss_TR", "departdelay_L", "departdelay_TR",
           "overflow_s_per_cycle", "blockage_s_per_cycle",
           "overflow_cycle_frac", "blockage_cycle_frac",
           "thru_blocked_vs_per_cycle", "wasted_left_green_frac",
           "blocked_left_green_frac", "never_inserted_tot", "teleports",
           "mean_cycle_s", "max_left_queue_up", "left_green_s", "cycles",
           "starved_left_green_s", "blocked_left_green_s",
           "q95_thru_queue_m", "mean_thru_queue_m", "q95_bayonly_left_veh",
           "never_inserted_L", "never_inserted_T", "never_inserted_R"]


def aggregate(rows):
    g = defaultdict(list)
    for r in rows:
        g[(r["bay"], r["share"], r["sig"])].append(r)
    out = {}
    for k, rs in g.items():
        c = {"n_seeds": len(rs)}
        for m in METRICS:
            mu, h = ci95([r[m] for r in rs])
            c[m], c[m + "_ci"] = mu, h
        out[k] = c
    return out


def bkey(b):
    return "full" if b == "full" else str(int(b))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--runs", required=True, help="dir with per-run events.json")
    ap.add_argument("--outdir", required=True)
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)

    rows = load(a.raw)
    agg = aggregate(rows)

    # ---------- compacted per-cell metrics CSV ----------
    p = os.path.join(a.outdir, "cell_metrics.csv")
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["bay_len_m", "left_share", "signal", "n_seeds"] +
                   [x for m in METRICS for x in (m, m + "_ci95")])
        for b in BAYS:
            for s in SHARES:
                for sg in SIGS:
                    c = agg[(bkey(b), s, sg)]
                    w.writerow([bkey(b), s, sg, c["n_seeds"]] +
                               [round(c[x], 4) if not math.isnan(c[x]) else ""
                                for m in METRICS for x in (m, m + "_ci")])
    print("wrote", p)

    # ---------- uncensored left queue from the FULL-lane control ----------
    # A design queue must be measured on a facility that cannot overflow;
    # a finite bay censors its own queue observation at the bay's capacity.
    # `bayonly_q_m_samples` is the per-cycle maximum CONTIGUOUS back-of-queue
    # distance (m) of stopped vehicles on the exclusive left lane. On the
    # full-length-lane control the lane is 400 m and never overflows at these
    # demands, so this is the unconstrained design queue.
    q95 = {}
    for s in SHARES:
        for sg in SIGS:
            samples = []
            for seed in range(1, 6):
                f = os.path.join(a.runs, f"bayfull_s{int(s*100)}_{sg}_seed{seed}",
                                 "events.json")
                if os.path.exists(f):
                    d = json.load(open(f))
                    samples += [n * VEH_SLOT for n in d["bayonly_q_left_samples"]]
            q95[(s, sg)] = (float(np.percentile(samples, 95)) if samples else float("nan"),
                            float(np.mean(samples)) if samples else float("nan"),
                            len(samples))

    # ---------- critical bay length ----------
    # L* = smallest swept bay length whose approach throughput is
    # STATISTICALLY within TOL of the full-length-lane control (i.e. the lower
    # 95% CI bound of the finite-bay throughput reaches TOL x the control mean).
    def critical(s, sg, tol=0.95, metric="throughput_vph"):
        ref = agg[("full", s, sg)][metric]
        thresh = tol * ref
        prev = None
        for b in NUMBAYS:
            c = agg[(bkey(b), s, sg)]
            lo = c[metric] - (0.0 if math.isnan(c[metric + "_ci"]) else c[metric + "_ci"])
            if lo >= thresh:
                if prev is None:
                    return float(b), b, ref, thresh
                # linear interpolation on the mean between the last failing and
                # this passing grid point
                b0, m0 = prev
                m1 = c[metric]
                if m1 > m0:
                    li = b0 + (thresh - m0) * (b - b0) / (m1 - m0)
                else:
                    li = float(b)
                return float(max(b0, min(b, li))), b, ref, thresh
            prev = (b, c[metric])
        return float("nan"), None, ref, thresh

    # Delay-based criterion: smallest L at which the LEFT movement's excess
    # time loss over the full-length-lane control is statistically
    # indistinguishable from DELAY_TOL seconds (upper CI bound below the
    # tolerance). Throughput recovers at a SHORTER bay than delay does, so both
    # are reported rather than one being passed off as "the" critical length.
    DELAY_TOL = 10.0

    def critical_delay(s, sg, tol=DELAY_TOL):
        ref = agg[("full", s, sg)]
        for b in NUMBAYS:
            c = agg[(bkey(b), s, sg)]
            d = c["timeloss_L"] - ref["timeloss_L"]
            hw = math.hypot(0.0 if math.isnan(c["timeloss_L_ci"]) else c["timeloss_L_ci"],
                            0.0 if math.isnan(ref["timeloss_L_ci"]) else ref["timeloss_L_ci"])
            if d + hw <= tol:
                return float(b)
        return float("nan")

    crit_rows = []
    for s in SHARES:
        left_vph = 800.0 * s
        for sg in SIGS:
            cyc = agg[("full", s, sg)]["mean_cycle_s"]
            arr = left_vph * cyc / 3600.0                       # left arrivals/cycle
            rot2 = 2.0 * arr * VEH_SLOT                         # 2 x arrivals x 7.5 m
            q, qm, nq = q95[(s, sg)]          # metres, already
            rot_q15, rot_q20 = 1.5 * q, 2.0 * q
            Li, Lg, ref, th = critical(s, sg)
            Li98, _, _, _ = critical(s, sg, tol=0.98)
            Li99, _, _, _ = critical(s, sg, tol=0.99)
            Ld = critical_delay(s, sg)
            # is the LEFT movement itself served-able at this split at all?
            gL = agg[("full", s, sg)]["left_green_s"] / max(agg[("full", s, sg)]["cycles"], 1)
            lcap = 1800.0 * gL / cyc if cyc else float("nan")
            crit_rows.append(dict(
                left_share=s, signal=sg, left_vph=left_vph, cycle_s=round(cyc, 1),
                mean_left_green_s=round(gL, 1),
                left_vc_at_stopline=round(left_vph / lcap, 2) if lcap else "",
                left_split_feasible=("yes" if left_vph / lcap < 0.95 else "NO - left oversaturated"),
                left_arr_per_cycle=round(arr, 2),
                rule_2x_arrivals_m=round(rot2, 1),
                q95_left_queue_m_uncensored=round(q, 1), mean_left_queue_m=round(qm, 1),
                rule_1p5x_q95_m=round(rot_q15, 1), rule_2x_q95_m=round(rot_q20, 1),
                measured_Lcrit_thr95_m=(round(Li, 1) if not math.isnan(Li) else "not reached"),
                measured_Lcrit_thr98_m=(round(Li98, 1) if not math.isnan(Li98) else "not reached"),
                measured_Lcrit_thr99_m=(round(Li99, 1) if not math.isnan(Li99) else "not reached"),
                measured_Lcrit_delay_m=(round(Ld, 1) if not math.isnan(Ld) else "not reached"),
                measured_Lcrit_gridpoint=(Lg if Lg else "not reached"),
                q95_thru_queue_m=round(agg[(bkey(150), s, sg)]["q95_thru_queue_m"], 1),
                ref_throughput_vph=round(ref, 1), threshold_vph=round(th, 1)))
    p = os.path.join(a.outdir, "critical_bay_length.csv")
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(crit_rows[0]))
        w.writeheader()
        w.writerows(crit_rows)
    print("wrote", p)

    # ---------- retiming compensation ----------
    # For each left share: the split that is best with an UNCONSTRAINED lane
    # (the "as-designed" plan) is held as the reference; then for every finite
    # bay we ask how much of the throughput lost to the short bay under that
    # reference plan can be recovered by re-optimising the split alone.
    comp_rows = []
    for s in SHARES:
        fixed = [g for g in SIGS if g != "actuated"]
        best_full = max(fixed, key=lambda g: agg[("full", s, g)]["throughput_vph"])
        ref_cap = agg[("full", s, best_full)]["throughput_vph"]
        for b in NUMBAYS:
            base = agg[(bkey(b), s, best_full)]["throughput_vph"]
            best_here = max(SIGS, key=lambda g: agg[(bkey(b), s, g)]["throughput_vph"])
            best_val = agg[(bkey(b), s, best_here)]["throughput_vph"]
            best_fx = max(fixed, key=lambda g: agg[(bkey(b), s, g)]["throughput_vph"])
            best_fx_val = agg[(bkey(b), s, best_fx)]["throughput_vph"]
            lost = ref_cap - base
            recov = best_fx_val - base
            comp_rows.append(dict(
                left_share=s, bay_len_m=b,
                as_designed_split=best_full,
                cap_full_lane_vph=round(ref_cap, 1),
                thr_asdesigned_vph=round(base, 1),
                thr_asdesigned_ci=round(agg[(bkey(b), s, best_full)]["throughput_vph_ci"], 1),
                loss_vph=round(lost, 1),
                loss_pct=round(100 * lost / ref_cap, 2),
                best_retimed_split=best_fx, thr_retimed_vph=round(best_fx_val, 1),
                thr_retimed_ci=round(agg[(bkey(b), s, best_fx)]["throughput_vph_ci"], 1),
                recovered_vph=round(recov, 1),
                pct_of_loss_recovered=(round(100 * recov / lost, 1) if lost > 5.0 else "n/a (no loss)"),
                residual_loss_pct=round(100 * (ref_cap - best_fx_val) / ref_cap, 2),
                best_incl_actuated=best_here, thr_best_incl_actuated=round(best_val, 1),
                # who bears the loss (under the as-designed plan)
                dTimeloss_left_s=round(agg[(bkey(b), s, best_full)]["timeloss_L"]
                                       - agg[("full", s, best_full)]["timeloss_L"], 1),
                dTimeloss_through_s=round(agg[(bkey(b), s, best_full)]["timeloss_TR"]
                                          - agg[("full", s, best_full)]["timeloss_TR"], 1),
                dTimeloss_left_ci=round(math.hypot(
                    agg[(bkey(b), s, best_full)]["timeloss_L_ci"],
                    agg[("full", s, best_full)]["timeloss_L_ci"]), 1),
                dTimeloss_through_ci=round(math.hypot(
                    agg[(bkey(b), s, best_full)]["timeloss_TR_ci"],
                    agg[("full", s, best_full)]["timeloss_TR_ci"]), 1),
            ))
    # Switching to actuated control is TWO changes at once: a better controller
    # (worth something even with an unconstrained lane) and a controller that
    # can react to a constrained bay. Decompose them, otherwise the control
    # upgrade gets miscredited as bay compensation:
    #     raw gain at L          = actuated(L) - asdesigned(L)
    #     control-upgrade value  = actuated(full) - asdesigned(full)
    #     bay-specific gain      = raw gain - control-upgrade value
    for r in comp_rows:
        s, b = r["left_share"], r["bay_len_m"]
        plan = r["as_designed_split"]
        B = agg[(bkey(b), s, plan)]["throughput_vph"]
        C = agg[("full", s, plan)]["throughput_vph"]
        A = agg[(bkey(b), s, "actuated")]["throughput_vph"]
        Af = agg[("full", s, "actuated")]["throughput_vph"]
        loss = C - B
        raw, upg = A - B, Af - C
        r["thr_actuated_vph"] = round(A, 1)
        r["actuated_full_lane_vph"] = round(Af, 1)
        r["actuation_raw_gain_vph"] = round(raw, 1)
        r["actuation_control_upgrade_vph"] = round(upg, 1)
        r["actuation_bay_specific_gain_vph"] = round(raw - upg, 1)
        r["pct_of_loss_recovered_by_actuation"] = (
            round(100 * (raw - upg) / loss, 1) if loss > 5.0 else "n/a (no loss)")

    p = os.path.join(a.outdir, "retiming_compensation.csv")
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(comp_rows[0]))
        w.writeheader()
        w.writerows(comp_rows)
    print("wrote", p)

    # ---------- design-rule-of-thumb verdict ----------
    # Evaluate the swept surface AT the rule-of-thumb length (linear
    # interpolation between the bracketing grid points) rather than eyeballing
    # the nearest grid point.
    def interp(s, sg, metric, L):
        xs = [float(b) for b in NUMBAYS]
        ys = [agg[(bkey(b), s, sg)][metric] for b in NUMBAYS]
        cs = [agg[(bkey(b), s, sg)][metric + "_ci"] for b in NUMBAYS]
        if L <= xs[0]:
            return ys[0], cs[0]
        if L >= xs[-1]:
            return ys[-1], cs[-1]
        return float(np.interp(L, xs, ys)), float(np.interp(L, xs, cs))

    verdict = []
    for s in SHARES:
        fixed = [g for g in SIGS if g != "actuated"]
        plan = max(fixed, key=lambda g: agg[("full", s, g)]["throughput_vph"])
        for sg, plabel in ((plan, "best feasible fixed-time"), ("actuated", "actuated")):
            cyc = agg[("full", s, sg)]["mean_cycle_s"]
            arr = 800.0 * s * cyc / 3600.0
            L_rule = 2.0 * arr * VEH_SLOT
            q, _, _ = q95[(s, sg)]
            L_ruleq = 2.0 * q
            ref = agg[("full", s, sg)]
            row = dict(left_share=s, signal=sg, plan_role=plabel,
                       rule_2x_arrivals_m=round(L_rule, 1),
                       rule_2x_q95left_m=round(L_ruleq, 1),
                       q95_through_queue_m=round(agg[(bkey(150), s, sg)]["q95_thru_queue_m"], 1))
            for tag, L in (("at_rule2xArr", L_rule), ("at_rule2xQ95", L_ruleq)):
                if L > 150.0:
                    row[f"thr_pct_of_unconstrained_{tag}"] = ">150m, outside swept range"
                    row[f"excess_left_timeloss_s_{tag}"] = ""
                    row[f"excess_through_timeloss_s_{tag}"] = ""
                    continue
                t, tc_ = interp(s, sg, "throughput_vph", L)
                lL, cL = interp(s, sg, "timeloss_L", L)
                lT, cT = interp(s, sg, "timeloss_TR", L)
                row[f"thr_pct_of_unconstrained_{tag}"] = round(100 * t / ref["throughput_vph"], 1)
                row[f"excess_left_timeloss_s_{tag}"] = (
                    f"{lL - ref['timeloss_L']:+.1f} +/- {math.hypot(cL, ref['timeloss_L_ci']):.1f}")
                row[f"excess_through_timeloss_s_{tag}"] = (
                    f"{lT - ref['timeloss_TR']:+.1f} +/- {math.hypot(cT, ref['timeloss_TR_ci']):.1f}")
            tpct = row["thr_pct_of_unconstrained_at_rule2xArr"]
            row["capacity_verdict"] = ("CONSERVATIVE (>=99% of unconstrained capacity)"
                                       if isinstance(tpct, float) and tpct >= 99.0
                                       else "check" if isinstance(tpct, float) else "n/a")
            verdict.append(row)
    p = os.path.join(a.outdir, "design_rule_verdict.csv")
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(verdict[0]))
        w.writeheader()
        w.writerows(verdict)
    print("wrote", p)

    json.dump({f"{k[0]}|{k[1]}|{k[2]}": v for k, v in agg.items()},
              open(os.path.join(a.outdir, "aggregate.json"), "w"), indent=1)
    return agg, crit_rows, comp_rows


if __name__ == "__main__":
    main()
