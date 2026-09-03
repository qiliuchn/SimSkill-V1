---
summary: A SUMO toll plaza built as a physical multi-server queueing facility does not obey M/M/c — it behaves as c independent M/G/1 queues whose service time is the booth transaction plus a deterministic 4.28 s car-following move-up floor, giving a squared service CV of 0.39 rather than 1.0; with those two measured corrections the Pollaczek-Khinchine formula reproduces simulated queue delay to within 10% over rho 0.40-0.88, while M/M/c is wrong by up to 88x, real booth capacity is 35-59% below the textbook 3600/E[S], a TraCI join-the-shortest-queue assigner closes 69-91% of the gap to the pooled ideal, and dedicated electronic-toll lanes never outperform all-mixed-use booths at any penetration.
keywords:
  - toll-plaza
  - queueing-theory
  - M/M/c
  - Pollaczek-Khinchine
  - service-time-distribution
  - headway-floor
  - join-shortest-queue
  - electronic-toll-collection
created: 2026-08-04T17:30:00
last_updated: 2026-08-04T17:30:00
sources:
  - "[[episodic-memory/2026-08-04_16-00-00/outputs/step2_mechanism_verification.json]]"
  - "[[episodic-memory/2026-08-04_16-00-00/outputs/step3_results_table.csv]]"
  - "[[episodic-memory/2026-08-04_16-00-00/outputs/step4_gap_closure.json]]"
  - "[[episodic-memory/2026-08-04_16-00-00/outputs/step5_design_study.json]]"
  - "[[episodic-memory/2026-08-04_16-00-00/outputs/crosscheck_independent.json]]"
related_pages:
  - "[[cordon-tolling-and-e3-detectors]]"
  - "[[managed-lanes-empty-lane-paradox-and-person-throughput]]"
  - "[[zipper-merge-lane-drop-discharge]]"
  - "[[sumo-stochastic-variability-and-replication-design]]"
  - "[[teleport-artifacts-and-gridlock-resolution-validity]]"
  - "[[roundabout-capacity-law-and-demand-metering]]"
  - "[[sumo-output-files]]"
  - "[[vehicle-class-lane-permissions]]"
  - "[[hcm-control-delay-vs-sumo-delay-metrics]]"
related_skills:
  - model-toll-plaza-as-queueing-facility
  - model-cordon-tolling-with-generalized-cost-surcharge
  - model-managed-lanes-with-dynamic-tolling-and-self-selection
  - compare-zipper-vs-default-merge-at-lane-drop
  - implement-alinea-ramp-metering
  - create-single-intersection
  - quantify-sumo-run-to-run-variability
  - set-vehicle-state
related_skills_for_graph_view:
  - "[[model-toll-plaza-as-queueing-facility]]"
  - "[[model-cordon-tolling-with-generalized-cost-surcharge]]"
  - "[[model-managed-lanes-with-dynamic-tolling-and-self-selection]]"
  - "[[compare-zipper-vs-default-merge-at-lane-drop]]"
  - "[[implement-alinea-ramp-metering]]"
  - "[[create-single-intersection]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[set-vehicle-state]]"
---

# Toll-Plaza Queueing and the Service Headway Floor

A toll plaza is the one piece of road infrastructure that is literally a textbook queueing
system: `c` parallel servers, customers arriving at random, a random service time. This page
records what happens when that system is built as physical microsimulation geometry in SUMO
(a 2-lane mainline fanning into six single-lane booth channels and back) and its delay is
compared against closed-form M/M/c, M/D/c, M/G/c and single-server predictions. The short
answer is that microsimulation and queueing theory **do** agree — but only against the right
model, and only after two corrections that no textbook formula contains.

All figures below come from raw SUMO 1.27.1 output (`stop-output`, `instantInductionLoop`,
`laneAreaDetector`, `entryExitDetector`, `tripinfo`, `summary`) over 120 replicated sweep runs
plus 80 design-study runs, and were independently re-derived through a second parsing path.
**Zero teleports occurred in any sweep run**, so none of the congested results are
gridlock-resolution artifacts (cf. [[teleport-artifacts-and-gridlock-resolution-validity]]).

## Verified finding: the car-following move-up floor is a deterministic additive constant

At a saturated booth the server is not free the instant a transaction ends. The next vehicle
must release its brakes, accelerate from rest, and roll forward into the booth. Measured
directly from `stop-output` as `started[k+1] - ended[k]`, this **move-up gap is 4.28 s and is
essentially invariant** to the service-time distribution and to its mean:

