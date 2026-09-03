---
summary: Turning sparse GPS probe trajectories into SUMO routes and OD matrices with tracemapper/route2OD, measured against exact ground truth over 180 matcher runs on a real 1467-edge OSM network — the error surface is far steeper in ping interval than in positional noise (1s->120s costs 0.44 F1 at zero noise; 0->50 m costs 0.36 at 30 s ping) and below ~30 s more noise is partly compensated by denser sampling; the dangerous failure mode is PLAUSIBLE-BUT-WRONG routes (fully connected, legal, silently incorrect) reaching 94-97%, because connectivity-repair options convert detectable failures into undetectable ones — at ping 60 s enabling --fill-gaps raises F1 0.240->0.766 and drops disconnected routes 92.3%->0.7% while 98.5% of output is silently wrong; OD aggregation CANCELS matching error (82/90 cells) because route2OD keys only on first and last edge, so origin-edge recovery collapses to 12.6% while origin-TAZ holds at 77.1%; the operating envelope is <= 15 s ping with 50 m noise nearly free; and the binding downstream failure at coarse ping is route shortening (94% of the deficit at 30 s), not demand loss. Also records seven tracemapper/route2OD mechanics including a silent TIME-vs-ID sort trap that costs F1 0.9623 -> 0.0875 with no error message.
keywords:
  - map-matching
  - gps-traces
  - probe-vehicle-data
  - floating-car-data
  - tracemapper
  - route2OD
  - trajectory-to-route
  - probe-demand-reconstruction
  - plausible-but-wrong
  - ping-interval
  - positional-noise
  - fleet-penetration
  - operating-envelope
created: 2026-08-18T20:00:00
last_updated: 2026-08-18T20:00:00
sources:
  - "[[episodic-memory/2026-08-18_map-matching/summary.md]]"
  - "[[episodic-memory/2026-08-18_map-matching/outputs/RESULTS.md]]"
related_pages:
  - "[[od-matrix-estimation-and-underdetermination]]"
  - "[[sensor-location-design-for-od-estimation]]"
  - "[[traffic-state-estimation-sensor-bias-and-sensing-tradeoffs]]"
  - "[[geh-statistic]]"
  - "[[sumo-output-files]]"
  - "[[openstreetmap]]"
  - "[[dfrouter-detector-based-demand-reconstruction]]"
related_skills:
  - map-match-gps-traces-to-reconstruct-demand
  - estimate-od-matrix-with-odme
  - design-count-station-locations-for-od-estimation
  - emulate-and-evaluate-partial-sensor-traffic-state-estimation
  - load-osm-network
related_skills_for_graph_view:
  - "[[map-match-gps-traces-to-reconstruct-demand]]"
  - "[[estimate-od-matrix-with-odme]]"
  - "[[design-count-station-locations-for-od-estimation]]"
  - "[[emulate-and-evaluate-partial-sensor-traffic-state-estimation]]"
  - "[[load-osm-network]]"
---

# GPS Map Matching and Probe Demand Reconstruction

Probe trajectories — taxi/TNC fleets, telematics, smartphone SDKs, commercial feeds — are the dominant modern demand data source, and turning them into network routes requires map matching. This page records what that costs, measured against exact ground truth rather than asserted: SUMO's `--vehroute-output` gives the true route of every vehicle, so every matcher output has a known correct answer beside it.

Testbed: a real OSM extract (Chicago Loop / River North, 2.94 x 2.51 km), 1467 non-internal edges, 728 junctions, 111 edge-km, with alleys, frontage roads and dual-carriageway pairs. Matching is genuinely ambiguous — at a 20 m radius **83.5%** of on-network points have more than one candidate edge (mean 2.81); at 50 m, mean 6.36. With zero noise the nearest edge is the true one 100% of the time, so all error below is degradation, not geometry. 1200 vehicles, 9 TAZ, 72 OD cells, 480,328 FCD records, 180 matcher runs over ping x noise x seed x config.

## The error surface is steeper in ping than in noise

Edge-level F1 (`--fill-gaps 2000`, 3 CRN seeds, failures scored 0):

| σ \ ping | 1 s | 5 s | 15 s | 30 s | 60 s | 120 s |
|---|---|---|---|---|---|---|
| **0 m** | 0.977 | 0.989 | 0.959 | 0.897 | 0.782 | 0.534 |
| **10 m** | 0.588 | 0.723 | 0.780 | 0.796 | 0.723 | 0.497 |
| **50 m** | 0.260 | 0.374 | 0.483 | 0.539 | 0.536 | 0.399 |

Going 1 s → 120 s at σ=0 costs **0.44 F1**; going 0 → 50 m at ping 30 s costs **0.36**. The ordering holds in both matcher configurations (0.443 vs 0.359 with gap-filling; 0.865 vs 0.238 without) at roughly 20× the CRN seed noise (median 0.0028, max 0.0226).

**Below ~30 s ping, more noise is partly compensated by denser sampling** — the σ=50 m row *rises* from 0.260 at 1 s to 0.539 at 30 s. A noisy dense feed can beat a clean sparse one, which inverts the usual procurement intuition that accuracy is what you pay for.

