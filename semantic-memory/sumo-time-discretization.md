---
summary: SUMO's time discretization is three coupled choices, not one - the step length, the integration method (semi-implicit Euler vs ballistic), and the vType actionStepLength that doubles as driver reaction time. Euler's position update carries a permanent v*dt/2 error, actionStepLength greater than the step length silently force-enables ballistic, and refining the step length while letting actionStepLength follow it changes driver reaction time rather than numerical accuracy.
keywords:
  - step-length
  - ballistic integration
  - semi-implicit Euler
  - actionStepLength
  - reaction time
  - numerical convergence
  - discretization artifact
  - dt sensitivity
created: 2026-08-04T02:30:00
last_updated: 2026-08-04T04:00:00
sources:
  - "[[episodic-memory/2026-08-04_02-30-00/outputs/CAVEAT_NOTE.md]]"
  - "[[episodic-memory/2026-08-04_02-30-00/outputs/CONVERGENCE_TABLE.md]]"
  - https://sumo.dlr.de/docs/Simulation/Basic_Definition.html
related_pages:
  - "[[sumo-command-line]]"
  - "[[kinematic-wave-theory-validity-across-car-following-models]]"
  - "[[car-following-parameter-calibration-and-identifiability]]"
  - "[[surrogate-safety-measures]]"
  - "[[webster-method]]"
  - "[[sumo-stochastic-variability-and-replication-design]]"
  - "[[vehicle-emissions-modeling]]"
  - "[[freeway-work-zone-capacity-closure-representation-and-merge-control]]"
related_skills:
  - choose-time-discretization-and-integration-method
  - measure-saturation-flow-and-validate-webster-method
  - design-and-control-freeway-work-zone-lane-closures
  - validate-kinematic-wave-theory-across-car-following-models
  - analyze-intersection-safety-with-ssm
  - calibrate-car-following-parameters-against-field-targets
related_skills_for_graph_view:
  - "[[choose-time-discretization-and-integration-method]]"
  - "[[measure-saturation-flow-and-validate-webster-method]]"
  - "[[design-and-control-freeway-work-zone-lane-closures]]"
  - "[[validate-kinematic-wave-theory-across-car-following-models]]"
  - "[[analyze-intersection-safety-with-ssm]]"
  - "[[calibrate-car-following-parameters-against-field-targets]]"
---

# SUMO Time Discretization

`--step-length` is not a lone accuracy knob. Three settings jointly determine what a SUMO
run means, and in SUMO they are **not independent**:

| setting | what it controls | default |
|---|---|---|
| `--step-length` | simulation time step `dt` | 1.0 s |
| `--step-method.ballistic` | position-update rule | off (semi-implicit Euler) |
| vType `actionStepLength` | how often a driver re-decides = **reaction time** | equals `--step-length` |

Because the default `actionStepLength` *follows* the step length, shrinking `dt` from 1.0 s
to 0.1 s does not only refine the numerics — it also cuts modelled driver reaction time by
a factor of ten. Almost everything commonly attributed to "numerical convergence" in SUMO is
in fact this reaction-time change.

## The position-update contract, verified against a closed form

A vehicle accelerating from rest at constant `a` has the exact solution `x(t) = 0.5*a*t^2`.
Comparing SUMO's reported position against it isolates the integrator with no traffic
confound (`scripts/exp_integration_rule.py` in the source episode):

- **Semi-implicit Euler (default)**: `x(t+dt) = x(t) + v(t+dt)*dt`. The whole step is
  travelled at the *new* speed, so the vehicle runs **ahead** of the truth. The error grows
  linearly during acceleration, `e(t) = a*dt*t/2`, and freezes into a **permanent offset of
  `v*dt/2`** once the vehicle stops accelerating. Verified: at `a=2.6 m/s^2` the error at
  `t=1 s` was exactly 1.30 / 0.65 / 0.32 / 0.13 m at `dt` = 1 / 0.5 / 0.25 / 0.1 s, and the
  settled offset at `v=13.89 m/s` was 6.65 m at `dt=1 s`, 0.70 m at `dt=0.1 s`.
