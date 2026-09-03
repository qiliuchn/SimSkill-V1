---
summary: SUMO's built-in actuated (gap-based) and delay_based traffic-light types adapt phase durations at runtime from auto-generated induction-loop detectors, cutting mean waiting time by roughly 80-97% versus a fixed-time plan on identical demand, with the advantage largest under light demand and narrowing as load increases.
keywords:
  - actuated-traffic-lights
  - delay_based
  - tlLogic
  - induction-loop-detectors
  - adaptive-signal-control
created: 2026-07-23T16:11:52
last_updated: 2026-08-05T06:00:00
sources:
  - "[[episodic-memory/2026-07-23_15-58-44/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-23_15-58-44/attempts/attempt-1/critic-agent-feedback.json]]"
  - https://sumo.dlr.de/docs/Simulation/Traffic_Lights.html
related_pages:
  - "[[tlscycleadaptation]]"
  - "[[tlscoordinator]]"
  - "[[abstract-network-generation]]"
  - "[[sumo-output-files]]"
  - "[[max-pressure-signal-control]]"
  - "[[roundabout-modeling-and-comparison]]"
  - "[[waut-time-of-day-signal-plan-switching]]"
  - "[[connected-vehicle-penetration-and-detector-free-signal-control]]"
  - "[[nema-dual-ring-controller]]"
  - "[[actuated-signal-detector-design-and-fault-tolerance]]"
  - "[[webster-method]]"
  - "[[autonomous-intersection-management-safety-and-performance-envelope]]"
related_skills:
  - control-signals-with-actuated-tls
  - create-grid-network
  - optimize-signals-by-tlscycleadaptation
  - optimize-signals-by-tlscoordinator
  - implement-maxpressure-traci-controller
  - design-actuated-signal-detector-placement-and-fault-tolerance
  - create-roundabout-network
  - implement-reservation-based-autonomous-intersection-management
related_skills_for_graph_view:
  - "[[control-signals-with-actuated-tls]]"
  - "[[create-grid-network]]"
  - "[[optimize-signals-by-tlscycleadaptation]]"
  - "[[optimize-signals-by-tlscoordinator]]"
  - "[[implement-maxpressure-traci-controller]]"
  - "[[design-actuated-signal-detector-placement-and-fault-tolerance]]"
  - "[[create-roundabout-network]]"
  - "[[implement-reservation-based-autonomous-intersection-management]]"
---

# Actuated Traffic Signals

SUMO has two built-in `tlLogic` types that adapt phase durations **at runtime**, from within the simulation itself — no external controller or offline plan computation needed. This is a different category from every other signal-control approach in memory: [[tlscycleadaptation]] and [[tlscoordinator]] both compute a **static** plan once from historical routed demand, and an external TraCI/RL loop (e.g. `optimize-signals-by-qlearning`) drives signals from **outside** the simulation. Actuated/delay_based logic instead reacts live to detector data every step.

## The two types

- **`type="actuated"`** (gap-based): extends the current green phase as long as vehicles keep arriving within a gap threshold (`max-gap`, default 3.0 s) at an approach's detector; if no vehicle is detected within that gap, the phase "gaps out" and the signal moves to the next phase.
- **`type="delay_based"`**: extends green based on **accumulated vehicle delay** (time loss relative to free-flow) on the approach, rather than raw gap detection — more directly optimizing for what usually actually matters (how much time vehicles are losing), at the cost of a slightly different tuning surface.

Both are bounded per-phase by `minDur`/`maxDur` (a phase can never run shorter than `minDur` or longer than `maxDur`, regardless of what the detectors say).

## Setting it up

`netgenerate`/`netconvert` expose `--tls.default-type <STR>` (`static`/`actuated`/`delay_based`), applied to every junction with an otherwise-unspecified type — this can be set directly at network-generation time, so building the *same* network topology multiple times with only this option changed produces a clean, controlled comparison set:

```bash
netgenerate --grid ... -j traffic_light --tls.default-type actuated -o grid_actuated.net.xml
```

Resulting `<tlLogic>` elements automatically carry `minDur`/`maxDur` on their green `<phase>` entries (commonly `5`/`50` by default), with phase states/yellow-phase structure otherwise identical to the static case:

