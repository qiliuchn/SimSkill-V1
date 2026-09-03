---
summary: A field turning-movement count is a served volume, so on a saturated approach it measures capacity rather than demand; verified in SUMO the 4-hour total survives (98.9% of true demand) while the peak hour is clipped to 86.6% and the worst 15 minutes to 80.3%, inflating the measured PHF from a true 0.870 to 0.983 and making a rebuilt model under-predict control delay by 32% and the 95th-percentile queue by 47% while passing GEH<5 on 100% of movement-bins.
keywords:
  - turning-movement-count
  - count-to-demand-workflow
  - peak-hour-factor
  - design-hour-k-factor
  - tmc-balancing
  - residual-queue-correction
  - equifinality
created: 2026-08-05T00:00:00
last_updated: 2026-08-05T00:00:00
sources:
  - "[[episodic-memory/2026-08-04_22-00-00/outputs/DECISION_RULE.md]]"
  - "[[episodic-memory/2026-08-04_22-00-00/outputs/demand_recovery_table.csv]]"
  - "[[episodic-memory/2026-08-04_22-00-00/outputs/performance_table.csv]]"
  - "[[episodic-memory/2026-08-04_22-00-00/outputs/geh_pass_rate_table.csv]]"
  - "[[episodic-memory/2026-08-04_22-00-00/outputs/phf_table.csv]]"
  - "[[episodic-memory/2026-08-04_22-00-00/outputs/iterative_scaling_table.csv]]"
  - "[[episodic-memory/2026-08-04_22-00-00/outputs/balancing_report_over.csv]]"
  - "[[episodic-memory/2026-08-04_22-00-00/outputs/replication_noise_floor.json]]"
related_pages:
  - "[[mutcd-signal-warrants-and-the-demand-vs-served-volume-trap]]"
  - "[[od-matrix-estimation-and-underdetermination]]"
  - "[[geh-statistic]]"
  - "[[hcm-control-delay-vs-sumo-delay-metrics]]"
  - "[[automated-traffic-signal-performance-measures]]"
  - "[[teleport-artifacts-and-gridlock-resolution-validity]]"
  - "[[sumo-stochastic-variability-and-replication-design]]"
  - "[[sumo-output-files]]"
  - "[[dfrouter-detector-based-demand-reconstruction]]"
  - "[[routesampler]]"
  - "[[webster-method]]"
  - "[[arterial-signal-progression-resonance-bandwidth-and-delay]]"
related_skills:
  - reconstruct-simulation-demand-from-field-turning-movement-counts
  - estimate-od-matrix-with-odme
  - conduct-driveway-signal-warrant-traffic-impact-analysis
  - generate-hcm-los-report-and-validate-against-microsimulation
  - build-atspm-pipeline-and-retime-arterial
  - quantify-sumo-run-to-run-variability
  - validate-congested-scenario-results-against-teleport-artifacts
related_skills_for_graph_view:
  - "[[reconstruct-simulation-demand-from-field-turning-movement-counts]]"
  - "[[estimate-od-matrix-with-odme]]"
  - "[[conduct-driveway-signal-warrant-traffic-impact-analysis]]"
  - "[[generate-hcm-los-report-and-validate-against-microsimulation]]"
  - "[[build-atspm-pipeline-and-retime-arterial]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[validate-congested-scenario-results-against-teleport-artifacts]]"
---

# Field Counts to Simulation Demand, and the Saturated-Count Truncation Trap

A turning-movement count (TMC) is the standard input to a signalized-corridor
microsimulation, and it is a count of **departures across a stop bar** — a *served*
volume. Under capacity that equals demand. Over capacity it equals the approach's
discharge capacity, and the model built from it inherits that truncation. This page
records the workflow, the size of the error, the correction that works, and the
threshold at which the correction becomes mandatory. The stop-controlled-minor-approach
version of the same phenomenon is in
[[mutcd-signal-warrants-and-the-demand-vs-served-volume-trap]]; the zone-level
version is [[od-matrix-estimation-and-underdetermination]].

## The count-to-demand workflow, stated

