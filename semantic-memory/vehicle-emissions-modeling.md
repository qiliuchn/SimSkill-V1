---
summary: SUMO models per-vehicle pollutant emissions (CO2, NOx, PMx, fuel, etc.) via the HBEFA3 emissionClass attribute on vTypes, with per-vehicle totals available in tripinfo and aggregated per-edge totals via a type="emissions" edgeData file.
keywords:
  - emissions
  - HBEFA3
  - vTypeDistribution
  - emissionClass
  - CO2
  - NOx
  - PMx
  - fuel-consumption
created: 2026-07-23T15:16:02
last_updated: 2026-08-06T04:00:00
sources:
  - "[[episodic-memory/2026-07-23_15-20-03/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-23_15-20-03/attempts/attempt-1/critic-agent-feedback.json]]"
  - https://sumo.dlr.de/docs/Models/Emissions.html
  - https://sumo.dlr.de/docs/Models/Emissions/HBEFA3-based.html
related_pages:
  - "[[sumo-output-files]]"
  - "[[random-trips]]"
  - "[[electric-vehicle-battery-and-charging]]"
  - "[[glosa-eco-driving]]"
  - "[[road-gradient-and-energy-consumption]]"
  - "[[harmonoise-traffic-noise-modeling]]"
  - "[[effort-based-routing-and-eco-routing]]"
  - "[[intersection-air-quality-hot-spot-analysis]]"
related_skills:
  - simulate-fleet-emissions
  - create-grid-network
  - generate-random-trips
  - run-simulation
  - simulate-ev-charging
  - implement-glosa-speed-advisory-controller
  - analyze-intersection-air-quality-hot-spots-from-microsimulation
related_skills_for_graph_view:
  - "[[simulate-fleet-emissions]]"
  - "[[create-grid-network]]"
  - "[[generate-random-trips]]"
  - "[[run-simulation]]"
  - "[[simulate-ev-charging]]"
  - "[[implement-glosa-speed-advisory-controller]]"
  - "[[analyze-intersection-air-quality-hot-spots-from-microsimulation]]"
---

# Vehicle Emissions Modeling (HBEFA3)

SUMO estimates per-vehicle pollutant emissions (CO2, CO, HC, NOx, PMx) and fuel/electricity consumption using the **HBEFA3** emission model, driven entirely by the `emissionClass` attribute on a vehicle's `vType`. Emission rates depend on both the vehicle's class/fuel/emission-standard and its instantaneous speed/acceleration, so identical trips produce different totals depending on which `vType` a vehicle was assigned and how it actually drove (stop-go at signals raises emissions relative to free-flow).

## Emission classes and vType attributes

`emissionClass` uses the format `HBEFA3/<vehicle-category>_<fuel>_<standard>`, e.g.:
- `HBEFA3/PC_G_EU4` — passenger car, gasoline, Euro 4
- `HBEFA3/PC_G_EU2` — passenger car, gasoline, Euro 2 (older, higher-emitting)
- `HBEFA3/LDV_D_EU4` — light-delivery van, diesel, Euro 4
- `HBEFA3/HDV` — heavy-duty vehicle (aggregate class)

Full list: fetch https://sumo.dlr.de/docs/Models/Emissions/HBEFA3-based.html rather than guessing a code — an invalid `emissionClass` string makes `sumo` fail at startup. `emissionClass` is independent of `vClass` (`passenger`/`delivery`/`truck`/etc., which governs edge/lane permissions) — both need to be set explicitly; setting one doesn't imply anything about the other.

**HBEFA4 classes also exist and were verified working against SUMO 1.27.1** ([[intersection-air-quality-hot-spot-analysis]]) using the format `HBEFA4/<category>_<fuel>_<standard>` (e.g. `HBEFA4/PC_petrol_Euro-6d`, `HBEFA4/RT_gt14-20t_Euro-VI_A-C`) — a more granular, currently-maintained successor to the HBEFA3 classes documented above.

For a heterogeneous fleet, define several `vType`s with different `emissionClass` values inside a `<vTypeDistribution>` (an "additional" file), each with a `probability`:

```xml
<additional>
    <vTypeDistribution id="fleet">
        <vType id="car_modern" vClass="passenger" emissionClass="HBEFA3/PC_G_EU4" probability="0.55" .../>
        <vType id="truck_hdv" vClass="truck" emissionClass="HBEFA3/HDV" probability="0.05" .../>
        <!-- ... -->
    </vTypeDistribution>
</additional>
```

Assign this distribution to generated demand by passing `type="<distribution-id>"` on the trips (e.g. `randomTrips.py --trip-attributes 'type="fleet"' --additional-files vtypes.add.xml`, see [[random-trips]]) — `duarouter` samples a concrete `vType` per vehicle from the distribution's probabilities when routing, and the resulting `.rou.xml` has real per-vehicle `type=` values (verifiable by counting occurrences and comparing to the declared probabilities). `$SUMO_HOME/tools/createVehTypeDistribution.py` can also generate a distribution from parameter distributions instead of a small hand-curated set.

