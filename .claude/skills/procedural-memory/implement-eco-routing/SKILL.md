---
name: implement-eco-routing
description: Use this skill when the user wants emissions-aware ("eco", "green", low-carbon, fuel-minimising) routing in SUMO rather than travel-time routing — either as an offline iterative assignment (duarouter --weight-files with --weight-attribute pointed at an emission measure) or as an online in-simulation controller (traci.edge.setEffort + traci.vehicle.rerouteEffort with a generalized cost alpha*traveltime + beta*fuel), including market-penetration sweeps and testing for an eco-routing rebound/paradox. Covers SUMO's separate EFFORT weight channel, the free-flow fallback needed because unsampled edges are silently free, per-vehicle vs per-edge-total emission normalisation, and the allocation-vs-timing decomposition of why full-penetration eco routing can emit more than doing nothing. Trigger on mentions of eco-routing, green routing, emissions-aware/CO2-minimising route choice, setEffort/rerouteEffort, --weight-attribute, or "does routing everyone by emissions reduce emissions."
---

# Implement Eco-Routing (emissions-aware route choice)

Routes vehicles to minimise **emissions or fuel** instead of travel time, offline
(a converged assignment) and online (a live TraCI controller), and measures whether
it actually reduces network emissions. This is different from every travel-time
routing skill in memory (`convert-trips-to-routes`, `compute-dynamic-user-equilibrium`,
`sweep-rerouting-device-market-penetration`) in one structural way: **the cost being
minimised is not a monotone function of travel time**, so the two objectives can rank
the same pair of routes in opposite order.

## Design the scenario so the objectives actually disagree

Build (or verify) a network where the faster route is the *dirtier* one, otherwise
"eco routing" is just shortest-path routing with extra steps. The canonical shape is a
**longer, faster, uninterrupted bypass vs. a shorter, signalised arterial**. Measure
the conflict before running anything, with a free-flow probe (below). A verified
example: bypass 2774 m / 124.9 s / 451.7 g CO2 vs arterial 1930 m / 139.0 s /
324.8 g CO2 — the bypass is 11% faster and 39% dirtier.

Also give the two corridors a few **mid-corridor connectors** so a vehicle already
committed to one can switch; without them an online reroute can only ever affect
vehicles that have not yet reached the diverge.

## Step 1 (always): a free-flow probe run for fallback weights

**An `edgeData type="emissions"` dump writes `traveltime` and every `*_perVeh`
attribute only for edges that had a vehicle on them.** A zero-flow edge gets
`*_abs`/`*_normed` (all `0.00`) and nothing else — verified directly against SUMO
1.27.1. This is fatal, because:

**Verified, decisive: for any `--weight-attribute` other than `traveltime`, duarouter
treats an edge missing from the weight file as costing ZERO** (it has no free-flow
fallback for a custom measure; with `traveltime` it *does* fall back to free flow).
Controlled test: a weight file listing every edge at 1.0 except the arterial gives
100% bypass under `--weight-attribute traveltime` and 100% arterial under a custom
attribute. So feeding a raw emissions dump to duarouter routes everything onto
whatever happened to be empty last iteration.

Fix: run one ultra-low-density probe (`scripts/probe_freeflow.py`) releasing a
handful of vehicles per edge at the speed limit with `sigma=0`, and use its per-edge
`traveltime`/`*_perVeh` values to fill every (edge, interval) cell that has no sample.
Report the fallback fraction each iteration — at 600 s intervals on a small corridor
**22% of cells** needed it.

## Step 2: offline iterative eco-assignment

`scripts/assign_loop.py`. One loop serves both objectives; only the cost expression
written into the weight file changes:

```
cost_e = alpha * traveltime_e + beta * fuel_perVeh_e     ->  gcost="..."
alpha=1, beta=0 -> travel-time UE      alpha=0, beta=1 -> pure minimum-fuel
```

