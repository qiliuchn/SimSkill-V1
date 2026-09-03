---
summary: SUMO carries a second, independent edge-weight channel ("effort") reachable offline via duarouter --weight-files/--weight-attribute and online via traci.edge.setEffort + traci.vehicle.rerouteEffort, which is what emissions-aware (eco) routing runs on; a verified study found the converged offline eco assignment is a strict Pareto improvement over the travel-time user equilibrium, while the same objective applied by a reactive online router is non-monotone in market penetration and at full penetration emits more than doing nothing at all.
keywords:
  - eco-routing
  - effort-based-routing
  - setEffort
  - rerouteEffort
  - weight-attribute
  - weight-files
  - emissions-aware-assignment
  - eco-routing-paradox
created: 2026-08-04T01:00:00
last_updated: 2026-08-04T01:00:00
sources:
  - "[[episodic-memory/2026-08-04_01-00-00/outputs/weightfile_pitfalls.txt]]"
  - "[[episodic-memory/2026-08-04_01-00-00/outputs/sweep_analysis.txt]]"
  - "[[episodic-memory/2026-08-04_01-00-00/outputs/mechanism_analysis.txt]]"
  - "[[episodic-memory/2026-08-04_01-00-00/outputs/timing_vs_allocation.txt]]"
  - https://sumo.dlr.de/docs/duarouter.html
  - https://sumo.dlr.de/docs/TraCI/Change_Edge_State.html
related_pages:
  - "[[vehicle-emissions-modeling]]"
  - "[[dynamic-user-equilibrium-and-wardrop]]"
  - "[[information-penetration-and-congestible-routing]]"
  - "[[duarouter]]"
  - "[[cordon-tolling-and-e3-detectors]]"
  - "[[glosa-eco-driving]]"
  - "[[sumo-output-files]]"
  - "[[sumo-stochastic-variability-and-replication-design]]"
related_skills:
  - implement-eco-routing
  - simulate-fleet-emissions
  - compute-dynamic-user-equilibrium
  - convert-trips-to-routes
  - sweep-rerouting-device-market-penetration
  - model-cordon-tolling-with-generalized-cost-surcharge
related_skills_for_graph_view:
  - "[[implement-eco-routing]]"
  - "[[simulate-fleet-emissions]]"
  - "[[compute-dynamic-user-equilibrium]]"
  - "[[convert-trips-to-routes]]"
  - "[[sweep-rerouting-device-market-penetration]]"
  - "[[model-cordon-tolling-with-generalized-cost-surcharge]]"
---

# Effort-Based Routing and Eco-Routing

SUMO's routers can minimise something other than travel time. The mechanism is a
second, **independent** per-edge weight container usually called **effort**, and it is
reachable from both halves of the toolchain:

* **Offline**: `duarouter --weight-files <file> --weight-attribute <name>`. The weight
  file is an ordinary meandata-shaped XML (`<meandata><interval begin= end=><edge
  id= .../></interval></meandata>`); `--weight-attribute` names *which attribute of
  each `<edge>` element* to minimise, and **any attribute name works**, including one
  you compute yourself. The default is `traveltime`.
* **Online**: `traci.edge.setEffort(edgeID, value)` writes the effort container and
  `traci.vehicle.rerouteEffort(vehID)` recomputes that vehicle's route against it.
  This is a *different container* from `traci.edge.adaptTraveltime` /
  `traci.vehicle.rerouteTraveltime`; the two never interact.

This is what makes emissions-aware ("eco") routing possible: put a generalized cost
`alpha * traveltime_e + beta * fuel_perVeh_e` on the effort channel, and the router
minimises emissions-weighted cost rather than time.

## The single most important fact: unsampled edges are silently free

An `edgeData type="emissions"` dump ([[vehicle-emissions-modeling]]) writes
`traveltime` and every `*_perVeh` attribute **only for edges that actually carried a
vehicle**. A zero-flow edge is written with `*_abs`/`*_normed` only, all `0.00`.

**Verified against SUMO 1.27.1 with a controlled A/B: for any `--weight-attribute`
other than `traveltime`, an edge missing from the weight file costs ZERO. With
`traveltime` it falls back to the network's free-flow travel time.** The test: a
weight file listing every edge at cost 1.0 *except* the arterial corridor sent 100%
of demand to the bypass under `--weight-attribute traveltime` (the omitted arterial
still "cost" its free-flow 139 s) and 100% to the arterial under a custom attribute
(the omitted arterial cost 0).

