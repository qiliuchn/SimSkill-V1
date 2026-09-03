---
name: analyze-intersection-air-quality-hot-spots-from-microsimulation
description: Use this skill when the user wants a project-level air-quality hot-spot / receptor-concentration analysis at a signalized intersection (EPA CO/PM/NOx conformity-style analysis), needs to carry SUMO's microsimulated emissions through a dispersion model to a receptor grid, or wants to know whether the delay-minimizing signal timing is also the pollution-minimizing one. Covers extracting emissions at multiple spatial resolutions from the same run (fleet total, whole-edge, 25m segments), a verified CAL3QHC-style Gaussian finite-line-source dispersion model, and a critical finding: whole-edge-averaged emission rates severely understate peak receptor concentration and mislocate the hot spot relative to spatially-resolved segment rates. Also documents a subtle --emission-output units gotcha that is silently masked at step-length=1.0s. Trigger on mentions of air quality hot spot, CAL3QHC, receptor concentration, dispersion model, or intersection emissions conformity analysis.
---

# Analyze Intersection Air-Quality Hot Spots from Microsimulation

**Whole-edge-averaged emission rates understate peak receptor
concentration by roughly half, and put the hot spot tens of meters from
where it actually is.** Verified on a 4-leg signalized intersection
(0.85–0.93 v/c, 8% heavy-vehicle fraction, HBEFA4 fleet), 12 CRN-replicated
scenario runs, a CAL3QHC-style finite-line-source dispersion model
independently validated against a closed-form solution, and a 360°
wind-direction sweep.

## Emissions are heavily concentrated at the stop line, not spread along the approach

Binning vehicle-level `--emission-output` records by longitudinal
position into 25 m segments shows NOx emission rate in the 0–25 m
stop-line bin is **10.2–11.9× higher** than the 300–325 m cruise-zone
bin, across every tested signal-timing scenario (CO ratio 6.8× in the
representative scenario). At each scenario's own measured queue-storage
length (the p95 back-of-queue distance over stopped vehicles, which
itself varied 117–212 m across scenarios depending on the plan), that
zone alone accounted for **roughly 72–87% of each approach's own NOx
emissions** and **roughly 47–62% of the whole intersection's total NOx**
including cross-street approaches. **A whole-edge-averaged emission rate
used as a dispersion-model input throws away this concentration entirely
— it treats a 300+ m approach as a single uniform source when in reality
the overwhelming majority of the mass is emitted from a ~100–200 m zone
next to the stop line.**

## The edge-average-vs-segment bias is the headline, quantified finding

Feeding whole-edge-averaged emission rates into the same dispersion model
instead of 25 m segment-resolved rates, across every tested scenario and
36 wind directions (144 scenario×wind cells): **off-roadway peak NOx
concentration was understated by a mean of 56.9% (range 41.3–68.5%)**,
with the predicted hot-spot **location** shifting a mean of 19.2 m (up to
44.0 m) from its true position. CO showed the same pattern at a smaller
magnitude (mean −35.1%, range 24.9–47.2%). Restricting to the full
receptor grid (including on-network cells) widened the NOx bias further
(mean −66.9%). **This is not a marginal modeling choice — an edge-average
input can miss the true peak concentration by half and place the hot spot
tens of meters from the real one.** Whenever a project-level hot-spot
analysis sources emission rates from SUMO's `edgeData` output rather than
vehicle-level position-resolved data, state this limitation explicitly or
switch to segment-resolved rates.

## The dispersion model: build it, then verify it against a closed form before trusting any receptor number

