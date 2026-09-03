---
name: implement-predictive-rolling-horizon-signal-control
description: Use this skill for ANTICIPATORY traffic signal control in SUMO — a controller that optimizes a SEQUENCE of future switch decisions over a finite horizon against a PREDICTED arrival profile, re-solving every few seconds. This is the OPAC / ALLONS-D / PRODYN / RHODES class, and its modern restatements as rolling-horizon dynamic programming or simulation-rollout MPC. Covers a forward DP over (phase, elapsed green, queue vector) with min/max green and clearance as hard constraints and provably exact dominance pruning; a separately validated arrival-prediction module built from upstream detector actuations with an explicit beyond-reach tail; rollout MPC on a shadow SUMO instance via saveState/loadState and why it costs ~900x the DP for no benefit; and the benchmarking discipline this class of controller needs — sweeping the controller's OWN constraint parameters before ranking it, an honest prediction null, and information controls that separate anticipation from profile-magnitude calibration. Trigger on model predictive control or MPC for signals, rolling horizon, OPAC, PRODYN, ALLONS-D, RHODES, look-ahead or anticipatory or predictive signal control, arrival prediction or platoon arrival profiles for signal timing, dynamic programming over phase sequences, simulation rollout for control, or "should my controller look ahead". Reach for this rather than `implement-maxpressure-traci-controller` when the decision rule needs a horizon rather than the present instant, and rather than `optimize-signal-plan-with-simulation-in-the-loop-ga` when the plan is recomputed online rather than fixed offline.
related_skills:
  - implement-maxpressure-traci-controller
  - build-rolling-horizon-traffic-forecast-with-state-warm-start
  - design-actuated-signal-detector-placement-and-fault-tolerance
  - model-demand-arrival-process-and-its-effect-on-capacity-and-delay
  - measure-saturation-flow-and-validate-webster-method
  - optimize-signals-by-tlscycleadaptation
  - optimize-signals-by-tlscoordinator
  - control-signals-with-actuated-tls
  - optimize-under-simulation-noise-with-a-fixed-budget
  - quantify-sumo-run-to-run-variability
related_skills_for_graph_view:
  - "[[implement-maxpressure-traci-controller]]"
  - "[[build-rolling-horizon-traffic-forecast-with-state-warm-start]]"
  - "[[design-actuated-signal-detector-placement-and-fault-tolerance]]"
  - "[[model-demand-arrival-process-and-its-effect-on-capacity-and-delay]]"
  - "[[measure-saturation-flow-and-validate-webster-method]]"
  - "[[optimize-signals-by-tlscycleadaptation]]"
  - "[[optimize-signals-by-tlscoordinator]]"
  - "[[control-signals-with-actuated-tls]]"
  - "[[optimize-under-simulation-noise-with-a-fixed-budget]]"
  - "[[quantify-sumo-run-to-run-variability]]"
related_pages:
  - "[[value-of-anticipation-in-predictive-signal-control]]"
  - "[[state-serialization-and-rolling-horizon-traffic-forecasting]]"
  - "[[coordinated-adaptive-signal-control-detector-bias-and-transition-cost]]"
---

# Predictive (Rolling-Horizon) Signal Control

Every other signal controller in this memory is offline-static (`optimize-signals-by-tlscycleadaptation`, `optimize-signal-plan-with-simulation-in-the-loop-ga`) or reactive to the present instant (`control-signals-with-actuated-tls`, `implement-nema-dual-ring-controller`, `implement-maxpressure-traci-controller`, `optimize-signals-by-qlearning`). This one anticipates.

**Lead with the measured conclusion, because it is not what the literature promises.** On a 4-leg junction across 3 arrival regimes × 4 demand levels × 8 CRN seeds, the deployable predictive controller beat the best non-anticipatory arm (Webster fixed-time, SUMO actuated, max-pressure) in **0 of 12 cells**, median penalty **+37%**. The same DP fed a *state-perfect* profile won 4 of 12 (median +11%). **The optimiser is not the weak link — the prediction is**, and about 26 of those 37 points are the price of prediction error. Build this when the conditions below hold, not by default.

