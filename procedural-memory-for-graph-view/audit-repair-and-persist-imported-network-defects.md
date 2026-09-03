---
name: audit-repair-and-persist-imported-network-defects
description: Use this skill when a SUMO network built from imported data (OpenStreetMap, OpenDRIVE, shapefile, VISUM) needs a quality audit, targeted repair, or a repair that must survive a later re-import of the source data. Covers the QA checks that actually find defects (strongly-connected-component / directed reachability, no-conflict guessed signals, shared through+left lanes, junction-join refusals) versus the ones that mislead, repair via plain-XML patch files and netconvert options rather than editing the compiled net, per-fix verification in the compiled network, an ID-keyed patch spec that reapplies after upstream map edits, and quantifying which defects actually bias simulated traffic versus which are cosmetic. Trigger on mentions of network QA, netcheck.py, netdiff.py, network defects, "is my imported network any good", disconnected/unreachable edges, unroutable trips after import, junctions that should be joined, guessed traffic signals, missing turn lanes, plain-XML round trip, or reapplying a network fix after re-downloading OSM.
related_skills:
  - load-osm-network
  - quantify-opendrive-roundtrip-fidelity
  - generate-random-trips
  - calibrate-demand-with-routesampler
  - validate-congested-scenario-results-against-teleport-artifacts
  - analyze-simulation-outputs
  - extract-subnetwork-scenario-with-boundary-demand
related_skills_for_graph_view:
  - "[[load-osm-network]]"
  - "[[quantify-opendrive-roundtrip-fidelity]]"
  - "[[generate-random-trips]]"
  - "[[calibrate-demand-with-routesampler]]"
  - "[[validate-congested-scenario-results-against-teleport-artifacts]]"
  - "[[analyze-simulation-outputs]]"
  - "[[extract-subnetwork-scenario-with-boundary-demand]]"
---

# Audit, Repair and Persist Imported-Network Defects

An imported network compiles with "Success." and a page of warnings, and none of that tells
you whether the network is usable. This skill establishes which QA checks find real defects,
how to repair them so the repair survives a re-import, and how to tell a defect that biases
results from one that is cosmetic.

Everything below was measured on a live 1.51 km² OpenStreetMap import of Boston
(543 edges / 58.3 lane-km / 61 signals). Numbers in **bold** are verified, not assumed.

## 1. The audit: run these five checks, skip the rest

`scripts/audit_network.py <net.xml> [--log build.log] [--json out.json]` runs the whole
inventory. The individual findings that justify each check:

### 1.1 Directed reachability / strongly-connected components — by far the highest-value check

**`netcheck.py <net>` with no options is actively misleading.** Its default component analysis
is undirected. On the test network it reported **531/543 edges = 97.79 % "connected"** while
only **376/543 = 69.2 %** of edges were mutually reachable and **50.4 % of lane-km** sat
outside the largest strongly-connected component.

Use the directed modes, or compute the SCC:

```bash
python $SUMO_HOME/tools/net/netcheck.py net.net.xml -s <a-central-edge>   # reachable FROM
python $SUMO_HOME/tools/net/netcheck.py net.net.xml -d <a-central-edge>   # can REACH
```

`patchlib.connectivity(net)` computes it directly and classifies the damage into the three
kinds that behave differently (its counts were validated to agree **exactly** with
`netcheck.py -s`/`-d`):

| class | meaning | routing consequence |
| --- | --- | --- |
| **trap** (`fwd − main`) | enterable, no way back | `trap → anywhere-in-core` is unroutable |
| **unreachable** (`bwd − main`) | can exit to the core, cannot be entered | `core → unreachable` is unroutable |
| **severed** (neither) | fully cut off | unroutable in both directions |

On a bbox-cut OSM extract the biggest offenders are the **truncated limited-access facility**
(freeway mainline + ramps whose continuation lies outside the box — the 4 longest severed
edges were 772/703/514/484 m of motorway) and **one-way enclaves** (a 42-edge district
vehicles could drive out of but never into). `--remove-edges.isolated` does *not* catch
either: it only removes fully-isolated edges.

