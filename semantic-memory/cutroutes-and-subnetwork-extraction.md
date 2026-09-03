---
summary: Option-level reference for SUMO sub-network extraction ("scenario cutting") — netconvert's --keep-edges.in-boundary / --keep-edges.in-geo-boundary / --keep-edges.explicit family and cutRoutes.py's departure-time, disconnected-route and filtering options — plus what the cut silently changes in the network.
keywords:
  - cutRoutes
  - scenario-cutting
  - subnetwork-extraction
  - keep-edges-in-boundary
  - netconvert
  - boundary-demand
created: 2026-08-04T00:15:00
last_updated: 2026-08-06T21:24:14
sources:
  - "[[episodic-memory/2026-08-04_00-15-00/attempts/attempt-1/action-agent-output.json]]"
  - https://sumo.dlr.de/docs/Tools/Routes.html
  - https://sumo.dlr.de/docs/netconvert.html
related_pages:
  - "[[geh-statistic]]"
  - "[[sumo-output-files]]"
  - "[[openstreetmap]]"
  - "[[duarouter]]"
  - "[[opendrive-and-network-format-interoperability]]"
  - "[[multi-resolution-modeling-buffer-sizing-and-boundary-handoff]]"
  - "[[teleport-artifacts-and-gridlock-resolution-validity]]"
  - "[[imported-network-defect-classes-and-traffic-impact]]"
related_skills:
  - extract-subnetwork-scenario-with-boundary-demand
  - load-osm-network
  - analyze-simulation-outputs
  - run-mesoscopic-simulation
  - assign-traffic-with-marouter
related_skills_for_graph_view:
  - "[[extract-subnetwork-scenario-with-boundary-demand]]"
  - "[[load-osm-network]]"
  - "[[analyze-simulation-outputs]]"
  - "[[run-mesoscopic-simulation]]"
  - "[[assign-traffic-with-marouter]]"
---

# cutRoutes.py and Sub-Network Extraction

"Scenario cutting" is taking a large SUMO scenario and keeping only a study
area, while preserving the traffic that enters and leaves across the cut face.
It is a two-tool operation: `netconvert` clips the network, and
`$SUMO_HOME/tools/route/cutRoutes.py` clips the demand to match. Neither tool
warns loudly when it degrades the scenario, so the losses have to be measured —
see `extract-subnetwork-scenario-with-boundary-demand` for the measurement
protocol and verified numbers.

## netconvert's edge-keeping family

All of these are applied to an already-compiled network via `-s parent.net.xml`
(sumo-net-file input) and combine additively — the help text is explicit that an
edge is kept if *any* keep-rule keeps it.

| option | meaning |
| --- | --- |
| `--keep-edges.in-boundary xmin,ymin,xmax,ymax` | keep edges located within a **cartesian** (network-coordinate) box |
| `--keep-edges.in-geo-boundary W,S,E,N` | same, but corners given as **lon/lat** |
| `--keep-edges.explicit ID,ID,...` | keep a literal edge list |
| `--keep-edges.input-file FILE` | same from a file; **sumo-gui selection files are accepted**, which is the practical way to draw an irregular study area by hand |
| `--remove-edges.explicit` / `--remove-edges.input-file` | the complements |
| `--keep-edges.components N` | keep only the N largest weakly-connected components — useful *after* a cut, which routinely strands fragments |
| `--keep-edges.postload` | apply the removal after loading/patching/joining rather than during |

`--keep-edges.in-boundary` uses an **any-point-inside** test, not
fully-contained: on one verified 475-edge cut, 411 kept edges lay wholly inside
the box and 57 only partly, while no dropped edge touched the box at all.

The geo and cartesian forms are **not interchangeable**. A rectangle that is
axis-aligned in lon/lat is a slightly rotated quadrilateral in the projected
plane (meridian convergence), so the same nominal box selects a slightly
different edge set — verified Jaccard 0.961 (476 vs 475 edges, 19 disagreeing).
Converting between them needs `sumolib`'s `convertXY2LonLat`, which requires
**pyproj**. Deriving the geo box by interpolating the `<location>` element's
`origBoundary` against `convBoundary` does **not** work: `origBoundary`
describes the raw input extent, not the same node set as `convBoundary`, and
doing so selected a wholly disjoint region (zero edge overlap) in a verified test.

