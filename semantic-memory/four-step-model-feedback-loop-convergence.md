---
summary: The classical four-step travel demand model's distribution/assignment feedback loop and its convergence behaviour, verified on a 16-zone synthetic SUMO city: undamped feedback settles into a two-cycle and can diverge, constant-weight damping stalls at the simulation noise floor or diverges outright, and only a vanishing method-of-successive-averages step converges — with the skim gap, not the OD-matrix change, as the metric that tells the truth.
keywords:
  - four-step-model
  - gravity-model
  - trip-distribution
  - Furness
  - IPF
  - deterrence-function
  - skim-matrix
  - feedback-loop
  - method-of-successive-averages
  - centroid-connectors
  - traffic-analysis-zones
  - intrazonal-trips
created: 2026-08-04T12:00:00
last_updated: 2026-08-04T12:00:00
sources:
  - "[[episodic-memory/2026-08-04_12-00-00/outputs/results/RESULTS.md]]"
  - "[[episodic-memory/2026-08-04_12-00-00/attempts/attempt-1/action-agent-output.json]]"
related_pages:
  - "[[od2trips]]"
  - "[[duarouter]]"
  - "[[od-matrix-estimation-and-underdetermination]]"
  - "[[dynamic-user-equilibrium-and-wardrop]]"
  - "[[marouter-macroscopic-assignment]]"
  - "[[sumo-stochastic-variability-and-replication-design]]"
  - "[[teleport-artifacts-and-gridlock-resolution-validity]]"
  - "[[abstract-network-generation]]"
  - "[[sumo-output-files]]"
related_skills:
  - build-four-step-model-with-feedback-loop
  - convert-od-matrix-to-trips
  - convert-trips-to-routes
  - compute-dynamic-user-equilibrium
  - estimate-od-matrix-with-odme
  - quantify-sumo-run-to-run-variability
related_skills_for_graph_view:
  - "[[build-four-step-model-with-feedback-loop]]"
  - "[[convert-od-matrix-to-trips]]"
  - "[[convert-trips-to-routes]]"
  - "[[compute-dynamic-user-equilibrium]]"
  - "[[estimate-od-matrix-with-odme]]"
  - "[[quantify-sumo-run-to-run-variability]]"
---

# Four-Step Model Feedback Loop and Its Convergence

The **four-step model** — trip generation, trip distribution, mode choice, traffic
assignment — is the classical aggregate travel-demand framework. Its well-known defect
is that distribution consumes a zone-to-zone impedance (**skim**) matrix that assignment
then contradicts: you distribute on free-flow times, assign, and discover the network is
congested. The fix is a **feedback loop** — extract congested skims from the assignment,
redistribute, reassign, repeat — and the practical question is whether that loop
converges, how fast, and how you know.

Everything below was verified on a controlled synthetic experiment: a 7x7 signalised SUMO
grid (300 m spacing, 1800 x 1800 m, 168 directed edges) with a 2-lane arterial ring and a
low-capacity 1-lane CBD core, partitioned into 16 traffic analysis zones, 7000 veh/h in a
peak hour, run for 6-12 outer iterations under six damping/constraint combinations.

## Where the uncertainty lives — contrast with ODME

This is the **forward synthesis** problem, and it is *not* the mirror image of
[[od-matrix-estimation-and-underdetermination]]. ODME's central finding is
under-identification: many matrices fit the same counts, so the matrix cannot be
recovered. Here the matrix is fully determined by (P, A, skim, β) — there is no
null space and no equifinality in the distribution step at all. The uncertainty has moved
somewhere else entirely: into **whether the skim the matrix was built on is a fixed point
of the loop that produced it**. Do not carry ODME's "improve, don't identify" caution
across; carry instead the discipline of quoting a residual and a noise floor beside every
matrix.

## The loop, concretely in SUMO

