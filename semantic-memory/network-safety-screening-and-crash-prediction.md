---
summary: HSM network safety screening — safety performance functions, negative-binomial overdispersion, the Empirical Bayes estimator, regression-to-the-mean bias, and crash modification factors — connected to SUMO's simulated surrogate conflicts on a 20-site synthetic jurisdiction with known ground truth; simulated conflict frequency ranked sites as well as three years of real crash data (Spearman 0.924 vs 0.878), but a type-matched conflict ratio agreed with a published left-turn CMF to within 3% while the aggregate conflict ratio disagreed by 30%, and the single "conflicts per crash" factor that benefit-cost analysis needs varied 23x across sites and 4.6x between control types.
keywords:
  - safety-performance-function
  - empirical-bayes
  - regression-to-the-mean
  - crash-modification-factor
  - network-screening
  - overdispersion
  - conflict-to-crash
created: 2026-08-04T19:00:00
last_updated: 2026-08-04T21:00:00
sources:
  - "[[episodic-memory/2026-08-04_19-00-00/outputs/analysis/screening_comparison.csv]]"
  - "[[episodic-memory/2026-08-04_19-00-00/outputs/analysis/rtm_years_sweep.csv]]"
  - "[[episodic-memory/2026-08-04_19-00-00/outputs/analysis/cmf_crosscheck.csv]]"
  - "[[episodic-memory/2026-08-04_19-00-00/outputs/analysis/transfer_function_models.csv]]"
  - "[[episodic-memory/2026-08-04_19-00-00/outputs/analysis/conflicts_per_crash_factor.json]]"
  - "[[episodic-memory/2026-08-04_19-00-00/outputs/analysis/site_table.csv]]"
  - https://onlinepubs.trb.org/onlinepubs/nchrp/nchrp_wod_297Draft.pdf
  - https://www.fhwa.dot.gov/publications/research/safety/18044/18044.pdf
related_pages:
  - "[[surrogate-safety-measures]]"
  - "[[left-turn-treatment-tradeoffs]]"
  - "[[driver-desired-speed-and-speed-enforcement-evaluation]]"
  - "[[transport-economic-appraisal-from-microsimulation]]"
  - "[[sumo-stochastic-variability-and-replication-design]]"
  - "[[unsignalized-vs-signalized-intersection-control]]"
  - "[[signal-clearance-intervals-dilemma-zone-and-safety-capacity-tradeoff]]"
  - "[[mutcd-signal-warrants-and-the-demand-vs-served-volume-trap]]"
  - "[[sumo-time-discretization]]"
  - "[[webster-method]]"
related_skills:
  - screen-network-safety-with-spf-and-empirical-bayes
  - analyze-intersection-safety-with-ssm
  - compare-left-turn-signal-treatments
  - quantify-sumo-run-to-run-variability
  - appraise-project-alternatives-with-benefit-cost-analysis
  - create-single-intersection
related_skills_for_graph_view:
  - "[[screen-network-safety-with-spf-and-empirical-bayes]]"
  - "[[analyze-intersection-safety-with-ssm]]"
  - "[[compare-left-turn-signal-treatments]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[appraise-project-alternatives-with-benefit-cost-analysis]]"
  - "[[create-single-intersection]]"
---

# Network Safety Screening and Crash Prediction

Every safety capability previously in this memory measures conflicts at *one*
site ([[surrogate-safety-measures]]). Safety *investment*, however, is decided by
network screening: rank all sites in a jurisdiction, treat the worst. The
governing methods are the Highway Safety Manual's — safety performance functions,
the Empirical Bayes estimator, and crash modification factors — and none of them
consume microsimulation output. This page records what happened when the two were
connected on a synthetic 20-intersection jurisdiction where the ground truth was
generated deliberately, so that every screening method could be *scored* rather
than merely compared. See `screen-network-safety-with-spf-and-empirical-bayes`
for the workflow.

## The machinery