## When anticipation is worth it

The boundary, measured rather than assumed:

- **Arrivals must be genuinely predictable.** Prediction skill (1 − MAE/MAE_null) was **0.419** for platooned arrivals, **0.072** for Poisson, and **≈0 or negative** for near-deterministic ones — where the historical mean *is* the truth, so detector events only add noise. Below ~0.1 skill, do not build this.
- **Demand must be under saturation.** At v/c ≥ 1.05 fixed-time won in every regime, and long horizons recovered nothing (at Poisson v/c 1.05, going H=30→60 made it *worse*: 125 → 173 s/veh). Only perfect state helped, by 3–4%.
- **The one place it was competitive is exactly where skill lives:** platooned arrivals at v/c 0.95, where it beat fixed-time by **−13.93 s/veh (−22.2%, significant)**.

Note the corollary: `implement-maxpressure-traci-controller`'s known myopia is *not* what limits it here. Anticipation did not fix it.

## The horizon is a predictor decision, not a controller decision

The most useful structural result, and it contradicts the natural intuition:

- **Component level:** prediction skill decays to zero at each setback's own `D / v_free` (5.8 / 10.8 / 18.0 / 28.8 s at D = 80 / 150 / 250 / 400 m). Horizon *is* detector geometry for the predictor.
- **Control level:** shorter H is monotonically better (76.4 → 80.3 → 85.4 → 117.4 → 121.3 s/veh at H = 10/20/30/45/60), and the best H does **not** order by setback. Head period and stage size are not levers at all (2.5% and 2.8% spread against 63% across H).

The reason: what control needs is accuracy in the **0–10 s** band, which is governed by queue-position uncertainty, not by how far upstream you can see. Every predictor tested had **negative** skill at 1–5 s lead (−0.18 to −0.48) because projecting a loop actuation onto a moving back-of-queue is uncertain by 2–5 s ≈ 1–2 bins.

So: pick H short (10–30 s), and spend the effort on short-lead accuracy rather than on setback or horizon length.

## Pipeline

```bash
# 0. Measure saturation flow — do NOT assume 1900. It is step-length dependent:
#    2190 / 2044 / 1877 veh/h/lane at dt = 0.1 / 0.5 / 1.0 s. Read fractional entry
#    times from getVehicleData; a lane-position poll misses vehicles entirely at dt=1.0
#    (13.9 m/s * 1 s = 13.9 m per step jumps clean over the stop bar).

# 1. Build the phase model by INTROSPECTION, never hand-written per network
python3 -c "from common import PhaseModel; pm = PhaseModel(conn, tls_id)"   # phase<->movement groups, clearance chains, via-lanes

# 2. Validate the predictor as a COMPONENT, before any control run
#    Report MAE/skill vs setback x lead time x arrival regime against an HONEST null.

# 3. Sweep the controller's OWN constraints (see below) — before ranking anything

# 4. Then, and only then, the six-arm factorial on common random numbers
```

`scripts/control.py` holds the reusable core: the `Predictor` interface (`update`/`profile`/`queues`), `DetectorPredictor`, `FreeFlowProjPredictor`, `MeanRatePredictor` (the honest null), the `JunctionController` GREEN→YELLOW→ALLRED state machine, `MaxPressureCtl`, and `DPCtl` with both the pruned solver and `solve_exhaustive` for validating it. `scripts/common.py` holds `PhaseModel` introspection, the detector writer and binding, and the switch-log auditor. `scripts/state_traps.py` diagnoses the two save/load-state traps before you rely on them.

## The DP

Forward DP over stages of 2 s. State = `(phase, elapsed green, queue vector)`; decision = hold vs switch; stage cost = accumulated delay from a store-and-forward queue model driven by the predicted profile and the *measured* saturation flow. Min green, max green, fixed yellow and all-red are hard constraints inside the recursion. Implement only the first head period `h < H`, then re-solve.

