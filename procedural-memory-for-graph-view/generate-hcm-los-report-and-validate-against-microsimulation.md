---
name: generate-hcm-los-report-and-validate-against-microsimulation
description: Use this skill when the user wants a standard engineering Level-of-Service (LOS) report for a signalized intersection out of a SUMO run - a per-approach, per-movement table of volume, v/c, control delay, LOS letter and 95th-percentile queue plus the volume-weighted intersection aggregate - and/or wants to check the HCM 6th Ed. Chapter 19 analytical delay model (uniform delay d1, incremental delay d2 with the analysis-period length T and control-type factor k, initial-queue delay d3, progression factor PF, back-of-queue) against microsimulation. Covers measuring true HCM control delay from paired upstream/downstream detectors rather than substituting SUMO's tripinfo timeLoss or waitingTime, the residual-queue truncation bias, and where the HCM model over- or under-predicts SUMO in the oversaturated regime. Trigger on mentions of HCM, Highway Capacity Manual, Level of Service / LOS letter, control delay, v/c or degree of saturation, 95th percentile queue, or "is my SUMO delay the same as HCM delay".
related_skills:
  - measure-saturation-flow-and-validate-webster-method
  - create-single-intersection
  - design-left-turn-storage-bay-length
  - control-signals-with-actuated-tls
  - design-signal-change-and-clearance-intervals
  - analyze-simulation-outputs
  - validate-congested-scenario-results-against-teleport-artifacts
related_skills_for_graph_view:
  - "[[measure-saturation-flow-and-validate-webster-method]]"
  - "[[create-single-intersection]]"
  - "[[design-left-turn-storage-bay-length]]"
  - "[[control-signals-with-actuated-tls]]"
  - "[[design-signal-change-and-clearance-intervals]]"
  - "[[analyze-simulation-outputs]]"
  - "[[validate-congested-scenario-results-against-teleport-artifacts]]"
related_pages:
  - "[[hcm-control-delay-vs-sumo-delay-metrics]]"
  - "[[sumo-output-files]]"
---

# Generate an HCM LOS Report and Validate It Against Microsimulation

Turns a SUMO signalized-intersection run into the report a traffic engineer actually signs
(volume / v/c / control delay / LOS / Q95 per lane group, plus the intersection aggregate),
and independently implements HCM 6th Ed. Chapter 19 so the analytical model can be *tested*
rather than trusted. This is the LOS/control-delay counterpart to
`measure-saturation-flow-and-validate-webster-method` (which validates Webster's cycle-length
optimum); it reuses that skill's measured-not-assumed saturation flow as its capacity input.

`scripts/los_report.py` is the reusable deliverable — point it at a run directory and a config
and it emits the table. `scripts/hcm_lib.py` holds the HCM formulas written out line by line.

## The pipeline

1. `scripts/gen_network.py` — 4-leg intersection, plain XML + netconvert
   (`create-single-intersection`), with an exclusive left-turn bay whose **compiled** length is
   iteratively calibrated (`design-left-turn-storage-bay-length`), a **250 m measurement segment**
   between the entry cross-section and the stop line, and a long upstream **feeder** for queue
   storage. Verified: bay, segment and feeder all compile to their intended lengths within 0.15 m
   after 2 iterations.
2. `scripts/scenario.py` — hand-written pretimed `tlLogic` and an actuated one with the *same*
   phase skeleton, built from the compiled link-index map so state strings are never hand-typed;
   detectors; demand.
3. `scripts/calibrate.py` — measure `s` and lost time per lane, and the free-flow segment
   travel time per movement.
4. `scripts/run_sweep.py` — v/c sweep, both control types, both arrival processes.
5. `scripts/los_report.py` / `analyze_sweep.py` / `make_report.py` / `write_comparison.py` —
   the report, the tables, the plots.

## Measure control delay from paired detectors, and define the segment explicitly

HCM control delay is *actual travel time through the intersection influence area minus the
travel time in the absence of the control*. Instrument it directly:

- `<instantInductionLoop>` on every approach lane at the **entry** cross-section (~250 m upstream
  of the stop line) and on every downstream exit lane ~100 m past the junction. Instant loops
  emit the **vehicle id**, so pairing entry/exit gives an exact per-vehicle segment travel time —
  no FCD file and no E3 aggregation needed. Read the movement off the flow id
  (`f_<approach><movement>.<n>`) rather than trying to infer it from lane geometry.
- Get the free-flow datum by **measuring the minimum observed segment traversal in a
  very-low-demand run**, per movement — do NOT use `segment_length / speed_limit`. Verified:
  the measured free-flow time exceeded the geometric one by 1.7 s for through and 4.9 s for the
  protected left (Krauss `sigma` dawdling plus the turn-radius speed limit on the internal
  junction lane). Using the geometric datum inflates every reported control delay by that amount,
  which is a whole LOS grade near a threshold.