| intended service | realized E[S] | realized CV | move-up gap | saturated departure headway |
|---|---|---|---|---|
| exponential, 8 s | 8.141 s | 0.954 | **4.28 s** | 12.438 s |
| Erlang-8, 8 s | 8.229 s | 0.355 | **4.28 s** | 12.512 s |
| deterministic, 8 s | 8.000 s | 0.000 | **4.29 s** | 12.286 s |
| exponential, 3 s | 3.047 s | 0.966 | **4.33 s** | 7.369 s |

Because the gap is additive and deterministic, the effective service time is
`S' = S + 4.28 s`, and two things follow that matter more than they first appear.

**Capacity.** A booth serves `3600/E[S']`, not `3600/E[S]`: **289 veh/h instead of 450** at 8 s
service (a **35.7% shortfall**), and **489 instead of 1200** at 3 s service (a **59.3%
shortfall** — worse, because a fixed floor is a larger share of a shorter transaction). In the
design case here, sizing a plaza on `3600/E[S]` called for 4 booths where simulation required
**7**; the 4-booth plaza put a 1113 m queue on the mainline and 120 s of insertion backlog.

**Variability.** A deterministic component added to a random one *reduces* the coefficient of
variation. A nominally exponential (C² = 1) transaction becomes a shifted exponential whose
squared CV, measured from the saturated departure headways, is **C²ₛ = 0.389**. **A SUMO
plaza is an M/G system rather than an M/M system purely as a consequence of car-following**,
independent of how the analyst chose to draw the service times.

## Verified finding: the plaza is c independent M/G/1 queues, not M/M/c

With booths chosen at random on generation (a Bernoulli split of a Poisson stream), simulated
mean queue delay was compared against five closed-form models, all fed the **measured**
`E[S'] = 12.438 s` and `C²ₛ = 0.389` — nothing fitted:

| rho | SUMO Wq (±95% CI) | M/M/c | M/D/c | M/G/c Allen-Cunneen | 6×M/M/1 | **6×M/G/1 (P-K)** | sim / P-K |
|---|---|---|---|---|---|---|---|
| 0.30 | 3.04 ± 0.51 | 0.03 | 0.03 | 0.02 | 5.41 | **3.76** | 0.81 |
| 0.41 | 5.35 ± 1.02 | 0.15 | 0.10 | 0.10 | 8.49 | **5.90** | 0.91 |
| 0.51 | 8.75 ± 2.67 | 0.45 | 0.27 | 0.32 | 12.97 | **9.01** | 0.97 |
| 0.61 | 13.36 ± 3.28 | 1.09 | 0.62 | 0.76 | 19.31 | **13.42** | 1.00 |
| 0.70 | 21.32 ± 1.94 | 2.39 | 1.29 | 1.66 | 29.51 | **20.50** | 1.04 |
| 0.81 | 36.88 ± 6.32 | 5.96 | 3.12 | 4.14 | 53.57 | **37.22** | 0.99 |
| 0.88 | 61.53 ± 15.22 | 12.54 | 6.44 | 8.71 | 94.78 | **65.84** | 0.93 |
| 0.95 | 123.91 ± 50.67 | 39.13 | 19.76 | 27.18 | 255.86 | **177.75** | 0.70 |

**M/M/c is wrong by 3x to 88x and is never within a factor of three.** M/D/c and Allen-Cunneen
M/G/c are worse still — all three assume one pooled queue feeding whichever server frees
first. The Pollaczek-Khinchine formula for `c` **independent** M/G/1 queues,
`Wq = rho_i·E[S']·(1+C²ₛ)/(2(1−rho_i))`, matches to **0.91-1.04 over rho = 0.40-0.88**.

The physical reason is a geometric commitment, not a modelling choice: a vehicle picks a booth
channel upstream and, once inside the plaza, physically cannot jockey to a booth that empties
first. Pooling — the defining assumption of M/M/c — is exactly what a plaza's islands
prevent.

**Per-booth load imbalance is not the explanation.** Across-booth throughput CV under random
routing was 0.037-0.067, statistically indistinguishable from the multinomial sampling floor
`1/sqrt(n/c) = 0.065`. The booths were as evenly loaded as random routing can make them; the
gap to M/M/c comes from the queues being *separate*, not from the loads being *unequal*.
Always compare an observed imbalance against that noise floor before treating it as real.

### Where the agreement breaks down, and why

