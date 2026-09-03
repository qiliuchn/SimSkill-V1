---
name: evaluate-multimodal-accessibility-and-equity
description: Use this skill when the question is "who can reach what" rather than "how fast does traffic move" — cumulative-opportunity and gravity accessibility to jobs, isochrones, car-vs-transit accessibility gaps, Lorenz/Gini/Palma of accessibility, carless vs car-owning populations, transport poverty, distributional or equity appraisal of a road-vs-transit investment choice, or auditing a benefit-cost analysis for distributional blindness. Covers building congested zone-to-zone car skims with duarouter --weight-files on simulated edge travel times, true door-to-door intermodal transit skims from personinfo, calibrating the gravity decay parameter to the simulated trip-length distribution, and the free-flow / threshold / boundary / MAUP traps that reverse zone rankings. Trigger on accessibility, isochrone, opportunities reachable, gravity/impedance decay, skim matrix, transport equity, Gini or Palma of accessibility, distributional incidence, transport poverty, or "the BCA says A but who actually benefits".
---

# Evaluate Multimodal Accessibility and Equity

Turns a SUMO scenario into a **zone x zone x mode impedance skim**, then into
accessibility indices, then into a distributional verdict. `analyze-simulation-outputs`
stops at network performance and `appraise-project-alternatives-with-benefit-cost-analysis`
converts performance into one money number; this skill answers the question both of
those structurally cannot: *which people gained, and which did not*.

The failure mode here is not a crashed run — every step below produces a plausible
number from a broken input. Almost every check in this file exists because an
unchecked version of it silently produced a *different ranking of zones*.

## Pipeline

```bash
S=scripts
python $S/build_network.py      work                  # net + 25 TAZs + taz.add.xml
python $S/build_pt.py           work                  # busStops + scheduled lines
python $S/build_demand.py       work                  # pop/jobs, gravity OD, od2trips
python $S/run_equilibrium.py    work base base.net.xml 20    # duaIterate -> routes_base
python $S/build_skim_demand.py  work base             # intermodal probes + car probes
python $S/run_scenario.py       work base 1           # simulation of record (per seed)
python $S/build_skims.py        work base             # T_car(cong), T_car(ff), T_pt
python $S/verify_skims.py       work base             # <-- do not skip
python $S/accessibility.py      work                  # calibrate beta, all measures
python $S/equity_bca.py         work                  # Lorenz/Gini/Palma + BCA + H1-H4
python $S/seed_variability.py   work                  # replication spread + MAUP
python $S/plots.py              work outputs
python $S/make_tables.py        work outputs
```

## Zones, centroids and the sector-boundary trap

Define TAZs as **polar band x angular sector** on a radial network, and assign each
edge to its zone from the **exact from-node/to-node midpoint** — *not* from the lane
shape centroid. A radial edge lying exactly on a sector boundary gets pushed into the
neighbouring sector by the sidewalk lane offset alone. Verified: edge `F5G5` (exactly
180 deg) landed in sector 4 instead of 5. This is the MAUP boundary problem appearing
before any analysis has been done.

Emit a real TAZ file (`<taz><tazSource weight=.../><tazSink .../></taz>`, weights =
edge length share) for `od2trips`, and separately pick **one connector edge per zone**
for the skims — preferring an edge whose reverse direction also exists, then the one
nearest the length-weighted zone centroid. Use the *same* connector for car and
transit or the two skims are not comparable.

## The car skim: congested weights, and it is still biased low

Dump `<edgeData begin=0 end=3600 excludeEmpty="false">` from the simulation of
record, average `traveltime` across seeds into a `<meandata>` weight file, then

```bash
duarouter -n net.net.xml -r skim.trips.xml -o skim.rou.xml \
    --weight-files weights.xml --weight-attribute traveltime --weights.expand \
    --write-costs
```

`--write-costs` puts the routing cost on each `<route cost=...>` — that *is* the skim
value; there is no need to reconstruct it from edge weights.

**Validate it, do not assume it.** Take the skim's own route for a sample of OD pairs,
inject those exact edge sequences as probe vehicles into the simulation, and compare
`duration + departDelay`. Verified on 40 pairs x 3 departures per scenario: the skim
is biased **low by 4.8-6.0% on the mean**, median |error| 4.9-5.9%, p90 10.9-15.3%,
worst 27.2%; 78-83% of pairs within 10%. Interval-mean edge travel times cannot see
which minute of the peak a given trip departs in, nor turn-specific junction delay.

## The transit skim must be realised, not predicted

