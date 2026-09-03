---
name: size-battery-electric-bus-fleet-and-chargers
description: Use this skill when the user wants to size a battery-electric bus (BEB) fleet in SUMO - choosing battery capacity, number and power of terminal opportunity chargers, or comparing depot-only vs terminal vs mid-day-depot charging strategies - and needs a feasibility verdict rather than just an energy total. Covers multi-cycle vehicle blocks with scheduled layover, charging-berth contention (SUMO's chargingStation `power` is per-vehicle and `totalPower` segfaults, so charger COUNT must be physical berths), the exact battery-output/chargingstations-output bookkeeping rules, the constantPowerIntake auxiliary-load trap, directional grade asymmetry, mass-coupled capacity sizing, and the fact that SUMO never immobilises a depleted vehicle so feasibility is entirely an analyst-side judgement. Trigger on mentions of electric bus, BEB, e-bus fleet electrification, opportunity charging, pantograph charger, charger sizing, battery sizing, depot charging, state-of-charge feasibility, or kWh/km for transit.
---

# Size a Battery-Electric Bus Fleet and its Chargers

Turns `simulate-ev-charging`'s single-vehicle battery mechanics into a fleet **sizing study**:
a battery-capacity x charger-count feasibility frontier for a scheduled bus line, with every
energy and feasibility number re-derived from raw `battery-output` /
`chargingstations-output` rather than from an assumed consumption constant. The distinguishing
problem is that **SUMO will happily simulate an infeasible fleet** - a bus whose battery hits
zero keeps driving at full speed and completes its block - so the study has to construct its own
failure criterion.

## Establish the battery/charging semantics BEFORE the study

`scripts/probe_battery_semantics.py` runs seven micro-probes against the installed binary and
writes a JSON record. Run it first, every time; the answers below were all verified on SUMO
1.27.1 and several contradict the intuitive reading of the documentation.

1. **Parameter names.** `device.battery.capacity` / `device.battery.chargeLevel` load silently.
   The older `maximumBatteryCapacity` / `actualBatteryCapacity` still work but emit a
   deprecation warning. `mass` is a plain `vType` attribute and **is** honoured by
   `Energy/unknown` (13 000 -> 18 000 kg raised `totalEnergyConsumed` by 21.9 %).
2. **What actually triggers charging.** Position over the chargingStation plus speed below the
   stopping threshold - **not** the `<stop>` naming the chargingStation. A `busStop` that merely
   overlaps a chargingStation charges exactly as much as a declared
   `<stop chargingStation="..."/>` (4750.00 Wh in both). This is what makes a
   "layover berth that happens to be electrified" modellable at all.
3. **The charging ledger.** `battery-output`'s `energyCharged` is reported for every step the
   vehicle is inside the station footprint, **including the departure acceleration after its
   stop has ended** (`timeStopped == 0`) - and those steps are **not** credited to
   `actualBatteryCapacity`. Summing `energyCharged` over-states delivery (4908.33 vs 4750.00 Wh
   in the probe). `chargingstations-output` matches the **credited** energy and is the
   authoritative ledger. Either read that file, or filter `battery-output` rows to
   `timeStopped > 0` (this closes the fleet energy balance to <0.21 Wh over ~20 000 steps x 7
   buses).
4. **Exhaustion behaviour.** One `Battery of vehicle 'X' is depleted` warning, then
   `actualBatteryCapacity` is **clamped at exactly 0** (never negative) and the vehicle keeps
   driving at full speed and finishes its trip. `totalEnergyConsumed` keeps accumulating, so
   reconstruct an **unclamped "virtual" SOC** from
   `initial - totalEnergyConsumed + totalEnergyRegenerated + credited_charge` - that is the only
   quantity that can express *how* infeasible a cell is.
5. **`chargingStation power` is a per-vehicle rate, not a station budget.** Two vehicles inside
   one station each drew the full 150 kW. The `totalPower` attribute, which would express a
   shared budget, **segfaults SUMO 1.27.1 (rc = -11)** the instant two vehicles charge
   simultaneously. **Charger count therefore has to be modelled as physically separate berths**
   (separate short chargingStations on separate lanes), never as one station's power.

## Build the scenario

`scripts/build_net.py` + `scripts/scenario.py` build a signalised bus corridor with terminals:

- **Grade.** Author `z` on plain-XML nodes; `netconvert` preserves it by default. **Verify the
  realised grade from the compiled net's lane `shape` triples** - netconvert keeps the node `z`
  exactly but shortens the edge at junctions, so a designed 3.500 % over a 1400 m edge comes out
  as **3.5466 %** over the realised 1381.6 m run (1.33 % steeper than authored). Never quote the
  authored grade.
- **Terminals as berths.** A bus-only terminal edge with one lane per layover berth; a short
  `chargingStation` over the berth on the berths that are electrified, plus a longer, lower-power
  depot charger on its own lane. Charger count = how many berths carry a chargingStation.
- **Blocks, not trips.** One `<vehicle>` per bus whose route repeats the round trip N times, with
  every en-route `<stop>` written out explicitly (a route's `repeat` attribute does not repeat
  `<stop>` children - see `demonstrate-and-control-bus-bunching`). Terminal layover stops carry
  `duration="<minimum>" until="<scheduled departure>"`, so an early bus charges longer and a late
  bus departs late - the schedule pressure is endogenous.
- **Endogenous dwell** via `boardingDuration` and real `walk -> ride -> walk` person demand, as in
  `design-bus-stop-placement-type-and-spacing`; background car flows sized to congest one peak
  direction.
- **Berth rotation gotcha.** Assign the berth by the **global pull-in index** `n = bus + cycle *
  n_buses`, not by `(bus + cycle) % 2`. If `n_buses` is even, `n % 2` collapses to `bus % 2` and a
  single-charger "skip" policy then systematically starves the odd buses; choose an **odd**
  `n_buses` so the assignment actually rotates. Getting this wrong also produces berth collisions
  that teleport buses out of their layover.

## Two distinct single-charger failure modes - model both

A shortfall of chargers can express itself in two completely different ways, and they have to be
separated because only one of them moves the frontier:

- **Session truncation** - arrivals keep alternating berths but only one berth is electrified, so
  every second pull-in gets no charge. Halves delivered energy; **zero** schedule cost
  (leg times bit-identical to the 2-charger arm).
- **Queueing** - every bus is sent to the single electrified berth and waits behind an occupant.
  Full energy delivered; the cost is in-service running time.

**Do not measure contention by counting overlapping stop intervals.** SUMO never lets two vehicles
occupy the same stopping place, so that counter reads exactly 0 in every run including the
saturated ones. Measure it as the **terminal-departure-to-next-berth-occupancy leg time**, paired
across arms under common random numbers (`scripts/analyze.py: leg_times/queueing_penalty`).

## The auxiliary-load trap: never trust `P_aux x time`

`constantPowerIntake` is the HVAC/auxiliary load, and it is genuinely large (26 % of net battery
energy at 7 kW on a 13.5 t bus). But:

- **It is not billed to the battery while the vehicle is taking charge.** The naive
  `P_aux x time_in_network` over-states the real draw by exactly
  `(charging steps) x P_aux / 3600` (39 225 Wh predicted vs 34 150 Wh measured for one bus;
  the 5 075 Wh gap matched 2 609 charging steps to 2 Wh).
- **It does not appear wholly in `totalEnergyConsumed` either.** Part of it is paid for out of
  recuperated power, so it shows up as *lost regeneration*: of 34 150 Wh, 26 188 Wh was extra
  gross consumption and 7 963 Wh was regeneration that never happened.

**Always measure auxiliary energy as `net(aux=P) - net(aux=0)` from a CRN-paired re-run**
(`scripts/aux_accounting.py`), where `net = totalEnergyConsumed - totalEnergyRegenerated`. On
in-motion legs with no charging the paired measurement matches `P x t` to a ratio of 1.0000, which
is the check that the accounting is right.

## Measure by direction and by leg, not by round trip

`scripts/battery_reduce.py` streams `battery-output` and splits each bus's per-step record by
edge into eastbound / westbound / terminal, giving kWh/km per direction, an unclamped SOC trace,
and an explicit balance residual. On a corridor with a sustained 3.5 % grade over 27 % of its
length, the **round-trip mean hid a 2.88x directional ratio** (1.381 vs 0.480 kWh/km); the
uphill rate was 47.8 % above the round-trip average. `scripts/leg_energy.py` goes further and
gives per-leg energy against realised leg speed, which is what shows the auxiliary share rising
with congestion (19.2 % at 39-42 km/h to 38.7 % at 9-12 km/h).

## Close the energy balance and report the residual

For every bus: `initial - totalEnergyConsumed + totalEnergyRegenerated + credited_charge - final`.
This closed to <= 0.21 Wh in all 97 runs with no depleted bus. **A large residual in a run
containing a depleted bus is not a bug** - it equals the unserved energy deficit created by
SUMO's clamp at zero. Split the audit on depletion or the headline residual is meaningless.

## Experiment design

`scripts/experiments.py` runs the whole matrix in a process pool with **common random numbers**:
the car route file and the person-demand file are generated once per seed and shared
byte-identically by every arm. Verify CRN worked by checking that net fleet energy is identical
across charger-count arms at fixed capacity and seed (charging must not perturb driving). Use at
least 3 seeds and report paired-t confidence intervals; with n=3 the CI is wide enough that real
effects (e.g. a 1.6 % fleet energy saving) come out non-significant, and that should be stated
rather than hidden.

Minimum useful matrix: capacity x charger count x seed, plus a **mass-decoupled control sweep**
(hold vehicle mass at one capacity's value) to prove that any capacity-driven consumption change
is the mass channel, plus `aux=0` and `regen=0` control arms.

## Sizing decision rule this produces

1. Size the battery on the **worst directional inter-charge drawdown**, not the round-trip mean.
2. Close the **mass feedback**: `C >= E(C) / (SOC_start - SOC_reserve)`; two fixed-point iterations
   suffice at 7 kg/kWh.
3. Size chargers on **peak coincident pull-ins**, not mean berth utilisation - a mean utilisation
   of 0.376-0.389 hid a real one-vs-two-charger difference.
4. Decide which shortfall mode the operating policy implies (queue -> running time; divert ->
   charge), because only the charge-losing mode moved the frontier.
5. Stop increasing charger power once the **battery's SOC headroom** binds - 200 kW and 300 kW gave
   identical delivered energy and identical min SOC in every seed.
6. Judge feasibility from the **unclamped per-bus SOC trace over the whole block**, and from the
   **worst bus**, not the fleet mean (a fleet-mean min SOC of 0.55 hid a worst bus at 0.05).

## Gotchas

- **`--chargingstations-output` is not a small file.** In 1.27.1 it writes one `<step>` child per
  charging time step per vehicle (6.9 MB for 84 sessions). `--chargingstations-output.aggregated`
  gives the compact form, but with a **different schema** (`<chargingEvent>` elements, no
  per-station `totalEnergyCharged` roll-up) - a parser for one will not read the other.
- **`totalPower` on a chargingStation segfaults SUMO 1.27.1** with two simultaneous chargers.
- **Sort `<flow>` elements by `begin`.** SUMO silently drops out-of-order flows with only a
  `Route file should be sorted by departure time, ignoring 'fN'!` warning - in a first attempt
  here that removed all 12 cross-street flows and the corridor ran with no cross traffic at all.
- **A TSP controller's offset-recovery loop can silently cancel its own grants.** If recovery
  flexes the same cross-street phase that truncation shortens, it repays the debt inside the same
  phase instance and the truncation never happens - the grant log still records it. Guard recovery
  against (a) the phase instance a grant was just issued in and (b) any bus currently approaching,
  and verify against `phase_trace.json` that a logged 10 s truncation really produced a 16 s
  realised green against a 26 s nominal one.
- **On a schedule-bound block, delay reduction does not reduce auxiliary energy** - the bus departs
  the terminal on `until` regardless, so time in service is unchanged. What TSP actually bought
  here was more time plugged in, which is where its extra saving came from.

## Scripts

- `probe_battery_semantics.py` - the seven pre-study probes (run first).
- `build_net.py` - graded corridor, two-pass netconvert with a coordinated program, compiled-net
  verification of grade / lane permissions / offsets.
- `scenario.py` - berths, chargers, BEB vType, multi-cycle blocks, car and person demand.
- `runner.py` / `tsp_runner.py` - one cell, command-line or TraCI-with-TSP (identical stepping loop
  in `--mode off`).
- `battery_reduce.py` - streaming `battery-output` reducer (SOC traces, directional energy,
  balance residual).
- `metrics.py` - per-run reduction: energy, schedule adherence, berth contention, validity.
- `experiments.py` - the CRN experiment matrix in a process pool.
- `analyze.py` - frontier table, hypothesis tests with paired CIs, leg-time contention analysis,
  validity audit.
- `aux_accounting.py` / `leg_energy.py` - the auxiliary-load validation and per-leg decomposition.
- `make_figures.py` (needs the traced reference runs' `battery.xml` retained) / `write_report.py`.

## Related

- `simulate-ev-charging` - the single-vehicle battery device, chargingStation and stationfinder
  mechanics this skill scales up to a fleet; **corrects** its claim that `chargingstations-output`
  is "much smaller than battery-output".
- `model-road-gradient-effects-on-energy` - the z-coordinate authoring and verify-from-compiled-net
  discipline, extended here with the junction-shortening grade overstatement.
- `simulate-multimodal-transit`, `design-bus-stop-placement-type-and-spacing` - busStop / pedestrian
  access / endogenous-dwell demand construction reused unchanged.
- `demonstrate-and-control-bus-bunching` - headway CV measurement from raw stop-output, and the
  "`repeat` does not repeat `<stop>` children" gotcha.
- `implement-transit-signal-priority` - the TSP controller design; this skill found and fixed a
  recovery-cancels-its-own-grant bug in that pattern.
- `quantify-sumo-run-to-run-variability` - the CRN/paired-t replication discipline used throughout.
- `analyze-simulation-outputs` - tripinfo/summary/stop-output parsing conventions.
- [[battery-electric-bus-energy-and-charger-sizing]] - the verified findings, SUMO semantics and
  traps this workflow is built on.
- [[electric-vehicle-battery-and-charging]] - the underlying battery-device concepts.
