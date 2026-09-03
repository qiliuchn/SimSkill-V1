---
summary: The defect classes a SUMO network inherits from an imported source (OpenStreetMap and friends), which QA checks actually detect them, and verified measurements of which defects materially bias simulated traffic versus which are cosmetic.
keywords:
  - network-quality-assurance
  - netcheck
  - netdiff
  - strongly-connected-component
  - network-repair
  - plain-xml-patch
  - guessed-signals
created: 2026-08-04T13:00:00
last_updated: 2026-08-04T13:00:00
sources:
  - "[[raw-materials/OpenStreetMap - SUMO Documentation.md]]"
  - https://sumo.dlr.de/docs/Networks/Import/OpenStreetMap.html
  - https://sumo.dlr.de/docs/Tools/Net.html
  - https://sumo.dlr.de/docs/Networks/PlainXML.html
related_pages:
  - "[[openstreetmap]]"
  - "[[opendrive-and-network-format-interoperability]]"
  - "[[cutroutes-and-subnetwork-extraction]]"
  - "[[random-trips]]"
  - "[[od2trips]]"
  - "[[routesampler]]"
  - "[[teleport-artifacts-and-gridlock-resolution-validity]]"
  - "[[sumo-command-line]]"
  - "[[sumo-stochastic-variability-and-replication-design]]"
related_skills:
  - audit-repair-and-persist-imported-network-defects
  - load-osm-network
  - generate-random-trips
  - quantify-opendrive-roundtrip-fidelity
  - extract-subnetwork-scenario-with-boundary-demand
related_skills_for_graph_view:
  - "[[audit-repair-and-persist-imported-network-defects]]"
  - "[[load-osm-network]]"
  - "[[generate-random-trips]]"
  - "[[quantify-opendrive-roundtrip-fidelity]]"
  - "[[extract-subnetwork-scenario-with-boundary-demand]]"
---

# Imported-Network Defect Classes and Traffic Impact

A network built by `netconvert` from imported data ([[openstreetmap]], OpenDRIVE, shapefile,
VISUM) compiles successfully and emits a page of warnings, and neither fact says anything about
whether the network is usable. This page catalogues the defect classes such a network carries,
which checks detect each one, and — measured rather than assumed — how much each one actually
distorts simulated traffic.

All figures below come from one verified end-to-end study on a live 1.51 km² OpenStreetMap
import of central Boston (543 edges, 58.3 lane-km, 340 junctions, 61 signals), built with
exactly `osmBuild.py`'s recommended option set plus a `passenger` vClass filter.

## The defect classes

### 1. Directed-connectivity defects (the dominant class)

Import truncates the world at a bounding box and drops ways the vClass filter excludes. What
survives is often **not strongly connected**, and the three sub-classes behave differently:

- **one-way traps** — reachable from the core, no way back (a trip *into* them completes, a trip
  *out of* them is unroutable);
- **unreachable enclaves** — can exit to the core, cannot be entered (the mirror case);
- **fully severed** — neither, typically a **bbox-truncated limited-access facility** whose
  entry/exit ramps lie outside the extract.

In the study network these accounted for **167 of 543 edges and 50.4 % of all lane-km**
(42 traps / 94 unreachable / 31 severed). `--remove-edges.isolated` catches none of them: it
only removes fully-isolated edges, and these are all attached to the network.

### 2. Traffic signals that resolve no conflict

`--tls.guess-signals` places signals on nodes where OSM tagged a signal pole. Some of the
resulting nodes have **no conflicting movements at all** — every controlled link is green in the
same phase group, so the program's only effect is an all-red interruption once per cycle.
**4 of 61 signals** were like this (one controlling a *single* link), each destroying **8 s of a
90 s cycle = 8.9 % of link capacity for zero safety benefit**. **netconvert emits no warning.**

The detector is exact and cheap: a `tlLogic` is a no-conflict signal iff the set of green link
indices is the same in every phase that has any green.

### 3. Guessed connections without an exclusive turn lane

netconvert's connection guessing routinely assigns a left turn and a through movement to the
*same* lane on a multi-lane approach, so a left-turner blocks a through lane.
**47 such approaches** existed inside the routable core; netconvert's
`Minor green from edge % to edge % exceeds 19.44m/s. Maybe a left-turn lane is missing.`
warning fired for exactly **one** of them.

### 4. Junction joining — under- and over-joined clusters

`--junctions.join` refuses some joins and reduces others, always with a stated reason
(`not compact`, `only 1 entry node`, `long edge`, `it contains a pt stop edge`,
`parallel incoming`). **These refusals are usually correct — see the measured result below.**
Over-joined clusters (many member nodes fused into one oversized junction) are the opposite
failure mode; netconvert offers no plain-XML primitive to split one.