`duarouter` with `<personTrip modes="public">` produces the plan; **its cost is not the
skim**. Verified: duarouter's a-priori plan cost under-predicts the realised
`<personinfo>` door-to-door duration by **37% (base), 45% (road project), 28%
(transit project)** on average, with only 7-17% of pairs within 10%. The plan assumes
the timetable is met; in a congested run buses are late and riders miss connections.

So: route with duarouter, then **simulate the probes and take T_pt from
`<personinfo>`**, averaged over departure offsets that uniformly cover one headway
(4 offsets 150 s apart cover both a 600 s and a 300 s headway) and over seeds.

`<personinfo>` arithmetic (verified to reconcile exactly):
`duration = sum(walk.duration) + sum(access.duration) + sum(ride.waitingTime) + sum(ride.duration)`
— `ride@duration` is `arrival - depart` where `depart` is the **boarding** time, so it
**excludes** the wait. Decompose as access-walk / initial wait / in-vehicle /
transfer(walk+wait) / egress-walk from the leg order around the first and last `<ride>`.

## Unroutable pairs are the finding, not an error

- `duarouter` with `modes="public"` **never fails** when no line is usable: it returns
  a **walk-only plan**. Verified: 743/2400 base probes (31.0%) came back walk-only.
  Define the transit skim only on plans containing >= 1 `<ride>`; everything else is
  **infinite impedance**, i.e. "no transit option", and must be counted per zone.
- Verified base: **155 of 600 zone pairs (25.8%) have no transit option**, concentrated
  exactly where the study is pointed (OUTER_2 12/24 destinations unreachable, MID_6 and
  OUTER_6 10/24). Deleting them instead of zeroing them removes the deficit from the
  result.
- Car unroutable pairs were 0/600 here — report the zero, do not omit the check.

## Calibrating beta — and the two ways it goes wrong

Fit beta by bisection so the gravity model's mean trip time equals the **observed**
mean, on the **same support** for model and observation:

```
Tbar(beta) = sum_ij P_i s_i O_j e^{-beta T_ij} T_ij / sum_ij P_i s_i O_j e^{-beta T_ij}
```

with `s_i` the mode-relevant population share (car ownership for car, 1 - ownership for
transit) and intrazonal pairs excluded from both sides. Recover each demand vehicle's
OD **zone** from the first/last edge of its route in the routed `.rou.xml` so the
observed set can be restricted to interzonal trips (this also yields a free ~600-cell
observed car OD time matrix).

Two verified failure modes:

1. **The free-flow skim has no admissible beta at all.** Observed mean interzonal car
   time 654.7 s; the free-flow model's mean at `beta = 0` (its maximum) is only
   475.1 s. No `beta >= 0` reproduces the observed trip-length distribution — a
   free-flow accessibility study cannot even fit the data it claims to model.
2. **Re-calibrating per scenario silently changes the index.** beta_car came out
   0.0482 / 0.0324 / 0.0561 per minute for base / road / transit. Compute every
   scenario comparison at the **base** beta; a flatter re-calibrated beta makes any
   alternative look better for free.

Transit's calibrated beta was **0.0027/min vs car's 0.0482/min — 18x flatter** — so
the transit gravity index degenerates toward a plain reachability count. Report both
the mode-specific beta and a **common-beta** version for like-for-like mode comparison.

Intrazonal impedance: half-nearest-neighbour, `T_ii = 0.5 * min_{j != i} T_ij`, applied
identically to every skim and scenario so it cannot drive a comparison.

## Threshold saturation kills the cumulative measure

On a 3 km-radius city, `A_i(t*)` for car **saturates**: at `t* = 30` and `45` min all
25 zones tie at the full 71,400 jobs and Spearman is undefined. The conventional
15/30/45 grid is wrong for a compact study area. Informative range here was 5-15 min.
Ranking robustness measured: car rho(10,15) = 0.906 but rho(15,20) = **0.770**;
transit rho(10,15) = **0.394**. **Always print the saturation flag** (`max == min`)
next to every cumulative-opportunity number.

The gravity index is far more rank-robust: halving or doubling beta gave Spearman
1.000 / 0.999 (car) and 0.986 / 0.964 (transit) with 4-5 of the top 5 zones unchanged.
Cumulative-at-30-min vs gravity agreed only at rho = 0.661 for transit.

## The free-flow trap, quantified

Population-weighted, base scenario, same zones, only the skim changes:

| measure | congested | free-flow | overstatement | Spearman |
| --- | --- | --- | --- | --- |
| jobs within 5 min by car | 2,210 | 17,303 | **+683%** | 0.944 |
| jobs within 10 min | 23,557 | 54,177 | **+130%** | 0.928 |
| jobs within 15 min | 61,131 | 70,297 | +15.0% | **0.786** |
| gravity (fixed beta) | 41,501 | 48,823 | +17.6% | 0.976 |

