---
name: implement-dynamic-hard-shoulder-running
description: Use this skill when the user wants dynamic hard-shoulder running (temporary shoulder-lane activation) in SUMO — a TraCI controller that opens a normally-restricted shoulder lane to passenger vehicles under congestion via traci.lane.setAllowed, and closes it again once congestion clears, as opposed to a static/always-open/always-closed lane configuration. Covers the critical netconvert-connectivity requirement (compile the net with the shoulder open, then gate access at t=0 via setAllowed/setDisallowed per scenario), the occupancy-based hysteresis control-loop design, building a genuine lane-drop bottleneck the shoulder relieves, and verifying setAllowed's runtime semantics (it gates new lane entry only, not vehicles already present). Trigger on mentions of hard shoulder running, HSR, shoulder lane, dynamic lane use, temporary lane opening, or setAllowed/setDisallowed for lane access control.
---

# Implement Dynamic Hard-Shoulder Running

Runtime TraCI lane-permission control that opens a hard-shoulder lane (normally restricted to `emergency`/`authority` vClasses) to passenger cars when upstream congestion crosses a threshold, and closes it again once congestion clears — as opposed to `model-vclass-lane-permissions`' static, build-time-only allow/disallow, or `implement-variable-speed-limits`' speed-limit (not lane-access) control.

## The critical gotcha: compile the net with the shoulder OPEN, not closed

**A network compiled with the shoulder lane closed (`allow="emergency authority"` at netconvert time) cannot be reliably opened at runtime via `traci.lane.setAllowed`.** netconvert bakes the restriction into the *internal junction connector lanes*, and SUMO's load-time best-lanes/connectivity graph is not rebuilt in response to a later runtime permission change — vehicles can enter the shoulder approach lane but cannot route across the junction into the shoulder continuation, effectively trapping them.

**The fix: compile the network with the shoulder lane OPEN by default** (no `allow` restriction, so the connectivity graph includes the full shoulder path end-to-end), then establish each scenario's actual initial state via `traci.lane.setAllowed`/`setDisallowed` at simulation start (t=0):

```python
SHOULDER_LANES = ["m_0", "w_0"]  # every physical lane segment the shoulder spans
CLOSED_CLASSES = ["emergency", "authority"]
OPEN_CLASSES = ["passenger", "emergency", "authority"]

def set_shoulder(classes):
    for ln in SHOULDER_LANES:
        traci.lane.setAllowed(ln, classes)

# at t=0, before the step loop:
if mode == "open":
    set_shoulder(OPEN_CLASSES)
else:  # closed and dynamic both start closed
    set_shoulder(CLOSED_CLASSES)
```

Runtime `setAllowed` changes to an edge-lane's permissions genuinely gate lane *use* going forward (verified: closed=0 vehicles ever entered the shoulder, open=continuous flow, dynamic=confined exactly to logged open windows) — the bug is specifically about the load-time connectivity graph inside junctions, not about `setAllowed` itself being ineffective.

## Building the bottleneck the shoulder is meant to relieve

The shoulder only matters if there's a genuine capacity constraint to relieve. Build a **real lane-count reduction**, not a speed-limit zone — a downstream edge with fewer through lanes than the approach edge, with the connection file (`.con.xml`) explicitly merging every upstream through lane into the surviving downstream lane(s):

```xml
<!-- hsr.con.xml: both approach through lanes (m_1, m_2) merge into the single
     bottleneck through lane (w_1); shoulder-to-shoulder (m_0 -> w_0) unchanged -->
<connection from="m" to="w" fromLane="0" toLane="0"/>
<connection from="m" to="w" fromLane="1" toLane="1"/>
<connection from="m" to="w" fromLane="2" toLane="1"/>
```

A uniform speed reduction on the downstream edge is **not** an acceptable substitute — it doesn't exercise the actual capacity-constraint scenario hard-shoulder running is designed for, and per `variable-speed-limits-and-e2-detectors`, SUMO's default lane-drop merge model doesn't always reproduce a strong capacity drop, so verify the bottleneck genuinely oversaturates under your demand before trusting it.

## Detector placement

- **E2 lane-area detectors** on the through lanes just upstream of the merge point — the controller's occupancy input (`scripts/gen_detectors.py`).
- **E1 induction loop on the shoulder lane itself** (mid-bottleneck) — the primary verification instrument: confirms zero/continuous/windowed shoulder usage per scenario.
- **E1 induction loops at the bottleneck exit** (one per lane, including shoulder) — throughput/discharge measurement.
- **edgeData** on both edges — aggregate speed/timeLoss per scenario.