**The queue model must have a free-flow-through term.** Capacity spends on the standing queue first; only *unabsorbed* arrivals join it, and they pay a one-off stop penalty `v/(2a) + v/(2b)` taken from the demand's own vType (4.21 s here). Without it every predicted arrival is instantly queued, the model cannot see the cost of ending green in front of a moving platoon, and it systematically undervalues holding. Measured effect of adding it: **−4.23 s/veh** — real, but an order of magnitude smaller than the min-green effect below, so do not expect it to rescue a badly parameterised controller.

**Do not scale the terminal weight by H.** Doing so makes H reshape the objective rather than extend lookahead, and then a "horizon sweep" is really an objective sweep. Use a fixed terminal window.

**Validate the pruning.** Dominance pruning keeps the lower-cost label at each key; that is only lossless if the kept label also queue-dominates. Run `solve_exhaustive` alongside and report the gap. Measured here: **0.00000000 across H ∈ {20,30,45,60}**, earned over 7,059 collisions where the kept label was *not* queue-dominating — so the pruning is genuinely exact, not vacuously checked. A prior version had dead skip-ahead code whose next-ring choice read the queue vector, breaking the Markov property; removing it is what made the recursion exact.

Cost: **0.6 ms per decision** (p95 0.9 ms), RTF 138–264 — field-deployable at 1 Hz with a ~1600× margin, and *identical* across predictors. If your `solve_ms` differs by predictor you are timing TraCI round-trips, not the optimiser; split the two.

## Rollout MPC: works, and is not worth it

Branch candidate switch sequences from the current state on a long-lived shadow SUMO instance driven by `saveState`/`loadState`, score each by a short rollout, commit the best first decision.

It functions — but costs **483–637 ms per decision** (79–99 ms per `loadState`, 40–59 ms per rollout, ~1200 rollouts/run), RTF 12–19, roughly **900× the DP's optimiser cost**, and lands *between* the DP and plain actuated control. Worst case exceeded a 1 Hz budget outright. Build it to diagnose, not to deploy.

Two traps from `build-rolling-horizon-traffic-forecast-with-state-warm-start` bite here specifically — see [[state-serialization-and-rolling-horizon-traffic-forecasting]]:

- **`getSpentDuration` does not survive a load.** Phase index and absolute next-switch time restore correctly; elapsed green comes back **0.0** against a true 6.0 s. Probed at every decision: phase matches 100%, elapsed green matches **0.00%**. Any min-green enforcement reading SUMO's phase clock after a load believes the green just started. **Workaround: drive the phase wholly externally (`setPhase` plus a large `setPhaseDuration`) and carry elapsed green in Python.** That works, and is not what makes rollout MPC impractical — the 552 ms is.
- **`<flowState>` double-counts** when forking onto a route file whose flow ids *differ* from the state's. Use explicit `<vehicle>` demand and the trap cannot fire at all (verified: no `<flowState>` element in the state).

**A probe guarded by "only on the first decision" cannot see either trap** — at t=0 the shadow has been on phase 0 since the start, so elapsed green trivially equals simulation time and everything looks fine. Probe every decision.

## Benchmarking discipline — the part that decides whether your result is real

This is the most transferable content in this skill, and the reason a first attempt at this study produced a completely different (wrong) headline.

**1. Sweep the controller's own constraint parameters BEFORE ranking it against baselines.** A hard-coded `--min-green 8` pinned the DP to its bound — the returned first-switch stage was stage 0 in 72–80% of decisions, making the realised policy a fixed-order min-green cycler. Raising it to 12 s moved the three DP arms from 77.5 / 53.2 / 24.1 to 29.3 / 29.4 / 28.2 s/veh and made a 53-second "oracle gap" vanish entirely. Every headline in that attempt was an artifact of one unswept knob. Nothing in the rest of this memory's benchmarking guidance covers this: `optimize-under-simulation-noise-with-a-fixed-budget` handles seeds and evaluation budget, not the controller's own parameterisation.

**Then check the ranking is robust to the knob**, rather than reporting it at one point — here the negative result held at *every* min green from 8 to 20 s and at each cell's own best horizon, which is what makes it trustworthy.

