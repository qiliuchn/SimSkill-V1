---
summary: The GEH statistic is a modified chi-squared measure used in traffic engineering to compare a modeled/simulated traffic volume against an observed or target count, with GEH < 5 as a common (soft) per-location acceptance guideline for demand calibration — but its tolerance band widens sharply at low volumes, where it certified a model correlating with the reference at only r = 0.23, and it is useless for RANKING candidate models: 47 of 47 competing OD-estimation designs passed GEH<5 on 100% of their instrumented links while their true OD errors spanned 69.6-105%, so report %RMSN on a FIXED reference link set (never the links a model was fitted to or selected) alongside r and RMSE.
keywords:
  - GEH-statistic
  - calibration-validation
  - traffic-counts
  - MAPE
  - demand-calibration
  - low-volume-insensitivity
  - model-ranking-vs-acceptance
  - fitted-set-scoring-tautology
created: 2026-07-23T15:16:02
last_updated: 2026-08-18T20:05:00
sources:
  - "[[episodic-memory/2026-07-23_14-58-12/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-23_14-58-12/attempts/attempt-1/critic-agent-feedback.json]]"
  - "[[episodic-memory/2026-08-11_16-40-44/summary.md]]"
  - "[[episodic-memory/2026-08-17_16-35-53/summary.md]]"
related_pages:
  - "[[gps-map-matching-and-probe-demand-reconstruction]]"
  - "[[routesampler]]"
  - "[[sensor-location-design-for-od-estimation]]"
  - "[[od-matrix-estimation-and-underdetermination]]"
  - "[[sumo-output-files]]"
  - "[[sumo-calibrator]]"
  - "[[dfrouter-detector-based-demand-reconstruction]]"
  - "[[population-synthesis-and-aggregation-bias]]"
related_skills:
  - calibrate-demand-with-routesampler
  - map-match-gps-traces-to-reconstruct-demand
  - design-count-station-locations-for-od-estimation
  - estimate-od-matrix-with-odme
  - analyze-simulation-outputs
  - synthesize-population-and-generate-disaggregate-demand
related_skills_for_graph_view:
  - "[[calibrate-demand-with-routesampler]]"
  - "[[map-match-gps-traces-to-reconstruct-demand]]"
  - "[[design-count-station-locations-for-od-estimation]]"
  - "[[estimate-od-matrix-with-odme]]"
  - "[[analyze-simulation-outputs]]"
  - "[[synthesize-population-and-generate-disaggregate-demand]]"
---

# GEH Statistic

The GEH statistic (named for Geoffrey E. Havers) is the standard traffic-engineering metric for comparing a modeled or simulated traffic volume `M` against an observed/target count `C` for the same location and time period. It behaves like a modified chi-squared statistic, scaled so that typical hourly traffic-count magnitudes (tens to low thousands of vehicles) map onto an intuitive 0-20ish range instead of the very large or very small values a raw chi-squared or percentage-error computation would give at those magnitudes:

```
GEH = sqrt( (M - C)^2 / ((M + C) / 2) )
```

## Interpretation

- **GEH < 5**: commonly treated as an acceptable fit at a single location — the standard (but soft, not universally mandated) threshold used in traffic-model calibration practice.
- **5 ≤ GEH < 10**: borderline; may warrant investigation depending on the model's purpose.
- **GEH ≥ 10**: generally considered a poor fit at that location.
- A common aggregate acceptance criterion (borrowed from UK/US transportation modeling guidelines) is something like "GEH < 5 for at least 85% of counted locations," though this specific percentage is a convention, not a law — treat it as a useful rule of thumb rather than a hard pass/fail bar, and always report the actual per-location distribution alongside any summary pass rate.

## GEH is a weak test at low volumes — pair it with r and RMSE

GEH's tolerance band widens sharply as volume falls, so on a lightly-loaded network it can
certify a model that has almost no explanatory power. Measured while comparing aggregate
against disaggregate demand on a 6x6 grid at ~40 veh/h per link
([[population-synthesis-and-aggregation-bias]]): a demand variant passed the conventional
85%-of-locations criterion (**GEH<5 on 88.3%** of links) while correlating with the
reference volumes at only **r = 0.23**, RMSE 22.4. A better-specified variant reached
GEH<5 on 100% at r = 0.93 — the two are indistinguishable on the headline pass rate but
not remotely equivalent.

