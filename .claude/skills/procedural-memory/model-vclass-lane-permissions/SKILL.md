---
name: model-vclass-lane-permissions
description: Use this skill when the user wants to restrict specific lanes in SUMO to (or away from) a vehicle class — bike lanes, bus lanes, truck-restricted lanes, HOV lanes — via lane allow/disallow permissions, and/or wants to model bicycle demand (vClass="bicycle") alongside motor vehicles. Covers editing plain-XML .edg.xml lane children, recompiling with netconvert, verifying permissions took effect on the compiled net, generating mixed-vClass demand, and comparing outcomes across vClasses (e.g. car vs bicycle mode split). Trigger on mentions of bike lane, bus lane, HOV lane, lane restriction, vClass permissions, allow/disallow, or bicycle demand/routing.
---

# Model vClass Lane Permissions

Restricts specific lanes to (or away from) a vehicle class using SUMO's `allow`/`disallow` lane attributes — the mechanism behind bike lanes, bus lanes, truck bans, and HOV lanes — and models mixed-vClass demand (e.g. cars + bicycles) to measure the effect. This is SimSkill's only skill covering static, always-on lane-level vClass restrictions; contrast with `model-parking-with-rerouting` and `simulate-incident-rerouting`, whose `rerouter` elements change route *choice* dynamically rather than restrict a lane's legal traffic outright.

## Editing lane permissions

A `<lane>` child of an `<edge>` in plain-XML `.edg.xml` (or directly in a compiled `.net.xml`, though editing the source and recompiling is more maintainable) takes `allow` (whitelist) or `disallow` (blacklist) — never both on the same lane:

```xml
<edge id="A0B0" from="A0" to="B0" numLanes="2" speed="13.9">
    <lane index="0" allow="bicycle"/>
    <lane index="1" disallow="bicycle"/>
</edge>
```

Lane `index="0"` is the rightmost lane. A lane with no `allow`/`disallow` attribute keeps the network's/edge's default permissions (normally all vClasses). `scripts/build_lane_permission_variant.py` automates rewriting a base `.edg.xml`'s self-closing `<edge .../>` tags into open tags with explicit per-lane permission children for a selected set of edges (by explicit id list or regex), then recompiles with `netconvert`:

```bash
python scripts/build_lane_permission_variant.py \
    --node-file base.nod.xml --edge-file base.edg.xml \
    --edge-id-regex '^[A-F]0[A-F]0$' \
    --lane "0:allow=bicycle" --lane "1:disallow=bicycle" \
    --out-edge-file separated.edg.xml --out-net separated.net.xml
```

**Critical: do not pass the original network's `.con.xml`/`.tll.xml` alongside a lane-edited `.edg.xml`.** Those files hard-code lane-to-lane turn connections and TLS link indices for the *original* lane layout. When a lane's permitted classes change — especially when a lane is dropped to a single-vClass subset — the surviving general-traffic lane needs its turn connections regenerated, or routing fails with "no connection" errors for vehicles that can no longer use the restricted lane. Let `netconvert` regenerate connections and TLS logic from node+edge files alone (omit `--connection-files`/`--tllogic-files`); this is the single most common way a lane-permission variant silently breaks.

## Verifying the restriction took effect

Always inspect the *compiled* `.net.xml`, not just the source `.edg.xml` — `netconvert` can in principle alter lane layouts (e.g. via internal lane generation), so the compiled net is the ground truth for what SUMO will actually simulate:

```bash
grep -A2 '<edge id="A0B0"' separated.net.xml
```

Confirm the expected lane carries `allow="bicycle"` (or the intended vClass) and its counterpart carries `disallow`, and diff this against a MIXED/unrestricted variant of the same edge to confirm the two nets actually differ where intended. Also confirm `duarouter` routes every vehicle of the restricted vClass with zero errors against the restricted net (a route through a now-illegal lane assignment fails loudly, not silently) — run it without `--ignore-errors` so a real permission mismatch surfaces as a hard error rather than being silently dropped.

## Modeling bicycle demand

Bicycles are a first-class vClass (`vClass="bicycle"`) with meaningfully different dynamics than cars — define a distinct `vType`:

```xml
<vType id="bike_bicycle" vClass="bicycle" maxSpeed="5.5" width="0.65" length="1.8"/>
```

`randomTrips.py --vehicle-class bicycle --vtype bike_bicycle` (or manually tagging generated trips) produces bicycle trips; merge with car trips into one demand stream before routing so both vClasses are routed against the identical network and share the identical departure schedule across variants (only the network's permissions should differ between compared runs — same demand file, same seed).

## Comparing outcomes by vClass

`scripts/compare_by_vclass.py` reads one or more runs' `tripinfo` output, splits per-vehicle metrics by `vType`, and reports throughput, mean travel time, mean waiting time, mean time loss, and mean route length per vClass plus network-wide totals, with %-change from a baseline run:

```bash
python scripts/compare_by_vclass.py \
    --run mixed=outputs/mixed/tripinfo.xml \
    --run separated=outputs/separated/tripinfo.xml \
    --vtypes car_passenger,bike_bicycle \
    --out-csv outputs/comparison_table.csv
```

**Watch route length, not just travel time, when interpreting a restricted vClass's outcome.** A restricted lane can force a longer path (e.g. queued behind slower traffic sharing a merge, or routed differently at a junction), which can make raw travel time look worse even when the underlying per-meter speed genuinely improved — compute `routeLength / duration` per vClass if travel time and route length move in the same direction, to separate a real slowdown from a longer-but-faster route.

## Gotchas

- **`allow` and `disallow` are mutually exclusive on one lane** — set one or the other, never both; a lane with both is invalid/undefined.
- **Reusing the original `.con.xml`/`.tll.xml` against edited lane permissions breaks routing** (see above) — always let `netconvert` regenerate them from node+edge files.
- **A restricted vClass's worse raw travel time may be a route-length artifact, not a real slowdown** — check route length alongside travel time before concluding a restriction hurt that vClass's speed.
- **Verify on the compiled `.net.xml`, not the source `.edg.xml`** — the source is an editing convenience; the compiled net is what's actually simulated.
- **A permission edit that changes zero vehicles' routing behavior may mean the vClass simply wasn't present in demand on that edge** — confirm nonzero vehicles of the restricted vClass actually traverse the edited edges before concluding a restriction "had no effect."

## Related

- `create-grid-network` / any network skill for the base topology to apply lane permissions to.
- `generate-random-trips`, `convert-trips-to-routes` for building the mixed-vClass demand and routing it against each variant.
- `model-parking-with-rerouting`, `simulate-incident-rerouting` — SimSkill's *dynamic* route-choice skills (rerouter-based), as opposed to this skill's static, always-on lane restrictions.
- [[vehicle-class-lane-permissions]] — the underlying SUMO concepts (vClass system, allow/disallow semantics, the connection/TLS-regeneration requirement).
- `evaluate-neighborhood-traffic-calming-and-cut-through-displacement` — uses this skill's permission-editing mechanism to build a modal-filter traffic-calming intervention, and found it produces a selective (zero-cost-to-exempted-vClass) access-cost signature structurally different from a non-selective speed-limit intervention.
- `model-urban-freight-delivery-tours` — sweeps this skill's `disallow` mechanism as a truck-route-restriction coverage variable (with and without an exempt vClass), and documents a critical demand-generator gotcha: screening vehicle-class assignment by edge permission alone, rather than round-trip route feasibility, can fabricate a fictitious non-monotone "partial restrictions worse than complete restrictions" finding.
