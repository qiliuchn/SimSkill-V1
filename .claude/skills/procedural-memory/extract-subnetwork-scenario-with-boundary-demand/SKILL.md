---
name: extract-subnetwork-scenario-with-boundary-demand
description: Use this skill when the user wants to carve a smaller study area out of a larger SUMO scenario ("scenario cutting", sub-network extraction, clipping a corridor/district out of a city model) while keeping the traffic that crosses the boundary, and wants to know how faithfully the cut scenario reproduces the parent — including when the "parent" is a coarser-resolution model (Multi-Resolution Modeling / MRM: a macroscopic marouter or mesoscopic model handing boundary demand to a microscopic study-area child). Covers netconvert --keep-edges.in-boundary / --keep-edges.in-geo-boundary / --keep-edges.explicit, cutRoutes.py (--orig-net, --disconnected-action, --min-length, --trips-output, --stops-output), what the cut silently drops (dangling connections, orphan TLS phase states, demoted junctions, edge-length drift), a GEH/R2/VKT/VHT fidelity protocol with a parent-vs-parent noise floor, buffer sizing as a function of parent resolution and congestion, and the "over-injection trap" a coarser parent's un-metered boundary demand creates under congestion, with a calibrator-based fix. Trigger on mentions of cutRoutes.py, scenario cutting, sub-network extraction, keep-edges.in-boundary, clipping a SUMO network, study-area extraction, multi-resolution modeling, MRM, subarea buffer sizing, or "does my cut-out sub-model still behave like the full model".
---

# Extract a Sub-Network Scenario with Boundary-Preserving Demand

Carves a study area out of a larger SUMO scenario and keeps the traffic that
crosses the cut face, then *measures* how faithful the result is instead of
assuming it. Two tools do the work: `netconvert` cuts the network,
`$SUMO_HOME/tools/route/cutRoutes.py` truncates the demand. See
[[cutroutes-and-subnetwork-extraction]] for the option semantics.

## The pipeline

```bash
# 1. cut the network (cartesian corner coords xmin,ymin,xmax,ymax)
netconvert -s parent.net.xml --keep-edges.in-boundary 1530,1540,2930,2940 \
           -o sub.net.xml --no-turnarounds.tls true

# 2. truncate the demand
python3 $SUMO_HOME/tools/route/cutRoutes.py sub.net.xml parent_vehroutes.xml \
        -o sub.rou.xml -d keep -v
```

`scripts/cut_scenario.py` does both plus emits a runnable `.sumocfg`, an
edgeData additional file, and the vType file the cut needs (see gotchas).

```bash
python3 scripts/cut_scenario.py --parent-net parent.net.xml \
  --parent-routes parent_vehroutes.xml --boundary 1530,1540,2930,2940 \
  --out-dir cut/ --name tight --vtype-source parent.rou.xml \
  --disconnected-action keep --edgedata-begin 600 --edgedata-end 3600
```

## Cut a `vehroute-output`, not a duarouter route file

**This is the single highest-leverage decision.** `cutRoutes.py` needs to know
*when* each vehicle reached the boundary edge. It gets that from `exitTimes` on
the `<route>` element, which only a **simulation** produces:

```bash
sumo -c parent.sumocfg --vehroute-output parent_vehroutes.xml \
                       --vehroute-output.exit-times true
```

If you instead hand it a `duarouter` output, you must pass `--orig-net
parent.net.xml` and it *extrapolates* departure times from edge lengths and
maximum speeds (optionally scaled by `--speed-factor`). Verified cost of that
fallback on a 2636-edge OSM network: interior mean GEH rose from
**0.19 ±0.01 to 0.25 ±0.02** and interior volume error from -1.9 % to -2.2 %.
Small, but free to avoid — always take the simulated exit times if you can run
the parent even once.

## Verify the cut structurally before running anything

`scripts/net_cut_diff.py` diffs parent vs cut on the surviving edges. On a
verified 2636 -> 475 edge cut (18 % kept) of a real OSM network:

| what | result |
|---|---|
| edge/lane/speed/priority/type/vClass attributes on surviving edges | **0 changes** |
| edge **length** on surviving edges | **52 of 475 changed**, +308 m net (+0.83 %), up to +14.3 m on one edge |
| real-edge -> real-edge connections between surviving edges | **0 lost** |
| dangling connections (surviving edge -> dropped edge) | **62 silently deleted** |
| connections in cut absent from parent | 14 — **all internal-edge (`:junction_*`) renumbering, zero invented movements** |
| tlLogic | 132 -> 41 (91 dropped, all outside the box) |
| TLS demoted | 3 `traffic_light` junctions became `dead_end` |
| **TLS with unused phase states** | **3** (state widths 6/9/15 but only 1/1/4 links still controlled) |

