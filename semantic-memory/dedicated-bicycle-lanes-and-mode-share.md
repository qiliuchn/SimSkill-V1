---
summary: A dedicated bicycle lane (netconvert allow="bicycle"/disallow="bicycle" lane split) removes the car-delay penalty that rising bicycle mode share otherwise causes on a mixed shared lane, but the benefit is strongly asymmetric — verified directly, cars gain far more than bicycles do from the separation.
keywords:
  - bicycle
  - bike-lane
  - vClass
  - mode-share
  - lane-permissions
  - netconvert
created: 2026-07-31T00:15:00
last_updated: 2026-08-06T02:00:00
sources:
  - "[[episodic-memory/2026-07-31_00-04-29/outputs/FINDINGS.md]]"
  - "[[episodic-memory/2026-07-31_00-04-29/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[vehicle-class-lane-permissions]]"
  - "[[sumo-output-files]]"
  - "[[multimodal-signal-progression-and-the-bicycle-green-wave]]"
related_skills:
  - model-dedicated-bicycle-lane-infrastructure
  - model-vclass-lane-permissions
  - analyze-simulation-outputs
  - design-multimodal-signal-progression-for-bicycles-and-cars
related_skills_for_graph_view:
  - "[[model-dedicated-bicycle-lane-infrastructure]]"
  - "[[model-vclass-lane-permissions]]"
  - "[[analyze-simulation-outputs]]"
  - "[[design-multimodal-signal-progression-for-bicycles-and-cars]]"
---

# Dedicated Bicycle Lanes and Mode Share

Bicycles are a first-class SUMO vClass (`vClass="bicycle"`) with much lower `maxSpeed` than cars (typically ~5.5 m/s / 20 km/h vs. ~13.9 m/s / 50 km/h for a passenger car). On a single shared lane with no overtaking model active, a slow bicycle directly caps the speed of any car queued behind it — this makes bicycle mode share a first-order determinant of car performance on a mixed lane, and a dedicated bike lane (via lane-level `allow`/`disallow`, see [[vehicle-class-lane-permissions]]) a genuine engineering lever, not just a bicycle-comfort measure.

**Retroactive caveat** ([[multimodal-signal-progression-and-the-bicycle-green-wave]]): this page's findings are specifically about the dedicated lane's benefit *to cars* under the default lane model, verified independently there. The same default lane model, applied to bicycles' own delay *within* a single-file dedicated bike lane, produces a measurement artifact — bicycles cannot overtake a slower rider ahead of them and can measure as worse off than in mixed traffic — unless the sublane model is enabled. Any study of a dedicated bike lane's effect on bicycle-side (not just car-side) delay should enable `--lateral-resolution` and verify overtaking is occurring.

## Verified effect: rising bike share degrades mixed-lane car performance; a dedicated lane insulates it

On a real 2 km single-direction corridor (200 trips/level, bicycle share swept 5%/20%/40%, identical demand and random seed shared across both infrastructure variants at each level so only the network's lane permissions differed):

- **Mixed traffic** (one lane, `allow="passenger bicycle"`): car mean travel time rose monotonically with bike share — 319.9s → 397.2s → 411.1s (5%→20%→40%); car mean time loss rose 168.6s → 245.2s → 258.4s. Slower bicycles sharing the single no-overtake lane directly impeded following cars.
- **Dedicated bike lane** (bike-only lane `allow="bicycle"` + car-only lane `disallow="bicycle"`): car mean travel time stayed essentially flat regardless of bike share — 173.3s / 173.2s / 174.2s (time loss ~21s throughout).
- **Headline gap at 40% bike share**: 236.9s mean car travel time (2.36x) and 237.0s mean car time loss (~12x) between the two variants — confirmed by independently re-parsing all six raw `tripinfo_*.xml` files.

Route length was confirmed identical across variants at every level (~1995m cars, ~1998m bikes), ruling out a route-choice artifact — the entire gap is a genuine speed/delay effect from lane sharing, not a routing difference.

## Asymmetric benefit: this is mostly a car benefit, not a bicycle benefit

**Bicycles themselves gained only modestly from the dedicated lane** — about 0.6-1.5% faster travel time, not the large factor seen on the car side. The reason: in mixed traffic, the bicycle is the slow pace-setter that *sets* the shared lane's speed, so it is barely impeded by the cars queued behind it — there's little congestion penalty for the bike to be freed from. Removing cars from the bike's lane made almost no difference to the bike; removing bikes from the car's lane made a dramatic difference to cars. Any analysis of a proposed bike lane should report both modes' outcomes explicitly rather than assuming the benefit is shared or bicycle-centric.

## Practical takeaways

- Model the two infrastructure options as netconvert lane-permission variants of an otherwise identical network (see `model-vclass-lane-permissions` for the allow/disallow mechanism and its connection-regeneration gotcha).
- Sweep bicycle mode share, not just a single fixed split — the mixed-lane car penalty is a function of mode share, not a fixed constant, and only shows up as a clear monotonic trend across a sweep.
- Generate demand once per mode-share level and run it, with the identical seed, against both infrastructure variants — this isolates the infrastructure effect from any demand-generation randomness.
- Check per-vClass route length as well as travel time, to rule out a routing artifact before attributing a gap to congestion.
- Report both cars' and bicycles' outcomes — don't assume a "bike lane" finding is symmetric or bicycle-centric; in this verified case it was overwhelmingly a car-side benefit.

See the `model-dedicated-bicycle-lane-infrastructure` skill for the full build/sweep/analyze workflow and bundled scripts.
