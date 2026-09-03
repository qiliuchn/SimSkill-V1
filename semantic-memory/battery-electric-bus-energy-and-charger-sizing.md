---
summary: How SUMO's battery device and chargingStation actually behave for a scheduled electric-bus fleet - charging is triggered by position not by the stop's declared target, charging-station `power` is per-vehicle and `totalPower` segfaults, `constantPowerIntake` is not billed while plugged in, and a depleted battery is clamped at zero while the bus keeps driving - plus a verified battery-capacity x charger-count feasibility frontier and the sizing rules that follow.
keywords:
  - battery-electric-bus
  - opportunity-charging
  - charger-sizing
  - state-of-charge-feasibility
  - constantPowerIntake
  - regenerative-braking
created: 2026-08-05T05:00:00
last_updated: 2026-08-05T05:00:00
sources:
  - "[[episodic-memory/2026-08-05_05-00-00/outputs/REPORT.md]]"
  - "[[episodic-memory/2026-08-05_05-00-00/outputs/battery_semantics_probe.json]]"
  - "[[episodic-memory/2026-08-05_05-00-00/outputs/hypothesis_results.json]]"
  - "[[episodic-memory/2026-08-05_05-00-00/outputs/aux_accounting.json]]"
  - https://sumo.dlr.de/docs/Models/Electric.html
related_pages:
  - "[[electric-vehicle-battery-and-charging]]"
  - "[[road-gradient-and-energy-consumption]]"
  - "[[transit-signal-priority]]"
  - "[[bus-bunching-and-forward-headway-holding]]"
  - "[[bus-stop-infrastructure-design-parking-mechanism-and-tsp-interaction]]"
  - "[[public-transport-and-intermodal-routing]]"
  - "[[sumo-output-files]]"
  - "[[sumo-stochastic-variability-and-replication-design]]"
related_skills:
  - size-battery-electric-bus-fleet-and-chargers
  - simulate-ev-charging
  - model-road-gradient-effects-on-energy
  - implement-transit-signal-priority
  - demonstrate-and-control-bus-bunching
  - quantify-sumo-run-to-run-variability
related_skills_for_graph_view:
  - "[[size-battery-electric-bus-fleet-and-chargers]]"
  - "[[simulate-ev-charging]]"
  - "[[model-road-gradient-effects-on-energy]]"
  - "[[implement-transit-signal-priority]]"
  - "[[demonstrate-and-control-bus-bunching]]"
  - "[[quantify-sumo-run-to-run-variability]]"
---

# Battery-Electric Bus Energy and Charger Sizing

Extends [[electric-vehicle-battery-and-charging]] from "does this vehicle strand?" to "is this
*fleet* feasible, and what infrastructure makes it so?". Everything below was measured on
SUMO 1.27.1 against a 10.4 km signalised bus corridor with an asymmetric vertical profile, a
7-bus fleet running 5.5 h multi-cycle blocks (124.9 km each) with person-driven endogenous dwell
and congesting background car traffic, over 108 runs at 3 common-random-number seeds.

## SUMO will simulate an infeasible fleet without complaining

**A vehicle whose battery reaches zero is not immobilised.** SUMO logs exactly one
`Battery of vehicle 'X' is depleted` warning, **clamps `actualBatteryCapacity` at 0** (it never
goes negative), and the vehicle keeps driving at unchanged speed and completes its trip
(verified: 100 steps at SOC 0, speed steady at 13.89 m/s, `tripinfo` arrival written normally).
`totalEnergyConsumed` keeps accumulating past depletion.

Two consequences that govern every fleet study:

1. **Feasibility is entirely an analyst-side judgement.** No output field says "this did not
   work". The criterion has to be constructed - e.g. minimum state of charge over every bus
   staying above a reserve for the whole block.
2. **Report an unclamped "virtual" SOC**, reconstructed as
   `initial - totalEnergyConsumed + totalEnergyRegenerated + credited_charge`. It is the only
   quantity that can say *how far* short a configuration was: a 7-bus fleet on 80 kWh
   depot-only batteries reached a virtual SOC of **-0.590 on its worst bus**, i.e. a 47 kWh
   energy deficit, while SUMO's own trace for that bus sat flat at 0.

## What actually triggers charging

