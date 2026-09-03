---
summary: How to turn SUMO microsimulation output into a defensible benefit-cost analysis (NPV, BCR, incremental BCR, FYRR, switching values), and the verified findings from a three-alternative signalized-arterial appraisal — most importantly that linear interpolation between an opening and a horizon year overstates NPV by 128-196% because benefits are convex in demand, that standalone BCR ranks mutually exclusive alternatives wrongly, and that an uncalibrated conflict-to-crash factor can silently become 96-119% of total benefits.
keywords:
  - benefit-cost-analysis
  - net-present-value
  - incremental-bcr
  - value-of-time
  - annualization
  - switching-values
  - conflict-to-crash
created: 2026-08-04T11:00:00
last_updated: 2026-08-05T04:00:00
sources:
  - "[[episodic-memory/2026-08-04_11-00-00/outputs/appraisal/appraisal_summary.csv]]"
  - "[[episodic-memory/2026-08-04_11-00-00/outputs/appraisal/interpolation_pv_impact.csv]]"
  - "[[episodic-memory/2026-08-04_11-00-00/outputs/appraisal/parameter_provenance.csv]]"
  - https://www.epa.gov/system/files/documents/2023-12/epa_scghg_2023_report_final.pdf
  - https://epa.gov/benmap/sector-based-pm25-and-ozone-benefit-ton-estimates
related_pages:
  - "[[sumo-stochastic-variability-and-replication-design]]"
  - "[[surrogate-safety-measures]]"
  - "[[vehicle-emissions-modeling]]"
  - "[[left-turn-storage-bay-length-design]]"
  - "[[tlscycleadaptation]]"
  - "[[accessibility-measurement-and-transport-equity]]"
  - "[[network-safety-screening-and-crash-prediction]]"
  - "[[tlscoordinator]]"
  - "[[sumo-time-discretization]]"
  - "[[webster-method]]"
  - "[[sumo-output-files]]"
related_skills:
  - appraise-project-alternatives-with-benefit-cost-analysis
  - analyze-simulation-outputs
  - optimize-signals-by-tlscycleadaptation
  - optimize-signals-by-tlscoordinator
  - simulate-fleet-emissions
  - analyze-intersection-safety-with-ssm
  - quantify-sumo-run-to-run-variability
  - design-left-turn-storage-bay-length
related_skills_for_graph_view:
  - "[[appraise-project-alternatives-with-benefit-cost-analysis]]"
  - "[[analyze-simulation-outputs]]"
  - "[[optimize-signals-by-tlscycleadaptation]]"
  - "[[optimize-signals-by-tlscoordinator]]"
  - "[[simulate-fleet-emissions]]"
  - "[[analyze-intersection-safety-with-ssm]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[design-left-turn-storage-bay-length]]"
---

# Transport Economic Appraisal from Microsimulation

Microsimulation answers "which design performs better". Economic appraisal answers
"which design is worth building" — a different question whose answer is usually
dominated not by the simulation but by the monetisation, annualisation and
discounting assumptions bolted onto it. This page records the methodology and the
verified findings from the first end-to-end appraisal built in this memory: a
5-intersection signalized arterial with three mutually exclusive alternatives,
54 SUMO runs (3 alternatives x 3 demand levels x 6 Common Random Number seeds).
See `appraise-project-alternatives-with-benefit-cost-analysis` for the workflow.

## The test case

A 1.6 km arterial with five signalized intersections at 400 m spacing, two lanes per
direction, one-lane cross streets, AM peak demand of ~2,800 veh/h with a deliberately
eastbound-dominant flow, left turns concentrated at J2/J3, and a 12.5% heavy-vehicle
fleet (HBEFA3 classes). Alternatives:

- **A (do-nothing)**: a Webster fixed-time plan sized for the demand of 8 years
  before opening, uncoordinated, never retimed again.
- **B (operational)**: `tlsCycleAdaptation --unified-cycle` + `tlsCoordinator`
  offsets, recomputed each analysis year. $180k capital, $30k/yr recurring.
- **C (capital)**: exclusive left-turn bays on all four approaches at J2 and J3
  (verified lane-isolated), which let netconvert generate protected left-turn
  phasing, *plus* B's retiming package. $4.78M capital, 30-year life.

Validity was confirmed before any economics: zero teleports, zero real collisions,
zero insertion backlog, and identical analysed trip sets across alternatives in all
54 runs.

## Verified finding: two-point interpolation overstates NPV by 128-196%

Standard appraisal practice models an opening year and a horizon year and
interpolates the annual benefit stream linearly between them. Tested here by
simulating a genuine mid year (demand-growth exponent k=10) and withholding it as an
out-of-sample check:

| quantity | 3-point (piecewise) | 2-point (single line) | error |
| --- | --- | --- | --- |
| B mid-year hourly benefit | $237/peak-h (simulated) | $1,153/peak-h | **+388%** |
| C mid-year hourly benefit | $1,098/peak-h (simulated) | $3,684/peak-h | **+236%** |
| B: PV of benefits | $2.35M | $4.61M | +96% |
| C: PV of benefits | $7.96M | $14.34M | +80% |
| B: NPV | $1.76M | $4.02M | **+128%** |
| C: NPV | $3.25M | $9.63M | **+196%** |
| incremental BCR (C vs B) | 1.36 | 2.36 | +74% |

