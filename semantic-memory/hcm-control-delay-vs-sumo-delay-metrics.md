---
summary: HCM control delay, SUMO's tripinfo timeLoss and SUMO's waitingTime are three different quantities measured over three different scopes against three different free-flow datums, and the choice changes the reported LOS letter about a third of the time. Records the verified HCM 6th Ed. Chapter 19 vs SUMO comparison across a v/c 0.4-1.15 sweep, including the upstream-reference-point truncation trap that makes HCM look like it over-predicts oversaturated delay.
keywords:
  - HCM
  - Highway Capacity Manual
  - control delay
  - level of service
  - LOS
  - degree of saturation
  - incremental delay d2
  - uniform delay d1
  - initial queue delay d3
  - back of queue
  - timeLoss
  - waitingTime
  - stopped delay
  - residual queue
  - analysis period
created: 2026-08-04T07:00:00
last_updated: 2026-08-05T19:00:00
sources:
  - "[[episodic-memory/2026-08-04_07-00-00/outputs/COMPARISON.md]]"
  - "[[episodic-memory/2026-08-04_07-00-00/outputs/sweep_results.csv]]"
  - "[[episodic-memory/2026-08-04_07-00-00/outputs/los_agreement.csv]]"
  - https://sumo.dlr.de/docs/Simulation/Output/TripInfo.html
  - https://sumo.dlr.de/docs/Simulation/Output/Lane_Area_Detectors_(E2).html
related_pages:
  - "[[webster-method]]"
  - "[[sumo-output-files]]"
  - "[[actuated-traffic-signals]]"
  - "[[left-turn-storage-bay-length-design]]"
  - "[[sumo-time-discretization]]"
  - "[[unsignalized-vs-signalized-intersection-control]]"
  - "[[signal-clearance-intervals-dilemma-zone-and-safety-capacity-tradeoff]]"
  - "[[mutcd-signal-warrants-and-the-demand-vs-served-volume-trap]]"
  - "[[two-lane-highway-follower-density-and-passing-lane-effectiveness]]"
  - "[[demand-arrival-process-and-unsignalized-capacity]]"
related_skills:
  - generate-hcm-los-report-and-validate-against-microsimulation
  - measure-saturation-flow-and-validate-webster-method
  - design-left-turn-storage-bay-length
  - control-signals-with-actuated-tls
  - analyze-simulation-outputs
  - model-demand-arrival-process-and-its-effect-on-capacity-and-delay
related_skills_for_graph_view:
  - "[[generate-hcm-los-report-and-validate-against-microsimulation]]"
  - "[[measure-saturation-flow-and-validate-webster-method]]"
  - "[[design-left-turn-storage-bay-length]]"
  - "[[control-signals-with-actuated-tls]]"
  - "[[analyze-simulation-outputs]]"
  - "[[model-demand-arrival-process-and-its-effect-on-capacity-and-delay]]"
---

# HCM Control Delay vs SUMO's Native Delay Metrics

Three numbers are routinely called "delay" at a signalized intersection, and they are not
interchangeable:

| | scope | free-flow datum | what it excludes |
|---|---|---|---|
| **HCM control delay** | a fixed segment: an upstream reference point (≈250 m) to a downstream point past the exit | the *measured* undelayed traversal of that same segment | everything outside the segment |
| **SUMO `tripinfo` `timeLoss`** | the whole trip | each **lane's own** speed limit, including the reduced limit on turning internal lanes | the geometric slow-down for a turn (it is "free flow" by SUMO's datum) |
| **SUMO `tripinfo` `waitingTime`** | the whole trip | none - it counts time below the halting-speed threshold | all acceleration/deceleration delay |

## Verified magnitudes

Isolated 4-leg signalized intersection, protected lefts, measured saturation flow and lost time,
pretimed control, Poisson arrivals, T = 1 h analysis period (see
`generate-hcm-los-report-and-validate-against-microsimulation`):

- **Stopped delay / control delay = 0.81-0.85** for the through+right lane group and
  **0.88-0.91** for the exclusive left, throughout the undersaturated range. The classic HCM
  field factor "control delay ≈ 1.3 × stopped delay" implies 0.77 — close, but consistently
  optimistic against what SUMO produces.
- **timeLoss / control delay = 1.10-1.24** in the same range. `timeLoss` reads *higher* not
  because it is a stricter definition but because it covers the whole trip (here a 700 m upstream
  feeder as well as the 250 m measurement segment).