```
S_in(0) = free-flow skim
loop n:
    T(n)      = gravity(P, A, deterrence(S_in(n), beta))     # Furness / IPF
    trips     = od2trips(TAZ, T(n))                          # od2trips
    routes    = duarouter(trips, --weight-files edgeData(n-1))
    sim       = sumo(routes, edgeData/tripinfo/summary)
    S_raw(n+1)= zone skim recomputed from sim's edgeData travel times
    S_in(n+1) = S_in(n) + w * (S_raw(n+1) - S_in(n))          # damping
```

The congested skim step is cheap and does not need TraCI: read each edge's `traveltime`
from an `edgeData` dump, fall back to free-flow on unobserved edges, and re-run an
edge-expanded Dijkstra (nodes = edges, arc e→f costs cost(f); one Dijkstra per connector
edge yields the whole edge-to-edge matrix). [[od2trips]] writes `fromTaz`/`toTaz` onto
every trip and [[duarouter]] preserves them onto the routed `<vehicle>`, so `tripinfo`
can also be aggregated back to OD pairs as a cross-check — the same attribute
pass-through ODME relies on.

## Damping: only a vanishing step works

`S_in(n) = S_in(n-1) + w * (S_raw(n) - S_in(n-1))`, three schedules, two gravity
constraint structures. OD relative change |T_n − T_(n−1)|₁ / |T_(n−1)|₁ at the last
common iteration, against a **measured run-to-run noise floor of 0.027-0.091**:

| schedule | doubly-constrained | singly (production) constrained |
|---|---|---|
| undamped (w = 1) | plateaus **0.18-0.27**, two-cycle | plateaus **0.55-0.74**, two-cycle then diverges |
| constant w = 0.5 | stalls **0.047-0.068** = the noise floor | **diverges**: skim mean 176 → 474 → 394 → 508 → 669 → 1653 s |
| **MSA w = 1/n** | **0.0063** at iteration 11 | **0.0081** at iteration 12 |

Three separate lessons:

1. **Undamped feedback oscillates in a two-cycle, and the oscillation is what eventually
   destroys it.** In the singly-constrained run the CBD attraction share alternated
   59.5 → 41.5 → 65.9 → 40.3 → 66.0 → 41.5 → 76.8 %, intrazonal share 37 % ↔ 26 %, mean
   trip length 1.19 ↔ 1.30 km. Each swing pushes the network further, and at iteration 5
   it gridlocked (314 teleports, 2.15 m/s) after which the skim gap exploded to 3.24. The
   honest answer to "does it oscillate or diverge" is **it oscillates first and diverges
   as a consequence**.
2. **A constant damping weight cannot converge below the simulation noise floor.** The
   w = 0.5 doubly-constrained run plateaued at 0.047-0.068, sitting exactly on the
   measured 0.027-0.091 band. A non-vanishing step re-injects a fixed fraction of each
   noisy skim forever; only 1/n weights average the noise away. This is the operational
   reason to prefer MSA over a fixed relaxation factor, independent of any stability
   argument.
3. **Damping strength is problem-dependent, and "some damping" is not enough.** The same
   w = 0.5 that merely stalls the doubly-constrained loop **diverges outright** on the
   singly-constrained one, which has the higher loop gain because destination choice is
   free.

This reproduces, one level up the loop hierarchy, the finding already recorded in
`scan-network-link-criticality-and-vulnerability` and
[[dynamic-user-equilibrium-and-wardrop]]: an undamped custom MSA re-implementation
oscillates violently on a congested network. There it was route-flow swap rates; here it
is the demand-distribution skim. The structural lesson is the same.

## The OD-change metric lies; report the skim gap

The true fixed-point residual is the **skim gap** — relRMSE between the skim the network
actually produced and the skim used to distribute, `relRMSE(S_raw(n+1), S_in(n))` — not
the iteration-to-iteration change in the OD matrix.