- **Ballistic** (`--step-method.ballistic`): `x(t+dt) = x(t) + (v(t)+v(t+dt))/2*dt`. This is
  **exact** for piecewise-constant acceleration — measured error stayed at or below 0.005 m
  (the FCD output's own rounding) at every step length tested, including `dt = 1 s`.

So ballistic is not "more accurate at fine dt": it is *exact at every dt* for the constant-
acceleration segments that car-following models actually produce. Euler's error is
first-order in `dt` and never vanishes at a fixed `dt`.

## actionStepLength is a reaction time, and it silently overrides the integrator

Two behaviours verified on SUMO 1.27.1, both easy to trip over:

1. **A vType `actionStepLength` strictly greater than `--step-length` force-enables ballistic
   integration, even in a run that never asked for it.** SUMO says so on stderr —
   `Action step length '1.00' is used for vehicle type 'car' but step-method.ballistic was
   not set. Setting it now to avoid collisions.` — but the message is easy to miss in a batch.
   Verified: at `dt` = 0.5 / 0.25 / 0.1 s with `actionStepLength="1.0"`, an otherwise-Euler
   run reproduced the exact solution. Setting `actionStepLength` *equal* to the step length
   does **not** trigger it (Euler is preserved), and at `dt = 1 s` with `actionStepLength=1.0`
   there is nothing to trigger.
   **Consequence: the (Euler, actionStepLength > step-length) combination does not exist in
   SUMO.** A `step-length x method x actionStepLength` factorial is not a full factorial —
   it collapses to three distinct arms per step length, not four.
2. **Merely supplying `--default.action-step-length` on the command line switches Euler to the
   exact update — even with the value `0`, which is its own documented default — and does so
   SILENTLY, with no warning at all.** Verified at `dt=0.5 s` for the values 0, 0.5 and 1.0.
   This is the more dangerous of the two: passing the option "to be explicit" changes results.
   Do not pass `--default.action-step-length` unless a non-default reaction time is intended.

## Refining dt does not converge unless actionStepLength is held fixed

Convergence toward a reference of `dt = 0.1 s`, ballistic, `actionStepLength = 1.0 s`, on
three testbeds (ring FD, signalized approach, priority merge), CRN seeds throughout:

- With **`actionStepLength` tied to `dt`** (the default, and what everyone does), refinement
  is **not convergent** — deviations *grow* as `dt` shrinks, because the run is walking away
  from a 1-s-reaction-time driver toward a 0.1-s-reaction-time one. Saturation flow rose
  +19.9%, severe conflicts (TTC < 1.5 s) fell to **exactly zero**, and mean time loss fell
  −22.6% between `dt=1 s` and `dt=0.1 s`.
- With **`actionStepLength` pinned at 1.0 s**, refinement is a substantially cleaner
  convergence study — monotone for most, though not literally all, metrics (a handful,
  including pulse depth and a few merge-testbed metrics, still show minor non-monotonicity)
  — and most metrics are already converged at the 1-second default.

Coarsest step length still within 2% of the reference, with reaction time pinned:

| within 2% at | metrics |
|---|---|
| `dt = 1.0 s` | ring capacity `q_max`, critical density, free-flow speed, backward wave speed, saturation flow, mean trip duration |
| `dt = 0.5 s` | mean time loss, completed-trip count, conflict count, min TTC, merge CO2/km |
| `dt = 0.25 s` | signalized-approach CO2/km |
| **`dt = 0.1 s` required** | **startup lost time, severe-conflict count (TTC < 1.5 s), residual stop-and-go speed dispersion** |

**Exception — this table is testbed-dependent, not universal.** A follow-up study on a
freeway work zone (see [[freeway-work-zone-capacity-closure-representation-and-merge-control]])
found that "capacity" and "mean trip duration" are *not* trustworthy at `dt = 1.0 s` on
every testbed: at a forced-merge taper, `dt = 1.0 s` (reaction time pinned) gave
work-zone capacity **+6.2%** and mean trip duration **-14.6%** against a `dt = 0.25 s`
reference — both far outside the 2% band above. The reaction-time confound was present
there too (capacity moved +2.8% with `actionStepLength` tied vs -5.8% pinned between
`dt=1.0 s` and `dt=0.25 s` — opposite signs — confirming this is a genuine discretization
effect, not a different mechanism). **The distinction is what "capacity" is measuring**:
the ring/saturation-flow instruments above are steady-state or car-following-limited
metrics, which converge quickly; a work-zone's capacity is set by *forced lane-change gap
acceptance in a taper*, a mechanism that behaves like the merge/SSM family (dt-fragile),
not the equilibrium-FD family (dt-robust). **Before trusting this table's `dt = 1.0 s`
row for a new metric, ask whether that metric is an equilibrium/steady-state quantity or
a forced-gap-acceptance quantity — the two families converge at very different step
lengths on the same nominal "capacity" label.**

## Where Euler and ballistic actually differ

Not in steady cruising. On a closed ring at `dt=1 s`, Euler and ballistic capacities were
2518 vs 2521 veh/h (0.1% apart); saturation flow was 1857 vs 1849 veh/h/lane (0.4% apart).

They differ in **deceleration-dominated** situations. A single deterministic vehicle
approaching a red light at 13.89 m/s began braking 13.9 m further upstream under ballistic
(x = 569.5 m) than under Euler (x = 583.4 m), and used 29.5 m vs 15.6 m of braking distance
against a textbook `v^2/(2b)` of 21.4 m.

**Euler does not make vehicles overshoot a stop line.** In all 16 tested configurations the
vehicle came to rest at exactly the same place — 1.0 m short of the stop line — because
SUMO's car-following/junction logic enforces the stopping constraint directly rather than
letting the integrator decide. The discretization changes *when braking starts*, not *where
it ends*; that is why approach-trajectory-sensitive outputs (SSM, emissions) move a lot while
stop-position accuracy does not move at all.

The Euler-vs-ballistic gap in *derived* metrics does not shrink with `dt` under the default
tied `actionStepLength`: merge conflict counts were 477 (Euler) vs 351 (ballistic) at
`dt=1 s`, and 173 vs 291 at `dt=0.1 s` — further apart, and in the opposite direction.

## Which output classes are fragile

Maximum deviation across `dt` in {1, 0.5, 0.25, 0.1} s, most to least fragile:

| output class | tied `actionStepLength` | pinned at 1.0 s |
|---|---:|---:|
| severe-conflict count (TTC < 1.5 s) | 100% | 12% |
| startup lost time | 96% | 60% |
| residual stop-and-go speed dispersion | 91% | 4% |
| min TTC | 80% | 2% |
| total conflict count | 50% | 2% |
| CO2 per km (signalized) | 26% | 13% |
| mean time loss (signalized) | 23% | 2% |
| saturation flow | 20% | 1% |
| ring capacity `q_max` | 8% | 0.0% |
| backward wave speed | 6% | 1% |
| free-flow speed / critical density | 2% / 0.8% | 0.0% |

**Safety (SSM) and emissions are far more `dt`-fragile than aggregate travel time**, and
equilibrium fundamental-diagram features are the most robust of all — `k_crit`, `v_free` and
`q_max` are essentially `dt`-invariant once reaction time is fixed. Startup lost time is the
one metric that genuinely needs a fine step for *numerical* reasons: a ~1.5 s lost time
cannot be resolved by a 1 s step at all (measured 0.60 s at `dt=1 s` vs 1.51 s at `dt=0.1 s`).

**A level can be fragile while a paired contrast is robust.** Absolute CO2/km moved 26%
across the `dt` sweep, yet the CRN-paired signalized-minus-priority CO2 difference was stable
(+60.5 to +70.6 g/km, significant at every convention). Common Random Numbers cancel much of
the shared discretization bias, so a *comparison* can be trustworthy at a step length where
neither *level* is.

## Are calibrated car-following parameters dt-specific?

Model-dependent — do not assume either answer:

- **Krauss transfers.** The archived calibrated Krauss vType held a weighted RMSN of
  0.051-0.071 against its five FD targets across the entire `dt`/method grid, comfortably
  inside the RMSN < 15% acceptance criterion everywhere.
- **IDM does not.** The archived calibrated IDM vType went from RMSN 0.044 at its own
  calibration condition (`dt=0.5 s`, ballistic) to 0.171 at `dt=1 s` ballistic, with `q_max`
  falling to 1861 veh/h/lane (target 2200, −15%) and backward wave speed collapsing to
  11.8 km/h (target 17.5, −33%), leaving only 2 of 5 features inside tolerance. Under Euler,
  IDM overshot `q_max` (2281-2302) and wave speed (21.6-22.5) at every fine step length.

This mirrors the prior finding that the fundamental diagram is largely a property of the
car-following model: so is that model's sensitivity to the integrator.

## Cost

On a small merge scenario (1800 s of simulation), measured serially:

- Runtime scaling in `dt` is **sub-linear**, not linear: 10x the steps cost only 6.2x the
  wall-clock (observed/ideal ratio 0.62). Refining `dt` is cheaper than `1/dt` suggests.
- Real-time factor fell from ~7800 at `dt=1 s` to ~1255 at `dt=0.1 s`.
- **TraCI is the dominant cost, not `dt`.** Stepping through TraCI without any queries cost
  2.8-6.2x a plain CLI run; adding two per-vehicle queries per step cost **39-48x**. A
  TraCI controller at `dt=1 s` is far more expensive than a CLI run at `dt=0.1 s`.
- `--threads` 2/4/8 made this scenario **slower** (0.65-0.72x of single-threaded) — thread
  overhead dominates on small networks.
- `libsumo` was **not installed** in the tested environment (`ModuleNotFoundError`), so the
  libsumo-vs-TraCI comparison could not be run; it is documented as missing rather than
  silently omitted.

Measured Pareto front (serial wall-clock, merge testbed with SSM + emissions devices, basket
of conflicts / TTC<1.5 s count / time loss / CO2 per km):

| cell | wall | mean deviation from reference |
|---|---:|---:|
| `dt=1 s`, ballistic | 1.01 s | 4.68% |
| `dt=0.5 s`, ballistic, `actionStepLength=1 s` | 1.72 s | **1.99%** |
| `dt=0.1 s`, ballistic, `actionStepLength=1 s` (reference) | 7.78 s | 0% |

`dt=0.5 s` + ballistic + pinned reaction time buys 2% fidelity at **4.5x less** wall-clock
than the reference. Every Euler-with-tied-actionStepLength cell is strictly dominated
(28.6% error at `dt=1 s`, and *39.1%* at `dt=0.1 s` — the most expensive cell tested is also
the least accurate).

## Practical contract

1. Turn ballistic on. It is exact for constant acceleration at every `dt`, and it costs
   nothing (it was marginally *faster* than Euler in every timing run).
2. Set `actionStepLength` explicitly on the vType to a real reaction time (~1 s) and keep it
   fixed when sweeping `dt`. Do not use `--default.action-step-length` for this — it changes
   the integrator silently.
3. Report the triple (`step-length`, integration method, `actionStepLength`) with any
   quantitative result. A capacity or conflict number without it is not reproducible.
4. Never compare two runs that differ in `dt` unless `actionStepLength` is pinned; otherwise
   the comparison is about driver reaction time, not about the treatment.