## Getting emissions out of a run

Two independent, complementary outputs:

1. **Per-vehicle totals via tripinfo**: enable the emissions device with `--device.emissions.probability 1.0` (or a lower share to sample only some vehicles) and request `--tripinfo-output`. Each `<tripinfo>` element then gets an `<emissions CO2_abs=... CO_abs=... HC_abs=... NOx_abs=... PMx_abs=... fuel_abs=.../>` child with that vehicle's **totals across its whole trip**. All mass/fuel values are in **milligrams** — convert explicitly (÷1000 for g, ÷1e6 for kg) before reporting, a common source of 1000x reporting errors.
2. **Per-step trajectory via `--emission-output <file>`**: a full per-vehicle-per-timestep trace of instantaneous emission rates and position. This is genuinely useful for fine-grained analysis (e.g. emissions vs. speed/acceleration at a specific location) but grows large fast — for anything beyond a short run or small fleet, prefer relying on the tripinfo totals (item 1) unless the trajectory-level detail is actually needed, and consider not persisting the raw trajectory file as a long-term deliverable.
3. **Per-edge aggregated totals via edgeData**: an `<edgeData type="emissions" file="..." period="<seconds>"/>` additional file (same meandata mechanism as any other edgeData output, see [[sumo-output-files]]) accumulates `CO2_abs`/`NOx_abs`/`PMx_abs`/`fuel_abs`/etc. per edge over each aggregation window — this is what a spatial "emissions hotspot" analysis reads from, not the per-vehicle files.

## What tends to show up in practice

Emissions and fleet-share are frequently very disproportionate: a small percentage of older or heavy-duty vehicles can account for a majority of NOx/PMx even while contributing a much smaller share of CO2/fuel. This is because CO2/fuel scale roughly with vehicle-km traveled (so numerous, lighter vehicles dominate the total), while NOx/PMx scale much more steeply with vehicle class/age/fuel — a Euro 2 or heavy-duty vehicle can emit an order of magnitude more NOx per km than a modern passenger car. `PMx_abs` can legitimately be near-zero for some classes (e.g. modern filtered diesel) — that's a real HBEFA3 characteristic, not a bug. Spatially, emissions tend to concentrate on the busiest signalized internal approaches (stop-go driving raises per-km emission rates) rather than spreading evenly across the network, so a "which edges are worst" ranking usually surfaces the network's real congestion/queueing hotspots, not just its highest-volume edges.

See the `simulate-fleet-emissions` skill for the full pipeline and a bundled analysis/plotting script.

## Speed and emissions: a non-obvious interaction

HBEFA3's speed-emission relationship is not simply "faster is worse" — sustained low-speed cruising can emit *more* CO2 per km than higher, steadier speeds, because the relationship is roughly U-shaped rather than monotonic. This matters for any speed-altering control strategy: a [[glosa-eco-driving]] controller that successfully eliminates stops by gliding vehicles through at a sustained low speed can, on the wrong network (e.g. uncoordinated signals where few greens are catchable at a reasonable speed), *increase* total emissions relative to normal stop-and-go driving — a verified, counter-intuitive result, not a hypothetical one.

## Related device: battery/energy for electric vehicles

The same per-vType device-attachment pattern (`<param key="has.XXX.device" value="true"/>` plus sizing/model params) is used for SUMO's battery device on electric vehicles — a different resource (energy/state-of-charge, not pollutants) with real behavioral consequences (a vehicle can actually run out and strand). See [[electric-vehicle-battery-and-charging]].

## Routing on emissions rather than measuring them

Everything above treats emissions as an *output* to measure after routing on travel time. [[effort-based-routing-and-eco-routing]] covers the inverse: putting an emissions/fuel measure onto SUMO's separate "effort" edge-weight channel so vehicles are actually routed to minimize it, including the gotcha that an `edgeData type="emissions"` dump silently omits any attribute for a zero-flow edge — fatal if that dump is fed straight into a router.

## Emissions totals are `dt`-fragile; paired comparisons are not

A 2026-08-04 time-discretization audit (see [[sumo-time-discretization]]) confirmed this page's "stop-go raises per-km emissions" claim holds at every tested `(step-length, integration method, actionStepLength)` convention, with the effect size (signalized-minus-priority CO2, paired by CRN seed) stable to within ~15% (+60.5 to +70.6 g/km across four conventions, significant everywhere). **But absolute CO2/km levels on the same testbed moved 26% across the discretization sweep** — emissions are one of the most `dt`-sensitive output classes measured (second only to safety/SSM counts). The general lesson: a CRN-paired *comparison* between two designs can be trustworthy at a step length where neither design's *absolute total* is — because the shared discretization bias cancels in the difference. Report an emissions comparison with more confidence than an emissions total, and if a total must be reported, state the `(step-length, integration method, actionStepLength)` triple it was measured at.