Charging is decided by the **vehicle's position over the chargingStation plus its speed**, not by
what the `<stop>` element names. A `busStop` that merely *overlaps* a chargingStation charges
exactly as much as a declared `<stop chargingStation="..."/>` (4750.00 Wh in both); a busStop
away from the station charges 0.00 Wh. This is what makes "a layover berth that happens to be
electrified" modellable, and it is also a hazard: any stop that lands inside a station footprint
charges whether or not that was intended.

## chargingStation `power` is per-vehicle; `totalPower` crashes

**`power` is a per-vehicle rate, not a shared station budget.** Two buses inside one
chargingStation each received the full 150 kW (41.667 Wh per 1 s step each). The `totalPower`
attribute, which would express a shared budget, **makes SUMO 1.27.1 segfault (rc = -11)** as soon
as two vehicles charge simultaneously; with a single vehicle it runs fine, which is why the bug
is easy to miss.

Therefore **the number of chargers must be modelled as physically separate berths** - separate
short chargingStations at distinct lanes/positions that vehicles physically contend for. A single
station with "n chargers' worth of power" is not a model of n chargers.

## The charging ledger: two files that disagree, and which one is right

- `battery-output` reports `energyCharged` on every step the vehicle is inside the station
  footprint, **including the departure acceleration after its stop has ended** (`timeStopped` back
  to 0). Those steps are **not** credited to `actualBatteryCapacity`.
- `chargingstations-output` totals match the **credited** energy exactly.

In the probe, `battery-output` summed to 4908.33 Wh against a credited and station-reported
4750.00 Wh - a 3.3 % over-statement from four departure-acceleration steps. Either read
`chargingstations-output`, or filter `battery-output` to `timeStopped > 0`; doing so closed the
per-bus energy balance
`initial - totalEnergyConsumed + totalEnergyRegenerated + credited_charge - final`
to **at most 0.21 Wh over ~20 000 steps x 7 buses in all 97 non-depleted runs**, with the two
files agreeing to 3.0 Wh across all 108.

**`chargingstations-output` is not a compact file** (correcting [[electric-vehicle-battery-and-charging]]):
in 1.27.1 it writes one `<step>` child per charging time step per vehicle - 6.9 MB for 84 sessions.
`--chargingstations-output.aggregated` gives the compact form but with a **different schema**
(`<chargingEvent>` elements, no per-station `totalEnergyCharged` roll-up), so a parser written for
one cannot read the other.

## `constantPowerIntake` is not `P x time`

The auxiliary/HVAC load is genuinely large - **26.3 % of net battery energy** at 7 kW on a 13.5 t
bus - but the obvious way to compute it is wrong in two directions at once:

- **It is not billed to the battery while the vehicle is taking charge.** The naive
  `P_aux x time_in_network` = 39 225 Wh against a paired-run measurement of 34 150 Wh for one bus;
  the entire 5 075 Wh gap was accounted for by 2 609 steps on which the bus was charging and the
  aux=7 kW and aux=0 runs agreed to the last decimal (2 609 x 1.9444 = 5 073 Wh).
- **It does not all appear in `totalEnergyConsumed`.** Part of it is paid for out of recuperated
  power, so it shows up as *lost regeneration*: of the 34 150 Wh, 26 188 Wh was extra gross
  consumption and 7 963 Wh was regeneration that did not happen.

**Measure auxiliary energy as `net(aux=P) - net(aux=0)` from a CRN-paired re-run**, with
`net = totalEnergyConsumed - totalEnergyRegenerated`. On in-motion legs with no charging that
measurement matches `P x t` to a ratio of 1.0000, which is the check that the accounting is right.

## Regeneration and its interaction with stop density

Regeneration is visible in the raw record as steps with `energyConsumed < 0` and a growing
`totalEnergyRegenerated`; a `recuperationEfficiency="0.0"` control arm writes 0.00 at every step.
On this corridor **39.7 % of gross energy was recuperated** (551.0 of 1386.4 kWh) and net
consumption fell from 1.6505 to 0.9554 kWh/km - a 42 % reduction.