### 1.2 The unroutable-rate probe — and the demand generator matters more than the network

Run the routability probe **with the demand generator you will actually use**. Verified on the
same defective network, 10 seeds × 2000 trips:

| generator | unroutable on raw import | unroutable after repair |
| --- | --- | --- |
| `randomTrips.py` (defaults) | **0 (0.00 %)** | 0 |
| independent lane-km-weighted OD sampling (od2trips-style) | **11 243 (56.22 %)** | **0 (0.00 %)** |

**`randomTrips.py` hides connectivity defects completely** — its source/sink samplers avoid
no-successor origins and no-predecessor destinations, and in 20 000 trips it never once
generated an impossible OD pair. An OD matrix, a `routesampler` calibration, or any
zone-based demand samples origin and destination independently and loses **56 %** of the
demand on the same network. `scripts/od_routability_probe.py` runs the independent-OD version.

### 1.3 No-conflict guessed signals

A `tlLogic` whose **green set is identical in every phase** resolves no conflict at all — its
only effect is an all-red interruption each cycle. `--tls.guess-signals` produces these on
nodes with no opposing movement. **4 of 61 signals** were like this (one controlling a
*single* link), each destroying **8 s of every 90 s cycle = 8.9 % of capacity for zero safety
benefit**, and **netconvert emitted no warning for any of them**.
`patchlib.noconflict_signals(net)` finds them.

### 1.4 Shared through + left lane on multi-lane approaches

`scripts/find_turnlane_defects.py <net> [out.json]` finds approaches inside the routable core
with ≥2 lanes where one lane serves both a `l`/`L` and an `s` movement. **47 found; netconvert
emitted only 1 `Minor green ... left-turn lane` warning in the whole log, and that warning was
on an edge outside the routable core (not one of the 47)** — so the warning is not even a
useful screen for this defect class; don't rely on netconvert's own log to find it.

### 1.5 Grep the netconvert log for three patterns only

Of 112 warning lines, **65 were public-transport-relation removals and unparseable OSM tag
values** — expected noise for a passenger-car import. Warning *count* is not a defect score.
Grep only for:

```bash
grep -E "Not joining junctions|Reducing junction cluster|Minor green.*left-turn lane" build.log
```

**Checks that produce false positives:** "default speed" heuristics keyed on 13.89 m/s —
460/543 edges sat at 11.18 m/s, which is Boston's *real* 25 mph default, not a guess. Compare
against the jurisdiction's actual default, or skip the check.

## 2. Repair: plain-XML round trip, and the six rules that make patches actually apply

```bash
netconvert -s base.net.xml --plain-output-prefix plain/base
# edit nothing; add small patch files / options; recompile
netconvert --node-files plain/base.nod.xml,patch.nod.xml \
           --edge-files plain/base.edg.xml,patch.edg.xml \
           --connection-files plain/base.con.xml,patch.con.xml \
           --tllogic-files plain/base.tll.xml -o repaired.net.xml
```

**Establish the noise floor first.** Recompile with *zero* edits as a lossless control. On a
real OSM network this is **not** bit-exact (correcting `quantify-opendrive-roundtrip-fidelity`,
whose "exactly lossless" claim came from synthetic networks): counts, lane counts, speeds and
**all tlLogic phase strings** were identical, but **75/543 edges changed length** (mean 1.20 m,
max 18.72 m) for a net **+0.018 % lane-km**, and 10/1246 connections got a `dir`/`state`
relabel. Any repair effect below that floor is not interpretable.

`scripts/patchlib.py` implements the four fix classes. **All four failed on the first
attempt**; the failures are the reusable part:

1. **`<delete id=..>` in a later `.edg.xml` cannot remove an edge** — the preceding
   `.con.xml`/`.tll.xml` still reference it (**102** hard `Error: The connection-source edge
   '%' is not known.`). Use **`--remove-edges.explicit <ids> --ignore-errors`**; verified to
   remove exactly the targeted edges and their orphaned junctions/tlLogics and nothing else.
