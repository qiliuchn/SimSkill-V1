---
summary: ALINEA is a classic feedback ramp-metering algorithm that adjusts an on-ramp's release rate from downstream mainline occupancy (r(k) = r(k-1) + K*(o_target - o_measured)); realized in SUMO via a one-car-per-green signal cycle, it substantially improved mainline speed/delay in a verified freeway scenario at a real ramp-queuing cost, with network-wide total delay sensitive to ramp storage geometry.
keywords:
  - ALINEA
  - ramp-metering
  - freeway-control
  - induction-loop-detector
  - merge-congestion
created: 2026-07-23T19:28:51
last_updated: 2026-07-23T19:28:51
sources:
  - "[[episodic-memory/2026-07-23_18-40-19/attempts/attempt-3/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-23_18-40-19/attempts/attempt-3/critic-agent-feedback.json]]"
related_pages:
  - "[[max-pressure-signal-control]]"
  - "[[glosa-eco-driving]]"
  - "[[abstract-network-generation]]"
  - "[[traci]]"
  - "[[variable-speed-limits-and-e2-detectors]]"
  - "[[macroscopic-fundamental-diagram]]"
  - "[[freeway-weaving-segment-turbulence]]"
  - "[[dfrouter-detector-based-demand-reconstruction]]"
  - "[[zipper-merge-lane-drop-discharge]]"
  - "[[mfd-based-perimeter-gating]]"
  - "[[managed-lanes-empty-lane-paradox-and-person-throughput]]"
  - "[[coordinated-ramp-metering-delay-transfer-and-ramp-storage]]"
related_skills:
  - implement-alinea-ramp-metering
  - implement-maxpressure-traci-controller
  - create-single-intersection
  - implement-mfd-based-perimeter-gating
  - model-managed-lanes-with-dynamic-tolling-and-self-selection
related_skills_for_graph_view:
  - "[[implement-alinea-ramp-metering]]"
  - "[[implement-maxpressure-traci-controller]]"
  - "[[create-single-intersection]]"
  - "[[implement-mfd-based-perimeter-gating]]"
  - "[[model-managed-lanes-with-dynamic-tolling-and-self-selection]]"
---

# Ramp Metering with ALINEA

