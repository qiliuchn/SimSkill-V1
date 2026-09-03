---
name: build-four-step-model-with-feedback-loop
description: Use this skill when the user wants a classical four-step travel demand model in SUMO — traffic analysis zones and a TAZ file, a land-use trip-generation table, a doubly- or singly-constrained gravity trip distribution with Furness/IPF and a calibrated deterrence function, then od2trips/duarouter/sumo assignment — and especially when they want the distribution/assignment FEEDBACK LOOP iterated to a congested equilibrium with convergence measured. Covers zone partitioning and centroid-connector placement, impedance (skim) matrix construction from free-flow and congested edge travel times, beta calibration against a target mean trip length, IPF convergence checking, method-of-successive-averages damping versus undamped and constant-weight schemes, and the run-to-run noise floor that every convergence claim must be measured against. Trigger on mentions of four-step model, trip generation/distribution/assignment, gravity model, deterrence function, Furness or IPF or Fratar, skim matrix, feedback loop, land-use table, traffic analysis zones, centroid connectors, or "congested equilibrium demand".
---

# Build a Four-Step Model with a Distribution/Assignment Feedback Loop

Builds the classical transport-planning pipeline on a SUMO network — zones → land-use
productions/attractions → gravity distribution → assignment → **feed the congested
travel times back into distribution and iterate** — and, critically, measures whether
that loop actually converged.

This is the *forward synthesis* problem. Its inverse — recovering a matrix from link
counts — is `estimate-od-matrix-with-odme`; read [[od-matrix-estimation-and-underdetermination]]
for the contrast. The two problems' lessons do **not** transfer symmetrically: ODME's
central finding is that many different matrices fit the same counts, so the matrix is
under-identified. Here the matrix is fully determined by (P, A, skim, β) — the
uncertainty has moved into whether the *skim* is a fixed point.

## Pipeline

```
step 1  netgenerate (+ plain-XML edit) ------------> net.net.xml       create-grid-network
step 2  make_zone_taz.py --------------------------> zones.taz.xml     convert-od-matrix-to-trips
step 3  land-use table, balance A to P ------------> P[], A[]
step 4  skim.py EdgeGraph.zone_skim(free-flow) ----> C[i][j] seconds
step 5  gravity.py calibrate_beta -----------------> beta, T[i][j]
step 6  write O-format matrix, od2trips -----------> trips.xml         convert-od-matrix-to-trips
step 7  duarouter (--weight-files = last edgeData)-> rou.xml           convert-trips-to-routes
step 8  sumo (--tripinfo, --summary, edgeData) ----> outputs           run-simulation
step 9  skim.py read_edgedata_traveltime ----------> congested C'      analyze-simulation-outputs
step 10 damp C', go to step 5 ----------------------- repeat 10-12x
```

## Scripts

`scripts/make_zone_taz.py` — partitions a network into a cols x rows zone grid on edge
midpoints and writes weighted `<tazSource>`/`<tazSink>` TAZ files. Asserts (does not
merely print) full coverage of loadable edges, no double assignment, no empty zone, and
that every zone still has a connector after `--exclude-type`. Writes **two** TAZ files —
restricted and all-edge — so the connector pitfall below can be measured.

```bash
python scripts/make_zone_taz.py -n city.net.xml -o zones --cols 4 --rows 4 \
    --exclude-type arterial
```

`scripts/skim.py` — edge-expanded Dijkstra (nodes = edges, arc e→f costs cost(f)) giving
the whole edge-to-edge cost matrix from one Dijkstra per connector, aggregated to
zone-to-zone by source-weight x sink-weight. `aux=` accumulates a second quantity along
the cost-shortest path (distance under a time skim). `read_edgedata_traveltime()` swaps
free-flow costs for measured `edgeData` travel times, falling back to free-flow on
unobserved edges — that one function is the whole congested-skim step.

`scripts/gravity.py` — `deterrence()` (exp / gamma-combined / power), `furness()`
(doubly-constrained IPF returning the **achieved margin error**, not just the multipliers),
`calibrate_beta()` (bisection on β against a target mean trip cost; mean trip cost is
monotone decreasing in β so bisection is safe).

`scripts/check_connector_shortcut.py` — the two-part connector diagnostic. Run it before
trusting any zone system.

A complete worked implementation (network build, land-use table, 6 loop variants,
noise-floor replication, gridlock reseed check, plots) is in
`episodic-memory/2026-08-04_12-00-00/attempts/attempt-1/scripts/`.

## Centroid connectors: never put them on the high-capacity network

Verified on a 7x7 signalised grid with a 2-lane arterial ring, 16 zones, 7000 veh/h.
Including the arterial ring edges as centroid connectors, versus restricting connectors
to local streets:

