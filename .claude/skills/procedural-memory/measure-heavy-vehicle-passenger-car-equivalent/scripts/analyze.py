#!/usr/bin/env python3
"""STEP 3 -- compute E_T (passenger-car equivalent) by THREE estimators and
assemble every deliverable table.

Estimators
----------
M1  SIGNAL capacity ratio (HCM f_HV inverted).
    Per seed, per truck share p: the window-free GREEN-DURATION REGRESSION
        N_d(g) = (s/3600) * (g - l1 + e)
    across g in {16,24,32,40} s gives the mixed-fleet saturation flow s(p).
    Then      f_HV = s(p) / s(0)   and   E_T = 1 + (1/f_HV - 1) / p .
    Paired with the SAME seed's p=0 control (Common Random Numbers).

M1b SIGNAL disaggregate discharge headway (micro, fully independent of M1's
    regression).  Within the saturated part of the queue (positions n >= 4) the
    mean rear-bumper headway of heavy vehicles is compared with that of cars in
    the SAME runs:   E_T = h_bar(heavy) / h_bar(car).
    This uses no p=0 control run at all and no capacity concept.

M2  FREEWAY equal-capacity equivalency.  The 3->1 lane-drop queue-discharge
    capacity C(p) is measured at the bottleneck station.  The car-only flow that
    yields the same capacity is C(0) by definition, so a mixed vehicle is worth
    C(0)/C(p) passenger cars, and
        E_T = 1 + (C(0)/C(p) - 1) / p .

All three use the REALISED heavy-vehicle share measured at the detector, not
the nominal one.  Replication CIs are 95% t-intervals over 3 seeds.
"""
import os
import json
import math

from common import (WORK, OUT, CAR, TRUCK_DEFAULT, HV_VARIANTS, GREENS, GRADES,
                    SEEDS, SIG_SPEED, FWY_SPEED, YELLOW, ALLRED, ols, mean_ci,
                    theoretical_lane_capacity)
import signal_rig as S
import freeway_rig as F
from run_sweeps import SHARES, DECOMP_P, GRADE_SHARES, sig_dir, fwy_dir

N_ASYM = 12       # first queue position at which the discharge headway has
                  # FLATTENED (read off the measured h-vs-n profile, which shows
                  # SUMO's documented undershoot: h dips to ~1.36 s at n=4 then
                  # climbs back to a ~1.56 s asymptote by n~12).
N_SENS = [8, 10, 12, 14, 16]      # window-sensitivity grid, reported explicitly
COVER = 0.9       # a queue position counts only if >=90% of that green's cycles
                  # reached it (otherwise high-n positions are survivor-biased
                  # toward the fastest cycles)
HCM_LEVEL_ET_2000 = 1.5     # HCM 2000 level-terrain freeway E_T (the task's target)
HCM_LEVEL_ET_6TH = 2.0      # HCM 6th ed. level terrain / signalised-intersection E_T