**Safety performance function (SPF)**: a negative-binomial regression of crash
frequency on exposure, `N_spf = exp(a + b·ln(AADT_maj) + c·ln(AADT_min))`, with
separate coefficients and a separate overdispersion parameter `k` per control
type. Verified, quotable values (NCHRP Web-Only Document 297, *Draft Text for the
Second Edition of the HSM*, Ch. 10, Eq. 10-8/10-9/10-EB/10-10):

| type | a | b | c | k | AADT_maj range | AADT_min range |
|---|---|---|---|---|---|---|
| 3ST | −9.86 | 0.79 | 0.49 | 0.54 | 0–19,500 | 0–4,300 |
| 4ST | −8.56 | 0.60 | 0.61 | 0.24 | 0–14,700 | 0–3,500 |
| 3SG | −5.88 | 0.54 | 0.23 | 0.31 | 0–23,591 | 0–23,320 |
| 4SG | −5.13 | 0.60 | 0.20 | 0.11 | 0–25,200 | 0–12,500 |

Two structural facts about these coefficients matter more than their values.
**All AADT exponents are below 1**, so crashes are sublinear in exposure — which
is why crash *rate* is a biased screening criterion (below). And **`k` varies by a
factor of five across control types** (0.11 for 4SG, 0.54 for 3ST), so the amount
of trust EB places in a site's own crash record is control-type-specific.

**Overdispersion**: `Var = N + k·N²`. `k` measures how badly the SPF fails to
explain site-to-site variation; `k → 0` is Poisson, and a smaller `k` is a more
reliable SPF.

**Empirical Bayes**, in annual units with `Y` years of data:

```
w    = 1 / (1 + k · N_spf · Y)
N_eb = w · N_spf + (1 − w) · N_observed_annual
```

## Verified finding: EB shrinkage depends on years, volume and k — in that order of magnitude

Measured across the 20-site inventory:

- **Years** dominates: the mean weight on the SPF fell from 0.44 at Y=1 to 0.074
  at Y=10 for the signalized sites. Ten years of data essentially reduces EB to
  the naive count.
- **Volume**: at fixed `k = 0.11`, w fell from 0.594 at the smallest signalized
  site (N_spf = 6.22) to 0.349 at the largest (N_spf = 16.99) at Y=1. A busy site
  is trusted to its own record; a quiet one is shrunk toward the SPF.
- **Overdispersion**: at essentially equal N_spf ≈ 1.03, the 4ST site
  (k = 0.24) got w = 0.801 while the 3ST site (k = 0.54) got w = 0.644 — a noisier
  SPF is trusted less, which is exactly what `k` is for.

## Verified finding: regression to the mean, quantified

With 2,000 Monte-Carlo crash histories per configuration, ranking by observed
frequency and asking how many of the naive top-3 were not truly top-3:

| years of data | naive false positives (of 3) | EB false positives | naive RTM drop | EB RTM drop |
|---|---|---|---|---|
| 1 | 1.67 | 1.38 | 32.3% | 28.2% |
| 3 | 1.33 | 1.19 | 17.7% | 16.0% |
| 5 | 1.12 | 1.04 | 11.7% | 10.9% |
| 10 | 0.90 | 0.87 | 6.4% | 6.1% |

"RTM drop" is the fall in the selected sites' observed crash count between the
selection period and an independent following period of equal length. **With one
year of data, more than half of a top-3 hotspot list is there by chance, and the
list's crash count falls a third by itself without any treatment** — the classic
mechanism by which an untreated hotspot programme appears to work. The naive
method converges toward EB as `Y` grows, exactly as the shrinkage weight predicts.

**EB's correction is real but modest here, and the reason is instructive**: the
true worst sites were all 4SG with `k = 0.11`, so `w` was small and EB sat close
to the observed count. EB helps most where the SPF is reliable and the record is
short — precisely the low-volume, high-`k` sites that are *not* usually the ones
competing for the top of a list.

## Verified finding: crash RATE is a badly biased screening criterion

