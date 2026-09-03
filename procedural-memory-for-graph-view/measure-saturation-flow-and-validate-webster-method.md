---
name: measure-saturation-flow-and-validate-webster-method
description: Use this skill when the user wants to empirically measure SUMO's own emergent saturation flow rate and startup lost time at a signalized stop line — rather than assuming textbook or tool-default values — and/or wants to compute Webster's optimal signal cycle length/splits/delay from first principles and test the prediction against brute-force simulation. Covers extracting per-vehicle discharge headways from E1/instant induction-loop data, deriving saturation flow and lost time via two independent estimators, showing how these parameters depend on car-following settings (tau, accel, minGap, length), implementing Webster's equations independently, and falsifying the analytical prediction with a cycle-length sweep across saturation levels. Trigger on mentions of saturation flow rate, startup lost time, discharge headway, Webster's method/equation from first principles, critical flow ratio, or validating/checking a signal-timing tool's capacity assumptions.
related_skills:
  - create-single-intersection
  - optimize-signals-by-tlscycleadaptation
  - analyze-simulation-outputs
  - measure-heavy-vehicle-passenger-car-equivalent
  - measure-roundabout-capacity-and-implement-metering
  - design-signal-change-and-clearance-intervals
  - choose-time-discretization-and-integration-method
related_skills_for_graph_view:
  - "[[create-single-intersection]]"
  - "[[optimize-signals-by-tlscycleadaptation]]"
  - "[[analyze-simulation-outputs]]"
  - "[[measure-heavy-vehicle-passenger-car-equivalent]]"
  - "[[measure-roundabout-capacity-and-implement-metering]]"
  - "[[design-signal-change-and-clearance-intervals]]"
  - "[[choose-time-discretization-and-integration-method]]"
related_pages:
  - "[[webster-method]]"
  - "[[sumo-time-discretization]]"
---

# Measure Saturation Flow and Validate Webster's Method

Empirically measures SUMO's own emergent per-lane discharge capacity (saturation flow rate `s`, startup lost time `l1`) directly from raw stop-line crossing data, then uses those *measured* — not assumed — parameters to compute Webster's classic signal-timing optimum and test it against brute-force simulated delay. This is the first skill in memory to validate `optimize-signals-by-tlscycleadaptation`'s theoretical assumptions rather than just consuming the tool's output — that skill wraps Webster's equation as a black box with a default saturation-headway assumption (`-H 2` s ≈ 1800 veh/h/lane) that this skill's measurement can reveal is meaningfully off for SUMO's own default vehicles, **provided `actionStepLength` is pinned rather than left tied to the fine `--step-length` this skill requires** — see the discretization gotcha below and [[sumo-time-discretization]].

## Building the test bed

Use `create-single-intersection`'s plain-XML + netconvert approach for an isolated 4-way, single-lane junction — but note its auto-generated `tlLogic` cannot be swept over cycle lengths; override it with a hand-written `tlLogic` in an additional file for every cycle length tested. Restrict green/demand to the four through movements only (hold every turning link red in every phase) to eliminate turning-conflict confounds from the capacity measurement. Use `--step-length 0.1` **and pin vType `actionStepLength="1.0"` explicitly (also turn on `--step-method.ballistic`)** — the default 1s step cannot resolve saturation headways around 1.5-2s, but a fine step *without* pinning reaction time gives every driver a 0.1s reaction time instead of a plausible one, and inflates measured saturation flow by ~20% for reaction-time reasons that have nothing to do with resolving the headway (see [[sumo-time-discretization]] / `choose-time-discretization-and-integration-method`). Use `departSpeed="max"` for any oversaturation scenario: `departSpeed="0"` throttles insertion to roughly 1500 veh/h/lane (a vehicle at rest must clear its own jam spacing before the next enters), which silently prevents the queue from ever spilling back and corrupts the measurement. Pass `--max-depart-delay` when deliberately oversaturating, or the pending-insertion backlog grows into the tens of thousands and dominates runtime.

## Measuring saturation flow and startup lost time

