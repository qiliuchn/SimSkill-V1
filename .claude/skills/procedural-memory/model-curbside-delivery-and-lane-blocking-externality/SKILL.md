---
name: model-curbside-delivery-and-lane-blocking-externality
description: Use this skill when the user wants to model a delivery/freight vehicle double-parking on a travel lane in SUMO (as opposed to off-street parkingArea parking) and measure the delay externality it imposes on general traffic, or wants to compare a double-parking scenario against a dedicated loading bay. Covers the lane-blocking <stop parking="false"/> mechanic, positively verifying a stop actually blocks a lane (rather than assuming it), constructing a geometrically-matched dedicated-bay alternative as a separate restricted lane, and computing a marginal externality rate (delay per unit curb-blockage time). Trigger on mentions of double-parking, curbside delivery, loading bay, lane-blocking stop, delivery vehicle externality, or freight/delivery disruption to traffic.
---

# Model Curbside Delivery and Lane-Blocking Externality

Models a delivery/freight vehicle physically blocking a travel lane while making a delivery, and measures the delay this imposes on general traffic — a fundamentally different SUMO mechanic from `model-parking-with-rerouting`'s off-street `parkingArea` occupancy, which never affects travel-lane capacity at all. This skill introduces the lane-blocking stop to memory, verified through direct raw-data confirmation rather than assumed to work as documented.

## The lane-blocking stop mechanic

```xml
<vehicle id="van0" type="delivery" ...>
    <route edges="..."/>
    <stop lane="ECURB_0" startPos="..." endPos="..." duration="120" parking="false"/>
</vehicle>
```