```xml
<tlLogic id="A0" type="actuated" programID="0" offset="0">
    <phase duration="42" state="GGggrrrrGGggrrrr" minDur="5" maxDur="50"/>
    <phase duration="3"  state="yyyyrrrryyyyrrrr"/>
    <phase duration="42" state="rrrrGGggrrrrGGgg" minDur="5" maxDur="50"/>
    <phase duration="3"  state="rrrryyyyrrrryyyy"/>
</tlLogic>
```

## Detectors: SUMO auto-generates them

**No explicit `<inductionLoop>` additional file is required for basic actuated/delay_based operation** — SUMO builds the necessary detectors internally at load time for any junction with an actuated-family `type`. This was independently verified: a plain `.net.xml` with `type="actuated"`/`delay_based` and no detector definitions anywhere produces genuinely adaptive behavior (phase durations visibly responding to traffic, not fixed at some nominal value), with zero warnings about missing detectors. Only declare detectors explicitly if the scenario needs non-default placement or parameters.

## Key parameters and their defaults

| Parameter | Type | Meaning | Default |
| --- | --- | --- | --- |
| `minDur` / `maxDur` | both | hard bounds on a green phase's duration regardless of detector input | typically `5`/`50` (network-generator dependent) |
| `max-gap` | actuated | seconds of no detection before the phase gaps out | 3.0 s |
| `detector-gap` | actuated | auto-detector's distance upstream of the stop line, in seconds of travel time at lane speed | 2.0 s |
| `passing-time` | actuated | assumed vehicle-clears-detector time used in the gap calculation | 2.0 s |
| `minTimeLoss` | delay_based | minimum per-vehicle time loss counted toward the delay-based extension decision | 1.0 s |
| `detectorRange` | delay_based | how far back delay is measured along the approach | whole lane |

Override any of these via `<param key="..." value="..."/>` children on the `<tlLogic>` element — fetch https://sumo.dlr.de/docs/Simulation/Traffic_Lights.html#actuated_traffic_lights for the exact key names and the delay_based section for its parameters before assuming a specific override syntax.

## Actuated vs. fixed-time: the load-dependence finding

A controlled 3×3 comparison (fixed-time / gap-based actuated / delay_based, crossed with low/medium/high demand, identical routes per demand level) found:

- Both actuated types substantially beat fixed-time at every demand level: roughly **-82% to -97% mean waiting time**, **-26% to -38% mean travel time**, **+25% to +49% mean speed**, with a slight throughput *gain*, not a cost.
- **`delay_based` consistently outperformed gap-based `actuated`** on every metric at every demand level.
- **The relative advantage is largest under light demand and narrows as demand rises** — clearest for `delay_based`, whose waiting-time reduction eroded monotonically (e.g. -96.9% → -93.7% → -89.9% from low to high demand in one measured run) as delay accumulated faster than actuation could shed it. Gap-based `actuated`'s advantage was comparatively load-flat.
- This erosion is the *expected* qualitative signature of actuated control, not a sign of a broken comparison — a fixed-time plan wastes less green time to reclaim once intersections are already busy, so the ceiling on improvement naturally comes down as load increases.
- A high-capacity network (e.g. a small single-lane grid with many parallel routes) may never actually saturate even at a "high" demand level (0 teleports, no gridlock) — that reflects the network's capacity margin, not a flaw in the test. Seeing the erosion trend reach its true endpoint (actuation's advantage vanishing entirely) requires a genuinely capacity-constrained network, not just higher demand on a high-capacity one.

See the `control-signals-with-actuated-tls` skill for the full setup/comparison workflow and a bundled comparison script. For a custom, hand-written control law applied externally via TraCI rather than SUMO's own built-in logic, see [[max-pressure-signal-control]] — a verified comparison found native actuated control still beat a max-pressure controller at moderate demand, with the gap narrowing as demand rose. For a non-signal control paradigm entirely — a roundabout, where right-of-way is structural rather than timed — see [[roundabout-modeling-and-comparison]], which found the same "signals impose delay with nothing to relieve at light demand" pattern extending to a three-way comparison including roundabouts.