Two of these are easy to miss and both matter:

- **Edge lengths change at the cut face.** Removing a junction's other
  approaches shrinks its internal area, and the adjoining edge grows into the
  freed space. Verified: 50 edges longer, 2 shorter, biggest +14.33 m on a
  125 m edge (+11 %). Density, travel-time and any edge-length-keyed join
  against parent data are all affected. Check it, don't assume geometry is inert.
- **Orphan TLS phase states are kept, not repaired.** netconvert emits
  `Warning: Unused state in tlLogic 'X', program '0' at tl-index N` and leaves
  the parent's full phase program in place. A junction that now has one
  surviving movement still runs a 15-character, multi-phase cycle, so that
  movement gets green for only its original share of the cycle — an artificial
  capacity restriction at the cut face. **Grep netconvert's stderr for
  `Unused state in tlLogic` after every cut** and rebuild or shorten those
  programs if the boundary junction's capacity matters.

`--keep-edges.in-boundary` keeps an edge if **any** part of it is in the box,
not only fully-contained ones (verified: 411 kept edges fully inside, 57 only
partly inside, 0 dropped edges still touching the box).

## `--keep-edges.in-geo-boundary` is *not* the same rectangle

Verified: converting the same box corners to lon/lat and re-cutting with
`--keep-edges.in-geo-boundary` gave 476 edges vs 475, Jaccard **0.961** (9 edges
only in the cartesian cut, 10 only in the geo cut). A lon/lat-axis-aligned
rectangle is a slightly rotated quadrilateral in the projected plane (meridian
convergence), so the two options select *nearly* but not exactly the same edges.
Pick one and stay with it; don't mix them across a study.