**Regeneration also decouples consumption from stop frequency.** Doubling stop density (6 -> 12
stops per direction) costs **0.0618 kWh/km (95 % CI 0.0483-0.0753) with regeneration** but
**0.1474 kWh/km (CI 0.1233-0.1716) without** - **2.39x more sensitive**, both significant on 3
paired seeds. A no-regeneration design assumption therefore both over-states the consumption level
by 73 % and over-states the penalty for a dense stop spacing by a factor of two-and-a-half.

## Grade asymmetry sets a direction-specific minimum

On a corridor with a sustained 3.5 % grade over 2.8 of 10.4 km in one direction, the round-trip
mean of 0.934 kWh/km hid **1.381 kWh/km uphill against 0.480 kWh/km downhill - a 2.88x ratio**;
the uphill rate was 47.8 % above the round-trip average. The governing SOC minimum is a
**mid-block, direction-specific event**: in one traced run a bus dropped to SOC 0.053 at
t = 16 340 s and recovered to 0.634 by the end of its block, so neither the start-of-block nor the
end-of-block SOC reveals it.

**Feasibility is also set by one bus, not the fleet mean.** In that run the seven buses' minimum
SOCs were 0.053, 0.345, 0.732, 0.643, 0.667, 0.722, 0.721 - the first departure ran the peak
uphill legs at 1.414 kWh/km against 1.313-1.331 for the rest. A fleet-average of 0.55 would have
called that cell comfortably feasible.

**Verify the grade from the compiled net** (extending [[road-gradient-and-energy-consumption]]):
netconvert keeps the node `z` values exactly but shortens the edge at junctions, so a designed
3.500 % over a 1400 m edge is realised as **3.5466 %** over the 1381.6 m lane - 1.33 % steeper than
authored. Read `dz / horizontal_run` off the lane `shape` triples; never quote the authored grade.

## Capacity, mass and diminishing returns

Coupling pack mass to capacity at 7 kg/kWh, kWh/km rose monotonically 0.91245 (80 kWh, 13 560 kg)
to 0.95539 (240 kWh, 14 680 kg) - **+4.70 % consumption for +8.26 % mass, elasticity 0.57**. A
control sweep holding mass at the 200 kWh value gave **0.94466 kWh/km at every capacity, identical
to five decimals**, proving the whole effect is the mass channel.

Usable range (0.9 -> 0.2 SOC) therefore shows real diminishing returns: **0.7404 km per added kWh
over 80 -> 120 kWh falling monotonically to 0.6911 over 200 -> 240 kWh, a 6.7 % loss**, against a
flat 0.7410 in the mass-decoupled control. Fitting the endpoints gives
`rate(C) = 0.89098 + 0.00026838 C`, so `R(C) = 0.7 C / rate(C)` increases monotonically but is
bounded by 2 608 km; the marginal return falls but never turns negative at this mass coefficient.

## Charger count: what "peak coincident arrivals, not the mean" actually means

A mean-based sizing passes one charger per terminal comfortably here - the busiest berth is
occupied only **37.6-38.9 %** of the service period across three seeds, and one 120 kW charger delivers more energy per
cycle than a cycle consumes. One charger is nevertheless not equivalent to two, and the cost lands
in one of two completely different places depending on operating policy:

| single-charger policy | energy delivered | schedule cost |
|---|---|---|
| **session truncation** (alternate berths, only one electrified) | 486.6 kWh vs 830-946 kWh, exactly 50 % of pull-ins charged | **zero** - leg times bit-identical to the 2-charger arm |
| **queueing** (all buses sent to the one electrified berth) | full (+5.6 +- 7.8 kWh vs 2 chargers, n.s.) | **+107.7 s (95 % CI +18.7 to +196.7) on the uphill terminal-to-terminal leg**, westbound unaffected |

Only the truncation mode moved the feasibility frontier - from 80 kWh with 2 chargers to 120 kWh
with 1.

**Two measurement traps here.** First, **SUMO never lets two vehicles occupy the same stopping
place**, so a naive "overlapping stop intervals" contention counter reads exactly 0 in every run,
including the saturated ones; contention has to be measured as terminal-departure-to-next-berth
occupancy time. Second, and more important, **the queueing delay did not propagate to schedule
adherence at all**: despite ~108 s of extra leg time, mean terminal departure deviation moved
+1.06 s (CI +-8.98), missed departures -0.67 and headway CV -0.0116, none significant. The
scheduled layover slack absorbed it. **Sizing chargers by watching headway variability or bunching
would have detected nothing.**

