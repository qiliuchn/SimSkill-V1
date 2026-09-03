---
name: form-platoons-with-simpla
description: Use this skill when the user wants to model connected/automated vehicle (CAV) platooning in SUMO — cooperative vehicles dynamically forming platoons and switching to the CACC car-following model with reduced inter-vehicle gaps — using SUMO's simpla plugin. Covers locating and importing simpla, the platoon-role vType mapping (default/leader/follower/catchup/catchupFollower), CACC/ACC parameters, join/split thresholds, verifying genuine platoon formation and gap-tightening from live simulation (not configuration alone), per-lane occupancy analysis, and forced-perturbation string-stability testing. Trigger on mentions of platooning, simpla, CACC, connected automated vehicles, or string stability.
related_skills:
  - run-simulation
  - implement-alinea-ramp-metering
  - implement-variable-speed-limits
  - get-vehicles-state
  - measure-av-penetration-effect-on-bottleneck-capacity
related_skills_for_graph_view:
  - "[[run-simulation]]"
  - "[[implement-alinea-ramp-metering]]"
  - "[[implement-variable-speed-limits]]"
  - "[[get-vehicles-state]]"
  - "[[measure-av-penetration-effect-on-bottleneck-capacity]]"
related_pages:
  - "[[simpla-platooning]]"
---

# Form Platoons with simpla

Models connected/automated vehicle (CAV) platooning in SUMO using `simpla`, SUMO's dedicated platooning plugin: cooperative vehicles dynamically form platoons and switch to the CACC (Cooperative Adaptive Cruise Control) car-following model with tightened inter-vehicle gaps. This is SimSkill's only skill covering cooperative multi-vehicle control — every other closed-loop TraCI controller (GLOSA, max-pressure, TSP) advises or controls a single vehicle or signal, not a dynamically-forming group of vehicles.

## Locating and loading simpla

`simpla` ships under `$SUMO_HOME/tools/simpla`, not as a pip package — add `$SUMO_HOME/tools` to `sys.path` (the same path `traci` itself needs) before importing it. It must be loaded **after** the TraCI connection is established, not before:

```python
import traci
traci.start([...])
import simpla
simpla.load("simpla.cfg.xml")
# simpla registers itself as a step listener; platoon management runs automatically on every traci.simulationStep()
```

## The simpla configuration file

See `templates/simpla.cfg.xml` and `templates/vtypes.map` for a complete, verified working example. `vTypeMapFile` maps one base vType to its four platoon-role vTypes (`orig:leader:follower:catchup:catchupFollower`); `vehicleSelectors` restricts management to vType ids matching a substring (e.g. only vehicles whose id contains a "connected" marker are ever platooned — everything else is left alone).

```xml
<vTypeMapFile value="vtypes.map"/>
<vehicleSelectors value="pcav"/>
<maxVehicles value="8"/>
<useHeadway value="true"/>
<maxPlatoonGap value="45.0"/>       <!-- distance-based join fallback -->
<maxPlatoonHeadway value="2.5"/>    <!-- time-based join threshold (s); the primary lever -->
<catchupDist value="100.0"/>
<catchupHeadway value="6.0"/>
<platoonSplitTime value="3.0"/>
```

Give the follower/catchupFollower role vTypes `carFollowModel="CACC"` with a short `tau` (e.g. 0.6s), and leader/catchup roles `carFollowModel="ACC"` with a longer `tau` (e.g. 1.4s) — the shorter CACC gap is what filtering/platooning benefit depends on physically.

**On a fast multi-lane freeway, tight join thresholds can leave nearly all managed vehicles stuck in `catchup` (ACC) mode, never actually becoming `follower` (CACC)** — a 1.5s `maxPlatoonHeadway` left ~99% of vehicles in catchup in one verified build; loosening it to 2.5s let vehicles a few seconds apart join as genuine CACC followers, engaging the tight-gap behavior the scenario is meant to demonstrate. Tune and verify this empirically (see below), don't assume a documented default threshold suits a given speed/geometry.

## Verifying genuine platoon formation and gap-tightening

**Don't trust the configuration alone — verify platoons actually form and gaps actually tighten from live simulation data.** `simpla` exposes its own live API for the first check:

```python
leaders = simpla.getPlatoonLeaderIDList()
for lid in leaders:
    info = simpla.getPlatoonInfo(simpla.getPlatoonID(lid))
    size = len(info["members"])  # a "platoon" of size 1 is not really a platoon
```