## What a cut silently changes

Verified by diffing a 2636-edge OSM parent against its 475-edge cut:

- **Edge attributes are preserved** — lane count, per-lane speed, priority,
  type, `allow`/`disallow`, from/to nodes: zero changes on surviving edges.
- **Edge *lengths* are not.** 52 of 475 edges changed length (50 longer,
  2 shorter, +0.83 % overall, up to +14.3 m on a 125 m edge). Removing a
  junction's other approaches shrinks its internal area and the adjoining edge
  extends into the freed space. Anything keyed on edge length — density, edge
  travel time, joins against parent data — inherits this.
- **Connections between surviving edges are fully preserved** (0 lost), but
  connections from a surviving edge to a dropped edge are **deleted without a
  warning** (62 in the verified case). Connections that appear "new" in the cut
  are internal-edge (`:junction_*`) renumbering, not invented movements.
- **Traffic lights outside the box are dropped wholesale** (132 -> 41), and a
  few boundary TLS junctions get **demoted to `dead_end`** (3 in the verified
  case) with their `tlLogic` removed.
- **Orphan TLS phase states survive.** A boundary signal that lost most of its
  approaches keeps the parent's full phase program: verified state widths 6, 9
  and 15 controlling only 1, 1 and 4 links respectively. netconvert says so —
  `Warning: Unused state in tlLogic 'X', program '0' at tl-index N` — but does
  not repair it, so the surviving movement still waits through phases serving
  movements that no longer exist. This is a real capacity artifact at the cut
  face; grep for that warning after every cut.

## cutRoutes.py

```bash
python3 $SUMO_HOME/tools/route/cutRoutes.py sub.net.xml parent_routes.xml \
        -o sub.rou.xml -d keep -v
```

Note the path: `$SUMO_HOME/tools/**route**/cutRoutes.py`, unlike
`randomTrips.py`/`osmGet.py` which sit directly in `tools/`.

| option | semantics |
| --- | --- |
| *(positional)* `network` then one or more `routeFiles` | the **sub**-network first, then the parent demand |
| `-o, --routes-output` | truncated `<vehicle><route>` output — the fidelity-preserving choice |
| `--trips-output` | write `<trip>` (origin/destination) instead; **mutually exclusive with `-o`** ("Only one of the options --trips-output or --routes-output can be given"). Discards the parent's realised path and lets SUMO re-route at load time — cheaper to reuse, less faithful |
| `--orig-net FILE` | the *parent* network, used to extrapolate new departure times from edge lengths and max speeds when the input carries no exit times |
| `--speed-factor F` | scales those max speeds during extrapolation (default 1.0), i.e. how much slower than free-flow the extrapolation assumes |
| `--discard-exit-times` | ignore `exitTimes` even if present, forcing the `--orig-net` extrapolation path |
| `-d, --disconnected-action {discard,keep,keep.walk}` | what to do with a route that leaves the study area and re-enters, so its in-area edges are not contiguous. `discard` deletes the vehicle; `keep` emits one vehicle per contiguous part (ids suffixed `_part0`, `_part1`, ...) |
| `--min-length N` | drop routes with fewer than N edges inside the sub-network |
| `--min-air-dist M` | the same filter in metres |
| `--default.departLane` / `--default.departSpeed` | override the injection lane/speed written for truncated vehicles |
| `--default.stop-duration` | stop duration for stand-alone routes |
| `--pt-input` / `--pt-output` | reduce public-transport flows to the sub-network |
| `--stops-output` | filtered stop file; **writes an empty `<additional>` if the input has no `<stop>` elements** — it is a PT/parking option, not something derivable from car routes |
| `-a, --additional-input` | additional file supplying bus-stop locations |
| `--missing-edges N` | print the N most frequently missing edges — the diagnostic for "why did so many routes get discarded" |
| `-b, --big` | out-of-memory sort for very large demand |

`-e/--heterogeneous` exists only for backward compatibility and has no effect.

### Departure times: exit times beat extrapolation

`cutRoutes.py` decides *when* a truncated vehicle should be injected at the
boundary. If the input route carries an `exitTimes` attribute it uses the real
per-edge exit times; otherwise it extrapolates from `--orig-net`.