Because **MSA with weight 1/n is an exact running arithmetic mean of every past raw
skim**, a pathological early iteration keeps contributing 1/n of the input for a long
time. Verified: at iteration 6 the doubly-constrained damped run had OD change **0.0167**
(comfortably below the noise floor, i.e. "converged" by that metric) while its skim gap
was still **0.353** — 2.8x *above* the noise floor — with an input skim of 281 s against a
network actually producing 226 s. The 492.9 s skim from iteration 1 (free-flow long-trip
matrix loaded onto a network that promptly gridlocked) was still one sixth of the average.

Practical rule: **4-5 iterations settle the OD-change metric; 10-12 are needed for the
skim gap to follow.** In the best-converged run (singly-constrained, MSA 1/n) the skim gap
fell 0.888 → 0.058, entering the 0.032-0.209 noise band at iteration 4 and dropping below
its 0.128 mean from iteration 6, with the raw skim mean pinned at 219.8-225.6 s for nine consecutive iterations.

A related trap: the skim gap as logged **is not comparable across damping schedules**,
because the MSA input lags by construction. For cross-variant comparison, recompute the
*raw* skims from every iteration's `edgeData` and compare them iteration-to-iteration —
that quantity is schedule-independent.

## Damping the skim damps only half the loop

The most consequential result of the experiment. A doubly-constrained MSA run's OD matrix
was converging (relative change 0.0091 → 0.0063 → 0.0147 at iterations 10-12) while the
network collapsed from 6.62 to 1.58 m/s and teleports went 0 → 83 → 571. Re-running each
suspect iteration's matrix *and its routing weight file* under three fresh seeds proved
this was not stochastic bad luck: the collapse reproduced at 1.91-2.46 m/s (154-424
teleports) while the healthy iteration 10 reproduced at 6.40-6.93 m/s (0-1 teleports).
The it10 and it12 matrices differ by 0.3 percentage points of intrazonal share.

Tabulating the **assigned edge loads** from each iteration's routed `.rou.xml` locates
the instability exactly:

| iteration | max edge volume | assigned-load relRMSE vs previous | OD relative change |
|---|---|---|---|
| 8 | 520 | — | 0.0108 |
| 9 | 628 | **0.587** | 0.0094 |
| 10 | 659 | **0.596** | 0.0091 |
| 11 | 694 | **0.632** | 0.0063 |
| 12 | 1037 | **0.814** | 0.0147 |

**Demand moved 0.6-1.5 % per iteration while assigned loads moved 59-81 %, and peak edge
volume climbed monotonically 520 → 1037.** MSA was damping the skim, so the distribution
step converged; the assignment step was a plain undamped all-or-nothing [[duarouter]]
pass on the previous iteration's weights, and it swung violently every iteration until
route concentration pushed the network past its capacity knee.

**A converged-looking OD matrix is not evidence of a converged model.** Report
assigned-load movement alongside the OD change; damp the route flows as well (Gawron or
logit blending, i.e. `duaIterate.py` as the inner loop) or nest a converged inner
assignment. This is exactly the lesson `scan-network-link-criticality-and-vulnerability`
recorded for route choice — damping the *path-flow swap rate*, not just link costs, is
what stabilises MSA on a congested network — now reproduced one level up the hierarchy,
in the demand-distribution loop. The singly-constrained damped run never hit this because
its equilibrium sits further from the knee (7.7-7.9 m/s), where all-or-nothing route
swings do not tip the network over.

## The noise floor is the yardstick, and it must be measured

Five replications of one identical demand set, differing only in od2trips/duarouter/sumo
seeds, each pushed through skim extraction and redistribution:

| quantity | mean | range |
|---|---|---|
| network mean speed | 5.71 m/s | 5.22-6.30 (CV 8.0 %) |
| total VHT | 515.2 h | 462.7-563.2 (CV 8.5 %) |
| teleports | 4.2 | 0-9 (CV 88 %) |
| pairwise skim relRMSE | **0.128** | 0.032-0.209 |
| pairwise OD relative change | **0.054** | 0.027-0.091 |