1. **Design hour.** From a mid-block ATR/permanent-count profile compute
   `K = DHV / daily` (daily = counted total / count-expansion factor) and the
   directional split `D`. Support both "use the observed peak hour" and
   "apply `K30 x AADT`"; the second scales every movement by `K30*AADT / DHV_obs`.
2. **Peak-hour factor.** `PHF = V / (4 * V15max)`, with the peak hour located by a
   **sliding 4-bin search**, never assumed clock-aligned.
3. **Balancing.** For each directional link between adjacent counted intersections,
   the upstream departing volume `U` and the downstream arriving volume `A` will not
   match. Reconcile with `B = w*U + (1-w)*A` (w = 0.5 = equal confidence) and rescale
   the downstream approach's movements to sum to `B`, preserving its turn ratios.
   Report the pre-balance imbalance per link per bin.
4. **Heavy vehicles and growth.** `f_HV = 1/(1 + P_HV*(E_T - 1))`, PCE volume
   `v/f_HV`, growth factor multiplicative.
5. **Emission.** Propagate each counted boundary approach through the corridor by
   the observed turn ratios, reconcile at each downstream approach, emit one
   `<flow>` per path per 15-minute bin with the routes that realise them.

## The three validation levels, which must be kept separate

- **Count fit** — reconstructed-run stop-bar counts vs the observed counts. This is
  what the workflow was built to reproduce, so it is **not evidence the demand is
  right** (same argument as [[od-matrix-estimation-and-underdetermination]]).
- **Demand recovery** — reconstructed input flow vs the true injected flow. Only
  computable in a synthetic experiment; unobservable in a real study, which is
  exactly the problem.
- **Performance recovery** — control delay, 95th-percentile back of queue, LOS
  letter, residual queue at the end of the peak.

## How large the truncation is

Verified on a 3-signal coordinated arterial (400 m spacing, C = 90 s, arterial
through green 41 s, 2 through lanes + exclusive left bay, measured saturation flow
1762 and 1838 veh/h/ln, maximum observed 15-minute discharge 1700 veh/h), two demand
arms at **measured v/c 0.74 and 1.14**, `--time-to-teleport -1`, 0 teleports,
0 collisions, every vehicle arrived, **zero insertion backlog at every 15-min
boundary in both arms**.

Stop-bar count divided by realized generated demand, critical through movement:

| | v/c 0.74 | v/c 1.14 |
|---|---|---|
| 4-hour total | 0.988 | **0.989** |
| true peak hour | 0.991 | **0.866** |
| worst 15-min bin | 0.884 | **0.803** |
| the three bins after the peak | 1.095 / 0.965 / 1.011 | **1.235 / 1.459 / 1.234** |

**The total volume is not lost — the peak is clipped and smeared forward.** A
total-volume or daily-volume reasonableness check passes cleanly (98.9 % recovery)
while every peak-derived design quantity is wrong. This is the opposite shape from
the stop-controlled case in
[[mutcd-signal-warrants-and-the-demand-vs-served-volume-trap]], where the count is
depressed for the whole study hour because the *capacity itself* falls; at a signal
the capacity is fixed by the green split, so the deficit is stored and released.

## PHF is the diagnostic, and 0.95 is the threshold

Truncating the peak while preserving the total is exactly the operation that
*raises* the measured PHF. True injected PHF was 0.870 on every arterial approach;
the stop-bar counts recovered 0.879 / 0.900 / 0.899 undersaturated (+1.0 to +3.4 %)
and **0.983 / 0.976 / 0.980** oversaturated (+12.2 to +12.9 %, about 14 run-to-run
standard deviations).

Across 9 approach-arm cases carrying more than 1000 veh in the peak hour the
uncorrected peak-hour demand error separates cleanly and with a wide gap:

| measured stop-bar PHF | n | uncorrected peak-hour demand error |
|---|---|---|
| 0.879 – 0.940 | 6 | -2.4 % to -1.4 % |
| 0.976 – 0.983 | 3 | -14.7 % |

**A stop-bar-measured approach PHF at or above 0.95 is a truncation signature, not a
genuinely flat arrival profile.** Two qualifiers:

- Apply the test only above roughly 1000 veh/h. On the 15 approaches below that, the
  uncorrected error averaged 4.5 % and reached 11.5 % from Poisson count noise
  alone, with no congestion involved.
- **A residual-queue diagnostic is necessary but not sufficient, and PHF beats it.**
  In the oversaturated arm exactly one approach stored a queue (69.5 veh at its
  worst bin; every other approach 0.0–0.2 veh), yet the two *downstream* arterial
  approaches were truncated by 14.7 % each **with no queue of their own** — they are
  metered by the upstream signal, so their own stop-bar count is a capacity. PHF
  flagged all three; the queue flagged one.

An ATR station upstream of the queue is immune: it located the true peak-hour window
correctly in both arms (the stop-bar PHF search was one bin late in the congested
arm), recovered `D` as 0.607 / 0.614 against a true 0.613, and the design-hour volume
to within +0.1 % / -1.1 %. Verify empirically that such a station is beyond the back
of queue by comparing its per-bin count against demand rather than arguing from
geometry (verified total ratio 0.999, per-bin 0.986–1.034).

## What the truncation costs, and what count fit says about it

Critical approach, true peak hour (4-seed noise floor in brackets):

| quantity | ground truth | counts used directly as demand |
|---|---|---|
| segment control delay | 66.8 s [62.7 +/- 2.8] | **45.7 s** (-32 %, 7.6 sd) |
| LOS letter | E | **D** |
| 95th-percentile back of queue | 126 veh [136 +/- 17] | **67 veh** (-47 %) |
| residual queue at end of peak | 85 veh [80 +/- 8] | **0 veh** |

That same reconstruction passed **GEH < 5 on 100.0 % of all 576 movement-bins**,
mean GEH 0.89. **A perfect count fit is fully compatible with a 15 % demand error, a
halved queue estimate and a wrong LOS grade** — see [[geh-statistic]] for why the
statistic is insensitive here: at bin counts of 400–500 vehicles, a 100-vehicle
error is GEH ~4.7 and still "passes".

## The correction that works: storage, not jam length

`demand_bin = served_count + (Q_end - Q_start)` is an exact input-output identity
**if Q is the number of vehicles present on the approach**. Two implementation
details decide whether it holds:

- **`jamLengthInVehicles` is the wrong quantity.** It measures the compact standing
  platoon; an oversaturated approach is a long *crawling* queue whose vehicles are
  mostly above the halting-speed threshold. Verified at the worst bin: ~258 vehicles
  were on the approach while the E2 residual jam length read ~68. Use the vehicle
  count on the detector (`LAST_STEP_VEHICLE_NUMBER`), sampled at the bin boundary —
  E2 interval output reports maxima, not boundary values.
- **The detector must span the whole approach.** A chain covering 1489 m of a
  2080 m approach missed 112 vehicles at the peak.

And one modelling rule: **once an approach is queue-corrected, its downstream
approaches must be reconciled to the propagated volume, not to their own counted
volume.** A downstream approach fed by a queue-constrained one is metered, so
rescaling the corrected stream to its count re-truncates the correction.

| variant | peak-hour demand err | delay | LOS | Q95 | residual |
|---|---|---|---|---|---|
| ground truth | — | 66.8 s | E | 126 veh | 85 veh |
| counts used directly | **-15.5 %** | 45.7 s | **D** | 67 | 0 |
| corrected with E2 jam length | -13.5 % | 56.4 s | E | 75 | 40 |
| corrected with approach storage | -7.1 % | 71.3 s | E | 127 | 77 |
| **storage + trust-propagation** | **-2.7 %** | **65.1 s** | **E** | **140** | 58 |

Delay and Q95 return inside the 4-seed noise band. **The two halves must be applied
together**: in the undersaturated arm the paired correction is harmless (delay
27.07 -> 26.83 s, inside noise) while the storage correction *without*
trust-propagation over-shoots (+2.6 sd on delay, +41 % on Q95).

## The correction that does not work: iterating on count fit