- **Pin the desired speed or the free-flow datum is meaningless.** `speedFactor="1.0"` alone does
  **not** do this — the default deviation survives and vehicles get factors of 1.15/1.20. Set
  `speedFactor="1.0" speedDev="0"`. Verified: before the fix, per-movement minimum segment times
  scattered 23.9-28.1 s; after, they tightened to 28.8-32.0 s with p05 within 0.2 s of the minimum.

## Measure the HCM inputs; do not accept the defaults

Feed `c = N * s * g/C` with a measured `s` and a measured lost time
(`measure-saturation-flow-and-validate-webster-method`), and measure each lane group **on the
geometry it actually operates on**:

- Saturate the through+right lane group and the exclusive-left bay in **separate** runs. A single
  "everything oversaturated" run cannot measure the bay's discharge: a saturated through queue in
  the shared upstream lane physically prevents left-turners from reaching the bay. Verified — in a
  joint-oversaturation run the left-lane green-duration regression returned s = 129-624 veh/h/ln
  at R² = 0.62-0.95, while the through lanes in the *same* run gave 1780-1880 at R² > 0.996.
- **Do not build a "cleaner" calibration network with the exclusive lane running the full
  approach.** Tried and rejected: with three upstream lanes SUMO scatters vehicles into lanes that
  have no continuation for their route and they force a lane change at the stop line. Verified:
  s_left = 876 veh/h/ln on the 3-lane calibration net vs 1466 veh/h/ln for the identical movement
  on the 2-lane operational net, and a through-only run on the calibration net put 2 through
  vehicles per cycle into the left-only lane.
- **`departLane="best"` inserts left-turners into the adjacent through lane under oversaturation**
  (bestLanes ranks by momentary occupancy), and they then force a lane change at the stop line —
  throttling the measured discharge and blocking the through lane at the same time. Pin
  `departLane` per movement instead.

Verified measured values on the default SUMO Krauss fleet
(`--step-length 0.1`, ballistic, `actionStepLength=1.0`): through-only lane
**2000 veh/h/ln**, shared through+right lane (11.8% RT) **1791**, exclusive protected left
**1264** — i.e. the protected left is **~30% below** the HCM 1900×0.95 default while the through
lane is within 5%. Net lost time against the *displayed* green was only **0.25-0.63 s**, not the
textbook 3-4 s, because SUMO's drivers keep discharging through the yellow (`e` ≈ `l1`).

**These capacities are correct.** Verified against measured throughput in the deeply oversaturated
runs: served volume / HCM capacity = 0.99-1.02 (left) and 0.95-0.96 (through+right) under pretimed
control. The capacity half of Chapter 19 is sound once fed measured inputs.

## The arrival process decides whether d2 is real — check it before blaming the model

`<flow vehsPerHour="...">` inserts vehicles at **equal headways** (verified: coefficient of
variation of departure headways = 0.001). HCM's incremental delay `d2` is derived for **random**
arrivals. Use `period="exp(<veh/s>)"` for Poisson (verified CV = 1.036).

Verified consequence, through+right lane group at v/c = 0.95, pretimed, T = 1 h:
simulated control delay was **45.3 s with uniform arrivals** (essentially HCM's `d1` = 37.2 s
alone, `d2` = 28.8 s contributing almost nothing) versus **60.0 s with Poisson arrivals**
against an HCM total of 65.4 s. **With deterministic arrivals a simulation reproduces d1 and
falsely appears to refute d2; the disagreement is an artifact of the demand model, not of HCM.**

## The 250 m reference point silently truncates delay once the queue passes it

This is the single biggest trap in validating HCM against simulation, and it bites exactly in the
oversaturated regime the validation is aimed at. Once the back of queue extends past the upstream
reference point, everything a vehicle suffers upstream of it is outside the measured segment.

Instrument it: give the `laneAreaDetector` chains a `maxJamLengthInMeters` read-out and report the
**fraction of cycles whose back of queue exceeded the entry cross-section**. Verified for the
through+right lane group under pretimed control: 0.00 up to v/c = 0.95, then 0.13 / 0.43 / 0.72 at
v/c = 1.00 / 1.05 / 1.15. Over that same range the segment-scoped control delay reads 116 / 154 /
169 s while the whole-trip delay for the same vehicles is 121 / 178 / **336** s.