- **Below rho ≈ 0.4** (sim/P-K = 0.81) theory over-predicts: at light load a vehicle often
  arrives at an idle booth and drives straight in without paying the move-up penalty, whereas
  `E[S']` charges it unconditionally. The floor is a *busy-server* phenomenon.
- **Above rho ≈ 0.9** (sim/P-K = 0.70 and falling) simulation delay drops *below* theory, from
  two physical causes: a finite 5400 s demand horizon never reaches the infinite-horizon
  steady state, and upstream platooning makes per-booth arrivals sub-Poisson (C²ₐ < 1), which
  reduces delay below the C²ₐ = 1 prediction. The 95% CI also blows out to ±41% of the mean —
  the near-capacity bimodality of
  [[sumo-stochastic-variability-and-replication-design]]. Five seeds is not enough there.

**Little's Law holds on the simulated data** to −0.35%…+1.35% across all 24 (arm, rho) cells,
checked on the e3 `entryExitDetector`'s own independently-computed in-zone vehicle count and
mean in-zone travel time. The disagreement with M/M/c is a disagreement about *assumptions*,
not a measurement error.

## Verified finding: join-the-shortest-queue closes most, but not all, of the gap

A TraCI assigner that routes each arriving vehicle to the booth with the fewest queued
vehicles cut mean queue delay by **65% at rho = 0.81** (36.88 → 12.93 s) and 64% at rho = 0.95
(123.91 → 43.99 s), closing **69-91%** of the distance from random assignment to the pooled
Allen-Cunneen M/G/c ideal, with the residual falling from 3.12× Allen-Cunneen at rho = 0.81 to
**1.61× at rho = 0.95** — the expected convergence of JSQ toward the single-queue result under
heavy traffic.

The residual is **not** the headway floor: the same `E[S']` and `C²ₛ` already fit the random
arm to within 10%. It is the **no-jockeying constraint** — a committed vehicle still cannot
move to a booth that empties first, which is exactly what M/G/c assumes and the plaza forbids.

**Counter-intuitive, verified: moving the decision point closer to the plaza made JSQ worse.**
Deciding at 1150 m along a 1196 m approach (fresher queue information, minimal commitment lag)
was worse at every rho than deciding at 600 m — 15.33 vs 12.93 s at rho = 0.81 — and closed
only 44-66% of the gap instead of 69-91% at low-to-mid rho. The bottleneck is execution, not
information: there is not enough remaining distance to complete the strategic lane change onto
the approach lane that feeds the chosen booth. **Fresher information is worthless if the
vehicle cannot physically act on it**, and this rules out decision lag as the explanation for
the residual. The disadvantage narrows sharply at high congestion (71.8% and 81.7% gap closure
at rho = 0.875 and 0.95, comparable to the front-loaded arm) — under heavy queueing, even a
short remaining distance is enough time for the lane change, since vehicles are moving slowly.

## Verified finding: report per-booth DELAY imbalance, not utilisation imbalance

Server utilisation is close to conserved across assignment policies — the same total work is
performed by the same servers — so busy fraction has little room to differ. At rho = 0.80 the
across-booth CV of busy fraction moved only **0.035 → 0.014** under the assigner, while the
across-booth CV of per-booth mean queue delay moved **0.154 → 0.053**. Reporting only
utilisation CV would have made an intervention that cuts delay by 65% look nearly useless.

## Verified finding: a low-speed edge is not a server

A speed-based booth — the intuitive alternative to a `<stop>` — **fails completely**, and the
failure is quantified rather than assumed. A 30 m segment limited to 3.75 m/s (nominally 8 s
of "service") produced a mean saturated departure headway of **5.892 s**, versus **5.871 s
with no booth at all** — within **0.4%** of imposing no constraint whatsoever. A low-speed
*segment* holds roughly four vehicles simultaneously at car-following spacing, so its capacity
is the link formula `v/(v·tau + L + minGap)` ≈ 1200 veh/h/lane, several times what a real
booth delivers. It is a slow link, not a single-customer server. The same reasoning applies to
any drive-through, gate, weigh station or border crossing: only a `<stop>` with
`parking="false"` creates a genuine one-customer-at-a-time server.

## Verified finding: dedicated ETC lanes never beat all-mixed-use booths

Sweeping transponder penetration 0 → 100% at a fixed 1500 veh/h across six booths (ETC 3 s vs
manual 8 s service, dedication implemented as compiled `allow="custom1"` lane permissions —
see [[vehicle-class-lane-permissions]]), all-mixed-use booths were **best or statistically
tied at every penetration tested**. A penetration-matched dedication (k = round(6·penetration))
was indistinguishable from mixed at 20%, 40% and 90% and much worse elsewhere (+204 s at 0%,
+94 s at 60%, +61 s at 80%); a fixed 2-lane dedication was worse everywhere.

