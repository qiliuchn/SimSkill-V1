---
name: appraise-project-alternatives-with-benefit-cost-analysis
description: Use this skill when the user wants to turn SUMO simulation output into an economic investment decision — benefit-cost analysis, BCA/CBA, net present value, benefit-cost ratio, incremental BCR, first-year rate of return, value of time, monetised delay/fuel/emissions/crash savings, annualisation of peak-hour benefits, discounting a multi-year benefit stream, switching values, or a tornado sensitivity chart — as opposed to `analyze-simulation-outputs`, which stops at engineering measures (travel time, throughput) and never monetises anything. Covers designing mutually exclusive alternatives on one network, the replication design needed to make the economics defensible, and the monetisation/discounting layer. Trigger on mentions of benefit-cost, cost-benefit, BCA, NPV, BCR, economic appraisal, "is this project worth building", value of time, monetise, discount rate, sensitivity/switching values, or comparing a do-nothing base against operational and capital alternatives.
---

# Appraise Project Alternatives with Benefit-Cost Analysis

Turns SUMO microsimulation output into a defensible investment recommendation. Every
other analysis skill in memory answers "which design performs better"; this one
answers "which design is *worth building*", which is a different question with a
different failure mode — the answer is usually driven less by the simulation than by
monetisation and discounting assumptions, so the whole workflow is built around
making those assumptions visible and testing what they are worth.

## The pipeline

1. **Build one network, three alternatives.** A do-nothing base (A), a low-capital
   operational alternative (B), and a capital alternative (C). Demand and network
   skeleton must be shared; only the treatment differs.
2. **Replicate with Common Random Numbers** across alternatives and simulate at least
   three demand levels (opening, mid, horizon) — see "Simulate a mid year" below,
   which is the single highest-value methodological step here.
3. **Extract engineering measures** with `scripts/extract_measures.py` (VHT/VKT split
   by vehicle class, time loss, stops, fuel/CO2/NOx/PM from the emissions device,
   SSM severe-conflict counts, plus teleport/collision validity fields).
4. **Verify before believing** with `scripts/verify_batch.py` — CRN integrity,
   teleports, real-vs-SSM collisions, insertion backlog, CV and bimodality.
5. **Monetise, annualise, discount, decide** with `scripts/appraise.py`.
6. **Quantify the interpolation assumption** with `scripts/interp_impact.py`.

```bash
python scripts/verify_batch.py outputs/measures            # must pass first
python scripts/appraise.py --measures-dir outputs/measures --out-dir outputs/appraisal
python scripts/interp_impact.py outputs/measures work/interp out/interp_impact.csv
```

`appraise.py` expects measures files named `alt<A|B|C>_y<K>_s<SEED>.json`, where `K`
is the **demand-growth exponent in years since opening**, not a calendar year.

## Design the base case as a stale plan, not as netconvert's default

A do-nothing base built from netconvert's default `tlLogic` will hand every
operational alternative an enormous, fake benefit — the default program splits green
equally between an arterial and a minor cross street regardless of flow. In a
verified build this default gridlocked a corridor (mean speed 8.3 km/h, 82% of travel
time as delay) that a Webster plan ran at 13.6 km/h on the same demand.

Build the base instead as a **Webster plan sized for the demand of N years ago** and
never coordinated (`optimize-signals-by-tlscycleadaptation` without `--unified-cycle`
and without `tlsCoordinator`). That is what "the plan was last retimed in 2019"
actually means, and it keeps the retiming benefit honest. Alternatives B and C then
get `--unified-cycle` plus `optimize-signals-by-tlscoordinator`, recomputed per
analysis year — which is also what the recurring retiming cost in the cost table is
buying.

Design the signal plans against a **separate demand realisation** (a different seed)
from the ones the alternatives are scored on, or each plan is tuned to the exact
noise it is about to be evaluated against.

## Simulate a mid year — linear interpolation from two points is badly wrong

Standard practice is to model an opening year and a horizon year and interpolate
annual benefits linearly between them. **Verified: that overstates PV of benefits by
80-96% and NPV by 128-196%.**