# ------------------------------------------------------------ signal cell ----
def signal_cell(var, p, seed):
    """One (variant, truck share, seed) cell.

    PRIMARY estimator -- ASYMPTOTIC DISCHARGE HEADWAY.  Rear-bumper headways are
    pooled by queue position n across all 9 green durations and both NS
    approaches, keeping only positions reached by >=90% of that green's cycles.
    h_s = mean headway over n in [N_ASYM, n_max]; s = 3600/h_s.  This is
    continuous-valued and therefore free of the integer-quantisation problem that
    afflicts the green-duration regression on a deterministic (sigma=0) fleet.

    SECONDARY estimator -- the window-free green-duration regression
    N_d(g) = (s/3600)(g - l1 + e), retained as a cross-check, with its
    quantisation caveat reported alongside.
    """
    xs, ys, ext = [], [], []
    qmin, cmin, shares, ncyc = [], [], [], 0
    bypos = {}          # n -> list of (headway, class)
    pair = {}
    for g in GREENS:
        d = sig_dir(var, p, g, seed)
        a = S.analyse_run(d, g)
        xs.append(g)
        ys.append(a["veh_per_cycle"])
        ext.append(a["ext_into_yellow"])
        qmin.append(a["queue_min"])
        cmin.append(a["counts_min"])
        shares.append(a["hv_share_discharged"])
        ncyc += a["n_approach_cycles"]
        cnt = {}
        for n, h, c, _sp in a["headways"]:
            cnt[n] = cnt.get(n, 0) + 1
        n1 = cnt.get(1, 0)
        keep = {n for n, k in cnt.items() if n1 and k >= COVER * n1}
        prev_c, prev_n = None, None
        for n, h, c, _sp in a["headways"]:
            if n in keep:
                bypos.setdefault(n, []).append((h, c))
                if prev_n == n - 1 and prev_c is not None:
                    pair.setdefault((prev_c, c), []).append(h)
            prev_c, prev_n = c, n

    a0, b, r2 = ols(xs, ys)
    e = sum(ext) / len(ext)
    s_reg = 3600.0 * b
    nmax = max(bypos)

    def window(lo):
        v = [x for n in range(lo, nmax + 1) if n in bypos for x in bypos[n]]
        return v

    sens = {}
    for lo in N_SENS:
        v = window(lo)
        if v:
            sens["n%d-%d" % (lo, nmax)] = dict(h_s=sum(h for h, _ in v) / len(v),
                                               s=3600.0 * len(v) / sum(h for h, _ in v),
                                               n_obs=len(v))
    v = window(N_ASYM)
    h_all = [h for h, _ in v]
    h_c = [h for h, c in v if c == "c"]
    h_t = [h for h, c in v if c == "t"]
    h_s = sum(h_all) / len(h_all)
    return dict(
        variant=var, p_nominal=p, seed=seed,
        h_s=h_s, s_vph=3600.0 / h_s, n_h_window=len(h_all), n_max_position=nmax,
        window_sensitivity=sens,
        headway_profile={int(n): round(sum(h for h, _ in bypos[n]) / len(bypos[n]), 4)
                         for n in sorted(bypos)},
        profile_counts={int(n): len(bypos[n]) for n in sorted(bypos)},
        s_vph_greenreg=s_reg, h_s_greenreg=3600.0 / s_reg, r2_greenreg=r2,
        l1_greenreg=e - a0 / b, greens=xs, veh_per_cycle=ys, ext_into_yellow=e,
        queue_min_over_greens=min(qmin), counts_min_over_greens=min(cmin),
        hv_share_realised=sum(shares) / len(shares), n_approach_cycles=ncyc,
        h_car=sum(h_c) / len(h_c) if h_c else None,
        h_hv=sum(h_t) / len(h_t) if h_t else None,
        n_h_car=len(h_c), n_h_hv=len(h_t),
        h_by_pair={"%s->%s" % k: (sum(x) / len(x), len(x)) for k, x in sorted(pair.items())},
    )


def freeway_cell(var, p, gr, seed):
    d = fwy_dir(var, p, gr, seed)
    a = F.analyse_run(d)
    a.update(variant=var, p_nominal=p, grade=gr, seed=seed)
    return a


# ----------------------------------------------------------------- helpers --
def agg(cells, key):
    return mean_ci([c[key] for c in cells if c.get(key) is not None])


def et_series(mix_cells, base_cells, cap_key, share_key):
    """Paired (CRN) per-seed E_T from a capacity-type ratio."""
    base = {c["seed"]: c for c in base_cells}
    out = []
    for c in mix_cells:
        b = base[c["seed"]]
        p = c[share_key]
        if p <= 0:
            continue
        ratio = b[cap_key] / c[cap_key]         # = 1/f_HV
        out.append(1.0 + (ratio - 1.0) / p)
    return out


