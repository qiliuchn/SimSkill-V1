#!/usr/bin/env python3
"""Aggregate every run's metrics.json into the study's deliverables:
frontier table, energy decomposition, hypothesis tests, validity audit, figures."""
import os, sys, json, math, statistics, collections, csv
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
RUNS = os.path.join(ROOT, "runs")
OUT = os.path.abspath(os.path.join(ROOT, "..", "..", "outputs"))
SEEDS = [1, 2, 3]
RESERVE = 0.20

T_CRIT = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447,
          7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228, 14: 2.145, 19: 2.093}


def tcrit(df):
    if df in T_CRIT:
        return T_CRIT[df]
    return 1.96 + 2.4 / max(df, 1)


def mean_ci(v):
    v = [x for x in v if x is not None]
    if not v:
        return None, None, None
    m = statistics.mean(v)
    if len(v) < 2:
        return m, 0.0, 0.0
    s = statistics.stdev(v)
    h = tcrit(len(v) - 1) * s / math.sqrt(len(v))
    return m, s, h


def paired_diff(a, b):
    """Paired (CRN) difference b - a with a t confidence interval."""
    d = [y - x for x, y in zip(a, b)]
    m, s, h = mean_ci(d)
    if m is None:
        return None
    t = (m / (s / math.sqrt(len(d)))) if (s and len(d) > 1) else None
    return dict(n=len(d), mean_diff=round(m, 5), sd=round(s, 5) if s else 0.0,
                ci95_halfwidth=round(h, 5), lo=round(m - h, 5), hi=round(m + h, 5),
                t=round(t, 3) if t else None,
                significant_95=bool(s and abs(m) > h))


def load_all():
    M = {}
    for tag in sorted(os.listdir(RUNS)):
        f = os.path.join(RUNS, tag, "metrics.json")
        if os.path.exists(f):
            M[tag] = json.load(open(f))
    return M


def arm(M, prefix, seeds=SEEDS):
    """Return list of metrics dicts for tags `prefix` + f'_s{seed}' in seed order."""
    return [M[f"{prefix}_s{s}"] for s in seeds if f"{prefix}_s{s}" in M]


def g(m, *path):
    x = m
    for p in path:
        x = x[p]
    return x


# ------------------------------------------------------------------ deliverables
def frontier(M):
    rows = []
    for cap in [80, 120, 160, 200, 240]:
        for nch, pol in [(0, "skip"), (1, "skip"), (1, "queue"), (2, "skip")]:
            pre = (f"A_cap{cap}_ch{nch}" if pol == "skip" or nch != 1
                   else f"B_cap{cap}_ch1queue")
            a = arm(M, pre)
            if not a:
                continue
            socmin = [g(m, "energy", "fleet", "min_soc_over_fleet") for m in a]
            feas = [g(m, "energy", "fleet", "feasible") for m in a]
            depl = [g(m, "energy", "fleet", "n_buses_depleted") for m in a]
            below = [g(m, "energy", "fleet", "n_buses_below_reserve") for m in a]
            dev = [g(m, "schedule", "mean_dep_dev_s") for m in a]
            p90 = [g(m, "schedule", "p90_dep_dev_s") for m in a]
            miss = [g(m, "schedule", "n_missed_departures") for m in a]
            cv = [g(m, "schedule", "headway_cv_pooled") for m in a]
            dwell = [g(m, "schedule", "mean_terminal_dwell_s") for m in a]
            chg = [g(m, "energy", "fleet", "charged_kwh") for m in a]
            net = [g(m, "energy", "fleet", "net_energy_kwh") for m in a]
            frac = [g(m, "contention", "frac_pullins_charged") for m in a]
            ovl = [g(m, "contention", "berth_overlaps") for m in a]
            ms, _, mh = mean_ci(socmin)
            rows.append(dict(
                cap_kwh=cap, chargers=nch, policy=pol, n_seeds=len(a),
                min_soc_mean=round(ms, 4), min_soc_ci95=round(mh, 4),
                min_soc_per_seed=[round(x, 4) for x in socmin],
                feasible_all_seeds=all(feas), n_seeds_feasible=sum(feas),
                buses_depleted_max=max(depl), buses_below_reserve_max=max(below),
                mean_dep_dev_s=round(mean_ci(dev)[0], 2),
                p90_dep_dev_s=round(mean_ci(p90)[0], 2),
                missed_departures_mean=round(mean_ci(miss)[0], 2),
                headway_cv=round(mean_ci(cv)[0], 4),
                terminal_dwell_s=round(mean_ci(dwell)[0], 1),
                charged_kwh=round(mean_ci(chg)[0], 1),
                net_energy_kwh=round(mean_ci(net)[0], 1),
                frac_pullins_charged=round(mean_ci(frac)[0], 3),
                berth_overlaps=round(mean_ci(ovl)[0], 2),
            ))
    return rows