### 5. Cosmetic noise that looks like defects

Roughly **65 of 112** netconvert warning lines on a real extract are public-transport-relation
removals and unparseable OSM tag values — expected for a passenger-car import.
**Warning count is not a defect score.** Likewise, a "default speed" check keyed on 13.89 m/s
(50 km/h) is a false-positive generator: 460/543 edges sat at 11.18 m/s because that is
Boston's *real* 25 mph default, not a netconvert guess.

## Which QA checks detect them

### `netcheck.py` with no options is actively misleading

`$SUMO_HOME/tools/net/netcheck.py <net>` reports connected **components**, and its default
analysis is **undirected**. On the study network it reported **531/543 = 97.79 % "connected"**
while only **376/543 = 69.2 %** of edges were mutually reachable.

The directed modes are the ones that matter, and they are exact:

```bash
netcheck.py net.net.xml -s <edge>   # 418/543 reachable FROM a central edge
netcheck.py net.net.xml -d <edge>   # 470/543 can REACH it
```

An independent strongly-connected-component computation agreed with both counts **exactly**,
and a strict-`duarouter` probe confirmed the classification behaviourally: all 20
`core→unreachable`, 20 `trap→core` and 20 `severed→core` trips were dropped; all 20
`core→core` trips routed.

### The unroutable-rate probe, run with the demand generator you will actually use

This is the check that subsumes most others — but its answer depends on the generator, not just
on the network. Verified, same network, 10 seeds × 2000 trips:

| demand generator | unroutable on raw import | after repair |
| --- | --- | --- |
| `randomTrips.py`, defaults ([[random-trips]]) | **0 (0.00 %)** | 0 |
| independent lane-km-weighted OD sampling (what [[od2trips]] / a zone OD table does) | **11 243 (56.22 %)** | **0 (0.00 %)** |

**`randomTrips.py` hides connectivity defects entirely.** Its source/sink samplers avoid
no-successor origins and no-predecessor destinations, and across 20 000 generated trips it never
once produced an impossible OD pair on a network where 31 % of edges are outside the routable
core. Any workflow using an OD matrix, [[routesampler]], or zone-based demand loses **56 %** of
its demand on the same network — silently, since `duarouter --ignore-errors` and
`randomTrips.py --validate` both just drop the trips.

## Traffic impact: what actually biases results

Measured with demand held fixed on the routable core (identical OD set offered to every arm,
routes recomputed per arm with strict `duarouter`, 600 s warm-up excluded, paired common random
numbers, 15 seeds congested + 10 seeds light, `--time-to-teleport 300` per
[[teleport-artifacts-and-gridlock-resolution-validity]]):

**On a fixed, routable OD set, repairing these defects changed network-wide mean travel time and
delay by no detectable amount.** Every paired 95 % CI spanned zero at both demand levels; the
only statistically significant network-wide deltas in the whole experiment were **+0.09 % and
+0.12 % route length**. Completed trips were identical to within 0.07 vehicles.

The impact is therefore almost entirely **in demand generation, not in the physics of the trips
that do route**:

| defect class | traffic verdict |
| --- | --- |
| edges outside the largest SCC | **Materially biases results — through demand only.** 56 % of an OD-style demand silently dropped, and the surviving demand is confined to the 49.6 % of lane-km inside the core. On a fixed routable OD set the effect is **provably zero**: 0 of 18 000 routed vehicles ever traversed one of the 167 edges, because no valid core→core route can. |
| no-conflict guessed signals | **Locally real, network-dilute.** −12.6 % link travel time / +12.6 % link speed on the affected links (significant), 17.8 % of vehicles exposed, yet no detectable network-wide change. Fix when the corridor is the study object. |
| shared through+left lane | **Locally real, small.** −2.0 % link travel time at one repaired approach (significant), 8.8 % of vehicles exposed, no network-wide effect. |
| a junction join netconvert *refused* | **Not a defect — forcing it is harmful.** Overriding a `not compact` refusal raised link travel time on the surviving approach edges from 1.58 s to 3.56 s, **+126 %** (significant) and roughly quadrupled teleports in the congested regime. |
| PT-relation / bad-tag warnings, plausible "default" speeds | **Cosmetic.** |

**A null result is uninterpretable without exposure.** Report, per defect, how many routed
vehicles actually traverse it and the link-level `edgeData` effect on exactly those edges —
restricted to edges present in *both* arms, since a junction join changes the edge population
and makes a naive link comparison meaningless.

