---
summary: Street-running tram/LRT in SUMO needs its lane-changing structurally suppressed (unlike vClass="rail", the tram vClass lane-changes by default on ordinary road lanes), its median reservation encoded as a lane permission plus a separate connection permission for the one junction movement that legitimately crosses it, and ordinary tlLogic rather than railSignal control; verified findings include a "tram trap" where a single non-evasive blockage explodes tail/variance (headway CV +143%) far more than the mean, a protected left-turn phase costing corridor-wide person-hours 25-66% more than prohibiting-and-rerouting the same conflicting movement, and a lane-conversion break-even ridership that is congestion-dependent — never paying off against a no-tram baseline in the tested range, but overtaking mixed running once car demand is oversaturated.
keywords:
  - tram
  - light-rail
  - LRT
  - streetcar
  - street-running-rail
  - median-reservation
  - right-of-way-class
  - lane-permission
  - connection-permission
  - break-even-ridership
created: 2026-08-06T20:18:44
last_updated: 2026-08-06T20:18:44
sources:
  - "[[episodic-memory/2026-08-06_20-12-39/attempts/attempt-1/action-agent-output.md]]"
  - "[[episodic-memory/2026-08-06_20-12-39/attempts/attempt-1/critic-agent-feedback.md]]"
related_pages:
  - "[[rail-simulation-and-railsignal]]"
  - "[[vehicle-class-lane-permissions]]"
  - "[[dynamic-hard-shoulder-running-with-traci-lane-permissions]]"
  - "[[transit-signal-priority]]"
  - "[[managed-lanes-empty-lane-paradox-and-person-throughput]]"
  - "[[bus-stop-infrastructure-design-parking-mechanism-and-tsp-interaction]]"
  - "[[curbside-delivery-blocking-externality]]"
related_skills:
  - simulate-street-running-tram-corridor
  - build-rail-corridor-with-railsignal
  - design-bus-stop-placement-type-and-spacing
  - implement-transit-signal-priority
  - model-curbside-delivery-and-lane-blocking-externality
  - model-vclass-lane-permissions
related_skills_for_graph_view:
  - "[[simulate-street-running-tram-corridor]]"
  - "[[build-rail-corridor-with-railsignal]]"
  - "[[design-bus-stop-placement-type-and-spacing]]"
  - "[[implement-transit-signal-priority]]"
  - "[[model-curbside-delivery-and-lane-blocking-externality]]"
  - "[[model-vclass-lane-permissions]]"
---

# Street-Running Tram Reservation and Right-of-Way Tradeoffs

Street-running rail transit (tram/LRT/streetcar) is structurally distinct from both [[rail-simulation-and-railsignal]]'s exclusive-right-of-way heavy rail and ordinary mixed-traffic buses ([[bus-stop-infrastructure-design-parking-mechanism-and-tsp-interaction]]): it has its own vClass and infrastructure like rail, but shares a signalized road network with cars like a bus — and unlike a bus, it physically cannot steer around an obstruction. See `simulate-street-running-tram-corridor` for the full build/verify/analyze workflow; this page holds the underlying SUMO mechanics and the measured right-of-way tradeoff findings.

## The tram vClass does not suppress lane-changing by default

`vClass="rail"`'s apparent inability to lane-change is a side effect of running on single-lane exclusive track — there's no second lane to change to. `vClass="tram"` on an ordinary multi-lane road has no such structural constraint: a direct behavioral probe (2-lane edge, slow blocker in lane 0, tram departing in lane 0) confirmed the tram **does lane-change** by default, identically to any other vehicle class. SUMO's default `tram` vType: length 22.0 m, width 2.4 m, height 3.2 m, accel 1.0 m/s², decel 3.0 m/s², emergencyDecel 7.0 m/s², maxSpeed 22.22 m/s (80 km/h), minGap 2.5 m, guiShape `"rail/railcar"`. Any scenario requiring a lane-confined tram (essentially any reserved-lane or fixed-guideway study) must enforce that confinement structurally via lane permission and verify it held via `--lanechange-output` — SUMO will not do this on the strength of the vClass alone.

## Two distinct permission mechanisms for a crossable-but-not-drivable reservation

A median tram reservation that cars may cross at a junction (typically a left turn) but not drive along mid-block requires **both** of the following, not either alone:

- A **lane permission** (`allow="tram"`) on the reservation's running-length lane, blocking mid-block car use for its entire length.
- A separate **connection permission** (`disallow="passenger"` added directly to the specific `<connection>` element) for any one movement you want to prohibit from crossing it — because the compiled net's `<connection>` elements carry no `allow`/`disallow` of their own by default, inheriting permission from the approach/via lane instead. Restricting only the lane would illegally block every movement through it, including ones you want to keep legal; restricting only a connection leaves the lane itself open to mid-block car use.

The crossing movement's own auto-generated internal junction lane is a **separate SUMO lane object** from the mid-block reservation lane and does not automatically inherit the reservation's restriction — this is the same "netconvert bakes permissions into internal connector lanes independently of the source lane's intent" gotcha documented in [[dynamic-hard-shoulder-running-with-traci-lane-permissions]], observed here from the connection-permission side rather than the lane-closure side.

