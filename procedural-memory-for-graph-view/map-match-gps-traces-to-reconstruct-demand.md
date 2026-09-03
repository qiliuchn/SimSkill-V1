---
name: map-match-gps-traces-to-reconstruct-demand
description: Use this skill to turn GPS PROBE TRAJECTORIES into SUMO routes and an OD matrix — map matching with `tools/route/tracemapper.py`, aggregation with `tools/route/route2OD.py`, and validation of the result against ground truth. This is the trajectory-based demand-reconstruction pathway, distinct from every count-based one in memory (`reconstruct-demand-with-dfrouter`, `estimate-od-matrix-with-odme`, `calibrate-demand-with-routesampler`, `reconstruct-simulation-demand-from-field-turning-movement-counts`), which consume aggregate counts at fixed points. Covers the probe degradation factory (ping interval, positional noise, fleet penetration, dropout) for testing a matcher before trusting it, the WGS84 lon/lat round trip through `--geo`, the matcher hyperparameters that actually matter and the one that is invisible unless swept at the right setting, three-level scoring (edge / route / OD) with the plausible-but-wrong rate as the number that matters most, and the measured operating envelope for probe-derived demand. Trigger on map matching, GPS traces, probe or floating-car trajectories, taxi/TNC/telematics/INRIX/HERE feeds, trajectory-to-route, tracemapper, route2OD, snapping GPS points to a network, "what ping interval do I need", or "can I build an OD matrix from probe data".
related_skills:
  - estimate-od-matrix-with-odme
  - design-count-station-locations-for-od-estimation
  - reconstruct-demand-with-dfrouter
  - calibrate-demand-with-routesampler
  - reconstruct-simulation-demand-from-field-turning-movement-counts
  - emulate-and-evaluate-partial-sensor-traffic-state-estimation
  - load-osm-network
  - quantify-sumo-run-to-run-variability
related_skills_for_graph_view:
  - "[[estimate-od-matrix-with-odme]]"
  - "[[design-count-station-locations-for-od-estimation]]"
  - "[[reconstruct-demand-with-dfrouter]]"
  - "[[calibrate-demand-with-routesampler]]"
  - "[[reconstruct-simulation-demand-from-field-turning-movement-counts]]"
  - "[[emulate-and-evaluate-partial-sensor-traffic-state-estimation]]"
  - "[[load-osm-network]]"
  - "[[quantify-sumo-run-to-run-variability]]"
related_pages:
  - "[[gps-map-matching-and-probe-demand-reconstruction]]"
  - "[[geh-statistic]]"
  - "[[od-matrix-estimation-and-underdetermination]]"
---

# Map-Match GPS Traces to Reconstruct Demand

Every other demand-reconstruction skill here consumes aggregate counts at fixed points. This one consumes trajectories — the dominant modern data source (taxi/TNC fleets, telematics, smartphone SDKs, commercial probe feeds).

**Build the ground truth first, and never skip it.** In SUMO this pathway is *self-validating*: `--vehroute-output` writes the exact route of every vehicle, so every matcher output has a known correct answer beside it. Any claim about matcher quality made without that comparison is unfalsifiable — and the failure mode below is specifically one you cannot see without it.

## The headline you need before designing anything

**Connectivity is not a quality signal.** A matcher's output can be fully connected, fully legal, and silently wrong — and the options that improve connectivity are exactly the ones that manufacture this. Measured on a 1467-edge OSM network with 1200 vehicles:

| ping | 1 s | 5 s | 15 s | 30 s | 60 s | 120 s |
|---|---|---|---|---|---|---|
| plausible-but-wrong, σ=0 m | 30.4% | 27.9% | 78.4% | **94.0%** | **95.5%** | 83.1% |
| plausible-but-wrong, σ=50 m | 63.4% | 87.0% | 95.0% | **97.4%** | 95.9% | 82.9% |

At ping 60 s / σ 5 m, enabling `--fill-gaps` raises F1 from 0.240 to 0.766 and drops disconnected routes from 92.3% to **0.7%** — while **98.5% of the routes produced are silently wrong**. A practitioner without ground truth sees a clean route set and has no signal at all. **Report the plausible-but-wrong rate; it is the single most informative number in this pipeline.**

## Pipeline