- **skim-level**: interzonal impedance **8.3 % cheaper**, worst pair **30.1 % cheaper**,
  **184 of 240** interzonal pairs made cheaper — a pure shortcut, no simulation involved;
- **simulation-level**: completion fell **100 % → 62.6 %**, mean speed **6.23 → 0.79 m/s**,
  teleports **2 → 2432**, because weighting connectors by length x lanes gives the 2-lane
  arterial double weight per metre and concentrates thousands of departures onto 32 edges.

**Diagnostic that works without a control run:** mean realised route length ÷ distance
skim, per OD pair. Healthy zone system → **ratio slightly above 1** (measured 1.04); the
shortcut case gave **0.945**. Below 1 means vehicles are getting a shorter trip than the
zone geometry says they should.

## Damping: use a vanishing step, and prove it converged

Three schedules on the skim, `S_in(n) = S_in(n-1) + w * (S_raw(n) - S_in(n-1))`:

| schedule | doubly-constrained gravity | singly (production) constrained |
|---|---|---|
| undamped (w = 1) | two-cycle, OD change plateaus at 0.18-0.27 | two-cycle, then **diverges** into gridlock |
| constant w = 0.5 | **stalls at the noise floor** (0.047-0.068) | **diverges outright** (skim mean 176 → 1653 s) |
| **MSA w = 1/n** | converges, OD change → 0.0063 | converges, OD change → 0.0081, skim gap → 0.058 |

Only the vanishing schedule works. A constant weight cannot average out simulation noise,
so it re-randomises at the amplitude of the noise forever; and where loop gain is higher
(singly-constrained, because destination choice is free) w = 0.5 is not enough damping
at all.