- **Both ratios invert above v/c ≈ 1.05** (stopped/control reaching 1.44 and 1.78, timeLoss/control
  2.02 and 2.64 at v/c = 1.15). This is a **scope** artifact, not a behavioural change: the
  whole-trip attributes keep counting once the queue extends past the control-delay segment's
  upstream reference point, and the segment measure does not.

## The upstream reference point truncates delay - and it does so exactly where the model is being tested

HCM control delay's field-measurement definition uses a fixed upstream reference point. Once the
back of queue passes it, the delay suffered upstream is simply not in the measurement.

Verified, through+right lane group, pretimed:

| v/c | cycles with back of queue past the 250 m point | segment control delay | whole-trip delay | HCM predicted |
|---:|---:|---:|---:|---:|
| 0.95 | 0.00 | 60.0 s | 60.5 s | 65.4 s |
| 1.00 | 0.13 | 115.9 s | 121.1 s | 108.2 s |
| 1.05 | 0.43 | 153.5 s | 177.7 s | 164.0 s |
| 1.15 | 0.72 | 168.9 s | **335.5 s** | 315.7 s |

**Measured against whole-trip delay, HCM Chapter 19 is accurate to −6% at v/c = 1.15. Measured
against the standard 250 m segment, the identical model on the identical run looks like an +87%
over-prediction.** Any claim that "HCM over-predicts oversaturated delay" must state where the
delay was measured; a large part of the classical result is a measurement-scope artifact. Always
report the back-of-queue length in metres against the reference-point distance alongside a control
delay.

## The arrival process decides whether the incremental delay term d2 exists

HCM's `d2 = 900*T*[(X-1) + sqrt((X-1)^2 + 8*k*I*X/(c*T))]` is derived for **random** arrivals - it
is the overflow-queue term. SUMO's `<flow vehsPerHour="...">` inserts vehicles at **equal
headways** (verified departure-headway CV = 0.001); `period="exp(rate)"` gives Poisson
(verified CV = 1.036).

Verified at v/c = 0.95, through+right, pretimed, T = 1 h: HCM `d1` = 37.2 s, `d2` = 28.8 s,
total 65.4 s. Simulated control delay was **45.3 s with uniform arrivals** (i.e. ≈ `d1` alone) and
**60.0 s with Poisson arrivals**. **A deterministic-arrival simulation reproduces `d1` and appears
to refute `d2`; the disagreement is a property of the demand model, not of HCM.** This is the
first thing to check before concluding an analytical delay model is wrong.

## The capacity half of Chapter 19 is sound; the delay half is where the disagreement lives

Fed *measured* saturation flow and *measured* lost time, `c = N*s*g/C` predicted the actually
served throughput in deeply oversaturated pretimed runs to within **1-2% for the exclusive left**
and **4-5% (slightly optimistic) for the through+right lane group**. Verified measured inputs on
the default SUMO Krauss fleet (`--step-length 0.1`, ballistic, `actionStepLength = 1.0` pinned):

| lane | measured s | HCM default |
|---|---:|---:|
| through-only | 2000 veh/h/ln | 1900 |
| shared through + 11.8% right | 1791 veh/h/ln | 1900 × f_RT |
| exclusive protected left | **1264 veh/h/ln** | 1900 × 0.95 = 1805 |

The protected left is **~30% below** the HCM default while the through lane is within 5% - so the
error from accepting defaults is movement-specific, not a uniform offset. Net lost time measured
against the *displayed* green was only **0.25-0.63 s**, not the textbook 3-4 s, because SUMO's
drivers keep discharging through the yellow (the end-of-green extension `e` nearly cancels the
start-up lost time `l1`). Compare [[webster-method]], where the same fleet's through-lane
discharge was found to be ~1890 veh/h/ln with reaction time pinned.

## Actuated control is where HCM diverges most

HCM has no fixed `g/C` for an actuated signal; the standard practice is to use the average green
and average cycle. That average is blind to the *within-cycle correlation* between arrivals and
green duration, which is the entire mechanism of actuation.

Verified, exclusive-left lane group at the top of the sweep (measured mean cycle 146.7 s, measured
mean left green 22.0 s), averaged across all four approaches: HCM computed `c` = 179 veh/h and
v/c = 1.19 and predicted **460 s/veh**; the simulation delivered **79-81 s/veh** with a stable
queue. On the N/S approach pair alone, HCM's `c` = 188 veh/h against an actually-served rate of
202 veh/h (1.08× the HCM capacity) — the 179 and 188 figures are different aggregations (4-way
average vs single approach pair), not a discrepancy; both point the same direction. This ~5.8×
over-prediction is by far the largest disagreement found - larger than anything in the pretimed
case at any v/c. The `k`-factor adjustment (`k = (1-2k_min)(X-0.5) + k_min`, `k_min` from the
unit extension) does not come close to covering it. Conversely, in the *undersaturated* actuated
range HCM and simulation agree almost exactly (92.3 vs 92.5 s/veh at the highest v/c the actuated
plan actually reached, 0.98).