Because GEH is deliberately insensitive to relative error at low counts, the pass rate
alone cannot tell "well calibrated" from "too little traffic to fail." Report the
correlation and RMSE against the reference alongside the GEH distribution, and be
especially wary of GEH-only acceptance on synthetic or off-peak networks where per-link
volumes are small.

## Using it to validate demand calibration

When calibrating OD demand against traffic counts (see `calibrate-demand-with-routesampler` / [[routesampler]]), GEH should be computed **twice, at different stages, and the two are not interchangeable**:

1. **Routing-level**: `routeSampler.py`'s own `--mismatch-output` reports GEH from its route-selection fit — this can be a perfect GEH = 0 purely as a sampling/scaling result, before any simulation dynamics are involved.
2. **Simulation-level**: after actually running the simulation on the calibrated routes and reading its edgeData output (see [[sumo-output-files]]), compute GEH per edge between the *simulated* volume and the original target. This is the number that actually reflects whether the calibrated demand behaves correctly once real queuing, spillback, and capacity limits are in play, and is the one that should be reported as the calibration's real validation result.

Mean absolute percentage error (MAPE) is a useful companion metric alongside GEH — GEH is intentionally less sensitive to relative error at low counts and more sensitive at high counts, while MAPE gives a more intuitive "how far off, percentage-wise" read; reporting both per edge (plus an overall/aggregate GEH computed from summed volumes) gives a fuller picture than either alone.

## GEH cannot rank alternative models at all — its worst measured failure

The low-volume insensitivity above understates the problem when GEH is used to *choose between* candidate models rather than to accept one. In the sensor-location experiment of [[sensor-location-design-for-od-estimation]], 47 competing OD-estimation designs were each scored on the links they had instrumented:

**At 8, 24 and 48 count stations, 47 of 47 designs passed GEH < 5 on 100% of their instrumented links — while their true OD-matrix errors spanned 69.6% to 105%.** GEH's discriminating power was not weak but exactly zero: every candidate, including designs no better than having no counts at all, cleared the conventional bar perfectly. Choosing by the best instrumented %RMSN (a finer statistic than GEH, and still on the selected links) picked a design with 104.6% OD error when 69.6% was available.

Two rules follow, and they are stronger than "report r and RMSE alongside":

- **Never score a model on the observations it was fitted to, or on a link set it chose.** Count fit on fitted links is the objective the estimator minimised. Score on a *fixed* reference set instead — across all candidate links the rank correlation with true OD error rose from +0.120 to +0.890.
- **For ranking, report %RMSN rather than GEH pass rates.** A pass rate saturates at 100% and then carries no information; a continuous residual statistic on a fixed link set still separates candidates. GEH remains reasonable for *accepting* a single model at a location, which is what it was designed for.

**Independently reconfirmed in a second, unrelated domain.** Scoring GPS-map-matched demand reconstructions ([[gps-map-matching-and-probe-demand-reconstruction]]), GEH<5 sat at **99.6-100% across the entire usable operating envelope** and fell only to 93-96% at the coarsest setting tested, while %RMSN over the same reconstructions spanned **0-45%** and separated them cleanly. Deciding the envelope on GEH would have accepted reconstructions carrying 45% count error. Same rule as above: decide on %RMSN over a fixed link set, reserve GEH for accepting a single candidate.

Related: an ODME solution and six flow-equivalent matrices differing by half of all trips likewise all passed GEH < 5 on 100% of counted links in microsimulation ([[od-matrix-estimation-and-underdetermination]]) — the same saturation, arrived at from the equifinality side.

## Worked reference point

From a validated SimSkill run calibrating a 4x4 grid's demand: 10 of 12 counted edges had GEH < 5 (83.3%), overall aggregate GEH (from summed target/simulated volumes) was 6.13, and MAPE was 12.2%. The two failing edges were on the network's busiest corridor and traced to genuine single-lane capacity limits rather than a calibration defect — a reminder that a GEH failure at a specific location needs to be diagnosed (pool coverage gap? real capacity ceiling? genuinely bad fit?) rather than treated as an undifferentiated "calibration failed" signal.