def energy_decomposition(M):
    rows = []
    for tag, label in [("A_cap240_ch2", "reference (240 kWh, 2 chargers, aux 7 kW)"),
                       ("D_tspoff_aux7000", "TSP off, aux 7 kW"),
                       ("D_tspoff_aux0", "TSP off, aux 0 kW"),
                       ("D_tspconditional_aux7000", "TSP on, aux 7 kW"),
                       ("D_tspconditional_aux0", "TSP on, aux 0 kW"),
                       ("F_rec0.85_stride1", "regen 0.85, 12 stops"),
                       ("F_rec0.0_stride1", "regen 0.00, 12 stops"),
                       ("F_rec0.85_stride2", "regen 0.85, 6 stops"),
                       ("F_rec0.0_stride2", "regen 0.00, 6 stops")]:
        a = arm(M, tag)
        if not a:
            continue
        def col(*p):
            return mean_ci([g(m, *p) for m in a])[0]
        gross = col("energy", "fleet", "gross_consumed_kwh")
        aux = col("energy", "fleet", "aux_kwh")
        regen = col("energy", "fleet", "regen_kwh")
        net = col("energy", "fleet", "net_energy_kwh")
        dist = col("energy", "fleet", "dist_km")
        rows.append(dict(arm=tag, label=label, n_seeds=len(a),
                         dist_km=round(dist, 1),
                         traction_gross_kwh=round(gross - aux, 1),
                         auxiliary_kwh=round(aux, 1),
                         gross_consumed_kwh=round(gross, 1),
                         regenerated_kwh=round(regen, 1),
                         net_energy_kwh=round(net, 1),
                         kwh_per_km=round(net / dist, 4),
                         kwh_per_km_EB=round(col("energy", "fleet", "mean_kwh_per_km_EB"), 4),
                         kwh_per_km_WB=round(col("energy", "fleet", "mean_kwh_per_km_WB"), 4),
                         aux_share_of_net=round(aux / net, 4),
                         regen_share_of_gross=round(regen / gross, 4),
                         bus_time_h=round(col("energy", "fleet", "dist_km") and
                                          sum(b for b in [0]) or 0, 3)))
    return rows