Without this, "the OD matrix moved 5 % this iteration" is uninterpretable — and it would
have led to declaring the constant-weight run converged. See
[[sumo-stochastic-variability-and-replication-design]]. The teleport CV of 88 % also means
a single bad iteration near the capacity knee may be one unlucky seed rather than a
divergence; re-run that iteration's matrix under fresh seeds before saying "diverged".

## A doubly-constrained model structurally cannot move demand away from the CBD

Because `sum_i T_ij = A_j` is a hard constraint, the share of trips attracted to the four
CBD zones was **exactly 66.6667 % at every iteration of every doubly-constrained
variant**, free-flow and congested alike. Congestion feedback changed trip lengths and
*which origins* served the CBD (outer-corner share 30.24 % → 29.50 %) and nothing else.

**Claiming a "congestion pushes activity out of the centre" result from a
doubly-constrained run is a category error.** The destination margin has to be free. With
a singly (production) constrained model on the same network and skims:

| | free-flow | congested equilibrium |
|---|---|---|
| CBD attraction share | 59.51 % | **49.18 %** (−17.4 % of CBD trips) |
| mean trip length | 1.4312 km | 1.2246 km (−14.4 %) |
| intrazonal share | 17.34 % | 35.00 % |
| network mean speed | 7.11 m/s | 7.74 m/s |

Per-zone: CBD cores −13 to −20 %, outer residential corners +73 to +96 %. Letting
destinations respond to congestion was worth about **+9 % network speed** here.

## How much congestion feedback changes the matrix

Doubly-constrained, free-flow versus converged equilibrium, same 7000 trips:

- zone-to-zone impedance more than doubles: interzonal **128.0 → 271.5 s (x2.12)**,
  intrazonal **65.1 → 149.8 s (x2.30)**, worst pair **x5.48**, best pair still **x1.60**;
- mean trip length **1.4500 → 1.2962 km (−10.6 %)**;
- intrazonal share **15.28 % → 25.65 %**;
- **the longest quartile of OD pairs loses 85.2 % of its demand; the shortest quartile
  gains 28.4 %**;
- 218 of 256 cells lose more than 10 %, 32 gain more than 10 %; cell-level relRMSE 0.744.

A free-flow matrix is therefore not a mild approximation of the congested one — it is a
substantially different trip-length distribution, and it is the *long* trips it gets
wrong. Intrazonal cost rises *more* than interzonal here because the CBD core (1 lane,
11.11 m/s, signalised) is exactly where the central zones' intrazonal trips happen.

## Deterrence function is a convergence parameter, not only a behavioural one

At an identical calibrated mean trip length of 1.45 km, on the converged skim:

| deterrence | β (1/s) | IPF iterations | loop gain at +10 % skim |
|---|---|---|---|
| exponential exp(-βc) | 0.03497 | 31 | 0.669 |
| gamma c^-0.5 exp(-βc) | 0.03014 | 29 | 0.625 |
| gamma c^-1.0 exp(-βc) | 0.02532 | 26 | 0.571 |
| gamma c^-1.5 exp(-βc) | 0.02051 | 23 | **0.502** |

Loop gain = OD relative change per unit relative skim change. A combined/gamma function
at α = 1.5 has **25 % lower loop gain** and needs **26 % fewer IPF iterations** than the
pure exponential at matched behaviour, because the power term flattens the deterrence
curve in the congested mid-range. On a marginally unstable loop that is a real lever
alongside damping.

Crucially, **all measured gains are below 1**: the gravity distribution map alone is a
contraction. The instability comes entirely from the assignment half, where near the
capacity knee a small demand change produces a large skim change. Damp the skim (or the
matrix), because that is where the amplification is; tightening the distribution step
will not help.

