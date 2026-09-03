---
summary: SUMO's SSM device logs vehicle-to-vehicle conflict encounters and computes surrogate safety measures (TTC, PET, DRAC, MDRAC, BR) without real crash data; a verified comparison found a signalized intersection is not automatically safer than a priority-controlled one — it depends on demand level and whether turns are protected or permissive.
keywords:
  - SSM-device
  - surrogate-safety-measures
  - time-to-collision
  - post-encroachment-time
  - DRAC
created: 2026-07-23T17:09:35
last_updated: 2026-08-06T23:54:30
sources:
  - "[[episodic-memory/2026-07-23_16-49-11/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-23_16-49-11/attempts/attempt-1/critic-agent-feedback.json]]"
  - https://sumo.dlr.de/docs/Simulation/Output/SSM_Device.html
related_pages:
  - "[[sumo-output-files]]"
  - "[[abstract-network-generation]]"
  - "[[actuated-traffic-signals]]"
  - "[[roundabout-modeling-and-comparison]]"
  - "[[pedestrian-crossings-and-signal-phasing]]"
  - "[[weather-friction-effects-on-capacity-and-safety]]"
  - "[[opposite-direction-overtaking-mechanics]]"
  - "[[right-turn-on-red-and-leading-pedestrian-interval]]"
  - "[[left-turn-treatment-tradeoffs]]"
  - "[[unsignalized-vs-signalized-intersection-control]]"
  - "[[roundabout-capacity-law-and-demand-metering]]"
  - "[[autonomous-intersection-management-safety-and-performance-envelope]]"
  - "[[signal-clearance-intervals-dilemma-zone-and-safety-capacity-tradeoff]]"
  - "[[sumo-time-discretization]]"
  - "[[transport-economic-appraisal-from-microsimulation]]"
  - "[[reversible-lane-encoding-and-changeover-safety]]"
  - "[[network-safety-screening-and-crash-prediction]]"
  - "[[motorist-yielding-calibration-and-midblock-crossing-treatment-selection]]"
  - "[[intersection-sight-distance-and-sumo-visibility-parameter]]"
  - "[[corridor-access-management-twltl-representation-and-density-effects]]"
related_skills:
  - analyze-intersection-safety-with-ssm
  - evaluate-corridor-access-management-and-median-treatments
  - create-single-intersection
  - control-signals-with-actuated-tls
  - create-roundabout-network
  - measure-roundabout-capacity-and-implement-metering
  - implement-reservation-based-autonomous-intersection-management
  - design-signal-change-and-clearance-intervals
  - calibrate-motorist-yielding-and-select-midblock-crossing-treatment
  - model-intersection-sight-distance-restriction-at-a-twsc-junction
related_skills_for_graph_view:
  - "[[analyze-intersection-safety-with-ssm]]"
  - "[[evaluate-corridor-access-management-and-median-treatments]]"
  - "[[create-single-intersection]]"
  - "[[control-signals-with-actuated-tls]]"
  - "[[create-roundabout-network]]"
  - "[[measure-roundabout-capacity-and-implement-metering]]"
  - "[[implement-reservation-based-autonomous-intersection-management]]"
  - "[[design-signal-change-and-clearance-intervals]]"
  - "[[calibrate-motorist-yielding-and-select-midblock-crossing-treatment]]"
  - "[[model-intersection-sight-distance-restriction-at-a-twsc-junction]]"
---

# Surrogate Safety Measures (SSM Device)

SUMO's SSM (Surrogate Safety Measures) device is a per-vehicle device that logs conflict encounters with nearby vehicles and computes standard traffic-safety proxy metrics — quantifying *safety* (near-misses, conflict severity) rather than the travel-time/throughput performance every other analysis capability in memory measures. It doesn't require any real crash data: the proxies are computed purely from simulated vehicle trajectories. **It only covers vehicle-vehicle conflicts** — for pedestrian-vehicle conflict exposure, see [[pedestrian-crossings-and-signal-phasing]], which measures that directly via TraCI instead.

## Metrics

- **TTC (Time-To-Collision)**: seconds until two vehicles would collide if they kept their current speeds/trajectories — smaller is more dangerous. `minTTC` per conflict episode is the closest call.
- **PET (Post-Encroachment Time)**: the time gap between one vehicle leaving a shared conflict point/area and the other arriving at it — only meaningful for crossing/merging encounters (undefined, `"NA"`, for pure car-following). Smaller PET means the two vehicles passed through the same point closer together in time.
- **DRAC (Deceleration Rate to Avoid Crash)**: the deceleration a following vehicle would need to apply to avoid a collision — larger DRAC means a harder emergency stop was needed.
- **MDRAC (Modified DRAC)**: DRAC adjusted for a driver reaction/perception time (`device.ssm.mdrac.prt`) before braking.
- **BR (Brake Rate)**: a vehicle's own realized deceleration, independent of any specific conflict — reported per-vehicle in `<globalMeasures>`, not per-conflict-pair.

## Enabling and configuring

Equip a `vType` (so every vehicle using it carries the device):

```xml
<vType id="ssmCar" ...>
    <param key="has.ssm.device" value="true"/>
    <param key="device.ssm.measures" value="TTC DRAC PET BR MDRAC"/>
    <param key="device.ssm.thresholds" value="3.0 3.0 2.0 0.0 3.4"/>
    <param key="device.ssm.range" value="50.0"/>
    <param key="device.ssm.extratime" value="5.0"/>
</vType>
```

