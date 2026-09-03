---
name: analyze-intersection-safety-with-ssm
description: Use this skill when the user wants to quantify traffic safety in SUMO — near-misses, conflicts, time-to-collision (TTC), post-encroachment time (PET), deceleration-rate-to-avoid-crash (DRAC/MDRAC), or brake-rate (BR) — rather than travel-time/throughput performance. Covers enabling SUMO's SSM (surrogate safety measures) device on vehicles, the device's parameters and output XML schema, and comparing conflict profiles between scenarios (e.g. signalized vs. unsignalized, or before/after a safety intervention). Trigger on mentions of SSM device, surrogate safety measures, conflicts/near-misses, time-to-collision, post-encroachment time, DRAC, or "how safe is this intersection."
related_skills:
  - create-single-intersection
  - generate-random-trips
  - convert-trips-to-routes
  - optimize-signals-by-tlscycleadaptation
  - control-signals-with-actuated-tls
  - analyze-simulation-outputs
  - design-restricted-crossing-uturn-and-michigan-left-intersections
  - implement-reservation-based-autonomous-intersection-management
  - design-signal-change-and-clearance-intervals
related_skills_for_graph_view:
  - "[[create-single-intersection]]"
  - "[[generate-random-trips]]"
  - "[[convert-trips-to-routes]]"
  - "[[optimize-signals-by-tlscycleadaptation]]"
  - "[[control-signals-with-actuated-tls]]"
  - "[[analyze-simulation-outputs]]"
  - "[[design-restricted-crossing-uturn-and-michigan-left-intersections]]"
  - "[[implement-reservation-based-autonomous-intersection-management]]"
  - "[[design-signal-change-and-clearance-intervals]]"
related_pages:
  - "[[surrogate-safety-measures]]"
---

# Analyze Intersection Safety with the SSM Device

Quantifies traffic *safety* — as opposed to travel-time/throughput performance, which every other analysis skill in memory covers — using SUMO's built-in Surrogate Safety Measures (SSM) device. The SSM device logs vehicle-to-vehicle conflict encounters and computes standard traffic-safety proxies (TTC, PET, DRAC, MDRAC, BR) without needing real crash data.

## Enabling the SSM device

Equip a `vType` with the device via a `<param>` child (simpler than per-vehicle equipping when every vehicle should carry it):

```xml
<additional>
    <vType id="ssmCar" vClass="passenger" length="4.5" minGap="2.5" accel="2.6" decel="4.5" sigma="0.5" maxSpeed="16.0">
        <param key="has.ssm.device" value="true"/>
        <param key="device.ssm.measures" value="TTC DRAC PET BR MDRAC"/>
        <param key="device.ssm.thresholds" value="3.0 3.0 2.0 0.0 3.4"/>
        <param key="device.ssm.range" value="50.0"/>
        <param key="device.ssm.extratime" value="5.0"/>
        <param key="device.ssm.mdrac.prt" value="1.0"/>
    </vType>
</additional>
```

- `device.ssm.measures` — which measures to compute (space-separated).
- `device.ssm.thresholds` — the per-measure trigger threshold, **in the same order as `measures`** — an encounter is only logged as a conflict once a measure crosses its threshold (e.g. TTC < 3.0s, DRAC > 3.0 m/s², PET < 2.0s).
- `device.ssm.range` — detection radius (m) around the ego vehicle for candidate foe vehicles.
- `device.ssm.extratime` — extra seconds an encounter keeps being tracked after the immediate conflict ends; needed because PET (measured after both vehicles have passed the conflict point) wouldn't otherwise be captured.
- `--device.ssm.probability <FLOAT>` on the `sumo` command line is a global alternative to the per-vType `has.ssm.device` param, if equipping via vType isn't convenient for a given scenario.

**Gotcha: don't set `device.ssm.file` (the output filename) as a vType param if the vType will be routed through `duarouter` first.** `duarouter` re-expands/re-embeds the vType into its output route file and can path-mangle a relative `device.ssm.file` value (resolving it against the wrong directory). The reliable fix: omit `device.ssm.file` from the vType, and instead pass the output path per-run via `--device.ssm.file <path>` on the `sumo` command line — this also makes it trivial to run the same vType/demand against multiple scenario variants, each writing its own SSM log without editing the additional file.

## Output schema

```xml
<SSMLog>
  <conflict begin="..." end="..." ego="veh3" foe="veh7">
      <minTTC   value="0.42" time="123.0" type="12" .../>   <!-- "NA" if undefined for this encounter -->
      <maxDRAC  value="5.1"  time="124.0" type="12" .../>
      <PET      value="0.9"  time="125.0" type="12" .../>   <!-- "NA" for pure car-following, only defined for crossing/merging -->
      <maxMDRAC value="6.0"  time="124.0" type="12" .../>
  </conflict>
  <globalMeasures ego="veh3">
      <maxBR value="4.5" time="..."/>
      <minSGAP .../> <minTGAP .../>
  </globalMeasures>
</SSMLog>
```

