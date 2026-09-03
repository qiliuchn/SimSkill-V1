---
summary: Round-tripping SUMO networks through OpenDRIVE, MATSim, and dlr-navteq found netconvert's export side is nearly lossless (the .xodr carries lane types and signal objects) while re-import is where fidelity is decided — a single option (--opendrive.import-all-lanes) is the only decisive lever, signal programs are silently regenerated on every network with zero warnings, and lost pedestrian/bicycle restrictions can make round-tripped traffic look better, not worse, by opening shortcuts that shouldn't exist; a plain-XML control confirmed 100% of the measured loss is genuine format information loss, not netconvert recompilation noise.
keywords:
  - opendrive
  - xodr
  - network-format-interoperability
  - matsim
  - dlr-navteq
  - netconvert
  - roundtrip-fidelity
created: 2026-08-03T23:00:00
last_updated: 2026-08-04T13:00:00
sources:
  - "[[episodic-memory/2026-08-03_23-00-00/outputs/results/fidelity_table.csv]]"
  - "[[episodic-memory/2026-08-03_23-00-00/outputs/results/fidelity.json]]"
  - "[[episodic-memory/2026-08-03_23-00-00/attempts/attempt-1/action-agent-output.json]]"
related_pages:
  - "[[openstreetmap]]"
  - "[[abstract-network-generation]]"
  - "[[sumo-command-line]]"
  - "[[sumo-stochastic-variability-and-replication-design]]"
  - "[[sumo-output-files]]"
  - "[[cutroutes-and-subnetwork-extraction]]"
  - "[[imported-network-defect-classes-and-traffic-impact]]"
related_skills:
  - quantify-opendrive-roundtrip-fidelity
  - create-grid-network
  - create-roundabout-network
  - load-osm-network
  - quantify-sumo-run-to-run-variability
related_skills_for_graph_view:
  - "[[quantify-opendrive-roundtrip-fidelity]]"
  - "[[create-grid-network]]"
  - "[[create-roundabout-network]]"
  - "[[load-osm-network]]"
  - "[[quantify-sumo-run-to-run-variability]]"
---

# OpenDRIVE and Network-Format Interoperability

SUMO networks are frequently exchanged with other tools — OpenDRIVE (`.xodr`) is the
standard bridge to driving simulators and HD-map/AV pipelines (CARLA, esmini, VTD),
MATSim is the standard bridge to agent-based regional demand models. This page reports
what genuinely survives a round trip through `netconvert`, measured on three networks
spanning feature richness (a signalized 3x3 grid, a roundabout, and a real-world OSM
extract with curved geometry and mixed vClass permissions), using an ID-agnostic
geometric network diff and a lossless plain-XML control to isolate genuine format loss
from recompilation noise. See `quantify-opendrive-roundtrip-fidelity` for the full
build/export/import/diff/repair pipeline and bundled scripts.

## Export is nearly lossless; import is where fidelity is decided

`netconvert --opendrive-output` (rev 1.4 in this SUMO version) genuinely encodes lane
types (`driving`/`sidewalk`/`biking`/`restricted`) and `<signal>` elements — inspecting
the `.xodr` directly confirmed the information is captured on export. Sweeping every
export-side option (`--opendrive-output.straight-threshold`,
`--junctions.internal-link-detail`, `--opendrive-output.lefthand-left`,
`--opendrive-output.shape-match-dist`) produced **no measurable change in round-trip
fidelity**, even though some visibly changed the file's internal geometry encoding.
**Fidelity is decided entirely on re-import.**

## The one decisive import option, and the diagnostic that reveals it's missing

`--opendrive.import-all-lanes` is the only import option that mattered on a mixed-vClass
network: without it, every non-driving lane is dropped and any edge left with zero
lanes disappears entirely — verified on a 433-edge network, default import retained only
181 edges (edge-match rate 0.217, lane-km 13.78 -> 6.34); with the flag, 432/433 edges
recovered (match rate 0.998), all 432 speed limits exact, junction positions accurate to
a mean 1.44 m offset. The dropped-edge count is directly diagnosable: netconvert's own
`Edge '%' has no lanes.` warning occurred exactly once per dropped edge in a verified
run (252 warnings for 252 dropped edges) — a decisive signal the flag was forgotten.
On networks with only driving lanes (the signalized grid, the roundabout), this and
every other import option swept made **no difference at all**.

Two options actively **hurt** import fidelity on real-world geometry:
`--opendrive.internal-shapes` (227 new warnings, edge-length accuracy driven to zero)
and `--geometry.remove` (edge-match rate fell further). Neither should be a default.

## Netconvert silence is not evidence of fidelity

Two losses were measured with **zero warnings emitted at either export or import**:

- **Traffic-light programs are silently regenerated on every tested network.** `tlLogic`
  *count* survived exactly (9->9 on the grid, 4->4 on the OSM network), but **zero of
  the phase strings matched** in either case — a hand-authored 8-phase plan with
  protected left-turn phases became a generic 2-phase plan. A matching cycle length
  (90s -> 90s) turned out to be a shared netconvert/netgenerate *default*, not evidence
  of preservation — verify phase strings themselves, not just phase counts or cycle
  length, before reporting "signals preserved."
- **`<roundabout>` declarations are always lost**, even when the underlying give-way
  link states (`M`/`m` connection flags) happen to survive intact. Tools and routing
  logic that key off the explicit `<roundabout>` element rather than inferring circular
  geometry will not recognize the round-tripped network as a roundabout at all.

