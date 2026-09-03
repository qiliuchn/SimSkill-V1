---
name: quantify-opendrive-roundtrip-fidelity
description: Use this skill when the user wants to exchange a SUMO network with another tool (OpenDRIVE/.xodr for driving simulators and HD-map/AV pipelines, MATSim, dlr-navteq/shapefile) and needs to know what actually survives the round trip — geometry, lane permissions, connections, traffic-light programs, roundabout declarations — rather than assuming a clean export/import means a faithful network. Covers building a netconvert export/import sweep, an ID-agnostic geometric network-diff, a lossless plain-XML control to isolate genuine format loss from recompilation noise, behavioral validation (does simulated traffic actually behave differently on the round-tripped net), and repair recipes for the most common defects. Trigger on mentions of OpenDRIVE, .xodr, netconvert format conversion, MATSim network export, network round-trip fidelity, "does my network survive export to X", or interoperability with CARLA/esmini/VTD/HD-map tools.
related_skills:
  - create-grid-network
  - create-roundabout-network
  - load-osm-network
  - generate-random-trips
  - analyze-simulation-outputs
  - quantify-sumo-run-to-run-variability
related_skills_for_graph_view:
  - "[[create-grid-network]]"
  - "[[create-roundabout-network]]"
  - "[[load-osm-network]]"
  - "[[generate-random-trips]]"
  - "[[analyze-simulation-outputs]]"
  - "[[quantify-sumo-run-to-run-variability]]"
related_pages:
  - "[[opendrive-and-network-format-interoperability]]"
  - "[[openstreetmap]]"
  - "[[abstract-network-generation]]"
  - "[[sumo-command-line]]"
---

# Quantify OpenDRIVE / Network-Format Round-Trip Fidelity

Netconvert can export a SUMO network to OpenDRIVE, MATSim, or dlr-navteq and re-import
it, but a clean exit code and zero warnings say nothing about whether the round-tripped
network still behaves the same way in simulation. This skill establishes an export ->
sweep-import -> diff -> control -> behavioral-validate pipeline that answers that
question with numbers instead of assumption, and hands back concrete repair recipes.

## 1. Build source networks spanning feature richness

Use existing skills for the source networks and deliberately choose ones that stress
different features: `create-grid-network` (signalized, turn lanes — stresses tlLogic
programs), `create-roundabout-network` (stresses the `<roundabout>` element and
give-way link states), `load-osm-network` (curved geometry, mixed vClass permissions —
sidewalks/bike lanes, guessed signals, `right_before_left` junctions). Verify each
source network's own properties before converting anything (edge/lane/junction/tlLogic
counts, roundabout right-of-way) — you cannot measure what a conversion lost without
knowing what the original actually had.

## 2. Export is not where fidelity is decided — import is

```bash
netconvert --sumo-net-file net.net.xml --opendrive-output net.xodr
netconvert --opendrive-files net.xodr -o net_rt.net.xml --opendrive.import-all-lanes
```

Verified: sweeping export-side options (`--opendrive-output.straight-threshold`,
`--junctions.internal-link-detail`, `--opendrive-output.lefthand-left`,
`--opendrive-output.shape-match-dist`) changed the `.xodr` file's byte content and
internal geometry encoding (line vs `paramPoly3` segment counts) but produced **no
measurable change in round-trip fidelity** on any test network. **The .xodr itself does
carry lane-type (sidewalk/biking/restricted) and `<signal>` elements** — inspect the
exported file before assuming information was never captured; the loss usually happens
on re-import.

**`--opendrive.import-all-lanes` is the single decisive import option.** Without it,
netconvert drops every non-`driving` lane and any edge left with zero lanes disappears
entirely: verified on a 433-edge mixed-vClass network, default import kept only 181
edges (58% dropped, edge-match rate 0.217) while `--opendrive.import-all-lanes` recovered
432/433 edges (0.998 match). The dropped-edge count is diagnosable directly from
netconvert's own stderr: `Edge '%' has no lanes.` warnings occurred exactly once per
dropped edge (252 warnings for 252 dropped edges in one verified run) — grep for this
message as a decisive signal you forgot the flag.

Other import options swept and found to have **no meaningful effect** on a network with
correctly-placed signals and uniform lane widths: `--opendrive.curve-resolution`,
`--opendrive.advance-stopline`, `--opendrive.ignore-widths`, `--opendrive.lane-shapes`,
`--opendrive.signal-groups`, `--junctions.join`, `--tls.guess-signals`.
**`--opendrive.internal-shapes` and `--geometry.remove` are actively harmful** on a
real-world OpenDRIVE import — the former produced 227 new warnings and drove edge-length
accuracy to zero, the latter dropped the edge-match rate further. Do not add either as a
default.

## 3. The network-diff: geometric ID matching, not name matching

Round-tripped edges/junctions get **new IDs** — comparison must match by geometry, not
name. `scripts/netdiff.py` matches junctions by iterated-median residual translation
(robust to a systematic origin shift) followed by greedy nearest-neighbor 1:1 matching,
then matches edges by midpoint+heading. Self-test it against a network compared to
itself before trusting any diff — every reported delta must be exactly zero.