- One `<conflict>` per (ego, foe) encounter episode, holding one extreme-value sub-element per requested measure (the *worst* value observed during that encounter, with its own `time`/`type`/position).
- `<globalMeasures>` is per-vehicle (not per-pair) — `maxBR` is that vehicle's own hardest braking event, independent of any specific conflict.
- **The `type` attribute is an encounter-type code, not arbitrary metadata** — use it to classify what kind of conflict occurred: `2,3,18` = following/rear-end, `6,7,8,19` = merging, `10-17` = crossing/angle, `111` = an actual (simulated) collision. This lets a comparison distinguish "more rear-end conflicts from stop-and-go queuing" from "more angle conflicts from unprotected turns" rather than just a single conflict count.

## Parsing and comparing variants

```bash
python scripts/analyze_ssm.py \
    --variant "priority=outputs/priority/ssm.xml,outputs/priority/tripinfo.xml,outputs/priority/summary.xml" \
    --variant "signalized=outputs/signalized/ssm.xml,outputs/signalized/tripinfo.xml,outputs/signalized/summary.xml" \
    --out-dir analysis/
```

For each variant, reports: total conflicts and a breakdown by encounter-type category (following/merging/crossing/collision), the count of conflicts below configurable TTC/PET severity thresholds (`--ttc-threshold`, default 1.5s; `--pet-threshold`, default 1.0s — the common traffic-safety-literature defaults, not hard requirements), the single worst (smallest) TTC/PET observed, and max DRAC/BR — alongside the usual efficiency metrics (throughput, mean waiting time/duration/time loss/speed, teleports) parsed from `tripinfo`/`summary` the same way `analyze-simulation-outputs` does.

**Correctly handles `summary.xml`'s cumulative `teleports` field** (reads the last step's value, doesn't sum across steps) — see [[surrogate-safety-measures]] and `analyze-simulation-outputs`'s own gotchas for why summing this field is a real bug that silently over-counts.

## What comparisons tend to show — and a genuine surprise worth remembering

Comparing an unsignalized (priority-controlled) intersection against a signalized one on identical, substantially-turning demand does **not** always show the signal as safer. In a verified comparison at a moderate, sub-capacity demand level, the signalized variant had *more* conflicts (dominated by a large increase in rear-end/following conflicts from stop-and-go platoon release at green) and *more* delay — i.e. a genuine "delay for nothing" result at that specific demand level, not the "signals trade some throughput for safety" trade-off often assumed by default. This happened because: (a) demand was too light to seriously stress the priority junction's gap-acceptance mechanism into risky merges, and (b) the signal's default plan used a permissive (not protected) left-turn phase, so it didn't even suppress the angle/crossing conflicts a protected-left plan would. **Don't assume signalization is automatically safer** — the actual answer depends on demand level and the specific signal plan's phase design (permissive vs. protected turns); measure it per scenario rather than asserting the conventional wisdom.

## Related

- `create-single-intersection` — the standard network shape for this kind of controlled A/B comparison (identical geometry, only `--junction-type` differing between variants).
- `generate-random-trips` + `convert-trips-to-routes` — build demand with a real turning-movement mix; filter out unrealistic same-arm U-turns if `randomTrips.py` generates them.
- `optimize-signals-by-tlscycleadaptation` / `control-signals-with-actuated-tls` — for the signalized variant's signal plan (a static Webster plan, native actuated logic, or netconvert's default fixed-time program are all reasonable choices).
- `analyze-simulation-outputs` — the travel-time/throughput analogue of this skill; reuse its conventions for the efficiency side of a safety+efficiency comparison.
- [[surrogate-safety-measures]] — the underlying SSM device concepts, parameters, and the verified safety/efficiency trade-off finding this skill's workflow is built on.
- `design-restricted-crossing-uturn-and-michigan-left-intersections` — uses this skill's SSM device setup and TTC/PET schema to cross-check a topological conflict-point count against simulated conflicts, and documents a further collinear-U-turn-merge SSM artifact.
- `implement-reservation-based-autonomous-intersection-management` — uses this skill's SSM device to test whether a zero-collision reservation controller's safety margin shows up as fewer or more severe simulated conflicts than a signal; found dramatically fewer, since the tested controller bought its margin with delay rather than tight clearances — a genuinely non-obvious result worth checking rather than assuming for any future collision-free controller.
- `design-signal-change-and-clearance-intervals` — uses this skill's SSM device to separately measure right-angle and rear-end conflict metrics across a yellow-length sweep, finding a genuine tradeoff between the two crash types rather than a single-metric optimum.