def fmt(m, hw, nd=3):
    if m is None:
        return "n/a"
    return "%.*f +/- %.*f" % (nd, m, nd, hw)


# --------------------------------------------------------------------- main --
def main():
    R = {}

    # ================================================== 1. SIGNAL share sweep
    sig = {}
    for p in SHARES:
        sig[p] = [signal_cell("hv_full", p, s) for s in SEEDS]
    R["signal_share_sweep"] = {}
    for p in SHARES:
        cs = sig[p]
        m_s, sd_s, hw_s, n = agg(cs, "s_vph")
        m_r, _, _, _ = agg(cs, "r2_greenreg")
        m_l, _, hw_l, _ = agg(cs, "l1_greenreg")
        m_p, _, _, _ = agg(cs, "hv_share_realised")
        ets = et_series(cs, sig[0.0], "s_vph", "hv_share_realised") if p > 0 else []
        m_e, sd_e, hw_e, ne = mean_ci(ets) if ets else (None, None, None, 0)
        hcar, _, _, _ = agg(cs, "h_car")
        hhv, _, _, _ = agg(cs, "h_hv")
        et_h = [c["h_hv"] / c["h_car"] for c in cs if c["h_hv"] and c["h_car"]]
        m_eh, _, hw_eh, neh = mean_ci(et_h) if et_h else (None, None, None, 0)
        R["signal_share_sweep"]["p%.2f" % p] = dict(
            p_nominal=p, p_realised=m_p,
            s_vph=m_s, s_sd=sd_s, s_ci95=hw_s, n_seeds=n,
            h_s=3600.0 / m_s, n_h_window=sum(c["n_h_window"] for c in cs),
            s_vph_greenreg=agg(cs, "s_vph_greenreg")[0],
            s_greenreg_ci95=agg(cs, "s_vph_greenreg")[2],
            regression_r2=m_r, l1_s=m_l, l1_ci95=hw_l,
            ET_M1_greenreg=mean_ci(et_series(cs, sig[0.0], "s_vph_greenreg",
                                             "hv_share_realised"))[0] if p > 0 else None,
            window_sensitivity=cs[0]["window_sensitivity"],
            headway_profile=cs[0]["headway_profile"],
            profile_counts=cs[0]["profile_counts"],
            f_hv=(m_s / R["signal_share_sweep"]["p0.00"]["s_vph"]) if p > 0 else 1.0,
            ET_M1_capacity_ratio=m_e, ET_M1_ci95=hw_e, ET_M1_per_seed=ets,
            h_car_s=hcar, h_hv_s=hhv,
            ET_M1b_headway_ratio=m_eh, ET_M1b_ci95=hw_eh, ET_M1b_per_seed=et_h,
            queue_min=min(c["queue_min_over_greens"] for c in cs),
            counts_min=min(c["counts_min_over_greens"] for c in cs),
            n_approach_cycles=sum(c["n_approach_cycles"] for c in cs),
            n_headway_car=sum(c["n_h_car"] for c in cs),
            n_headway_hv=sum(c["n_h_hv"] for c in cs),
            h_by_pair=cs[0]["h_by_pair"],
        )

    # ================================================= 2. FREEWAY share sweep
    fwy = {}
    for p in SHARES:
        fwy[p] = [freeway_cell("hv_full", p, 0.0, s) for s in SEEDS]
    R["freeway_share_sweep"] = {}
    for p in SHARES:
        cs = fwy[p]
        m_c, sd_c, hw_c, n = agg(cs, "capacity_vph")
        m_p, _, _, _ = agg(cs, "hv_share_discharged")
        ets = et_series(cs, fwy[0.0], "capacity_vph", "hv_share_discharged") if p > 0 else []
        m_e, sd_e, hw_e, _ = mean_ci(ets) if ets else (None, None, None, 0)
        R["freeway_share_sweep"]["p%.2f" % p] = dict(
            p_nominal=p, p_realised=m_p,
            capacity_vph=m_c, capacity_sd=sd_c, capacity_ci95=hw_c, n_seeds=n,
            f_hv=(m_c / R["freeway_share_sweep"]["p0.00"]["capacity_vph"]) if p > 0 else 1.0,
            ET_M2_equal_capacity=m_e, ET_M2_ci95=hw_e, ET_M2_per_seed=ets,
            pce_per_mixed_vehicle=(R["freeway_share_sweep"]["p0.00"]["capacity_vph"] / m_c) if p > 0 else 1.0,
            equivalent_car_only_flow_pcph=R["freeway_share_sweep"]["p0.00"]["capacity_vph"] if p > 0 else m_c,
            discharge_speed_ms=agg(cs, "discharge_speed_ms")[0],
            upstream_space_mean_speed_ms=agg(cs, "upstream_space_mean_speed_ms")[0],
            upstream_occupancy_pct=agg(cs, "upstream_occupancy_pct")[0],
            queue_meanJamVeh_lane2=sum(c["queue_meanJamVeh_per_lane"]["q_2"] for c in cs) / len(cs),
            trend_vph_per_hour=agg(cs, "trend_vph_per_hour")[0],
            teleports=sum(c["teleports"] for c in cs),
            collisions=sum(c["collisions"] for c in cs),
            mean_headway_car=agg(cs, "mean_headway_car")[0],
            mean_headway_hv=agg(cs, "mean_headway_hv")[0],
            n_discharged=sum(c["n_discharged"] for c in cs),
        )

    # ============================================== 3. GRADE sensitivity (fwy)
    R["freeway_grade"] = {}
    netver = json.load(open(os.path.join(WORK, "network_verification.json")))
    for gr in GRADES:
        base = [freeway_cell("hv_full", 0.0, gr, s) for s in SEEDS]
        mix = [freeway_cell("hv_full", 0.20, gr, s) for s in SEEDS]
        ets = et_series(mix, base, "capacity_vph", "hv_share_discharged")
        m_e, _, hw_e, _ = mean_ci(ets)
        R["freeway_grade"]["g%g" % gr] = dict(
            grade_pct_intended=gr,
            grade_pct_realised_from_compiled_net=netver["freeway"]["g%g" % gr]["realised_grade_pct_per_lane"],
            grade_verified=netver["freeway"]["g%g" % gr]["grade_verified"],
            capacity_p0=agg(base, "capacity_vph")[0], capacity_p0_ci95=agg(base, "capacity_vph")[2],
            capacity_p20=agg(mix, "capacity_vph")[0], capacity_p20_ci95=agg(mix, "capacity_vph")[2],
            p_realised=agg(mix, "hv_share_discharged")[0],
            ET_M2=m_e, ET_M2_ci95=hw_e, ET_M2_per_seed=ets,
            discharge_speed_p0=agg(base, "discharge_speed_ms")[0],
            discharge_speed_p20=agg(mix, "discharge_speed_ms")[0],
            teleports=sum(c["teleports"] for c in base + mix),
            collisions=sum(c["collisions"] for c in base + mix))

    # ================================================= 4. Parameter decomposition
    R["decomposition"] = {}
    sig_base = sig[0.0]
    fwy_base = fwy[0.0]
    for var in HV_VARIANTS:
        sc = [signal_cell(var, DECOMP_P, s) for s in SEEDS]
        fc = [freeway_cell(var, DECOMP_P, 0.0, s) for s in SEEDS]
        e1 = et_series(sc, sig_base, "s_vph", "hv_share_realised")
        e2 = et_series(fc, fwy_base, "capacity_vph", "hv_share_discharged")
        e1b = [c["h_hv"] / c["h_car"] for c in sc if c["h_hv"] and c["h_car"]]
        diff = {k: v for k, v in HV_VARIANTS[var].items()
                if k != "vClass" and abs(float(v) - float(CAR[k])) > 1e-9}
        R["decomposition"][var] = dict(
            attrs=HV_VARIANTS[var], differs_from_car_in=diff,
            n_params_changed=len(diff),
            s_vph=agg(sc, "s_vph")[0], s_ci95=agg(sc, "s_vph")[2],
            capacity_vph=agg(fc, "capacity_vph")[0], capacity_ci95=agg(fc, "capacity_vph")[2],
            p_realised_sig=agg(sc, "hv_share_realised")[0],
            p_realised_fwy=agg(fc, "hv_share_discharged")[0],
            ET_M1_signal=mean_ci(e1)[0], ET_M1_ci95=mean_ci(e1)[2],
            ET_M1b_headway=mean_ci(e1b)[0] if e1b else None,
            ET_M1b_ci95=mean_ci(e1b)[2] if e1b else None,
            ET_M2_freeway=mean_ci(e2)[0], ET_M2_ci95=mean_ci(e2)[2],
            queue_min=min(c["queue_min_over_greens"] for c in sc),
            fwy_upstream_speed_ms=agg(fc, "upstream_space_mean_speed_ms")[0],
            teleports=sum(c["teleports"] for c in fc),
            collisions=sum(c["collisions"] for c in fc))

    # ============================================ 4b. mechanism / additivity
    # Decompose in HEADWAY-INCREMENT space: dh = 3600/C_variant - 3600/C_car.
    # If the single-parameter effects are additive, sum(dh_i) == dh_full.
    mech = {}
    h0s = 3600.0 / R["signal_share_sweep"]["p0.00"]["s_vph"]
    h0f = 3600.0 / R["freeway_share_sweep"]["p0.00"]["capacity_vph"]
    singles = ["hv_len", "hv_accel", "hv_decel", "hv_vmax130"]
    for var in HV_VARIANTS:
        d = R["decomposition"][var]
        mech[var] = dict(dh_signal_s=3600.0 / d["s_vph"] - h0s,
                         dh_freeway_s=3600.0 / d["capacity_vph"] - h0f)
    mech["ADDITIVITY_CHECK"] = dict(
        note="the four attributes that SUMO's default truck actually changes",
        components=singles,
        sum_dh_signal=sum(mech[v]["dh_signal_s"] for v in singles),
        measured_dh_signal_hv_full=mech["hv_full"]["dh_signal_s"],
        sum_dh_freeway=sum(mech[v]["dh_freeway_s"] for v in singles),
        measured_dh_freeway_hv_full=mech["hv_full"]["dh_freeway_s"])
    R["mechanism_headway_increments"] = mech

    # Is f_HV actually LINEAR in p, as HCM assumes?  Compare the measured mixed
    # headway with the linear blend of the two PURE fleets (p=0 and p=1).
    lin = {}
    if "p1.00" in R["signal_share_sweep"]:
        hs0 = 3600.0 / R["signal_share_sweep"]["p0.00"]["s_vph"]
        hs1 = 3600.0 / R["signal_share_sweep"]["p1.00"]["s_vph"]
        hf0 = 3600.0 / R["freeway_share_sweep"]["p0.00"]["capacity_vph"]
        hf1 = 3600.0 / R["freeway_share_sweep"]["p1.00"]["capacity_vph"]
        for p in SHARES:
            a = R["signal_share_sweep"]["p%.2f" % p]
            b = R["freeway_share_sweep"]["p%.2f" % p]
            ps, pf = a["p_realised"], b["p_realised"]
            hs, hf = 3600.0 / a["s_vph"], 3600.0 / b["capacity_vph"]
            lin["p%.2f" % p] = dict(
                signal_h_measured=hs, signal_h_linear_blend=(1 - ps) * hs0 + ps * hs1,
                signal_excess_pct=100.0 * (hs / ((1 - ps) * hs0 + ps * hs1) - 1),
                freeway_h_measured=hf, freeway_h_linear_blend=(1 - pf) * hf0 + pf * hf1,
                freeway_excess_pct=100.0 * (hf / ((1 - pf) * hf0 + pf * hf1) - 1),
                ET_pure_fleet_anchor_signal=hs1 / hs0,
                ET_pure_fleet_anchor_freeway=hf1 / hf0)
    R["hcm_linearity_check"] = lin

    # ---------------------------------------------- per-run raw metrics export
    raw = []
    for p in SHARES:
        for c in sig[p]:
            raw.append(dict(testbed="signal", variant=c["variant"], p_nominal=p,
                            grade=0.0, seed=c["seed"],
                            p_realised=c["hv_share_realised"], h_s=c["h_s"],
                            s_vph=c["s_vph"], s_vph_greenreg=c["s_vph_greenreg"],
                            greenreg_r2=c["r2_greenreg"], l1_s=c["l1_greenreg"],
                            h_car=c["h_car"], h_hv=c["h_hv"],
                            n_headways=c["n_h_window"], n_max_position=c["n_max_position"],
                            min_queue_veh=c["queue_min_over_greens"],
                            min_veh_per_cycle=c["counts_min_over_greens"],
                            n_approach_cycles=c["n_approach_cycles"]))
        for c in fwy[p]:
            raw.append(dict(testbed="freeway", variant=c["variant"], p_nominal=p,
                            grade=0.0, seed=c["seed"],
                            p_realised=c["hv_share_discharged"],
                            capacity_vph=c["capacity_vph"], n_discharged=c["n_discharged"],
                            discharge_speed_ms=c["discharge_speed_ms"],
                            upstream_space_mean_speed_ms=c["upstream_space_mean_speed_ms"],
                            upstream_occupancy_pct=c["upstream_occupancy_pct"],
                            queue_meanJamVeh_lane2=c["queue_meanJamVeh_per_lane"]["q_2"],
                            trend_vph_per_hour=c["trend_vph_per_hour"],
                            h_car=c["mean_headway_car"], h_hv=c["mean_headway_hv"],
                            teleports=c["teleports"], collisions=c["collisions"]))
    for gr in GRADES:
        for pp in GRADE_SHARES:
            for sd in SEEDS:
                c = freeway_cell("hv_full", pp, gr, sd)
                raw.append(dict(testbed="freeway_grade", variant="hv_full", p_nominal=pp,
                                grade=gr, seed=sd, p_realised=c["hv_share_discharged"],
                                capacity_vph=c["capacity_vph"], n_discharged=c["n_discharged"],
                                discharge_speed_ms=c["discharge_speed_ms"],
                                upstream_space_mean_speed_ms=c["upstream_space_mean_speed_ms"],
                                upstream_occupancy_pct=c["upstream_occupancy_pct"],
                                queue_meanJamVeh_lane2=c["queue_meanJamVeh_per_lane"]["q_2"],
                                trend_vph_per_hour=c["trend_vph_per_hour"],
                                teleports=c["teleports"], collisions=c["collisions"]))
    for var in HV_VARIANTS:
        for sd in SEEDS:
            c = signal_cell(var, DECOMP_P, sd)
            raw.append(dict(testbed="signal_decomp", variant=var, p_nominal=DECOMP_P,
                            grade=0.0, seed=sd, p_realised=c["hv_share_realised"],
                            h_s=c["h_s"], s_vph=c["s_vph"], h_car=c["h_car"], h_hv=c["h_hv"],
                            min_queue_veh=c["queue_min_over_greens"],
                            n_headways=c["n_h_window"]))
            c = freeway_cell(var, DECOMP_P, 0.0, sd)
            raw.append(dict(testbed="freeway_decomp", variant=var, p_nominal=DECOMP_P,
                            grade=0.0, seed=sd, p_realised=c["hv_share_discharged"],
                            capacity_vph=c["capacity_vph"], n_discharged=c["n_discharged"],
                            discharge_speed_ms=c["discharge_speed_ms"],
                            upstream_space_mean_speed_ms=c["upstream_space_mean_speed_ms"],
                            teleports=c["teleports"], collisions=c["collisions"]))
    R["per_run_metrics"] = raw

    # =============================================== 5. bounds + bookkeeping
    R["theory"] = dict(
        signal_speed_ms=SIG_SPEED, freeway_speed_ms=FWY_SPEED,
        theoretical_1lane_bound_car_vph=theoretical_lane_capacity(FWY_SPEED, CAR),
        theoretical_1lane_bound_truck_vph=theoretical_lane_capacity(FWY_SPEED, TRUCK_DEFAULT),
        note_bound="v/(v*tau+length+minGap)*3600 evaluated at the FREE-FLOW speed; "
                   "re-evaluated below at the MEASURED discharge speed, which is the "
                   "relevant speed for a queue-discharge capacity.",
        hcm_level_terrain_ET_hcm2000=HCM_LEVEL_ET_2000,
        hcm_level_terrain_ET_hcm6th=HCM_LEVEL_ET_6TH,
        car_attrs=CAR, truck_attrs=TRUCK_DEFAULT)
    vd0 = R["freeway_share_sweep"]["p0.00"]["discharge_speed_ms"]
    R["theory"]["bound_at_measured_discharge_speed_car_vph"] = theoretical_lane_capacity(vd0, CAR)
    R["theory"]["bound_at_measured_discharge_speed_truck_vph"] = theoretical_lane_capacity(vd0, TRUCK_DEFAULT)
    R["theory"]["measured_discharge_speed_ms"] = vd0

    with open(os.path.join(WORK, "pce_results.json"), "w") as f:
        json.dump(R, f, indent=2, default=float)

    # ------------------------------------------------------------- printout --
    print("=" * 96)
    print("SIGNAL testbed -- saturation flow and E_T vs truck share")
    print("%-7s %-8s %7s %9s %8s %9s  %-17s %-17s %-9s"
          % ("p_nom", "p_real", "h_s(s)", "s(veh/h)", "f_HV", "s_greenreg",
             "E_T M1 (h_s ratio)", "E_T M1b (per-class)", "E_T(greenreg)"))
    for p in SHARES:
        r = R["signal_share_sweep"]["p%.2f" % p]
        print("%-7.2f %-8.4f %7.4f %9.1f %8.4f %9.1f  %-17s %-17s %-9s"
              % (p, r["p_realised"], r["h_s"], r["s_vph"], r["f_hv"], r["s_vph_greenreg"],
                 fmt(r["ET_M1_capacity_ratio"], r["ET_M1_ci95"]),
                 fmt(r["ET_M1b_headway_ratio"], r["ET_M1b_ci95"]),
                 "n/a" if r["ET_M1_greenreg"] is None else "%.3f" % r["ET_M1_greenreg"]))
    print()
    print("FREEWAY testbed -- lane-drop queue-discharge capacity and E_T vs truck share")
    print("%-7s %-9s %11s %8s   %-20s %8s %8s" % ("p_nom", "p_real", "C(veh/h)", "f_HV",
                                                  "E_T (M2 equal-cap)", "up_v", "tel/col"))
    for p in SHARES:
        r = R["freeway_share_sweep"]["p%.2f" % p]
        print("%-7.2f %-9.4f %11.1f %8.4f   %-20s %8.2f %d/%d"
              % (p, r["p_realised"], r["capacity_vph"], r["f_hv"],
                 fmt(r["ET_M2_equal_capacity"], r["ET_M2_ci95"]),
                 r["upstream_space_mean_speed_ms"], r["teleports"], r["collisions"]))
    print()
    print("GRADE sensitivity (freeway, p=20%)")
    print("%-8s %-10s %10s %10s   %-20s" % ("grade%", "verified", "C(p=0)", "C(p=20)", "E_T (M2)"))
    for gr in GRADES:
        r = R["freeway_grade"]["g%g" % gr]
        print("%-8g %-10s %10.1f %10.1f   %-20s"
              % (gr, r["grade_verified"], r["capacity_p0"], r["capacity_p20"],
                 fmt(r["ET_M2"], r["ET_M2_ci95"])))
    print()
    print("PARAMETER DECOMPOSITION (p=30%%, one attribute changed at a time)")
    print("%-12s %-28s %10s %10s   %-18s %-18s" % ("variant", "differs from car in", "s(veh/h)",
                                                   "C(veh/h)", "E_T signal (M1)", "E_T freeway (M2)"))
    for var in HV_VARIANTS:
        r = R["decomposition"][var]
        dd = ", ".join("%s=%s" % (k, v) for k, v in sorted(r["differs_from_car_in"].items()))
        print("%-12s %-28s %10.1f %10.1f   %-18s %-18s"
              % (var, dd, r["s_vph"], r["capacity_vph"],
                 fmt(r["ET_M1_signal"], r["ET_M1_ci95"]),
                 fmt(r["ET_M2_freeway"], r["ET_M2_ci95"])))
    print()
    print("theoretical 1-lane bound @ free-flow  : car %.0f  truck %.0f veh/h"
          % (R["theory"]["theoretical_1lane_bound_car_vph"],
             R["theory"]["theoretical_1lane_bound_truck_vph"]))
    print("theoretical 1-lane bound @ measured discharge speed %.2f m/s: car %.0f  truck %.0f"
          % (vd0, R["theory"]["bound_at_measured_discharge_speed_car_vph"],
             R["theory"]["bound_at_measured_discharge_speed_truck_vph"]))
    print()
    print("MECHANISM -- headway increment dh (s) vs the pure-car fleet, at p=30%")
    print("%-12s %12s %12s" % ("variant", "dh signal", "dh freeway"))
    for var in HV_VARIANTS:
        m = R["mechanism_headway_increments"][var]
        print("%-12s %12.4f %12.4f" % (var, m["dh_signal_s"], m["dh_freeway_s"]))
    ac = R["mechanism_headway_increments"]["ADDITIVITY_CHECK"]
    print("  sum of the 4 single-parameter increments : signal %.4f  freeway %.4f"
          % (ac["sum_dh_signal"], ac["sum_dh_freeway"]))
    print("  measured for the full default truck      : signal %.4f  freeway %.4f"
          % (ac["measured_dh_signal_hv_full"], ac["measured_dh_freeway_hv_full"]))
    print()
    print("HCM LINEARITY CHECK -- is f_HV really linear in p?")
    print("%-7s %10s %10s %8s   %10s %10s %8s" % ("p", "sig h_meas", "sig h_lin", "excess%",
                                                  "fwy h_meas", "fwy h_lin", "excess%"))
    for p in SHARES:
        l = R["hcm_linearity_check"]["p%.2f" % p]
        print("%-7.2f %10.4f %10.4f %8.2f   %10.4f %10.4f %8.2f"
              % (p, l["signal_h_measured"], l["signal_h_linear_blend"], l["signal_excess_pct"],
                 l["freeway_h_measured"], l["freeway_h_linear_blend"], l["freeway_excess_pct"]))
    print("  pure-fleet anchor E_T (p=1 ratio): signal %.4f  freeway %.4f"
          % (R["hcm_linearity_check"]["p1.00"]["ET_pure_fleet_anchor_signal"],
             R["hcm_linearity_check"]["p1.00"]["ET_pure_fleet_anchor_freeway"]))
    print()
    print("window sensitivity of h_s (p=0 control arm):",
          {k: round(v["h_s"], 4) for k, v in R["signal_share_sweep"]["p0.00"]["window_sensitivity"].items()})
    print("written", os.path.join(WORK, "pce_results.json"))


if __name__ == "__main__":
    main()
