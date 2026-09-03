---
summary: GLOSA (Green Light Optimal Speed Advisory) is a closed-loop TraCI controller that advises vehicle speed from upcoming signal timing (derived via getNextTLS + getAllProgramLogics + getNextSwitch) so vehicles catch greens or glide to a stop instead of braking hard; verified to cut stops/waiting/hard-braking substantially but to increase emissions and travel time on an uncoordinated corridor, since HBEFA3 penalizes sustained low-speed cruising more than the stop-start bursts it replaces.
keywords:
  - GLOSA
  - eco-driving
  - speed-advisory
  - getNextTLS
  - green-light-optimal-speed-advisory
created: 2026-07-23T17:56:30
last_updated: 2026-07-23T17:56:30
sources:
  - "[[episodic-memory/2026-07-23_17-30-30/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-23_17-30-30/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[traci]]"
  - "[[change-vehicle-state]]"
  - "[[max-pressure-signal-control]]"
  - "[[vehicle-emissions-modeling]]"
  - "[[transit-signal-priority]]"
related_skills:
  - implement-glosa-speed-advisory-controller
  - implement-maxpressure-traci-controller
  - simulate-fleet-emissions
related_skills_for_graph_view:
  - "[[implement-glosa-speed-advisory-controller]]"
  - "[[implement-maxpressure-traci-controller]]"
  - "[[simulate-fleet-emissions]]"
---

# GLOSA / Eco-Driving Speed Advisory

GLOSA (Green Light Optimal Speed Advisory) is a closed-loop TraCI controller that advises **vehicle** speed — not signal timing — based on the upcoming traffic light's schedule, so an equipped vehicle either speeds up to catch a green it can still reach, or glides smoothly down to arrive just as a red turns green, instead of braking hard and idling. It's the vehicle-side complement to [[max-pressure-signal-control]]'s signal-side closed-loop control: same general TraCI stepping-loop pattern (read state → decide → command → repeat), inverted as to which object is being controlled.

## Deriving "time until green" — the non-obvious part

`traci.vehicle.getNextTLS(veh)` returns `[(tlsID, linkIndex, distance, currentState), ...]` — the nearest upcoming signal, its distance, and the *current* state character for the vehicle's specific movement. This does **not** tell you when that movement next turns green. Getting that requires combining it with the signal's own program:

- `traci.trafficlight.getNextSwitch(tls)` — when the *current* phase ends.
- `traci.trafficlight.getAllProgramLogics(tls)[0].phases` — every phase's `state` string and `duration`.

Walk the phase list forward from the current phase (~2 cycles is enough lookahead), reading `state[link_idx]` of each phase to build the actual sequence of green/not-green windows for that vehicle's movement. This phase-introspection technique is the same one `implement-maxpressure-traci-controller` uses to map phases to movements, applied here to build a time-based schedule instead of a lane-set mapping.

## One decision rule, two behaviors

Rather than writing separate "speed up" and "glide down" logic, a single rule covers both: search the derived green windows in arrival order, and a window `[gs, ge]` is *catchable* if some constant speed within `[v_min, v_max]` lands the vehicle's arrival inside it (the reachable-arrival interval `[now + dist/v_max, now + dist/v_min]` overlaps `[gs, ge]`). For the earliest catchable window, target the earliest feasible arrival at or after `gs` and back out the required constant speed:

- If the *current* green is about to end but is still just catchable, this naturally computes a **higher** speed (up to the limit) to catch it.
- If the light is red, the earliest catchable window is the *next* green, and the same rule naturally computes a **lower glide** speed so the vehicle arrives right as it turns green.
- If no green is catchable at all (too far even at max speed, or would arrive too early even at min speed), the vehicle must stop — advise a comfortable glide-to-stop speed (`v = sqrt(2 · a_comf · distance)`) rather than an abrupt brake.

## Applying it safely

`traci.vehicle.setSpeed(veh, target)` under SUMO's **default** speed mode (bitset 31, every safety check enabled) is sufficient — no override needed. With safe-following and red-light-braking checks active, the commanded target can only ever be *capped downward* by real safety constraints; it cannot force a collision or a red-light violation. See [[change-vehicle-state]] for the general `setSpeed`/speed-mode API and its warning against disabling safety checks broadly — a correctly-designed GLOSA controller is a case where that warning's advice (don't override) is the right call, not a limitation to work around. Release control (`setSpeed(veh, -1)`) once the vehicle has no signal ahead, its nearest signal is beyond the advisory horizon, or it's within a small clearing distance of the stop line, so normal car-following resumes.

## Verified finding: stops down, emissions and travel time can go up

On a 5-junction arterial corridor with identical, **uncoordinated** (no green-wave) fixed-time signals and moderate through-traffic demand, comparing a baseline (no advisory) against 100%-penetration GLOSA on identical routes:

- **Stops per vehicle: -21.6%.** **Waiting time: -15.5%.** **Hard-braking events: -14.2%.** **Network-wide speed variance: -24.0%.** — exactly the smoothness/stop-reduction benefits GLOSA targets, genuinely delivered.
- **Total CO2/fuel: +8.3%. Mean trip duration: +9.3%.** — a real, honestly-measured *cost*, not a bug or a unit-conversion error.

**Why**: on an uncoordinated corridor, most red lights simply aren't catchable at any reasonable speed (there's no green wave synchronizing them to a plausible travel speed), so the controller spends most of its time gliding vehicles into a sustained low-speed approach rather than speeding up to catch greens. HBEFA3's speed-emission relationship (see [[vehicle-emissions-modeling]]) means sustained low-speed cruising (roughly 18-25 km/h in the verified case) emits *more* CO2 per km than the stop-start acceleration bursts it replaces — and the extra time spent gliding also adds to total time-in-network, compounding the effect. A 50%-penetration run showed the same directional pattern at roughly half magnitude, confirming it's a real, scalable effect rather than an artifact of full equipping.

**Practical implication**: GLOSA's benefit profile depends on whether the signals it's advising against are coordinated. A green-wave-coordinated corridor (where speed-up-to-catch-a-reachable-green dominates over glide-to-near-stop) would be expected to shift the emissions direction — this is an open, testable follow-up rather than an assumed result. Don't treat GLOSA as an unconditional emissions win; measure it against the actual signal-timing context, the same way [[actuated-traffic-signals]] and [[surrogate-safety-measures]] both found that "the obviously better" intervention isn't universally better either.

See the `implement-glosa-speed-advisory-controller` skill for the full implementation and a bundled scenario-runner script.