```bash
# 1. Ground truth — record BEFORE touching any matcher
sumo -c gt.sumocfg --vehroute-output gt_vehroutes.xml --vehroute-output.exit-times true \
     --fcd-output gt_fcd.xml --fcd-output.attributes x,y --tripinfo-output gt_tripinfo.xml

# 2. Degrade into a realistic probe feed (scripts/probe_factory.py)
#    ping interval x positional noise x penetration, CRN over degradation seeds
#    with the underlying traffic held identical

# 3. Match  (scripts/matcher.py wraps this with chunked parallelism)
python3 $SUMO_HOME/tools/route/tracemapper.py -n net.net.xml -t feed.trace -o matched.rou.xml \
        --delta 20 --fill-gaps 2000 --gap-penalty 1000

# 4. Aggregate to OD  (scripts/od_lib.py wraps this; see the exit-code trap below)
python3 $SUMO_HOME/tools/route/route2OD.py -r matched.rou.xml -n net.net.xml \
        --taz-file districts.taz.xml -o reconstructed.od.xml

# 5. Score at three levels against step 1 (scripts/scoring.py)
# 6. Re-simulate the reconstructed OD and compare link counts on a FIXED link set
```

`scripts/` bundles the reusable pieces: `probe_factory.py` (nested ping sampling with shared noise draws so CRN holds), `matcher.py`, `scoring.py` (three-level scorer with strict denominator discipline), `od_lib.py` (`route2OD.py` wrapper plus OD metrics).

## Tool mechanics — each one cost real debugging time

1. **`--fcd-output` is TIME-sorted; `tracemapper`'s `readFCD` requires ID-sorted, and says nothing when it isn't.** Feeding the raw file gives **1.0 edges/route and F1 0.0875**; re-sorted by vehicle ID it gives **27.3 edges/route and F1 0.9623**. **No error, no warning.** Sort before matching, always.
2. **`route2OD.py` reads only `<vehicle>`/`<trip>`/`<flow>`.** Raw `tracemapper` output is bare `<route>` elements → "read 0 vehicles". Wrap them.
3. **`route2OD.py` always exits 1, even on success** — `main()` has no `return`, so `if not main(...): sys.exit(1)` fires unconditionally. **Judge success by output, never by exit code**, or your pipeline will abort on a working run.
4. **`tracemapper` is order-dependent.** `sumolib.net.readNet` calls `initRoutingCache(1000)`; the LRU key omits `maxCost` and the cache-hit path returns `constructPath(dist)` without a cost check, so a path found under a loose budget is reused under a tight one. Reversing trace order changes **19.2%** of routes; `readNet(..., maxcache=0)` gives 0%. Aggregate effect is small (±0.005 F1) but it makes exact reproduction impossible unless you pin the order or disable the cache.
5. **`route2OD` drops trips whose O/D edge is outside the TAZ**, printing only for the first four occurrences per direction plus a summary count — easy to miss in a long log. A trip-end-only TAZ covering 66.5% of edges would have lost 9.4–30.0% of trips as ping coarsened. **Use a TAZ that covers every edge**, not just trip ends.
6. **OSM extracts need a largest-SCC restriction on TAZ trip ends.** 8.2% of edges sat outside the largest strongly-connected component; `--remove-edges.isolated` removes only fully isolated edges, and strict `duarouter` then failed on 1121 of 1200 trips.
7. See `load-osm-network` for the `--bbox=` quoting rule — a negative-longitude bbox must be one argv token.

## Hyperparameters: sweep them where they can act

**Only `--delta`, `--fill-gaps` and `--gap-penalty` matter — but `--gap-penalty` is invisible unless you sweep it at `--fill-gaps > 0`.** `sumolib/route.py:175` computes `maxGap = min(penalty + edge.getLength() + path[-1].getLength(), fillGaps)`, so at `--fill-gaps 0` the clamp forces `maxGap = 0` and no routed extension can be returned regardless of the penalty. A sweep at the default therefore *cannot* detect the option:

| option | max \|ΔF1\| at `--fill-gaps 0` | at `--fill-gaps 2000` |
|---|---|---|
| `--delta` | 0.525 | — |
| `--fill-gaps` | 0.463 | — |
| **`--gap-penalty`** | 0.042 *(structurally inert)* | **0.347** |
| `--air-dist-factor` | 0.011 | 0.033 |
| `--direction` | +0.017 | 0.022–0.026 |

**The general lesson: before declaring a parameter inert, check whether the configuration you swept it in permits it to act at all.**

`--delta` helps up to about 2× the positional noise, then saturates, and **cannot compensate for coarse ping** — at 120 s it buys F1 0.046 → 0.097 and stops. Its cost is nonlinear (δ=200 took 112 s against 3 s at δ=20).

`--fill-gaps` and `--gap-penalty` both trade the same way: at ping 30 s, raising `--gap-penalty` 0 → 1000 drops disconnected routes 84.8% → 14.1% while raising plausible-but-wrong 14.6% → 84.9%. On *noiseless* coarse traces the same option is genuine repair (250 m spacing: F1 0.422 → 0.955, length ratio 0.475 → 0.928, moving toward 1.0). With noise it fabricates: at ping 1 s / σ 50 m, `--fill-gaps 2000` gives a **length ratio of 47.3×** — the matcher bounces between edges 50 m apart and dutifully builds a real connected path between every bounce. **Both answers are true; the regime decides which.**