2. **`<join nodes="a b c"/>` is SPACE-separated**, and **every listed node must exist** — one
   stale id aborts the entire build with `Unknown junction ... in join-cluster` *and*
   `No edges loaded`. Filter the list against the current `.nod.xml` before writing it.
3. **`<delete>` in a later `.con.xml` cannot delete a connection an earlier `.con.xml`
   declared.** Verified against a connection demonstrably present in the source file:
   `Error: Connection from=% to=% fromLane=% toLane=% not found`. **Plain-XML connection
   patching is additive only.**
4. **Changing the lane assignment of a TL-controlled connection requires rewriting the
   `.tll.xml` `<connection ... tl=.. linkIndex=..>` binding in the same build**, or netconvert
   aborts. **`--ignore-errors.connections` does not suppress this.** Rebind by string-replacing
   the `(from,to,fromLane,toLane)` tuple; keeping the other movements' tuples unchanged avoids
   a `linkIndex` reshuffle that would invalidate every phase string.
5. **`--tls.unset` takes JUNCTION ids, not tlLogic ids** (`The junction 'GS_61340907' to set as
   not-controlled is not known`). It is the clean way to demote a guessed signal — a
   `.nod.xml` `type="priority"` patch alone leaves the `.tll.xml` program and its connection
   bindings dangling (10+ errors).
6. **Fixes interact.** A connectivity fix that deletes edges will delete the targets of other
   fixes. Re-resolve every later fix against the post-deletion element set, or the combined
   build dies with `The from-node is not given for edge '%'`.

**Verify in the compiled net, never assume.** `patchlib.verify(net, spec, fixes)` re-parses the
output and checks the *intended state* (lane count, which lanes serve the left turn and whether
it is exclusive, whether the joined junction exists and its members are gone, whether the
targeted tlLogics are absent) plus that **no new defect appeared** (edges-outside-SCC, dead-end
edges, residual no-conflict signals, `Minor green` warnings, all re-measured after each build).

## 3. Persistence: an ID-keyed patch spec, not a netdiff

Store the repair as a **JSON spec keyed on SUMO element ids** (`repair_patch_spec.json`
pattern), never as coordinates. OSM-derived edge/node ids and `cluster_*` ids (a sorted
concatenation of member OSM node ids, not a counter) are stable across re-import.

Verified re-application against three re-imports of the same OSM data:

| fix class | identical rebuild | `--junctions.join-dist` changed | upstream `.osm.xml` edited |
| --- | --- | --- | --- |
| edge removal (enumerated id list) | reapplies | reapplies | **partially stale** |
| junction join (node ids) | reapplies | reapplies | reapplies |
| lane + connection re-lane | reapplies | reapplies | **correctly skipped** |
| signal demotion (`--tls.unset`) | reapplies | reapplies | reapplies |

Two mechanisms behind the failures, both worth designing for:

- **An enumerated removal list is not self-updating.** After 8 upstream way deletions the patch
  still removed all 167 original edges, but **6 new** out-of-SCC edges had appeared.
  **Re-run the audit after every re-import; do not just replay the patch.**
- **Put a pre-state guard on any attribute patch.** An upstream `lanes=4` edit had already made
  the target edge 4 lanes with different downstream connections. Guarding on
  `old_numLanes == expected` plus "the expected `<connection>` rows are present" made the
  applier *skip and report*; without the guard netconvert died with `Could not insert
  connection between '%' and '%' after build`. A patch whose assumed pre-state is gone must
  degrade loudly, not apply blindly.

**`netdiff.py` is a reporting tool, not a patch format.** Its docstring promises "the minimal
plain-xml input which can be loaded with netconvert alongside source to create dest". Tested
per fix class **including against the diff's own source network**:

| diff contents | reapplies? |
| --- | --- |
| tlLogic `<delete>` only (signal removal) | **yes — on all four targets including perturbed re-imports** |
| any node `<delete>` (edge removal, junction join) | **no — 18–30 errors, even self-applied** |
| any connection `<delete>` (re-laning) | **no — 1 error, even self-applied** |