A CAL3QHC-style finite-line-source model was implemented: each 25 m
segment is its own line source with its own emission rate (g/m/s),
integrated as 25 ground-level Gaussian point sub-sources per segment with
full ground reflection, Briggs (1973) urban stability-class sigma
formulas. **Verify the numerical line-integral implementation against the
closed-form infinite-line Gaussian solution** (`C = 2·q_L /
(√(2π)·σ_z·u)`) before trusting anything — in this study the numerical
model matched the closed form to 0.0000% relative error at every tested
downwind distance (5–200 m). Two further verification checks worth
running on any such pipeline: **receptor grid resolution is itself a real
source of bias** (a 5 m grid understated the true off-road peak by 10.6%
relative to a 1 m grid in this study — always resolve the grid finely
enough to actually land a point near the true peak); and a sensitivity
check on the minimum-downwind-distance cutoff (`X_MIN`) used to avoid a
Gaussian singularity at the source showed **the impact is genuinely
receptor-dependent, not uniformly negligible** — one corner receptor
changed <1% across a 0.25–4 m X_MIN sweep, while two others at the same
setback distance changed 3–4%, depending on which sources happen to sit
closest to that specific receptor under the tested wind direction. Don't
generalize an X_MIN sensitivity result from a single receptor.

## Mass reconciliation: verify it, expect small pollutant-dependent gaps, and label scope differences honestly

Total emitted mass fed into the dispersion model matched the raw
trajectory-derived total exactly (differences at floating-point
precision, ~1e-12 to ~3e-12 relative — i.e. exact by construction, since
both are built from the same underlying per-vehicle records).
Whole-edge `edgeData` totals ran systematically **0.2–1.0% below** the
trajectory total, with the gap **pollutant-dependent** — CO/NOx/CO2 sat
around 0.2–0.5% low, while PMx ran roughly twice that (up to ~1%) — a
genuine, small, systematic effect from how `edgeData` and per-vehicle
trajectory records attribute a step's emissions differently at edge
boundaries, not a bug. Comparing against `tripinfo`'s per-trip emission
totals showed a **larger, ~2.9% gap** for a completed-trips-only
comparison window — correctly understood as a **scope** difference (a
different vehicle population and time extent than the windowed
trajectory total), not a reconciliation error. Always report which of
these three quantities ("all emissions in the analysis window,"
"edge-attributed emissions," "completed-trip emissions") a reconciliation
figure actually compares.

## Minimum delay does not reliably coincide with minimum peak concentration

Comparing a baseline signal plan, a true delay-minimizing cycle length
(found via a brute-force sweep, not assumed from Webster's formula — see
below), and a longer, "smoother" cycle: the delay-minimizing plan was
the lowest-concentration plan at only **19 of 36 tested wind
directions** for NOx (baseline won 13, the long-cycle plan won 4) — a
majority tendency, not an identity. At one specific receptor, the
delay-minimizing plan was measurably *worse* for NOx than both
alternatives (checked and confirmed, not an outlier artifact). **A
signal-timing choice cannot be assumed to jointly optimize delay and air
quality; both must be evaluated explicitly, at the receptor level, across
a range of wind directions.**

## A plausible "longer cycle reduces stop-and-go emissions" hypothesis is refuted

Lengthening the cycle substantially (intended as an emissions-targeted
measure, reasoning that fewer stop-start cycles per hour should reduce
idling emissions) instead made every measured outcome worse: delay rose
~52% relative to the delay-optimal cycle, total NOx rose ~20%, and
worst-case peak receptor concentration rose ~7%. **A longer cycle
lengthens the time each vehicle spends idling in queue more than it
reduces the number of stop-start events — the net effect on both delay
and emissions is negative, not positive.** Do not assume cycle-length
extension is an emissions countermeasure without checking; in this study
it was the opposite.

## A non-signal-timing measure can win at every wind direction, by relocating emissions, not just reducing them