Ranking by observed crashes per million entering vehicles achieved Spearman
ρ = 0.354 (95% CI −0.037 to 0.680) against true mean crash frequency, versus 0.878
for observed frequency — the worst of every method tested. The cause is
structural, not statistical: because SPF AADT exponents are below 1, crashes per
vehicle *decrease* with volume, so a rate criterion systematically promotes
low-volume sites. In the inventory, ranking by rate moved the smallest signalized
site from 14th to 1st and the largest from 1st to 13th. **Frequency and rate rank
sites differently, and for crashes the difference is enormous** (ρ between the two
orderings = 0.556, maximum rank shift 13 of 20). For *conflicts* the same
divergence exists but is much milder (ρ = 0.947, maximum shift 6), because
conflicts scale superlinearly with volume.

## Verified finding: simulated conflicts rank sites about as well as a few years of crash data

Scored against total-crash truth at Y = 3, MC = 2,000:

| method | Spearman ρ [95% CI] | hit rate @3 | FPR @5 |
|---|---|---|---|
| SPF (correctly specified — see caveat) | 1.000 | 1.000 | 0.000 |
| simulated conflict **frequency** | 0.924 | 0.667 | 0.133 |
| simulated crossing-conflict rate | 0.904 | 0.333 | 0.067 |
| Empirical Bayes | 0.908 [0.815, 0.968] | 0.602 | 0.111 |
| observed crash frequency | 0.878 [0.763, 0.954] | 0.556 | 0.121 |
| simulated conflict rate per MEV | 0.831 | 0.667 | 0.200 |
| observed crash rate per MEV | 0.354 [−0.037, 0.680] | 0.120 | 0.247 |
| EB **excess** over SPF | −0.038 [−0.482, 0.405] | 0.233 | 0.227 |

Simulated conflict frequency, computed with **no crash data whatsoever**,
out-ranked three years of actual crash counts. That is the strongest argument for
simulation-based screening — and it comes with three heavy qualifications, below.

**EB *excess* is nearly uncorrelated with total-crash truth (ρ ≈ −0.04).** It
answers "which site is worst relative to sites like it", not "which site has the
most crashes". The two are different screening questions and the criteria are not
interchangeable.

## The tautology caveat, stated plainly

If the ground truth is `C · SPF · CMF` and the screening SPF is the same formula,
the SPF scores ρ = 1.000 **by construction**. That is arithmetic, not evidence.
Two corrections were run:

1. **A genuinely mis-specified problem.** Screening for *angle* crashes with an
   SPF that lacks a left-turn-phasing inventory (the CMF is large here, so the
   blind SPF is really wrong): blind SPF ρ = 0.783, simulated crossing-conflict
   rate ρ = 0.710, crossing frequency 0.736, observed angle-crash frequency 0.802,
   EB 0.861. **The simulated conflict measure did not beat even a mis-specified
   SPF.** This is a negative result and it is the more honest half of the story.
2. **A persistent unmeasured site effect** (half the overdispersion made a fixed
   per-site multiplier rather than year-to-year noise — the realistic case, and
   the thing `k` is supposed to represent). Rankings invert: observed frequency
   0.921 now beats the SPF 0.887, EB beats both at 0.936, and the simulated
   conflict measure *falls* to 0.769 because it cannot see the unmeasured effect
   either. **A conflict measure recovers only exposure, geometry and operations —
   never the site-specific unmeasured characteristics that EB exists to capture.**

## Verified finding: simulation separates sites the SPF cannot distinguish

Two sites identical in every SPF covariate *and* in left-turn phasing — so
identical SPF predictions of 11.05 crashes/yr by construction — were differentiated
only by signal cycle length. Against a per-site noise floor established from a
12-seed replication family:

| cycle | total conflicts | rear-end | crossing | mean time loss |
|---|---|---|---|---|
| 35 s | +8.8% (2.3× noise floor) | +8.6% | +9.6% | +38.3% |
| 60 s (Webster) | baseline | baseline | baseline | baseline |
| 100 s | +14.2% (3.3×) | +20.1% | −17.4% | +25.3% |
| 140 s | +26.7% (8.1×) | +36.5% | −26.2% | +56.2% |

