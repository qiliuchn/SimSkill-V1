---
name: model-opposite-direction-overtaking
description: Use this skill when the user wants to model overtaking via the oncoming lane on a two-way undivided road in SUMO — a car passing a slow leader by temporarily using the opposing-direction lane, as opposed to a same-direction passing lane or a multi-lane freeway. Covers the netconvert --opposites.guess requirement and antiparallel lane geometry needed to enable SUMO's native opposite-direction driving mechanism, the lcOpposite lane-change parameter, and — critically — the lane-change aggressiveness (lcAssertive/lcPushy/lcImpatience) tuning required to model overtaking as genuinely safe behavior rather than one that produces literal SUMO-detected head-on collisions. Trigger on mentions of opposite-direction driving, oncoming lane overtaking, passing on a two-lane road, rural road overtaking, or lcOpposite.
related_skills:
  - analyze-intersection-safety-with-ssm
  - model-adverse-weather-effects-on-freeway-traffic
related_skills_for_graph_view:
  - "[[analyze-intersection-safety-with-ssm]]"
  - "[[model-adverse-weather-effects-on-freeway-traffic]]"
related_pages:
  - "[[opposite-direction-overtaking-mechanics]]"
---

# Model Opposite-Direction Overtaking

Models a car overtaking a slow leader by temporarily using the oncoming lane on a two-way, undivided, single-lane-per-direction road — SUMO's native opposite-direction driving mechanism (`Simulation/OppositeDirectionDriving`), distinct from a same-direction passing lane or multi-lane freeway scenarios.

## Network: explicit netconvert flag plus antiparallel geometry required

**SUMO's opposite-direction driving requires `netconvert --opposites.guess true`** (off by default) applied to a network where the two opposing single-lane edges share the same node pairs in reverse, with default right-spread geometry placing them side-by-side and antiparallel:

```bash
netconvert -n rural.nod.xml -e rural.edg.xml -o rural.net.xml --opposites.guess true
```

```xml
<!-- primary direction: W -> A -> B -> E -->
<edge id="W_A" from="W" to="A" numLanes="1" speed="27.78"/>
<!-- opposing direction, SAME node pairs reversed -->
<edge id="A_W" from="A" to="W" numLanes="1" speed="27.78"/>
```

Verify the compiled `.net.xml` directly: each opposing lane should carry a reciprocal `<neigh lane="..."/>` element pointing at the other (e.g. lane `A_B_0` has `<neigh lane="B_A_0"/>` and vice versa), and their lane shapes should show them antiparallel and offset by roughly a lane-width (e.g. y=-1.60/y=+1.60) — this reciprocal marker is what makes the oncoming lane usable for overtaking. Don't assume the flag alone is sufficient; check the compiled output.

## Enabling overtaking: `lcOpposite`, but tune aggressiveness conservatively

`lcOpposite` on the overtaking vType's lane-change parameters enables willingness to use the opposing lane (0 = never; SUMO's default ~1.0 = normal willingness). **Critical: do not pair `lcOpposite` with elevated `lcAssertive`/`lcPushy`/`lcImpatience` values** — an aggressive combination lets SUMO's LC2013 model commit to an oncoming-lane pass it cannot safely complete, producing genuine SUMO-detected `<collision type="frontal">` events (verified: 10-17 real crashes per ~130-vehicle run with `lcAssertive=1.5, lcPushy=0.5, lcImpatience=0.6`). **Use SUMO's conservative defaults for these three parameters (`lcAssertive=1.0, lcPushy=0.0, lcImpatience=0.0`) alongside `lcOpposite=1.0`** — this lets LC2013's own gap-acceptance logic genuinely *refuse* an unsafe pass rather than execute one into a crash, while still producing real overtakes whenever the oncoming lane is genuinely clear enough (verified: zero collisions across an identical sweep at ~130-vehicle exposure, with overtake counts and delay trends preserved). **This is low-collision, not collision-free — it does not scale.** The identical tuning applied to a 16km corridor at much larger exposure (3.29M vehicle-km) produced 6 genuine frontal collisions (1.82 per million vehicle-km); re-check `--collision-output` at your own scenario's actual scale rather than trusting a zero-collision result carried over from a smaller one (see `evaluate-two-lane-highway-with-hcm-and-passing-lanes`).

```xml
<vType id="car" ... laneChangeModel="LC2013"
       lcOpposite="1.0" lcAssertive="1.0" lcPushy="0.0" lcImpatience="0.0">
```

**Always keep collision detection fully active while validating a new scenario** (`--collision-output`, `--collision.action warn`, `--collision.mingap-factor 0`) and check the output file for genuine `<collision>` elements — don't weaken detection settings to make a problem disappear from the log; fix the underlying lane-change tuning instead.

## Demand design and the sweep

Author a primary-direction demand with a slow leader (e.g. a truck vType capped at ~60 km/h, `lcOpposite="0"` so it never overtakes) followed by faster cars (desired ~100 km/h, `lcOpposite="1.0"`). In the opposing direction, author a uniform flow at the swept variable — the oncoming-flow rate. Hold the primary demand file and seed identical across every sweep level; only the opposing-flow file/rate should differ.

## Detecting genuine overtakes from FCD

Positively confirm overtaking used the oncoming lane by scanning FCD for a primary-direction vehicle occupying an opposing-direction lane ID at the same time as an opposing-direction vehicle is present there — see `scripts/count_passes.py`. Don't infer overtakes from timing alone; confirm the actual lane occupancy.

## Verified findings

On a real corridor with conservatively-tuned (low-collision) lane-change parameters: completed overtakes fell strictly monotonically as oncoming volume rose across a 0→800 veh/h sweep, while fast-car mean travel time and total time loss rose strictly monotonically in step — cars are increasingly trapped behind the slow leader as safe oncoming gaps become scarcer. SSM near-miss safety exposure (encounter type 20 = oncoming/head-on) appeared only at higher oncoming volumes and remained bounded (minimum TTC around 1.5-1.7s), a real but modest risk signal genuinely distinct from — and far less alarming than — the literal crashes an overly aggressive parameterization would otherwise produce.

## Gotchas

- **`netconvert --opposites.guess true` is required and off by default** — verify reciprocal `<neigh>` elements in the compiled net rather than assuming the flag alone worked.
- **Elevated `lcAssertive`/`lcPushy`/`lcImpatience` alongside `lcOpposite` can produce genuine SUMO collisions**, not just risky-looking near-misses — always check `--collision-output` for real `<collision>` elements when validating a new overtaking scenario, and retune toward conservative defaults if any appear.
- **Keep collision detection active during validation** — don't loosen `--collision.mingap-factor` or disable `--collision-output` to make a problem invisible; fix the vType parameters instead.
- **A truly conservative driver population can eliminate overtaking almost entirely, not just collisions** — if this happens, report it as a legitimate finding rather than re-introducing aggressive parameters just to preserve overtake counts.

## Related

- `analyze-intersection-safety-with-ssm` — the SSM device configuration and TTC/conflict interpretation this skill's safety analysis reuses (note encounter type 20 = oncoming/head-on for this scenario's straight-corridor geometry).
- `model-adverse-weather-effects-on-freeway-traffic` — a similar sweep-plus-SSM-safety methodology, useful structural reference.
- [[opposite-direction-overtaking-mechanics]] — the underlying network-enablement and collision-vs-safe-tuning mechanics, and the verified monotonic trends.