Per iteration: simulate -> `edgeData type="emissions"` (**one dump gives you both
`traveltime` and `CO2_perVeh`/`fuel_perVeh`**) -> exponentially smooth the cost
surface across iterations (s~0.5) -> write a *complete* weight file -> all-or-nothing
`duarouter --weight-files w.xml --weight-attribute gcost` -> move 1/k of vehicles onto
the new route (MSA). Custom attribute names work fine; duarouter reads whatever
attribute you name.

**Convergence criterion that worked:** `max |Delta route share| < 0.01` sustained over
5 consecutive iterations **and** a relative gap
`(C_current - C_allOrNothing)/C_current` that has stopped decreasing. Do not expect
the gap to reach zero on a congested microsimulation — a plateau near 0.02 (eco) /
0.05 (travel time) was the honest converged state in one verified case, corroborated
by `duaIterate.py` reproducing the same pooled route split to <0.1 pp from a
completely independent implementation. **Always cross-check the travel-time arm
against `duaIterate.py`** (see `compute-dynamic-user-equilibrium`); it is free
validation that your loop is not the source of a surprising eco result.

## Step 3: online eco-routing over the EFFORT channel

`scripts/traci_eco_router.py`. SUMO keeps **two independent edge-weight containers**:
travel time (`adaptTraveltime` / `rerouteTraveltime`) and **effort**
(`traci.edge.setEffort` / `traci.vehicle.rerouteEffort`). Push the generalized cost
onto the effort channel and reroute only equipped vehicles:

```python
for e in edges:                       # every control period (e.g. 60 s)
    n  = conn.edge.getLastStepVehicleNumber(e)
    tt = min(conn.edge.getTraveltime(e), MAX_TT)
    fuel = conn.edge.getFuelConsumption(e) / n * tt if n else ff[e]["fuel_perVeh"]
    ...                                # EMA-smooth tt and fuel
    conn.edge.setEffort(e, alpha * tt_s[e] + beta * fuel_s[e])

for vid in conn.vehicle.getIDList():
    if conn.vehicle.getTypeID(vid) == "eco":
        conn.vehicle.rerouteEffort(vid)
```

* `traci.edge.getFuelConsumption()` is a **rate in mg/s summed over the vehicles
  currently on the edge**; per-traversal fuel is `rate / n_veh * traveltime`. With
  `n_veh == 0` the rate is 0 — the same "empty edge looks free" trap as the offline
  weight files. Use the free-flow fallback here too.
* Set effort on **every** edge every period; an edge whose effort was never set falls
  back to travel time, silently mixing two cost units in one route computation.
* **Verified: `setEffort` + `rerouteEffort` works with no `device.rerouting` attached
  at all.** This is a *different* answer from the observation recorded in
  `model-cordon-tolling-with-generalized-cost-surcharge`, where the automatic
  rerouting *device* ignored `adaptTraveltime` — an explicit `rerouteEffort()` call
  does honour globally-set effort. Verify on your version anyway with the two controls
  below.

### The two controls that make the mechanism a fact rather than a hope

1. **Negative control — 0% penetration**: expect `reroute_calls == 0`,
   `route_changes == 0`, and a realised route split byte-equal to the loaded route
   file. (Verified: 0.5436 realised vs 0.544 in the file.)
2. **Positive control — force one corridor's effort to a huge constant** at partial
   penetration: equipped vehicles must abandon it completely while unequipped
   vehicles' split stays at baseline. (Verified: equipped 0.0% bypass / unequipped
   0.540 bypass at 50% penetration — and the 20% of equipped that ended on *hybrid*
   routes are exactly the ones already on the bypass that escaped via the connectors,
   which also proves the connectors work.)

Also cross-check the equipped/unequipped partition against an independent source
(vType in `--vehroute-output` vs vType in `tripinfo`); a mismatch count of exactly 0
across every run is cheap, strong evidence.

## Step 4: sweep penetration AND the alpha/beta weighting, with a travel-time control