## Connectivity is not a quality signal

The dangerous failure mode is a route that is **fully connected, fully legal, and silently wrong** — undetectable without ground truth, which is exactly what a practitioner never has. As a share of the whole 1200-vehicle fleet:

| ping | 1 s | 5 s | 15 s | 30 s | 60 s | 120 s |
|---|---|---|---|---|---|---|
| σ=0 m | 30.4% | 27.9% | 78.4% | **94.0%** | **95.5%** | 83.1% |
| σ=50 m | 63.4% | 87.0% | 95.0% | **97.4%** | 95.9% | 82.9% |

**Connectivity-repair options convert detectable failures into undetectable ones.** At ping 60 s / σ 5 m, enabling `--fill-gaps` raises F1 from 0.240 to 0.766 and drops disconnected routes from 92.3% to **0.7%** — while **98.5% of the routes produced are silently wrong**. The same trade appears in a second, independent option: raising `--gap-penalty` from 0 to 1000 at ping 30 s drops disconnected routes 84.8% → 14.1% while raising plausible-but-wrong 14.6% → 84.9%, and at an easy cell it makes F1 *worse* (0.793 → 0.741) while driving disconnected to 0.0%.

Whether gap-filling is repair or fabrication depends on the regime, and both answers are real:

| trace | option | F1 | connected | length ratio |
|---|---|---|---|---|
| noiseless, 250 m spacing | `--fill-gaps 0` | 0.422 | 0.0% | 0.475 |
| noiseless, 250 m spacing | `--fill-gaps 500` | **0.955** | **100%** | **0.928** |
| ping 1 s, σ 50 m | `--fill-gaps 2000` | — | — | **47.3x** |

On coarse *noiseless* traces it is genuine repair — the length ratio moves *toward* 1.0. Under noise it fabricates: the matcher bounces between edges 50 m apart and dutifully builds a real connected path between every bounce.

**Report the plausible-but-wrong rate.** It is the single most informative number in this pipeline, and it is invisible to every diagnostic a practitioner can run on their own data.

## Sweep a parameter where it can act

`sumolib/route.py:175` computes `maxGap = min(penalty + edge.getLength() + path[-1].getLength(), fillGaps)`, so at `--fill-gaps 0` the clamp forces `maxGap = 0` and **no routed extension can be returned regardless of `--gap-penalty`**. A hyperparameter sweep at the default therefore cannot detect that option at all:

| option | max \|ΔF1\| at `--fill-gaps 0` | at `--fill-gaps 2000` |
|---|---|---|
| `--delta` | 0.525 | — |
| `--fill-gaps` | 0.463 | — |
| **`--gap-penalty`** | 0.042 *(structurally inert)* | **0.347** |
| `--air-dist-factor` | 0.011 | 0.033 |
| `--direction` | +0.017 | 0.022–0.026 |

An initial analysis declared `--gap-penalty` inert on the strength of the left-hand column. It is the third-strongest lever of five. **Before calling a parameter inert, check whether the configuration you swept it in permits it to act.**

`--delta` helps up to about 2× the positional noise, then saturates, and **cannot compensate for coarse ping** — at 120 s it buys F1 0.046 → 0.097 and stops, at nonlinear cost (δ=200 took 112 s against 3 s at δ=20).

## OD aggregation cancels matching error

[[od-matrix-estimation-and-underdetermination]] shows counts leave OD degrees of freedom structurally undetermined. Trajectories are a different observation type, and the sharp question is whether aggregating noisy matched routes to zones cancels the error or compounds it. **It cancels**: OD misallocation is below route-level error in **82 of 90 cells** (median +18.6 pp) with gap-filling, and 90 of 90 without.

The mechanism is structural rather than statistical — `route2OD.py` keys only on `edges[0]` and `edges[-1]`, so interior matching error cannot reach the OD, and endpoint snapping usually lands in the right district:

| ping (σ 10 m) | F1 | origin **edge** correct | origin **TAZ** correct | OD misallocation |
|---|---|---|---|---|
| 15 s | 0.780 | 40.1% | **93.7%** | 6.3% |
| 30 s | 0.796 | 23.0% | **86.9%** | 11.6% |
| 60 s | 0.723 | 12.6% | **77.1%** | 19.9% |

**If you need an OD matrix you need far less matcher quality than if you need routes.** Origin-edge recovery collapses to 12.6% while origin-TAZ recovery holds at 77.1%.

## Penetration bounds you; the matcher still matters inside that bound

Fleet penetration sets a sampling floor no matcher can beat, but within it matcher quality still dominates the remainder: at 20% penetration, going from a 120 s to a 5 s feed removes **97% of the error above the sampling floor** (85% at 5% penetration). Matching overtakes sampling as the larger term at **ping 120 s at every penetration**.

Two measurement cautions, both learned by getting them wrong:

- **Compute every %RMSN term on a common cell universe.** A decomposition whose terms are evaluated over different cell sets — because the universe is built per call as `set(estimate) | set(truth)` — is not a decomposition; correcting it raised the matching term by up to 2.45x and reversed the conclusion.
- **At ~1% penetration %RMSN is non-monotone in matcher quality** and can support no matcher claim: an **empty OD scores 111.0 while a perfect matcher scores 225.5**, because a dozen probes scaled 100x become spikes farther from the true ~17-vehicle cells than zero is. Spearman between matcher F1 and OD error is **+0.245 at 1%** (wrong sign), −0.105 at 5%, −0.380 at 20%, −0.457 at 100%.

## Downstream: the binding failure is route shortening, not demand loss

Link entries factorise exactly as `E = N_vehicles x (entries/vehicle)`, so the flow deficit decomposes cleanly (verified to 1.4e-14 pp across 37 runs; ground truth 24.65 entries/vehicle):

| ping | total flow error | = trip loss | x entries/vehicle | demand-loss share |
|---|---|---|---|---|
| 30 s | −7.14% | **−0.42%** | **−6.75%** | **6%** |
| 60 s | −15.06% | −3.25% | −12.21% | 22% |
| 120 s | −32.57% | −16.67% | −19.08% | 51% |

**Demand loss dominates only at 120 s.** At 30 s about 94% of the deficit is route shortening; at 60 s, 78%. Reconstructions also manufacture **intrazonal** trips the true OD has none of by construction — 5.9% at ping 30 s, 17.0% at 120 s, and 36.5% for the worst configuration — misallocation into the shortest possible relation.

## The operating envelope, and how to state one honestly

On this network (1467 edges over 7.4 km², 1200 veh/h): **probe data at ≤ 15 s ping reproduces network conditions within the demand-sampling noise floor. 30 s is statistically indistinguishable from the floor. 120 s does not work.** Positional noise up to 50 m is nearly free downstream — the axis that matters is temporal, not spatial.

Three disciplines, each of which changed the answer here:

- **A ping level qualifies only if every tested noise level at that ping passes.** Taking the max passing ping and the max passing noise *independently* and gluing them into a sentence describes a corner that was never tested — it inflated this envelope from 15 s to 30 s until corrected.
- **Compare against a seed-varied control, not a zero floor.** Re-simulating the *true* OD with the seed that generated it reproduces the ground truth exactly (0.0%), an artefact that makes every reconstruction look bad against an unattainable target. Re-sampling the perfect OD under fresh seeds put the real floor at **19.0%** count %RMSN.
- **GEH cannot decide it.** GEH<5 sat at 99.6–100% across the whole envelope and fell only to 93–96% at 120 s, while %RMSN spanned 0–45%. Decide on %RMSN over a fixed link set; reserve GEH for accepting a single candidate. This is an independent second confirmation of [[geh-statistic]]'s ranking correction, in a different domain from the one that produced it.

## Tool mechanics

1. **`--fcd-output` is TIME-sorted; `tracemapper`'s `readFCD` requires ID-sorted — and is silent when it isn't.** Raw file: **1.0 edges/route, F1 0.0875**. Re-sorted by vehicle ID: **27.3 edges/route, F1 0.9623**. No error, no warning. This single trap can make a working pipeline look like a failed method.
2. `route2OD.py` reads only `<vehicle>`/`<trip>`/`<flow>`; raw `tracemapper` output is bare `<route>` elements and yields "read 0 vehicles".
3. **`route2OD.py` always exits 1, even on success** — `main()` has no `return`, so `if not main(...): sys.exit(1)` fires unconditionally. Judge success by output, never exit code.
4. **`tracemapper` is order-dependent.** `sumolib.net.readNet` calls `initRoutingCache(1000)`; the LRU key omits `maxCost` and the hit path returns `constructPath(dist)` with no cost check, so a path found under a loose budget is reused under a tight one. Reversing trace order changes **19.2%** of routes; `readNet(..., maxcache=0)` gives 0%. Small in aggregate (±0.005 F1) but it defeats exact reproduction.
5. `route2OD` drops trips whose O/D edge is outside the TAZ, printing only for the first four occurrences per direction plus a summary — use a TAZ covering every edge, not just trip ends (a trip-end-only TAZ covering 66.5% of edges would have lost 9.4–30.0% of trips as ping coarsened).
6. OSM extracts need a **largest-SCC restriction on TAZ trip ends** — 8.2% of edges sat outside it, and strict `duarouter` then failed on 1121 of 1200 trips.
7. A **negative-longitude `--bbox` must be one argv token** (`--bbox=-87.6,...`); see [[openstreetmap]] and the `load-osm-network` skill, whose wrapper carried this bug.

Also: distinguish genuine matcher failures from feeds too short to match. Pooled here, 7,873 "failures" contained 7,380 sub-2-ping feeds and only **493 (6.3%)** real matcher failures — at 120 s ping, 99.8% were simply too-short feeds, a sampling-design limit rather than a matcher limit. And keep every failure in the denominator: **a matcher that silently drops hard trips looks excellent.**
