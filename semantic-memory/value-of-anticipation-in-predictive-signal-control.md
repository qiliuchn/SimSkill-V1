---
summary: Predictive rolling-horizon signal control (the OPAC/ALLONS-D/RHODES class) measured against Webster fixed-time, SUMO actuated and max-pressure on 3,292 CRN-paired SUMO runs — the deployable predictive controller beat the best non-anticipatory arm in 0 of 12 demand cells (median +37% delay) while the same DP fed a state-perfect profile won 4 of 12 (median +11%), so the deficit is prediction quality and not optimiser myopia (the DP is provably exact, pruning gap 0.0); arrival-prediction skill is 0.419 platooned, 0.072 Poisson and ~0 deterministic, and is NEGATIVE at the 1-5 s lead that control actually needs; the useful horizon saturates at the detector's D/v_free for the PREDICTOR but not for the CONTROLLER, where shorter horizons are monotonically better and head period and stage size are not levers at all; long horizons recover nothing at v/c>=1 in either regime; rollout MPC on a shadow instance costs ~900x the DP's optimiser for no benefit; and a bin-shuffle information control shows anticipation is load-bearing but second-order to plain profile-magnitude calibration.
keywords:
  - predictive-signal-control
  - rolling-horizon-control
  - model-predictive-control
  - OPAC
  - RHODES
  - ALLONS-D
  - arrival-prediction
  - value-of-anticipation
  - prediction-horizon
  - dynamic-programming-signal-timing
  - simulation-rollout-mpc
  - information-control-experiment
  - controller-constraint-sweep
created: 2026-08-17T18:17:37
last_updated: 2026-08-18T00:30:00
sources:
  - "[[episodic-memory/2026-08-17_18-17-37/summary.md]]"
  - "[[episodic-memory/2026-08-17_18-17-37/outputs/RESULTS.md]]"
related_pages:
  - "[[coordinated-adaptive-signal-control-detector-bias-and-transition-cost]]"
  - "[[state-serialization-and-rolling-horizon-traffic-forecasting]]"
  - "[[actuated-signal-detector-design-and-fault-tolerance]]"
  - "[[demand-arrival-process-and-unsignalized-capacity]]"
  - "[[max-pressure-signal-control]]"
  - "[[actuated-traffic-signals]]"
  - "[[webster-method]]"
  - "[[simulation-based-optimization-under-noise-and-seed-overfitting]]"
  - "[[connected-vehicle-penetration-and-detector-free-signal-control]]"
related_skills:
  - implement-predictive-rolling-horizon-signal-control
  - implement-maxpressure-traci-controller
  - build-rolling-horizon-traffic-forecast-with-state-warm-start
  - control-signals-with-actuated-tls
  - optimize-signals-by-tlscycleadaptation
  - optimize-under-simulation-noise-with-a-fixed-budget
related_skills_for_graph_view:
  - "[[implement-predictive-rolling-horizon-signal-control]]"
  - "[[implement-maxpressure-traci-controller]]"
  - "[[build-rolling-horizon-traffic-forecast-with-state-warm-start]]"
  - "[[control-signals-with-actuated-tls]]"
  - "[[optimize-signals-by-tlscycleadaptation]]"
  - "[[optimize-under-simulation-noise-with-a-fixed-budget]]"
---

# The Value of Anticipation in Predictive Signal Control

Predictive signal control — OPAC, PRODYN, ALLONS-D, RHODES, and their modern restatement as rolling-horizon DP or MPC — optimizes a *sequence* of future switch decisions over a finite horizon against a *predicted* arrival profile, re-solving every few seconds. It is the natural next step after max-pressure, whose known weakness is precisely that it is myopic.

This page records what happened when the promise was measured rather than assumed, on a 4-leg SUMO junction across 3 arrival regimes × 4 demand levels × 8 common-random-number seeds (3,292 simulation runs plus 48 prediction-validation runs). The procedural counterpart is `implement-predictive-rolling-horizon-signal-control`.

**The headline is negative and the mechanism is specific: anticipation did not fix myopia, because the binding constraint is not horizon length but short-lead prediction accuracy — which is exactly where upstream detectors are worst.**

## The ranking

Against the best of three non-anticipatory arms (Webster fixed-time, SUMO `actuated` with properly bound detectors, max-pressure) in each of 12 demand cells:

| controller | cells won | median delay penalty |
|---|---|---|
| deployable predictive DP (detector-fed) | **0 / 12** | **+37.2%** |
| the same DP fed a state-perfect profile | 4 / 12 | +11.2% |

