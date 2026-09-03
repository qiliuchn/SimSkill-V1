---
name: model-dedicated-bicycle-lane-infrastructure
description: Use this skill when the user wants to compare a dedicated bicycle lane against mixed car/bicycle traffic in SUMO, or wants to quantify how rising bicycle mode share affects car and bike performance on a corridor. Covers building two netconvert-compiled lane-permission variants (a single mixed lane vs. a bike-only lane + car-only lane), generating a mode-share-swept demand sweep with identical seed/schedule across variants, running the sweep, and splitting tripinfo metrics by vClass. Trigger on mentions of bike lane vs mixed traffic, bicycle infrastructure, bicycle mode share, or cyclist/car interaction on a shared lane.
---

# Model Dedicated Bicycle-Lane Infrastructure

Builds two netconvert-compiled infrastructure variants of an identical corridor — **mixed traffic** (one lane shared by cars and bicycles) vs. **dedicated** (a bicycle-only lane alongside a car-only lane) — and quantifies how each variant's car and bicycle performance respond to a swept bicycle mode share. This is a specific application of `model-vclass-lane-permissions`'s allow/disallow mechanism to the bike-lane use case, adding the mode-share sweep, the "same route file drives both nets" demand-identity trick, and per-vClass metric splitting.

## Building the two variants

Same node file, one edge file per variant, differing only in per-lane `allow`/`disallow`:

```xml
<!-- mixed.edg.xml: one lane, both vClasses share it -->
<edge id="E0" from="A" to="B" numLanes="1" speed="13.9">
    <lane index="0" allow="passenger bicycle"/>
</edge>

<!-- dedicated.edg.xml: two lanes, cleanly separated -->
<edge id="E0" from="A" to="B" numLanes="2" speed="13.9">
    <lane index="0" allow="bicycle"/>      <!-- bike-only -->
    <lane index="1" disallow="bicycle"/>   <!-- car lane, bikes excluded -->
</edge>
```

Compile each with `netconvert` from node+edge files alone (no `.con.xml` — see `model-vclass-lane-permissions`'s connection-regeneration gotcha). Because SUMO auto-assigns each vClass to its only legal lane, the *same* route file (`<route edges="E0"/>`) works unmodified on both compiled nets — this is what makes the demand-identity trick below possible.

**Always verify permissions on the compiled `.net.xml`, not the source `.edg.xml`**: `grep -A3 '<edge id="E0"' mixed.net.xml` should show `allow="passenger bicycle"` on the single lane; the same grep on `dedicated.net.xml` should show one lane `allow="bicycle"` and the other `disallow="bicycle"`. See bundled `NETCONVERT_LANE_PERMISSION_NOTE.md`-style documentation pattern in a run's own outputs for a worked example.

## Sweeping bicycle mode share with identical demand across variants

`scripts/gen_demand.py --total 200 --fraction 0.20 --seed 42 --out demand_bike20.rou.xml` generates ONE route file per mode-share level: a fixed total trip count and fixed departure schedule (identical across every level), with bicycle vs. car assignment drawn from a seeded RNG so the specific vehicles chosen as bikes are deterministic and reproducible. **The critical design choice: this single route file is then run against BOTH infrastructure variants with the same `--seed`** — demand and departure order are therefore provably identical between the mixed and dedicated runs at a given level; only the network's lane permissions differ. Never regenerate demand separately per variant, or a performance difference could be a demand artifact rather than a genuine infrastructure effect.

`scripts/run_sweep.sh` runs the full 2-variant × N-level sweep (writes one `.sumocfg` per combination, `time-to-teleport=-1` to avoid masking real congestion with teleports, and reports the tripinfo record count per run as a quick throughput sanity check).

## Analyzing: split by vClass, check route length

`scripts/analyze_by_mode_share.py` parses every run's raw tripinfo directly, splitting records by `vType` into car vs. bike, and computes per vClass/variant/level: throughput, mean travel time, mean time loss, mean speed (`mean(routeLength/duration)` per vehicle, not `mean(routeLength)/mean(duration)` — these differ when trip counts/lengths vary slightly), and mean route length. It writes a comparison table (CSV+markdown) and a two-panel plot of car travel time and time loss vs. bicycle mode share, one line per variant.

**Always check mean route length alongside mean travel time, per vClass** (same gotcha as `model-vclass-lane-permissions`): if route length differs between variants, a travel-time difference could be a routing artifact rather than a genuine speed/congestion effect. On a single-edge corridor with one route string valid on both nets, route length is normally identical by construction — but verify it directly rather than assuming.

## What was verified in one real test

On a 2km single-lane-per-direction corridor, 200 trips/level, 5%/20%/40% bicycle share: in **mixed** traffic, car mean travel time rose monotonically with bike share (319.9s → 397.2s → 411.1s) as slower bikes held cars behind them on the shared, no-overtake lane; car time loss rose correspondingly (168.6s → 245.2s → 258.4s). With a **dedicated** bike lane, car travel time stayed essentially flat and independent of bike share (173.3s / 173.2s / 174.2s). At 40% bike share the car-delay gap between variants was 236.9s mean travel time (2.36x) and 237.0s mean time loss (~12x) — confirmed by independently re-parsing the raw tripinfo files.

**Notable nuance, worth checking in any similar study**: bicycles themselves gained only modestly from the dedicated lane (~0.6-1.5% faster travel time) — since the bike is the slow pace-setter in mixed traffic, it is barely impeded by cars queued behind it. The large win from separation was almost entirely a **car** benefit, not a bicycle benefit. Don't assume separation helps both modes equally; measure both sides.

## Gotchas

- **Don't reuse `.con.xml`/`.tll.xml` across lane-permission variants** — let `netconvert` regenerate connections from node+edge files (see `model-vclass-lane-permissions`).
- **Verify lane permissions on the compiled net, not the source edge file.**
- **Generate demand once per mode-share level and run it against both variants with the same seed** — never regenerate per-variant demand, or a result could be confounded by a demand difference instead of the infrastructure change.
- **Use `mean(routeLength/duration)` per vehicle for mean speed, not `mean(routeLength)/mean(duration)`** — they diverge when durations vary across vehicles in the sample.
- **Check route length didn't drift between variants** before attributing a travel-time gap entirely to congestion/delay.
- **The dedicated lane's benefit may be asymmetric between vClasses** — report both cars' and bicycles' outcomes, not just the mode you expect to benefit.

## Related

- `model-vclass-lane-permissions` — the underlying allow/disallow mechanism and its `build_lane_permission_variant.py` / `compare_by_vclass.py` scripts (this skill's demand-identity-sweep and per-level-shared-route-file pattern are specific refinements for a mode-share study).
- `generate-random-trips`, `convert-trips-to-routes` — alternative demand-generation path for non-single-edge corridors.
- `analyze-simulation-outputs` — general tripinfo/summary comparison, for studies not requiring a per-vClass split.
- [[dedicated-bicycle-lanes-and-mode-share]] — the underlying SUMO concepts and verified findings.