## Hysteresis controller design

Two-sided hysteresis with independent hold times prevents rapid open/close flapping: open when occupancy stays above `occ_open` for `hold_open` seconds; close when it stays below `occ_close` for `hold_close` seconds (`occ_close` should be meaningfully below `occ_open`). See `scripts/run_hsr.py` for the full implementation, including timestamped event logging (`OPEN`/`CLOSE`/`INIT_CLOSED`) to a file — essential for later cross-checking shoulder-detector activity against the controller's own decisions.

```bash
python3 scripts/run_hsr.py --mode dynamic --net net/hsr_open.net.xml --routes demand.rou.xml \
    --add detectors.add.xml --outdir outputs/dynamic --eventlog logs/events_dynamic.log \
    --seed 42 --occ-open 18 --hold-open 45 --occ-close 6 --hold-close 120
```

## Threshold sensitivity

Sweep the open/close thresholds (`scripts/sweep_thresholds.py` pattern: several `(occ_open, occ_close, hold_open, hold_close)` configs, each with its own saved outputs and event log) rather than asserting sensitivity from a single run. Verified behavior: sensitivity is monotonic in the open threshold, and **if the open threshold is set above the bottleneck's actual peak occupancy, the controller never fires at all and degenerates exactly to the always-closed baseline** — a real, run-backed failure mode, not just a theoretical one.

## Verifying `setAllowed`'s runtime semantics — new entries only, not existing occupants

**`traci.lane.setAllowed` gates future lane entry; it does not eject, teleport, or otherwise affect vehicles already on the lane when the permission changes.** Verified directly: at a logged close event, the count of vehicles on the shoulder immediately before and immediately after the `setAllowed` call was identical (e.g. 4 before, 4 after) — those vehicles drained naturally over the following ~20-30 seconds as they simply continued along their already-chosen route. To verify this yourself, snapshot `traci.lane.getLastStepVehicleIDs(shoulder_lane)` immediately before and after the `setAllowed` call at a close event, then keep sampling it for a short window afterward.

## Three-scenario comparison methodology

Run identical demand and seed across: (a) shoulder permanently closed, (b) shoulder permanently open, (c) dynamic controller. Compare via `analyze-simulation-outputs`-style metrics (mean speed, timeLoss, peak-window exit discharge from the E1 exit loops) — a working dynamic controller should recover most (not necessarily all) of scenario (b)'s benefit relative to (a), while the shoulder E1 detector shows zero flow outside the controller's own logged open windows.

## Gotchas

- **Compile the net with the shoulder OPEN, gate access via `setAllowed`/`setDisallowed` at t=0** — compiling closed and trying to open at runtime traps vehicles at the junction (see above).
- **Use a real lane-count-reduction bottleneck, not a speed-limit zone** — the latter doesn't exercise the actual capacity constraint the shoulder is meant to relieve, and is a scope deviation from what "hard shoulder running" actually models.
- **`setAllowed` doesn't affect vehicles already on the lane** — only gates new entries; don't expect an instant lane-clear on close.
- **An open threshold set above the bottleneck's actual peak occupancy makes the controller a permanent no-op** — verify your threshold against the bottleneck's measured occupancy range, not just a plausible-sounding number.
- **Don't report an untested "what if the bottleneck were designed differently" variant as a measured finding** — if you want a secondary comparison, actually build and run it with saved artifacts, or clearly label it as unverified speculation.

## Related

- `model-vclass-lane-permissions` — the static/build-time counterpart this skill extends into runtime control.
- `implement-variable-speed-limits` — the closest structural template (bottleneck construction, E2 detector instrumentation, hysteresis control-loop pattern), controlling speed rather than lane access.
- `implement-alinea-ramp-metering`, `implement-maxpressure-traci-controller` — hand-authored motorway plain-XML and general closed-loop TraCI control-loop patterns this skill builds on.
- `analyze-simulation-outputs` — general tripinfo/edgeData comparison methodology used for the three-scenario evaluation.
- [[dynamic-hard-shoulder-running-with-traci-lane-permissions]] — the underlying `setAllowed`/connectivity-graph mechanics and verified findings.
- `model-managed-lanes-with-dynamic-tolling-and-self-selection` — a case where this skill's `setAllowed` mechanism was deliberately avoided in favor of `traci.vehicle.setVehicleClass` against a net compiled with the restriction already in place, sidestepping this skill's junction-connectivity trap entirely rather than working around it with the open-then-gate-at-t=0 technique.