**The optimiser is not the weak link.** The DP is provably exact — dominance pruning validated against exhaustive enumeration at a gap of **0.00000000**, earned over 7,059 label collisions where the kept label was *not* queue-dominating, so the check is real rather than vacuous. The roughly 26 percentage points between the two rows is the price of prediction error.

The one cell where anticipation is competitive is exactly where prediction has skill: **platooned arrivals at v/c 0.95, beating fixed-time by −13.93 s/veh (−22.2%, significant)**.

The result is not an artifact of the operating point. It holds at **every** minimum green from 8 to 20 s (0/12, 0/12, 1/12, 0/12, 0/12) and in **12/12** cells when each cell is given its own best horizon.

## Prediction skill exists only where there is something to predict

Skill = 1 − MAE/MAE_null against an honest null (the same flat historical-mean predictor the control arm runs — not one calibrated with ground truth):

| arrival regime | D=80 m | D=150 m | D=250 m | D=400 m |
|---|---|---|---|---|
| near-deterministic | 0.003 | 0.002 | 0.000 | −0.001 |
| **platooned** | 0.119 | 0.309 | 0.367 | **0.419** |
| Poisson | 0.005 | 0.002 | 0.004 | 0.072 |

Under deterministic arrivals the historical mean *is* the truth, so detector events add only noise. Under Poisson there is nothing in the past to predict from. Below roughly 0.1 skill, the controller has no information to act on.

**Every predictor has NEGATIVE skill at 1–5 s lead** (−0.18 to −0.48), because projecting a loop actuation onto the moving back-of-queue is uncertain by 2.2–4.5 s ≈ 1–2 bins. This is the crux: short lead is what control needs and it is where prediction is worst.

## The horizon is a predictor decision, not a controller decision

- **Component level:** each setback's skill curve holds a plateau and drops to zero **exactly at its own `D / v_free`** (5.8 / 10.8 / 18.0 / 28.8 s at D = 80 / 150 / 250 / 400 m), within one 2 s bin. Horizon genuinely is detector geometry for the predictor.
- **Control level:** it is not. Shorter horizons are monotonically better — 76.4 / 80.3 / 85.4 / 117.4 / 121.3 s/veh at H = 10 / 20 / 30 / 45 / 60 — and the best H does **not** order by setback. **Head period and stage size are not levers at all**: 2.5% and 2.8% spread across their ranges, against 63% across H.

A natural and wrong inference would be "instrument further upstream to see further ahead, and lengthen the horizon to match." The data says the extra reach buys prediction skill in a band the controller cannot use.

## Anticipation is real but second-order — the information controls

The obvious comparison (predictive arm vs flat-profile arm) does **not** measure the value of anticipation, because the two profiles differ in *level* as well as in *timing*. Two controls separate them:

| perturbation | information added | Δ delay, predictive | Δ delay, flat | decisions changed, predictive | decisions changed, flat |
|---|---|---|---|---|---|
| profile × 2 | **none** | −11.7% | −15.9% | 72.4% | 83.6% |
| profile × 3 | **none** | −12.8% | −15.5% | 77.1% | 82.4% |
| bins shuffled | **all timing destroyed** | **+7.7%** | **+0.00% exactly** | 75.7% | **0.0%** |

The bin-shuffle isolates timing: destroying it costs 7.7% and changes 75.7% of decisions, so the arrival *timing* genuinely is load-bearing. The flat profile moving by exactly 0.00 s/veh and 0.0% of decisions is a perfect negative control (shuffling a constant is the identity) and confirms the wiring.

But a purely information-free rescaling buys **more** than timing is worth, and flips 72–84% of decisions. **So: anticipation contributes a measurable but second-order share of this controller's behaviour; profile-magnitude calibration contributes more.** Neither "prediction adds nothing" nor "prediction adds a lot" is defensible without these controls — a first pass at this study asserted the first, and its naive inverse was equally wrong.

## Saturation, and why a longer horizon cannot rescue it

At v/c 1.05 fixed-time won in every arrival regime. Long horizons recover **nothing**, in either regime:

| cell | arm | H=30 | H=60 | H=90 | H=150 |
|---|---|---|---|---|---|
| platooned v/c 1.05 | predictive | 135.44 | 145.37 | 140.31 | 142.19 |
| Poisson v/c 1.05 | predictive | 125.42 | **173.24** | 160.87 | 168.73 |
| Poisson v/c 1.05 | state-perfect | 85.96 | **83.58** | 83.80 | 84.16 |

Neutral when platooned, actively harmful when Poisson; only the state-perfect arm improves, and only by 3–4%. Optimiser cost over the same range rises 0.57 → 22.19 ms. Since the optimiser is exact, the failure at saturation is a prediction failure, not a lookahead failure.