`thresholds` are in the same order as `measures` and determine when an encounter is logged as a conflict at all (e.g. only once TTC drops below 3.0s). `extratime` keeps tracking an encounter a bit past its immediate resolution — necessary for PET, which by definition is only knowable after both vehicles have cleared the conflict point. `--device.ssm.probability` on the `sumo` command line is a global alternative to the per-vType param for equipping a fraction (or all) of vehicles without editing a vType.

**A real gotcha**: don't set `device.ssm.file` (the output path) as a vType param if that vType will pass through `duarouter` — `duarouter` re-embeds/re-expands the vType and can mangle a relative file path. Passing the output file per-run via `--device.ssm.file <path>` on the `sumo` command line instead is the reliable approach, and conveniently lets the same vType/demand run against multiple scenario variants without editing the additional file between runs.

## Output structure

```xml
<SSMLog>
  <conflict begin="..." end="..." ego="veh3" foe="veh7">
      <minTTC value="0.42" time="123.0" type="12" .../>
      <PET value="0.9" time="125.0" type="12" .../>   <!-- "NA" for pure following -->
  </conflict>
  <globalMeasures ego="veh3">
      <maxBR value="4.5" time="..."/>
  </globalMeasures>
</SSMLog>
```

One `<conflict>` per encounter episode between a specific ego/foe pair, holding the *worst* value seen for each requested measure. The `type` attribute on each measure is an **encounter-type code** worth classifying rather than ignoring: `2,3,18` = following/rear-end, `6,7,8,19` = merging, `10-17` = crossing/angle, `111` = labelled "collision". Breaking conflicts down by this code turns "conflicts went up" into an actionable diagnosis (e.g. "the increase is almost entirely rear-end conflicts from stop-and-go queuing," as opposed to more dangerous angle conflicts).

**Correction: a `type="111"` encounter does NOT mean SUMO registered an actual simulated collision.** Verified (see [[sumo-time-discretization]]'s time-discretization audit): 7-29 type-111 encounters occurred per run with `collisions=0` in both the `summary` output and `--collision-output`. Always cross-check a "collision" reading against those two authoritative sources before reporting any simulated crash.

## Verified finding: signalization is not automatically safer

Comparing a priority-controlled and a signalized variant of the *same* 4-arm intersection geometry, on identical substantially-turning demand (~280 veh/h per arm — moderate, sub-capacity): the signalized variant had **more** total conflicts (1766 vs. 487), **more** severe conflicts (TTC<1.5s: 858 vs. 124), a **worse** single closest call (worst TTC 0.20s vs. 0.64s), and **also more delay** (mean waiting time 11.78s vs. 2.01s). The conflict increase was overwhelmingly rear-end/following conflicts (243→1166) from stop-and-go platoon release at each green phase, not a reduction in angle/crossing conflicts (222→552, also increased) — because the default signal plan used a *permissive*, not protected, left-turn phase, so unprotected left turns across oncoming traffic still occurred under the signal too.

This was independently verified as a genuine result (sane, non-degenerate signal timing; identical demand across both runs; hand-recomputed metrics matching exactly) rather than a broken setup. **The lesson: don't assume a signal is automatically the safer design** — at light-to-moderate demand where a priority junction's gap-acceptance mechanism isn't seriously stressed, and with a permissive rather than protected turn phase, a signal can add both delay and conflicts with no safety benefit. The classical "signals trade some efficiency for safety" intuition is a hypothesis to test at the actual demand level and signal-plan design in question, not a default to assume — heavier demand (where gap acceptance genuinely breaks down at an unsignalized junction) or a protected-left signal plan would be expected to shift this result.

**Re-qualification (2026-08-04 time-discretization audit, see [[sumo-time-discretization]]): the headline direction holds, but the absolute counts above are not portable and one sub-claim does not survive.** Re-testing the same priority-vs-signalized comparison across four `(step-length, integration method, actionStepLength)` conventions (6 CRN seeds, an independently rebuilt 4-arm testbed) found the signalized variant significantly worse on total conflicts and mean delay at every convention — the headline conclusion is robust. However: (1) **absolute severe-conflict (TTC<1.5s) counts moved by a factor of ~7 between conventions on identical demand and geometry** (e.g. 52 vs. 9.7 for the priority variant) — treat any stored SSM count as meaningful only alongside its discretization settings, and read the "1766 vs 487" style of figures above as *ordinal* (which design has more conflicts) rather than *cardinal* (exactly how many). (2) **A PET-based sub-conclusion flips**: at SUMO's plain defaults the signal had significantly *fewer* PET-defined conflicts than the priority junction; once driver reaction time was pinned to a realistic value, that became a non-significant difference of the opposite sign. A claim of the form "the signal reduces crossing-conflict exposure (via PET)" would not survive re-measurement and should not be drawn from this page's numbers.

See the `analyze-intersection-safety-with-ssm` skill for the full workflow and a bundled parsing/comparison script. For a third control-type comparison beyond priority-vs-signalized, see [[roundabout-modeling-and-comparison]] — a roundabout can have the *highest total conflict count* at some demand levels while still being categorically safer (zero angle conflicts/collisions), reinforcing that raw conflict count alone is a misleading safety metric without the encounter-type breakdown.