Benefits are strongly **convex** in demand, because delay is convex in demand near
capacity. A straight line between two points on a convex curve lies *above* the
curve, so every intervening year is overbooked. Measured out-of-sample against a
genuinely simulated mid year, the two-point line overpredicted the mid-year hourly
benefit by **236% (alt C) and 388% (alt B)**, and inflated the incremental BCR by 74%
— easily enough to flip a decision.

Simulate at least three demand levels and interpolate piecewise between the
*bracketing* simulated points. `scripts/interp_impact.py` re-runs the appraisal with
the mid point withheld so the error is measured, not assumed.

## Map appraisal years to demand LEVELS, not to year indices

The simulated points are demand *levels* `S0*(1+g_sim)^k`. If the appraisal is re-run
with a different assumed growth rate — which any sensitivity analysis will do — an
appraisal year must be mapped onto the equivalent simulated level:

```python
ratio = math.log1p(assumed_growth) / math.log1p(SIM_GROWTH)
benefit_in_year_t = interp(hourly_benefits, (t - 1) * ratio)
```

Indexing benefits by year instead makes the demand-growth sensitivity **silently do
nothing** — the tornado bar comes out at exactly zero width and looks like a real
finding. This was a live bug in the first version of this skill's script.

## Calibrate the conflict-to-crash factor; never assume it

Monetising safety needs conflicts converted to crashes. Do **not** invent a ratio: an
"obvious" 1 crash per 10,000 severe conflicts made the safety term **96-119% of total
benefits** and drove alternative B's PV of benefits negative — the entire appraisal
was a restatement of one unsourced number.

Instead, **back-calculate the factor so the do-nothing base reproduces an assumed
corridor crash frequency**:

```
conflicts_per_crash = base_severe_conflicts_per_peak_hour * peak_hours_per_year
                      / (base_crashes_per_year * peak_share_of_crashes)
```

On the verified corridor this gave ~697,000 severe conflicts per crash — **70x** the
naive guess — and moved safety to a plausible 28.5% of alternative C's benefits. The
calibration also absorbs any *uniform* scale error in SSM counts, which matters
because this memory has verified that absolute severe-conflict counts move by a
factor of ~7 with time-discretisation settings alone ([[sumo-time-discretization]]).
It does **not** absorb a *differential* error between alternatives, so the safety term
stays ordinal evidence. State the residual linearity assumption explicitly.

## Report the incremental BCR — standalone BCR ranks options wrongly

For **mutually exclusive** alternatives the standalone BCR is the wrong decision rule.
Verified case: standalone BCR ranked B far above C (**3.99 vs 1.69**), but the
incremental BCR of C over B was **1.36 > 1**, so the extra capital genuinely pays for
itself and **C is the correct choice**. Reporting only standalone BCRs would have
recommended the wrong alternative. Always report
`ΔPV(benefits) / ΔPV(costs)` between the ranked non-base alternatives.

Also report FYRR — it catches a different failure. Alternative C's FYRR was **0.42%**
($20,140 of first-year net benefit against $4.78M of capital): in the opening year C
was *worse than doing nothing on travel time* (paired ΔVHT = −1.95 h, p = 0.008),
because protected left-turn phasing and the longer cycle it forces cost more delay
than the bays saved until left-turn demand grew into them. A project can be strongly
NPV-positive over 20 years and still be about a decade too early to build — NPV alone
cannot see this.

## Propagate simulation noise into the economics

Re-run the **entire appraisal once per seed** rather than appraising seed-averaged
inputs, then report the CI on NPV and on the incremental BCR. Also paired-test the
underlying measures (`scripts/verify_batch.py` and `paired_statistics.csv`).

Verified pattern: the delay-savings term was significant at 95% with **n=2** seeds,
while the **safety** term needed **220 replications** at opening year and 26 at mid
year to be distinguishable from noise, and was not significant at either. A single
appraisal number can therefore rest on one term that is rock solid and another that is
pure noise — report the required-replication count per term, not per study.

