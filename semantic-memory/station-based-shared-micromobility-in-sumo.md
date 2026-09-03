---
summary: How to model station-based shared micromobility (bikeshare / e-scooter share) in SUMO, and — measured against SUMO 1.27.1 rather than asserted — what the simulator already provides. `<stop triggered="person">` rations a finite named fleet, `lines="ANY"` binds a traveller to whichever vehicle is free at runtime, `extension` time-boxes a triggered hold so one stop can unload, hold inventory and admit a new boarder in the same visit, and `<parkingAreaReroute>` gives occupancy-driven dock-full continuation; what is genuinely absent is only that legal alighting points are {authored stops} UNION {route terminus} with forward-only travel, that denial resolves as an UNCOSTED teleport (vehicle="NULL", routeLength="-1.00"), and that state-dependent inventory-driven rebalancing has no native expression. Also records a verified operating study on a 2x2 km district (125 CRN runs) — fleet size and dock capacity are NOT separable because a full destination dock pushes the bike onward and so acts as free passive rebalancing (+40 bikes bought +0.0 rides at loose docks and +71.8 at tight ones), one rebalancing van is worth 8-38 extra bikes rising steeply with fleet size, and a cohort-corrected mode-substitution analysis where 94% of the raw walking effect is a denial-rule artefact.
keywords:
  - bikeshare
  - shared-micromobility
  - e-scooter-share
  - station-based-bikeshare
  - docking-station-inventory
  - triggered-stop
  - lines-ANY
  - parkingAreaReroute
  - stop-output
  - first-and-last-mile
  - rebalancing
  - mode-substitution-counterfactual
  - dock-capacity
created: 2026-08-18T09:16:23
last_updated: 2026-08-18T12:30:00
sources:
  - "[[episodic-memory/2026-08-18_09-16-23/summary.md]]"
  - "[[episodic-memory/2026-08-18_09-16-23/outputs/verification/]]"
related_pages:
  - "[[parking-areas-and-rerouters]]"
  - "[[car-to-transit-intermodal-transfer-and-park-and-ride]]"
  - "[[public-transport-and-intermodal-routing]]"
  - "[[taxi-and-drt-dispatch]]"
  - "[[sumo-output-files]]"
  - "[[dedicated-bicycle-lanes-and-mode-share]]"
  - "[[downs-thomson-paradox-and-mode-choice-equilibrium]]"
related_skills:
  - build-and-evaluate-park-and-ride-corridor
  - model-parking-with-rerouting
  - simulate-taxi-and-drt-dispatch
  - simulate-multimodal-transit
  - quantify-sumo-run-to-run-variability
related_skills_for_graph_view:
  - "[[build-and-evaluate-park-and-ride-corridor]]"
  - "[[model-parking-with-rerouting]]"
  - "[[simulate-taxi-and-drt-dispatch]]"
  - "[[simulate-multimodal-transit]]"
  - "[[quantify-sumo-run-to-run-variability]]"
---

# Station-Based Shared Micromobility in SUMO

A shared physical asset with **per-station inventory** — one traveller consumes a bike, a later traveller reuses it — is the fourth fleet paradigm alongside the dispatched driver-operated fleet ([[taxi-and-drt-dispatch]]), the fixed-schedule transit fleet ([[public-transport-and-intermodal-routing]]) and the privately-owned vehicle in a finite lot ([[car-to-transit-intermodal-transfer-and-park-and-ride]]).

**Read the capability table below before building anything.** A study of this domain spent three attempts asserting SUMO could not express things it can, each "proof" bounded by construction — decoy vehicles with unreachable one-edge routes, disconnected routes hidden by `--ignore-route-errors`, a `personCapacity="2"` with a free seat, an unset `--time-to-teleport.ride`. Everything below was measured against SUMO 1.27.1 with connected routes, no error suppression, and control/treatment pairs.

## What SUMO already provides