Mechanism: netconvert applies node deletions while loading the `--node-files` list, and then
the *source's own* `.edg.xml` references the now-missing node → `Error: Edge's '%' from-node
'%' is not known.` Connection `<delete>` hits rule 2.3 above. `<delete>` inside `.tll.xml`
works because tlLogic ids are resolved after the structural build.

## 4. Traffic impact: which defects actually bias results

Design (per `quantify-sumo-run-to-run-variability` and
`validate-congested-scenario-results-against-teleport-artifacts`): generate demand once per
seed on the **most-restricted arm's** network so the identical OD set is offered to every arm
(verify the edge-set intersection), recompute routes **per arm** with strict `duarouter`,
exclude a warm-up, use paired CRN, and set `--time-to-teleport` above the longest red phase.

**Verified headline result: on a fixed, routable OD set, none of the four repairs changed
network-wide mean travel time or delay at a detectable level** (15 seeds congested + 10 seeds
light; every paired 95 % CI spanned zero; the only significant network-wide deltas were
+0.09 %/+0.12 % route length). The entire measurable cost of the import defects was in
**demand routability** (§1.2), not in the travel time of the trips that did route.

**A null is uninterpretable without exposure and a link-level measurement.** Always compute
both (`scripts/defect_exposure.py`, then `edgeData` restricted to the defect's edges — and
restrict to edges present in *both* arms, or a junction join changes the edge population and
the comparison is meaningless):

| defect class | exposure | link-level effect | verdict |
| --- | --- | --- | --- |
| edges outside largest SCC | **0 of 18 000 vehicles** | n/a | **cosmetic for fixed OD *by construction*** (no valid core→core route can use them) — but costs **56 %** of an OD-style demand |
| no-conflict guessed signals | 17.8 % of vehicles | **−12.6 % link travel time, +12.6 % speed (significant)** | **locally real, network-dilute** |
| shared through+left lane | 8.8 % of vehicles | **−2.0 % link travel time (significant)** | locally real, small |
| netconvert's *refused* junction join | 7.6 % of vehicles | **1.58 s → 3.56 s, +126 % link travel time (significant, harmful)** | **not a defect — the heuristic was right** |
| PT-relation / bad-tag warnings | — | — | cosmetic |

**Do not treat every un-joined cluster as a defect.** Forcing the join netconvert refused as
"not compact" made things measurably worse and roughly quadrupled teleports in the congested
regime. netconvert's join refusals state their reason; believe them unless you have a
specific reason not to.

**Congested-regime caution**: at the demand where gridlock starts, single seeds tip over and
dominate the mean — one arm showed +10.96 % mean travel time with a ±68.70 s CI and a **median
of +0.61 s**, driven by one seed at 740 s / 133 teleports. Report medians and teleport counts
alongside means, and prefer a demand level where teleports are near zero.

## 5. Scripts

| script | purpose |
| --- | --- |
| `scripts/audit_network.py` | full defect inventory of a compiled net → console + JSON |
| `scripts/patchlib.py` | `connectivity()`, `noconflict_signals()`, `apply_patch()`, `verify()` — the reusable core |
| `scripts/find_turnlane_defects.py` | shared through+left lane scan, restricted to the routable core |
| `scripts/netcmp.py` | ID-based structural diff of two nets (lossless control + per-fix verification) |
| `scripts/od_routability_probe.py` | independent lane-km-weighted OD unroutable-rate probe |
| `scripts/defect_exposure.py` | how many routed vehicles actually touch each defect |

## Related

- `load-osm-network` — builds the network this skill audits; its gotchas list is the input to §1.
- `quantify-opendrive-roundtrip-fidelity` — the plain-XML control pattern, corrected here for
  real-world networks.
- `generate-random-trips`, `calibrate-demand-with-routesampler` — the demand side of §1.2.
- `validate-congested-scenario-results-against-teleport-artifacts` — teleport reporting convention.
- `analyze-simulation-outputs` — tripinfo/edgeData parsing.
- `extract-subnetwork-scenario-with-boundary-demand` — the other operation that manufactures
  exactly these boundary connectivity defects.