**General lesson: diff the network, don't just watch the conversion log** — see
[[kinematic-wave-theory-validity-across-car-following-models]] and
[[gtfs-import-and-pt-representation-semantics]] for the same "a clean exit code is not
verification" pattern recurring in other SUMO import pipelines.

## The control: 100% of the measured OpenDRIVE deficit is genuine format loss

A plain-XML round trip (`--plain-output-prefix`, then recompile from the
`.nod/.edg/.con/.tll` files **only** — see gotcha below) reproduced every tested network
**exactly**: identical edge/lane/junction counts, identical lane-km, identical speeds,
and **identical `tlLogic` phase strings** on every network (9/9, 4/4). Because this
control is perfectly lossless, every deficit measured against OpenDRIVE is attributable
entirely to genuine format information loss, not to netconvert recompilation artifacts —
a load-bearing methodological control for any format-fidelity claim.

**Caveat on a real OSM-derived import** (not one of the 9/9, 4/4 networks tested above,
which were synthetic/grid nets): `tlLogic` phase strings still survived exactly, but 75 of
543 edge *lengths* shifted (mean 1.2 m, max 18.7 m, net +0.018% lane-km) — see
[[imported-network-defect-classes-and-traffic-impact]]. The plain-XML control is lossless
for topology and signal programs on every network tested so far, but not necessarily
bit-exact on edge geometry for a real-world import; re-measure the noise floor rather than
assuming zero before attributing a deficit to format loss on a non-synthetic network.

**Gotcha:** `--plain-output-prefix` also writes a `.typ.xml` containing
`sidewalkWidth`/`bikeLaneWidth`. Feeding that file back into the recompile re-triggers
sidewalk/bike-lane *guessing*, silently inventing pedestrian infrastructure that wasn't
in the original edges and degrading an otherwise-perfect control (one verified case:
score 1.0 -> 0.94, +3.3 km of newly-guessed pedestrian lane-km). Recompile from
`.nod/.edg/.con/.tll` alone.

## The wider format landscape

| format | what survives | what's lost |
|---|---|---|
| plain XML | everything, exactly | nothing (verified control) |
| MATSim | geometry, lengths, speeds, connections (plus some re-guessed extras) | **every `tlLogic`** (9->0 on the grid) |
| dlr-navteq | topology + signals well on a **geo-referenced** network (0.005 m mean junction offset, all TLS present) | catastrophically miscomputes a **non-geo-referenced/synthetic** network (18.5 -> 2368 lane-km) by reprojecting cartesian coordinates as geographic ones |
| shapefile | n/a | netconvert has import only in this version — not round-trippable, no `--shapefile-output` exists |

**Use plain XML for any SUMO-to-SUMO exchange.** MATSim is unsuitable whenever signal
timing matters. dlr-navteq is a reasonable OpenDRIVE alternative, but only on real-world,
geo-referenced networks.

## Behavioral consequences: lossy import can make traffic look better OR worse

Behavioral validation used geometric edge-ID remapping (translating demand generated
once on the original network through the same geometric map the diff used, rather than
regenerating demand separately per network) so every arm serves identical geographic
OD pairs despite total ID renaming after round-tripping.

- **Lost signal detail makes travel look artificially faster.** A round-tripped grid
  network showed -6.7% travel time / -14.3% delay vs. the original at *identical route
  lengths* (paired 95% CI excluding zero, 10 replications) — transplanting the original
  signal programs back removed the effect entirely (-6.7% -> -0.1%, no longer
  significant), isolating the simplified regenerated signal plan as the sole cause.
- **Lost pedestrian/bicycle restrictions can make traffic look artificially better at
  high demand — an inflation, not a degradation.** On a round-tripped mixed-vClass
  network at oversaturated demand, completed trips rose **+115%** and duration fell
  -65% relative to the original; traced directly to 55 of 1250 vehicles (4.4%) making
  220 edge traversals over segments that were pedestrian/bicycle-only in the original
  but became vehicle-usable after a default (non-all-lanes) OpenDRIVE import — a handful
  of illegitimate shortcuts relieved the network's real bottleneck. A naive permission
  repair over-corrected in the opposite direction; the residual divergence traced to
  separately-lost connections and `right_before_left`->`priority` junction-type
  conversions that the permission patch alone doesn't fix.
- **Divergence grows monotonically with demand.** The same OSM network's behavioral gap
  vs. the original widened from roughly -2% to -65% in travel-time metrics as demand
  rose from free-flow toward oversaturation, and unmapped/dropped edges caused as much
  as 81% of demand to become unroutable in the least-repaired (default-import) arm.
  **A round-trip that looks acceptable at low demand can diverge sharply once the
  network is stressed** — validate behaviorally at multiple demand levels, not just one.

## Deployment guidance

Treat an OpenDRIVE (or any format) round trip as safe for traffic-simulation *results*
only for unsignalized, single-vClass, driving-lanes-only geometry studies. Any network
with load-bearing signal timing, multimodal permissions, or turn restrictions needs
explicit repair (transplant original signal programs; re-apply original lane
permissions; expect residual connection loss) before its round-tripped simulation
results can be trusted, and that need becomes more acute — not less — the more heavily
loaded the network is.

The "lossless plain-XML control isolates genuine format loss" methodology here was later
reused for a different kind of network transformation: [[cutroutes-and-subnetwork-extraction]]
applies the same pattern (an uncut/uncalibrated control, explicit fidelity metrics,
honest attribution of divergence to a specific structural cause) to sub-network
extraction ("scenario cutting") rather than format round-tripping.
