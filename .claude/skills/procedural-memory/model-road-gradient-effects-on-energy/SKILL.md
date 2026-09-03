---
name: model-road-gradient-effects-on-energy
description: Use this skill when the user wants to model longitudinal road gradient/elevation in SUMO and quantify its effect on vehicle energy consumption or emissions — building plan-identical network variants that differ only in slope (via node/edge z-coordinates), and comparing HBEFA3 emissions (ICE) or EV battery energy (including regenerative braking) across grades. Covers plain-XML z-coordinate authoring, netconvert's default elevation-preservation behavior, verifying realized slope from the compiled net's own lane-shape data, and interpreting the qualitative ICE-vs-EV difference under downhill grade. Trigger on mentions of road gradient, grade, slope, elevation, hills, or regenerative braking energy recovery.
---

# Model Road Gradient Effects on Energy

Builds SUMO networks with longitudinal road gradient (elevation) and quantifies how grade drives vehicle energy consumption and emissions — the one geometric dimension every other network-creation skill in SimSkill ignores, despite feeding directly into SUMO's HBEFA3 emission model and EV battery/regenerative-braking model.

## Authoring elevation via node z-coordinates

Grade is set by giving nodes a `z` attribute in plain-XML `.nod.xml` — a constant grade along a corridor means each downstream node's `z` increases (or decreases) proportionally to its `x`-distance from the start:

```xml
<node id="A" x="0.0"   y="0.0" z="0.0"/>
<node id="B" x="400.0" y="0.0" z="16.0"/>   <!-- +4% grade: dz/dx = 16/400 = 0.04 -->
```

For a controlled comparison, build multiple variants that are **identical in plan (x/y)** and differ **only** in `z` — this isolates grade as the sole variable. `scripts/gen_gradient_corridor.py` automates generating a straight multi-edge corridor as several named grade variants from one command.

## netconvert preserves elevation by default — no special flag needed

`netconvert` keeps node/edge `z`-coordinates through compilation without any special option. **`--flatten` is the flag that strips elevation** (useful if you want to discard z-data, not to preserve it); `--osm.elevation` is specific to OSM import and irrelevant to plain-XML authoring. The compiled `.net.xml` has no dedicated "slope" attribute — elevation lives in each lane's `shape` attribute as `x,y,z` coordinate triples, and SUMO derives grade from consecutive shape points at runtime.

## Verify realized slope from the compiled net — never assume it

**Read the actual grade back from the compiled network rather than trusting the source `.nod.xml` propagated correctly.** Parse each edge's lane `shape` string, take the first and last `(x,y,z)` points, and compute `grade% = 100 * dz / horizontal_distance`:

```python
(x0, y0, z0), (x1, y1, z1) = shape_points[0], shape_points[-1]
horiz = ((x1-x0)**2 + (y1-y0)**2) ** 0.5
grade_pct = 100.0 * (z1 - z0) / horiz
```

`scripts/gen_gradient_corridor.py` does this automatically for every generated variant and prints the realized per-edge slope — confirm it matches the intended grade before trusting any downstream energy/emissions comparison. A shape point with only 2 coordinates (no `z` given) means flat (z=0) at that point, not a parsing error.

## Comparing ICE emissions and EV energy across grade

Run identical mixed demand (an ICE vType with an HBEFA3 `emissionClass`, an EV vType with a battery device and `recuperationEfficiency` set for regenerative braking) through each grade variant, with `tripinfo-output`, a `type="emissions"` edgeData file, and battery output enabled. `scripts/compare_grade_energy.py` extracts per-vehicle ICE CO2/fuel from `tripinfo`'s `<emissions>` child and EV net battery energy from `battery.xml` (`initial_charge - final actualBatteryCapacity`, cross-checked against `totalEnergyConsumed - totalEnergyRegenerated` for bookkeeping consistency), and reports a comparison table plus monotonicity/net-negative verification.

## The qualitative ICE-vs-EV difference under downhill grade

Both ICE and EV consumption/emissions scale monotonically with grade (downhill < flat < uphill) — but they differ qualitatively downhill. **An EV's net battery energy can go genuinely negative on a sufficiently steep, sufficiently long downhill grade** — regenerative braking recovers more energy than the vehicle consumed traversing the segment, so the battery ends fuller than it started. An ICE vehicle has no equivalent recovery mechanism; its downhill consumption is merely *lower*, never negative. Verify this distinction with real numbers (compare `totalEnergyConsumed` vs. `totalEnergyRegenerated` directly), not by assuming regen makes downhill "free" for an EV without checking whether it actually crosses zero for the specific grade/speed/vehicle combination being modeled.

## What a well-configured grade comparison shows

Measured on a 1.6km corridor at ±4% grade: per-vehicle ICE CO2 scaled from 174g (downhill) to 296g (flat) to 455g (uphill) — roughly 2.6x from downhill to uphill. EV energy consumption followed the same monotonic pattern, but EV *net* battery energy told a different story: genuinely negative downhill (the vehicle gained charge), positive and larger flat, and largest uphill — a qualitative EV-specific effect the ICE vehicle's emissions model cannot produce.

## Gotchas

- **A shape point with 2 coordinates instead of 3 means flat (z=0) at that point**, not malformed data — handle this when parsing lane shapes.
- **`--flatten` strips elevation; it is not required and should be omitted** when building a graded network — its presence would silently erase the very feature being modeled.
- **A blanket `device.battery.probability=1.0` (or similar) attaches a default-parameterized battery device to every vehicle, including non-EV ones** — filter any per-vehicle-class analysis by vType/id prefix explicitly, or scope the battery device to the EV vType only, to avoid ambiguous mixed results.

## Related

- `simulate-fleet-emissions` — the HBEFA3 emissionClass mechanics this skill's ICE-side comparison builds on.
- `simulate-ev-charging` — the EV battery device and energy-consumption model this skill's regenerative-braking analysis builds on.
- `model-vclass-lane-permissions`, `create-roundabout-network` — the hand-author-plain-XML-then-verify-from-the-compiled-net discipline this skill applies to elevation.
- [[road-gradient-and-energy-consumption]] — the underlying netconvert elevation-preservation mechanics, the verify-from-compiled-net method, and the verified ICE-vs-EV grade findings.