`exitTimes` is produced only by a **simulation**, via
`--vehroute-output FILE --vehroute-output.exit-times true` — `duarouter` output
does not have it. Verified penalty for extrapolating instead: interior mean GEH
0.25 ±0.02 versus 0.19 ±0.01, interior volume error -2.2 % versus -1.9 %. Small
but avoidable whenever the parent can be run once.

**`vehroute-output` does not write `<vType>` elements** and there is no option
to make it (the `--vehroute-output.*` family covers exit-times, sorted, dua,
cost, intended-depart, route-length, write-unfinished, skip-ptlines, incomplete,
stop-edges, speedfactor, internal, last-route — no vtypes). A route file cut
from vehroute output therefore carries dangling `type=` references and SUMO
aborts; the `<vType>` definitions must be supplied separately as an additional
file.

### How truncated vehicles are injected

Verified on output: `cutRoutes.py` marks every truncated vehicle with
`departLane="best"` and `departSpeed="max"`, and writes **no `departPos`**.
Vehicles therefore appear at the *start* of the boundary edge, on the best lane,
at the edge's free-flow speed — carrying none of the queueing the parent had
upstream. Vehicles whose whole trip already lay inside the study area keep their
original departure attributes, so the presence of `departSpeed` is a reliable
marker of which vehicles were cut and which edges form the injection face.

That marker matters because network topology is a poor substitute: in a verified
cut only 7 edges had in-degree 0 while vehicles were actually injected on 28
distinct edges — an edge fed from outside the box usually still has other
in-box predecessors and so is not a graph source.

## A bigger study box produces MORE disconnected routes

The counter-intuitive core fact of scenario cutting. Growing the box means more
routes intersect it at all, and a larger fraction of those clip a corner and
re-enter, becoming disconnected. Verified on one parent (3001 vehicles): tight
box 75 disconnected, +300 m buffer **375**, +600 m buffer 344.

With the default `-d discard` those routes are deleted, so **adding a buffer
ring while leaving `discard` in place makes interior fidelity worse, not
better**: interior volume error went from -1.9 % (tight) to -7.2 % (+300 m
buffer). Pairing the buffer with `-d keep` recovers it and then some
(-0.17 % volume error, mean GEH 0.11, at SUMO's own run-to-run noise floor).

`--min-length` acts as a second, blunter demand filter. `--min-length 5` was
free (GEH 0.18 vs 0.19); `--min-length 15` removed a third of the vehicles and
was the worst configuration tested (interior GEH 1.24, volume error -10.9 %).

## Evaluating a cut

Compare per-edge volumes with the [[geh-statistic]] from `edgeData` output (see
[[sumo-output-files]]), on a warm-up-excluded window, split into an interior
"core" and a boundary "band". Two conventions make the result meaningful:

1. **A parent-vs-parent noise floor.** Rerun the parent with a different
   `--seed` and identical demand and compare it to itself. Nothing can be more
   faithful than that. Verified floor: mean GEH 0.12 ±0.00, volume error
   -0.29 %. Against it, "GEH < 5 everywhere" is worthless as a discriminator —
   every configuration but one satisfied it. This is the lossless-control idea
   from [[opendrive-and-network-format-interoperability]] applied to a spatial
   cut.
2. **Replicate before believing time metrics.** Cut sub-scenarios are
   metastable. Verified: one configuration's mean time loss was 227.3 / 73.1 /
   67.9 / 131.4 s across four seeds (sd 74), and interior VHT error was
   4.78 % ±11.30 — a standard deviation larger than the effect. Flow/GEH metrics
   were stable to ~0.01-0.03 GEH. Report VKT and flow from a single run if you
   must; never report VHT or travel time without replications.

The flow error decays with distance from the cut face — verified profile for a
tight cut: mean GEH 0.72 at ~75 m, 0.47 at 150 m, 0.31 at 250 m, 0.21 at 375 m,
reaching the noise floor around 500 m. A 300-500 m buffer (with `-d keep`) is
the practical recommendation when the interior must be clean.

Finally, localise teleports by edge before attributing them to the cut. In a
verified case the cut's 4 teleports were all on the same edge the *parent*
already teleported on, with the same `wrong lane` cause, and none occurred on
injection or sink edges — the cut introduced no boundary teleports at all. See
[[teleport-artifacts-and-gridlock-resolution-validity]].
