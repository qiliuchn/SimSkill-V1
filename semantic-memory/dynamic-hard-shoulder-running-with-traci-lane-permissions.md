---
summary: Runtime traci.lane.setAllowed opens/closes a SUMO lane's vClass permissions during a running simulation, but a net compiled with a lane closed traps vehicles at the junction because netconvert bakes the restriction into internal connector lanes and the load-time connectivity graph isn't rebuilt; the fix is compiling open and gating access via setAllowed at t=0. setAllowed also only gates future lane entry, never affecting vehicles already on the lane.
keywords:
  - setAllowed
  - setDisallowed
  - hard-shoulder-running
  - lane-permissions
  - traci
  - connectivity-graph
created: 2026-07-28T09:00:00
last_updated: 2026-08-04T17:00:00
sources:
  - "[[episodic-memory/2026-07-27_21-08-01/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-27_21-08-01/attempts/attempt-2/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-27_21-08-01/attempts/attempt-2/critic-agent-feedback.json]]"
related_pages:
  - "[[traci]]"
  - "[[variable-speed-limits-and-e2-detectors]]"
  - "[[managed-lanes-empty-lane-paradox-and-person-throughput]]"
  - "[[reversible-lane-encoding-and-changeover-safety]]"
related_skills:
  - implement-dynamic-hard-shoulder-running
  - model-vclass-lane-permissions
  - implement-variable-speed-limits
  - model-managed-lanes-with-dynamic-tolling-and-self-selection
related_skills_for_graph_view:
  - "[[implement-dynamic-hard-shoulder-running]]"
  - "[[model-vclass-lane-permissions]]"
  - "[[implement-variable-speed-limits]]"
  - "[[model-managed-lanes-with-dynamic-tolling-and-self-selection]]"
---

# Dynamic Hard-Shoulder Running with TraCI Lane Permissions

`traci.lane.setAllowed(laneID, vClasses)` (and its complement `setDisallowed`) changes which vehicle classes may use a lane *while the simulation is running* — the runtime counterpart to the static, netconvert-time `allow`/`disallow` lane attributes covered in [[vehicle-class-lane-permissions]]-style static permission editing. This is the mechanism behind dynamic hard-shoulder running (HSR): a shoulder lane normally reserved for `emergency`/`authority` vehicles is temporarily opened to `passenger` traffic under congestion, then closed again once it clears.

## The connectivity-graph gotcha: compile open, gate at runtime

**A network compiled with a lane closed to a vClass at netconvert time cannot be reliably reopened to that vClass purely via a later `setAllowed` call.** netconvert bakes the closed lane's restriction into the *internal junction connector lanes* generated for that junction, and SUMO's load-time best-lanes/connectivity graph — which determines which lanes a vehicle can actually route across a junction on — is fixed at load time and is not rebuilt in response to a runtime permission change. The practical symptom: vehicles enter the approach lane (now nominally open) but cannot cross the junction into the lane's continuation on the far side, effectively trapping them mid-network even though the lane's own `allow` attribute now permits them.

**Verified fix:** compile the network with the lane **open** by default (no `allow` restriction, so the full connectivity graph — including the internal junction connectors — includes the complete lane path end-to-end), then use `setAllowed`/`setDisallowed` at simulation start (t=0) to establish each scenario's actual initial permission state. Runtime permission changes made this way genuinely and reliably gate lane use going forward; the bug is specific to the load-time connectivity graph inside junctions, not to `setAllowed`'s general effectiveness.

## `setAllowed` only gates future entry, not existing occupants

**Calling `setAllowed`/`setDisallowed` on a lane does not eject, teleport, or otherwise disturb vehicles already present on that lane.** It only affects which vehicles are permitted to enter the lane from that point forward. Verified directly: snapshotting `traci.lane.getLastStepVehicleIDs()` immediately before and immediately after a permission-narrowing `setAllowed` call showed an identical vehicle count (e.g. 4 vehicles present both immediately before and immediately after) — those vehicles simply continued along their already-chosen path and drained off the lane naturally over the following ~20-30 seconds, rather than being forcibly removed.

## Hysteresis control and threshold sensitivity

A dynamic HSR controller reading upstream E2 lane-area occupancy and applying two-sided hysteresis (separate open/close thresholds plus independent hold times, to avoid rapid flapping) can recover most — not necessarily all — of the throughput/delay benefit of permanently opening the shoulder, while keeping it unused during off-peak periods (measured: ~88-90% of the always-open benefit recovered, with zero off-peak shoulder usage versus continuous all-day usage in the always-open case). Sensitivity to the open threshold is monotonic, and there is a real, verifiable failure mode: **if the open threshold is set above the bottleneck's actual peak occupancy, the controller never fires at all and the run degenerates exactly to the always-closed baseline** — not a subtle effect, but an exact match to the no-shoulder scenario's numbers.

## The bottleneck must be a genuine lane-count reduction, not a speed trick

Hard-shoulder running is meant to relieve an actual capacity constraint — a downstream reduction in the number of through lanes, with all upstream through lanes merging into fewer downstream ones. A uniform speed-limit reduction applied to an unchanged lane count does not exercise this scenario and understates or misrepresents what HSR is actually for; verify a `.con.xml`'s connection elements (or the compiled net's own `<connection>` elements) show a genuine many-to-one lane merge, not just a `speed` attribute change, before treating a network as a valid HSR test bed. See [[variable-speed-limits-and-e2-detectors]] for the related caveat that SUMO's default lane-drop merge model doesn't always reproduce a strong capacity drop under congestion — worth checking that your bottleneck genuinely oversaturates rather than assuming it will.

See the `implement-dynamic-hard-shoulder-running` skill for the full network-design, controller, and verification workflow.