Report, per network pair: edge/lane/junction/connection counts; junction-type histogram
(`priority`/`traffic_light`/`right_before_left`/`zipper`/`dead_end`); total lane-km and
the per-edge length-difference distribution; junction position offsets after matching;
speed limits; per-lane vClass allow/disallow (aggregate into lane-km by functional role:
car-usable, pedestrian-only, bicycle-only, mixed, blocked); edge priority; street names;
`<roundabout>` declarations; and, per matched `tlLogic`, phase count, cycle length, and
**phase-string identity** (not just phase count — see below).

**Critical gotcha: do not undo `<location netOffset>` when comparing.** netconvert's
OpenDRIVE export writes the SUMO net's already-internally-offset coordinates into the
`.xodr`, and re-import emits `netOffset="0,0"`. Subtracting the original net's offset
before matching introduces a spurious translation (verified: 150 m on one network) that
makes a perfect round-trip look broken. Match geometrically in absolute compiled
coordinates on both sides.

## 4. Two things a clean report can still be hiding

- **Signal program regeneration is universal and silent.** Every tested network's
  `tlLogic` **count** survived the round trip (9->9, 4->4), but **zero phase strings
  matched** — a hand-authored 8-phase plan with protected lefts (33/3/6/3/33/3/6/3s)
  became a generic 2-phase plan (42/3/42/3s) with no warning at all. **A matching cycle
  length (90s->90s here) is very likely a netconvert-default coincidence, not evidence of
  preservation** — check the actual phase strings before reporting "signals preserved."
- **`<roundabout>` declarations are lost even when the give-way link states happen to
  survive.** The circulating/entry `M`/`m` states can look correct while the
  `<roundabout>` element itself (which some SUMO tools and roundabout-aware routing rely
  on) is simply gone, with zero warnings.

**General rule: netconvert silence is not evidence of fidelity.** Both losses above
produced zero export-time and zero import-time warnings. Diff, don't just watch the log.

## 5. Controls: separate genuine format loss from netconvert noise

Run a **plain-XML round trip** (`--plain-output-prefix` then recompile from the
`.nod/.edg/.con/.tll` files, **omitting the auto-written `.typ.xml`**) as a near-lossless
control on the same networks. Verified: this reproduces every network **exactly** —
edges, lanes, lane-km, speeds, and all `tlLogic` phase strings identical — so any
deficit measured against OpenDRIVE (or another format) is **genuine format information
loss, not recompilation artifact.**

