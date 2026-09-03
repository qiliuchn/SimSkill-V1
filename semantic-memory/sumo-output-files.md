---
summary: SUMO's tripinfo, summary, edgeData, --stop-output and --fcd-output files — what each records, their key XML attributes, and how they're parsed into network-level performance metrics; including personinfo's walk/access/ride legs, the two things <ride> does not tell you (waitingTime is measured from the end of the access walk, and a denied boarding is recorded nowhere), the FCD sampling-period and precision flags that decide whether a trajectory plot is true, and the fact that an <edgeData> element's own file= wins over --edgedata-output so two runs sharing one additional file silently overwrite each other.
keywords:
  - tripinfo, summary-output, edgeData, meandata, post-processing, xml2csv, performance-metrics, stop-output, stopinfo, personinfo, fcd-output, device.fcd.period, precision.geo
created: 2026-07-23T11:43:23
last_updated: 2026-09-01T10:21:28
sources:
  - "[[episodic-memory/2026-07-23_11-43-23/outputs/baseline/tripinfo_baseline.xml]]"
  - "[[episodic-memory/2026-07-23_11-43-23/outputs/baseline/summary_baseline.xml]]"
  - "[[episodic-memory/2026-07-23_11-43-23/outputs/baseline/edgedata_baseline.out.xml]]"
  - https://sumo.dlr.de/docs/Simulation/Output/TripInfo.html
  - https://sumo.dlr.de/docs/Simulation/Output/Summary.html
  - https://sumo.dlr.de/docs/Simulation/Output/Lane-_or_Edge-based_Traffic_Measures.html
  - "[[episodic-memory/2026-08-11_18-30-39/summary.md]]"
  - "[[episodic-memory/2026-08-11_19-40-15/summary.md]]"
related_pages:
  - "[[station-based-shared-micromobility-in-sumo]]"
  - "[[sumo-command-line]]"
  - "[[tlscycleadaptation]]"
  - "[[routesampler]]"
  - "[[geh-statistic]]"
  - "[[vehicle-emissions-modeling]]"
  - "[[public-transport-and-intermodal-routing]]"
  - "[[cordon-tolling-and-e3-detectors]]"
  - "[[dedicated-bicycle-lanes-and-mode-share]]"
  - "[[freeway-weaving-segment-turbulence]]"
  - "[[surrogate-safety-measures]]"
  - "[[sumo-plotting-tools]]"
  - "[[sumo-stochastic-variability-and-replication-design]]"
  - "[[teleport-artifacts-and-gridlock-resolution-validity]]"
  - "[[traffic-state-estimation-sensor-bias-and-sensing-tradeoffs]]"
  - "[[transit-capacity-passenger-loading-and-pass-up-dynamics]]"
  - "[[bus-stop-infrastructure-design-parking-mechanism-and-tsp-interaction]]"
  - "[[georeferencing-sumo-output-and-cartographic-fidelity]]"
  - "[[intermodal-transfer-and-person-stage-semantics-in-sumo]]"
related_skills:
  - run-simulation
  - analyze-simulation-outputs
  - calibrate-demand-with-routesampler
  - simulate-fleet-emissions
  - simulate-multimodal-transit
  - analyze-intersection-safety-with-ssm
  - visualize-trajectories-and-timeseries
  - quantify-sumo-run-to-run-variability
  - validate-congested-scenario-results-against-teleport-artifacts
  - emulate-and-evaluate-partial-sensor-traffic-state-estimation
  - publish-georeferenced-and-animated-results
related_skills_for_graph_view:
  - "[[run-simulation]]"
  - "[[analyze-simulation-outputs]]"
  - "[[calibrate-demand-with-routesampler]]"
  - "[[simulate-fleet-emissions]]"
  - "[[simulate-multimodal-transit]]"
  - "[[analyze-intersection-safety-with-ssm]]"
  - "[[visualize-trajectories-and-timeseries]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[validate-congested-scenario-results-against-teleport-artifacts]]"
  - "[[emulate-and-evaluate-partial-sensor-traffic-state-estimation]]"
  - "[[publish-georeferenced-and-animated-results]]"
