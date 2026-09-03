"""H4 -- OPTIMAL STOP SPACING (analytic vs simulated) and
   H5 -- STOP CONSOLIDATION IS NOT FREE (who loses when stops are removed).

The person OD draw is INDEPENDENT of the stop layout (same seed -> same origins,
destinations and departure times in every spacing arm), so this is a clean CRN
comparison of stop layouts against a fixed corridor demand.

Analytic optimum (classical access-vs-in-vehicle tradeoff):
    C(s) = s / (2*v_walk)            mean access + egress walk time
         + (L_ride / s) * t_stop     in-vehicle penalty of the stops passed
    => s* = sqrt(2 * v_walk * L_ride * t_stop)
with t_stop the FIXED per-stop cost (door/dead time + deceleration/acceleration
loss); the per-passenger boarding time is NOT part of t_stop because every
passenger boards exactly once regardless of spacing.
"""
import os
import sys
import math
import json
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from scenario import Cfg  # noqa: E402
from expbase import run_arms, paired, mean, col, validity, save, ci  # noqa: E402

SEEDS = list(range(1, 11))
SPACINGS = (150.0, 200.0, 250.0, 300.0, 400.0, 500.0, 650.0, 800.0, 1000.0)


def analytic(cfg, t_stop_measured=None):
    v = cfg.speed_art
    a, d = 1.2, 3.0                      # bus accel / decel from the vType
    accel_loss = 0.5 * v * (1.0 / a + 1.0 / d)
    t_stop = (cfg.min_dwell + accel_loss) if t_stop_measured is None else t_stop_measured
    L_ride = 1050.0                      # mean person OD distance (500..1600 uniform)
    s_star = math.sqrt(2.0 * cfg.walk_speed * L_ride * t_stop)
    return {"accel_decel_loss_s": round(accel_loss, 2), "t_stop_s": round(t_stop, 2),
            "L_ride_m": L_ride, "walk_speed": cfg.walk_speed,
            "s_star_m": round(s_star, 1)}