A heavy-vehicle turn restriction (removing trucks from the exclusive left
turn lane — the movement with the shortest green and heaviest idling —
and routing that demand into the through movement instead) cost a
negligible delay penalty (<1%) while cutting the worst-case peak NOx
concentration and winning at **all 36 of 36** tested wind directions —
categorically stronger and more consistent than either signal-timing
alternative. Verified mechanism, not assumed: total intersection NOx fell
by only ~2%, but NOx emitted in the 0–25 m stop-line bin specifically
fell by ~11% — **the win comes from spatially redistributing where
emissions occur (out of the highest-idling movement), not primarily from
reducing total emitted mass.** A hot-spot analysis should consider
demand-management and lane-assignment measures alongside signal timing,
since they can move the source away from the queue-zone concentration
this skill's other findings show dominates the receptor result.

## Wind direction dominates concentration level and hot-spot location more than the signal plan does

At a single fixed plan, worst-case-over-wind peak off-road NOx varied by
roughly 8% across the 36 tested wind directions; at a single fixed wind
direction, the spread across different signal-timing/demand plans was
comparable in magnitude to the plan-driven differences themselves, and
the different plans' hot-spot locations coincided at only about a fifth
of tested wind directions. **Report a hot-spot analysis result across a
full wind-direction sweep, not a single assumed prevailing wind** — the
choice of wind direction can matter as much as the traffic-engineering
choice being evaluated.

## With a modern (HBEFA4) fleet, CO is essentially a non-issue; NOx/PM is where the analysis matters

The worst modeled 1-hour off-roadway CO concentration across every
scenario and wind direction sat roughly two orders of magnitude below a
typical 1-hour CO air-quality standard. **A project-level hot-spot
analysis using a modern vehicle fleet should focus on NOx and PM, not
CO** — CO conformity, historically the dominant concern for this kind of
analysis, is not where a modern fleet's emissions profile creates risk.

## Gotchas

- **`--emission-output` reports instantaneous RATES (mg/s), not per-step
  masses.** Naively summing the reported values and treating the sum as
  total mass is silently, exactly correct only at `--step-length 1.0`
  (where the numeric coincidence hides the bug) and becomes **2× too
  high** at `--step-length 0.5`. Multiply each record by the actual step
  length, verified at four step lengths (1.0/0.5/0.25/0.1 s) with a small,
  step-length-proportional residual at trip boundaries.
- **netconvert re-origins network coordinates** so all values are
  non-negative — a junction authored at (0,0) can compile to a
  substantially different absolute position. Always read the compiled
  node's actual coordinate back from the compiled net and translate any
  externally-defined geometry (like a receptor grid) accordingly, rather
  than assuming source-XML coordinates survive compilation unchanged.
- **`ElementTree.iterparse` child-clearing order trap**: clearing a
  sibling element can clear a child element before its parent's `end`
  event fires, causing `element.find(...)` on the parent to silently
  return `None`/a default value rather than raising an error — this can
  make a cross-check read as exactly zero without any exception. Clear
  only the specific elements you're done with, not broadly.
- **A detector group pooling flow across two physical approaches must be
  divided by the number of pooled approaches** before it can be used as
  a single-approach flow in a saturation-flow or Webster-style
  calculation — otherwise the resulting "saturation flow per lane" comes
  out physically impossible (too high) and the derived critical-flow
  ratio is proportionally wrong.
- **A signal-plan XML writer that formats duration as an integer can
  silently produce a cycle length one second longer than the nominal
  design value** — always read the realized cycle length back from the
  compiled `tlLogic`, not from the design parameter used to generate it.
- **Receptor grid resolution is itself a real, quantifiable source of
  bias in a hot-spot analysis**, not a purely computational convenience —
  verify the true peak is actually landed on by comparing against a finer
  grid before reporting a coarse-grid peak concentration as final.

See `simulate-fleet-emissions` and [[vehicle-emissions-modeling]] for the
HBEFA4 vType/emission-class setup this skill's fleet composition builds
on, `measure-saturation-flow-and-validate-webster-method` for the
measured-saturation-flow and Webster methodology this skill's
delay-minimizing-cycle comparison reuses, and `analyze-simulation-outputs`
for the `edgeData` file-path-resolution gotcha this skill's per-run
additional-file handling works around.
