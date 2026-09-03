---
name: implement-alinea-ramp-metering
description: Use this skill when the user wants a freeway/motorway on-ramp scenario in SUMO with ramp metering — controlling how fast vehicles are released from an on-ramp based on downstream mainline conditions, as opposed to intersection signal control. Covers building a motorway+ramp network from hand-authored plain XML (netgenerate can't express ramp/merge geometry), defining E1 induction-loop detectors, and implementing the ALINEA feedback ramp-metering algorithm over TraCI. Trigger on mentions of ramp metering, ALINEA, freeway on-ramp control, merge congestion, or ramp queue vs mainline throughput trade-offs.
related_skills:
  - create-single-intersection
  - implement-maxpressure-traci-controller
  - implement-glosa-speed-advisory-controller
  - analyze-simulation-outputs
  - compare-zipper-vs-default-merge-at-lane-drop
  - model-managed-lanes-with-dynamic-tolling-and-self-selection
related_skills_for_graph_view:
  - "[[create-single-intersection]]"
  - "[[implement-maxpressure-traci-controller]]"
  - "[[implement-glosa-speed-advisory-controller]]"
  - "[[analyze-simulation-outputs]]"
  - "[[compare-zipper-vs-default-merge-at-lane-drop]]"
  - "[[model-managed-lanes-with-dynamic-tolling-and-self-selection]]"
related_pages:
  - "[[ramp-metering-with-alinea]]"
---

# Implement ALINEA Ramp Metering

Models a freeway on-ramp merge and controls the ramp's release rate via **ALINEA**, a classic feedback ramp-metering algorithm, to keep the downstream mainline near its critical (capacity-maximizing) occupancy. This is SimSkill's only freeway-scenario skill — every other network is either a signalized grid/spider/single-intersection or an OSM import, and every other closed-loop TraCI controller (`implement-maxpressure-traci-controller`, `implement-glosa-speed-advisory-controller`) controls intersection signals or vehicle speed, not a ramp's release rate.

## Building the network: plain XML, not netgenerate

`netgenerate` cannot express the asymmetric ramp/mainline geometry a forced merge needs (it's built for grid/spider/random topologies, not arbitrary node layouts) — the same reasoning `create-single-intersection` uses for per-arm control applies here. Hand-author `.nod.xml`/`.edg.xml` (and an explicit `.con.xml` for the merge connections) and compile with `netconvert`, following `create-single-intersection`'s plain-XML+netconvert technique adapted to a linear topology:

```xml
<!-- ramp.nod.xml -->
<nodes>
    <node id="n_in"      x="0"    y="0"   type="priority"/>
    <node id="n_up"      x="800"  y="0"   type="priority"/>
    <node id="n_merge"   x="1500" y="0"   type="zipper"/>
    <node id="n_end"     x="2500" y="0"   type="priority"/>
    <node id="n_ramp_in" x="1280" y="-70" type="priority"/>
    <node id="n_meter"   x="1390" y="-25" type="traffic_light"/>
</nodes>
```

```xml
<!-- ramp.edg.xml -->
<edges>
    <edge id="ml_in"      from="n_in"      to="n_up"    numLanes="2" speed="33.33" priority="10"/>
    <edge id="ml_up"      from="n_up"      to="n_merge" numLanes="2" speed="33.33" priority="10"/>
    <edge id="ml_down"    from="n_merge"   to="n_end"   numLanes="2" speed="33.33" priority="10"/>
    <edge id="ramp_in"    from="n_ramp_in" to="n_meter" numLanes="1" speed="16.67" priority="1"/>
    <edge id="ramp_merge" from="n_meter"   to="n_merge" numLanes="1" speed="22.22" priority="1"/>
</edges>
```

**The merge junction type is the single most important design decision.** A `priority`-type merge junction lets the ramp fully yield to the mainline — verified directly: this dumps all congestion onto the ramp while the mainline stays near free-flow, giving a ramp-metering algorithm nothing to actually improve. Use `type="zipper"` instead (equal-priority alternating merge) for a genuine forced 2-into-1 merge that actually degrades the mainline under heavy combined demand — this is what makes the scenario meaningful. An explicit `.con.xml` makes the forced merge unambiguous:

```xml
<!-- ramp.con.xml — ramp lane and mainline lane 0 both feed downstream lane 0 -->
<connections>
    <connection from="ml_up" to="ml_down" fromLane="0" toLane="0"/>
    <connection from="ml_up" to="ml_down" fromLane="1" toLane="1"/>
    <connection from="ramp_merge" to="ml_down" fromLane="0" toLane="0"/>
</connections>
```

Verify the forced merge actually exists in the compiled `.net.xml`: the contested lane's connections should show state `Z` (zipper) on both the mainline and ramp side feeding it, while an uncontested lane shows `M` (uncontested major move) — don't just trust the node/edge XML, check the compiled connection states.

**Get the ramp length right if the task specifies a range.** Compute the actual on-ramp length from the node coordinates (sum of all ramp edges) — and note that `netconvert` trims internal geometry at a zipper junction, so the *compiled* lane lengths (read from the actual `.net.xml`) can differ slightly from the raw node-to-node distance. Verify against the compiled output, not just the source coordinates.

## E1 detectors

```xml
<additional>
    <inductionLoop id="e1_down_0" lane="ml_down_0" pos="15"  period="60" file="/abs/path/to/run/detectors.xml"/>
    <inductionLoop id="e1_down_1" lane="ml_down_1" pos="15"  period="60" file="/abs/path/to/run/detectors.xml"/>
    <inductionLoop id="e1_up_0"   lane="ml_up_0"   pos="600" period="60" file="/abs/path/to/run/detectors.xml"/>
    <inductionLoop id="e1_ramp"   lane="ramp_in_0" pos="100" period="60" file="/abs/path/to/run/detectors.xml"/>
</additional>
```

Place one set **just downstream of the merge** (this is where ALINEA measures occupancy — right where merge-induced congestion first shows up), one **upstream** as a reference, and one **on the ramp** (queue/flow measurement). `period` is the real attribute name (not `freq`) for the aggregation interval in seconds. The output `file` path resolves relative to the additional file's own directory, not the caller's cwd — use an absolute path to avoid ambiguity, and give **each run its own dedicated output path** (see Gotchas).

## Flow-based demand

With only two fixed O-D movements (mainline-through, ramp-to-mainline), hand-written `<flow>` elements are simpler and more direct than `randomTrips.py`-generated demand:

```xml
<flow id="f_main" route="mainline_route" begin="0" end="3600" vehsPerHour="3600"/>
<flow id="f_ramp" route="ramp_route" begin="0" end="3600" vehsPerHour="1200"/>
```

Set the combined rate high enough that the merge's shared downstream lane is genuinely oversaturated (verify: baseline downstream speed should visibly collapse well below free-flow) — otherwise metering has no congestion to relieve.

## The ALINEA controller

```
r(k) = r(k-1) + K * (o_target - o_measured)
```

`o_measured` is the occupancy (%) at the downstream detector(s), averaged over the control interval; `r` is clamped to `[r_min, r_max]` (veh/h). `scripts/alinea_runner.py` implements this plus the **rate → signal-timing translation** — the genuinely new design decision this algorithm needs, since ALINEA outputs a continuous rate but a traffic light is binary: impose a one-car-per-green cycle of length `C = 3600 / r` seconds (green for `green_time`, red for the rest), holding the signal green outright if `C <= green_time` (rate at or above saturation). This translation is reusable for any rate-based metering algorithm, not just ALINEA.

**Calibrate `o_target` from the network's own data — don't assume a textbook value.** The commonly-cited 15-25% range is not universal; run a supplementary low-to-high mainline-only demand sweep (ramp closed) to trace the actual flow-vs-occupancy relationship at the downstream detector, and read off the occupancy where flow peaks. In one verified case, a 120 km/h point detector's critical occupancy was ~12-14%, well below the textbook range — the correct setpoint depends on detector placement, speed, and vehicle characteristics specific to the network being modeled.

## Comparing metered vs. unmetered

Run identical demand/network with `--mode unmetered` (ramp signal held permanently green) and `--mode metered` (ALINEA active), then compare: mainline throughput and speed (from the downstream detector time series), network-wide travel time/time loss/speed (from `tripinfo`), and **ramp cost** — critically, look at `departDelay` (SUMO's insertion backlog), not `tripinfo`'s `waitingTime`, for the true ramp queuing cost. A vehicle held back by a red meter signal before it even enters the network accrues delay as `departDelay`; `waitingTime` only counts involuntary halting *after* insertion and can stay near zero even when the real ramp queue is severe — checking only `waitingTime` will badly understate the ramp's cost.

## Gotchas

- **A `priority`-type merge lets the ramp fully yield — use `zipper`** for a scenario where metering actually has something to do. Verify via the compiled net's connection states (`Z` on the contested lane), not just the source XML.
- **Give each run's detector output a dedicated, absolute file path, and never re-invoke `sumo` against that same path afterward for a sanity check.** Doing so silently overwrites the real detector output — verified the hard way: a stray validation run with `--end 1` clobbered a full ~4600s, ~60-interval detector file down to a single 1-second stub, and the corruption wasn't caught until independently re-opening the file. Do any ad-hoc checks against a throwaway scratch path, separate from the real run's output.
- **The ramp queuing cost lives in `departDelay`, not `tripinfo`'s `waitingTime`** (see above) — using the wrong field will make metering look nearly free to ramp travelers when it isn't.
- **ALINEA improving the mainline does not guarantee it improves total network-wide delay.** This is a well-known, expected property (ALINEA optimizes mainline flow, not aggregate system delay) — a real verified comparison found the mainline improved substantially (speed +10%, time loss -23%) while ramp travelers paid a real cost (+21% queue delay), with network-wide total delay landing anywhere from roughly break-even to modestly worse depending on how much ramp storage/geometry constrains the queue. Report both sides honestly; don't treat "network-wide delay didn't improve" as a bug.
- `netconvert` trims internal geometry at a zipper junction — compiled edge/lane lengths can differ from raw node-to-node distances; verify lengths from the compiled `.net.xml`, not just the source coordinates, if a spec calls for a specific range.

## Related

- `create-single-intersection` — the plain-XML+netconvert technique this skill's network-building approach is adapted from.
- `implement-maxpressure-traci-controller` / `implement-glosa-speed-advisory-controller` — the other closed-loop TraCI controller patterns in memory; ALINEA's control-a-signal-from-external-feedback structure is closest to max-pressure's, though the decision law and what's being optimized (rate vs. phase choice) differ.
- `analyze-simulation-outputs` — general tripinfo/summary conventions this skill's comparison follows; E1 detector parsing needs a custom script (not covered by that skill).
- `compare-zipper-vs-default-merge-at-lane-drop` — the same `zipper` junction type and `Z`-state verification technique, applied to a straight 2-lane-to-1-lane work-zone lane drop instead of a ramp-onto-mainline merge; found zipper can actually *reduce* discharge under saturation there, a useful counterpoint to this skill's ramp-merge use of zipper.
- [[ramp-metering-with-alinea]] — the underlying algorithm, the rate-to-signal translation, the critical-occupancy calibration technique, and the verified mainline-benefit/ramp-cost trade-off finding.
- `model-managed-lanes-with-dynamic-tolling-and-self-selection` — repurposes this skill's feedback-control law as a dynamic toll-price update rule on managed-lane occupancy/speed, and reuses this skill's zipper-merge ramp-geometry construction for a managed-lane corridor's own on/off-ramps.
