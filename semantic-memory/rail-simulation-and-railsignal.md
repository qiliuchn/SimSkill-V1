---
summary: SUMO models rail traffic via vClass="rail" bidirectional track (single-lane edge pairs with spreadType="center", recognized as bidi by netconvert), carFollowModel="Rail" with a trainType for realistic traction, and rail_signal junctions that arbitrate meets between opposing trains on single-track sections — verified deadlock-free and collision-free on a passing-siding corridor, contingent on giving each station its own signal block.
keywords:
  - rail-simulation
  - railSignal
  - rail-signal
  - bidirectional-track
  - carFollowModel-Rail
  - trainType
  - passing-siding
created: 2026-07-25T09:30:00
last_updated: 2026-08-06T20:18:44
sources:
  - "[[episodic-memory/2026-07-25_09-03-42/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-25_09-03-42/attempts/attempt-1/critic-agent-feedback.json]]"
  - https://sumo.dlr.de/docs/Simulation/Railways.html
related_pages:
  - "[[roundabout-modeling-and-comparison]]"
  - "[[vehicle-class-lane-permissions]]"
  - "[[public-transport-and-intermodal-routing]]"
  - "[[sumo-output-files]]"
  - "[[rail-crossing-junction-mechanics]]"
  - "[[street-running-tram-reservation-and-right-of-way-tradeoffs]]"
related_skills:
  - build-rail-corridor-with-railsignal
  - create-roundabout-network
  - model-vclass-lane-permissions
  - simulate-multimodal-transit
  - simulate-street-running-tram-corridor
related_skills_for_graph_view:
  - "[[build-rail-corridor-with-railsignal]]"
  - "[[create-roundabout-network]]"
  - "[[model-vclass-lane-permissions]]"
  - "[[simulate-multimodal-transit]]"
  - "[[simulate-street-running-tram-corridor]]"
---

# Rail Simulation and railSignal

SUMO models rail/train traffic through genuinely distinct mechanics from ordinary road vehicles: `vClass="rail"` track, a `Rail` car-following model, and `rail_signal` junctions that arbitrate right-of-way on single-track sections shared by opposing trains. This is a structurally separate mode from every other "transit" capability in memory — [[public-transport-and-intermodal-routing]]'s buses run as ordinary road vehicles on shared lanes with no analogous single-track conflict-resolution mechanism.

**This exclusive-right-of-way case should not be assumed to generalize to street-running rail** (tram/LRT/streetcar sharing a signalized road with cars): a bare `vClass="tram"` does **not** inherit `vClass="rail"`'s effective inability to lane-change — that behavior here is a side effect of single-lane track, not a vClass property — and street-running is controlled by ordinary road `tlLogic`, not `rail_signal`, since it has no single-track meet conflict to arbitrate. See [[street-running-tram-reservation-and-right-of-way-tradeoffs]] and `simulate-street-running-tram-corridor` for the in-street case and the mechanics/findings that diverge from this page's.

## Bidirectional single track

A rail section shared by both directions is authored as **two single-lane edges, one per direction, both with `spreadType="center"`** so they overlay exactly — `netconvert` then recognizes them as a genuine bidirectional pair, marking each edge with a `bidi=` attribute pointing at its counterpart in the compiled net. Omitting `spreadType="center"` or offsetting the pair prevents this recognition. A passing siding is modeled as two *parallel* edges between the same pair of nodes (a straight "main" track plus an offset "siding" track, using an explicit `shape=` on the siding to route it visibly apart) so a held train can wait on one track while another passes on the other.

## Train definitions

```xml
<vType id="ice3" vClass="rail" carFollowModel="Rail" trainType="ICE3" length="200" accel="0.8" decel="0.9" maxSpeed="44.44"/>
```

`carFollowModel="Rail"` switches to rail-specific longitudinal dynamics; `trainType` (e.g. `ICE3`, `Freight`) layers on realistic traction/resistance/mass behavior appropriate to that class of train. `length`/`accel`/`decel`/`maxSpeed` should still be set explicitly for the specific train being modeled. Station dwells use ordinary duration-based `<stop>` elements referencing a `busStop` on the station's platform edge — `busStop` works unmodified for rail vClass, no separate rail-stop element exists.

## rail_signal semantics and verifying a meet

A `rail_signal`-type junction (set via `<node type="rail_signal">` in plain-XML authoring) arbitrates access to the block(s) it controls, holding a train at the signal until the conflicting block is clear rather than letting it proceed into an occupied single-track section. **Verifying that a signal genuinely resolved a meet requires more than checking for the absence of a collision or teleport** — those confirm safety was maintained, but not *how*, or whether the intended siding-based meet actually occurred versus some other (still safe but unintended) resolution. Verification needs FCD data (position over time), because `tripinfo`'s `waitingTime` alone confirms *that* a train waited but not *where*:

1. Identify a train's genuine signal-hold periods: near-zero speed, outside any scheduled station-dwell window (read from `--stop-output`, not hardcoded, since dwell times can shift).
2. Confirm the two trains' occupancy of the actually-single-track section(s) was time-disjoint — never simultaneously present on the same single-track bidirectional edge (a true head-on hazard check).
3. Confirm zero collisions/teleports (from `summary.xml`/collision output) and that both trains actually arrived (non-negative arrival time), ruling out deadlock.

## The station-block design lesson

**A station platform placed directly on a shared single-track section (rather than behind its own dedicated signal block) can produce an origin-station standoff instead of a siding-based meet.** In a verified build, an initial 4-node design (stations at the single-track's own endpoints) was already collision- and deadlock-free — but held the waiting train at its *origin station* the entire time, because the opposing train's platform occupied the shared single-track block from the very start of the simulation, before either train had even departed. Adding dedicated station-entrance `rail_signal` nodes between each station and the through single track gave each station its own block, letting a departing train actually advance into the contested section and be held at the siding turnout as intended — the correct, more realistic meet-resolution behavior. When a scenario specifically calls for demonstrating siding-based conflict resolution (rather than just "no collision, whichever safe outcome occurs"), station block placement is the design choice that determines it.

## Measured finding

On a ~3km single-track corridor with a mid-point passing siding, a faster passenger train (ICE3) and a slower freight train departing simultaneously from opposite ends: the passenger train was held 72s at the siding turnout — confirmed genuinely stationary in FCD at that exact location, matching `tripinfo`'s `waitingTime` exactly — while the freight train, which had entered the contested single-track section first, passed through on the parallel siding track without ever being held. The two trains' occupancy of the shared section was confirmed time-disjoint; zero collisions, zero teleports, both completed their routes. Signal arbitration in this scenario followed entry order into the contested block, not train class or speed — worth checking explicitly rather than assuming a particular train type gets priority by default.

See the `build-rail-corridor-with-railsignal` skill for the full network/route templates, verification script, and design guidance.