def hypotheses(M):
    H = {}

    # ---------------- H1: auxiliary share, congestion growth, TSP energy saving
    off = arm(M, "D_tspoff_aux7000")
    on = arm(M, "D_tspconditional_aux7000")
    off0 = arm(M, "D_tspoff_aux0")
    on0 = arm(M, "D_tspconditional_aux0")
    if off and on and off0 and on0:
        # (a) validate the auxiliary share by the aux=0 re-run
        aux_pred = [g(m, "energy", "fleet", "aux_kwh") for m in off]
        aux_meas = [g(a, "energy", "fleet", "gross_consumed_kwh") -
                    g(b, "energy", "fleet", "gross_consumed_kwh") for a, b in zip(off, off0)]
        # bus-time in the network differs slightly between the two arms; report both
        H["H1_aux_validation"] = dict(
            aux_predicted_kwh=[round(x, 2) for x in aux_pred],
            aux_measured_by_zeroing_kwh=[round(x, 2) for x in aux_meas],
            ratio=[round(b / a, 4) for a, b in zip(aux_pred, aux_meas)],
            paired=paired_diff(aux_pred, aux_meas))
        net_off = [g(m, "energy", "fleet", "net_energy_kwh") for m in off]
        net_on = [g(m, "energy", "fleet", "net_energy_kwh") for m in on]
        net_off0 = [g(m, "energy", "fleet", "net_energy_kwh") for m in off0]
        net_on0 = [g(m, "energy", "fleet", "net_energy_kwh") for m in on0]
        # traction-only saving = saving measured with the auxiliary load switched off
        H["H1_tsp"] = dict(
            total_energy_saving_kwh=paired_diff(net_off, net_on),
            traction_only_saving_kwh=paired_diff(net_off0, net_on0),
            aux_energy_off_kwh=[round(x, 2) for x in
                                [g(m, "energy", "fleet", "aux_kwh") for m in off]],
            aux_energy_on_kwh=[round(x, 2) for x in
                               [g(m, "energy", "fleet", "aux_kwh") for m in on]],
            bus_ride_duration_off_s=[g(m, "validity", "ride_mean_duration_s") for m in off],
            bus_ride_duration_on_s=[g(m, "validity", "ride_mean_duration_s") for m in on],
            car_timeloss_off_s=[g(m, "validity", "car_mean_timeloss_s") for m in off],
            car_timeloss_on_s=[g(m, "validity", "car_mean_timeloss_s") for m in on],
        )
    # (b) congestion dependence of the auxiliary share: peak vs off-peak per-bus
    H["H1_aux_share_reference"] = {}
    for tag in ["A_cap240_ch2", "D_tspoff_aux7000"]:
        a = arm(M, tag)
        if a:
            H["H1_aux_share_reference"][tag] = dict(
                aux_share_of_net=[round(g(m, "energy", "fleet", "aux_share_of_net"), 4) for m in a])

    # ---------------- H2: regeneration vs stop density
    res = {}
    for stride, nstops in [(1, 12), (2, 6)]:
        aR = arm(M, f"F_rec0.85_stride{stride}")
        aN = arm(M, f"F_rec0.0_stride{stride}")
        if aR and aN:
            res[f"{nstops}_stops"] = dict(
                regen_on_kwh_per_km=[round(g(m, "energy", "fleet", "net_energy_kwh") /
                                           g(m, "energy", "fleet", "dist_km"), 4) for m in aR],
                regen_off_kwh_per_km=[round(g(m, "energy", "fleet", "net_energy_kwh") /
                                            g(m, "energy", "fleet", "dist_km"), 4) for m in aN],
                dist_km=[round(g(m, "energy", "fleet", "dist_km"), 1) for m in aR])
    if len(res) == 2:
        rOn12 = res["12_stops"]["regen_on_kwh_per_km"]
        rOn6 = res["6_stops"]["regen_on_kwh_per_km"]
        rOff12 = res["12_stops"]["regen_off_kwh_per_km"]
        rOff6 = res["6_stops"]["regen_off_kwh_per_km"]
        res["sensitivity_to_stop_density"] = dict(
            with_regen_delta_kwh_per_km=paired_diff(rOn6, rOn12),
            without_regen_delta_kwh_per_km=paired_diff(rOff6, rOff12),
            with_regen_pct=[round(100 * (a - b) / b, 3) for a, b in zip(rOn12, rOn6)],
            without_regen_pct=[round(100 * (a - b) / b, 3) for a, b in zip(rOff12, rOff6)])
    H["H2_regen_stop_density"] = res

    # ---------------- H3: directional asymmetry
    a = arm(M, "A_cap160_ch2")
    if a:
        H["H3_direction"] = dict(
            kwh_per_km_round_trip=[round(g(m, "energy", "fleet", "mean_kwh_per_km"), 4) for m in a],
            kwh_per_km_EB=[round(g(m, "energy", "fleet", "mean_kwh_per_km_EB"), 4) for m in a],
            kwh_per_km_WB=[round(g(m, "energy", "fleet", "mean_kwh_per_km_WB"), 4) for m in a],
            ratio_EB_over_WB=[round(g(m, "energy", "fleet", "mean_kwh_per_km_EB") /
                                    g(m, "energy", "fleet", "mean_kwh_per_km_WB"), 3) for m in a])

    # ---------------- H4: charger sizing
    h4 = {}
    for cap in [80, 120, 160]:
        for pre, lab in [(f"A_cap{cap}_ch1", "1 charger (session truncation)"),
                         (f"B_cap{cap}_ch1queue", "1 charger (queueing)"),
                         (f"A_cap{cap}_ch2", "2 chargers")]:
            a = arm(M, pre)
            if not a:
                continue
            h4[f"cap{cap}::{lab}"] = dict(
                min_soc=[round(g(m, "energy", "fleet", "min_soc_over_fleet"), 4) for m in a],
                charged_kwh=[round(g(m, "energy", "fleet", "charged_kwh"), 1) for m in a],
                net_kwh=[round(g(m, "energy", "fleet", "net_energy_kwh"), 1) for m in a],
                frac_pullins_charged=[g(m, "contention", "frac_pullins_charged") for m in a],
                berth_overlaps=[g(m, "contention", "berth_overlaps") for m in a],
                mean_dep_dev_s=[g(m, "schedule", "mean_dep_dev_s") for m in a],
                p90_dep_dev_s=[g(m, "schedule", "p90_dep_dev_s") for m in a],
                missed_departures=[g(m, "schedule", "n_missed_departures") for m in a],
                headway_cv=[g(m, "schedule", "headway_cv_pooled") for m in a],
                max_berth_utilisation=[round(max(v["utilisation"] for k, v in
                                                 g(m, "contention", "berth_occupancy").items()), 4)
                                       for m in a])
    H["H4_charger_sizing"] = h4

    # ---------------- H5: capacity -> mass -> consumption
    h5 = {"coupled": {}, "fixed_mass": {}}
    for cap in [80, 120, 160, 200, 240]:
        for key, pre in [("coupled", f"A_cap{cap}_ch2"), ("fixed_mass", f"C_cap{cap}_massfixed")]:
            a = arm(M, pre)
            if not a:
                continue
            kk = [g(m, "energy", "fleet", "net_energy_kwh") / g(m, "energy", "fleet", "dist_km")
                  for m in a]
            m_, s_, h_ = mean_ci(kk)
            h5[key][cap] = dict(kwh_per_km=[round(x, 5) for x in kk],
                                mean=round(m_, 5), ci95=round(h_, 5),
                                mass_kg=g(a[0], "cfg", "_mass_kg"))
    # marginal usable range per added kWh (0.9 -> 0.2 SOC window, depot-only duty)
    if h5["coupled"]:
        caps = sorted(h5["coupled"])
        rng = {c: 0.7 * c / h5["coupled"][c]["mean"] for c in caps}
        marg = {f"{a}->{b}": round((rng[b] - rng[a]) / (b - a), 4)
                for a, b in zip(caps, caps[1:])}
        h5["usable_range_km"] = {c: round(v, 2) for c, v in rng.items()}
        h5["marginal_km_per_added_kwh"] = marg
        if "fixed_mass" in h5 and h5["fixed_mass"]:
            rngf = {c: 0.7 * c / h5["fixed_mass"][c]["mean"] for c in caps if c in h5["fixed_mass"]}
            h5["usable_range_km_fixed_mass"] = {c: round(v, 2) for c, v in rngf.items()}
            h5["marginal_km_per_added_kwh_fixed_mass"] = {
                f"{a}->{b}": round((rngf[b] - rngf[a]) / (b - a), 4)
                for a, b in zip(caps, caps[1:]) if a in rngf and b in rngf}
    H["H5_capacity_mass"] = h5

    # ---------------- strategy (c): mid-day depot recharge
    st = {}
    for cap in [120, 160]:
        for pre, lab in [(f"A_cap{cap}_ch0", "depot-only (overnight charge only)"),
                         (f"G_cap{cap}_midday", "depot-only + mid-day depot recharge"),
                         (f"A_cap{cap}_ch2", "terminal opportunity charging (2 chargers)")]:
            a = arm(M, pre)
            if not a:
                continue
            st[f"cap{cap}::{lab}"] = dict(
                min_soc=[round(g(m, "energy", "fleet", "min_soc_over_fleet"), 4) for m in a],
                feasible=[g(m, "energy", "fleet", "feasible") for m in a],
                charged_kwh=[round(g(m, "energy", "fleet", "charged_kwh"), 1) for m in a],
                mean_dep_dev_s=[g(m, "schedule", "mean_dep_dev_s") for m in a],
                missed_departures=[g(m, "schedule", "n_missed_departures") for m in a],
                headway_cv=[g(m, "schedule", "headway_cv_pooled") for m in a],
                headway_mean_s=[g(m, "schedule", "headway_mean_s") for m in a],
                ride_wait_s=[g(m, "validity", "ride_mean_wait_s") for m in a])
    H["strategy_comparison"] = st

    # ---------------- terminal charger power sweep
    pw = {}
    for p in [120, 200, 300]:
        for cap in [80, 120]:
            pre = f"A_cap{cap}_ch1" if p == 120 else f"H_p{p}_cap{cap}_ch1"
            a = arm(M, pre)
            if not a:
                continue
            pw[f"{p}kW_cap{cap}"] = dict(
                min_soc=[round(g(m, "energy", "fleet", "min_soc_over_fleet"), 4) for m in a],
                charged_kwh=[round(g(m, "energy", "fleet", "charged_kwh"), 1) for m in a],
                feasible=[g(m, "energy", "fleet", "feasible") for m in a])
    H["charger_power_sweep"] = pw
    return H