`parking="false"` (SUMO's default if omitted, but state it explicitly) keeps the vehicle occupying its travel lane at zero speed for the stop's `duration` — this is what makes it a genuine double-park, as opposed to `parking="true"`, which is the `model-parking-with-rerouting` off-street mechanic (the vehicle effectively leaves the lane's traffic stream).

## Verify the block genuinely happened — don't assume it

**A mis-specified stop can silently fail to block anything, and FCD output alone cannot distinguish a blocking stop from a non-blocking one.** Verify via at least two of these three independent channels:

1. **`stop-output`'s `parking` attribute** — the cheapest check: confirm it's written back as `"0"` (not `"1"`) for the vehicle's stop.
2. **`laneData`/`edgeData` occupancy on the specific lane** — a genuinely blocked lane shows the van's dwell time counted as occupied lane-seconds; a `parking="true"` (off-lane) stop does **not** appear in laneData at all, even though the vehicle still shows up in FCD.
3. **`--lanechange-output`, filtered to reason `strategic|urgent`** — this is SUMO's own machine-readable tag for "a vehicle was forced to change lanes because its current lane's continuation was blocked." A genuine lane-blocking stop should produce many `strategic|urgent` car lane changes off the blocked lane; a non-blocking (off-lane) stop should produce essentially zero.

**Gotcha: FCD shows a parked vehicle (`parking="true"`) at zero speed on its lane too** — FCD position/speed alone cannot tell a genuine travel-lane block from an off-lane parking stop, because SUMO still reports the vehicle's FCD position relative to its lane regardless of whether that lane's traffic is actually obstructed. Use `stop-output` and `laneData`/lane-change-reason, not FCD, as the discriminating instruments.

## Building a genuinely separate dedicated loading bay (not a parkingArea on a travel lane)

To model the "with loading bay" alternative as a real capacity-preserving intervention, add a genuinely **separate, restricted-vClass lane** (e.g. `allow="delivery"`) alongside the normal travel lanes, with a `<parkingArea>` on it — not a `parkingArea` placed on a shared travel lane. If the bay were placed on a shared lane, its geometry would look identical to a double-park scenario in FCD, defeating the comparison. Give the delivery vType an explicit `parking="true"` stop referencing the bay's `parkingArea` id (see `model-parking-with-rerouting`).

**Watch for a geometry confound this creates**: a wider junction (needed to add the extra bay lane) gets longer internal junction lanes from `netconvert`, which by itself adds a small, real amount of extra travel distance/time even with zero delivery activity — this is not the intervention's effect, it's incidental network geometry. Measure each variant's own zero-delivery baseline separately and compare every treatment effect against that variant's *own* baseline, not against the other variant's baseline, so this asymmetry doesn't contaminate the causal claim. Quantify the asymmetry explicitly (compare internal junction lane lengths between compiled variants) rather than assuming the two networks are perfectly equivalent.

## Verified finding: the externality rate is nonlinear and threshold-dependent

Sweeping background traffic volume against a fixed delivery-stop rate, the marginal externality (extra car delay per unit of curb-blockage time) was **near-negligible and roughly linear at low-to-moderate demand**, then **exploded by a large step multiplier** (verified case: ~21x) once demand crossed the network's *blocked-state* capacity — i.e. the reduced capacity available when one lane is periodically occupied by a stopped vehicle, not the network's nominal unblocked capacity. This distinction matters for prediction: the relevant threshold to watch is the effective capacity under blockage, not the free-flow or unblocked capacity figure.

## Verified finding: stop frequency has a real but small independent effect, distinct from occupancy time

At **equal total curb-occupancy time** (same total vehicle-hours of blockage per hour), many short stops produced measurably more car delay than few long stops at low-to-moderate demand (a small but statistically real effect, driven by more frequent forced-merge events, not more total blocked time) — but this effect became statistically indistinguishable from noise (and even direction-ambiguous) right at the demand level where the network approaches its blocked-state capacity threshold. **The forced-lane-change-count mechanistic explanation stops being reliable exactly where it matters most**: past saturation, a lower lane-change count reflects fewer available gaps to merge into, not less disruption — the same raw metric flips from measuring "how much forced merging happened" to "how much merging was even possible." Don't trust a lane-change-count proxy's direction once a scenario is genuinely oversaturated.

## Verified finding: a dedicated loading bay substantially reduces but does not eliminate the externality

A geometrically-separate loading bay removed the large majority of the double-parking externality (verified case: 54-99%, with the removed fraction *increasing* as background demand approached the blocked-state capacity threshold, since that's exactly where the double-parking externality itself was largest). **A small, statistically robust residual remained even for genuinely off-lane deliveries** — traced directly to the mechanistic cause: every van's pull-out maneuver from the bay back into travel-lane traffic is itself a forced (`strategic|urgent`-tagged) merge event. This residual scaled with the **number** of pull-out events, not with total dwell time — many short bay visits left a small but real residual at every volume tested, while few long bay visits' residual was statistically indistinguishable from zero. A loading bay is a large improvement, not a complete fix, and the remaining cost is specifically a merge-frequency cost, not an occupancy-time cost.

## Gotchas

- **FCD alone cannot distinguish a genuine lane-blocking stop from an off-lane parking stop** — both show the vehicle at zero speed "on" a lane in FCD; use `stop-output`'s `parking` attribute, `laneData` occupancy, and `strategic|urgent` lane-change counts as the real discriminators.
- **A dedicated loading bay's `parkingArea` must be on a genuinely separate, restricted lane**, not placed on a shared travel lane, or it becomes geometrically indistinguishable from the double-parking scenario it's meant to contrast against.
- **A wider junction built to add a bay lane gets longer internal junction lanes**, adding a small real delay even with zero delivery activity — measure and disclose this asymmetry rather than assuming perfect network equivalence between variants, and compare every effect against each variant's own zero-delivery control.
- **The threshold that matters for the externality explosion is the blocked-state (reduced) capacity, not the network's nominal free capacity.**
- **A lane-change-count-based mechanistic proxy inverts past saturation** — fewer lane changes past the demand knee can mean *less merge opportunity*, not less disruption.
- **A short two-lane street may never produce a teleport from a lane-blocking stop** (there's always an escape lane) — on a genuinely single-lane link, a `parking="false"` stop is a realistic candidate to trigger SUMO's stuck-vehicle teleport mechanism, which would need separate handling.

## Related

- `model-parking-with-rerouting` — the off-street `parkingArea` mechanic this skill's dedicated-bay alternative is built on; that skill's vehicles never affect travel-lane capacity, which is exactly the contrast this skill studies.
- `quantify-sumo-run-to-run-variability` — the replication/Common-Random-Numbers methodology this skill's externality-rate measurement applies; a genuine, real-world confirmation that CRN helps for well-correlated metrics but can stop helping at the most saturated cells.
- `analyze-simulation-outputs` — general tripinfo/summary/edgeData conventions this skill's delay-comparison analysis follows.
- [[curbside-delivery-blocking-externality]] — the verified nonlinear-threshold externality finding, the frequency-vs-occupancy result, and the loading-bay residual finding.
- `design-bus-stop-placement-type-and-spacing` — transfers this skill's lane-blocking verification protocol (stop-output, laneData, forced lane changes) to `<busStop parking="true">`, and finds a sign-reversed version of this skill's frequency-vs-occupancy result on a single lane with no escape (few long dwells cost more than many short ones there, the opposite of this skill's multi-lane finding).
- `model-cruising-for-parking-search-externality` — reuses this skill's standing-vehicle-seconds instrument to isolate the parking **maneuver's** own lane-blocking cost (via `--parking.maneuver`) as distinct from parking-search delay, finding the maneuver's per-event cost scales with the congestion of the specific block face blocked rather than with total curb parking share.
- `model-urban-freight-delivery-tours` — reuses this skill's lane-blocking verification protocol for freight loading-bay double-parking, and finds this skill's convex bay-deficit externality shape does **not** transfer to a single-lane residential street (no escape lane means a double-park is already a complete blockage from the first deficit unit, giving a linear rather than convex delay curve).