**Verification requires three independent angles**, because authoring intent and compiled reality can diverge silently:
1. Grep the *compiled* `.net.xml` directly for the lane's `allow` and the connection's `disallow`.
2. Run `duarouter` **without** `--ignore-errors` on a trip desiring the prohibited movement — a returncode of 0 does *not* prove the movement is legal (duarouter silently finds any legal alternate route); the proof is inspecting the realized route's edge list for a detour.
3. Add a `laneData` detector on the reservation's mid-block lanes filtered by `vTypes`, confirming car `sampledSeconds ≈ 0` there while the diverted demand still completes its trips (i.e. genuinely discharged, not gridlocked). Note: `<laneData lanes="...">` does **not** filter what SUMO writes to the output file — it dumps every lane regardless; filtering must happen when reading the output by lane id.

## Signal control: ordinary tlLogic, and what adding the lane costs

Street-running is controlled by the road's ordinary `tlLogic`, not `railSignal` — `railSignal` exists specifically for single-track block conflicts between opposing trains (see [[rail-simulation-and-railsignal]]), a conflict street-running doesn't have since each direction gets its own signal-controlled lane. Two measured, verified costs of adding the lane:

- **Controlled-link count grows**: a 6-signal arterial example measured 14 links (no tram) → 18 (shared tram lane) → 22 (exclusive tram lane) at one junction.
- **A protected left-turn phase measurably grows cycle length**: 66 s (4 phases, left turns prohibited) vs. 79 s (6 phases, dedicated protected-left phase) in a verified example — a systemic cost paid every cycle by all traffic, not a local one.

## Left-turn-conflict resolution: prohibition beats a protected phase

Comparing left-turn treatments at a reservation-crossing junction, a real measured result found **prohibiting the conflicting movement and rerouting it via a parallel street beats adding a protected left-turn phase, corridor-wide** — by +25% to +66% total person-hours for "protected" vs. "prohibited" across two tested configurations (unprioritized and TSP-equipped tram). The mechanism is the cycle-length tax above: the protected phase's added seconds fall on every vehicle every cycle at that signal, not just the minority actually turning left, and can even *increase* the tram's own signal wait despite existing to help it (since the tram now also waits through the longer cycle). The individual left-turning vehicle is faster under "protected" — direct movement vs. a detour — but that local improvement is swamped by the system-wide cost. Don't assume the individually-safer-feeling treatment (a dedicated protected phase) is the collectively better one; measure the corridor-wide tradeoff.

## The tram trap: tail/variance fragility to a non-evasive blockage

A tram confined to one lane by permission has no escape route around a stopped/double-parked vehicle mid-block — unlike a bus in mixed traffic, which can change lanes around it (see [[curbside-delivery-blocking-externality]] for the analogous car-side externality). **The effect is concentrated in the tail and variance, not the mean**, and checking only the mean will miss it entirely. A verified measured example: mean tram run time moved only +2–3% with a 300 s non-evasive blockage in place, while in the exclusive-reservation arm **max run time rose +35%, standard deviation +63%, and downstream headway coefficient-of-variation at the terminal stop rose +143%** (0.167→0.405). Counterintuitively, the arm with the more regular baseline service (exclusive reservation) was *more fragile* in relative terms to a single blockage than mixed running's already-noisier baseline. Report max/sd/headway-CV alongside the mean whenever evaluating a reservation's reliability under blockage risk.

## Break-even ridership is congestion-dependent

The decision-relevant question for choosing between no tram, mixed running (Class C), and an exclusive reservation (Class B) is not which wins on average but **at what ridership the reservation's transit benefit repays its car-lane opportunity cost, and whether that threshold moves with congestion** — following the person-throughput-over-vehicle-throughput accounting discipline of [[managed-lanes-empty-lane-paradox-and-person-throughput]], with car occupancy treated as an explicit varied parameter rather than a baked-in constant.

A verified measured example, swept across two car-congestion levels: the exclusive reservation **never** overtook mixed running on total person-hours at an uncongested car-demand level (tested to ~880 riders/hr corridor-wide) — but overtook it at ≈500–600 riders/hr once car demand was oversaturated. The reservation never overtook the no-tram baseline at all within the tested ridership range, at either congestion level. The general lesson: a lane's opportunity cost is only repaid once the congestion it relieves is severe enough that the lane's marginal value to cars is high — report break-even against both "vs. mixed running" and "vs. no tram" separately (they can differ enormously), and do not extrapolate a break-even curve past its tested ridership range.

## Where this diverges from the bus-transit precedent

Transit signal priority applied to the tram (the [[transit-signal-priority]] controller, reused unchanged, retargeted to `priority-vclass="tram"`) shows the same qualitative pattern as the bus finding: substantial signal-delay reduction at a modest, proportionate car-delay cost. The genuine differences from the bus case: SUMO's default tram vClass dimensions/kinematics differ measurably from a typical bus, a multi-car tram consist governs intersection occupancy time more than a bus's shorter body would, and — the consequential one — a tram is *deliberately and structurally* incapable of lane-changing once confined by permission, where a bus in mixed traffic is not; this is precisely what produces the tram trap's fragility to a blockage that a bus would mostly absorb by merging around it.