def validity_audit(M):
    rows = []
    for tag, m in sorted(M.items()):
        v = m["validity"]
        rows.append(dict(tag=tag, teleports=v["teleports_total"], teleports_bus=v["teleports_bus"],
                         stops_skipped=v["stops_skipped"],
                         depleted_warnings=v["battery_depleted_warnings"],
                         buses_complete=f'{v["buses_completing_full_block"]}/{v["n_buses"]}',
                         unfinished_vehicles=v["n_unfinished_vehicles"],
                         persons_without_ride=v["n_persons_without_ride"],
                         n_rides=v["n_rides"],
                         max_balance_residual_wh=m["energy"]["fleet"]["max_balance_residual_wh"],
                         ledger_diff_wh=m["energy"]["charge_ledger_check"]["diff_wh"],
                         n_buses_depleted=m["energy"]["fleet"]["n_buses_depleted"]))
    agg = dict(
        n_runs=len(rows),
        runs_with_bus_teleports=sum(1 for r in rows if r["teleports_bus"] > 0),
        runs_with_any_teleport=sum(1 for r in rows if r["teleports"] > 0),
        total_teleports=sum(r["teleports"] for r in rows),
        total_stops_skipped=sum(r["stops_skipped"] for r in rows),
        runs_all_blocks_complete=sum(1 for r in rows if r["buses_complete"].split("/")[0] ==
                                     r["buses_complete"].split("/")[1]),
        max_abs_balance_residual_wh_no_depletion=max(
            [abs(r["max_balance_residual_wh"]) for r in rows if r["n_buses_depleted"] == 0]),
        n_runs_with_depletion=sum(1 for r in rows if r["n_buses_depleted"] > 0),
        max_abs_balance_residual_wh_with_depletion=max(
            [abs(r["max_balance_residual_wh"]) for r in rows if r["n_buses_depleted"] > 0] or [0]),
        note_on_residual=("For runs in which no bus is depleted the energy balance "
                          "initial - consumed + regenerated + credited_charge - final closes to "
                          "<0.2 Wh over ~20000 steps x 7 buses. In runs where at least one bus "
                          "empties its battery the residual is NOT an error: SUMO clamps "
                          "actualBatteryCapacity at 0, so the residual equals the unserved energy "
                          "deficit (the amount by which the block exceeded the battery)."),
        max_abs_ledger_diff_wh=max(abs(r["ledger_diff_wh"]) for r in rows),
        total_persons_without_ride=sum(r["persons_without_ride"] for r in rows),
    )
    return agg, rows