All differences are significant at conventional p < 0.01 (total conflicts at
35 s reaches p = 2.5×10⁻⁵; the 100 s and 140 s comparisons clear p < 10⁻⁴ on every
metric; the three 35 s per-category metrics are significant but land between
p = 0.0001 and p = 0.004, not below 10⁻⁴). **The effect is also non-monotone and
category-dependent**: a long cycle raises rear-end conflicts while *lowering*
crossing conflicts (fewer permissive-left service opportunities per hour), so
"which cycle is safer" has no single answer — a genuine safety trade-off that no
SPF or standard CMF represents.

**But note what this experiment can and cannot prove.** Because the ground truth
was generated from the SPF, both sites have identical true crash frequency by
construction. The result therefore demonstrates that the conflict measure is
*sensitive* to something the SPF is *blind* to. It cannot demonstrate that the
conflict difference corresponds to a real crash difference — nothing in this
design could.

## Verified finding: match the crash category or the CMF comparison is meaningless

Left-turn phasing CMFs differ by nearly an order of magnitude between crash
categories, and the aggregate one is essentially null (FHWA-HRT-18-044 Table 35
and its literature review of Hauer 2004 and Srinivasan et al.):

| treatment | total | left-turn | rear-end |
|---|---|---|---|
| permissive → protected/permissive | 1.023 (SE 0.016, n.s.) | 0.862 | 1.075 |
| permissive → protected-only | ≈1.0 | ≈0.30 | — |

On a matched-AADT phasing triplet the simulation reproduced this structure:

| comparison | simulated ratio | published CMF | disagreement |
|---|---|---|---|
| perm → prot/perm, **crossing** conflicts | 0.832 | 0.862 (left-turn) | **0.97×** |
| perm → prot/perm, **total** conflicts | 1.328 | 1.023 (total) | 1.30× |
| perm → prot-only, **crossing** conflicts | 0.563 | 0.300 (left-turn) | 1.88× |
| perm → prot-only, **total** conflicts | 1.293 | ≈1.0 (total) | 1.29× |

**The type-matched comparison agreed to 3%; the aggregate comparison disagreed by
30%.** A study that reported "protected lefts raised total conflicts 33%" against
a total-crash CMF of ~1.0 would conclude the simulation was badly wrong, when in
fact its crossing-conflict channel was nearly exact. Simulation over-delivers the
rear-end penalty (ratio 1.53 vs a CMF of 1.075) and under-delivers the
protected-only left-turn benefit (0.56 vs 0.30) — both directionally correct,
both quantitatively off.