**Mechanism**: delay is convex in demand, so the annual benefit stream is convex in
time. A straight line between two points on a convex curve lies *above* it, so every
intervening year is overbooked. The error is largest for the alternative whose base
case degrades fastest. This is not a rounding-level concern — it is large enough to
flip an incremental BCR across 1.0 and therefore to change the recommended
alternative. **Simulate at least three demand levels and interpolate piecewise
between bracketing simulated points.**

A related trap: benefits must be indexed by demand **level**, not by year index. If
the appraisal maps appraisal year `t` straight onto simulated point `t-1`, then
re-running it with a different assumed growth rate changes nothing, and the
demand-growth bar in the tornado chart comes out at zero width while looking like a
legitimate finding. The correct mapping is
`k = (t-1) * ln(1+g_assumed) / ln(1+g_simulated)`.

## Verified finding: standalone BCR ranks mutually exclusive alternatives wrongly

| | PV benefits | PV costs | NPV | BCR | FYRR |
| --- | --- | --- | --- | --- | --- |
| B (operational) | $2.35M | $0.59M | $1.76M | **3.99** | 27.8% |
| C (capital) | $7.96M | $4.70M | $3.25M | **1.69** | 0.4% |
| C vs B (incremental) | $5.61M | $4.11M | $1.49M | **1.36** | — |

Standalone BCR ranks B more than twice as highly as C. The incremental BCR — the
correct rule for mutually exclusive options — is 1.36 > 1, so the extra $4.11M of
present-value cost buys $5.61M of extra present-value benefit and **C is the correct
recommendation**. A report showing only standalone BCRs would have recommended the
wrong alternative. The seed-to-seed spread confirms the ranking is not noise:
NPV(C) − NPV(B) = $1.49M, 95% CI [$0.90M, $2.08M], p = 0.0013, and the incremental
BCR exceeded 1.0 in all six seeds (range 1.15-1.50).

**FYRR catches a failure NPV hides.** C's first-year rate of return is **0.42%** — a
first-year net benefit of only $20,140 against $4.78M of capital. In the opening year
C is actually *worse than doing nothing on travel time* (paired ΔVHT = **−1.95 h**,
p = 0.008), because protected left-turn phasing and the longer cycle it forces (53 s
vs 30 s) cost more delay than the bays save until left-turn demand grows into them;
the barely-positive net figure comes only from the safety and emissions terms
offsetting that travel-time disbenefit. **A project can be strongly NPV-positive over
20 years and still be roughly a decade too early to build** — NPV alone cannot see
this, FYRR can.

## Verified finding: an uncalibrated conflict-to-crash factor swamps the appraisal

Converting SSM conflict counts to crash costs is the weakest link in any
simulation-based appraisal. An apparently reasonable placeholder of **1 crash per
10,000 severe conflicts (TTC<1.5 s)** produced:

- safety = **96% to 119%** of total benefits,
- alternative B's PV of benefits **negative** (−$13.4M),
- a nonsensical implied ~1.5 crashes per peak hour on a five-intersection corridor.

The fix is to **back-calculate the factor so the do-nothing base reproduces an
assumed corridor crash frequency**, rather than to assert a ratio:

```
conflicts_per_crash = base_severe_conflicts_per_peak_hour * peak_hours_per_year
                      / (base_crashes_per_year * peak_share_of_crashes)
```

With 6,274 severe conflicts per peak hour, 18 crashes/yr and 25% of them in the 500
appraised peak hours, this gives **~697,000 severe conflicts per crash — 70x the
naive guess** — and moves safety to a plausible 28.5% of alternative C's benefits and
−9.8% of B's. The calibration additionally absorbs any *uniform* scale error in SSM
counts, which matters given the verified factor-of-~7 sensitivity of absolute
severe-conflict counts to time-discretisation settings ([[sumo-time-discretization]]).
It does not absorb a *differential* error between alternatives, so the safety term
remains **ordinal** evidence. The residual assumption — that crash risk is strictly
linear in severe-conflict count — is not established by the surrogate-safety
literature and should always be stated.

## Verified finding: retiming and coordination made the corridor less safe

Alternative B's safety benefit is **negative**: −$230k PV, −9.8% of its benefits. At
the horizon year B had **1,087 more** severe conflicts per peak hour than the
do-nothing base (p = 0.00003), despite saving 69 vehicle-hours of delay. This is the
same mechanism [[surrogate-safety-measures]] records for signalization generally —
tighter coordination releases larger, denser platoons, and the extra conflicts are
overwhelmingly rear-end/following. Alternative C, which adds protected left-turn
phasing, reverses it (+5,054 fewer severe conflicts at horizon). **A signal-timing
improvement justified on delay should not be assumed to be safety-neutral.**