Consequence: **feeding a raw emissions edgeData dump straight into duarouter routes
everything onto whatever was empty last iteration.** The remedy is a free-flow probe
run — a handful of vehicles per edge at the speed limit with no interaction — whose
per-edge values fill any (edge, interval) cell with no sample.

## Other verified weight-file mechanics

* **Intervals do not extend.** With a weight file covering only [0,600 s) and the
  bypass made absurdly expensive there, the vehicles departing before 600 s obeyed it
  while the ~1800 departing afterwards reverted to network defaults and all took the
  bypass. Weight-file intervals must span the entire departure window; nothing warns
  you if they do not.
* **Finer intervals are not automatically better.** 600 s intervals left **22%** of
  (edge, interval) cells with no emission sample (needing fallback); one whole-horizon
  interval left **0%** and converged to a *lower* residual gap. Pick the interval by
  measuring the zero-sample fraction.
* **`*_perVeh` is the only additive per-driver route cost.** `*_abs` is a per-edge
  *total*, so it scales with the edge's own flow and is meaningless across corridors
  of different width. Verified inversion: at the travel-time equilibrium `fuel_abs`
  ranks the arterial cheaper; at the eco equilibrium the same measure ranks the bypass
  cheaper — solely because the busy route changed. An assignment loop run on `*_abs`
  converged to **+30% network CO2** and diverted 8.7% of vehicles onto longer
  hybrid/connector routes (all still arrived — no teleports or trip failures),
  because it chases whichever route is emptiest, not cleanest.

## The eco cost surface is not proportional to travel time

HBEFA3 rates depend on speed *and* acceleration, so per-edge time and per-edge
emissions are correlated but not interchangeable: measured Spearman
rho(traveltime, CO2_perVeh) = +0.84 across edges, dropping to +0.48 once both are
length-normalised. More importantly the *route* ordering can invert. On a verified
corridor, at free flow the bypass was **11% faster and 39% dirtier** than the
signalised arterial (124.9 s / 451.7 g CO2 vs 139.0 s / 324.8 g CO2), because CO2
scales mostly with distance while time scales with distance/speed. That inversion is
what makes eco routing a genuinely different assignment rather than a relabelled
shortest path. (The related non-monotonicity of HBEFA's speed-emission curve is
covered in [[vehicle-emissions-modeling]] and [[glosa-eco-driving]].)

## traci.edge.setEffort + vehicle.rerouteEffort: verified working

**`setEffort` + an explicit `rerouteEffort()` call works with no `device.rerouting`
attached at all**, and affects only the vehicles told to reroute. Verified with two
controls on a mixed-equipage run: at 0% penetration the controller made zero reroute
calls and reproduced the loaded route file's split exactly; with one corridor's effort
forced to a huge constant at 50% penetration, equipped vehicles ended at **0.0%** on
that corridor while unequipped vehicles stayed at their baseline 54.0%.

**This is a different answer from [[cordon-tolling-and-e3-detectors]]**, where the
automatic rerouting *device* was observed to ignore `traci.edge.adaptTraveltime` and a
`findRoute` + `setRoute` workaround was needed. The distinction that matters: the
*device's own periodic rerouting* may route on its internally measured weights, but an
*explicit* `rerouteEffort()` / `rerouteTraveltime()` TraCI call honours the container
you wrote. Prefer the explicit call when you control the reroute trigger.

Practical detail for building the online cost: `traci.edge.getFuelConsumption()` is a
**rate in mg/s summed over the vehicles currently on the edge**, so per-traversal fuel
is `rate / n_veh * traveltime`; with `n_veh == 0` the rate is 0, reproducing the
"empty edge looks free" trap in the online setting too. Set effort on *every* edge each
control period — an edge whose effort was never set falls back to travel time, silently
mixing units inside one route computation. Cap `getTraveltime` (it is
`length / mean speed` and diverges on a stopped edge).

## Verified findings: offline eco assignment helps, online eco routing at full
penetration does not

Measured on a two-alternative corridor (fast 1-lane bypass vs shorter 4-signal
arterial) at near-saturation peak demand, 5 demand seeds, Common Random Numbers,
paired t-tests.