## Calibration facts worth knowing

- **β is demand-scale-independent.** Bisecting β against a target mean trip length gave
  an identical 0.034970 at 7000 and at 12400 trips, because scaling P and A scales T
  proportionally. Recalibrate when the skim changes, not when the demand level does.
- **IPF cost explodes with β**: 2 iterations at β = 5e-4 versus 194 at β = 0.20 on the
  same 16-zone problem, because a steep deterrence function makes row/column balancing
  much stiffer. Check the **achieved margin error** (max relative deviation of row and
  column sums from P and A), not the change in the balancing multipliers.
- Along the calibration curve, mean trip length fell monotonically 1.835 → 1.177 km while
  the **intrazonal share climbed 4.1 % → 39.4 %**. Intrazonal trips are how a gravity
  model absorbs deterrence, and they barely load the network — so c_ii is doing a lot of
  quiet work. Compute it from real within-zone connector pairs with `s == t` **excluded**
  (an included pair is a zero-cost trip that dominates the diagonal), and always report
  the share; a too-cheap c_ii makes a congested equilibrium look like a demand collapse.

## Centroid connectors: the shortcut is measurable before you simulate

Zone-to-zone skims depend on which edges a zone is allowed to load onto. Allowing a
high-capacity arterial ring to act as a centroid connector, versus restricting connectors
to local streets, on the same network and zones:

- **skim-level, no simulation**: interzonal impedance **8.3 % cheaper**, worst pair
  **30.1 % cheaper**, **184 of 240** interzonal pairs made cheaper;
- **simulation-level**: trip completion **100 % → 62.6 %**, mean speed
  **6.23 → 0.79 m/s**, teleports **2 → 2432** — because weighting connectors by
  length x lanes gives a 2-lane arterial double weight per metre and concentrates
  thousands of departures onto 32 of 168 edges.

**The diagnostic that needs no control run** is the ratio of mean realised route length
to the distance skim, per OD pair. A healthy zone system gives a ratio slightly **above**
1 (measured 1.04) because real routes are a little longer than the idealised
weight-averaged skim; the shortcut case gave **0.945**, i.e. vehicles genuinely getting a
shorter trip than the zone geometry allows. Also pass `--different-source-sink` to
[[od2trips]] — verified 0 of 6997 trips had `from == to` with it, whereas without it
intrazonal cells generate degenerate zero-length trips.

## Size the demand before running any loop

This network's capacity knee sat between 7000 and 8000 veh/h — 6.23 m/s with 2 teleports
at 7000, 2.60 m/s with 143 at 8000, 0.98 m/s with 912 at 10000. A feedback loop run above
the knee measures teleport artifacts rather than equilibrium
([[teleport-artifacts-and-gridlock-resolution-validity]]). Sweep the demand level first
and pick a point that is genuinely congested but still clears; then treat any later
gridlock episode as a hypothesis to test with fresh seeds, not a conclusion.

Note also that the doubly-constrained structure itself keeps the network closer to the
knee: fixed attraction margins point 66.7 % of all demand at 4 of 16 zones no matter how
congested they become, which made that whole family of runs noisier and prone to random
gridlock episodes, while the singly-constrained runs relaxed to a stable 7.4-7.9 m/s.

## Relation to assignment-side equilibrium

The loop above uses one all-or-nothing [[duarouter]] pass per outer iteration, on the
previous iteration's congested edge weights, with the outer MSA doing all the averaging.
That is a legitimate scheme but its fixed point is the fixed point of *this* loop, not a
Wardrop equilibrium. A converged inner assignment ([[dynamic-user-equilibrium-and-wardrop]]
via `duaIterate.py`, or the far cheaper macroscopic
[[marouter-macroscopic-assignment]]) nests inside it at roughly 50x and 0.05x the cost
respectively. When reporting a "congested equilibrium demand matrix", say which
equilibrium concept the inner loop actually delivered.