**Gotcha: feeding the auto-written `.typ.xml` back in re-triggers sidewalk/bike-lane
guessing** (`sidewalkWidth`/`bikeLaneWidth` re-derive new pedestrian infrastructure that
wasn't in the original edge attributes), degrading an otherwise-perfect plain-XML
control. Recompile from `.nod/.edg/.con/.tll` only.

Compare the format landscape while you're at it — verified results across three formats:
MATSim (`--matsim-output`/`--matsim-files`) preserved geometry/lengths/speeds but lost
**every** `tlLogic` (9->0) and invented extra connections (+48, re-guessed turns);
dlr-navteq preserved topology and signals well on a geo-referenced real-world network
(0.005 m mean junction offset, all TLS present) but **catastrophically miscomputed a
synthetic, non-geo-referenced network** (18.5 -> 2368 lane-km, 0/N junctions matched) by
reprojecting its cartesian coordinates as if they were geographic — only use dlr-navteq
on a network built from real-world coordinates. Shapefile export does not exist in
netconvert (import-only, verify with `--help` before assuming otherwise); Amitran is
export-only. **Use plain XML for any SUMO-to-SUMO exchange.**

## 6. Behavioral validation: geometric edge-ID remapping, not seed regeneration

A round-tripped network has entirely new edge IDs, so demand generated on the original
can't be loaded directly onto it. Generate trips **once per replication** on the
original network (`randomTrips.py --seed <rep>`), then **translate the resulting route
file through the same geometric edge map `netdiff.py` already computed**
(`scripts/mapdemand.py`) onto every other arm — this guarantees every arm serves the
*same geographic OD pairs* despite total ID renaming, which seed-regeneration on each
network cannot guarantee. Report the map rate (fraction of trips whose edges all
resolved) per arm; a low map rate on a lossy arm is itself a finding, not just a
methodology footnote — one verified case had only 94/433 mappable edges after a default
(non-all-lanes) import, causing 81% of demand to become unroutable.

Use paired CRN replication (same `sumo --seed` across arms per replication number,
`quantify-sumo-run-to-run-variability`'s design) and report paired 95% CIs, not just
means — with route lengths reported alongside travel time/delay so a genuine behavioral
change can be distinguished from routing through a physically different (e.g. resampled
curve) network.

**Attribute every divergence to a specific structural cause found in step 4, and verify
the attribution by removing that cause.** Verified case: a round-tripped grid network
showed -6.7% travel time / -14.3% delay versus the original at identical route lengths —
transplanting the *original* signal programs back onto the round-tripped net
(`scripts/repair_tls.py`) removed the effect entirely (-6.7% -> -0.1%, no longer
significant), proving the simplified regenerated signal plan was the sole cause. A
second verified case at high demand showed a **spurious +115% completed-trip inflation**
on a round-tripped mixed-vClass network; traced to 55 of 1250 vehicles (4.4%) using 220
edge traversals over segments that had been pedestrian/bicycle-only in the original but
became vehicle-usable after a default OpenDRIVE import — i.e. **a lossy import can make a
network look like it performs *better*, not just worse**, by silently opening shortcuts
that shouldn't exist. Applying a naive permission repair over-corrected in the opposite
direction; the residual divergence traced to separately-lost connections and
`right_before_left`->`priority` junction-type conversions.

## 7. Repair recipes for the four most common defects

1. **Signal programs reset to netconvert defaults** — `scripts/repair_tls.py` transplants
   the original `tlLogic` onto the round-tripped net by deriving the controlled-link
   index permutation from the (fromEdge, fromLane, toEdge, toLane) geometric edge map,
   then loads it via `--additional-files`. Verified 100% link coverage on every tested
   intersection.
2. **Sidewalks/bike lanes dropped, or drivable roads gaining traffic they shouldn't have**
   — always import with `--opendrive.import-all-lanes`, then run
   `scripts/repair_permissions.py`, which re-applies the original per-lane
   allow/disallow via a netconvert edge patch (`--edge-files`) keyed on the same
   geometric map. Verified 432/433 edges correctly re-patched.
3. **Missing connections** (turn restrictions silently dropped, concentrated at
   signalized junctions) — not automated here; diagnose via `netdiff.py`'s connection
   delta plus the `Could not find fromEdge representation of '%' in connection '%'`
   warning, then hand-author a `.con.xml` patch and reload with `--connection-files`.
4. **Duplicated/unjoined fringe junctions and degraded junction-type** (`right_before_left`
   silently becoming `priority`) — every fringe edge gains a duplicate `*.end` node on
   OpenDRIVE import; `--junctions.join` on import does **not** fix this (verified no
   score change, sometimes worse in combination). Fix by re-declaring node types via a
   `.nod.xml` patch keyed on the geometric map.
5. **Edge priority and street names** are simply not representable in OpenDRIVE and are
   unrecoverable from the `.xodr` alone — restore via an `.edg.xml` patch from the
   original, same mechanism as recipe 2, if these attributes matter downstream.

## Decision table: is an OpenDRIVE exchange safe?

| situation | verdict |
|---|---|
| Unsignalized, driving-lanes-only, single vClass (freeway, synthetic grid without signals) | **Safe** — edges/lanes/connections/lane-km/speeds/lengths were bit-exact |
| Traffic signals whose programs matter (coordination, protected turns, offsets) | **Unsafe without repair** — programs are always regenerated; apply `repair_tls.py` or re-author |
| Multimodal (sidewalks/bike/bus lanes, vClass restrictions) | **Unsafe without `--opendrive.import-all-lanes` + `repair_permissions.py`** — otherwise ~58% of edges vanish, or the reverse: blocked infrastructure opens up and inflates throughput |
| Real-world network at or near capacity | **Unsafe** — behavioral divergence grows monotonically with demand level |
| Real-world network, free-flow, geometry-only questions | **Acceptable** with `--opendrive.import-all-lanes` — sub-2m junction offsets, exact speeds, near-exact lengths |
| Turn restrictions / prohibited movements load-bearing | **Unsafe** — connections are silently lost with no reliable auto-repair |
| Roundabouts | **Caution** — the `<roundabout>` element is always lost even if link states happen to survive; re-declare it |
| SUMO-to-SUMO exchange | **Use plain XML** (recompile without the auto-written `.typ.xml`) — verified exactly lossless on synthetic networks; on a real OSM import, topology/signals still survive exactly but ~14% of edge lengths can shift by 1-19 m (see `imported-network-defect-classes-and-traffic-impact`) |
| Geo-referenced network needing a compact interchange with topology+signals present | dlr-navteq performed best of the non-plain formats, but never use it on a non-geo-referenced network |
| Considering MATSim but need signals preserved | **No** — MATSim loses every `tlLogic` |

## Related

- `create-grid-network`, `create-roundabout-network`, `load-osm-network` — source
  networks spanning feature richness for the fidelity sweep.
- `generate-random-trips`, `analyze-simulation-outputs` — demand generation and output
  parsing reused for behavioral validation.
- `quantify-sumo-run-to-run-variability` — the CRN/paired-replication design behind the
  behavioral comparison's confidence intervals.
- [[opendrive-and-network-format-interoperability]] — the full verified fidelity table,
  behavioral findings, and decision table this skill implements.
- [[openstreetmap]], [[abstract-network-generation]], [[sumo-command-line]] — network
  construction and shared netconvert option conventions.
