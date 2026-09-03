---
summary: A CAL3QHC-style Gaussian dispersion model driven by SUMO's microsimulated, position-resolved emissions (verified to 0.0000% error against a closed-form solution) found whole-edge-averaged emission rates understate peak receptor NOx concentration by a mean of 56.9% and mislocate the hot spot by a mean of 19.2m, because emissions are 10-12x more concentrated in the 25m nearest the stop line than in the cruise zone; the delay-minimizing signal cycle coincides with the concentration-minimizing plan at only 19 of 36 tested wind directions (a majority tendency, not an identity), a plausible "longer cycle reduces stop-and-go emissions" hypothesis is refuted (it worsened delay, total NOx, and peak concentration), and a heavy-vehicle turn restriction beat every signal-timing plan at all 36/36 wind directions by spatially redistributing emissions out of the highest-idling movement rather than by reducing total mass.
keywords:
  - air-quality-hot-spot
  - cal3qhc
  - dispersion-model
  - receptor-concentration
  - emission-output
  - gaussian-line-source
  - hbefa4
created: 2026-08-06T04:00:00
last_updated: 2026-08-06T04:00:00
sources:
  - "[[episodic-memory/2026-08-06_04-00-00/outputs/analysis/emissions_profile_by_bin.csv]]"
  - "[[episodic-memory/2026-08-06_04-00-00/outputs/analysis/queue_zone_fraction.csv]]"
  - "[[episodic-memory/2026-08-06_04-00-00/outputs/analysis/edgeavg_bias.csv]]"
  - "[[episodic-memory/2026-08-06_04-00-00/outputs/analysis/mass_reconciliation.csv]]"
  - "[[episodic-memory/2026-08-06_04-00-00/outputs/dispersion/verification.txt]]"
  - "[[episodic-memory/2026-08-06_04-00-00/outputs/analysis/scenario_comparison.csv]]"
  - "[[episodic-memory/2026-08-06_04-00-00/outputs/analysis/receptor_worstcase.csv]]"
  - "[[episodic-memory/2026-08-06_04-00-00/outputs/analysis/headline_stats.json]]"
  - "[[episodic-memory/2026-08-06_04-00-00/outputs/analysis/emission_output_units.txt]]"
  - "[[episodic-memory/2026-08-06_04-00-00/outputs/net/saturation_measurement.json]]"
  - "[[episodic-memory/2026-08-06_04-00-00/outputs/runs/sweep/cycle_sweep_summary.csv]]"
related_pages:
  - "[[vehicle-emissions-modeling]]"
  - "[[road-gradient-and-energy-consumption]]"
  - "[[webster-method]]"
  - "[[heavy-vehicle-passenger-car-equivalent-in-sumo]]"
  - "[[sumo-output-files]]"
related_skills:
  - analyze-intersection-air-quality-hot-spots-from-microsimulation
  - simulate-fleet-emissions
  - measure-saturation-flow-and-validate-webster-method
  - analyze-simulation-outputs
related_skills_for_graph_view:
  - "[[analyze-intersection-air-quality-hot-spots-from-microsimulation]]"
  - "[[simulate-fleet-emissions]]"
  - "[[measure-saturation-flow-and-validate-webster-method]]"
  - "[[analyze-simulation-outputs]]"
---

# Intersection Air-Quality Hot-Spot Analysis

Every prior emissions finding in memory stops at aggregate mass (g or
g/km). This page carries SUMO's microsimulated emissions all the way to
a receptor concentration — the question a project-level EPA conformity
analysis actually asks — via a verified CAL3QHC-style Gaussian
finite-line-source dispersion model, on a 4-leg signalized intersection
(0.85–0.93 v/c, 8% heavy-vehicle fraction, HBEFA4 fleet), 12 CRN-replicated
scenario runs, and a 360° wind-direction sweep.

## Emissions are heavily concentrated at the stop line

Binning vehicle-level emission records by longitudinal position into
25 m segments shows NOx emission rate in the 0–25 m stop-line bin is
**10.2–11.9× higher** than the 300–325 m cruise-zone bin, across every
tested signal-timing scenario (CO ratio 6.8× in the representative
scenario). At each scenario's own measured queue-storage length (varying
117–212 m depending on the plan), that zone alone accounted for roughly
**72–87% of each approach's own NOx** and **47–62% of the whole
intersection's NOx**. A whole-edge-averaged rate throws this away
entirely.

## Whole-edge-averaged emission rates understate the peak and mislocate the hot spot

Feeding whole-edge-averaged emission rates into the dispersion model
instead of 25 m segment-resolved rates, across every tested scenario and
36 wind directions (144 cells): **off-roadway peak NOx concentration was
understated by a mean of 56.9% (range 41.3–68.5%)**, with the predicted
hot-spot **location** shifting a mean of 19.2 m (up to 44.0 m). CO showed
the same pattern at smaller magnitude (mean −35.1%). Restricting to the
full receptor grid widened the NOx bias further (mean −66.9%). **An
edge-average input can miss the true peak concentration by half and place
the hot spot tens of meters from the real one** — this is not a marginal
modeling choice.

## The dispersion model, and how to verify one

