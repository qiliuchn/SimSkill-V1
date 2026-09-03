---
summary: SUMO's opposite-direction driving (lcOpposite) requires netconvert --opposites.guess and antiparallel single-lane geometry (verified via reciprocal <neigh> elements in the compiled net); pairing lcOpposite with elevated lcAssertive/lcPushy/lcImpatience produces genuine SUMO-detected head-on <collision> events rather than safe overtaking, while conservative defaults let LC2013 genuinely refuse unsafe passes — verified to preserve monotonically-declining overtake counts and monotonically-rising delay as oncoming volume increases, with zero real collisions at the original 2km/~130-vehicle scale and a bounded SSM near-miss signal. Correction: at much larger exposure (16km, 3.29M vehicle-km), the SAME conservative tuning produced 6 genuine frontal collisions (1.82 per million vehicle-km) — see [[two-lane-highway-follower-density-and-passing-lane-effectiveness]]. It is low-collision, not collision-free; "zero collisions" at small scale is an exposure result, not a property of the parameters.
keywords:
  - opposite-direction-driving
  - lcOpposite
  - overtaking
  - oncoming-lane
  - lane-change-aggressiveness
created: 2026-07-28T20:35:00
last_updated: 2026-08-05T21:00:00
sources:
  - "[[episodic-memory/2026-07-28_20-07-12/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-28_20-07-12/attempts/attempt-1/critic-agent-feedback.json]]"
  - "[[episodic-memory/2026-07-28_20-07-12/attempts/attempt-2/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-28_20-07-12/attempts/attempt-2/critic-agent-feedback.json]]"
related_pages:
  - "[[surrogate-safety-measures]]"
  - "[[weather-friction-effects-on-capacity-and-safety]]"
  - "[[two-lane-highway-follower-density-and-passing-lane-effectiveness]]"
  - "[[one-lane-two-way-alternating-flow-and-shared-lane-representation]]"
related_skills:
  - model-opposite-direction-overtaking
  - analyze-intersection-safety-with-ssm
  - control-one-lane-two-way-alternating-flow-through-a-work-zone
related_skills_for_graph_view:
  - "[[model-opposite-direction-overtaking]]"
  - "[[analyze-intersection-safety-with-ssm]]"
  - "[[control-one-lane-two-way-alternating-flow-through-a-work-zone]]"
---

# Opposite-Direction Overtaking Mechanics

SUMO's opposite-direction driving mechanism lets a vehicle temporarily use the oncoming-direction lane to pass a slower leader on a two-way, single-lane-per-direction road — governed by the `lcOpposite` lane-change parameter, but requiring specific network preparation to be usable at all.

## Network enablement requires an explicit netconvert flag

**`netconvert --opposites.guess true` (off by default) is required** to make two opposing single-lane edges (sharing the same node pairs, reversed) usable for opposite-direction overtaking. Verified directly: the compiled network's lane elements carry reciprocal `<neigh lane="..."/>` markers (lane A pointing at lane B and vice versa) only when this flag was passed, with antiparallel lane-shape geometry (offset by roughly one lane width) confirming the pairing. Without this flag, or without the reversed-edge geometry, no such `<neigh>` marker appears and opposite-direction overtaking is silently unavailable — always verify the compiled net directly rather than assuming the source XML alone is sufficient.

## Critical finding: `lcOpposite` + aggressive lane-change tuning produces genuine collisions, not just risky-looking overtakes

**Pairing `lcOpposite` (enabling opposite-lane overtaking willingness) with elevated `lcAssertive`/`lcPushy`/`lcImpatience` values can cause SUMO's LC2013 lane-change model to commit vehicles to oncoming-lane passes they cannot safely complete, producing genuine SUMO-detected `<collision type="frontal">` events** — real vehicle-overlap crashes, not near-misses, independently corroborated by explicit engine warnings (e.g. "frontal collision ... gap=-6.58") in the console log. Verified directly: a scenario using `lcAssertive=1.5, lcPushy=0.5, lcImpatience=0.6` alongside `lcOpposite=2.0` produced 10-17 real head-on crashes per ~130-vehicle run — a genuinely broken parameterization, not a valid representation of overtaking risk.

**The fix: use SUMO's more conservative defaults for lane-change aggressiveness (`lcAssertive=1.0, lcPushy=0.0, lcImpatience=0.0`) alongside a normal `lcOpposite` willingness (~1.0).** This lets LC2013's own gap-acceptance logic genuinely refuse a pass when the oncoming gap is unsafe, rather than executing it anyway. Verified: this retuning eliminated all collisions (zero `<collision>` elements across an identical sweep) while *preserving* the core behavioral signal — overtakes still occurred and still declined monotonically as oncoming volume rose, and fast-car delay still rose monotonically in step.

**Always keep collision detection fully active while validating a new overtaking scenario** (`--collision-output`, `--collision.action warn`, `--collision.mingap-factor 0`) — checking the resulting `<collision>` elements (or their absence) is the only reliable way to distinguish a genuinely safe overtaking model from a broken one that merely looks plausible until scrutinized. A model producing real collisions under its own gap-acceptance logic is not modeling realistic driver behavior, however plausible the resulting overtake/delay trends look in isolation.

## Verified behavioral trends (with conservative, low-collision tuning)

On a real 2km two-way rural corridor: completed overtakes fell strictly monotonically as oncoming flow rose (0→200→400→800 veh/h), and fast-car mean travel time and total time loss rose strictly monotonically in step — cars are increasingly trapped behind a slow leader as safe oncoming gaps become scarcer. SSM near-miss safety exposure (encounter type 20, oncoming/head-on) appeared only at the higher oncoming-volume levels and remained bounded (minimum TTC around 1.5-1.7 seconds) — a real, quantifiable risk signal, but genuinely distinct from and far less alarming than the literal collisions an overly aggressive parameterization would otherwise produce.

**Correction — "collision-free" does not scale.** At this scenario's exposure (~130 vehicles on 2km) zero real `<collision>` elements occurred. A follow-up study running the identical conservative parameterization (`lcOpposite=1.0`, default `lcAssertive`/`lcPushy`/`lcImpatience`) on a 16km corridor with far more vehicles (3.29M vehicle-km total exposure) found 6 genuine frontal collisions, all on opposing-direction lanes (1.82 per million vehicle-km) — see [[two-lane-highway-follower-density-and-passing-lane-effectiveness]]. Collision detection was left fully active in both studies. The correct claim is that this tuning is **low-collision, not collision-free**; a zero-collision result at small exposure should not be generalized to larger scenarios without re-checking `--collision-output`.

See the `model-opposite-direction-overtaking` skill for the full network, vType, and safe-tuning workflow.