def write_csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow({k: (json.dumps(v) if isinstance(v, (list, dict)) else v)
                        for k, v in r.items()})


# ------------------------------------------------------------------ leg timing
def leg_times(tag):
    """Per terminal-to-terminal leg: departure from one terminal -> stop start at the next.
    Re-derived directly from the run's raw stop-output, so queueing for an occupied
    charging berth shows up as extra leg time even though SUMO never lets two vehicles
    occupy the same stop (so a naive 'overlapping stop interval' count is always 0)."""
    import xml.etree.ElementTree as ET
    d = os.path.join(RUNS, tag)
    rows = []
    for s in ET.parse(os.path.join(d, "stopinfo.xml")).getroot():
        vid = s.get("id", "")
        if vid.startswith("bus_"):
            rows.append((vid, float(s.get("started")), float(s.get("ended")), s.get("busStop", "")))
    rows.sort(key=lambda r: (r[0], r[1]))
    legs = collections.defaultdict(list)
    byv = collections.defaultdict(list)
    for r in rows:
        byv[r[0]].append(r)
    for vid, rs in byv.items():
        term = [r for r in rs if r[3].startswith("bs_T")]
        for a, b in zip(term, term[1:]):
            side = "EB" if b[3].startswith("bs_TE") else "WB"
            legs[side].append(b[1] - a[2])
            legs["all"].append(b[1] - a[2])
    return {k: sorted(v) for k, v in legs.items()}


