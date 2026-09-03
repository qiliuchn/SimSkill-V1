---
summary: SUMO models emergency-vehicle full signal preemption via a TraCI controller that forces an immediate phase transition with a genuine yellow-then-all-red clearance interval before granting the vehicle's movement green (held until it physically clears the junction, then recovered), categorically different from transit-signal-priority's bounded current-phase-only perturbation; separately, device.bluelight causes surrounding traffic to physically yield laterally and form a rescue lane. Verified on a real corridor that preemption reduces emergency-vehicle travel time and stops at a real, bounded cross-street delay cost, with the bluelight and preemption effects cleanly isolated via a three-configuration design.
keywords:
  - emergency-vehicle-preemption
  - signal-preemption
  - bluelight
  - rescue-lane
  - all-red-clearance
created: 2026-07-29T16:10:00
last_updated: 2026-08-04T20:00:00
sources:
  - "[[episodic-memory/2026-07-29_15-43-18/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-29_15-43-18/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[transit-signal-priority]]"
  - "[[railroad-preemption-of-nearby-signalized-intersections]]"
related_skills:
  - implement-emergency-vehicle-preemption
  - implement-transit-signal-priority
  - control-signals-with-actuated-tls
related_skills_for_graph_view:
  - "[[implement-emergency-vehicle-preemption]]"
  - "[[implement-transit-signal-priority]]"
  - "[[control-signals-with-actuated-tls]]"
---

# Emergency-Vehicle Preemption and Bluelight

Full emergency-vehicle signal preemption in SUMO — implemented via a TraCI controller, not a native SUMO feature — forces an immediate, safety-correct transition to serve an approaching emergency vehicle's movement, distinct from [[transit-signal-priority]]'s bounded perturbation of the currently-active phase's duration.

## The mechanism: forced state transitions with manufactured clearance

Where transit signal priority only extends or truncates the current green phase (never jumping phase index, relying on the native program to handle sequencing), full preemption must construct its own transition from an arbitrary current state: any conflicting green movement is driven to `y` (yellow), held, then every link is forced to `r` (a genuine all-red clearance interval) before the emergency vehicle's target movement is finally granted `G`/`g`. This is implemented via direct `traci.trafficlight.setRedYellowGreenState` overrides — not phase-duration adjustment — specifically so that every clearance state string is directly loggable and independently auditable (a state string with zero `G`/`g` characters is the verifiable signature of genuine clearance).

**When the target movement is already green** when the emergency vehicle arrives (no conflicting movement needs clearing), the clearance sequence should be correctly skipped rather than blindly inserted every time — a real controller should check current state before deciding whether clearance is needed.

**The grant should be held based on verified vehicle position** (checking that the emergency vehicle no longer lists the junction among its upcoming traffic lights via `getNextTLS`), not a fixed timer — a timer risks releasing the grant too early or holding it needlessly long.

## `device.bluelight`: a distinct, complementary rescue-lane mechanism

SUMO's `device.bluelight` (equipped via `<param key="has.bluelight.device" value="true"/>` on the emergency vehicle's vType, with the sublane model enabled via `--lateral-resolution`) causes surrounding vehicles to physically yield laterally, forming a rescue lane ahead of the emergency vehicle — a genuinely separate mechanism from signal preemption, operating on car-following/lane-changing behavior rather than signal control.

## Isolating the two effects: a three-configuration design

Because bluelight and preemption are independent mechanisms that can each speed an emergency vehicle's progress, a clean study should run three configurations on identical background demand and seed: (a) baseline (neither mechanism active), (b) bluelight only, (c) bluelight plus preemption. This decomposes total benefit into a rescue-lane component (b vs. a) and a signal-control component (c vs. b) rather than conflating the two into a single before/after comparison.

## Verified findings

On a real 4-signal arterial corridor: emergency-vehicle corridor travel time fell from 144s (baseline) to 104s (bluelight alone) to 96s (bluelight plus preemption), with the vehicle's final stop eliminated only once preemption was active — decomposing to roughly 40 seconds of rescue-lane benefit and a further ~8 seconds plus one fewer stop from preemption specifically. Every preemption event showed a genuine all-red clearance interval in the raw controller log (zero `G`/`g` characters, held for the intended duration) except where correctly skipped for an already-green target movement. The rescue-lane effect was independently confirmed from FCD data: the vehicle immediately ahead of the emergency vehicle showed a substantially larger lateral gap from its path and a marked speed reduction specifically in the bluelight-equipped configurations.

**Preemption's benefit came at a real, bounded cross-street cost** — measurable additional waiting time and time loss on the conflicting approaches (roughly 183 and 232 additional vehicle-seconds respectively in a verified test) — a legitimate, quantifiable tradeoff for the emergency vehicle's roughly 48-second benefit, not a free improvement.

See the `implement-emergency-vehicle-preemption` skill for the full controller FSM, bluelight configuration, and three-configuration verification workflow.