| capability | construct | measured |
|---|---|---|
| Ration a finite named fleet | `<stop parkingArea triggered="person">` + `<ride lines="BK0 ...">` | 5 bikes, 40 travellers → **5 carried**, `aborted="35"`, 35 legs `vehicle="NULL"`, **0 bikes conjured** |
| Bind a rider to whichever vehicle is free, **at runtime** | `lines="BK0 BK1 BK2 BK3 BK4"` | FIRST→BK0, SECOND→BK1, THIRD→BK2 |
| The same with **no enumeration at all** | **`lines="ANY"`** | identical result; this *is* "whichever bike is free when I arrive" |
| Fall through to an idle identical bike | `lines="ANY"`, second rider 1400 s later | rides **BK1** after BK0 is taken; `lines="BK0"` instead → `NULL` |
| One stop that unloads, holds inventory **and** admits a boarder | `<stop triggered="person" duration="1" until="400" extension="10">` | `initialPersons="2" loadedPersons="1" unloadedPersons="1"`, held 107 s, through-rider carried on |
| Release a triggered hold when the vehicle is full | `personCapacity="1"` (the default for a bike vType) | `Warning: Vehicle 'BK0' ignores triggered stop ... due to capacity constraints` — carries the through-rider straight on |
| Bound the wait for a vehicle | `--time-to-teleport.ride 600` | teleported at t=1600, `abortWait="1"`; the plan's following legs still run |
| **Occupancy-driven dock-full continuation** | `<parkingAreaReroute>` on the dock's own edge | full dock → re-docks at the spare dock; **part-full → docks there instead** (verified causal) |
| Demand-driven destination, no authored stops | `device.taxi` + `<personTrip modes="taxi">` | 2 riders, different destinations, both carried — at **56% empty km**, and the vehicle never rests as inventory |

Two gotchas that mislead: `<personTrip modes="bicycle">` **conjures a private bicycle** and never consults fleet state (40 travellers → 45 distinct bicycles for an intended fleet of 5); and `until` alone does **not** release a triggered hold — `extension` does, while `expected=""` is rejected outright.

## What is genuinely absent

- **Legal alighting points are {authored stops} ∪ {route terminus}, and travel is forward-only along the author's fixed dock order.** A destination *on the route* but without an authored `<stop>` is not boardable — the rider waits out the horizon with `vehicle="NULL"`. (SUMO's `MSStageDriving::isWaitingFor` → `stopsAtEdge`.) Free origin–destination choice therefore needs an **O(N)** authored stop list covering every dock, not an O(N²) enumeration of pairs: one bike whose stop list is simply all docks, with `extension`, carried three riders choosing origin and destination purely at runtime.
- **Denial resolves as an uncosted teleport, never a costed re-plan.** A bounded wait ends `vehicle="NULL" depart="-1" routeLength="-1.00"` — the traveller arrives having travelled no distance, in no vehicle, at no cost. `--time-to-teleport.remove` is **vehicle-scoped only** and does not apply to persons. If the study's outcome depends on what a denied traveller *does instead* (as every effect below does), that substitute trip must be authored by a controller.
- **State-dependent, inventory-driven rebalancing has no native expression.** `--device.taxi.idle-algorithm taxistand` is a built-in idle-repositioning policy, but it does not respond to per-station inventory.

So a TraCI layer is justified by the **operating semantics** — costed denial with a re-plan, and inventory-driven rebalancing — not by the person↔vehicle binding, which SUMO does natively.

## Verifying an inventory primitive

Occupancy has no `--parking-output`, but it is **not** TraCI-only (a correction to [[parking-areas-and-rerouters]]): `--stop-output` + `--stop-output.write-unfinished` emits `<stopinfo ... parkingArea= started= ended= loadedPersons= unloadedPersons=>`, from which a per-station per-interval ledger reconstructs offline. Use it — a ledger built from the controller's *own* occupancy samples makes conservation **tautological** (`inv_end − inv_start == arrivals − departures` holds by construction and cannot fail).

The check that actually discriminates, on a 120-bike/8-station run: **168 station-interval cells rebuilt from `<stopinfo>` versus the controller's ledger, 0 disagreements**; arrivals 293 − departures 173 = net 120 = fleet; **173 gaps between consecutive dock stays matched to 173 `<ride vehicle="BK…">` legs**, with `loadedPersons`/`unloadedPersons` = 173/173 as a third independent read. Denied travellers must be confirmed from `<personinfo>` — SUMO's `<ride>` records a denial nowhere ([[sumo-output-files]]) — and from FCD that they physically moved rather than stalling.