Keep demand away from the capacity knee if few seeds are affordable. Measure the knee
as the **peak of a served-throughput sweep** ([[sumo-stochastic-variability-and-replication-design]]);
on the verified corridor throughput plateaued at ~3,880 veh/h and delay quadrupled
between 85% and 100% of that, so the horizon year must be checked for whether it has
crossed it.

## Gotchas

- **Window the analysis on INTENDED departure (`depart - departDelay`), and add
  `departDelay` into VHT.** Windowing on actual departure silently gives each
  alternative a *different* trip set whenever one of them queues vehicles at the
  insertion point, breaking CRN; discarding departDelay makes a congested
  alternative look good by hiding its worst-affected travellers. With this fix the
  analysed `n_veh` is identical across alternatives — check it, it is a free
  CRN integrity test.
- **duarouter embeds the vTypes into its output route file.** Passing the same
  vTypes additional file to `sumo` as well fails with `Another vehicle type (or
  distribution) with the id 'x' exists`.
- **An `--` sequence anywhere inside an XML comment is a hard parse error** in
  SUMO's XML reader. Easy to hit when writing explanatory comments into a generated
  `.add.xml`.
- **`tlsCycleAdaptation` wrapper args `-b`/`--max-cycle` are ints**, not floats.
- **Widening an approach shortens the compiled edge** (netconvert cuts edges back to
  clear a larger junction shape), so a lane-addition alternative can look like it has
  a shorter corridor. Static analysis of the net file suggested a 1.5% shortening and
  a spurious travel-time benefit — but **measured over 4,200 real trips the per-trip
  difference was −0.32 m (the bay variant was marginally *longer*), i.e. negligible.**
  Measure the artefact from `tripinfo` `routeLength` rather than reasoning about it
  from junction geometry; keep the correction factor in the pipeline as a cheap guard.
- **SSM `type="111"` is not a real collision** — verified again here: 146-442
  type-111 encounters per alternative-year with `collisions=0` in both `summary` and
  `--collision-output` ([[surrogate-safety-measures]]).
- **Emission totals are in milligrams**, fuel included; convert explicitly.
- **The SSM log is ~70 MB per run.** Parse it to a small measures JSON and delete it
  inside the runner, or a 54-run batch leaves several GB behind.
- **`--device.ssm.probability 0.0` does NOT disable the SSM device** if a vType
  enabled it via `<param key="has.ssm.device" value="true"/>` — the vType param wins.
  Verified with a controlled 302-vehicle run: with the param set and probability 0.0
  and **no** `--device.ssm.file`, SUMO still ran the device and wrote **one
  `ssm_<vehID>.xml` per vehicle into the current working directory** (162 stray
  files; 8,705 accumulated across this study's calibration runs before it was
  caught). With `--device.ssm.file` set, the same run produced exactly one file.
  Removing the vType param produced none. **Always pass an explicit
  `--device.ssm.file`, even on runs where you do not want SSM output** (point it at
  a throwaway path), and disable the device by omitting the vType param rather than
  by setting probability to zero.
- **Label every monetary parameter's provenance in the code**, and emit it as
  `parameter_provenance.csv` alongside the results. This appraisal's credibility rests
  on nobody mistaking a placeholder for a measurement — of 14 parameters, only 4 were
  genuinely citable.

## Related

- `analyze-simulation-outputs` — the engineering-measures layer this sits on top of;
  use that alone when the question stops at "which performs better".
- `optimize-signals-by-tlscycleadaptation` / `optimize-signals-by-tlscoordinator` —
  build alternative B (and the stale base plan) with these.
- `design-left-turn-storage-bay-length` — the bay geometry and lane-isolation
  verification used for the capital alternative.
- `simulate-fleet-emissions` — the HBEFA3 fleet and emissions device that feed the
  fuel/CO2/NOx/PM monetisation terms.
- `analyze-intersection-safety-with-ssm` — the severe-conflict counts the safety term
  is calibrated from.
- `quantify-sumo-run-to-run-variability` — capacity-knee and replication methodology.
- [[transport-economic-appraisal-from-microsimulation]] — the verified findings,
  parameter provenance table and decision rules behind this workflow.