---

# SUMO Output Files (tripinfo, summary, edgeData)

SUMO can emit several XML output files while it runs, controlled by `.sumocfg`/CLI options. The three most useful for evaluating network performance — "did this change actually help?" — are `tripinfo`, `summary`, and `edgeData`. `analyze-simulation-outputs` parses all three into a comparison table and plots; this page documents what's actually in them.

## Enabling them

Pass the relevant options to `sumo` (see `run-simulation`, `[[sumo-command-line]]`):

```bash
sumo -n net.net.xml -r routes.rou.xml \
  --tripinfo-output tripinfo.xml \
  --summary-output summary.xml \
  -a edgedata.add.xml   # additional file defining an <edgeData> collector, see below
```

`edgeData` isn't a direct CLI flag — it's configured via an "additional file" loaded with `-a`/`--additional-files`:

```xml
<additional>
  <edgeData id="edgedata_baseline" file="edgedata_baseline.out.xml" freq="300"/>
</additional>
```

**`freq` controls the aggregation interval** (seconds) — each `<interval>` block in the output averages/sums over that window, not per simulation step. **The `file` path is written relative to the additional file's own directory**, not to SUMO's working directory at run time — verified directly against SUMO 1.27.1 (cwd and the additional file's directory set to two different locations; output landed next to the additional file, exit code 0, no warning). *(Correction: an earlier version of this page claimed the opposite — relative to SUMO's cwd. That was wrong and caused real batch-run breakage: parallel replications sharing one additional file silently overwrote each other's output. If the output doesn't show up where expected, check the additional file's own location, not the invoking cwd — and give every parallel run its own copy of the additional file if outputs must not collide.)*

## `tripinfo`: one record per completed vehicle

One `<tripinfo>` element per vehicle that finished its trip (vehicles still en route when the simulation ends, or that vaporized/teleported out, are handled specially — see gotchas). Key attributes, from a real record:

```xml
<tripinfo id="13" depart="39.00" departLane="A1B1_0" departPos="5.10" departSpeed="13.90"
          departDelay="0.00" arrival="48.00" arrivalLane="A1B1_0" arrivalPos="85.60"
          arrivalSpeed="6.27" duration="9.00" routeLength="80.50" waitingTime="0.00"
          waitingCount="0" stopTime="0.00" timeLoss="3.75" rerouteNo="0"
          vType="DEFAULT_VEHTYPE" speedFactor="1.16"/>
```

| Attribute | Meaning |
| --- | --- |
| `duration` | total trip time (s), depart to arrival — the basis for "mean/total travel time" |
| `routeLength` | distance traveled (m) — `routeLength / duration` gives mean trip speed |
| `waitingTime` | total time stopped (speed below a small threshold) during the trip |
| `timeLoss` | total time lost relative to free-flow speed (delay from signals, congestion, acceleration) — often the most sensitive metric for signal-optimization comparisons |
| `departDelay` | time between the vehicle's intended depart time and when it actually entered the network (insertion was blocked, e.g. by downstream congestion) |
| `rerouteNo` | number of times the vehicle was rerouted mid-trip |

**Counting `<tripinfo>` elements gives completed-trip throughput.** A route file with N vehicles but fewer than N `<tripinfo>` records means some trips never finished (still running at simulation end, or vaporized) — worth checking before trusting an otherwise-good-looking comparison.

## `personinfo`: one record per completed person, with walk/access/ride legs

When person demand is loaded (persontrips, walks), `--tripinfo-output` also emits one `<personinfo>` element per person alongside the vehicle `<tripinfo>` elements, with `duration`/`waitingTime`/`timeLoss` totals for that person's whole journey and a sequence of leg sub-elements describing exactly how they got there:

```xml
<personinfo id="p5" depart="60.00" type="DEFAULT_PEDTYPE" duration="416.00" waitingTime="111.00" timeLoss="95.28" traveltime="322.00">
    <walk depart="60.00" arrival="300.00" duration="240.00" routeLength="230.16" waitingTime="17.00"/>
    <access stop="ns_2" depart="300.00" arrival="302.00" duration="2.00" routeLength="2.60"/>
    <ride waitingTime="94.00" vehicle="bus_ns_1" depart="396.00" arrival="466.00" duration="70.00" routeLength="150.04" timeLoss="53.45"/>
    <access stop="ns_3" depart="466.00" arrival="468.00" duration="2.00" routeLength="2.60"/>
    <walk depart="468.00" arrival="476.00" duration="8.00" routeLength="7.80" waitingTime="0.00"/>
</personinfo>
```

| Leg element | Meaning |
| --- | --- |
| `<walk>` | a pedestrian leg; `routeLength`/`duration` as usual, `waitingTime` covers any pedestrian-side waiting (e.g. at a crossing) during that leg |
| `<access>` | the short pedestrian connector between a `busStop`'s sidewalk `<access>` link and the stop itself (`stop` names which busStop); present only immediately before/after a `<ride>` |
| `<ride>` | a public-transport leg; `vehicle` is the id of the PT vehicle actually boarded, `waitingTime` is time spent waiting at the stop for that vehicle to arrive (a key metric for transit-quality analysis) |

A person with **no `<ride>` element walked the whole trip**; a person with **one or more `<ride>` elements** used public transport for at least part of it — this is the standard way to compute a modal split from tripinfo output. See `simulate-multimodal-transit` / [[public-transport-and-intermodal-routing]] for the full pipeline that produces this data and a bundled analysis script.

Two things `<ride>` does **not** tell you, both verified in SUMO 1.27.1:

- **`waitingTime` is measured from the end of the `<access>` walk, not from `depart`** — which is the correct definition (a bus missed while the person was still walking is not a wait), and is what makes `depart − waitingTime` the true moment the person joined the stop's queue.
- **There is no record of a denied boarding.** `<ride>` has only `arrival, arrivalPos, depart, duration, routeLength, timeLoss, vehicle, waitingTime`. If a full vehicle refused this passenger three times, `waitingTime` correctly includes that wait but is indistinguishable from a single long headway. See [[transit-capacity-passenger-loading-and-pass-up-dynamics]] — a pass-up is invisible in *every* SUMO output channel and raises no warning, so it must be reconstructed by joining `--stop-output` with these `<ride>` records.
- **`<ride depart="-1">` can appear on a ride that actually completed** (valid `vehicle`, `arrival`, `routeLength`) — observed once in 98 000 rides. Guard any `depart`-based arithmetic.

**Do not read `-1` as "this person failed".** A *stranded* traveller — one still at a stop when the horizon ends — is a different case with a different signature: the `<personinfo>` itself carries `duration="-1"`, and the leg they were stuck on has `vehicle="NULL" depart="-1" duration="-1"` **but a real, non-negative `waitingTime`**. The reliable marker is `vehicle="NULL"`, not `depart="-1"`, which (per the bullet above) also occurs on completed rides. A parser that treats `duration="-1"` as a zero-duration completion silently counts stranded travellers as free trips — and that censoring is large enough to reverse a service-plan comparison. See [[intermodal-transfer-and-person-stage-semantics-in-sumo]] for the full stage decomposition (which reconciles to `personinfo@duration` with 0.0 s error) and [[transit-network-design-and-frequency-setting]] for the reversal.

## `--stop-output`: one record per vehicle stop event

Separate from the three files above, `--stop-output <file>` emits one `<stopinfo>` per vehicle stop — the primary source for transit dwell and loading analysis. Its attribute set is **stop-type dependent**, and the difference matters: a `busStop` record carries `id, type, busStop, lane, pos, parking, started, ended, delay, initialPersons, loadedPersons, unloadedPersons, initialContainers, loadedContainers, unloadedContainers, blockedDuration`, while a **`parkingArea` record carries `parkingArea` in place of `busStop`** (verified against SUMO 1.27.1). `parkingArea` is the attribute that makes `--stop-output` an **offline substitute for TraCI occupancy sampling** — each record's `started`/`ended` pair reconstructs a per-lot occupancy series without driving the run over TraCI at all, which is what lets an inventory ledger be rebuilt from a channel a controller never touches (see [[station-based-shared-micromobility-in-sumo]] and [[parking-areas-and-rerouters]]). Pair it with `--stop-output.write-unfinished` or every vehicle still parked at the horizon is omitted.

Derived quantities: `dwell = ended − started`, and `load_on_departure = initialPersons − unloadedPersons + loadedPersons`. Note there is **no capacity or denial field** — the only indirect sign that a vehicle left full is `initialPersons − unloadedPersons + loadedPersons == personCapacity`.

Also note `<stop parking="true">` hides a real, flow-dependent bay re-entry cost *inside* `ended` rather than in post-stop movement timing — see [[bus-stop-infrastructure-design-parking-mechanism-and-tsp-interaction]].

## `--fcd-output`: per-vehicle positions, and the two flags that decide whether it is usable

`--fcd-output <file>` writes every vehicle's position and speed per sampling step — the input for trajectory plots and animations. Three options govern it, and the defaults are wrong for most uses:

- **`--device.fcd.period`** sets the sampling period. This is the parameter that decides whether an animation or a trajectory plot is *true*: measured against a full-resolution 0.1 s reference, ≤1 s is faithful, 2 s is the ceiling, 5 s is misleading, and at 10 s a signal discharge wave is unmeasurable in 69% of green onsets. Critically, **slow and fast waves have different requirements from the same run** — a queue envelope is still within 13% at 10 s while stop/discharge waves alias badly. See [[georeferencing-sumo-output-and-cartographic-fidelity]].
- **`--fcd-output.filter-edges.input-file`** restricts output to named edges. Prefer this to sampling coarser: an unfiltered network at 0.1 s reaches hundreds of MB (225 MB for one corridor-hour).
- **`--fcd-output.geo`** emits lon/lat instead of local XY. It is governed by **`--precision.geo` (default 6)**, and local coordinates by **`--precision` (default 2)**. Comparing SUMO's geo output against a Python `sumolib` conversion at defaults appears to show a ~7 cm disagreement that is **entirely output quantisation, not a transform difference** — at `--precision 10 --precision.geo 12` the two agree to 6.75e−08 m.

## Two `<edgeData>` collectors must not share an additional file

Worth stating separately because it silently destroys data: an `<edgeData>` element's own `file=` attribute **wins over the `--edgedata-output` command-line option**, and (per the note above) resolves relative to the additional file's own directory. So a second run that reuses the same `.add.xml` overwrites the first run's output, whatever `--edgedata-output` says. Observed in practice when a `sumo-gui` probe run reusing one `edgedata.add.xml` wiped the edgeData that four downstream analysis scripts read — leaving a file containing only SUMO's config-echo header, with zero `<interval>` elements and no error anywhere. Give every run its own copy of the additional file.

## `summary`: one record per simulation step, network-wide

One `<step>` element per simulation step (or per `--step-length`-sized interval), with network-wide aggregates:

```xml
<step time="0.00" loaded="2" inserted="1" running="1" waiting="0" ended="0" arrived="0"
      collisions="0" teleports="0" halting="0" stopped="0" meanWaitingTime="0.00"
      meanTravelTime="-1.00" meanSpeed="13.17" meanSpeedRelative="0.95" discarded="0" duration="1"/>
```

| Attribute | Meaning |
| --- | --- |
| `running` | vehicles currently in the network at this step — the basis for a "congestion over time" plot |
| `meanSpeed` | mean speed (m/s) of all running vehicles this step |
| `teleports` | **cumulative** count of vehicles teleported so far in the run (SUMO's mechanism for resolving gridlock by force-moving a stuck vehicle) — read the **last** `<step>`'s value directly (or `max()` across steps) for the run's total; do NOT sum across steps, since the attribute already accumulates and summing wildly over-counts (verified directly: a run with 5 real teleports shows `teleports="0"` for many steps then climbs 1→2→3→4→5 and *stays* at 5 for every remaining step, never resetting) |
| `halting` | vehicles below the halting-speed threshold this step |

**`meanSpeed` (and `meanTravelTime`) use `-1` as a sentinel for "not computable this step"** — typically when `running == 0`, i.e. no vehicles are currently in the network (start-of-run before insertion, or a fully drained network at the tail). Treat `-1` as missing data, not a real (negative) speed — plotting it as-is produces a misleading dip to -1 at the start/end of a run. `analyze-simulation-outputs`'s time-series plot already filters these points out.

## `edgeData` / `meandata`: per-edge aggregates over an interval

Requires an `<edgeData>` additional file (above). Output is one `<interval>` block per `freq`-sized time window, containing one `<edge>` per network edge:

```xml
<interval begin="0.00" end="300.00" id="edgedata_baseline">
  <edge id="A0A1" sampledSeconds="195.47" traveltime="13.61" overlapTraveltime="14.59"
        density="6.82" overlapDensity="7.27" laneDensity="6.82" occupancy="3.41"
        waitingTime="50.00" timeLoss="100.04" speed="6.48" speedRelative="0.47"
        departed="3" arrived="1" entered="11" left="12" laneChangedFrom="0"
        laneChangedTo="0" flow="161.53"/>
  ...
</interval>
```

`sampledSeconds` is vehicle-seconds spent on that edge during the interval (sum it across edges/intervals as a cross-check against `tripinfo`'s total travel time). Useful for spotting *which* edges are the bottleneck, rather than just the network-wide average that `tripinfo`/`summary` give — e.g. confirm a signal-timing optimization helped a specific congested corridor, not just the network mean.

This same `<interval>`/`<edge>` shape, with an `entered` (or similar) attribute giving a per-edge vehicle count, is also the format [[routesampler]] expects for its target counts input — an edgeData file isn't only a simulation *output*, it doubles as the hand-authored (or real-detector-derived) counts file that drives count-based demand calibration. Comparing a calibration's simulated edgeData output against such a target counts file, using the [[geh-statistic]], is the standard way to validate that a calibration actually worked.

The same edgeData/meandata mechanism also has a `type="emissions"` variant, aggregating per-edge pollutant totals (`CO2_abs`, `NOx_abs`, `PMx_abs`, `fuel_abs`, etc.) instead of traffic counts — see [[vehicle-emissions-modeling]] for how that's configured and used for spatial emissions-hotspot analysis.

For quantifying *safety* rather than performance — conflicts, near-misses, time-to-collision — see [[surrogate-safety-measures]], a separate per-vehicle device (SSM) with its own output file and schema, not part of tripinfo/summary/edgeData.

For turning any of these output files into an actual plot rather than a numeric table — trajectory diagrams from FCD output, time-series charts from `summary.xml` — see [[sumo-plotting-tools]].

## Parsing and comparing

Two ways to consume these files, both used by `analyze-simulation-outputs`:

1. **`$SUMO_HOME/tools/xml/xml2csv.py`** — SUMO's own converter, turns any of these XML files into a flat CSV (same location-under-`tools/` convention as `randomTrips.py`/`tlsCycleAdaptation.py`; not next to the `sumo` binary itself). Good for spreadsheet/pandas inspection, not required for scripted metric extraction.
2. **Direct `xml.etree.ElementTree.iterparse`** — stream the file, extracting `duration`/`waitingTime`/`timeLoss`/`routeLength` from each `<tripinfo>` and `teleports` from each `<step>`, without loading the whole file into memory. This is what actually computes the aggregate metrics (mean/total travel time, mean waiting time, mean time loss, mean speed, throughput, total teleports).

See `run-simulation` for how to configure these outputs, and `analyze-simulation-outputs` for the comparison script itself.