## Residual-queue truncation bias

A vehicle still queued when the analysis period ends emits **no `<tripinfo>` record at all**, so a
run that simply stops at the end of the demand period reports the mean delay of the survivors.
The correction is to keep simulating past the demand period until the network drains, then compute
metrics over vehicles *scheduled to depart* inside the period regardless of when they finish.

Verified (pretimed, Poisson, demand over [0, 3600] s, `--end 7200` which drained every run to
`running = 0`):

| v/c | unfinished at 3600 s | reported mean whole-trip delay bias |
|---:|---:|---:|
| 0.85 | 5.5% | −0.6% |
| 1.00 | 8.2% | −3.8% |
| 1.05 | 10.7% | −6.7% |
| 1.10 | 13.7% | −12.0% |
| 1.15 | 17.8% | **−16.4%** |

The bias is **not proportional to the vehicle loss** - losing 17.8% of vehicles costs 16.4% of the
mean, because the dropped vehicles are systematically the worst-delayed ones.

## Which measurement choices actually move the LOS letter

Across 320 lane-group observations (2 arrival processes × 2 control types × 10 v/c levels ×
4 approaches × 2 lane groups), against a baseline of segment control delay / T = 1 h / full drain:

| choice changed | LOS letter changed | max grades apart |
|---|---:|---:|
| delay definition → stopped delay (`waitingTime`) | 34.1% | 1 |
| delay definition → `timeLoss` | 30.3% | 1 |
| analysis period T = 1 h → first 15 min | 28.4% | 2 |
| analysis period T = 1 h → last 15 min | 17.2% | 1 |
| measurement scope → whole trip | 6.6% | 1 |
| residual-queue truncation | 1.9% | 1 |

**The delay definition and the analysis-period length are first-order; residual-queue handling is
second-order for a segment-scoped measure** (though first-order, −16%, for whole-trip means). An
LOS letter is not reproducible without the triple (delay definition, T, residual-queue handling).

Best overall LOS agreement (80 observations, delay thresholds applied to both sides) was Poisson
arrivals + pretimed control + whole-trip delay: **55 agree, 12 off by one grade, 13 off by two**,
never more than two. The worst was uniform arrivals + actuated control + stopped delay:
**20 agree, 34 off by one, 26 off by two or more**.

## Free-flow datum and desired-speed heterogeneity

Control delay is defined against a free-flow travel time, so that datum has to be measured, not
computed from the posted speed. Verified over a 250 m + 100 m segment at a 13.89 m/s limit: the
geometric free-flow time is 27.1 s, but the measured minimum traversal was 28.8 s for the through
movement and 32.0 s for the protected left (Krauss `sigma` dawdling plus the turn-radius speed
limit on the internal junction lane). Using the geometric datum inflates every control delay by
1.7-4.9 s - a whole LOS grade near a threshold.

**`speedFactor="1.0"` on a vType does not pin desired speed** - the default deviation survives and
vehicles receive factors of 1.15/1.20. `speedFactor="1.0" speedDev="0"` is required. Verified: the
per-movement minimum segment times scattered over 23.9-28.1 s before the fix (below the geometric
free-flow time, which is physically impossible at the posted limit) and tightened to 28.8-32.0 s
with the 5th percentile within 0.2 s of the minimum afterwards.

## Back of queue

HCM's back-of-queue estimate (`Q = Q1 + Q2`, HCM 2000 Ch.16 App. G / HCM 6th Ed. Ch.31) tracked the
simulated per-cycle maximum reasonably in the undersaturated range but the comparison is only as
good as the queue instrument: measure the per-cycle maximum from a multi-lane `laneAreaDetector`
chain using the **actual** signal cycle boundaries (which vary under actuated control), taken from
a `SaveTLSSwitchStates` log, rather than a fixed-width window. The HCM 95th-percentile factor
`f_B95` is a table indexed by `Q`; the Poisson approximation `Q95 = Q + 1.65*sqrt(Q)` is a
defensible substitute but must be labelled as a substitute, not presented as the HCM value.
