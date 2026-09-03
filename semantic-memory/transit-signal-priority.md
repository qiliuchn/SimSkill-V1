---
summary: Transit Signal Priority (TSP) in SUMO is implemented via a TraCI controller that grants an approaching priority-vClass vehicle green extension or red-truncation-based early green by perturbing only the current signal phase's remaining duration, requiring an offset-recovery mechanism to keep grants individually attributable and a per-cycle grant limit to keep cross-street traffic from being starved.
keywords:
  - transit-signal-priority
  - TSP
  - bus-priority
  - green-extension
  - red-truncation
  - signal-preemption
  - offset-recovery
created: 2026-07-24T15:25:00
last_updated: 2026-08-06T20:18:44
sources:
  - "[[episodic-memory/2026-07-24_14-55-20/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-24_14-55-20/attempts/attempt-1/critic-agent-feedback.json]]"
  - https://sumo.dlr.de/docs/TraCI/Change_Traffic_Lights_State.html
related_pages:
  - "[[max-pressure-signal-control]]"
  - "[[glosa-eco-driving]]"
  - "[[public-transport-and-intermodal-routing]]"
  - "[[actuated-traffic-signals]]"
  - "[[emergency-vehicle-preemption-and-bluelight]]"
  - "[[bus-stop-infrastructure-design-parking-mechanism-and-tsp-interaction]]"
  - "[[battery-electric-bus-energy-and-charger-sizing]]"
  - "[[street-running-tram-reservation-and-right-of-way-tradeoffs]]"
related_skills:
  - implement-transit-signal-priority
  - implement-maxpressure-traci-controller
  - implement-glosa-speed-advisory-controller
  - simulate-multimodal-transit
  - design-bus-stop-placement-type-and-spacing
  - simulate-street-running-tram-corridor
related_skills_for_graph_view:
  - "[[implement-transit-signal-priority]]"
  - "[[implement-maxpressure-traci-controller]]"
  - "[[implement-glosa-speed-advisory-controller]]"
  - "[[simulate-multimodal-transit]]"
  - "[[design-bus-stop-placement-type-and-spacing]]"
  - "[[simulate-street-running-tram-corridor]]"
---

# Transit Signal Priority