def queueing_penalty(M):
    """Paired (CRN) comparison of the two single-charger failure modes against 2 chargers."""
    out = {}
    for cap in [120, 160]:
        base = [leg_times(f"A_cap{cap}_ch2_s{s}") for s in SEEDS]
        for pre, lab in [(f"A_cap{cap}_ch1", "1 charger, session truncation"),
                         (f"B_cap{cap}_ch1queue", "1 charger, queueing")]:
            try:
                alt = [leg_times(f"{pre}_s{s}") for s in SEEDS]
            except Exception:
                continue
            r = {}
            for side in ("EB", "WB", "all"):
                bm = [statistics.mean(x[side]) for x in base]
                am = [statistics.mean(x[side]) for x in alt]
                bp = [x[side][int(0.9 * (len(x[side]) - 1))] for x in base]
                ap = [x[side][int(0.9 * (len(x[side]) - 1))] for x in alt]
                r[side] = dict(mean_leg_s_2ch=[round(x, 1) for x in bm],
                               mean_leg_s_alt=[round(x, 1) for x in am],
                               paired_mean_diff=paired_diff(bm, am),
                               p90_leg_s_2ch=[round(x, 1) for x in bp],
                               p90_leg_s_alt=[round(x, 1) for x in ap],
                               paired_p90_diff=paired_diff(bp, ap))
            # schedule-side paired differences
            b2 = arm(M, f"A_cap{cap}_ch2"); a2 = arm(M, pre)
            r["dep_dev_mean"] = paired_diff([g(m, "schedule", "mean_dep_dev_s") for m in b2],
                                            [g(m, "schedule", "mean_dep_dev_s") for m in a2])
            r["dep_dev_p90"] = paired_diff([g(m, "schedule", "p90_dep_dev_s") for m in b2],
                                           [g(m, "schedule", "p90_dep_dev_s") for m in a2])
            r["missed_departures"] = paired_diff([g(m, "schedule", "n_missed_departures") for m in b2],
                                                 [g(m, "schedule", "n_missed_departures") for m in a2])
            r["headway_cv"] = paired_diff([g(m, "schedule", "headway_cv_pooled") for m in b2],
                                          [g(m, "schedule", "headway_cv_pooled") for m in a2])
            r["charged_kwh"] = paired_diff([g(m, "energy", "fleet", "charged_kwh") for m in b2],
                                           [g(m, "energy", "fleet", "charged_kwh") for m in a2])
            r["min_soc"] = paired_diff([g(m, "energy", "fleet", "min_soc_over_fleet") for m in b2],
                                       [g(m, "energy", "fleet", "min_soc_over_fleet") for m in a2])
            out[f"cap{cap}::{lab}"] = r
    return out


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    M = load_all()
    print(f"loaded {len(M)} runs")
    fr = frontier(M)
    write_csv(os.path.join(OUT, "frontier_table.csv"), fr)
    ed = energy_decomposition(M)
    write_csv(os.path.join(OUT, "energy_decomposition.csv"), ed)
    H = hypotheses(M)
    H["H4_queueing_penalty_paired"] = queueing_penalty(M)
    json.dump(H, open(os.path.join(OUT, "hypothesis_results.json"), "w"), indent=1)
    agg, rows = validity_audit(M)
    json.dump(dict(summary=agg, per_run=rows),
              open(os.path.join(OUT, "validity_audit.json"), "w"), indent=1)
    print(json.dumps(agg, indent=1))
    print("\n--- frontier ---")
    for r in fr:
        print(f'cap={r["cap_kwh"]:>3} ch={r["chargers"]}/{r["policy"]:<5} '
              f'minSOC={r["min_soc_mean"]:.3f}+-{r["min_soc_ci95"]:.3f} '
              f'feasible={r["n_seeds_feasible"]}/{r["n_seeds"]} '
              f'depDev={r["mean_dep_dev_s"]:>6.1f}s p90={r["p90_dep_dev_s"]:>6.1f} '
              f'missed={r["missed_departures_mean"]:>4.1f} cv={r["headway_cv"]:.3f} '
              f'chgd={r["charged_kwh"]:>6.1f}kWh frac={r["frac_pullins_charged"]}')
