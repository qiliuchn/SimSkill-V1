#!/usr/bin/env python3
"""Render the study's markdown deliverable from the machine-readable outputs."""
import os, sys, json, csv, statistics

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(os.path.join(HERE, "..", "..", "..", "outputs"))


def L(x):
    return json.load(open(os.path.join(OUT, x)))


def rows(x):
    return list(csv.DictReader(open(os.path.join(OUT, x))))


def main():
    fr = rows("frontier_table.csv")
    ed = rows("energy_decomposition.csv")
    H = L("hypothesis_results.json")
    V = L("validity_audit.json")["summary"]
    NET = json.load(open(os.path.abspath(os.path.join(HERE, "..", "build",
                                                      "net_verification.json"))))
    AX = L("aux_accounting.json")
    LG = L("leg_energy_decomposition.json")
    P = L("battery_semantics_probe.json")

    o = []
    A = o.append
    A("# Battery-electric bus fleet electrification and charging-infrastructure sizing")
    A("")
    A("SUMO 1.27.1. 10.4 km one-way signalised bus corridor, asymmetric vertical profile, "
      "7-bus fleet, 5.5 h multi-cycle vehicle blocks, endogenous person-driven dwell, "
      "background car traffic. 108 experimental runs + 5 traced reference runs, "
      "3 common-random-number seeds per arm.")
    A("")

    A("## 1. Scenario, verified from the compiled network")
    A("")
    gd = NET["grade_detail"]["EB_2"]
    A(f"- Corridor: 7 signalised links, {len(NET['lane_lengths'])} directed edges; "
      f"realised bus block length **{20.82:.2f} km/round trip** "
      f"(tripinfo `routeLength` 124.9 km over 6 cycles).")
    A(f"- **Grade actually applied**: designed +3.500 % over 2.8 km eastbound (J2->J4); "
      f"compiled net gives **{gd['grade_pct']:.4f} %** on EB_2 and EB_3 "
      f"(dz = {gd['dz_m']} m over a horizontal run of {gd['horiz_m']} m). "
      f"netconvert preserves the node `z` values exactly but shortens the edge at the junctions "
      f"(1400 m designed -> {gd['horiz_m']} m realised), so the realised grade is "
      f"**1.33 % steeper than authored**. All flat edges verified at 0.0000 %.")
    A(f"- Signals: 6 fixed-time controllers, cycle 90 s at every junction, "
      f"progression offsets {NET['tls_offsets']}.")
    A(f"- Structural checks from the compiled net: {len(NET['issues'])} issues "
      f"(bus-only terminal lanes, sidewalk/driving lane permissions, stop positions).")
    A("")

    A("## 2. SUMO battery/charging semantics established before the study "
      "(`outputs/battery_semantics_probe.json`)")
    A("")
    A("| probe | result |")
    A("|---|---|")
    A("| battery parameter names | `device.battery.capacity` / `device.battery.chargeLevel` load "
      "silently; the older `maximumBatteryCapacity` / `actualBatteryCapacity` still work but emit "
      "a deprecation warning |")
    p2 = P["P2_mass_sensitivity"]["pct_change_vs_13000t"]
    A(f"| `mass` honoured? | yes: 13 000 -> 15 000 -> 18 000 kg raises `totalEnergyConsumed` by "
      f"{p2['15000']:+.2f} % and {p2['18000']:+.2f} % |")
    A("| what triggers charging | **position over the chargingStation + speed below the stopping "
      "threshold** - the `<stop>` does not have to name the chargingStation. A `busStop` that "
      "merely overlaps a chargingStation charges (4750.00 Wh, identical to a declared "
      "`<stop chargingStation=...>`); a busStop away from it charges 0.00 Wh |")
    p4 = P["P4_charge_bookkeeping"]
    A(f"| charging ledger | `battery-output` reports `energyCharged` on "
      f"{p4['steps_violating_per_step_identity']} extra steps while the vehicle accelerates away "
      f"inside the station footprint (`timeStopped == 0`); those are **not** credited to "
      f"`actualBatteryCapacity`. Reported {p4['reported_sum_wh']} Wh vs credited "
      f"{p4['credited_sum_wh']} Wh; `chargingstations-output` reports "
      f"{list(p4['chargingstations_output_wh'].values())[0]} Wh, i.e. it matches the CREDITED "
      f"energy and is the authoritative ledger |")
    p5 = P["P5_exhaustion"]
    A(f"| **battery exhaustion** | SUMO does **not** immobilise the vehicle. One warning "
      f"(`{p5['warning'][0].strip()}`), `actualBatteryCapacity` **clamped at exactly 0** (never "
      f"negative), speed unchanged ({p5['speed_after_depletion'][0]} m/s in the last steps), trip "
      f"completed at t={p5['arrival']}. `totalEnergyConsumed` keeps accumulating, so an unclamped "
      f"'virtual' SOC can still be reconstructed - **feasibility is entirely an analyst-side "
      f"judgement; the simulation never reports failure** |")
    A("| chargingStation `power` | a **per-vehicle** rate, not a shared station budget: two "
      "vehicles inside one station each drew the full 150 kW (41.667 Wh/step each). The "
      "`totalPower` attribute, which would express a shared budget, makes SUMO 1.27.1 "
      "**segfault (rc = -11)** as soon as two vehicles charge simultaneously. Charger *count* "
      "must therefore be modelled as physically separate berths |")
    A("")

    A("## 3. Energy decomposition and the auxiliary-load trap")
    A("")
    A("| arm | dist (km) | gross traction (kWh) | auxiliary, naive P x t (kWh) | "
      "regenerated (kWh) | net (kWh) | kWh/km | kWh/km EB | kWh/km WB |")
    A("|---|---|---|---|---|---|---|---|---|")
    for r in ed:
        A(f"| {r['label']} | {r['dist_km']} | {r['traction_gross_kwh']} | {r['auxiliary_kwh']} | "
          f"{r['regenerated_kwh']} | {r['net_energy_kwh']} | {r['kwh_per_km']} | "
          f"{r['kwh_per_km_EB']} | {r['kwh_per_km_WB']} |")
    A("")
    A("The `auxiliary` column above is the naive `constantPowerIntake x time_in_network` product; "
      "the paragraph below shows it is an **upper bound**, not the battery's actual auxiliary "
      "draw. `gross traction` is `totalEnergyConsumed` minus that naive product and is therefore "
      "an indicative split only; the trustworthy figures are `net`, `regenerated` and the "
      "paired-run auxiliary measurement.")
    A("")
    A(f"**Auxiliary validation by re-running with `constantPowerIntake=0`** "
      f"(`outputs/aux_accounting.json`, bus_0 of the CRN-paired pair): the naive "
      f"`P_aux x time_in_network` = {AX['naive_P_times_time_wh']:.0f} Wh, but the measured "
      f"auxiliary draw on the battery is {AX['measured_aux_from_paired_run_wh']:.0f} Wh "
      f"(ratio {AX['ratio_measured_over_naive']}). The whole shortfall of "
      f"{AX['unaccounted_wh']:.0f} Wh is accounted for by "
      f"{AX['steps_where_the_two_runs_agree_exactly']['while_charging']} steps on which the bus "
      f"was taking charge and the two runs agreed **exactly** "
      f"({AX['unaccounted_equals_zero_diff_charging_steps']:.0f} Wh): "
      f"**the auxiliary load is not billed to the battery while the vehicle is plugged in.**")
    A("")
    A(f"The auxiliary energy also does **not** appear wholly in `totalEnergyConsumed`. Of the "
      f"{AX['measured_aux_from_paired_run_wh']:.0f} Wh, "
      f"{AX['split_of_aux']['extra_gross_consumption_wh']:.0f} Wh appears as extra gross "
      f"consumption and {AX['split_of_aux']['lost_regeneration_wh']:.0f} Wh as *lost "
      f"regeneration* (the aux load is partly paid for out of recuperated power). Auxiliary "
      f"energy must be measured on **net** energy from a paired aux=0 run.")
    A("")
    A(f"Fleet totals (240 kWh, 2 chargers, 3 seeds): gross traction 1111.8 kWh, "
      f"regenerated 551.0 kWh, net 835.4 kWh over 874.4 km. Auxiliary measured as "
      f"net(aux=7 kW) - net(aux=0) = 835.4 - 615.3 = **220.1 kWh = 26.3 % of net energy** "
      f"(the naive P x t product would have said 274.6 kWh = 32.9 %).")
    A("")
    A(f"**Regeneration is real and large**: 551.0 kWh recuperated against 1386.4 kWh gross "
      f"consumption = **39.7 % of gross traction+auxiliary energy recovered**. Identified in the "
      f"raw per-step output as steps with `energyConsumed < 0` and a growing "
      f"`totalEnergyRegenerated`; the regen=0 control arm reports "
      f"`totalEnergyRegenerated = 0.00` at every step.")
    A("")
    A("**Energy balance.** For every run with no depleted bus, "
      "`initial - totalEnergyConsumed + totalEnergyRegenerated + credited_charge - final` closes "
      f"to at most **{V['max_abs_balance_residual_wh_no_depletion']} Wh** over ~20 000 steps x 7 "
      f"buses (all 97 such runs). `chargingstations-output` and the credited battery charge agree "
      f"to at most **{V['max_abs_ledger_diff_wh']} Wh** across all 108 runs (2-decimal rounding in "
      f"the station file). In the {V['n_runs_with_depletion']} runs containing a depleted bus the "
      f"residual is not an error - SUMO clamps SOC at 0, so the residual **is** the unserved "
      f"energy deficit (max {V['max_abs_balance_residual_wh_with_depletion']/1000:.1f} kWh).")
    A("")

    A("## 4. Feasibility frontier (battery capacity x terminal chargers)")
    A("")
    A("Feasible = minimum state of charge over every bus in the fleet stays at or above the "
      "0.20 reserve for the whole 5.5 h block, in **all three** CRN seeds. `min SOC` is the "
      "unclamped ('virtual') SOC reconstructed from the cumulative counters, so a negative value "
      "is a genuine energy deficit rather than SUMO's clamped zero.")
    A("")
    A("| capacity | chargers/terminal | conflict policy | min SOC (mean +- 95% CI) | seeds "
      "feasible | buses depleted | charge delivered (kWh) | pull-ins charged | mean dep. "
      "delay (s) | p90 dep. delay (s) | missed departures | headway CV |")
    A("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in fr:
        A(f"| {r['cap_kwh']} kWh | {r['chargers']} | {r['policy']} | "
          f"{float(r['min_soc_mean']):+.3f} +- {float(r['min_soc_ci95']):.3f} | "
          f"{r['n_seeds_feasible']}/{r['n_seeds']} | {r['buses_depleted_max']} | "
          f"{r['charged_kwh']} | {float(r['frac_pullins_charged'])*100:.0f}% | "
          f"{r['mean_dep_dev_s']} | {r['p90_dep_dev_s']} | {r['missed_departures_mean']} | "
          f"{r['headway_cv']} |")
    A("")
    A("Minimum feasible combination: **120 kWh battery + 1 electrified berth per terminal at "
      "120 kW**, provided the single charger is operated as a queue (every pull-in charges) or "
      "the bus can tolerate charging on only every second pull-in. Depot-only operation needs "
      "**200 kWh**. See `outputs/feasibility_frontier.png`.")
    A("")

    A("## 5. Hypotheses")
    A("")
    h1 = H["H1_tsp"]
    A("### H1 - auxiliary energy is large and congestion-growing, so a delay-reducing measure "
      "saves more energy than its traction saving implies")
    A("")
    A("**Partly accepted, with the hypothesised mechanism rejected.**")
    A("")
    A(f"- Auxiliary share of net energy = **26.3 %** (validated, section 3) - large, as claimed.")
    lg = LG["paired_leg_aux"]
    A(f"- **Congestion dependence, measured leg by leg** (`outputs/leg_energy_decomposition.json`, "
      f"paired aux=7 kW / aux=0 legs): eastbound peak legs run "
      f"{lg['EB']['peak']['dur_s']:.0f} s at {lg['EB']['peak']['speed_kmh']:.1f} km/h vs "
      f"{lg['EB']['offpeak']['dur_s']:.0f} s at {lg['EB']['offpeak']['speed_kmh']:.1f} km/h "
      f"off-peak; auxiliary share rises from **{lg['EB']['offpeak']['aux_share_true']*100:.1f} % "
      f"to {lg['EB']['peak']['aux_share_true']*100:.1f} %**. Of the "
      f"{(lg['EB']['peak']['net_kwh']-lg['EB']['offpeak']['net_kwh'])*1000:.0f} Wh extra energy a "
      f"peak eastbound leg costs, "
      f"{(lg['EB']['peak']['aux_true_kwh']-lg['EB']['offpeak']['aux_true_kwh'])*1000:.0f} Wh "
      f"({100*(lg['EB']['peak']['aux_true_kwh']-lg['EB']['offpeak']['aux_true_kwh'])/(lg['EB']['peak']['net_kwh']-lg['EB']['offpeak']['net_kwh']):.0f} %) "
      f"is auxiliary, not traction. Binned by realised leg speed the auxiliary share rises "
      f"monotonically in trend from 19.2 % at 39-42 km/h to 38.7 % at 9-12 km/h.")
    A(f"- **Transit signal priority** (conditional TSP, min cross green 12 s, 1 grant/signal/cycle; "
      f"302 grants in seed 1 -- 204 truncations, 98 extensions -- verified against "
      f"`phase_trace.json`: the 136 truncations found in the retained trace realised a mean cross "
      f"green of **17.8 s against a nominal 26.0 s**, the 49 matched extensions realised "
      f"**60.5 s against a nominal 56.0 s**, and the residual offset debt was exactly 0.0 s at all "
      f"six signals at the end of the run, so every grant is a bounded, repaid perturbation): "
      f"mean in-vehicle ride duration fell from "
      f"{statistics.mean(h1['bus_ride_duration_off_s']):.1f} s to "
      f"{statistics.mean(h1['bus_ride_duration_on_s']):.1f} s. Net fleet energy fell by "
      f"**{-h1['total_energy_saving_kwh']['mean_diff']:.2f} kWh** "
      f"(95% CI {-h1['total_energy_saving_kwh']['hi']:.2f} to "
      f"{-h1['total_energy_saving_kwh']['lo']:.2f}, n=3, **not significant**), while the "
      f"traction-only saving measured in the aux=0 arms was "
      f"**{-h1['traction_only_saving_kwh']['mean_diff']:.2f} kWh** "
      f"(CI {-h1['traction_only_saving_kwh']['hi']:.2f} to "
      f"{-h1['traction_only_saving_kwh']['lo']:.2f}, significant). The total saving is "
      f"**3.24x the traction-only saving**, which is the direction H1 predicts.")
    A(f"- **But the mechanism is not the hypothesised one.** The block is schedule-bound: buses "
      f"depart terminals on `until`, so TSP does not shorten time in service at all "
      f"(P_aux x time is 274.58 kWh in both arms, identical to 2 decimals). The extra "
      f"9.30 kWh saving comes from the *charging* side - arriving earlier means more terminal "
      f"dwell spent plugged in, and the auxiliary load is not billed to the battery while "
      f"charging (section 3). Measured auxiliary draw: 220.1 kWh (TSP off) vs 210.8 kWh (TSP on). "
      f"On a schedule-bound block, a delay-reducing measure moves auxiliary load onto the "
      f"charger; it does not remove it.")
    A("")

    h2 = H["H2_regen_stop_density"]
    A("### H2 - with regeneration, kWh/km is much less sensitive to stop frequency")
    A("")
    A("**Accepted.**")
    A("")
    A("| stops per direction | regen on (kWh/km) | regen off (kWh/km) |")
    A("|---|---|---|")
    A(f"| 12 | {statistics.mean(h2['12_stops']['regen_on_kwh_per_km']):.4f} | "
      f"{statistics.mean(h2['12_stops']['regen_off_kwh_per_km']):.4f} |")
    A(f"| 6 | {statistics.mean(h2['6_stops']['regen_on_kwh_per_km']):.4f} | "
      f"{statistics.mean(h2['6_stops']['regen_off_kwh_per_km']):.4f} |")
    s = h2["sensitivity_to_stop_density"]
    A("")
    A(f"Doubling stop density costs **{s['with_regen_delta_kwh_per_km']['mean_diff']:.4f} kWh/km "
      f"(95% CI {s['with_regen_delta_kwh_per_km']['lo']:.4f} to "
      f"{s['with_regen_delta_kwh_per_km']['hi']:.4f}) with regeneration** but "
      f"**{s['without_regen_delta_kwh_per_km']['mean_diff']:.4f} kWh/km "
      f"(CI {s['without_regen_delta_kwh_per_km']['lo']:.4f} to "
      f"{s['without_regen_delta_kwh_per_km']['hi']:.4f}) without** - "
      f"**2.39x more sensitive** in absolute terms, and 9.8 % vs 7.0 % in relative terms. Both "
      f"paired differences are significant at 95 % with n=3. A no-regen design assumption would "
      f"also over-state the absolute consumption level by 73 % (1.6505 vs 0.9554 kWh/km).")
    A("")

    h3 = H["H3_direction"]
    A("### H3 - grade asymmetry hides a direction-specific SOC minimum that governs feasibility")
    A("")
    A("**Accepted.**")
    A("")
    A(f"Round-trip mean **{statistics.mean(h3['kwh_per_km_round_trip']):.4f} kWh/km** decomposes "
      f"into **{statistics.mean(h3['kwh_per_km_EB']):.4f} kWh/km eastbound (uphill)** and "
      f"**{statistics.mean(h3['kwh_per_km_WB']):.4f} kWh/km westbound (downhill)** - a ratio of "
      f"**{statistics.mean(h3['ratio_EB_over_WB']):.2f}x** over 3 seeds. The eastbound rate is "
      f"**{100*(statistics.mean(h3['kwh_per_km_EB'])/statistics.mean(h3['kwh_per_km_round_trip'])-1):.1f} % "
      f"above the round-trip average**, so a battery sized on the round-trip figure is that much "
      f"short for the leg that actually sets the minimum. The SOC traces "
      f"(`outputs/soc_trajectories.png`, panel C: 80 kWh, 2 chargers, seed 1) show bus_0 reaching "
      f"**SOC 0.0534 at t = 16 340 s (4.54 h) in mid-block** and then recovering to **0.6341** by "
      f"the end of the block: the governing minimum is a mid-block, direction-specific event that "
      f"neither the start-of-block nor the end-of-block SOC reveals.")
    A("")
    A("**Feasibility is also set by one bus, not by the fleet mean.** In that same run the seven "
      "buses' minimum SOCs are 0.0534, 0.3446, 0.7320, 0.6428, 0.6667, 0.7218, 0.7205 - bus_0, "
      "the first departure, runs the peak eastbound legs and realises 1.4143 kWh/km eastbound "
      "against 1.313-1.331 for the rest. A fleet-average SOC of 0.55 would have called this cell "
      "comfortably feasible; the worst bus is at 0.05.")
    A("")

    A("### H4 - charger count is set by peak coincident arrivals, not mean energy demand")
    A("")
    A("**Accepted in its conclusion; one of its two proposed failure modes was not observed.**")
    A("")
    A("A mean-based sizing would pass one charger per terminal comfortably: with 2 chargers the "
      "busiest berth is occupied only **38.0 %** of the service period, and one 120 kW charger "
      "delivers more energy per cycle than a cycle consumes. Yet one charger is not equivalent "
      "to two:")
    A("")
    A("- **Session truncation** (arrivals alternate between an electrified and a plain berth): "
      "delivered charge halves, 486.6 kWh vs 830-946 kWh, exactly 50 % of pull-ins charged. "
      "This moves the feasibility threshold from 80 kWh (2 chargers, min SOC +0.147, still just "
      "below reserve) to 120 kWh. **Zero schedule cost**: terminal-to-terminal leg times are "
      "bit-identical to the 2-charger arm (paired difference 0.0 s, sd 0.0).")
    q = H["H4_queueing_penalty_paired"]["cap120::1 charger, queueing"]
    A(f"- **Queueing** (every bus is sent to the single electrified berth): full energy delivered "
      f"(paired difference vs 2 chargers {q['charged_kwh']['mean_diff']:+.1f} kWh, CI "
      f"+-{q['charged_kwh']['ci95_halfwidth']:.1f}, n.s.), busiest berth utilisation rises "
      f"0.380 -> 0.565-0.603, and the **eastbound terminal-to-terminal leg time rises by "
      f"{q['EB']['paired_mean_diff']['mean_diff']:+.1f} s "
      f"(95% CI {q['EB']['paired_mean_diff']['lo']:+.1f} to "
      f"{q['EB']['paired_mean_diff']['hi']:+.1f}, n=3)** while the westbound leg is unaffected "
      f"({q['WB']['paired_mean_diff']['mean_diff']:+.1f} s). The delay is entirely a pull-in "
      f"queue at the east terminal.")
    A(f"- **Null result on the hypothesised schedule symptom.** Despite ~108 s of extra eastbound "
      f"leg time, mean terminal departure deviation changed by only "
      f"{q['dep_dev_mean']['mean_diff']:+.2f} s (CI +-{q['dep_dev_mean']['ci95_halfwidth']:.2f}), "
      f"missed departures by {q['missed_departures']['mean_diff']:+.2f} and headway CV by "
      f"{q['headway_cv']['mean_diff']:+.4f} - **none significant**. The scheduled layover slack "
      f"absorbs the queueing delay, so charger contention did **not** show up as headway "
      f"variability or bunching. It showed up as longer in-service running time and as delivered "
      f"energy. Measuring charger sizing through headway CV alone would have missed the effect "
      f"entirely.")
    A(f"- **Berth-overlap counting is a trap**: SUMO never lets two vehicles occupy the same "
      f"stopping place, so a naive 'overlapping stop intervals' counter reads exactly 0 in every "
      f"one of the 108 runs, including the saturated single-charger arms. Contention has to be "
      f"measured as the extra time from the previous terminal departure to the next berth "
      f"occupancy.")
    A("")

    h5 = H["H5_capacity_mass"]
    A("### H5 - added capacity adds mass, so range per added kWh diminishes")
    A("")
    A("**Accepted, with a clean isolation of the mechanism.**")
    A("")
    A("| capacity | mass (kg) | kWh/km, mass coupled | kWh/km, mass held at the 200 kWh value | "
      "usable range (0.9->0.2 SOC, km) | marginal km per added kWh |")
    A("|---|---|---|---|---|---|")
    caps = sorted(int(c) for c in h5["coupled"])
    for i, c in enumerate(caps):
        cc, ff = h5["coupled"][str(c)], h5["fixed_mass"][str(c)]
        marg = ""
        if i > 0:
            k = f"{caps[i-1]}->{c}"
            marg = (f"{h5['marginal_km_per_added_kwh'][k]:.4f} "
                    f"(fixed mass {h5['marginal_km_per_added_kwh_fixed_mass'][k]:.4f})")
        A(f"| {c} kWh | {cc['mass_kg']:.0f} | {cc['mean']:.5f} +- {cc['ci95']:.5f} | "
          f"{ff['mean']:.5f} | {h5['usable_range_km'][str(c)]:.2f} | {marg} |")
    A("")
    A("With mass held constant the consumption rate is **identical to 5 decimal places at every "
      "capacity** (0.94466 kWh/km) and the marginal range is a flat 0.7410 km per added kWh - so "
      "the entire effect is the mass channel and nothing else. With mass coupled at 7 kg/kWh, "
      "consumption rises +4.70 % from 80 to 240 kWh (+8.26 % mass, elasticity 0.57) and the "
      "marginal return falls monotonically from **0.7404 to 0.6911 km per added kWh, a 6.7 % "
      "loss** across the tested range.")
    A("")
    A("Fitting the two endpoints exactly gives `rate(C) = 0.89098 + 0.00026838 C` kWh/km, so "
      "usable range `R(C) = 0.7 C / rate(C)` is monotonically increasing but bounded above by "
      "`0.7 / 0.00026838 = 2608 km`, with `dR/dC = 0.7 x 0.89098 / rate(C)^2` "
      "(0.683 km/kWh at C = 240 kWh, consistent with the 0.691 finite difference over 200->240). "
      "Diminishing returns are real but never turn negative in this parameterisation; the "
      "extrapolation is far outside the tested range and is quoted only to characterise the "
      "shape.")
    A("")

    A("## 6. Charging-strategy comparison")
    A("")
    st = H["strategy_comparison"]
    A("| strategy | capacity | min SOC (3 seeds) | feasible | charge delivered (kWh) | mean dep. "
      "delay (s) | missed departures | headway CV | mean rider wait (s) |")
    A("|---|---|---|---|---|---|---|---|---|")
    for k, v in st.items():
        cap, lab = k.split("::")
        A(f"| {lab} | {cap.replace('cap','')} kWh | "
          f"{statistics.mean(v['min_soc']):+.3f} | {sum(v['feasible'])}/3 | "
          f"{statistics.mean(v['charged_kwh']):.1f} | "
          f"{statistics.mean(v['mean_dep_dev_s']):.1f} | "
          f"{statistics.mean(v['missed_departures']):.1f} | "
          f"{statistics.mean(v['headway_cv']):.3f} | "
          f"{statistics.mean(v['ride_wait_s']):.1f} |")
    A("")
    A("**The mid-day depot recharge is a clear negative result.** Pulling four of seven buses out "
      "of service for 1 200 s each at a 60 kW depot charger delivered only 89.4 kWh to the whole "
      "fleet (vs 860 kWh from terminal charging), moved minimum SOC by +0.012 at 160 kWh, and did "
      "**not** restore feasibility at either 120 or 160 kWh - while degrading the service badly: "
      "mean terminal departure deviation 29.6 s -> 181.9 s, missed departures 10.7 -> 25.7, "
      "headway CV 0.308 -> 0.597, mean rider wait 503.7 s -> 561.1 s. The service gap it opens "
      "costs far more than the energy it buys, because a 60 kW depot charger over 20 minutes is "
      "worth about one sixth of a bus's block energy.")
    A("")
    pw = H["charger_power_sweep"]
    A("**Charger power saturates.** At one charger per terminal and 80 kWh batteries, raising "
      f"terminal power from 120 kW to 200 kW raised delivered charge from "
      f"{statistics.mean(pw['120kW_cap80']['charged_kwh']):.1f} kWh to "
      f"{statistics.mean(pw['200kW_cap80']['charged_kwh']):.1f} kWh and min SOC from "
      f"{statistics.mean(pw['120kW_cap80']['min_soc']):+.3f} to "
      f"{statistics.mean(pw['200kW_cap80']['min_soc']):+.3f}; raising it further to 300 kW changed "
      f"**nothing at all** (identical delivered charge and min SOC to 4 decimals in every seed), "
      f"because the binding constraint becomes the SOC headroom in the battery, not the charger. "
      f"Neither power level restored feasibility at 80 kWh with one charger.")
    A("")

    A("## 7. Sizing decision rule")
    A("")
    A("1. **Size the battery on the worst directional inter-charge drawdown, never on the "
      "round-trip average.** Required usable energy is `max over legs (E_leg between consecutive "
      "charge opportunities)` plus the reserve, not `mean kWh/km x block km / n_charges`. Here "
      "that is a factor 1.48 difference between the eastbound and the round-trip rate.")
    A("2. **Compute the capacity with the mass feedback closed.** `C >= E_required / (SOC_start - "
      "SOC_reserve)` where the consumption rate used to compute `E_required` is itself a function "
      "of `C`. Solve the fixed point; iterating twice is enough at 7 kg/kWh.")
    A("3. **Size chargers on peak coincident pull-ins, not on mean berth utilisation or mean "
      "energy.** Required electrified berths = the maximum number of buses simultaneously in the "
      "terminal layover window under the *realised* (not scheduled) arrival distribution. Mean "
      "utilisation of 0.38 hid a real one-vs-two-charger difference here.")
    A("4. **Then check what a shortfall actually costs in this system.** If arriving buses queue, "
      "the cost is in-service running time (+108 s per eastbound leg here); if they are diverted "
      "to a plain berth, the cost is charge (-50 % delivered energy). Which of the two applies is "
      "an operating-policy choice, and only the second one moved the feasibility frontier.")
    A("5. **Do not size on charger power beyond the point where the battery's SOC headroom binds.** "
      "Verify by sweeping power and checking that delivered energy still responds.")
    A("6. **Verify feasibility from the unclamped SOC trace, per bus, over the whole block.** "
      "SUMO's own SOC is clamped at 0 and a depleted bus keeps driving, so a run that looks "
      "'completed' can be deeply infeasible.")
    A("")

    A("## 8. Validity audit")
    A("")
    A(f"- Runs: **{V['n_runs']}**; teleports: **{V['total_teleports']}** "
      f"(runs with a bus teleport: {V['runs_with_bus_teleports']}); "
      f"skipped stops: **{V['total_stops_skipped']}**.")
    A(f"- Every bus completed its full block in **{V['runs_all_blocks_complete']}/{V['n_runs']}** "
      f"runs (156 scheduled stop events per bus: 6 cycles x (12 + 1 + 12 + 1); verified per bus "
      f"from `stop-output`).")
    A(f"- Persons: 2400 per run, **{V['total_persons_without_ride']}** persons failed to complete "
      f"a ride stage in any run. Dwell is endogenous: mean 13.0 s at "
      f"`boardingDuration=2.0 s/passenger` with a 5 s door time.")
    A(f"- Energy balance residual (no-depletion runs): "
      f"<= {V['max_abs_balance_residual_wh_no_depletion']} Wh. Charging-ledger cross-check: "
      f"<= {V['max_abs_ledger_diff_wh']} Wh.")
    A("- Incomplete vehicles at the simulation horizon are background cars still en route when "
      "the run ends (~410 of ~33 750 per run, 1.2 %); no bus is ever unfinished.")
    A("- Common random numbers: the car route file and the 2 400-person demand file are generated "
      "once per seed and shared byte-identically across every arm, so paired differences isolate "
      "the treatment. Verified: net fleet energy is identical to 0.1 kWh across charger-count "
      "arms at fixed capacity and seed, i.e. charging does not perturb driving.")
    A("")
    A("## 9. Files")
    A("")
    A("- `outputs/frontier_table.csv`, `outputs/feasibility_frontier.png` - the frontier")
    A("- `outputs/soc_trajectories.png` - per-bus SOC over the block, four strategies")
    A("- `outputs/energy_decomposition.csv`, `outputs/energy_decomposition.png`")
    A("- `outputs/hypothesis_results.json` - every hypothesis test with per-seed values and CIs")
    A("- `outputs/battery_semantics_probe.json` - the SUMO-behaviour probes of section 2")
    A("- `outputs/aux_accounting.json`, `outputs/leg_energy_decomposition.json`")
    A("- `outputs/validity_audit.json` - per-run teleport/completion/balance audit")
    A("- `attempts/attempt-1/scripts/` - the full pipeline")
    A("")
    open(os.path.join(OUT, "REPORT.md"), "w").write("\n".join(o))
    print("wrote", os.path.join(OUT, "REPORT.md"), len(o), "lines")


if __name__ == "__main__":
    main()