Also: `sumolib`'s `convertXY2LonLat` needs **pyproj** (`pip3 install pyproj
--break-system-packages`); without it you get "Network does not provide
geo-projection or pyproj not installed". Do **not** try to derive lon/lat by
linearly interpolating the `<location>` element's `origBoundary` against
`convBoundary` — verified failure: `origBoundary` covers the raw input extent,
not the same node set as `convBoundary`, and the resulting box selected a
completely disjoint region (**0 edge overlap**).

## `--disconnected-action` is the knob that actually matters

A route is "disconnected in the sub-network" when it leaves the study area and
comes back, so its in-area edges are not contiguous. Counter-intuitive verified
finding: **a bigger study box produces MORE disconnected routes, not fewer** —
tight box 75, +300 m buffer 375, +600 m buffer 344 (of 3001). A bigger rectangle
intersects more routes, and more of those clip a corner and re-enter.

Consequence: **adding a buffer ring while leaving `-d discard` makes fidelity
worse, not better**, because the extra discarded routes are demand the interior
needed. Verified interior means over 3 seeds:

| config | mean GEH | interior volume err | VKT err |
|---|---|---|---|
| tight, `-d discard` | 0.19 ±0.01 | -1.92 % | -2.01 % |
| +300 m buffer, `-d discard` | 0.65 ±0.03 | **-7.22 %** | -7.65 % |
| +600 m buffer, `-d discard` | 0.64 ±0.02 | -7.13 % | -7.11 % |
| +600 m buffer, **`-d keep`** | **0.11 ±0.01** | **-0.17 %** | **-0.30 %** |

**Use `-d keep` whenever you buffer.** `keep` splits a disconnected route into
one vehicle per contiguous part (ids get `_part0`, `_part1`, ...), preserving the
demand instead of deleting it.

## `--min-length` is a demand filter, not a cleanup option

`--min-length N` drops any route with fewer than N edges inside the sub-network
(`--min-air-dist` is the metres equivalent). It is tempting as "remove trivial
boundary-clipping trips", but it removes real flow. Verified on the tight cut:

| `--min-length` | vehicles kept | interior mean GEH | interior volume err |
|---|---|---|---|
| unset | 2509 | 0.19 ±0.01 | -1.92 % |
| 5 | 2368 | 0.18 ±0.02 | -1.84 % |
| 15 | 1698 | **1.24 ±0.02** | **-10.9 %** |

`--min-length 5` is free; `--min-length 15` cost a third of the demand and was
the worst configuration tested (boundary-ring GEH 2.40, 13.4 % of edges failing
GEH<5). Only use it to strip genuinely degenerate 1-2-edge clips.

## Measure fidelity against a parent-vs-parent noise floor, not against zero

Rerun the **parent** with a different `--seed` and identical demand, and compare
it to itself on the same edges. That is the floor no cut can beat. Verified
floor on the interior set: mean GEH **0.12 ±0.00**, volume error -0.29 %,
VKT -0.33 %, VHT -2.07 %. Against that floor `buf600_keep` (GEH 0.11 ±0.01) is
**not distinguishable from the simulator's own reproducibility** — a far more
meaningful statement than "GEH < 5 everywhere", which every configuration except
`--min-length 15` satisfied and which therefore discriminated nothing here.
This is the same lossless-control logic as
`quantify-opendrive-roundtrip-fidelity`.

Run `scripts/sensitivity.py` (3 seeds x N configs, `CUT_ZONE=core|band`) and
`scripts/fidelity_report.py` (single-seed per-edge table + `per_edge.csv`).
Split the evaluation set into **core** (edges >= 250 m inside the box) and
**band** (the rest) — reporting one number over the whole cut hides where the
error is.

## The cut scenario is metastable — never trust one seed on time metrics

Verified, and it nearly produced a wrong conclusion: `-d keep` on the tight cut
gave mean time loss **227.3 / 73.1 / 67.9 / 131.4 s** across seeds 42/1/2/3
(sd 74). Reading seed 42 alone says `keep` triples delay; the 3-seed mean says it
is mildly worse than `discard`, and on *flow* it is clearly better. Flow/GEH
metrics were stable (sd ~0.01-0.03 GEH); **time-based** metrics were not.
Interior VHT error for `tight_keep` was 4.78 % **±11.30** — a standard deviation
larger than the effect. Report VKT/GEH from a cut with confidence; report VHT
and travel time only with replications and their spread (see
`quantify-sumo-run-to-run-variability`).

The boundary ring is worse still: the **parent-vs-parent** VHT spread on band
edges was +15.2 % ±3.2. Boundary-zone time metrics at a congested demand level
are essentially uninterpretable — say so rather than reporting a number.

## Boundary artifacts, measured

`scripts/boundary_artifacts.py` classifies edges into the route-derived
injection face, the sink face, and hop-distance bands, then compares each class
against the parent.

- **cutRoutes.py writes `departSpeed="max"` and `departLane="best"`** on every
  truncated vehicle (verified: 2067 of 2509) and **no `departPos`** — vehicles
  are injected at the *start* of the boundary edge at the edge's free-flow
  speed, on the best lane, regardless of the queue the parent had upstream.
  That is the "loss of upstream metering" artifact in its literal form.
  Overriding it with `--default.departSpeed 0` changed interior flow
  negligibly (GEH 0.20 vs 0.19) but shifted interior VHT error from -3.3 % to
  -4.5 % — i.e. **at undersaturated demand the injection speed barely matters**;
  expect it to matter when the boundary edge is genuinely queued.
- **The flow error decays with distance from the cut face.** Verified profile
  for the tight cut: mean GEH 0.72 at ~75 m from the border, 0.47 at 150 m,
  0.31 at 250 m, 0.21 at 375 m, reaching the noise floor by ~500 m. **Budget a
  buffer of roughly 300-500 m (or 3-5 blocks) if the interior must be clean** —
  and pair it with `-d keep`.
- **The topological source set badly under-counts the cut face.** Only 7 of the
  475 edges had in-degree 0, but vehicles were injected on **28** distinct
  edges: an edge fed from outside the box usually still has other in-box
  predecessors, so it is not a graph source. Derive the injection face from the
  cut **route file** (edges carrying `departSpeed`), not from network topology.
- **Cutting did not manufacture teleports here.** Parent: 16 teleports over
  2636 edges, 15 of them already inside the study area. Tight cut: 4 teleports,
  **all on edge `844568710`, the same edge the parent teleported on**, all
  reason `wrong lane`. Zero teleports on injection or sink edges. Always
  localise teleports by edge before blaming the cut — per
  `validate-congested-scenario-results-against-teleport-artifacts`.

## Multi-resolution parent handoff: when the cut's "parent" is a coarser model

Everything above assumes the parent that generated the boundary demand ran at the
**same** resolution as the cut child (micro parent, micro child). Multi-Resolution
Modeling (MRM) — a coarse regional model handing boundary demand to a fine
study-area model, the standard large-agency workflow — instead uses a
**mesoscopic or macroscopic** parent. This changes both how much buffer you need
and whether buffer alone is even sufficient. Verified on a 64-junction regional
grid with a 2x2 study area, cutting at buffer = 0/1/2/3 blocks from both a micro
parent (`run-mesoscopic-simulation`'s sibling, i.e. an ordinary micro reference
run) and a meso parent (`--mesosim --meso-junction-control`), at two demand
levels (undersaturated v/c~0.6 and oversaturated v/c~1.0-1.1 with verified
spillback across the study-area boundary):

- **GEH-on-volumes does not discriminate buffer size when demand is
  duarouter-fixed** (no in-simulation rerouting): `cutRoutes.py` preserves each
  vehicle's exact edge sequence regardless of buffer, so GEH sits flat at/near
  the micro replication noise floor at every buffer, for either parent
  resolution. **Judge buffer adequacy on delay RMSE and VHT-proxy bias
  instead** — those *are* buffer-sensitive.
- **A micro parent needs buffer=0** — the cut is already inside the reference
  band with no buffer at all, at both demand levels tested. **A meso parent needs
  buffer≈2 blocks under moderate demand and buffer≈3 (near the full region) once
  oversaturated** — verified delay RMSE from a meso parent fell 2.36s (buf0) ->
  1.25 (buf1) -> 0.67 (buf2) -> 0.61s (buf3) at moderate demand, with VHT-proxy
  bias closing from +7.0% to within the micro-parent's own ±1-2% band by buf2.
  **The needed buffer grows both with parent coarseness and with congestion** —
  budget more than the ~300-500 m / 3-5 blocks quoted above (measured for a
  same-resolution parent) when the parent is meso or macro, and expect to need
  still more once the boundary is actually congested.
- **A macroscopic (`marouter`) parent is a capacity-mismatch risk, not just a
  coarser buffer problem.** Verified: `marouter`'s own capacity-constrained
  assignment (`flowCapacityRatio`) converged on a per-edge capacity **>30x lower**
  than the true measured micro capacity on identical geometry (~20 veh/h implied
  vs. ~750-800 veh/h/edge actually sustained) — a far larger mismatch than
  `[[marouter-macroscopic-assignment]]`'s previously-documented case. Never use
  `marouter`'s own capacity reference to decide whether a scenario is
  under/oversaturated; measure capacity directly (a micro flow-vs-demand sweep,
  or `quantify-sumo-run-to-run-variability`'s "peak of the curve" method) before
  trusting any `marouter`-derived demand level or boundary volume for an MRM
  handoff.

## The over-injection trap: buffer alone does not fix a coarse parent's boundary demand under congestion

This is the sharp edge of the "loss of upstream metering" artifact flagged above
("expect it to matter when the boundary edge is genuinely queued") — verified
directly, with a fix. **A coarser parent's boundary crossings are not metered by
the same-resolution congestion the child would itself develop** (meso
underestimates control/queuing delay — see `[[mesoscopic-simulation]]` — so its
reported boundary inflow is closer to the parent's *demand* than to what a real
signal-metered boundary would actually discharge). Handed to a micro child as
literal insertion volume, this produces a genuine over-injection: verified at
oversaturated demand, a meso-parent cut showed **4-5x higher mean insertion
(departure) delay than an equivalent micro-parent cut at every buffer tested**
(e.g. buf2: ~55s meso-parent vs. ~23s micro-parent), plus 2-4x more vehicles
delayed >1s at insertion — **and this gap did not close by buffer=3**, i.e. by
nearly the full region. Buffer size fixes the *spatial* extent of the parent's
missing detail; it does not fix the parent's *rate* being wrong at the boundary
it hands off, and growing the buffer mainly delays where that mismatch surfaces
rather than removing it.

**The fix**: don't hand the coarse parent's raw boundary crossings to the child as
literal insertion demand. Load a `<calibrator>` (see `calibrate-flow-with-in-
simulation-calibrator`, [[sumo-calibrator]]) on each injection edge, targeting
the *true*, congestion-aware boundary rate — ideally measured from a micro
reference if one exists even briefly, or otherwise the best available metered
estimate — instead of the coarse parent's uncongested crossing count. Verified
result on one oversaturated meso-parent cut: mean entry delay fell **0.27-0.31s
-> 0.14-0.15s** (~50%) and completed trips over the same window **rose 6.7%** —
smoothing the injection burst relieved a self-inflicted queue that had been
throttling downstream throughput generally, not just at the boundary. Honest
tradeoff: calibrator-inserted shortfall vehicles need a representative
continuation route per edge rather than each original vehicle's real
destination, trading a little route-diversity fidelity for correct metering.

**Decision rule this implies**: a micro-resolution parent is close to a free
lunch for an MRM handoff (buffer=0 already sufficient in the verified case); a
meso or macro parent is not — it needs a materially larger buffer *and* a
calibrator-based (or otherwise congestion-aware) boundary-injection fix, not
buffer alone, once the boundary is genuinely congested. Reserve a coarse-parent
cut for questions the coarse resolution itself remains valid for (see
[[mesoscopic-simulation]] and `[[marouter-macroscopic-assignment]]` for what
those are) — never for intersection-level delay/queue/LOS questions, which are
exactly where this artifact is worst.

## Gotchas

- **`vehroute-output` does not emit `<vType>`**, so `cutRoutes.py`'s output has
  dangling `type=` references and SUMO aborts. There is no
  `--vehroute-output.write-vtypes` option. Copy the `<vType>` elements from the
  original route file into an additional file and load it alongside
  (`cut_scenario.py --vtype-source` does this).
- **`--trips-output` and `-o/--routes-output` are mutually exclusive** —
  `cutRoutes.py` exits with "Only one of the options --trips-output or
  --routes-output can be given". `--trips-output` writes `<trip>` elements
  (origin/destination only, re-routed at load time by SUMO) instead of fixed
  `<route>`s; that discards the parent's realised path, so prefer
  `--routes-output` for fidelity work.
- **`--stops-output` writes an empty `<additional>` unless the input routes
  actually contain `<stop>` elements** (verified: 841-byte empty file from a
  passenger-car-only scenario). It filters bus-stop/parking definitions down to
  the ones the cut vehicles still use; it is a public-transport option, and
  pairs with `--pt-input`/`--pt-output` and `--additional-input`.
- **`cutRoutes.py` lives in `$SUMO_HOME/tools/route/`, not `$SUMO_HOME/tools/`**
  — unlike `randomTrips.py`/`osmGet.py`.
- **The parent scenario must be undersaturated or the study measures gridlock,
  not cutting.** First attempt here (12000 veh/h, static guessed OSM signals)
  produced 5218 teleport warnings; 5000 veh/h still gave 430 teleports and 325
  vehicles never finishing. Rebuilding with `--tls.default-type actuated` and
  3000 veh/h gave 16 teleports (0.53 %) and 100 % arrivals. Fix the parent
  before cutting anything.
- **zsh does not word-split unquoted variables** — building netconvert/cutRoutes
  argument lists in a `for` loop with `set -- $var` silently produces one
  argument containing spaces. Use arrays, or drive the pipeline from Python.

`scripts/mrm_buffer_curve.py` builds the buffer x parent-resolution x demand-level
fidelity table (GEH/delay-RMSE/VHT-bias) described above; `scripts/
injection_trap_diagnosis.py` computes the insertion-delay/teleport over-injection
comparison; `scripts/calibrator_boundary_fix.py` builds the per-edge `<calibrator>`
fix; `scripts/mrm_common.py` holds their shared GEH/edgeData/tripinfo/CI helpers.

## Related

- [[cutroutes-and-subnetwork-extraction]] — option-by-option semantics.
- [[street-running-tram-reservation-and-right-of-way-tradeoffs]] — unrelated
  domain, but the same "verify from raw output, don't trust the coarser model's
  own self-report" discipline this skill's MRM section follows.
- `load-osm-network`, `generate-random-trips`, `convert-trips-to-routes` — build
  the parent scenario.
- `analyze-simulation-outputs`, [[sumo-output-files]] — edgeData/tripinfo parsing.
- [[geh-statistic]] — the GEH definition and why GEH<5 discriminated nothing here.
- `quantify-opendrive-roundtrip-fidelity` — same lossless-control methodology
  applied to format round-trips instead of spatial cuts.
- `quantify-sumo-run-to-run-variability` — how many replications a claimed
  effect needs, and the "measure capacity as the peak of the curve" method used
  to catch `marouter`'s bad capacity reference above.
- `validate-congested-scenario-results-against-teleport-artifacts` — teleport
  localisation convention used above.
- `run-mesoscopic-simulation`, [[mesoscopic-simulation]] — the meso-parent case's
  underlying signal-delay-underestimation mechanism.
- `assign-traffic-with-marouter`, [[marouter-macroscopic-assignment]] — the
  macro-parent case and its capacity-mismatch risk.
- `calibrate-flow-with-in-simulation-calibrator`, [[sumo-calibrator]] — the
  over-injection trap's fix.