Parameterise `beta = lambda * R` with
`R = sum_e freeflow_traveltime_e / sum_e freeflow_fuelPerVeh_e` so that `lambda = 1`
weights the two terms equally at free flow (verified value on one corridor:
1.238e-3 s/mg). Then:

* **`lambda = 0` (pure travel time, same controller, same penetration) is a mandatory
  control**, not an optional extra. It separates "the effect of rerouting at all"
  from "the effect of the eco objective". Without it you will attribute a
  bottleneck-relief benefit to eco routing that a plain travel-time router captures
  just as well or better.
* Keep demand, starting routes and simulation seed identical across arms (Common
  Random Numbers) and re-type vehicles in place to set penetration, so nothing but
  equipage varies. Use >=5 demand seeds and paired t-tests.

## Verified findings: the eco-routing rebound is real, and its cause is not the objective

* **Offline, the eco assignment can be a strict Pareto improvement.** Converged
  minimum-fuel assignment vs travel-time UE, 5 seeds: CO2 -5.3% (p=0.010),
  mean travel time -9.9% (p=0.006), p90 -16.6%, vehicle-km -2.5%. This happens when
  the travel-time user equilibrium over-loads a capacity-limited fast route (UE != SO),
  so minimising fuel incidentally corrects a congestion inefficiency. **Do not
  generalise it** — check the `lambda=0` control before crediting the eco objective.
* **Online, network CO2 is non-monotone in penetration and full penetration is worse
  than doing nothing.** Verified: 2426.0 -> 2345.3 (25%) -> 2372.2 (50%) -> 2425.6
  (75%) -> 2520.9 kg (100%); the 50->75% and 75->100% legs are individually
  significant (p=0.013, p=0.007) and 100% vs 0% is +3.9% (p=0.013).
* **At full penetration, optimising fuel produces MORE fuel than optimising time**
  (+68.3 kg CO2, p=0.005), and the whole alpha/beta Pareto front is **degenerate** —
  CO2 *and* travel time both rise monotonically with lambda, so every positive eco
  weight is strictly dominated. Plot it; a monotone "frontier" is itself the finding.
* **Mechanism, decomposed rather than asserted.** Split the CO2 change into a
  *distance* effect (vehicle-km) and an *intensity* effect (g/veh-km). Verified:
  distance falls monotonically (-4.0% at 100%, exactly as designed) while the
  arterial's intensity rises 347.9 -> 378.4 g/veh-km as signal waiting per vehicle
  rises 13% — at 100% the intensity penalty (+184.5 kg) is more than double the
  distance saving (-82.1 kg). HBEFA3 emission rates climb steeply with the
  acceleration cycles after each stop, so pushing traffic onto a signalised corridor
  buys distance and pays it back in stop-and-go.
* **Allocation vs timing, via a static-split reference.** Force fixed route shares
  with no router and find the emissions-minimising split; then attribute each reactive
  arm's shortfall to "wrong average split" vs "right split, wrong process". Verified,
  and the two failure modes appear **at the same penetration level with only the cost
  function differing**: the online *travel-time* router lands on a near-perfect
  average split (allocation cost +6.9 kg) and loses everything to herding
  (timing +137.9 kg), while the online *eco* router's loss is mostly allocation
  (+144.7 kg) — it over-diverts 5 pp past even the offline eco equilibrium
  (0.367 vs 0.417, p=0.004). The reason is that effort is an **average** cost: each
  vehicle sees the arterial's measured per-vehicle emissions, never the marginal
  emissions its own arrival imposes on the queue.
* **The paradox belongs to the reactive implementation, not the objective.** The
  offline eco *equilibrium* (2287.7 kg) beats the do-nothing baseline (2426.0 kg) and
  even the best constant static split (2307.8 kg), while the online reactive version
  of the same objective at full penetration (2520.9 kg) is worse than doing nothing —
  +233.1 kg vs the offline equilibrium, p=0.0001. Report both; reporting only the
  online arm would falsely indict eco routing as a concept.