ALINEA (Papageorgiou et al.) is a classic, simple feedback control algorithm for freeway on-ramp metering — it regulates a ramp's vehicle release rate to keep the downstream mainline near its critical (capacity-maximizing) occupancy, rather than letting on-ramp demand freely add to mainline flow and push it into breakdown. This is SimSkill's first freeway/motorway scenario and first ramp-control algorithm — a different network topology (linear mainline + merging ramp, requiring hand-authored plain XML since `netgenerate` can't express it) and a different control object (a ramp's continuous release *rate*, not a signal *phase* or a vehicle's *speed*) from every other closed-loop TraCI controller in memory. See [[variable-speed-limits-and-e2-detectors]] for the mainline-speed analogue of this same downstream-detector-feedback pattern.

## The algorithm

```
r(k) = r(k-1) + K * (o_target - o_measured)
```

Every control interval (e.g. 60s): measure `o_measured`, the occupancy (%) at a detector just downstream of the merge; compute the new rate `r` from the previous rate plus a gain `K` times the gap between a critical-occupancy setpoint `o_target` and what was actually measured; clamp `r` to `[r_min, r_max]` (veh/h). If the mainline is under-occupied relative to target, the ramp is allowed to release more; if over-occupied, less.

## Realizing a rate through a binary signal

ALINEA outputs a continuous rate, but a ramp meter is a traffic light — a real translation is needed. The verified working approach: impose a one-car-per-green metering cycle of length `C = 3600 / r` seconds on the ramp signal (green for a short `green_time`, e.g. 2s, long enough to release roughly one vehicle, then red for the remainder of the cycle) — this discharges approximately `r` vehicles/hour. If `C <= green_time` (rate at or above the ramp's own saturation), hold the signal green outright rather than cycling. This translation is reusable for any rate-output metering algorithm, not specific to ALINEA.

## Calibrating the occupancy setpoint — don't assume a textbook value

The commonly-cited critical-occupancy range in the transportation literature (roughly 15-25%) is not universal — it depends on detector placement, mainline speed, and vehicle characteristics. **Measure it from the actual network**: run a supplementary demand sweep (mainline-only, ramp closed, sweeping from light to heavy volume) and trace the flow-vs-occupancy relationship at the downstream detector; the occupancy where flow peaks is the network's real critical occupancy. In one verified case (a 120 km/h / 33.3 m/s mainline with a point detector just past the merge), the measured critical occupancy was **~12-14%** — well below the textbook range — because a high-speed, low-density point-detector reading simply doesn't reach the same numeric occupancy at capacity that a slower or longer-detection-zone setup would. Set `o_target` just below the measured peak (a small conservative margin), and treat any deviation from the textbook range as something to verify empirically per-network, not something to assume.

## Network construction: forced merge is essential

Build the motorway from hand-authored `.nod.xml`/`.edg.xml` (plus an explicit `.con.xml` for the merge), compiled with `netconvert` — `netgenerate` cannot express this asymmetric ramp/mainline topology. **The merge junction type is the single most consequential design decision**: a `type="priority"` junction lets the on-ramp fully yield to the mainline, which (verified directly) dumps essentially all congestion onto the ramp while the mainline stays near free-flow — leaving a metering algorithm nothing to actually improve. `type="zipper"` (equal-priority alternating merge) produces a genuine forced 2-into-1 merge that measurably degrades mainline speed under heavy combined demand, which is what makes a metering study meaningful. Verify the forced merge in the compiled network by checking connection states: the contested lane shows `Z` on both the mainline and ramp side feeding it, an uncontested lane shows `M`.

## E1 detectors

```xml
<inductionLoop id="e1_down_0" lane="ml_down_0" pos="15" period="60" file="/abs/path/detectors.xml"/>
```

`period` (not `freq`) is the real aggregation-interval attribute. Place detectors just downstream of the merge (ALINEA's measurement point), upstream (reference), and on the ramp (queue/flow). **Give every run's detector output a dedicated, absolute file path, and never re-run `sumo` against that same path afterward for even a quick sanity check** — doing so silently overwrites the real output. This was learned directly: a stray validation invocation with `--end 1` clobbered a full ~4600-second, ~60-interval detector file down to a single 1-second stub, and the corruption wasn't discovered until independently re-opening the file during review — a purely mechanical, easily-avoided data-integrity failure that cost an entire extra iteration to catch and fix.

## The real ramp cost hides in `departDelay`, not `waitingTime`

A vehicle held back by a red meter signal before it even enters the network accrues its wait as `departDelay` (SUMO's insertion backlog), not as `tripinfo`'s `waitingTime` (which only counts involuntary halting *after* insertion, per [[sumo-output-files]]'s general documentation of that field). In a verified ramp-metering comparison, ramp `waitingTime` stayed near 0-1 second in both the unmetered and metered runs, while `departDelay` rose substantially under metering (+21% mean, +17.5% max) — checking only `waitingTime` would have made metering look almost free to ramp travelers when the real cost was real and significant.

## Verified finding: mainline benefit is real, system-wide delay depends on ramp geometry

On a verified freeway on-ramp scenario (2-lane mainline, 1-lane ramp with a genuine ~198m length forcing a real queue, zipper merge, oversaturating combined demand): ALINEA metering **substantially improved mainline quality** — mean trip speed +10.0%, time loss -23.1%, downstream mean speed +2.5% — with a slight mainline throughput *gain* (+0.6%), **at a real cost to ramp travelers** (mean queue/insertion delay +20.9%, max wait +17.5%). Network-wide total delay (mainline + ramp combined) came out essentially break-even in this scenario — a materially different, more favorable result than an earlier iteration with an oversized (~824m) ramp, which showed system-wide delay +8.7% *worse* under metering. **The lesson: ALINEA's mainline benefit is robust, but whether total system delay improves, breaks even, or worsens is sensitive to how much ramp storage/queue capacity actually exists** — a genuine, literature-consistent property (ALINEA optimizes mainline flow, not necessarily aggregate system delay), not evidence of an error when the aggregate number doesn't clearly improve.

See the `implement-alinea-ramp-metering` skill for the full network/detector/controller implementation. [[coordinated-ramp-metering-delay-transfer-and-ramp-storage]] generalizes this single-ramp result to a multi-ramp corridor: it makes the "sensitive to ramp storage" caveat above precise (a storage-ratio threshold), adds the origin-insertion delay term that a single short ramp can hide, and finds that HERO-style coordination across ramps loses to isolated ALINEA when the shared bottleneck has no capacity drop to defend.