## Supply-side findings (2×2 km district, 8 docks, 1300 travellers, 125 CRN runs)

**Fleet size and dock capacity are not separable, and the mechanism is counterintuitive.** With initial placement pinned so capacity moves alone:

| fleet | cap 22 → cap 45 | effect |
|---|---|---|
| 120 | 174.2 → 151.2 served | dock-full eliminated (0.505 → 0.000 redirects/ride), rides shorten 3328 → 2177 m, **served falls 13%** |
| 160 | 246.0 → 151.2 served | **served falls 39%** |
| +40 bikes at cap 45 | 151.2 → 151.2 | **+0.0 rides** |
| +40 bikes at cap 22 | 174.2 → 246.0 | **+71.8 rides** |

**A full destination dock pushes the bike onward to another station, so tight docks act as free, passive rebalancing.** The two levers trade one failure mode for the other rather than removing them independently. Throughput is maximised at the tightest docks and door-to-door time at the loosest — a policy choice, not an optimisation. Initial placement is a genuine third lever (+22.4 rides from demand-proportional versus flat).

**Rebalancing beats fleet size, at a rate that rises steeply with fleet size.** Residential docks ran net −27/−30/−29 over the peak and drained to zero by minutes 20–30. One threshold-triggered van is worth **8.0 extra bikes at fleet 40 and 38.3 at fleet 120**; the pooled mean of 15.9 is not meaningful. 120 bikes + 2 vans served **213.6** against 160 bikes with no vans at **197.0** — 33% more bikes lost to two vans.

## Cohort-correcting a mode-substitution counterfactual

A denial rule re-plans turned-away travellers onto walk or transit. Their travel is **not something the system delivered**, so a raw with-versus-without comparison attributes it to the system. Split every metric by cohort (served / denied / untreated control):

| metric | RAW | CORRECTED (served) | artefact share |
|---|---|---|---|
| car VMT | −204.23 km | **−105.80 km** | 48% |
| private-bike VMT | −130.51 km | **−66.81 km** | 49% |
| transit boardings | +44.40 | **+20.00** | 55% |
| person walking | +195.65 km | **+11.61 km** | **94%** |
| door-to-door | +165.60 s | **+62.19 s** | 62% |

Correcting only the headline metric is a trap: here the artefact contributes 48% to car VMT and **94%** to walking, and walking is the question a micromobility evaluation is actually asked. Bound the pairing error on an untreated control cohort whose plans are byte-identical in both arms — here ≤ **1.65%** of each corrected effect.

**What the study then found**, on 173.4 carried trips/run displacing WALK 42.2% / CAR 25.6% / transit-with-walk-access 18.0% / private bike 14.2%:

1. **Car use fell, really but modestly** — −105.8 km, **10.2%** of baseline.
2. **Transit was fed, not cannibalised, on net** (+20.0 boardings among carried travellers) — but only 10.0 of 31.2 transit converts kept a transit leg, and that cohort's own boardings **fell 16.6 → 6.8**. The net is positive because gains elsewhere outweigh real gross cannibalisation.
3. **Walkers were the largest ridership source, yet walking rose** (+11.6 km). **A station-based system does not remove the walk; it inserts a ride between two walks** — 780.6 s of dock-adjacent walking per carried traveller in a district only 2 km across. "Where riders came from" and "what happened to pedestrian activity" are different questions with opposite answers.
4. **The cost is time**: a carried traveller took 1452.2 s against 986.0 s for the same person in the paired no-system run (+47%), and 264 s worse than the mode-choice model's own prediction for the option it chose.

## A methodological warning

A TraCI controller that iterates `set(traci.person.getIDList())` is **not reproducible across processes** — Python set order over strings varies with `PYTHONHASHSEED`, so which traveller wins the last scarce bike changes between runs. Identical configurations differed by up to 3 served rides and 7 dock-full redirects, the same order as some reported effects. Sort the ID list, or state that common random numbers cover the demand realisation only.

More generally: **do not justify a custom primitive on "the simulator cannot do X" until a test of X survives adversarial review.** Three successive tests here were bounded by construction and each produced a confident, false negative result about SUMO.