The implemented model (each 25 m segment as its own line source, 25
ground-level Gaussian point sub-sources per segment with full ground
reflection, Briggs 1973 urban stability-class sigmas) matched the
closed-form infinite-line Gaussian solution `C = 2·q_L /
(√(2π)·σ_z·u)` to **0.0000% relative error** at every tested downwind
distance — verify any such implementation against this closed form
before trusting a receptor result. Receptor grid resolution is itself a
real bias source: a 5 m grid understated the true off-road peak by
**10.6%** relative to a 1 m grid. A sensitivity check on the minimum
downwind-distance cutoff used to avoid a Gaussian singularity found the
impact is genuinely receptor-dependent, not uniformly negligible — one
corner receptor changed <1% across a 0.25–4 m sweep, while two others at
the same setback distance changed 3–4%, depending on source geometry
relative to that specific receptor. Don't generalize a single receptor's
sensitivity result.

## Mass reconciliation: expect small, pollutant-dependent gaps, and label scope differences

Total mass fed to the dispersion model matched the raw trajectory total
exactly (floating-point precision). Whole-edge `edgeData` totals ran
systematically 0.2–1.0% below the trajectory total, with the gap
**pollutant-dependent** — CO/NOx/CO2 around 0.2–0.5% low, PMx roughly
twice that — a genuine, small effect from how edge-attributed and
per-vehicle records handle emissions at edge boundaries differently, not
a bug. A completed-trips-only (`tripinfo`) comparison showed a larger
~2.9% gap, correctly understood as a **scope** difference (different
vehicle population and time extent), not a reconciliation error. Always
state which of "all emissions in the window," "edge-attributed," or
"completed-trip" a reconciliation figure compares.

## Minimum delay does not reliably coincide with minimum peak concentration

Comparing a baseline plan, a true delay-minimizing cycle length (found
via a brute-force sweep, not assumed from Webster's formula), and a
longer "smoother" cycle: the delay-minimizing plan was the
lowest-concentration plan at only **19 of 36 tested wind directions** for
NOx — a majority tendency, not an identity. At one specific receptor the
delay-minimizing plan was measurably *worse* for NOx than both
alternatives. A signal-timing choice cannot be assumed to jointly
optimize delay and air quality; both must be evaluated at the receptor
level, across a wind-direction range.

## A "longer cycle reduces stop-and-go emissions" hypothesis is refuted

Lengthening the cycle substantially (reasoning that fewer stop-start
cycles per hour should reduce idling emissions) instead made every
measured outcome worse: delay rose ~52% relative to the delay-optimal
cycle, total NOx rose ~20%, and worst-case peak receptor concentration
rose ~7%. A longer cycle lengthens per-vehicle idling time more than it
reduces stop-start event count. Do not assume cycle-length extension is
an emissions countermeasure without checking.

## A non-signal-timing measure can win by relocating emissions, not just reducing them

A heavy-vehicle turn restriction (removing trucks from the exclusive left
turn lane — shortest green, heaviest idling — into the through movement
instead) cost a negligible delay penalty (<1%) while cutting worst-case
peak NOx and winning at **all 36 of 36** tested wind directions —
categorically stronger and more consistent than either signal-timing
alternative. Verified mechanism: total intersection NOx fell only ~2%,
but NOx emitted in the 0–25 m stop-line bin fell ~11% — the win comes
from spatially redistributing where emissions occur, not primarily from
reducing total mass.

## Wind direction dominates concentration level and hot-spot location as much as the plan does

At a fixed plan, worst-case-over-wind peak off-road NOx varied ~8% across
the 36 tested directions; at fixed wind, the spread across different
plans was comparable in magnitude to the plan-driven differences
themselves, and different plans' hot-spot locations coincided at only
about a fifth of tested wind directions. Report a hot-spot analysis
across a full wind-direction sweep, not a single assumed prevailing
wind.

## With a modern (HBEFA4) fleet, CO is essentially a non-issue

The worst modeled 1-hour off-roadway CO concentration across every
scenario and wind direction sat roughly two orders of magnitude below a
typical 1-hour CO air-quality standard. A project-level hot-spot analysis
using a modern vehicle fleet should focus on NOx and PM, not CO.

## Gotchas

- `--emission-output` reports instantaneous RATES (mg/s), not per-step
  masses. Naively summing values is silently, exactly correct only at
  `--step-length 1.0` (the numeric coincidence hides the bug) and becomes
  2× too high at `--step-length 0.5`. Multiply by the actual step length;
  a small, step-length-proportional residual remains at trip boundaries.
- netconvert re-origins network coordinates so all values are
  non-negative — always read a compiled node's actual coordinate back
  from the compiled net before translating externally-defined geometry
  (like a receptor grid) to match.
- `ElementTree.iterparse` child-clearing order: clearing a sibling
  element can clear a child before its parent's `end` event fires,
  causing `element.find(...)` to silently return a default rather than
  raising — a cross-check can read as exactly zero without any error.
- A detector group pooling flow across two physical approaches must be
  divided by the number of pooled approaches before use as a
  single-approach flow in a saturation-flow calculation, or the derived
  per-lane saturation flow comes out physically impossible.
- A signal-plan XML writer formatting duration as an integer can
  silently produce a cycle one second longer than the nominal design
  value — read the realized cycle back from the compiled `tlLogic`.
- Receptor grid resolution is a real, quantifiable bias source in a
  hot-spot analysis — verify the true peak is landed on by comparing
  against a finer grid.

See `analyze-intersection-air-quality-hot-spots-from-microsimulation` for
the full build/dispersion-model/verification workflow, and
[[vehicle-emissions-modeling]] for the HBEFA3/HBEFA4 emission-class
mechanics this page's fleet composition builds on.
