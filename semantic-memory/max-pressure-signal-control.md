---
summary: Max-pressure is a decentralized adaptive traffic-signal control rule that greedily serves the green phase with the highest queue-based "pressure" (incoming queue minus outgoing queue), theoretically maximizing throughput under saturation; in a verified SUMO comparison it decisively beat a fixed-time plan but lost to SUMO's native actuated control at moderate demand, with the gap narrowing as demand rose.
keywords:
  - max-pressure
  - adaptive-signal-control
  - queue-based-control
  - TraCI-controller
  - Varaiya
created: 2026-07-23T16:46:38
last_updated: 2026-08-07T01:30:23
sources:
  - "[[episodic-memory/2026-07-23_16-31-30/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-23_16-31-30/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[traci]]"
  - "[[actuated-traffic-signals]]"
  - "[[tlscycleadaptation]]"
  - "[[glosa-eco-driving]]"
  - "[[ramp-metering-with-alinea]]"
  - "[[transit-signal-priority]]"
  - "[[coordinated-adaptive-signal-control-detector-bias-and-transition-cost]]"
  - "[[autonomous-intersection-management-safety-and-performance-envelope]]"
  - "[[connected-vehicle-penetration-and-detector-free-signal-control]]"
related_skills:
  - implement-maxpressure-traci-controller
  - control-signals-with-actuated-tls
  - get-vehicles-state
  - implement-glosa-speed-advisory-controller
  - implement-alinea-ramp-metering
  - implement-reservation-based-autonomous-intersection-management
  - implement-scats-style-coordinated-adaptive-signal-control
related_skills_for_graph_view:
  - "[[implement-maxpressure-traci-controller]]"
  - "[[control-signals-with-actuated-tls]]"
  - "[[get-vehicles-state]]"
  - "[[implement-glosa-speed-advisory-controller]]"
  - "[[implement-alinea-ramp-metering]]"
  - "[[implement-reservation-based-autonomous-intersection-management]]"
  - "[[implement-scats-style-coordinated-adaptive-signal-control]]"
---

# Max-Pressure Signal Control

Max-pressure (Varaiya, 2013) is a decentralized adaptive traffic-signal control rule: at each signalized junction, greedily serve whichever green phase currently has the highest **pressure**, defined per phase as the queue length on its incoming (upstream) lanes minus the queue length on its outgoing (downstream) lanes:

```
pressure(phase) = sum(queue(l) for l in incoming_lanes(phase)) - sum(queue(l) for l in outgoing_lanes(phase))
```

Queue length is typically the number of halting vehicles on a lane (speed below a small threshold) — the same standard proxy used elsewhere for queue-length state (see `get-vehicles-state`'s `get_queue_length`). Using queue length (not raw vehicle count or fractional occupancy) on **both** sides of the subtraction keeps the formula unit-consistent and is what makes it theoretically grounded: the downstream term discounts serving a movement whose receiving lane is already backed up, making the controller spillback-aware rather than just locally greedy.

## Why it's theoretically notable

Max-pressure has a proven property that most heuristic adaptive controllers lack: under mild conditions, it is throughput-maximizing — if a stable signal-timing policy exists at all for a given demand, max-pressure will keep the network stable (queues won't grow unboundedly). This is fundamentally an **oversaturation-regime** guarantee: its design goal is preventing gridlock and maximizing sustainable throughput under heavy, imbalanced load, not necessarily minimizing average vehicle delay under light-to-moderate, well-behaved demand.

## Implementing it via TraCI

This requires a genuine external, closed-loop controller — not SUMO's own built-in actuated logic (see [[actuated-traffic-signals]] for that, a different mechanism entirely). Three pieces, all handled generically (not hardcoded per network) in the `implement-maxpressure-traci-controller` skill's bundled script:

1. Map each green phase to its controlled lane-to-lane movements via `traci.trafficlight.getControlledLinks` (index-aligned with the phase's RYG state string).
2. Enforce a minimum green time per junction via a tracked "green since" timestamp.
3. Route every phase switch through the network's own existing clearance yellow phase **and, if present, any all-red phase that follows it** — never jump directly from one green to another, and never jump directly from yellow to the next green either.

SUMO's own phase auto-advance must be suppressed (e.g. holding each phase at a very long `setPhaseDuration`) so the external controller has full authority over transition timing.

**Safety correction (verified in a later episode building an unrelated reservation-based
controller):** an implementation that inserted the clearance yellow but skipped a
following all-red phase produced a real, simulated junction collision on a 2-phase
permissive-left program — a fixed, short all-red is not automatically sufficient either,
since a vehicle already committed to the internal junction from standstill can need
several seconds to clear a long internal path. The robust fix is to hold all-red until
the junction's relevant internal lanes are **verified physically empty** (via
`traci.lane.getLastStepVehicleNumber` on the internal/via lanes), bounded by a capped
maximum wait so a permanently-blocked junction can't freeze the signal — see
`implement-maxpressure-traci-controller`'s Gotchas and
[[autonomous-intersection-management-safety-and-performance-envelope]], which
independently arrived at the identical "clear on occupancy, not a timer" principle from
a completely different (reservation-based) controller architecture.

## Verified comparison result

On a 4x4 grid with 2-lane arterials and an EW-imbalanced demand (a dominant east-west flow, light cross traffic), max-pressure was compared against a static fixed-time baseline and SUMO's native `type="actuated"` control on identical demand:

- **Max-pressure decisively beat fixed-time** (roughly -71% mean waiting time, -50% time loss, -19% trip duration at 1300 veh/h) — consistent with the general finding in [[actuated-traffic-signals]] that any reasonable adaptive control beats a static plan by a wide margin.
- **Max-pressure lost to native actuated control at moderate demand** (+90% mean waiting time relative to actuated at 1300 veh/h). This is not a sign of a broken implementation — it reflects that max-pressure's design goal is throughput/stability under saturation, not minimum average delay under moderate load, where a well-tuned detector-reactive controller (native actuated) can do just as well or better.
- **The gap narrowed as demand rose** (waiting-time disadvantage vs. actuated: +90% → +65% → +14% across 1300/2600/6000 veh/h on the same network), and at the highest tested demand max-pressure actually cleared the network slightly faster than actuated — the expected direction of max-pressure's theoretical advantage, though a strict overtake on mean delay would likely require a genuinely capacity-constrained/bottleneck network rather than just raising demand on a high-reserve-capacity grid (this test network never teleported/gridlocked even at 6000 veh/h).

**Takeaway for future comparisons:** don't treat "a correctly-implemented max-pressure controller loses to native actuated control" as evidence of a bug — verify the phase-mapping/min-green/yellow-transition mechanics are genuinely correct first (see `implement-maxpressure-traci-controller`), then report a loss at moderate demand as a legitimate, condition-dependent result; the interesting empirical question is how the gap changes with demand level, not just who wins at one operating point.

See the `implement-maxpressure-traci-controller` skill for the full controller implementation and the general phase-mapping/min-green/yellow-transition pattern it's built on (reusable for other custom TraCI control algorithms, not just max-pressure). For the vehicle-side inverse of this pattern — commanding vehicle speed instead of signal phase, based on the same kind of `getAllProgramLogics` phase introspection — see [[glosa-eco-driving]]. For a different control object entirely — a ramp's continuous release rate rather than an intersection phase — see [[ramp-metering-with-alinea]], whose feedback-loop structure (read detector state, compute a control signal, actuate) is the same closed-loop TraCI pattern applied to a freeway on-ramp.