**Congested-regime caution**: at the demand level where gridlock begins, single seeds dominate.
One arm showed +10.96 % mean travel time with a ±68.70 s CI and a **median of +0.61 s**, driven
by one seed at 740 s with 133 teleports versus 292 s / 3 teleports at another. Report medians and
teleport counts alongside means.

## Repair mechanics: plain-XML patch layering is more restrictive than it looks

Repair by decomposing to plain XML (`netconvert -s net.net.xml --plain-output-prefix p`) and
recompiling with small patch files layered on the originals — never by editing the compiled
`.net.xml`. Verified rules for SUMO 1.27.1:

- **`<delete id=..>` in a later `.edg.xml` cannot remove an edge**: the preceding `.con.xml` and
  `.tll.xml` still reference it (102 hard errors). Use
  `--remove-edges.explicit <ids> --ignore-errors`.
- **`<join nodes="a b c"/>` is SPACE-separated**, and every listed node must exist — one stale id
  aborts the whole build (`Unknown junction ... in join-cluster` *and* `No edges loaded`).
- **`<delete>` in a later `.con.xml` cannot delete a connection an earlier `.con.xml` declared.**
  Plain-XML connection patching is **additive only**.
- **Re-laning a TL-controlled connection requires rewriting the `.tll.xml`
  `<connection ... tl=.. linkIndex=..>` binding in the same build**, or netconvert aborts;
  `--ignore-errors.connections` does *not* suppress it.
- **`--tls.unset` takes JUNCTION ids, not tlLogic ids.**
- **Fixes interact**: a connectivity fix that deletes edges deletes other fixes' targets, so a
  combined build must re-resolve later fixes against the post-deletion element set.

### The plain-XML round trip is *not* exactly lossless on a real network

[[opendrive-and-network-format-interoperability]] records the plain-XML round trip as exactly
lossless — that was established on synthetic networks. On a real OSM import, recompiling the
plain files with **zero** edits preserved every count, every lane count, every speed and **every
tlLogic phase string**, but changed **75 of 543 edge lengths** (mean 1.20 m, max 18.72 m) for a
net **+0.018 % lane-km**, and relabelled 10 of 1246 connection `dir`/`state` values. Always run
this zero-edit control to establish the noise floor before interpreting a repair delta.

## Persistence: making a repair survive re-import

Store repairs as a spec **keyed on SUMO element ids**, never coordinates. OSM-derived edge and
node ids — and `cluster_*` ids, which are a sorted concatenation of member OSM node ids rather
than a counter — are stable across a rebuild and across netconvert option changes (all 17
`cluster_*` ids survived a `--junctions.join-dist` change from 10 to 15).

Two failure modes to design around, both verified against a hand-edited `.osm.xml`:

- **An enumerated removal list does not self-update.** After 8 upstream way deletions the patch
  still removed all 167 originally-targeted edges, but 6 *new* out-of-SCC edges had appeared.
  **Re-run the audit after every re-import; do not just replay the patch.**
- **Attribute patches need a pre-state guard.** An upstream `lanes=4` edit had already changed the
  target edge, and the unguarded patch killed the build (`Could not insert connection between
  '%' and '%' after build`). Guarding on the expected old lane count and the expected
  `<connection>` rows made the applier skip and report instead. A patch whose assumed pre-state
  is gone must degrade loudly.

### `netdiff.py` is a reporting tool, not a patch format

`$SUMO_HOME/tools/net/netdiff.py` promises "the minimal plain-xml input which can be loaded with
netconvert alongside source to create dest". Tested per fix class, **including re-applying each
diff to its own source network**:

| diff contents | reapplies? |
| --- | --- |
| tlLogic `<delete>` only (signal removal / demotion) | **yes** — on the source and on all three perturbed re-imports |
| any node `<delete>` (edge removal, junction join) | **no** — 18–30 errors, *even self-applied* |
| any connection `<delete>` (re-laning) | **no** — 1 error, *even self-applied* |

The mechanism: netconvert applies node deletions while loading the `--node-files` list, and the
*source's own* `.edg.xml` then references the missing node →
`Error: Edge's '%' from-node '%' is not known.` Connection `<delete>` hits the additive-only rule
above. `<delete>` inside `.tll.xml` works because tlLogic ids are resolved after the structural
build. Use `netdiff.py` to *see* what changed; use an ID-keyed spec that knows which netconvert
mechanism each fix class needs to *reapply* it.

## Where else these defects come from

The same connectivity defect classes are manufactured deliberately by network cutting — see
[[cutroutes-and-subnetwork-extraction]], where the boundary of an extracted study area produces
exactly the trap/unreachable/severed pattern — and by lossy format round trips, see
[[opendrive-and-network-format-interoperability]]. The audit in this page applies unchanged to
both.