The mechanism is the classical pooling result — partitioning `c` servers into two groups is
never better than pooling them — amplified by lane granularity: with only six lanes the split
can be set in 1/6 steps, and most mismatches drive one group's sub-plaza above rho = 1 (k = 1
at 0% penetration leaves five manual booths carrying all 1500 veh/h at rho = 1.04; k = 4 at
60% leaves two manual booths carrying 600 veh/h, again rho = 1.04). This is the empty-lane
paradox of [[managed-lanes-empty-lane-paradox-and-person-throughput]] reappearing in a
service-facility rather than a mainline-capacity setting. The real-world case for dedicated
ETC lanes is geometric and behavioural (higher speeds, no braking, safety separation) — the
queueing-efficiency argument for them is actually *negative*.

## Verified finding: the plaza never becomes queue-free while vehicles still stop

Mixed-use mean queue delay fell monotonically **54.3 s → 4.0 s** as penetration went 0 → 100%,
crossing 5 s at roughly **96% penetration**. But it never reaches zero: at 100% ETC the plaza
still imposes **4.00 ± 0.21 s** of mean queue delay and a 19.1 s 95th percentile, because a
3 s transaction still carries the 4.33 s move-up floor. Only removing the stop entirely gets
to zero — an open-road run over the same geometry showed **3.41 s** of e3 zone time loss
versus **7.53 s** at 100% ETC, and that 3.41 s is purely the geometric cost of the retained
20 km/h booth islands, which a real gantry over unmodified mainline would not have.

## Verified finding: the cordon abstraction is right for a gantry and wrong for a plaza

[[cordon-tolling-and-e3-detectors]] models a toll as a perceived-cost surcharge with **real
travel time and capacity untouched**. Running that same e3 instrumentation over a physical
plaza at 1500 veh/h shows what the abstraction cannot represent: a 1736.7 veh/h capacity
ceiling, 54.3 s of mean queue delay (166.4 s at the 95th percentile) against the cordon's
structural zero, 1113 m of mainline spillback and 120 s of insertion backlog once the plaza is
undersized, and per-booth delay imbalance for which the cordon model has no concept at all.
**At the all-electronic endpoint the two models agree** (3.41 s of geometric time loss versus
the cordon's zero) — which is the useful boundary: a cordon abstraction is a correct model of
an all-electronic toll and understates a manual plaza's delay by roughly **16x** at
rho = 0.86. The crossover sits at the same ~96% penetration found above.

## Spillback and the queue-length ceiling

Sweeping booth count downward at fixed demand, the queue first touched the mainline at
rho = 1.04 (max 341 m, on the mainline 16.7% of the time), reached 1026 m at rho = 1.30
(48.9% of the time), and pinned at the 1195 m storage ceiling for 80% of the run at
rho = 1.73. **Once the storage ceiling is reached, on-road queue length saturates and stops
discriminating** — the excess demand moves into `tripinfo`'s `departDelay` (0.3 s → 120.4 s →
884.4 s across c = 5, 4, 3). This is the same ceiling effect documented in
[[zipper-merge-lane-drop-discharge]]; reporting only queue length would make a badly
undersized plaza look like a marginally undersized one. Served flow tracked plaza capacity
rather than collapsing, because an isolated plaza model has nothing upstream for the queue to
block — genuine mainline throughput collapse needs an upstream junction and cannot be claimed
from this geometry.

## Practical takeaways

- Measure the move-up gap before applying any queueing formula; `3600/E[S]` overstates booth
  capacity by 35% at 8 s service and 59% at 3 s.
- Compare against the **partitioned** models (c×M/G/1) as well as the pooled ones; a plaza
  without jockeying is not M/M/c.
- Feed formulas the measured `E[S']` and `C²ₛ`, not nominal values — car-following changes
  both.
- Model any single-customer server with `<stop>`, never a low-speed edge.
- Judge booth imbalance by per-booth delay, and against the `1/sqrt(n/c)` multinomial noise
  floor, not by utilisation.
- Zero `speedDev` and never clip negative measured delays when the quantity of interest is a
  few seconds of queueing.

See the `model-toll-plaza-as-queueing-facility` skill for the full network build, the
service-mechanism verification protocol, the shortest-queue assigner, and the sizing workflow.