Rank flips at t* = 10 min: INNER_6 3rd -> 9th, INNER_1 5th -> 2nd, MID_7 17th -> 13th,
OUTER_4 22nd -> 18th. **Name the flipping zones** — an aggregate overstatement figure
hides that the ordering itself changed.

**A free-flow skim cannot see capacity at all.** A lane addition changes nothing in a
free-flow skim except through the speed-limit component, so it *understates* the gain
from a pure capacity project even while it *overstates* the level. Verified for the
road project: free-flow predicted +2,623 jobs within 5 min vs +305 realised (88%
erosion), but at t* = 15 min and for the gravity index the congested gain was
**larger** than the free-flow gain. Direction of the erosion is threshold-dependent —
report the curve, not one number.

## Equity metrics

Population-weighted Lorenz over zones sorted by accessibility; Gini as `1 - 2*area`;
Palma as (share of accessibility held by the top 10% of population) / (bottom 40%),
with **within-zone interpolation** at the 10th/40th percentile boundaries — 25 zones
are far too coarse to snap to zone edges. Carless gap: car-owners get `A_car`, carless
get `A_pt`, each weighted by `P_i * c_i` and `P_i * (1 - c_i)`.

Verified base: Gini 0.164 (person) but **0.072 car-only vs 0.334 transit-only** — car
accessibility is nearly equally distributed and transit accessibility is not, so a
single-mode equity statistic is a choice of answer, not a measurement. Carless
accessibility was **4.12x lower** than car-owner accessibility.

### This skill models demographics as ZONE attributes — know what that costs

Everything above assigns each zone a car-ownership rate and an income index, then weights
zone-level outcomes by them. That is the standard approach and it is the only option when
demand is aggregate — but it is an **ecological estimator**, and its error has now been
measured directly against person-level truth
([[population-synthesis-and-aggregation-bias]], skill
`synthesize-population-and-generate-disaggregate-demand`):

- zone-averaging attributed a **32.8% car mode share to households owning no car** (a
  physically impossible 813 car trips/day), and understated the 2+-vehicle group by 18
  points;
- the zero-vehicle vs 2+-vehicle travel-burden ratio was **1.783x** in person-level truth
  and **1.006x** computed ecologically **on the very same simulation run** — a 78% gap
  compressed to 1%, and on a well-specified aggregate run it came out **0.936x, sign
  inverted**.

So treat carless-gap and by-income figures produced this way as *lower bounds on the
disparity*, and say so when reporting them. If the question is genuinely distributional —
who bears the delay, not how the network performs — the demand itself has to carry
household attributes; the accessibility machinery here is not the part that fails, the
zone-averaged demographics are.

One further trap, independent of aggregation: **monetising at an income-specific value of
time can erase the disparity even when person-level data is available** — a 2.09x
minutes-equivalent generalized-cost gap became 0.99x in EUR, because a lower-income
traveller's time is priced lower. Report minutes-equivalent alongside any monetised
figure.

## Testing whether BCA is distributionally blind — do it properly

Naively hoping the BCA ranking and the equity ranking disagree is not a test. Here they
**agreed** (transit project best on both; NPV +$17.2M vs -$98.6M, and -$22.5M for the
road project even at an equalised budget). Report that honestly, then demonstrate the
blindness where it actually lives:

- **Benefit incidence by zone group.** Road project: 66.8% of monetised benefit to the
  affluent inner ring, and the CORE was made **worse off** (-28.9% share); per capita
  the affluent gained 2.1x what the low-income periphery did. Transit project: 51.1% to
  the four low-income zones, and the affluent ring slightly *lost*. The BCA total is
  identical whichever of these two incidence patterns produced it.
- **Distributional weights** `w_i = (income index)^-e`. At `e = 1` the road project's
  weighted benefit falls 11% while the transit project's rises 31%, moving the ratio
  between them from 8.9x to 13.2x — invisible in the unweighted NPV.
- **What BCA cannot count at all**: 45 OD pairs / 113 transit trips per peak hour that
  had **no transit option** in the base gained one. There is no consumer-surplus
  triangle for a service that did not exist; the monetised benefit for those travellers
  is zero by construction.
- **Switching value**: the road project only out-benefits the transit project if
  transit users' time is worth less than **$1.80/h**. Report the switching value rather
  than asserting robustness.

## Replication discipline