**Report both scopes.** Against the whole-trip delay HCM is accurate to −6% at v/c = 1.15
(316 vs 336 s); against the 250 m segment it looks like an +87% over-prediction. Same model, same
run — only the measurement point differs.

## Residual queue: quantify it, do not just drain it

A vehicle still queued at the end of the analysis period emits **no `<tripinfo>` record**, so a
run that simply stops at the end of the demand period reports the mean delay of the survivors.
Fix by simulating well past the demand period (verified: demand over [0, 3600] s with `--end 7200`
drained every run to `running=0`, 0 teleports, 0 collisions), then compute metrics both ways.

Verified bias, pretimed + Poisson, comparing "run ended at 3600 s" against the drained run:

| v/c | vehicles unfinished at 3600 s | reported mean delay bias |
|---:|---:|---:|
| 0.85 | 5.5% | −0.5% |
| 1.00 | 8.2% | −3.6% |
| 1.05 | 10.7% | −6.4% |
| 1.10 | 13.7% | −11.7% |
| 1.15 | 17.8% | **−15.8%** |

Note the two are **not** proportional: losing 17.8% of vehicles costs 15.8% of the mean delay,
because the lost vehicles are systematically the worst-delayed ones.

## Implement HCM Chapter 19 explicitly

`scripts/hcm_lib.py`, written out so each line can be checked against the textbook:

```
c   = N * s * g/C                      s = MEASURED, g = displayed green - MEASURED lost time
X   = v/c
d1  = 0.5*C*(1-g/C)^2 / (1 - min(1,X)*g/C)
k   = 0.5 (pretimed);  actuated: k = (1-2*k_min)*(X-0.5) + k_min, clipped to [k_min, 0.5],
      k_min from the unit extension (2.0s->0.04 ... 5.0s->0.23)
d2  = 900*T*[(X-1) + sqrt((X-1)^2 + 8*k*I*X/(c*T))]        I = 1.0 for an isolated intersection
d3  = 1800*Qb*(1+u)*t/(c*T)   with t = min(T, Qb/(c*(1-X))) for X<1 else T,
      u = 0 if t<T else max(0, 1 - (c*T/Qb)*(1-min(1,X)))
PF  = (1-P)*fPA/(1-g/C)                = 1.0 for isolated/random arrivals (P = g/C)
d   = d1*PF + d2 + d3
LOS: A<=10, B<=20, C<=35, D<=55, E<=80, F>80 s/veh   (+ LOS F whenever v/c > 1)
Q1  = PF2 * (v/N)*C*(1-g/C) / (3600*(1 - min(1,X)*g/C))
Q2  = 0.25*(c/N)*T*[(X-1) + sqrt((X-1)^2 + 8*kB*X/((c/N)*T))]     kB = 0.12 pretimed / 0.10 actuated
Q   = Q1 + Q2
```

**Honest deviation:** HCM's 95th-percentile back-of-queue factor `f_B95` is a table indexed by `Q`
that is not reproduced here; `Q95 = Q + 1.65*sqrt(Q)` (the Poisson approximation) is used instead
and is labelled as such in the output. Do not present it as the HCM table value.

Verified: the "LOS F whenever v/c > 1" override never changed the letter in 320 lane-group rows —
by the time v/c reaches 1 the delay is already past 80 s/veh, so the override is redundant here,
not load-bearing.

## For actuated control, use the MEASURED average green and cycle - and expect an over-prediction

There is no fixed `g/C` to plug in. Log the signal with
`<timedEvent type="SaveTLSSwitchStates" source="<tlsID>" dest="..."/>` and derive the mean green
per phase and the mean cycle inside the analysis period (`los_report.signal_timing`). Verified the
actuated logic genuinely adapts: mean cycle 52.5 s at low demand to 146.7 s at the top of the
sweep.

Verified divergence: for the exclusive-left lane group at nominal v/c = 1.15, averaged across
all four approaches, the actuated plan's average g/C gave HCM `c` = 179 veh/h and X = 1.19,
predicting **460 s/veh**; the simulation delivered **79-81 s/veh** with a stable queue. On the
single N/S approach pair specifically, HCM's `c` = 188 veh/h against an actual served rate of
202 veh/h (1.08x HCM capacity) — the two figures (179 four-way-average vs 188 single-approach)
are different aggregations, not a discrepancy; both tell the same story. **The HCM average-g/C
formulation cannot represent the within-cycle correlation between arrivals and green duration
that is the entire point of actuation**, so it both under-states actuated capacity and
over-states actuated oversaturated delay — by far the largest disagreement found anywhere in
this study. The `k`-factor adjustment does not come close to covering it.

## Report the delay definitions side by side

Verified ratios, pretimed + Poisson, T = 1 h (whole-trip tripinfo attributes against the
segment-scoped control delay):