**Measure the run-to-run noise floor first.** Replicate one demand set under 5 seeds and
compute the pairwise OD relative change and skim relRMSE. Measured here: OD change
**0.027-0.091**, skim relRMSE **0.032-0.209**, network speed CV 8 %, teleport CV 88 %.
Any convergence threshold tighter than that band is meaningless, and any plateau sitting
*on* the band (like w = 0.5's) is noise, not convergence.

**Report the skim gap, not only the OD change.** MSA 1/n is an exact running arithmetic
mean of every past raw skim, so a pathological early iteration contaminates the input for
many iterations and the OD-change metric goes quiet long before the fixed point arrives.
Verified: at iteration 6 the doubly-constrained damped run had OD change 0.0167 (below the
noise floor) while its skim gap was still 0.353 — 2.8x *above* it, with input skim 281 s
against a network actually producing 226 s. **4-5 iterations settle the OD change; 10-12
are needed for the skim gap to follow.**

The per-iteration `skim_gap` is also **not comparable across damping schedules** (the MSA
input lags by construction). For a cross-variant comparison, recompute the *raw* skims
from every iteration's `edgeData` and compare them iteration-to-iteration.

## Damping the skim damps only half the loop

The single most important failure mode found here. A doubly-constrained MSA run's OD
matrix was converging beautifully (change 0.0091 → 0.0063 → 0.0147 at iterations 10-12)
while the network collapsed from 6.62 to 1.58 m/s with teleports going 0 → 83 → 571.
Reseeding proved this was not seed luck — the collapse reproduced at 1.91-2.46 m/s across
three fresh seeds, while the healthy iteration 10 reproduced at 6.4-6.9 m/s.

Tabulating the **assigned edge loads** straight out of each iteration's `.rou.xml`
explains it:

| iteration | max edge volume | assigned-load relRMSE vs previous | OD change |
|---|---|---|---|
| 9 | 628 | **0.587** | 0.0094 |
| 10 | 659 | **0.596** | 0.0091 |
| 11 | 694 | **0.632** | 0.0063 |
| 12 | 1037 | **0.814** | 0.0147 |

**The demand moved 0.6-1.5 % per iteration while the assigned loads moved 59-81 %, with
peak edge volume climbing monotonically 520 → 1037.** MSA damps the skim, so distribution
converges; the assignment step is a plain undamped all-or-nothing `duarouter` pass on the
previous iteration's weights and swings violently every iteration until route
concentration tips the network past the capacity knee.

**Always report assigned-load movement beside OD change** — a converged-looking matrix is
not a converged model. Fix by damping the route flows too (Gawron/logit blending, i.e.
`duaIterate.py` as the inner loop) or by nesting a converged inner assignment. This is
the same lesson `scan-network-link-criticality-and-vulnerability` recorded for route
choice — damp the *path-flow swap rate*, not just link costs — reproduced one level up,
in the demand-distribution loop.

Extraction is three lines: count each edge id across every `<route edges="...">` in the
iteration's `.rou.xml`, then compare vectors between iterations.

## A doubly-constrained model cannot move demand away from the CBD

Because `sum_i T_ij = A_j` is a hard constraint, the share of trips attracted to the CBD
was **exactly 66.6667 % at every iteration of every doubly-constrained variant**. Feedback
changed trip lengths and *which origins* served the CBD, and nothing else. If the question
is "does congestion push activity out of the centre", the destination margin has to be
free — use a singly (production) constrained model, where the same feedback loop moved
CBD attraction **59.5 % → 49.2 % (−17.4 % of CBD trips)** and raised network speed ~9 %.
Stating a CBD-redistribution result from a doubly-constrained run is a category error.

## Deterrence function is a convergence parameter too

At an identical calibrated mean trip length, on the converged skim:

| deterrence | β | IPF iterations | loop gain at +10 % skim |
|---|---|---|---|
| exponential exp(-βc) | 0.03497 | 31 | 0.669 |
| gamma c^-1.0 exp(-βc) | 0.02532 | 26 | 0.571 |
| gamma c^-1.5 exp(-βc) | 0.02051 | 23 | **0.502** |

A combined/gamma function with α = 1.5 has **25 % lower loop gain** and needs **26 % fewer
IPF iterations** than the pure exponential at matched behaviour — a legitimate lever on a
marginally unstable loop. All gains are **< 1**, so the gravity map itself is a
contraction: **the instability lives in the assignment half**, which is where damping
must act.

## Gotchas

- **β is demand-scale-independent.** Calibrated identically (0.034970) at 7000 and 12400
  trips, because scaling P and A scales T proportionally and leaves mean trip length
  unchanged. Recalibrate when the *skim* changes, not when the demand level does.
- **IPF cost explodes with β.** 2 iterations at β = 5e-4, 194 at β = 0.20 on the same
  16-zone problem. Check the **achieved margin error**, not the multiplier change, and
  assert it — `furness()` returns `max_rel_margin_error`.
- **Intrazonal impedance c_ii is invented, and it drives a lot.** Intrazonal share ran
  4.1 % → 39.4 % across the β sweep and 15.3 % → 25.7 % through the feedback loop.
  Compute c_ii over real within-zone connector pairs with `s == t` **excluded** (an
  included `s == t` pair is a zero-cost trip that will dominate the diagonal), and always
  report the share — a too-cheap c_ii makes a congested equilibrium look like a demand
  collapse.
- **Pass `--different-source-sink` to od2trips.** Verified 0 of 6997 trips had
  `from == to` with it; without it, intrazonal cells produce degenerate zero-length trips.
- **od2trips writes concrete `from`/`to` edges plus `fromTaz`/`toTaz`, and duarouter
  preserves the TAZ attributes** — so routing is genuinely edge-to-edge and no zero-cost
  TAZ connector arcs enter the network. Verify this in the route file rather than
  assuming it; the same `fromTaz`/`toTaz` pass-through is what lets tripinfo be
  aggregated back to OD pairs.
- **Size the demand with an explicit sweep before running any loop.** This network's
  capacity knee was between 7000 and 8000 veh/h (6.23 m/s / 2 teleports vs 2.60 m/s /
  143 teleports). A feedback loop run above the knee measures teleport artifacts, not
  equilibrium — see [[teleport-artifacts-and-gridlock-resolution-validity]].
- **Near the knee, one iteration can gridlock by chance.** Before calling a bad late
  iteration a divergence, re-run that iteration's matrix under several fresh seeds.
- **`edgeData`'s `file=` path resolves relative to the additional file's own directory**,
  so give it an absolute path when many runs share a layout (see
  `analyze-simulation-outputs`).

## Related

- `convert-od-matrix-to-trips` ([[od2trips]]) — the TAZ/O-format conventions this skill's
  step 6 uses verbatim.
- `convert-trips-to-routes` ([[duarouter]]) — step 7; `--weight-files` on the previous
  iteration's `edgeData` is what makes the assignment congestion-responsive.
- `compute-dynamic-user-equilibrium` ([[dynamic-user-equilibrium-and-wardrop]]) — the
  inner-loop equilibrium this skill deliberately replaces with a single all-or-nothing
  pass plus outer MSA. Its MSA-oscillation lesson (an undamped custom MSA can oscillate
  violently on a congested network) reproduces exactly here, one level up in the loop
  hierarchy.
- `assign-traffic-with-marouter` — a faster macroscopic alternative for the inner
  assignment, with the capacity-reference caveat in
  [[marouter-macroscopic-assignment]].
- `estimate-od-matrix-with-odme` ([[od-matrix-estimation-and-underdetermination]]) — the
  inverse problem; contrast, don't transfer.
- `quantify-sumo-run-to-run-variability` — the noise-floor discipline this skill depends
  on; here it is not optional, it is the yardstick for every convergence claim.
- `analyze-simulation-outputs`, `run-simulation`, `create-grid-network` — the underlying
  run/analysis/network steps.
- [[four-step-model-feedback-loop-convergence]] — the methodology and the verified
  convergence findings behind this skill.
