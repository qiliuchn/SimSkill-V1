---
name: compute-dynamic-user-equilibrium
description: Use this skill when the user wants iterative dynamic user equilibrium (DUE) traffic assignment in SUMO — vehicles' route choice converging so that all used parallel routes have approximately equal travel time (Wardrop's first principle) — as opposed to single-shot shortest-path routing (duarouter alone), which just all-or-nothing-overloads the nominally fastest path regardless of congestion. Covers duaIterate.py, the Gawron and logit route-choice models, convergence criteria, and correctly testing Wardrop's principle. Trigger on mentions of duaIterate, dynamic user equilibrium, DUE, Wardrop's principle, traffic assignment, route choice equilibrium, or "does congestion make people switch routes."
---

# Compute Dynamic User Equilibrium (duaIterate.py)

Iterates `duarouter` + `sumo` via `duaIterate.py` until vehicles' route choices reach a **dynamic user equilibrium**: no driver can unilaterally switch to a faster route, because all routes actually used between a given origin and destination end up with approximately equal travel time (Wardrop's first principle). This is a fundamentally different demand paradigm from every other routing skill in memory (`convert-trips-to-routes`/`duarouter`, `calibrate-demand-with-routesampler`) — those compute a route once, all-or-nothing, against static free-flow weights; this iterates against *simulated, congestion-updated* weights until route choice stabilizes.

## Locating the tool

```bash
ls "$SUMO_HOME/tools/assign/duaIterate.py"
```

Unlike `randomTrips.py`/`tlsCoordinator.py` (directly under `tools/`), `duaIterate.py` lives in the `assign/` subdirectory.

## Basic usage

```bash
python "$SUMO_HOME/tools/assign/duaIterate.py" \
    -n net.net.xml -F demand.flows.xml \
    -l 50 -e 3600 \
    -A 0.5 -B 0.9 \
    --convergence-iterations 5 --max-convergence-deviation 0.005 \
    --clean-alt
```

Key options (verified via `--help`):
- `-n`/`--net-file` — the network (required).
- Exactly one of `-t`/`--trips`, `-r`/`--routes`, `-F`/`--flows` — the step-0 demand (trips, pre-routed routes, or flow definitions).
- `-l`/`--last-step` — the maximum number of DUA iterations (default 50).
- `-A`/`--gA`, `-B`/`--gBeta` — Gawron's route-choice model parameters (alpha, beta; defaults 0.5/0.9). This is the default route-choice model.
- `--logit` — switch to the (c-)logit route-choice model instead, with its own `-g`/`--logitbeta`, `-i`/`--logitgamma`, `-G`/`--logittheta` parameters. Running both models and confirming they converge to the same split is a good robustness check.
- `--convergence-iterations`/`--max-convergence-deviation` — declare convergence once travel-time deviation across this many recent iterations stays below this threshold, rather than always running the full `--last-step` count.
- `--clean-alt` — clean up intermediate route-alternative files (housekeeping).
- Passthrough: any `sumo--<option>` (e.g. `sumo--time-to-teleport 300`) forwards that flag to the underlying `sumo` calls.

## Interpreting the working directory

`duaIterate.py` creates numbered subdirectories (`000/`, `001/`, `002/`, ...), one per iteration, each containing that iteration's routed demand (gzipped `.rou.xml.gz`) and simulation output (`tripinfo_<iter>.xml`, an edgeData meandata dump used to compute the next iteration's weights). Build a convergence trace by parsing these directly: per-iteration mean travel time, the fraction of vehicles that changed which route they used vs. the previous iteration, and the resulting path/route split. A well-converging run shows the route-change fraction collapsing from ~50% (first re-route) to near-zero within a handful of iterations.

## Testing Wardrop's first principle — check BOTH in-network and total time

Classify each vehicle by which of several parallel routes it used (a marker-edge unique to each route, checked against the final iteration's route file), then compare mean travel time **per used route**. **Compute this on two different cost definitions, not just one:**

1. **In-network duration** — the router-visible cost `duaIterate` actually optimizes against (it derives route-choice weights from an edgeData dump of per-edge travel times, which only measures vehicles already *on* an edge).
2. **Total experienced time** = in-network duration + `departDelay` — what a traveler actually experiences, including any time spent queued at the origin waiting to be inserted into the simulation.

**These can disagree, and checking only the first one overstates the result.** A vehicle stuck in an origin insertion queue (common when the demand oversaturates a bottleneck) accrues real delay that the edge-weight router cannot see or route around — so an equilibrium can show two used routes' in-network times converging nicely (Wardrop satisfied for that metric) while their *total* experienced times still differ substantially (Wardrop not satisfied for what a rider actually cares about). Verified directly: an equilibrium with in-network times 1.2% apart (well within a 5% "approximately equal" threshold) had total experienced times 6.6% apart — enough to reverse the verdict if only the in-network number is checked. **Always compute and report both, using `scripts/analyze_due.py`'s dual check, rather than assuming in-network equality implies total-time equality.**

## If a total-time gap remains: is it a wrong split, or an ordering artifact?

Before concluding an equilibrium "failed" Wardrop on total time, investigate whether the residual gap is a genuine assignment error or a **departure-time/insertion-ordering artifact**. Verified diagnostic: re-simulate the *same* converged route split but with vehicles' departure times cleanly interleaved across routes (rather than `duaIterate`'s actual emitted ordering, which can cluster same-route departures in short bursts that transiently exceed a bottleneck's insertion capacity). If the interleaved re-simulation eliminates the departure-delay asymmetry and matches or improves on the original's total network time, the residual gap was an ordering artifact, not a wrong equilibrium split — `duaIterate` got the route-choice fractions right; only the fine-grained timing of *when* each route's vehicles depart was suboptimal for total time (a dimension it doesn't optimize at all).