Three seeds with common random numbers, paired per seed. Verified spreads: mean
per-person accessibility CV 0.13-1.06%; Gini SD 0.001-0.003. Paired differences vs
base were **sign-consistent across all three seeds** for every claim made
(road: Gini +0.0065, t = 3.5; transit: Palma -0.0389, t = -10.1) **except**
`altB mean car accessibility` (-248, t = -0.82, sign flipped between seeds) — that one
claim is noise and was reported as such. Run the *whole* skim rebuild per seed, not
just the simulation, or the seed-averaged weight file hides the variance.

**MAUP**: merging the 8 sectors of each band into 4 quadrants (25 -> 13 zones) left the
population-weighted mean identical by construction but moved Gini 0.1643 -> 0.1580
(-3.8%) and Palma 0.4972 -> 0.4859 (-2.3%). Every scenario comparison kept its sign;
no magnitude survived. **Boundary truncation**: dropping the 8 outer zones (6.2% of
jobs) cost interior zones 4.5-7.6% of cumulative accessibility, unevenly (INNER_2 lost
17.9% of transit accessibility vs MID_1's 5.8%), and dropped the rank correlation to
0.753 at t* = 20 min.

## Gotchas

- **`duaIterate.py` aborts if you re-pass an option it already sets.**
  `sumo--time-to-teleport`, `sumo--no-step-log`, `duarouter--ignore-errors` all fail
  with `A value for the option '...' was already set`. `sumo--seed` and
  `sumo--duration-log.statistics` are fine.
- **Use `--weight-memory`.** Without it, the road-project assignment oscillated
  596-700 s over 12 iterations and never converged; with it, 4 iterations.
- **A capacity project can destabilise an unrelated part of the network.** The widened
  radial re-routed flow into unsignalised peripheral priority junctions (E7/F7) and
  produced 67 teleports on one seed versus 2 in the base — a pure artefact that would
  have been reported as an equity finding about the poor periphery. Signalising those
  junctions **in every scenario** removed it (0 teleports in all final runs). Check
  teleport *locations*, not just counts ([[teleport-artifacts-and-gridlock-resolution-validity]]).
- **`--sidewalks.guess` skips edges above `--sidewalks.guess.max-speed` (default
  13.89 m/s).** 60 km/h arterials and a 70 km/h widened corridor would silently have no
  sidewalk and therefore no pedestrian access to their bus stops. Pass
  `--sidewalks.guess.max-speed 25` and verify every normal edge has a pedestrian lane.
- **SUMO rejects `|` in person ids** (`Invalid person id ... Contains invalid
  characters`). `#` works — matters when encoding `P#origin#dest#depart`.
- **od2trips O-format header is a 24-h clock and silently yields zero trips** if it does
  not overlap `-b/-e`. `7.00 8.00` with `-b 0 -e 3600` produced an empty file and exit
  code 0.
- **Every `<stop>` on a PT vehicle needs an absolute `until=`** or the intermodal router
  resolves everyone to walking ([[public-transport-and-intermodal-routing]]).
- **Peak fleet is max concurrent vehicles**, computed from bus `<tripinfo>`
  depart/arrival events — not the departure count. Getting this wrong inflated the
  transit project's capital cost 5x (51 buses instead of 16) and flipped its NPV from
  -$2.0M to +$17.2M.

## Related

- `simulate-multimodal-transit`, `build-gtfs-transit-scenario` — the PT layer this
  builds its transit skim on; [[gtfs-import-and-pt-representation-semantics]] if the
  lines come from a real feed instead of being hand-authored.
- `compute-dynamic-user-equilibrium` — produces the congested route set whose edgeData
  becomes the skim weights; its `--weight-memory` / oscillation lesson is load-bearing.
- `convert-od-matrix-to-trips`, `convert-trips-to-routes`, `assign-traffic-with-marouter`
  — the demand and assignment layer; `marouter` is the macroscopic alternative when a
  microsimulated skim is too expensive.
- `appraise-project-alternatives-with-benefit-cost-analysis` — the aggregate appraisal
  this skill audits; reuse its VOT/discounting/provenance discipline and add the
  incidence and distributional-weight layers here.
- `analyze-simulation-outputs`, `visualize-network-congestion-heatmap` — the
  performance-measure and network-plotting layers underneath.
- `create-spider-network`, `load-osm-network` — the monocentric geometry.
- [[transport-economic-appraisal-from-microsimulation]],
  [[discrete-network-design-and-project-interaction]],
  [[dynamic-user-equilibrium-and-wardrop]], [[sumo-output-files]],
  [[sumo-stochastic-variability-and-replication-design]].