| regime | stopped delay / control delay | timeLoss / control delay |
|---|---:|---:|
| v/c 0.40-1.00, through+right | 0.81-0.85 | 1.10-1.22 |
| v/c 0.40-1.00, exclusive left | 0.88-0.91 | 1.21-1.24 |
| v/c 1.15 | 1.44 (TR) / 1.78 (L) | 2.02 (TR) / 2.64 (L) |

The classic HCM field factor of ~1.3 (control ≈ 1.3 × stopped) corresponds to a ratio of 0.77 —
close to, but consistently above, the 0.81-0.85 measured here for the through lane group. The
ratios **invert above 1.0 once the queue leaves the measured segment**, which is a scope artifact,
not a behavioural change: the tripinfo attributes cover the whole trip and the control delay does
not.

## Which measurement choices actually move the LOS letter

Across 320 lane-group observations (2 arrival processes x 2 control types x 10 v/c levels x
4 approaches x 2 lane groups), against a baseline of segment control delay / T = 1 h / full drain:

| choice changed | LOS letter changed | max grades |
|---|---:|---:|
| delay definition -> stopped delay (`waitingTime`) | 34.1% | 1 |
| delay definition -> `timeLoss` | 30.3% | 1 |
| analysis period T = 1 h -> first 15 min | 28.4% | 2 |
| analysis period T = 1 h -> last 15 min | 17.2% | 1 |
| measurement scope -> whole trip | 6.6% | 1 |
| residual-queue truncation | 1.9% | 1 |

**The delay definition and the analysis-period length are first-order; the residual-queue
correction is not** (at least not for a segment-scoped measure — it *is* first-order, −15.8%, for
whole-trip means). Report the triple (delay definition, T, residual-queue handling) with any LOS
letter.

## Gotchas

- **`speedFactor="1.0"` does not pin desired speed** — the default deviation survives. Add
  `speedDev="0"`. This corrupts any free-flow-referenced delay measurement.
- **`vehsPerHour` is deterministic, not Poisson.** Use `period="exp(rate)"` before concluding
  anything about HCM's `d2`.
- **`departLane="best"` misassigns turning vehicles under congestion.** Pin `departLane` per
  movement, and verify from stop-line detector counts that vehicles are on the lane you intended.
- **The upstream reference point truncates delay once the queue passes it.** Always report
  `maxJamLengthInMeters` against the reference-point distance alongside any control delay.
- **A multi-lane `laneAreaDetector` needs a genuinely consecutive lane chain** — the chain differs
  between a bay geometry (`feed_1 inA_1 inB_2`) and a full-length exclusive lane
  (`feed_2 inA_2 inB_2`), and a wrong chain is a hard SUMO error, not a warning.
- **Measure each lane group on the geometry it operates on**; a "cleaner" isolation network can
  measure a *worse* number than the real one.
- **Do not compute the HCM inputs at one `--step-length` and run the sweep at another** unless
  `actionStepLength` is pinned — see [[sumo-time-discretization]].
- **Instant induction loops emit an `enter`/`stay`/`leave` triple per vehicle**; use `enter` at
  both ends for a front-bumper-to-front-bumper segment time, and `leave` at a stop line for the
  HCM/Teply discharge-headway convention.

## Related

- `measure-saturation-flow-and-validate-webster-method` — supplies the measured `s`/lost time that
  this skill feeds into `c = N*s*g/C`; this skill confirmed its methodology and extends the same
  measure-don't-assume discipline to the free-flow datum and the arrival process.
- `create-single-intersection` — the plain-XML + netconvert base this test bed is built on.
- `design-left-turn-storage-bay-length` — the compiled-length calibration and the
  laneAreaDetector queue instrumentation reused here; its bay-blockage/starvation failure mode is
  what breaks a naive joint-oversaturation saturation-flow measurement.
- `control-signals-with-actuated-tls` — the actuated conventions; this skill adds the
  `SaveTLSSwitchStates` route to the measured average `g`/`C` that HCM needs.
- `design-signal-change-and-clearance-intervals` — lost-time measurement conventions.
- `analyze-simulation-outputs` — tripinfo/summary parsing conventions.
- `validate-congested-scenario-results-against-teleport-artifacts` — the teleport/gridlock
  validity checks applied to every oversaturated run here (0 teleports by construction,
  `--time-to-teleport -1`, verified `running = 0` at the end).
- [[hcm-control-delay-vs-sumo-delay-metrics]] — the theory, the verified divergence findings and
  the measurement-scope trap.
- [[sumo-output-files]] — tripinfo `timeLoss`/`waitingTime` semantics.