**A safety warning fell out of the countermeasure run.** At the highest-volume
site, converting permissive to protected/**permissive** produced *no* change in
crossing conflicts (ratio 1.000, p = 0.99) but a **+141% increase in severe
(TTC < 1.5 s) crossing conflicts** (p = 3×10⁻⁶): the remaining permissive
left-turners face a shorter fill-in window against heavy opposing flow and accept
much tighter gaps. Protected-**only** at the same site cut crossing conflicts 40%
and severe crossing conflicts 82% (both p < 10⁻⁶), while mean time loss fell 4.4%
(p = 0.051, borderline) and throughput rose 0.6% (p = 3×10⁻⁵). This independently
reproduces and quantifies the mechanism noted in [[left-turn-treatment-tradeoffs]]
— protected/permissive can carry worse worst-case left-turn encounters than
permissive-only.

**The delay cost of left-turn protection is volume-dependent, and flips sign.**
At the high-volume site above, protection *reduced* delay. At the matched-AADT
triplet (18,000/7,000 AADT, ~2,230 veh/h entering), the same treatments *raised*
mean time loss by 39.6% (protected/permissive) and 50.5% (protected-only), both
p ≤ 10⁻⁶. Neither sign is safe to assume; measure it at the demand level in
question, consistent with the non-textbook efficiency ordering already recorded in
[[left-turn-treatment-tradeoffs]].

## Verified finding: the conflict-to-crash factor is not a constant

This is the calibration relationship
[[transport-economic-appraisal-from-microsimulation]] flagged as the weakest link
in any simulation-based appraisal. Measured directly:

- A log-log transfer function `ln(N_true) = b0 + b1·ln(conflict rate)` fits
  R² = 0.776, LOO-R² = 0.725, with a **95% prediction interval of ×/÷ 2.45**.
  Using conflict *frequency* instead does better: R² = 0.898, LOO-R² = 0.876,
  interval ×/÷ 1.83. For angle crashes on crossing conflicts it is worse:
  R² = 0.660, LOO-R² = 0.581, ×/÷ 2.79.
- The **single-factor "conflicts per crash" ratio varied 23.1× across the 20
  sites** (34,447 to 795,736 conflicts per crash at 500 equivalent peak hours/yr
  and a 25% peak share) and **4.6× between control types**: 109,661 (3ST),
  162,688 (4ST), 508,846 (4SG). Restricting to severe (TTC < 1.5 s) conflicts
  narrows it only to 3.9× (51,867 / 50,781 / 198,960). For reference, the
  back-calculated 697,000 severe-conflicts-per-crash figure in
  [[transport-economic-appraisal-from-microsimulation]] sits above every value
  here but within the same order of magnitude as the 4SG value — reassuring for
  that appraisal's calibration approach, and confirming that the factor must be
  back-calculated per network rather than asserted.
- **Transfer across control types fails badly.** A function fitted on
  stop-controlled sites and applied to signalized sites under-predicted angle
  crashes by 5.3× (median ratio 0.187, log-RMSE 1.64). The mechanism is
  identifiable: SUMO's junction model resolves priority conflicts by yielding
  with exact gap perception, so drivers never *misjudge* a gap — the dominant
  real-world angle-crash mechanism at two-way-stop intersections is absent from
  the model. SUMO therefore generates 5.6× more crossing conflicts per unit of
  true angle-crash risk at signalized sites than at stop-controlled ones.

**Conditions under which a conflict-to-crash transfer function should not be used
for policy**: (1) across control types, geometries or demand regimes not present
in the fitting set; (2) for absolute crash prediction rather than ordinal ranking
— a ×/÷ 2 to ×/÷ 3 prediction interval is wider than most benefit-cost decisions
can tolerate, and it does not include SSM's own factor-of-~7 sensitivity to
time-discretisation settings ([[sumo-time-discretization]]); (3) at sites whose
demand does not fully load (see below); (4) whenever the crash category and the
conflict category are not matched.

## Practical cautions established here

- **Oversaturated stop-controlled minor approaches silently truncate the
  measurement.** Three sites left 6.4–14.5% of demand never entering the network
  (`inserted / loaded` of 0.936, 0.908, 0.855), which shrinks both the conflict
  count and the entering-vehicle denominator. These were the highest-volume
  stop-controlled sites — exactly the ones an SPF ranks worst within their class.
  Always report `inserted/loaded` per site.
- **Required replication count varies by more than an order of magnitude across a
  jurisdiction**: 7 seeds at the busiest site, 158 at the quietest, at a ±5%
  half-width target, because conflict-count CV rises as counts fall (0.050 to
  0.317 here). Compute required-n per site and top up only where needed — the
  general point of [[sumo-stochastic-variability-and-replication-design]] applied
  to a network rather than a single scenario.
- **Common Random Numbers paid off cleanly for conflict-count before/after
  comparisons** — paired correlations of 0.71–0.85 and variance-reduction factors
  of 2.8–6.5 across the cycle-length ladder. This is the favourable end of the
  range in [[sumo-stochastic-variability-and-replication-design]], which also
  records CRN *hurting* a weakly correlated queue metric; conflict counts at a
  fixed geometry are strongly seed-correlated, so CRN helps here. It was measured,
  not assumed.
- **Replication genuinely matters for simulation screening**: a single-seed
  conflict ranking scored ρ = 0.838 [0.809, 0.874] where the fully replicated one
  scored 0.831–0.924 depending on the measure. The penalty is small but the CI is
  real, and it disappears for free once a seed family is run anyway.
- **`type="111"` SSM encounters are still not collisions.** Re-confirmed at scale:
  19 type-111 encounters across 988 runs against 0 collisions in both
  `summary.xml` and `--collision-output` — see [[surrogate-safety-measures]].