`scripts/run_platoon.py` samples this every simulated second and logs platoon count/mean size to a CSV — direct, empirical proof of formation independent of the config. For gap-tightening, parse FCD `posLat`-adjacent fields (`x`,`speed`,`lane`) for consecutive same-lane vehicles and compute realized time-headway/space-gap: a genuinely working CACC platoon should show sub-second headways that would be physically impossible under the baseline's ACC-only `tau`, concentrated specifically among platoon-role vTypes (`*_follower`/`*_catchupFollower`) — not spread evenly across all vehicles, which would suggest a confound rather than genuine platooning.

## Demand density matters — don't force an artificial benefit

**Keep demand within whatever range the scenario specifies, and don't quietly oversaturate a bottleneck to manufacture a throughput story.** A platooning benefit demonstrated only under artificial demand well above a realistic range is not evidence the effect holds at realistic demand — verify the claimed benefit persists (even if it shrinks) at an in-spec, non-oversaturated demand level before reporting a throughput/travel-time finding. If a network's single entry point does saturate at the demand level actually specified, that's worth reporting explicitly (with the real `departDelay` figures), not something to route around by inflating demand further.

## Per-lane occupancy

Compute vehicle-time-weighted occupancy fraction per lane, split by role (platoon follower/catchupFollower vs. non-connected), directly from FCD. Platoon followers can concentrate disproportionately in one lane (e.g. the middle lane on a 3-lane road) under mixed (partial) penetration — worth checking explicitly rather than assuming uniform lane use, since it can affect how representative a single-lane-focused analysis is.

## String-stability verification

If natural cruising traffic shows negligible speed variance (nothing to measure disturbance propagation against), add a forced-perturbation test: make a platoon leader brake sharply for a few seconds mid-corridor, then track the speed-deviation amplitude at each successive follower down the chain. **String stability** means the disturbance amplitude *decreases* follower-to-follower (damped); *increasing* amplitude down the chain would indicate string instability — a real risk with poorly-tuned CACC gains, worth checking rather than assuming CACC is automatically stable.

## What a well-configured platooning scenario shows

Measured on a 3-lane, 3km freeway at 1800 veh/h/lane (within realistic capacity), full CAV penetration vs. a non-platooned baseline: mean travel time -11%, timeLoss -65%, mainline throughput +4% (consistent across multiple demand seeds), mean speed +12.5%. The benefit persisted, scaled down, at an undersaturated 1200 veh/h/lane (+1.6% throughput, still -9% travel time) — confirming it wasn't an artifact of demand oversaturation. Platoon followers achieved genuinely sub-second headways impossible under ACC alone. At 50% mixed penetration, platoon followers concentrated ~61% in the middle lane (vs. 33% uniform). A forced leader-braking perturbation damped from a 15+ m/s speed dip at the leader to near-zero by the third follower — confirming string stability under this configuration.

## Gotchas

- **`simpla` must be imported and loaded after `traci.start()`**, not before.
- **Tight join thresholds can leave most managed vehicles stuck in ACC/catchup mode rather than becoming genuine CACC followers** — verify the actual role distribution, don't assume the configured thresholds work as intended.
- **A throughput benefit demonstrated only under artificial demand oversaturation isn't evidence it holds at realistic demand** — always check an in-spec, non-oversaturated case.
- **Absolute output paths for additional-file-declared outputs avoid SUMO re-rooting them under the additional file's own directory** — a real gotcha when scripting multiple runs into different output directories.

## Related

- `run-simulation` — the general TraCI step-loop pattern this skill's runner specializes for simpla's step-listener registration.
- `implement-alinea-ramp-metering`, `implement-variable-speed-limits` — SimSkill's other freeway-scenario skills, including the capacity-drop-verification discipline (verify a real bottleneck exists/doesn't before attributing a throughput result to the intervention under study).
- `get-vehicles-state` — the TraCI vehicle-state-reading patterns this skill's FCD/gap-tightening analysis builds on.
- [[simpla-platooning]] — the underlying simpla API/config schema, CACC/ACC mechanics, and the verified throughput/lane-occupancy/string-stability findings.
- `measure-av-penetration-effect-on-bottleneck-capacity` — measures a full capacity-vs-penetration curve (this skill demonstrates platooning at a single fixed configuration) and found SUMO's CACC can silently ignore its own configured parameters behind a non-CACC leader — worth checking before trusting this skill's CACC gap-tightening numbers in a mixed (non-platooned) fleet.