## Gotchas

- **`duaIterate.py` lives in `tools/assign/`, not `tools/` directly** — don't assume every tool script shares one location.
- **Route choice is driven by an edge-weight dump, which cannot see origin-insertion queueing.** This is the structural reason a total-time Wardrop check can fail even when the in-network check passes — see above.
- **Engineer a genuine trade-off between routes, not just "one is shorter."** A useful test network needs one route that's fastest at low demand but capacity-limited (so it degrades under load) alongside a slower-but-higher-capacity alternative — otherwise there's no route choice to observe, everything just uses the nominally-shortest path regardless of demand level.
- **A `priority`-type merge where two parallel routes rejoin can inject spurious asymmetric congestion** that has nothing to do with the routes' own capacity — use a `zipper`-type merge (see `implement-alinea-ramp-metering`'s network-construction gotchas) for a clean, symmetric rejoin.
- **Run both Gawron and logit route-choice models and confirm they agree** on the equilibrium split as a robustness check — if they diverge substantially, that's worth investigating rather than reporting either result unconditionally.

## Related

- `convert-trips-to-routes` / [[duarouter]] — the single-shot routing this skill iterates on top of; `duarouter`'s own docs already flag `duaIterate.py` as the tool for "traffic-responsive iterative equilibrium," which this skill implements.
- `create-single-intersection` — the plain-XML+netconvert technique useful for engineering a network with a genuine parallel-route trade-off.
- `implement-alinea-ramp-metering` — shares the zipper-merge-for-clean-forced-interaction technique and the departDelay-vs-in-network-time distinction (a recurring theme whenever a bottleneck causes origin-insertion queueing).
- `analyze-simulation-outputs` — general tripinfo/summary comparison conventions this skill's `scripts/analyze_due.py` extends with per-path classification and the dual Wardrop check.
- [[dynamic-user-equilibrium-and-wardrop]] — the underlying DUE/Wardrop concepts and the verified in-network-vs-total-time finding this skill's methodology is built on.
- `construct-and-verify-braess-paradox` — reuses this skill's dual-cost Wardrop check, zipper-merge lesson, and departure-ordering-artifact diagnostic on a genuinely different topology (a diamond with a cross-link) to reproduce Braess's Paradox and measure Price of Anarchy.
- `sweep-rerouting-device-market-penetration` — uses this skill's `duaIterate.py`/Wardrop methodology as an equilibrium reference point for a live-rerouting (rather than offline-assignment) scenario, and extends the per-cost-definition Wardrop check to a per-departure-time-bin check for time-varying (incident) demand.
- `equilibrate-departure-time-choice-in-bottleneck-model` — adapts this skill's outer-iteration-loop structure to a genuinely different equilibrium concept (departure-time choice instead of route choice), and found this skill's MSA convergence discipline does NOT transfer: the departure-time equilibrium can be a repelling, not attracting, fixed point of naive day-to-day adjustment.
- `scan-network-link-criticality-and-vulnerability` — uses `duaIterate.py` as the re-equilibrated adaptation regime in a network-wide link-closure scan, and found an undamped custom MSA re-implementation can oscillate violently on a congested network exactly as `duaIterate.py` itself transiently does before settling — damping the path-flow swap rate specifically, not just link costs, is what stabilizes it.
- `simulate-incident-rerouting` — the live, in-simulation counterpart to this skill's offline, pre-simulation route optimization: same underlying route-choice-under-congestion problem, but reacting to a real-time incident mid-run rather than converging a route split before the simulation of record starts.
- `evaluate-neighborhood-traffic-calming-and-cut-through-displacement` — found a network shape (a permeable grid parallel to a higher-capacity arterial) where this skill's cost-convergence check is insufficient on its own: the DUE fixed point can be converged in cost while the route split itself remains only weakly identified, requiring a tail-window/tail-median resolution not needed on this skill's own simpler topologies.