This echoes and extends [[coordinated-adaptive-signal-control-detector-bias-and-transition-cost]], where SCATS-class adaptive control also failed to beat well-tuned fixed-time and its disadvantage *widened* under unpredictable demand.

## Rollout MPC works and is not worth building

Branching candidate switch sequences on a long-lived shadow SUMO instance via `saveState`/`loadState` is feasible, but costs **483–637 ms per decision** (79–99 ms per state load, 40–59 ms per rollout, ~1200 rollouts per run), RTF 12–19 — roughly **900× the analytic DP's optimiser cost** — and lands between the DP and plain actuated control. The analytic DP costs **0.6 ms per decision** (p95 0.9 ms), field-deployable at 1 Hz with a ~1600× margin, and its cost is identical across predictors.

A measurement trap: a `solve_ms` that differs by predictor is timing TraCI round-trips, not the optimiser. Split sensing from solving before quoting either.

## Coordination does not emerge from local anticipation

On a 2-signal corridor 500 m apart, independent local predictive controllers did not produce progression. Arrival-on-green was significant in only **6 of 12** cells and *negative* in 3, while plain `actuated` was the strongest progression arm (significant 11/12, up to +0.156 absolute) and won delay in 11 of 12 cells.

Two side results: coordination itself paid only under saturation — `tlsCoordinator` offsets beat uncoordinated fixed-time by 13.4–14.7% at v/c 1.05 but **cost** 5.3–6.5% at v/c 0.55; and progression is a metric worth reporting separately from delay, since the arms rank differently on the two.

## The methodological lesson that decided the result

**Sweep an adaptive controller's own constraint parameters before ranking it against baselines.** A first attempt at this study hard-coded minimum green at 8 s. That pinned the DP to its bound — the returned first-switch stage was stage 0 in 72–80% of decisions, making the realised policy a fixed-order min-green cycler rather than an optimizer. Raising it to 12 s moved the three DP arms from 77.5 / 53.2 / 24.1 to **29.3 / 29.4 / 28.2** s/veh and made a 53-second apparent "oracle gap" vanish entirely. Every headline in that attempt was an artifact of one unswept knob, and the corrected study reached a different number *and* a different explanation.

This is a distinct failure mode from the seed-overfitting and evaluation-budget concerns in [[simulation-based-optimization-under-noise-and-seed-overfitting]]: the noise handling there was already correct. The parameterisation of the thing being benchmarked was not.

Two riders:

- **Check the ranking is robust to the knob** rather than reporting it at one point — here it held at every min green and at each cell's own best horizon, which is what makes the negative result trustworthy.
- **Watch the sweep's own confound.** 50–64% of realised greens ended exactly on the min-green bound at *every* value tested, so minimum green effectively sets the cycle length (realised cycle 54 → 138 s as it went 8 → 20 s, against Webster plans of 66–150 s). Much of such a sweep is a cycle-length optimum rather than a control-logic effect. Recover the realised cycle from the switch log and say so.

## Modelling notes that changed measured behaviour

- **The store-and-forward queue model needs a free-flow-through term.** Without it, every predicted arrival is instantly queued, so the model cannot see the cost of ending green in front of a *moving* platoon and systematically undervalues holding. Adding it (capacity spends on the standing queue first; only unabsorbed arrivals join it and pay a one-off `v/(2a) + v/(2b)` stop penalty) is worth **−4.23 s/veh** — real, but an order of magnitude smaller than the min-green effect.
- **Do not scale the terminal weight by H**, or changing the horizon reshapes the objective instead of extending lookahead, and a "horizon sweep" is silently an objective sweep.
- **Saturation flow is step-length dependent** and must be measured, not assumed: 2190 / 2044 / 1877 veh/h/lane at dt = 0.1 / 0.5 / 1.0 s. A lane-position poll misses vehicles entirely at dt = 1.0 s (13.9 m per step jumps clean over the stop bar) — read fractional entry times from induction-loop vehicle data instead.
- **The realised arrival regime erodes within the approach.** Headway CV measured at a 400 m entry loop versus an 80 m near-stop-bar loop: deterministic 0.016 → 0.419 at v/c 0.55, and **all three regimes converge on CV > 1 once v/c ≥ 0.95** — the intersection's own metering erases the arrival-regime distinction. This extends [[demand-arrival-process-and-unsignalized-capacity]]'s "never trust the flow tag" finding to a *within-approach spatial gradient*: where you place the detector changes which regime you appear to be in.