**And watch the sweep's own confound:** 50–64% of realised greens ended exactly on the min-green bound at every value tested, so min green effectively *sets the cycle length* (realised cycle 54→138 s as mg went 8→20). Much of such a sweep is a cycle-length optimum, not a control-logic effect. Recover the realised cycle from the switch log and say so.

**2. The prediction null must be the same null the control arm runs.** A null calibrated with ground-truth counts is not a null; it makes skill scores incomparable with the control comparison they are meant to explain.

**3. Information controls, to separate anticipation from calibration.** The comparison "predictive arm vs flat-profile arm" does *not* measure the value of anticipation, because the two profiles differ in level as well as in timing. Run both:

| perturbation | information added | Δ delay, predictive | Δ delay, flat | decisions changed |
|---|---|---|---|---|
| profile × 2 or × 3 | **none** | −11.7% to −12.8% | −15.5% to −15.9% | 72–84% |
| bins shuffled | **all timing removed** | **+7.7%** | **+0.00% (exactly)** | 75.7% vs **0.0%** |

The bin-shuffle isolates timing: destroying it costs 7.7% and changes 75.7% of decisions, so anticipation *is* load-bearing. But a pure information-free rescaling buys *more*. **Honest conclusion: anticipation contributes a measurable but second-order share of behaviour; profile-magnitude calibration contributes more.** The shuffle on a flat profile moving by exactly 0.00 is your proof the control is wired correctly.

**4. Audit each arm against its own governing constraint.** Auditing passive arms against the DP's min green spuriously flags every shorter Webster phase. Derive each arm's minimum from its programmed `tlLogic`/`minDur`, not from observed behaviour, or the audit becomes self-fulfilling.

**5. Fix the operating point before the sweep that would choose it, and you have repeated the mistake.** The factorial here fixed H=30 before the H sweep ran, which later found H=10 better. It was verified not to overturn the ranking — but that verification is the minimum you owe the reader.

## Corridors: progression does not emerge from local anticipation

Independent local predictive controllers at two junctions 500 m apart did **not** produce coordination. Arrival-on-green was significant in only 6 of 12 cells (and *negative* in 3), while plain `actuated` was the strongest progression arm (significant 11/12, up to +0.156 absolute) and won delay in 11 of 12 cells.

Two side findings worth carrying: coordination itself paid only under saturation (`tlsCoordinator` beat uncoordinated fixed-time by 13.4–14.7% at v/c 1.05 but *cost* 5.3–6.5% at v/c 0.55); and a per-junction schedule keying bug is easy to introduce here — keying a departure schedule on `edges[0].getToNode()` silently leaves the second junction with no schedule at all.

## Related

- `implement-maxpressure-traci-controller` — the closed-loop TraCI skeleton this extends; also the myopic reference arm
- `build-rolling-horizon-traffic-forecast-with-state-warm-start` — the save/load-state semantics Controller B depends on
- `design-actuated-signal-detector-placement-and-fault-tolerance` — detector binding and setback as a design variable
- `model-demand-arrival-process-and-its-effect-on-capacity-and-delay` — the arrival regimes, and why to verify realised headway CV rather than the generator's label
- `measure-saturation-flow-and-validate-webster-method` — the saturation flow the DP's queue model needs
- `optimize-signals-by-tlscycleadaptation`, `optimize-signals-by-tlscoordinator`, `control-signals-with-actuated-tls` — the baselines that beat this in most cells
- `optimize-under-simulation-noise-with-a-fixed-budget`, `quantify-sumo-run-to-run-variability` — CRN pairing and replication count
- [[value-of-anticipation-in-predictive-signal-control]] — the full measured boundary and the negative results
- [[state-serialization-and-rolling-horizon-traffic-forecasting]] — the two traps, and the refinements this study added
- [[coordinated-adaptive-signal-control-detector-bias-and-transition-cost]] — the closest prior result: SCATS-class adaptive control also lost to well-tuned fixed-time
