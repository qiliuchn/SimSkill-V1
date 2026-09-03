---
name: choose-time-discretization-and-integration-method
description: Use this skill when the user needs to pick or defend SUMO's --step-length, --step-method.ballistic and vType actionStepLength rather than accept the defaults - including running a step-length convergence study, deciding which step length a given metric can be trusted at, separating a genuine numerical-resolution effect from the driver-reaction-time change that a naive step-length refinement smuggles in, or auditing whether an existing quantitative SUMO result is a discretization artifact. Covers the verified Euler-vs-ballistic position-update contract, the two ways actionStepLength silently overrides the integrator, a per-metric convergence/trust table, a dt-sensitivity ranking putting SSM and emissions far above travel time, and the fidelity-vs-runtime Pareto (including TraCI overhead dominating dt). Trigger on mentions of step length, time step, dt, ballistic integration, Euler update, actionStepLength, reaction time, numerical convergence, discretization artifact, "is this result real or a timestep effect", or simulation resolution/runtime trade-offs.
---

# Choose Time Discretization and Integration Method

Treats SUMO's time discretization as an **experimental variable to be justified**, not a
default to inherit. Every other measurement skill in this memory fixes a step length by
convention (`measure-saturation-flow-and-validate-webster-method` mandates 0.1 s;
`calibrate-car-following-parameters-against-field-targets` uses 0.5 s + ballistic;
most others take SUMO's 1 s default) without ever testing what that choice costs. This
skill supplies the missing test, and the answer turns out to change several stored numbers.

## The three coupled settings

`--step-length` (`dt`), `--step-method.ballistic`, and vType `actionStepLength`. The third
defaults to *equal to* `dt`, and it is a **driver reaction time**, not a numerical setting.
That coupling is the single most important fact here: refining `dt` with default settings
makes drivers ten times more alert, which is not a convergence study.

**These three are not independent in SUMO** (verified on 1.27.1, see
`scripts/exp_integration_rule.py`):

- A vType `actionStepLength` **strictly greater than** `dt` **force-enables ballistic
  integration**, warning on stderr: `Action step length '1.00' is used for vehicle type
  'car' but step-method.ballistic was not set. Setting it now to avoid collisions.`
  So the `(Euler, actionStepLength > dt)` cell **does not exist** — a
  `dt x method x actionStepLength` design collapses to three arms per `dt`, not four.
  Setting `actionStepLength` equal to `dt` does *not* trigger this.
- Merely **supplying `--default.action-step-length` at all** — including the value `0`, its
  own default — switches Euler to the exact update **silently, with no warning**. Never
  pass this option unless a non-default reaction time is genuinely intended; set
  `actionStepLength` on the vType instead, where at least the override is announced.

## Verifying the integrator before trusting any dt study

Do not take the update rule on faith. A single vehicle accelerating from rest at constant
`a` on a free lane has the exact answer `x(t) = 0.5*a*t^2`; run it and diff.

- **Euler** (default): `x += v_new*dt`, so the vehicle runs *ahead* of the truth. Error
  grows as `a*dt*t/2` during acceleration and freezes at a **permanent `v*dt/2` offset**
  (verified: 6.65 m at `dt=1 s`, `v=13.89 m/s`; 0.70 m at `dt=0.1 s`).
- **Ballistic**: `x += (v_old+v_new)/2*dt`, **exact** for piecewise-constant acceleration —
  residual <= 0.005 m (output rounding) at *every* step length including 1 s.

`scripts/exp_integration_rule.py` runs this as a 20-case matrix and prints the inferred rule
per case; run it first in any new SUMO version, since this is version-specific behaviour.

## Designing the sweep

Full factorial `dt` in {1, 0.5, 0.25, 0.1} s x {Euler, ballistic} x `actionStepLength`
{tied to `dt`, pinned at 1.0 s}, **CRN throughout**: pre-write one route file with explicit
`<vehicle depart=...>` entries (not `<flow>`, whose departures re-quantise per `dt`) and
reuse the identical file and identical seed list in every cell. Use
`quantify-sumo-run-to-run-variability`'s replication discipline and report paired CIs.

Use the **`dt=0.1 s`, ballistic, `actionStepLength=1.0 s`** cell as the reference: it is the
only cell that is simultaneously numerically fine, exactly integrated, and physically
plausible in reaction time.

Build at least three testbeds — they answer different questions and disagree by an order of
magnitude in sensitivity:

- **(a) closed single-lane ring** for FD/capacity/wave speed (`validate-kinematic-wave-theory-across-car-following-models`'s instrument): steady cruising, the *least* `dt`-sensitive regime.
- **(b) oversaturated signalized approach** for saturation flow, startup lost time, delay, emissions (`measure-saturation-flow-and-validate-webster-method`'s instrument): repeated stop/start, strongly `dt`-sensitive.
- **(c) priority merge or unsignalized crossing** with the SSM device (`analyze-intersection-safety-with-ssm`): gap acceptance and conflicts, the *most* `dt`-sensitive regime.

Add a **deterministic single-vehicle probe** (`sigma=0`) for the stop-line/braking question —
it isolates the integrator from all traffic noise and costs seconds.

## The central result: isolate reaction time from numerics

Run every metric twice, once with `actionStepLength` tied to `dt` and once pinned at 1.0 s.
The difference between the two families is the confound, and it is usually most of the effect.

Verified on a signalized approach (saturation flow, veh/h/lane):

| | `dt=1 s` | `dt=0.1 s` | change |
|---|---:|---:|---:|
| `actionStepLength` tied to `dt` | 1857 | 2244 | **+20.9%** |
| `actionStepLength` pinned at 1.0 s | 1857 | 1871 | **+0.8%** |

**About 96% of the apparent "capacity gain from a finer time step" is the reaction-time
change; only ~4% is integration accuracy.** On a closed ring the split is even starker:
capacity rose 7.9% with `actionStepLength` tied and **0.0%** with it pinned.

Equally important: **with `actionStepLength` tied, refinement is not convergent at all** —
deviations from the reference *grow* monotonically as `dt` shrinks, because the run is
walking away from a 1-s-reaction driver rather than toward a converged answer. The pinned
family is a substantially cleaner convergence study — most metrics do converge monotonically
in it, though not literally every one (a handful, e.g. pulse depth and a few merge-testbed
metrics, still show minor non-monotonicity). Report both families or the convergence table
is meaningless.

## Per-metric trust table (reaction time pinned)

Coarsest `dt` still within 2% of the reference, every finer `dt` also within 2%:

| trustworthy at | metrics |
|---|---|
| **`dt = 1.0 s`** | ring capacity, critical density, free-flow speed, backward wave speed, saturation flow, mean trip duration |
| `dt = 0.5 s` | mean time loss, completed-trip count, total conflict count, min TTC, merge CO2/km |
| `dt = 0.25 s` | signalized-approach CO2/km |
| **`dt = 0.1 s` required** | startup lost time, severe-conflict count (TTC < 1.5 s), residual stop-and-go speed dispersion |

`dt`-sensitivity ranking (max deviation across the `dt` sweep, tied / pinned): severe
conflicts 100%/12%, startup lost time 96%/60%, residual speed dispersion 91%/4%,
min TTC 80%/2%, conflict count 50%/2%, CO2 26%/13%, mean time loss 23%/2%, saturation flow
20%/1%, ring capacity 8%/0.0%, free-flow speed 2%/0.0%, critical density 0.8%/0.0%.

**Safety/SSM and emissions are far more fragile than aggregate travel time; equilibrium FD
features are nearly `dt`-invariant.** The most alarming single number: severe conflicts
(TTC < 1.5 s) at a merge fell from 152 per run at `dt=1 s` to **exactly zero** at
`dt <= 0.25 s` with `actionStepLength` tied — a safety metric annihilated by a settings
change, with the collision log and teleport count both zero throughout.

**Levels are fragile; CRN-paired contrasts are much less so.** Absolute CO2/km moved 26%
across the sweep, while the paired signalized-minus-priority CO2 difference stayed within
~15% (+60.5 to +70.6 g/km, significant at every convention). If the deliverable is a
comparison rather than a level, a coarser `dt` may be defensible — but demonstrate it.

## Euler vs ballistic: where it actually matters

- **Steady cruising: irrelevant.** Ring capacity 2518 vs 2521 veh/h; saturation flow 1857
  vs 1849 veh/h/lane (both at `dt=1 s`).
- **Deceleration: large.** A deterministic vehicle stopping at a red began braking 13.9 m
  earlier under ballistic (569.5 m vs 583.4 m) and used 29.5 m vs 15.6 m of braking distance
  against a textbook `v^2/(2b)` = 21.4 m.
- **There is no stop-line overshoot to fix.** In all 16 configurations the vehicle rested at
  exactly the same point, 1.0 m short of the stop line. SUMO's car-following/junction logic
  enforces the stop directly; the integrator never gets to overshoot it. `dt` changes *when
  braking starts*, not *where it ends* — which is precisely why SSM and emissions (functions
  of the approach trajectory) move so much while stop accuracy does not move at all.
  Do not go looking for an overshoot artifact; measure brake-onset position instead.
- **The gap does not shrink with `dt` under tied `actionStepLength`**: merge conflicts were
  477 (Euler) vs 351 (ballistic) at `dt=1 s`, and 173 vs 291 at `dt=0.1 s` — further apart
  and opposite in sign.

## Testing whether a calibrated parameter set is dt-specific

Re-evaluate a stored calibrated vType against its own targets across the `dt`/method grid,
reusing `calibrate-car-following-parameters-against-field-targets`'s ring probe, `fd_features`
and weighted-RMSN `objective` (import its `cf_common` and wrap `run_sumo` to rewrite the
step/method flags — its `ring_cell` hardcodes ballistic and takes `step` as a kwarg).

**The answer is model-dependent — test, do not assume.** Verified: a calibrated **Krauss**
set held RMSN 0.051-0.071 across the whole grid (transfers fine), while a calibrated **IDM**
set degraded from RMSN 0.044 at its calibration condition to 0.171 at `dt=1 s` ballistic,
with capacity −15% and backward wave speed −33% and only 2 of 5 features in tolerance.
Always re-state the `dt`/method a calibration was performed at as part of the parameter set;
a vType without it is under-specified.

## Cost, and where the cost actually is

- **Runtime scaling in `dt` is sub-linear, not linear** — 10x the steps cost 6.2x the wall
  clock (observed/ideal 0.62). Refining `dt` is cheaper than `1/dt` suggests; don't
  over-budget for it.
- **TraCI dominates `dt`.** Plain CLI vs TraCI stepping without queries: 2.8-6.2x. With two
  per-vehicle queries per step: **39-48x**. A TraCI controller at `dt=1 s` costs far more
  than a CLI run at `dt=0.1 s` — optimise the interface before optimising the step length,
  and batch/subscribe rather than polling per vehicle.
- **`--threads` can make things slower.** 2/4/8 threads ran at 0.65-0.72x single-threaded on
  a small network; thread overhead dominates. Measure before enabling it.
- **Ballistic is not slower than Euler** (marginally faster in every timing run), so there is
  no cost argument for staying on Euler.
- Check for `libsumo` and report its absence rather than skipping the comparison; it was not
  installed in the environment this skill was developed in (`ModuleNotFoundError`).

**Recommended default**, from the measured Pareto front (serial timings, merge testbed):
`--step-method.ballistic` with `actionStepLength="1.0"` on the vType, at `dt = 1 s` for
screening (4.68% mean basket deviation, 1.01 s) or `dt = 0.5 s` for reporting (**1.99%**,
1.72 s -- 4.5x cheaper than the 7.78 s reference). Reserve `dt = 0.1 s` for startup lost
time, severe-conflict counts, and stop-and-go structure.
**Every Euler + tied-actionStepLength cell is strictly dominated**: 28.6% basket error at
`dt=1 s`, and 39.1% at `dt=0.1 s` -- the most expensive cell tested is also the least
accurate, which is the clearest possible illustration that a finer step is not a free
accuracy upgrade.

## Gotchas

- **`--default.action-step-length` changes the integrator silently, even at value 0.** Set
  `actionStepLength` on the vType instead.
- **`actionStepLength > step-length` force-enables ballistic** (with a stderr warning) — the
  `(Euler, pinned reaction time)` factorial cell is unreachable; don't report it as measured.
- **`<flow>`-based demand is not CRN across `dt`** — departure times re-quantise. Pre-write
  explicit `<vehicle depart=...>` entries.
- **SSM encounter type `111` is labelled "collision" but does not mean SUMO registered a
  crash.** Verified: 7-29 type-111 encounters per run with `collisions=0` in both the
  `summary` output and `--collision-output`. Cross-check against those before reporting
  simulated collisions.
- **SSM `PET` can be `NA` for an entire scenario** — a collinear merge produced zero PET
  values across 80 runs. PET needs a genuine crossing conflict; use a 4-arm junction.
- **SSM `PET` can be negative** (rare) — filter or report separately rather than taking a
  raw `min()` as the "worst" value.
- **A metric that gets *better* at fine `dt` is a red flag, not a validation.** Delay,
  conflicts and emissions all improved monotonically as `dt` shrank with tied
  `actionStepLength` — because the drivers became superhuman, not because the answer converged.
- **Report completed / still-running / not-inserted per cell.** Finer `dt` with tied
  `actionStepLength` raised throughput enough to change the completed count by 19%, which
  survivor-biases any mean-delay comparison across `dt` unless it is accounted for.

## Related

- `quantify-sumo-run-to-run-variability` — the CRN/replication discipline used throughout; a `dt` sweep without it cannot distinguish a discretization effect from seed noise.
- `validate-kinematic-wave-theory-across-car-following-models` — the closed-ring FD instrument reused as testbed (a); its FD features turn out to be the most `dt`-robust outputs in memory.
- `measure-saturation-flow-and-validate-webster-method` — testbed (b)'s instrument, and the source of the saturation-flow claim this skill's audit re-qualified.
- `analyze-intersection-safety-with-ssm` — testbed (c)'s instrument; its conflict metrics are the most `dt`-fragile outputs measured.
- `calibrate-car-following-parameters-against-field-targets` — its ring probe/objective are reused directly for the parameter-transferability test.
- `run-simulation` / `run-mesoscopic-simulation` — the coarse end of the same fidelity/cost trade-off this skill quantifies at the micro end.
- [[sumo-time-discretization]] — the verified integration contract, `actionStepLength` semantics, convergence table, sensitivity ranking and cost findings.
- [[sumo-command-line]] — where `--step-length`, `--step-method.ballistic` and `--default.action-step-length` live.
