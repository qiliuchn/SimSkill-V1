---
summary: SUMO's sublane model, activated via --lateral-resolution, lets narrow vehicles like motorcycles adopt continuous sub-lane lateral positions to filter past queued traffic; genuine filtering is verified via FCD posLat (exactly zero under the default lane model, continuously nonzero under sublane) plus a net-overtake-rate check, and was found to substantially benefit motorcycles with no cost to cars.
keywords:
  - sublane-model
  - lateral-resolution
  - lane-filtering
  - posLat
  - motorcycle-modeling
  - minGapLat
  - maxSpeedLat
created: 2026-07-25T15:10:00
last_updated: 2026-08-06T02:00:00
sources:
  - "[[episodic-memory/2026-07-25_14-45-58/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-25_14-45-58/attempts/attempt-1/critic-agent-feedback.json]]"
  - https://sumo.dlr.de/docs/Simulation/SublaneModel.html
related_pages:
  - "[[vehicle-class-lane-permissions]]"
  - "[[sumo-output-files]]"
  - "[[actuated-traffic-signals]]"
  - "[[multimodal-signal-progression-and-the-bicycle-green-wave]]"
related_skills:
  - simulate-motorcycle-lane-filtering-with-sublane-model
  - model-vclass-lane-permissions
  - create-single-intersection
  - visualize-trajectories-and-timeseries
  - design-multimodal-signal-progression-for-bicycles-and-cars
related_skills_for_graph_view:
  - "[[simulate-motorcycle-lane-filtering-with-sublane-model]]"
  - "[[model-vclass-lane-permissions]]"
  - "[[create-single-intersection]]"
  - "[[visualize-trajectories-and-timeseries]]"
  - "[[design-multimodal-signal-progression-for-bicycles-and-cars]]"
---

# Sublane Model and Lane Filtering

SUMO's default microscopic model gives every vehicle a fixed, effectively binary position within its lane — no partial lateral offset is representable. The **sublane model**, activated via `--lateral-resolution <meters>`, replaces this with continuous lateral positioning, enabling narrow vehicles (motorcycles, mopeds) to occupy sub-lane positions and filter past wider, queued, or slower traffic within the same lane — a behavior pattern common in real-world mixed motorized traffic that the default model cannot represent at all.

## Activation is required for lateral parameters to matter

`--lateral-resolution` is the single switch between the two models. **Without it, all lateral vType parameters (`latAlignment`, `minGapLat`, `maxSpeedLat`, and the `lc*` lateral-eagerness parameters) have no effect** — a vType configured for aggressive filtering still behaves like any ordinary vehicle under the default model, queuing behind traffic rather than moving laterally. A baseline-vs-sublane comparison should differ in exactly this one setting; verify with a direct diff of the two run configurations that nothing else changed.

## Lateral vType parameters

```xml
<vType id="moto" vClass="motorcycle" length="2.2" width="0.8"
       minGapLat="0.12" maxSpeedLat="2.5" latAlignment="center"
       lcSublane="3.0" lcPushy="1" lcImpatience="1" lcAccelLat="2.0" lcKeepRight="0" lcSpeedGain="5.0"/>
```

`width` narrow relative to the lane width is what physically permits filtering at all — a full-lane-width vehicle (an ordinary car) can't share a lane laterally regardless of other settings, and needs no special lateral configuration. `minGapLat` (minimum lateral gap to a neighbor) and `maxSpeedLat` (maximum sideways speed) directly govern how tightly and how quickly a vehicle can squeeze past. The SL2015 lane-change model's `lc*` parameters (`lcSublane`, `lcPushy`, `lcImpatience`, `lcAccelLat`, `lcKeepRight`, `lcSpeedGain`) tune lateral-gap-seeking eagerness — set these more aggressive for a class meant to actively filter.

## posLat: the genuine-filtering discriminator

FCD output's `posLat` attribute (lateral offset from lane center, in meters) is the clean, unambiguous signal for whether sublane behavior is actually occurring, rather than assuming it from configuration or aggregate travel-time changes alone:

- **Default lane model: `posLat` is exactly `0.000` in every single frame**, for every vehicle — there is no partial lateral state to represent.
- **Sublane model, genuinely filtering vehicle: continuous, nonzero `posLat`** as it maneuvers within and across the lane, verifiable directly from FCD.

This zero-vs-nonzero contrast should be checked directly from raw FCD data before claiming filtering occurred — an aggregate metric improvement alone doesn't distinguish genuine lateral filtering from some other confound.

## Net-overtake verification, and a caveat about the baseline

Counting how many vehicles a filtering-class vehicle passes on a queuing approach (vehicles ahead of it on entry, behind it on exit) is a second, independent verification signal. **A nonzero overtake count in the default-model baseline is expected, not evidence the comparison is broken** — ordinary lane-change overtaking still happens as a queue discharges even without the sublane model. The decisive signature distinguishing genuine sublane filtering is the *combination* of nonzero `posLat` with a substantially higher overtake *rate* under sublane, not the mere presence of overtaking in either run.

## Measured finding

On a 3-lane signalized approach with a standing red-phase queue and mixed 80/20 car/motorcycle demand: enabling the sublane model (`--lateral-resolution 0.8`) let motorcycles take continuous lateral positions up to ~1.75m off lane center and overtake roughly 5.6x more vehicles on average than the default model's occasional lane-change overtaking. This produced a substantial motorcycle benefit — mean waiting time -30.6%, travel time -10.5%, time loss -34.2% — with **no cost to cars**, whose metrics were unaffected or slightly improved (a filtered-forward motorcycle vacates queue space rather than continuing to occupy a full lane slot, marginally helping the cars behind it too).

## Gotcha

`fcd-output.attributes` in a `.sumocfg` must be **comma-separated**, not space-separated — an incorrectly-delimited attribute list is misparsed as a single unrecognized attribute value rather than a list.

See the `simulate-motorcycle-lane-filtering-with-sublane-model` skill for the full build/run/verify workflow and bundled verification script.