* **Private outcome reverses too.** Being equipped cost 10-15 s of travel time at
  every penetration level, and the equipped group's own per-vehicle CO2 advantage
  vanished and reversed by 75% penetration (971.3 vs 965.8 g). At that same 75%
  level, unequipped drivers were already better off than anyone in the 0% baseline
  (321.3 s vs 346.8 s mean travel time) — the congestible-good signature documented
  in [[information-penetration-and-congestible-routing]], reproduced in the
  emissions domain. (Not checkable at 100% penetration, where no unequipped vehicles
  remain.)

## Gotchas

- **`*_perVeh`, never `*_abs`.** `*_abs` is a per-edge *total*, so it scales with the
  edge's own flow and is not comparable between a 2-lane and a 1-lane corridor.
  Verified inversion: at the travel-time UE `fuel_abs` calls the arterial cheaper;
  at the eco equilibrium the same measure calls the bypass cheaper — purely because
  the busy route changed. Running the full loop on `*_abs` converged to **+30% CO2**
  (2806.7 vs 2160.5 kg) and diverted 8.7% of vehicles onto longer hybrid/connector
  routes (all still arrived — no teleports or trip failures), because the router
  chases whichever route is emptiest rather than cleanest.
- **Weight-file intervals must span the whole departure window; they do not extend.**
  Verified: with weights covering only [0,600) and the bypass made absurdly
  expensive, the 203 vehicles departing before 600 s obeyed it while the 1829
  departing after reverted to network defaults and all took the bypass. Nothing warns
  you.
- **Finer aggregation intervals are not automatically better.** 600 s intervals left
  22% of (edge, interval) cells with no sample; a single whole-horizon interval left
  0% and actually converged to a *lower* residual gap. Choose the interval by
  measuring the zero-sample fraction, not by instinct.
- **Emission edgeData attributes are in milligrams** (fuel included) — /1000 for g,
  /1e6 for kg (see [[vehicle-emissions-modeling]]).
- **Keep the equipped and unequipped vTypes physically identical** (same
  `emissionClass`, length, accel, sigma, speedDev) so the subgroup comparison is a
  routing comparison and not a fleet-composition comparison.
- **Cap the measured edge travel time** (`traci.edge.getTraveltime` is
  `length / mean speed` and explodes toward infinity on a stopped edge) before it
  enters a generalized cost.

## Related

- `simulate-fleet-emissions` — the HBEFA `emissionClass` + `edgeData type="emissions"`
  measurement layer this skill routes on top of; use its mixed-fleet setup if the eco
  objective should differ by vehicle type.
- `compute-dynamic-user-equilibrium` — the travel-time counterpart and the
  `duaIterate.py` cross-check this skill's offline loop is validated against; the
  eco loop is that methodology with `--weight-attribute` retargeted.
- `convert-trips-to-routes` — the underlying `duarouter` invocation, including the
  `--weight-files` flag whose non-travel-time semantics this skill pins down.
- `sweep-rerouting-device-market-penetration` — the penetration-sweep design,
  subgroup attribution and static-split allocation-vs-timing decomposition reused
  here; this skill adds a second cost function and finds the two failure modes can be
  swapped by the objective alone.
- `model-cordon-tolling-with-generalized-cost-surcharge` — the other generalized-cost
  TraCI controller in memory; contrast explicitly, since it uses
  `adaptTraveltime` + `findRoute`/`setRoute` (having found the rerouting *device*
  ignored `adaptTraveltime`), whereas this skill's `setEffort` + `rerouteEffort` pair
  works directly.
- `quantify-sumo-run-to-run-variability` — the CRN/replication discipline behind the
  paired tests used for the rebound claim.
- [[effort-based-routing-and-eco-routing]] — the mechanism reference and verified
  findings.
