---
name: simulate-motorcycle-lane-filtering-with-sublane-model
description: Use this skill when the user wants to model lane-filtering or within-lane overtaking in SUMO — motorcycles or other narrow vehicles moving to sub-lane lateral positions to pass queued/slower traffic — using SUMO's sublane model (--lateral-resolution). Covers activating the sublane model, the lateral vType parameters (width, minGapLat, maxSpeedLat, latAlignment, lc* eagerness parameters), interpreting sublane FCD output (posLat), and verifying genuine filtering behavior against a default-lane-model baseline rather than assuming it from configuration alone. Trigger on mentions of sublane model, lateral-resolution, lane filtering, motorcycle filtering, or posLat.
related_skills:
  - model-vclass-lane-permissions
  - create-single-intersection
  - control-signals-with-actuated-tls
  - analyze-simulation-outputs
  - visualize-trajectories-and-timeseries
related_skills_for_graph_view:
  - "[[model-vclass-lane-permissions]]"
  - "[[create-single-intersection]]"
  - "[[control-signals-with-actuated-tls]]"
  - "[[analyze-simulation-outputs]]"
  - "[[visualize-trajectories-and-timeseries]]"
related_pages:
  - "[[sublane-model-and-lane-filtering]]"
---

# Simulate Motorcycle Lane Filtering with the Sublane Model

Models lane-filtering — narrow vehicles (motorcycles, mopeds) adopting continuous sub-lane lateral positions to overtake queued or slower traffic within a lane rather than only changing lanes discretely — using SUMO's sublane model. This is SimSkill's only skill covering the lateral/sublane dimension of SUMO's microscopic behavioral model itself; every other vehicle-behavior skill treats lane position as a discrete, one-vehicle-per-lane assignment.

## Activating the sublane model

```bash
sumo -n net.xml -r routes.rou.xml --lateral-resolution 0.8 --tripinfo-output tripinfo.xml --fcd-output fcd.xml
```

`--lateral-resolution` (meters) is the single flag that switches SUMO from its default lane model (vehicles occupy a fixed position within their lane, position is effectively binary per lane) to the continuous sublane model. **Without this flag, `latAlignment`/`minGapLat`/`maxSpeedLat` and similar lateral vType parameters have no effect** — a vType configured for filtering will still just queue behind traffic like any other vehicle if the simulation itself isn't run with `--lateral-resolution` set. A baseline-vs-sublane comparison should therefore differ in exactly this one flag (or config line) and nothing else — verify this with a direct diff of the two run configurations before trusting a comparison.

## vType lateral parameters

```xml
<vType id="moto" vClass="motorcycle" length="2.2" width="0.8"
       minGapLat="0.12" maxSpeedLat="2.5" latAlignment="center"
       lcSublane="3.0" lcPushy="1" lcImpatience="1" lcAccelLat="2.0" lcKeepRight="0" lcSpeedGain="5.0"/>
```

- **`width`** — vehicle body width; a narrow width relative to the lane width is what physically permits filtering (a full-lane-width car has no room to share a lane laterally regardless of other parameters).
- **`minGapLat`** — minimum lateral gap kept from a neighboring vehicle; small for a filtering-capable class so it can squeeze alongside wider traffic.
- **`maxSpeedLat`** — maximum lateral movement speed; higher lets a vehicle reposition sideways quickly to find a gap.
- **`latAlignment`** — preferred lateral position within the lane (`center`, `right`, `left`, `arbitrary`, or a specific offset).
- **`lc*` (SL2015 lane-change model) parameters** — `lcSublane`, `lcPushy`, `lcImpatience`, `lcAccelLat`, `lcKeepRight`, `lcSpeedGain` tune how aggressively a vehicle seeks lateral gaps; set these more eager for a class meant to actively filter past stopped/slow traffic.

A full-lane-width class (e.g. ordinary cars) needs no special lateral configuration — its `width` alone prevents it from sharing a lane laterally even under the sublane model.

## Verifying genuine filtering (don't trust configuration alone)

**A sublane-configured run producing different tripinfo numbers than a baseline is not proof of genuine physical filtering** — it could reflect an unrelated confound. Verify directly from FCD output using `posLat` (the vehicle's lateral offset from lane center, in meters):

- **Under the default lane model, `posLat` is exactly `0.000` in every single frame** — vehicles only ever occupy discrete lane-center positions, with no partial/lateral offset representable at all.
- **Under the sublane model, a genuinely filtering vehicle shows continuous, nonzero `posLat`** values as it maneuvers within and across the lane.

This zero-vs-nonzero contrast is a clean, unambiguous discriminator — check it directly rather than inferring filtering from aggregate travel-time improvements alone. Additionally, count **net overtakes** on the queuing approach: for each filtering-class vehicle, count how many other vehicles were ahead of it when it entered the approach and behind it when it exited — `scripts/verify_sublane_filtering.py` automates both checks:

```bash
python scripts/verify_sublane_filtering.py \
    --baseline-tripinfo outputs/baseline/tripinfo.xml --baseline-fcd outputs/baseline/fcd.xml \
    --sublane-tripinfo outputs/sublane/tripinfo.xml --sublane-fcd outputs/sublane/fcd.xml \
    --filtering-vtype-prefix moto_ --other-vtype-prefix car_ --approach-lane-prefix WC_ \
    --out-csv comparison_table.csv --out-json filtering_summary.json
```

**Note that ordinary lane-change overtaking still occurs in the default (non-sublane) model** as a queue discharges — a nonzero baseline overtake count is expected and not itself evidence against the sublane model working. The decisive signature is the *combination* of `posLat` (zero vs. nonzero) and a substantially higher overtake *rate* under sublane, not overtaking's mere presence in either run.

## What a well-configured filtering scenario shows

Measured on a 3-lane signalized approach with a standing red-phase queue, mixed 80/20 car/motorcycle demand: enabling the sublane model let motorcycles take continuous lateral positions (up to ~1.75m off lane center) and overtake ~5.6x more vehicles on average than the default model's occasional lane-change overtaking. This translated into a substantial motorcycle benefit (mean waiting time -30.6%, travel time -10.5%, timeLoss -34.2%) with **no cost to cars** — car metrics were unaffected or slightly improved, since a filtered-forward motorcycle vacates queue space rather than occupying a full lane slot.

## Gotchas

- **`--lateral-resolution` must actually be set for lateral vType parameters to take effect at all** — a filtering-configured vType under the default lane model behaves like any other vehicle.
- **`fcd-output.attributes` must be comma-separated in a `.sumocfg` value**, not space-separated — an incorrectly-delimited attribute list errors as an unrecognized single attribute.
- **`posLat` is the clean discriminator for genuine sublane behavior** — exactly zero under the default model, continuously nonzero under sublane; don't rely on aggregate travel-time differences alone to claim filtering occurred.
- **A nonzero baseline overtake count is expected, not a sign of a broken comparison** — ordinary lane-change overtaking exists in the default model too; compare the overtake *rate*, not its mere presence.

## Related

- `model-vclass-lane-permissions` — SimSkill's other vClass-differentiated skill (static allow/disallow lane restrictions), contrasted with this skill's dynamic within-lane lateral positioning.
- `create-single-intersection`, `control-signals-with-actuated-tls` — for building the queuing approach this scenario needs.
- `analyze-simulation-outputs`, `visualize-trajectories-and-timeseries` — general analysis/plotting skills this one specializes for lateral-position and overtake-count verification.
- [[sublane-model-and-lane-filtering]] — the underlying SUMO sublane mechanics, `posLat` interpretation, and the verified motorcycle-benefit-without-car-cost finding.