Load the approach at roughly 2x its expected capacity so every green is served from a permanently spilled-back standing queue. Instrument the stop line with an `<instantInductionLoop>` for per-vehicle enter/leave timestamps, plus a `<laneAreaDetector>` (with `endPos` explicitly clipped to the lane's own length — **not** an oversized `length`, which silently continues measuring onto the next upstream lane and corrupts the queue-verification check) to independently verify the standing queue never actually ran out during any measured cycle.

**Headway convention**: use the rear-bumper crossing (`state="leave"`), the standard field (HCM/Teply) convention and the only one meaningfully defined for the first vehicle, which is already standing on the stop line at green onset.

Use **two independent estimators**. Prefer the second as primary only for a fleet with genuine driver-behavior noise (`sigma > 0`) — see the correction below for the deterministic (`sigma=0`) case, where the first is primary instead:

1. **Headway vs. queue position**: average headway `h_n` at each position `n` over many cycles; `h_s` = mean over a chosen "saturated" window of `n`; `s = 3600/h_s`; `l1 = sum over n<window of (h_n - h_s)`. Report window sensitivity explicitly — the choice of which positions count as "saturated" can move `s` by a few percent and `l1` by fractions of a second.
2. **Green-duration regression (window-free, preferred with a caveat below)**: re-run the same oversaturated scenario at several distinct green durations `g` (e.g. 16/24/32/40s) and fit vehicles-discharged-per-cycle `N_d(g) = (s/3600)(g - l1 + e)` by OLS across `g`. This needs no arbitrary window choice, uses the entire green period's information, and its R² is a built-in sanity check that the queue never exhausted at any tested green duration (R²≈1.0 is strong evidence of clean saturation throughout).

**Correction, verified in a follow-up study (`measure-heavy-vehicle-passenger-car-equivalent`): the green-duration regression is integer-quantization-limited on a fully deterministic fleet (`sigma=0`, no driver-behavior noise).** With zero stochasticity, vehicles-discharged-per-cycle can land on an exact small integer lattice at each tested green duration (a verified case: exactly 11, 16, 21, and 26 vehicles at four tested green durations, with no cycle-to-cycle variation at all) — the regression is then fit through only as many effectively distinct data points as there are green durations tested, with no within-duration variance to anchor it, and can produce a nonsensical result (verified case: `s`/`l1` implying a physically-impossible E_T < 1 in a downstream analysis). **Use the windowed headway-position estimator (option 1) as primary, or the asymptotic-headway estimator below, whenever the fleet has `sigma=0`** — reserve the green-duration regression for a fleet with genuine driver-behavior noise (`sigma > 0`), where cycle-to-cycle variation gives the regression real information to fit against, or use it only as a secondary cross-check regardless of `sigma`.

`scripts/measure_saturation.py` implements both.

## Saturation flow and startup lost time are emergent, not fixed

Re-run the same measurement across several car-following parameterizations (vary `tau`, `accel`, `minGap`, vehicle `length` one at a time) on the identical network and signal. Verified finding: saturation flow spanned a **39% range** (1766-2457 veh/h/lane) from car-following parameters alone. `tau` passes through to the saturation headway almost 1:1 (`dh_s/dtau ≈ 0.9-1.0`); vehicle `length`/`minGap` contribute through the equilibrium space-headway term `h_s = tau + (length+minGap)/v_d`, but only when `v_d` is the **emergent discharge speed** (found to be ~80% of the posted speed limit in one verified case), not the speed limit itself — using the speed limit in that formula overestimates capacity. `accel` is the cleanly separable odd one out: it barely moves `h_s` but strongly shifts `l1` (from near-zero to +1.7s in one verified test) — **`tau`/geometry set the saturation headway, `accel` sets the startup lost time**, not the same parameter driving both.

**Don't assume monotone headway decay.** The textbook picture is a long first headway decaying smoothly to a flat asymptote. SUMO's Krauss model can instead **undershoot** — headways dip *below* the eventual asymptote around the 3rd-5th queue position, then climb back up — an emergent acceleration-wave/platoon-dispersion effect (the discharging platoon crosses the stop line below the speed limit, with crossing speed creeping up as the platoon disperses), not a bug. This means "the constant saturation headway" is an approximation of SUMO's actual behavior, not an identity — always report window sensitivity or use the window-free regression estimator.

## Computing Webster's method from measured parameters

Implement independently (don't just consume a tool's output):

```
y_i = q_i / s                              (s = MEASURED saturation flow, not assumed)
L   = sum_i (l1 + l2_i)                    (l2 = yellow + all-red clearance; measure or state explicitly)
Y   = sum_i y_i
C_opt = (1.5*L + 5) / (1 - Y)              (undefined/negative if Y >= 1)
g_eff,i = (C - L) * y_i / Y                 (effective green per phase)
d(C) = C*(1-lam)^2 / (2*(1-lam*x)) + x^2/(2*q*(1-x)) - 0.65*(C/q^2)^(1/3) * x^(2+5*lam)
        with lam = g_eff/C, x = q/(lam*s)   (standard Webster 1958 delay formula)
```

`scripts/webster.py` implements this. Compute `C_opt` and the delay curve at several distinct demand/saturation levels (e.g. Y≈0.5, Y≈0.85, Y≥1) to exercise the formula across its valid range and past it.

## Falsifying the prediction with a brute-force sweep

Run identical demand/seed/network fixed-time plans across a wide cycle-length grid (e.g. 20-180s in 10s steps) with Webster-proportional splits at every cycle length, and compare simulated mean `timeLoss` (or another delay proxy) per vehicle against Webster's predicted `d(C)`. Verified findings from one such sweep:

- **Webster's C_opt can land within a fraction of a second of the true simulated optimum** near-critical saturation, at a real but small (~1-4%) delay penalty versus the exact simulated argmin — a strong result, *provided it is fed genuinely measured parameters* rather than defaults.
- **Simulated delay sits systematically below/above Webster's prediction by a roughly constant offset** — expected, since a raw delay proxy like `timeLoss` includes acceleration/deceleration loss that Webster's pure stopped-delay model excludes.
- **Webster's formula diverges as any phase's degree of saturation `x`→1**, predicting delay far above what simulation shows (simulation's delay is bounded by the finite demand period; Webster's isn't), and returns **no value at all** once `Y≥1` — even though the simulation continues to produce a well-behaved, finite, monotone-then-flattening delay curve throughout. Report both: the formula's qualitative advice (favor longer cycles under oversaturation) can still hold even where its own arithmetic breaks down.
- **The optimum's flatness is saturation-dependent, and can run opposite to common "Webster's optimum is always flat" folklore.** In one verified sweep, the undersaturated case had a *sharp* relative optimum (only a single grid point within 5% of the minimum), while the near-critical and oversaturated cases had comfortably wide flat bands (tens of seconds within 5%). Don't assume flatness without checking — it can invert with saturation level.

Report `not_inserted`/`still_running`/`teleport` counts for every sweep run as an honest sanity check that delay comparisons aren't survivor-biased by dropped or stranded vehicles, and note explicitly that an oversaturated sweep's delay is bounded by the finite demand period (horizon-dependent), not a stationary-state measurement — a genuinely different quantity from what Webster's formula describes.

## Checking a signal-timing tool's assumptions against reality

Run the real `optimize-signals-by-tlscycleadaptation` tool on the same network/demand and simulate its output plan under identical conditions, alongside the measured-parameter Webster optimum and the brute-force optimum. Verified finding: `tlsCycleAdaptation.py`'s `-H 2` s default (≈1800 veh/h/lane) **did not match** SUMO's actual default-vehicle discharge — the tool computed critical flow ratios above the true values from its capacity assumption. **The tool's own math is correct for the saturation flow it's told to assume** — the finding is that the default assumption doesn't describe SUMO's own vehicles. Practical fix: measure the real saturation headway for the vType(s) actually in the scenario (this skill) and pass it explicitly via `-H`, rather than accepting the 2s default.

**Re-qualification (2026-08-04 time-discretization audit — see [[sumo-time-discretization]]): the originally-reported mismatch size (measured 2191 veh/h/lane, +21.7%, "16-26% more simulated delay") was itself measured with `--step-length 0.1` and `actionStepLength` left tied to it, i.e. at an effective 0.1s driver reaction time.** With `actionStepLength` pinned at a realistic 1.0s, SUMO's default vehicles discharge at ~1890 veh/h/lane — only ~5% off the tool's 1800 default, not 21.7% — and a mismatch that size would not plausibly trigger the oversaturation fallback or cost 16-26% delay. The methodological lesson above (measure, don't assume, the saturation headway) is unaffected; only the magnitude of the tool-default mismatch is convention-dependent. Always pin `actionStepLength` per the gotcha below before quoting a specific percentage.

## Gotchas

- **`departSpeed="0"` silently caps insertion at ~1500 veh/h/lane** regardless of requested flow rate, preventing genuine queue spillback — use `departSpeed="max"` when deliberately oversaturating.
- **A `laneAreaDetector` with an oversized `length` continues onto upstream lanes** and silently measures traffic that isn't on the intended approach — clip with an explicit `endPos` matching the lane's actual length.
- **`--step-length` at the 1s default cannot resolve saturation headways** around 1.5-2s — use 0.1s or finer. **But a fine step alone is not enough: pin vType `actionStepLength` to a realistic reaction time (e.g. 1.0s) and turn on `--step-method.ballistic`, or the finer step silently gives every driver a proportionally faster reaction time and inflates measured saturation flow by ~20%** — this is the single biggest source of error in this skill's own measurements (see [[sumo-time-discretization]]).
- **Detector `file` paths resolve relative to the additional file's own directory**, not the caller's cwd — give every measurement run's detectors their own dedicated output directory to avoid parallel runs overwriting each other.
- **Don't assume a monotone headway decay** — SUMO's Krauss model can undershoot the asymptote at low queue positions before climbing back; use the window-free green-duration-regression estimator as primary (when the fleet has driver noise, `sigma > 0`), and report windowed-estimator sensitivity as a secondary check.
- **The green-duration regression is integer-quantization-limited on a fully deterministic (`sigma=0`) fleet** — vehicles-per-cycle can land on an exact small integer lattice across tested green durations, starving the regression of real variance and potentially producing a nonsensical fit. Use the windowed headway-position estimator as primary on a deterministic fleet instead.
- **A tool's Webster-based output is only as good as the capacity assumption fed into it** — verify `-H`/`-l` against a real measurement before trusting `tlsCycleAdaptation.py`'s plan, especially for any non-default vType.
- **Webster's delay formula is undefined once any phase's `x≥1`, even if the network-wide `Y<1`** — a short cycle length can push an individual phase's saturation degree over 1 even when the aggregate critical-flow sum looks fine; don't assume `Y<1` alone guarantees a defined delay value at every cycle length.

## Related

- `create-single-intersection` — the plain-XML+netconvert network-building technique this skill's test bed is built from.
- `optimize-signals-by-tlscycleadaptation` — the tool this skill validates; see its Gotchas for the `-H`/`-l` defaults this skill's measurement was checked against.
- `analyze-simulation-outputs` — general tripinfo/summary parsing conventions this skill's delay comparison follows.
- [[webster-method]] — the underlying theory, the verified emergent-saturation-flow findings, and where the analytical formula breaks down against simulation.
- `measure-heavy-vehicle-passenger-car-equivalent` — reuses and extends this skill's rig for a mixed car/truck fleet; found and reported back the green-duration-regression integer-quantization gotcha above.
- `measure-roundabout-capacity-and-implement-metering` — reuses this skill's measured (not assumed) discharge-rate methodology to Webster-size a signalized reference junction and to diagnose the level-offset component of a roundabout entry-capacity-vs-HCM comparison (the same ~30% discharge-rate overshoot shows up at both a signalized stop line and a roundabout entry).
- `design-signal-change-and-clearance-intervals` — reuses this skill's stop-line discharge measurement methodology to measure lost time directly (rather than assuming it equals the programmed intergreen), and found the resulting Webster-cycle-length correction's sign depends on fleet composition, not just a fixed offset.
- `choose-time-discretization-and-integration-method` / [[sumo-time-discretization]] — found that this skill's own "use `--step-length 0.1`" rule, taken alone, inflates measured saturation flow by ~20% via an unpinned reaction-time confound; always pin `actionStepLength` alongside the fine step length.