## Verified finding: benefit terms differ enormously in statistical reliability

Paired (CRN) tests across 6 seeds, with the replication count required for the 95% CI
half-width to fall below the mean effect:

| comparison | metric | significant at 95%? | replications needed |
| --- | --- | --- | --- |
| A→B, opening | VHT saving | yes (p=0.003) | 2 |
| A→B, opening | severe conflicts | **no** (p=0.76) | **220** |
| A→B, mid | severe conflicts | **no** (p=0.38) | **26** |
| A→C, all years | VHT saving | yes (p<0.01) | 2 |
| A→C, all years | severe conflicts | yes (p<0.001) | 2 |

**A single appraisal number can rest on one term that is rock solid and another that
is pure noise.** Report the required-replication count per benefit component, not per
study. Note also that Common Random Numbers *hurt* here for several comparisons
(variance-reduction factors of 0.6x for A→B at both mid and horizon years), consistent
with [[sumo-stochastic-variability-and-replication-design]]'s finding that CRN is not
universally beneficial.

## Parameter provenance: only 4 of 14 parameters were genuinely citable

The appraisal's credibility depends on never letting an assumption pass as a
measurement. Emit a provenance table alongside the results.

**Cited**: SC-CO2 $190/tCO2 (US EPA 2023 SC-GHG report, 2% near-term rate);
value of time $24.01/veh-h car and $80.16/veh-h truck (TTI Urban Mobility Report
2024); NOx $14,700/t and PM $158,000/t (US EPA sector-based benefit-per-ton) — but
the last two are **sector transfers** from cement kilns, not on-road mobile sources,
and SUMO reports **PMx**, not PM2.5, so applying a PM2.5 damage cost slightly
overstates that term.

**Pure placeholders**: non-fuel VOC $0.20/veh-km, fuel $1.00/L, crash cost
$150k, base crash frequency 18/yr, peak share of crashes 25%, and all capital and
recurring costs.

**Stated assumptions**: 500 equivalent peak-hours/year (AM+PM x 250 weekdays, with
off-peak and weekend benefits set to zero — conservative for congestion relief, but it
*understates* VOC/fuel/emissions, which accrue in every hour); 7% real discount rate;
1.5%/yr demand growth; 20-year appraisal period.

## Verified finding: what the recommendation is actually fragile to

Switching values (the parameter value at which the stated conclusion reverses):

| parameter | central | NPV(C) = 0 | ranking flips to B |
| --- | --- | --- | --- |
| demand growth | 1.5%/yr | **1.17%/yr** | **1.29%/yr** |
| discount rate | 7% | 10.9% | 9.07% |
| value of time | 1.0x | 0.33x | 0.43x |
| capital cost of C | 1.0x | 1.77x | 1.36x |
| conflict-to-crash factor | 1.0x | never (in range) | 2.49x |
| annualisation | 500 h/yr | 295 h/yr | 367 h/yr |

**Demand growth is by far the widest tornado bar and has the tightest switching
value** — a fall from 1.5% to 1.29%/yr, well inside normal forecasting error, reverses
the recommendation from C to B. The recommendation is a bet on traffic growth far
more than on any traffic-engineering result. Notably the *simulation* inputs are the
most robust part of the chain and the *forecast and financial* inputs the least — the
opposite of where modelling effort usually goes.

## Practical takeaways

- Build the do-nothing base as a **stale but sane** signal plan, never netconvert's
  default program — the default gridlocked this corridor (8.3 km/h) where a Webster
  plan ran at 13.6 km/h on identical demand, which would have fabricated most of the
  retiming benefit.
- Window measures on **intended** departure (`depart - departDelay`) and count
  `departDelay` as travel time, or alternatives get scored on different trip sets and
  the most-delayed travellers vanish from the statistics.
- Simulate a **mid year**; do not interpolate linearly from two points.
- Report **incremental BCR** and **FYRR**, not just standalone BCR and NPV.
- Re-run the whole appraisal **per seed** and report CIs on NPV, rather than
  appraising seed-averaged inputs.
- Check the demand level against the **capacity knee** — here served throughput
  plateaued at ~3,880 veh/h and delay quadrupled between 85% and 100% of it.
- **Always pass an explicit `--device.ssm.file`.** Verified: `--device.ssm.probability
  0.0` does not disable an SSM device enabled by a vType `has.ssm.device` param, and
  with no output file set SUMO writes one `ssm_<vehID>.xml` per vehicle into the
  working directory (162 files from a 302-vehicle control run; 8,705 accumulated
  unnoticed across this study's calibration runs). Setting the file collapses this to
  a single output; only removing the vType param actually turns the device off.
  See also [[surrogate-safety-measures]], which documents the related path-mangling
  reason for never setting `device.ssm.file` as a vType param.
- Verify geometry artefacts **empirically**: static analysis of the net file predicted
  a 1.5% corridor shortening (and a spurious travel-time benefit) for the
  lane-addition alternative, but the measured per-trip difference over 4,200 trips was
  −0.32 m — negligible, and in the opposite direction.