Transit Signal Priority (TSP) grants an approaching priority vehicle — typically a bus — favorable treatment at a signalized intersection: **green extension** (holding an active green a bit longer so the vehicle clears before it turns) or **early green via red truncation** (shortening a conflicting green so the priority vehicle's phase arrives sooner). SUMO has no built-in TSP mechanism; it's implemented as a TraCI controller layered on top of a native fixed-time (`tlLogic type="static"`) program, using the same closed-loop pattern as [[max-pressure-signal-control]] and [[glosa-eco-driving]] but reacting to a specific vClass's approach rather than aggregate queue pressure or advising the vehicle instead of the signal.

## Detecting the approaching vehicle and its phase

`traci.vehicle.getNextTLS(vehicle_id)` returns `[(tlsID, linkIdx, dist, state), ...]` for the vehicle's upcoming signals; the nearest entry's `linkIdx` identifies exactly which movement (and therefore which phase) the vehicle needs, found by scanning the signal's green phases for the one whose RYG state character at `linkIdx` is `G`/`g`. Filtering by `traci.vehicle.getVehicleClass(vid)` restricts requests to the intended priority class.

## Perturbation mechanism: current-phase duration only

The controller should never call `setPhase` to jump the phase index. It should only call `traci.trafficlight.setPhaseDuration(tls, remaining)` on the phase currently active — lengthening it for green extension, or shortening its remaining duration toward zero for red truncation. SUMO's native static program continues to handle all sequencing, yellow, and clearance intervals; a priority grant is a bounded perturbation of one phase's length rather than a rewrite of the signal logic. `setPhaseDuration` sets the *remaining* duration of the current phase under TraCI semantics, which both directions rely on.

## Offset recovery is required, not optional

**Left uncorrected, a single truncation or extension permanently shifts the signal's cycle offset relative to its background fixed-time schedule.** Every subsequently-arriving priority vehicle then benefits (or is disadvantaged) by that leftover shift regardless of whether it made its own request — this breaks grant-to-benefit attribution and contaminates any baseline-vs-priority comparison, since the "baseline" schedule the comparison is measured against has silently drifted. The fix: track a per-signal "debt" value (positive when the signal is running ahead of schedule from a truncation, negative when behind from an extension) and repay it by flexing *only the cross-street green* — never the priority vehicle's own phase — the next time a cross phase is active and no priority vehicle is currently being served. This keeps every grant a bounded, individually-attributable perturbation rather than a permanent schedule shift.

## Unconditional vs. conditional priority

Unconditional/aggressive priority (grant on every approach, minimal cross-street minimum-green, no per-cycle cap) maximizes the priority vehicle's benefit but can badly starve cross-street traffic. Conditional TSP bounds this with a genuine cross-street minimum-green and a per-cycle grant limit (e.g. at most one grant per signal per cycle) — a real, enforced cap that must actually bind under the scenario's demand for the comparison to be meaningful; if the priority vehicle's headway is long relative to the cycle length, the limit may rarely trigger and conditional/aggressive converge to similar behavior, making the comparison uninformative.

## Verifying grants actually changed signal timing

A grant *log* entry only proves the controller *intended* an action — verify it actually changed what was simulated by also recording each phase's realized vs. nominal duration (a phase trace) and cross-referencing specific logged grant events against it: a logged truncation at time *t* should correspond to a phase ending near *t* with realized duration well below nominal, and a logged extension should correspond to a realized duration above nominal. This distinguishes a controller that works from one that only appears to.

## A grant-counting gotcha

When tracking how many priority requests were *blocked* by the per-cycle limit (a useful diagnostic alongside the actual grant count), dedupe the count **per phase-instance, not per simulation step**. A naive per-step increment while a blocking condition persists — e.g. throughout an entire multi-second green-extension window where the limit is already exhausted — inflates the blocked count far above the true number of distinct blocked opportunities, while the parallel truncation-blocking code path (naturally single-shot per phase) doesn't show the same inflation. This asymmetry can make "granted + blocked" sum to more than the true number of priority-vehicle-to-signal encounters, which should be caught as an internal-consistency check on the diagnostic numbers before reporting them.

## Measured aggressive-vs-conditional tradeoff

On a 3-signal fixed-time arterial (89 buses over ~1 hour, 40s headway, mixed arterial/cross-street car demand), identical demand and seed across all configurations: aggressive/unconditional priority cut bus mean travel time 45% (and even improved arterial car delay, since removing bus-related stop-and-go helps following traffic too) but increased cross-street car delay roughly 14x (267 grants, no per-cycle limit). Conditional TSP (10s cross minimum-green, 1 grant/signal/cycle) captured much of the bus benefit — travel time -15%, in-signal delay -36% — and still improved arterial flow, while limiting the cross-street cost to a proportionate increase, an order of magnitude smaller than aggressive's. The general lesson: unconditional priority is not free bus benefit bought at a small cost — it typically buys a modest additional bus improvement over a well-designed conditional scheme at a wildly disproportionate cross-street cost. A bounded conditional scheme is usually the actual best-balance configuration, not merely a compromise that sacrifices most of the bus benefit.

See the `implement-transit-signal-priority` skill for the full controller implementation and comparison workflow. [[bus-stop-infrastructure-design-parking-mechanism-and-tsp-interaction]] reuses this controller unchanged and finds that stop *placement* interacts strongly with TSP: a near-side stop can consume most of a priority grant's benefit via dwell, cutting TSP's signal-delay reduction roughly in half versus far-side/mid-block and even flipping TSP's net corridor effect from a gain to a loss — decide placement only after deciding whether TSP will run.