## Scoring: three levels, and keep failures in the denominator

- **Edge**: per-trip precision/recall/F1, an order-aware similarity (LCS or normalised edit distance), length-weighted overlap, and O/D **edge** and **TAZ** recovery separately — they diverge sharply.
- **Route**: length-ratio bias *with its sign* (shortcutting at coarse ping, detouring under noise), disconnected share, failure share, and the **plausible-but-wrong** share.
- **OD**: per-cell GEH and %RMSN, total-flow conservation, 1/penetration scaling.

**A matcher that silently drops hard trips looks excellent.** Score failures as 0 against the full fleet. Also distinguish genuine matcher failures from trips whose feed was too short to match: pooled here, 7,873 "failures" contained 7,380 sub-2-ping feeds and only **493 (6.3%)** real matcher failures — at 120 s ping, 99.8% were simply too-short feeds, a sampling-design limit rather than a matcher limit.

## What the error surface looks like

**Steeper in ping than in noise**, which is counter-intuitive. Going 1 s → 120 s at σ=0 costs 0.44 F1; going 0 → 50 m at ping 30 s costs 0.36. **Below ~30 s ping, more noise is partly compensated by denser sampling** — the σ=50 m row *rises* from F1 0.260 at 1 s to 0.539 at 30 s. So a noisy dense feed can beat a clean sparse one.

**OD aggregation cancels matching error rather than compounding it.** OD misallocation is below route-level error in 82 of 90 cells (median +18.6 pp). The mechanism is structural: `route2OD.py` keys only on `edges[0]` and `edges[-1]`, so interior error cannot reach the OD, and endpoint snapping usually lands in the right district — origin-*edge* recovery collapses to 12.6% at 60 s ping while origin-*TAZ* recovery holds at 77.1%. **If you only need an OD matrix, you need far less matcher quality than if you need routes.**

**Penetration bounds you, but the matcher still matters within that bound.** The sampling floor dominates at low penetration, but at 20% penetration going from a 120 s to a 5 s feed still removes **97% of the error above that floor** (85% at 5%). Two cautions when measuring this: compute every %RMSN term on a **common cell universe** or the terms are not comparable; and at ~1% penetration %RMSN is **non-monotone in matcher quality** — an *empty* OD can score better than a perfect matcher, because a handful of probes scaled 100× become spikes farther from truth than zero is. Do not draw matcher conclusions from that regime.

## Operating envelope, and how to state one

Measured on a dense urban network (1467 edges over 7.4 km², 1200 veh/h): **probe data at ≤ 15 s ping reproduces network conditions within the demand-sampling noise floor; 30 s is statistically indistinguishable from the floor; 120 s does not work.** Positional noise up to 50 m is nearly free downstream. The binding failure at coarse ping is **not** demand loss — at 30 s about 94% of the link-flow deficit is route shortening and misallocation into shorter and intrazonal relations, and demand loss only dominates at 120 s.

Two disciplines when stating an envelope:

- **A ping level qualifies only if every tested noise level at that ping passes.** Taking the max passing ping and the max passing noise *independently* and gluing them into one sentence describes a corner that was never tested.
- **Compare against a seed-varied control, not a zero floor.** Re-simulating the *true* OD with the seed that generated it reproduces the ground truth exactly (0.0% error), an artefact that makes every reconstruction look bad against an unattainable target. Re-sample the perfect OD under several fresh seeds — here that floor is 19.0% count %RMSN, not 0%.
- **GEH cannot rank reconstructions** — it sat at 99.6–100% across the entire envelope while %RMSN spanned 0–45%. Decide on %RMSN over a fixed link set; reserve GEH for accepting a single candidate. See [[geh-statistic]].

## Related

- `estimate-od-matrix-with-odme` — the count-based inverse problem; its `odme_core` GEH/%RMSN helpers are reused here
- `design-count-station-locations-for-od-estimation` — the sensor-side counterpart: where to put counters versus what a trajectory feed buys instead
- `reconstruct-demand-with-dfrouter`, `calibrate-demand-with-routesampler`, `reconstruct-simulation-demand-from-field-turning-movement-counts` — the other count-based pathways
- `emulate-and-evaluate-partial-sensor-traffic-state-estimation` — FCD plumbing and probe penetration for *state* estimation rather than demand
- `load-osm-network` — the ambiguous testbed, and the `--bbox=` quoting rule
- `quantify-sumo-run-to-run-variability` — CRN across degradation seeds with traffic held identical
- [[gps-map-matching-and-probe-demand-reconstruction]] — the full measured error surface and the tool-mechanic evidence
- [[geh-statistic]] — why GEH cannot decide the envelope
- [[od-matrix-estimation-and-underdetermination]] — the count-based null-space problem this pathway partly escapes