## Verified feasibility frontier

7-bus fleet, 124.9 km blocks, 0.9 initial SOC, 0.20 reserve, 120 kW terminal chargers, 3 CRN seeds
(cell = mean minimum unclamped SOC over the fleet):

| capacity | 0 chargers (depot-only) | 1, truncation | 1, queueing | 2 chargers |
|---|---|---|---|---|
| 80 kWh | -0.590 (7 buses depleted) | -0.020 | - | +0.147 |
| 120 kWh | -0.104 (7 depleted) | **+0.276 feasible** | **+0.389 feasible** | **+0.390 feasible** |
| 160 kWh | +0.138 | +0.424 | +0.510 | +0.510 |
| 200 kWh | **+0.284 feasible** | +0.512 | - | +0.583 |
| 240 kWh | +0.381 | +0.571 | - | +0.631 |

Minimum feasible combination: **120 kWh + one electrified berth per terminal at 120 kW**.
Depot-only operation of the same block needs **200 kWh**.

**Charger power saturates.** Raising terminal power 120 -> 200 kW at 80 kWh lifted delivered charge
486.6 -> 638.9 kWh and min SOC -0.020 -> +0.065; raising it further to **300 kW changed nothing at
all** (identical delivered energy and min SOC to four decimals in every seed), because the binding
constraint becomes the battery's SOC headroom, not the charger.

**Mid-day depot recharge is a clear negative result.** Pulling four of seven buses out of service
for 1 200 s each at a 60 kW depot charger delivered only 89.4 kWh to the whole fleet (against
860 kWh from terminal charging), moved minimum SOC by +0.012 at 160 kWh, did **not** restore
feasibility at 120 or 160 kWh, and badly degraded service: mean terminal departure deviation
29.6 -> 181.9 s, missed departures 10.7 -> 25.7, headway CV 0.308 -> 0.597, mean rider wait
503.7 -> 561.1 s. The service gap costs far more than the energy it buys.

## Delay reduction on a schedule-bound block does not save auxiliary energy

Conditional [[transit-signal-priority]] (302 grants in one seed, verified against `phase_trace.json`:
truncations realised 17.8 s of cross green against a 26.0 s nominal, extensions 60.5 s against
56.0 s, residual offset debt exactly 0.0 s at all six signals) cut mean in-vehicle ride duration
334.5 -> 320.3 s and net fleet energy by 13.46 kWh (95 % CI -0.84 to +27.76, n=3, **not
significant**), against a traction-only saving of 4.16 kWh (CI 2.05-6.27, significant) measured in
the aux=0 arms - a total saving **3.24x** the traction saving.

But the intuitive mechanism is wrong. **The block is schedule-bound**: buses depart terminals on
`until`, so TSP does not shorten time in service at all - `P_aux x time` was 274.58 kWh in both
arms, identical to two decimals. The extra 9.30 kWh came from the *charging* side: arriving earlier
means more terminal dwell spent plugged in, and the auxiliary load is not billed to the battery
while charging. **A delay-reducing measure on a schedule-bound block moves auxiliary load onto the
charger; it does not remove it.** (The auxiliary share does rise with congestion within a leg -
19.2 % at 39-42 km/h to 38.7 % at 9-12 km/h, and 54 % of the extra energy a peak uphill leg costs
is auxiliary rather than traction - the hypothesis fails on the *remedy*, not on the mechanism.)

## Sizing decision rule

1. Size the battery on the **worst directional inter-charge drawdown**, never the round-trip mean.
2. Close the **mass feedback**: `C >= E(C) / (SOC_start - SOC_reserve)` as a fixed point.
3. Size chargers on **peak coincident pull-ins**, not mean berth utilisation or mean energy.
4. Decide which shortfall mode the operating policy implies - queue (costs running time) or divert
   (costs charge) - because only the charge-losing mode moves the frontier.
5. Stop raising charger power once the battery's SOC headroom binds; verify by sweeping power.
6. Judge feasibility from the **unclamped per-bus SOC trace across the whole block, worst bus**.

See the `size-battery-electric-bus-fleet-and-chargers` skill for the full build/run/analyse
pipeline, including the pre-study probe script that re-establishes every SUMO behaviour above
against whatever binary is installed.