def main():
    base = dict(lanes_art=2, q_art=1200.0, q_cross=250.0, pax_rate=1200.0,
                headway=180.0, stop_type="inlane")
    arms = {f"h4_sp{int(s)}": Cfg(stop_spacing=s, **base) for s in SPACINGS}
    # zero-transit control so the CAR externality of stop density is visible
    arms["h4_nobus"] = Cfg(stop_spacing=400.0, headway=100000.0, pax_rate=1.0,
                           **{k: v for k, v in base.items()
                              if k not in ("headway", "pax_rate")})
    print(f"H4/H5: {len(arms)} arms x {len(SEEDS)} seeds")
    res, errs = run_arms(arms, SEEDS, workers=9, tag="h4", detail=True)

    ctrl = res["h4_nobus"]
    rows = []
    for s in SPACINGS:
        ms = res[f"h4_sp{int(s)}"]
        allacc = [x for m in ms for x in m["rider_access_lens"]]
        alltot = [x for m in ms for x in m["rider_totals"]]
        allacc.sort()
        alltot.sort()

        def q(v, p):
            return v[min(len(v) - 1, int(p * len(v)))] if v else float("nan")
        rows.append({
            "spacing_m": s, "n_stops": ms[0]["n_stops"],
            "rider_total_s": round(mean(col(ms, "rider_mean_total")), 2),
            "rider_total_hw": round(ci(col(ms, "rider_mean_total"))[1], 2),
            "rider_access_s": round(mean(col(ms, "rider_mean_access")), 2),
            "rider_egress_s": round(mean(col(ms, "rider_mean_egress")), 2),
            "rider_wait_s": round(mean(col(ms, "rider_mean_wait")), 2),
            "rider_inveh_s": round(mean(col(ms, "rider_mean_inveh")), 2),
            "rider_access_len_m": round(mean(col(ms, "rider_mean_access_len")), 2),
            "rider_egress_len_m": round(mean(col(ms, "rider_mean_egress_len")), 2),
            "bus_mean_dur": round(mean(col(ms, "bus_mean_dur")), 2),
            "mean_dwell": round(mean(col(ms, "mean_dwell")), 2),
            "car_mean_loss": round(mean(col(ms, "car_mean_loss")), 2),
            "car_person_hours": round(mean(col(ms, "car_person_hours")), 3),
            "rider_person_hours": round(mean(col(ms, "rider_person_hours")), 3),
            "total_person_hours": round(mean(col(ms, "total_person_hours")), 3),
            "total_ph_hw": round(ci(col(ms, "total_person_hours"))[1], 3),
            "access_len_p50": round(q(allacc, 0.50), 1),
            "access_len_p90": round(q(allacc, 0.90), 1),
            "access_len_p95": round(q(allacc, 0.95), 1),
            "access_len_max": round(max(allacc), 1) if allacc else None,
            "frac_access_gt_400m": round(sum(1 for x in allacc if x > 400) / len(allacc), 4) if allacc else None,
            "frac_access_gt_600m": round(sum(1 for x in allacc if x > 600) / len(allacc), 4) if allacc else None,
            "total_time_p50": round(q(alltot, 0.50), 1),
            "total_time_p90": round(q(alltot, 0.90), 1),
            "total_time_p95": round(q(alltot, 0.95), 1),
            "n_rider_obs": len(alltot),
            "validity": validity(ms),
        })
        r = rows[-1]
        print(f"s={s:6.0f} stops={r['n_stops']:2d} riderTot={r['rider_total_s']:7.1f}+-{r['rider_total_hw']:.1f} "
              f"(acc {r['rider_access_s']:5.1f} wait {r['rider_wait_s']:5.1f} inveh {r['rider_inveh_s']:6.1f} "
              f"egr {r['rider_egress_s']:5.1f}) carLoss={r['car_mean_loss']:6.2f} "
              f"totalPH={r['total_person_hours']:8.2f}+-{r['total_ph_hw']:.2f}")

    # ---------------- MATCHED COHORT (bias correction) -----------------------
    # The rider POPULATION changes with spacing: a person whose nearest boarding
    # and alighting stop coincide cannot make a transit trip at all, and simply
    # vanishes from the demand.  Comparing raw per-arm rider means across spacings
    # is therefore a biased comparison (survivorship in the transit-usable subset).
    # Fix: restrict to persons who ride in EVERY spacing arm of the same seed.
    per_seed_common = {}
    for i, s in enumerate(SEEDS):
        sets = []
        for sp in SPACINGS:
            m = res[f"h4_sp{int(sp)}"][i]
            sets.append(set(m["person_records"].keys()))
        per_seed_common[s] = set.intersection(*sets)
    coh = []
    for sp in SPACINGS:
        vals, accs, tots = [], [], []
        for i, s in enumerate(SEEDS):
            m = res[f"h4_sp{int(sp)}"][i]
            ids = per_seed_common[s]
            recs = [m["person_records"][p] for p in ids]
            vals.append(sum(r[4] for r in recs) / len(recs))
            accs.extend(r[5] for r in recs)
            tots.extend(r[4] for r in recs)
        accs.sort()
        tots.sort()

        def qq(v, p):
            return v[min(len(v) - 1, int(p * len(v)))]
        coh.append({"spacing_m": sp, "cohort_n_per_seed": len(per_seed_common[SEEDS[0]]),
                    "cohort_mean_total_s": round(mean(vals), 2),
                    "cohort_hw": round(ci(vals)[1], 2),
                    "cohort_access_p50": round(qq(accs, .5), 1),
                    "cohort_access_p90": round(qq(accs, .9), 1),
                    "cohort_access_p95": round(qq(accs, .95), 1),
                    "cohort_total_p90": round(qq(tots, .9), 1),
                    "cohort_total_p95": round(qq(tots, .95), 1),
                    "per_seed_means": [round(v, 2) for v in vals]})
        print(f"  cohort s={sp:6.0f} meanTotal={coh[-1]['cohort_mean_total_s']:7.2f}"
              f"+-{coh[-1]['cohort_hw']:.2f} (n={coh[-1]['cohort_n_per_seed']}/seed) "
              f"accP90={coh[-1]['cohort_access_p90']:6.1f}")
    # riders LOST to consolidation (persons with no usable stop pair)
    lost = [{"spacing_m": sp,
             "mean_riders": round(mean(col(res[f"h4_sp{int(sp)}"], "n_riders")), 1),
             "mean_persons_loaded": round(mean(col(res[f"h4_sp{int(sp)}"], "n_persons_loaded")), 1),
             "mean_persons_dropped_no_usable_stop_pair":
                 round(mean(col(res[f"h4_sp{int(sp)}"], "n_persons_skipped")), 1)}
            for sp in SPACINGS]
    best_cohort = min(coh, key=lambda r: r["cohort_mean_total_s"])

    best_rider = min(rows, key=lambda r: r["rider_total_s"])
    best_total = min(rows, key=lambda r: r["total_person_hours"])
    ana = analytic(Cfg(**base))
    # analytic with the MEASURED fixed per-stop cost instead of the nominal one
    out = {
        "seeds": SEEDS, "spacings": SPACINGS, "rows": rows,
        "analytic": ana,
        "nobus_control": {"car_mean_loss": round(mean(col(ctrl, "car_mean_loss")), 3),
                          "car_person_hours": round(mean(col(ctrl, "car_person_hours")), 3)},
        "matched_cohort": coh,
        "riders_lost_to_consolidation": lost,
        "simulated_optimum_matched_cohort_m": best_cohort["spacing_m"],
        "simulated_optimum_rider_time_m": best_rider["spacing_m"],
        "simulated_optimum_total_person_hours_m": best_total["spacing_m"],
        "n_failed": len(errs),
    }
    print(f"\nanalytic s* = {ana['s_star_m']} m  (t_stop={ana['t_stop_s']}s = "
          f"{Cfg(**base).min_dwell}s door + {ana['accel_decel_loss_s']}s accel/decel)")
    print(f"simulated optimum (rider door-to-door, raw population) = {best_rider['spacing_m']} m")
    print(f"simulated optimum (rider door-to-door, MATCHED COHORT)  = {best_cohort['spacing_m']} m")
    print(f"simulated optimum (TOTAL person-hours incl. cars) = {best_total['spacing_m']} m")

    # ---- H5: consolidation decomposition, dense -> consolidated ---------------
    h5 = []
    for dense, sparse in ((200.0, 400.0), (200.0, 650.0), (300.0, 650.0), (400.0, 800.0)):
        A = res[f"h4_sp{int(dense)}"]
        B = res[f"h4_sp{int(sparse)}"]
        accA = sorted(x for m in A for x in m["rider_access_lens"])
        accB = sorted(x for m in B for x in m["rider_access_lens"])
        totA = sorted(x for m in A for x in m["rider_totals"])
        totB = sorted(x for m in B for x in m["rider_totals"])

        def q(v, p):
            return v[min(len(v) - 1, int(p * len(v)))]
        # per-rider win/lose split needs matched riders: same seed, same person ids
        h5.append({
            "from_spacing": dense, "to_spacing": sparse,
            "d_rider_total_mean": paired(col(A, "rider_mean_total"), col(B, "rider_mean_total")),
            "d_total_ph": paired(col(A, "total_person_hours"), col(B, "total_person_hours")),
            "d_car_ph": paired(col(A, "car_person_hours"), col(B, "car_person_hours")),
            "access_p50": [round(q(accA, .5), 1), round(q(accB, .5), 1)],
            "access_p90": [round(q(accA, .9), 1), round(q(accB, .9), 1)],
            "access_p95": [round(q(accA, .95), 1), round(q(accB, .95), 1)],
            "access_max": [round(accA[-1], 1), round(accB[-1], 1)],
            "total_p50": [round(q(totA, .5), 1), round(q(totB, .5), 1)],
            "total_p90": [round(q(totA, .9), 1), round(q(totB, .9), 1)],
            "total_p95": [round(q(totA, .95), 1), round(q(totB, .95), 1)],
            "frac_access_gt_500m": [round(sum(1 for x in accA if x > 500) / len(accA), 4),
                                    round(sum(1 for x in accB if x > 500) / len(accB), 4)],
        })
        # per-PERSON win/lose decomposition over the matched cohort
        dts, dacc = [], []
        for i, sd_ in enumerate(SEEDS):
            ids = per_seed_common[sd_]
            ra, rb = A[i]["person_records"], B[i]["person_records"]
            for pid in ids:
                dts.append(rb[pid][4] - ra[pid][4])
                dacc.append(rb[pid][5] - ra[pid][5])
        dts.sort()
        n = len(dts)
        h5[-1]["cohort_person_delta"] = {
            "n_persons": n,
            "frac_worse_off": round(sum(1 for x in dts if x > 0) / n, 4),
            "frac_better_off": round(sum(1 for x in dts if x < 0) / n, 4),
            "mean_delta_s": round(sum(dts) / n, 2),
            "mean_delta_among_losers_s": round(
                sum(x for x in dts if x > 0) / max(sum(1 for x in dts if x > 0), 1), 2),
            "delta_p50": round(dts[n // 2], 1),
            "delta_p90": round(dts[int(.9 * n)], 1),
            "delta_p95": round(dts[int(.95 * n)], 1),
            "delta_p99": round(dts[int(.99 * n)], 1),
            "delta_max": round(dts[-1], 1),
            "mean_access_len_delta_m": round(sum(dacc) / len(dacc), 2)}
        c = h5[-1]["cohort_person_delta"]
        print(f"      cohort: {c['frac_worse_off']*100:.1f}% worse off, "
              f"mean +{c['mean_delta_s']}s, losers +{c['mean_delta_among_losers_s']}s, "
              f"p90 +{c['delta_p90']}s p99 +{c['delta_p99']}s max +{c['delta_max']}s")
        r = h5[-1]
        print(f"H5 {dense:.0f}->{sparse:.0f} m: mean rider time {r['d_rider_total_mean']['diff']:+7.2f}s "
              f"({r['d_rider_total_mean']['pct']:+5.1f}%) | access p50 {r['access_p50']} "
              f"p90 {r['access_p90']} p95 {r['access_p95']} max {r['access_max']} | "
              f"rider total p90 {r['total_p90']} p95 {r['total_p95']}")
    out["h5_consolidation"] = h5
    save(out, "h4h5_spacing.json")


if __name__ == "__main__":
    main()