* **The converged offline eco assignment was a strict Pareto improvement** over the
  travel-time user equilibrium: network CO2 -5.3% (p=0.010), mean travel time -9.9%
  (p=0.006), p90 travel time -16.6%, vehicle-km -2.5%, with ~10 pp of demand moved off
  the bypass. The reason is scenario-specific: the *travel-time* user equilibrium
  over-loads the capacity-limited fast route (UE != system optimum), so minimising fuel
  incidentally corrects a congestion inefficiency. **Always run a travel-time-only
  control at the same penetration** before crediting the eco objective for a benefit a
  plain travel-time router would also deliver.
* **The online reactive eco router's network CO2 is non-monotone in market
  penetration**: 2426.0 -> 2345.3 (25%) -> 2372.2 (50%) -> 2425.6 (75%) -> 2520.9 kg
  (100%). Both later legs are individually significant (p=0.013, p=0.007), and full
  penetration is **+3.9% worse than deploying nothing at all** (p=0.013).
* **At full penetration, optimising fuel produced more fuel than optimising time**
  (+68.3 kg CO2, p=0.005), and the whole alpha/beta trade-off curve is **degenerate**:
  CO2 *and* travel time both rise monotonically with the emission weight, so every
  positive eco weighting is strictly dominated. A "Pareto plot" that turns out
  monotone is itself the result worth reporting.
* **Mechanism, decomposed:** splitting the CO2 change into a *distance* effect and an
  *intensity* effect shows the eco router does exactly what it was asked — main-OD
  vehicle-km falls monotonically (-4.0% at full penetration) — but the arterial's
  emission intensity rises 347.9 -> 378.4 g CO2/veh-km as signal waiting per vehicle
  rises 13%. At full penetration the intensity penalty (+184.5 kg) is more than double
  the distance saving (-82.1 kg). **Eco routing buys distance and pays for it in
  stop-and-go.**
* **The failure is allocation, not (mainly) timing — and the failure mode swaps with
  the objective.** Against a non-reactive static-split reference (the technique from
  [[information-penetration-and-congestible-routing]]), the online *travel-time*
  router at full penetration landed on a near-optimal average split (allocation cost
  +6.9 kg) and lost everything to herding (timing +137.9 kg), while the online *eco*
  router's loss was mostly allocation (+144.7 kg): it over-diverted 5 pp past even the
  offline eco equilibrium's split (p=0.004). **The same penetration level, the same
  controller, two different failure modes — because effort is an *average* cost and
  each vehicle never sees the marginal emissions its own arrival imposes on the queue
  it is joining.**
* **The paradox belongs to the reactive implementation, not the objective.** The
  offline eco *equilibrium* (2287.7 kg) beat both the do-nothing baseline (2426.0 kg)
  and the best constant static split (2307.8 kg), while the online reactive version of
  the same objective at full penetration (2520.9 kg) was worse than doing nothing —
  +233.1 kg vs the offline equilibrium, p=0.0001. Reporting only the online arm would
  falsely indict eco routing as a concept.
* **The congestible-good signature reappears in the emissions domain.** Being equipped
  cost 10-15 s of travel time at every penetration level, and the equipped group's own
  per-vehicle CO2 advantage vanished and *reversed* by 75% penetration (971.3 vs
  965.8 g). At that same 75% level, unequipped drivers were already better off than
  anyone in the 0% baseline (321.3 s vs 346.8 s mean travel time; not checkable at
  100% penetration, where no unequipped vehicles remain) — the same free-riding
  pattern documented for rerouting devices in
  [[information-penetration-and-congestible-routing]], now with an environmental
  rather than a purely time-based objective.

## Practical takeaways

- Build a free-flow probe table before any emission-weighted assignment; never let an
  unsampled edge reach the router.
- Use `*_perVeh`, never `*_abs`, as the routing measure.
- Make weight-file intervals span the whole departure window, and choose the interval
  length by the zero-sample fraction it produces.
- Always run a `beta = 0` (travel-time-only) control at every penetration level.
- Sweep penetration rather than testing 0% vs 100%; the interesting behaviour is the
  interior maximum/minimum.
- Report the offline (converged) and online (reactive) versions of the same objective
  side by side — they can disagree in *sign*.
- The obvious untested fix, given the diagnosed mechanism, is a **marginal** rather
  than average emission cost on the effort channel.

See the `implement-eco-routing` skill for the full pipeline, the two mechanism
controls, and reusable scripts.