An iterative loop that inflates movement demand until the *simulated* stop-bar
counts match the observed ones, started from the truncated demand and from 1.5x it.
After 3 iterations the two branches emitted **2041 and 3347** vehicles in the
critical peak hour — a factor of **1.64**, with the truth (2152) between them — and
achieved count fits of **99.8 % and 98.3 % GEH < 5** (mean GEH 1.02 and 1.15), both
far above the conventional 85 % bar. The inflated branch **diverged** (+28 % to
+55 %) rather than converging.

The mechanism is the intersection-level null space: once every candidate demand
saturates the stop bar, the simulated count stops responding to the demand, the
objective's gradient vanishes, and the iterate wanders. Along the base branch the
implied delay went 45.7 -> 85.4 -> 66.5 -> 77.5 s (a factor of 1.9, non-monotone)
while the objective moved by 0.2 percentage points. **Report an equifinal spread,
never a single "count-calibrated" demand** — the same conclusion
[[od-matrix-estimation-and-underdetermination]] reaches for ODME.

## Mid-block imbalance must be materialised, not absorbed

TMC balancing leaves a residual between the volume propagated from the upstream
intersection and the volume counted at the downstream one. That residual is a
mid-block source or sink, and if it is absorbed by rescaling the upstream streams it
**retroactively rewrites the upstream intersection's counted demand** (verified: with
90 vehicles of non-materialisable imbalance, the recovered entry-approach volume came
out 1.03 % below its own counted volume). Where the network exposes a real access
edge, emit the residual as an explicit mid-block sink path or source stream there;
where it does not, flag it.

Detection is possible directly from the compiled network by walking between counted
approaches and recording every branch off, and every edge merging into, each link —
but **skip the first hop**, or the junction's own approach edges are mis-reported as
mid-block access at every link.

Two sobering magnitudes from the verified run: the true net mid-block flow on the one
link that had a driveway was -140.0 vehicles over 4 h and the reconciliation
recovered only -83.5 of it, while the three links with *no* mid-block access
showed apparent residuals of -5.5 to -71.4 vehicles. **At this magnitude a genuine mid-block source
or sink is not cleanly separable from count noise plus the count-period end effect.**

## The count-period offset is an end effect, not a bin shift

At 400 m spacing and 13.9 m/s the link travel time is 28.8 s = 3.2 % of a 900 s bin,
so any "shift the downstream series by the travel time" correction rounds to zero
bins. Its real effect is at the *end* of the count window — vehicles counted upstream
in the last bin are never counted downstream — worth about 0.8 % of the link total,
the same order as the genuine mid-block leakage. Verified balancing magnitudes on a
clean synthetic corridor: total per-link imbalance 0.06–3.11 %, mean per-bin
absolute imbalance 1.48–4.08 %, worst single bin 8–24 vehicles.

## Realized PHF is not the flow file's PHF

Stochastic insertion and insertion capacity distort it in both directions, so
measure it from the rerun's own detector output. Verified: a reconstruction whose
flow file implied PHF 0.879 realized 0.824; one whose flow file implied 0.983
realized 0.995.

## Instrumentation notes

- **Movement-resolved stop-bar counts come from E1 loops on junction-INTERNAL
  lanes.** An internal lane is one `(fromLane -> toEdge)` pair, so the loop at its
  head counts exactly one turning movement. Verified against per-lane stop-bar loops:
  agreement to within 0.02–0.11 %, the small excess being lane-changing vehicles that
  miss the point loop — consistent with
  [[automated-traffic-signal-performance-measures]]'s finding that stop-bar
  *presence* detectors under-count volume badly, while point loops do not.
- **E1 aggregate output carries no vehicle-type breakdown.** Add a parallel loop set
  with `vTypes="hgv"` for the heavy-vehicle column.
- **`--lateral-resolution 0` kills SUMO during loading** (SIGKILL, no error message);
  omit the option rather than setting it to zero.
- **An E2 `endPos` must clear the junction-shortened lane length** — an 80 m bay
  compiles to 68.8 m; use a negative `endPos`.
- **Sort `<flow>` elements by `begin`** or SUMO silently drops the out-of-order ones.
- Poisson demand plus small movement volumes dominates sub-10 % effects: establish
  the realized-vs-nominal gap and a multi-seed noise floor
  ([[sumo-stochastic-variability-and-replication-design]]) before attributing
  anything to method.
