---
name: reconstruct-simulation-demand-from-field-turning-movement-counts
description: Use this skill when the user wants to turn field turning-movement counts (a TMC, a video/ATSPM count, an ATR/permanent-count profile) into SUMO demand for a signalized corridor, or wants to know whether counts collected under congestion can be trusted as demand input. Covers the full engineering workflow - design-hour selection (K factor, D directional split, observed-peak vs K30xAADT), peak-hour factor by sliding 4-bin search, TMC balancing between adjacent intersections with an explicit mid-block source/sink, heavy-vehicle PCE and growth factors, and emission of 15-minute flow elements plus routes - and the failure mode that matters - a saturated stop bar counts capacity, not demand, so the rebuilt model passes GEH while under-predicting delay and queue. Includes a measured PHF>=0.95 truncation threshold, a storage-based (not jam-length-based) residual-queue correction, and a demonstration that iterating on count fit lands on an equifinal family rather than the truth. Trigger on turning movement count, TMC, count-to-demand, design hour, K factor, peak hour factor, PHF, count balancing, "can I use my traffic counts as model input", or count-based demand calibration at intersections.
related_skills:
  - estimate-od-matrix-with-odme
  - conduct-driveway-signal-warrant-traffic-impact-analysis
  - generate-hcm-los-report-and-validate-against-microsimulation
  - build-atspm-pipeline-and-retime-arterial
  - design-arterial-signal-progression-and-verify-bandwidth
  - quantify-sumo-run-to-run-variability
  - validate-congested-scenario-results-against-teleport-artifacts
  - calibrate-demand-with-routesampler
  - reconstruct-demand-with-dfrouter
related_skills_for_graph_view:
  - "[[estimate-od-matrix-with-odme]]"
  - "[[conduct-driveway-signal-warrant-traffic-impact-analysis]]"
  - "[[generate-hcm-los-report-and-validate-against-microsimulation]]"
  - "[[build-atspm-pipeline-and-retime-arterial]]"
  - "[[design-arterial-signal-progression-and-verify-bandwidth]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[validate-congested-scenario-results-against-teleport-artifacts]]"
  - "[[calibrate-demand-with-routesampler]]"
  - "[[reconstruct-demand-with-dfrouter]]"
related_pages:
  - "[[field-counts-to-simulation-demand-and-the-saturated-count-truncation-trap]]"
  - "[[geh-statistic]]"
  - "[[hcm-control-delay-vs-sumo-delay-metrics]]"
  - "[[mutcd-signal-warrants-and-the-demand-vs-served-volume-trap]]"
  - "[[od-matrix-estimation-and-underdetermination]]"
---

# Reconstruct Simulation Demand from Field Turning-Movement Counts

Builds the count-to-demand workflow a traffic engineer actually runs, then measures
how far it is from the truth when the counts were taken on a saturated approach.
This is the *intersection-level* form of the identifiability problem that
`estimate-od-matrix-with-odme` studies at the zone level and
[[mutcd-signal-warrants-and-the-demand-vs-served-volume-trap]] studies at a
stop-controlled minor approach: **a stop-bar count is a served volume, and once the
approach is over capacity a served volume is a capacity measurement.**

`scripts/counts_to_demand.py` is the reusable deliverable. `scripts/test_c2d.py`
unit-tests each step in isolation (17 assertions).

## Pipeline

```bash
S=.claude/skills/procedural-memory/reconstruct-simulation-demand-from-field-turning-movement-counts/scripts
python $S/build_network.py       # 3-signal arterial, plain XML + netconvert
python $S/demand.py              # ground truth as PATH flows (see below)
python $S/build_detectors.py     # movement E1 + lane E1 + E2 storage + E3 delay + ATR
python $S/make_config.py         # the corridor config the tool consumes
python $S/run_sim.py --route gt_over.rou.xml --name gt_over
python $S/export_tmc.py --arm over            # the field TMC CSV + ATR profile
python $S/counts_to_demand.py --tmc tmc_counts_over.csv --atr atr_profile_over.csv \
       --net corridor.net.xml --config corridor_config.json \
       --out rec_over.rou.xml --report rec_over_report.json \
       [--design-hour k30 --k30 0.10 --aadt 30000] [--growth 1.02] [--pce 2.0] \
       [--balance-weight 0.5] [--queue-correction queue_bins.csv \
        --queue-metric storage --trust-propagation]
python $S/analyze_roundtrip.py   # the three-level comparison
python $S/iterate.py --arm over --tag base --start 1.0   # the equifinality test
```

## Define ground truth as PATH flows, not free-floating movement flows

Specify the synthetic demand as fringe-to-fringe path flows and derive the true
turning-movement volume at every intersection as a closed-form sum over the paths
that traverse it (`demand.py:true_movement_volumes`). Free-floating per-movement
flows would make vehicles appear and vanish mid-corridor, and the demand-recovery
level of the test would then have no well-defined referent. Use
`period="exp(rate)"` (Poisson), not `vehsPerHour`, and report BOTH the nominal and
the *realized* generated volume (`tripinfo` `depart - departDelay`) — on a movement
of ~90 vehicles over 4 h, Poisson noise alone produced a 12 % gap between the two,
which is larger than several of the effects being measured.

## Instrument movements, not lanes: put E1 loops on junction-INTERNAL lanes

A junction-internal lane is by construction one `(fromLane -> toEdge)` pair, so an
`<inductionLoop>` at its head is exactly one turning movement's stop-bar departure
count — which is what a TMC/video/ATSPM count records. Read the internal lane ids
from the compiled net's `<connection via=...>` attributes. Verified against
per-lane stop-bar loops on the same approaches: the two agree to within
0.02–0.11 % (6 vehicles in 6257 on the busiest approach), the small excess on the
movement loops being vehicles that change lanes across the point loop and so miss
it — the same effect `build-atspm-pipeline-and-retime-arterial` reports.

Add a second, identical loop set with `vTypes="hgv"` for the heavy-vehicle column;
E1 aggregate output carries no type breakdown, and `instantInductionLoop` output
(which does carry `type`) costs ~8 MB per approach per 4 h.

## The tool's five steps, and what each one is actually worth

**(a) Design hour from an ATR profile.** `design_hour_from_profile` computes
`K = DHV / daily` (daily via a stated count-expansion factor) and the directional
split `D`, and supports both "use the observed peak hour" and "apply K30 x AADT".
**The ATR path is the robust one**: a mid-block station upstream of the queue
located the true peak-hour window correctly (bin 7) in *both* the undersaturated
and the oversaturated arm, while the stop-bar PHF search put it one bin late (bin 8)
in the congested arm. Verified D = 0.607 / 0.614 against a true 0.613, and
DHV within +0.1 % / -1.1 % of truth, in both arms. **Verify empirically that the
ATR station is beyond the back of queue** — compare its per-bin count against the
realized generated demand rather than arguing from geometry (verified total ratio
0.999, per-bin 0.986–1.034 in the oversaturated arm).

**(b) PHF by sliding 4-bin search.** `PHF = V / (4*V15max)` with the peak hour found
by sliding search, never assumed clock-aligned. With a peak hour deliberately
straddling the clock hours, the best clock-aligned window under-stated the
peak-hour volume by 2.3 %.

**(c) TMC balancing.** For each directional link, `B = w*U + (1-w)*A` (w = 0.5 =
equal confidence in the upstream departures U and downstream arrivals A), then
rescale the downstream approach's movements to sum to B, preserving its turn
ratios. Report the *pre-balance* imbalance per link per bin. Verified magnitudes on
a clean synthetic corridor: total imbalance 0.06–3.11 % per link, mean
per-bin absolute imbalance 1.48–4.08 %, worst single bin 8–24 vehicles.

**A count-period offset does not show up as a bin shift and must not be modelled as
one.** At 400 m spacing and 13.9 m/s the link travel time is 28.8 s = 3.2 % of a
900 s bin, so `--offset-correct` rounds to a zero-bin shift. Its real effect is an
*end-of-window* effect — vehicles counted upstream in the last bin are never counted
downstream — worth ~0.8 % of the link total, which is the same order as the genuine
mid-block leakage and is not separable from it at this bin size.

**Materialise the mid-block imbalance on a real access edge, or it silently rewrites
the upstream counts.** `corridor_topology` walks the compiled net between counted
approaches and reports every branch off, and every edge merging into, each link.
Where such an access edge exists, the reconciliation residual is emitted as an
explicit mid-block sink path (destination = the access edge) or source stream
(origin = the access edge); where it does not, the tool falls back to rescaling the
upstream streams and **flags `materialised: false`**. That fallback is not free:
with 90 vehicles of non-materialisable imbalance, the recovered J1 EB approach
volume came out 1.03 % below the counted volume, i.e. the downstream reconciliation
retroactively shrank an upstream intersection's counted demand. Verified the walk
finds the one real driveway and nothing else (`{"J2|EB": {"out": ["dw_out"],
"into": ["dw_in"]}}`) — but note it recovered only -83.5 of a true -140.0 vehicle
net mid-block flow: at this magnitude the leakage is not cleanly separable from
count noise.

*Detection gotcha:* when walking outward from a junction, skip the first hop before
collecting merging edges — the edges entering the first downstream edge are the
junction's own approaches, and counting them produces spurious "mid-block access"
at every link.

**(d) Heavy vehicles and growth.** `f_HV = 1/(1 + P_HV*(E_T-1))`, PCE volume
`v/f_HV`, growth applied multiplicatively; the emitted demand preserves the
observed heavy share by splitting each flow into `car`/`hgv` sub-flows.

**(e) Path expansion + emission.** Propagate each counted boundary approach through
the corridor by the observed turn ratios in topological order, reconciling at each
downstream approach, then emit one `<flow>` per path per 15-min bin with
`period="exp(...)"` and an explicit `<route>`. **Sort flows by `begin`** — SUMO
silently discards out-of-order flow departures.

## The failure, measured

Two arms identical except the arterial scale factor. Measured saturation flow at
the critical stop bar 1762 and 1838 veh/h/ln, maximum observed 15-minute discharge
1700 veh/h, giving **measured v/c 0.74 and 1.14**. Both arms ran with
`--time-to-teleport -1` to 0 teleports, 0 collisions, every vehicle arrived, no
running-count freeze, and — importantly — **zero insertion backlog at every 15-min
boundary**, so none of the demand was hidden outside the network.

Stop-bar count divided by the *realized generated* demand (`tripinfo`
`depart - departDelay`, so Poisson noise is divided out) on the critical through
movement:

| | UNDER (v/c 0.74) | OVER (v/c 1.14) |
|---|---|---|
| 4-hour total | 0.988 | **0.989** |
| true peak hour (4 bins) | 0.991 | **0.866** |
| worst single 15-min bin | 0.884 | **0.803** |
| three bins after the peak | 1.095 / 0.965 / 1.011 | **1.235 / 1.459 / 1.234** |

**The volume is not lost, the PEAK is.** Over four hours the saturated stop bar
recovers 98.9 % of the demand — a total-volume check passes outright — while inside
the peak hour it recovers 86.6 % and in the worst 15 minutes 80.3 %; the missing
vehicles reappear as counts 23–46 % *above* demand in the three bins after the peak.
That is the practically dangerous shape of the error: the aggregate check passes and
every peak-derived design quantity is wrong.

Consequences, critical approach, true peak hour (4-seed noise floor in brackets):

| quantity | ground truth | counts used directly |
|---|---|---|
| segment control delay | 66.8 s [62.7 +/- 2.8] | **45.7 s** (-32 %, 7.6 sd) |
| LOS letter | E | **D** |
| 95th-pct back of queue | 126 veh [136 +/- 17] | **67 veh** (-47 %) |
| residual queue at end of peak | 85 veh [80 +/- 8] | **0 veh** |
| measured PHF (true 0.870) | 0.983 | — |

...while the reconstruction passed **GEH < 5 on 100.0 % of all 576 movement-bins**
(mean GEH 0.89). **Count fit certifies nothing.** Keep the three levels — count
fit, demand recovery, performance recovery — explicitly separate, exactly as
`estimate-od-matrix-with-odme` insists at the zone level.

## Measure the REALIZED PHF from detector output, not from the flow file

Stochastic insertion and insertion capacity distort it in both directions.
Verified: an undersaturated reconstruction whose flow file implied PHF 0.879
realized 0.824 in the rerun's own stop-bar counts, and an oversaturated one whose
flow file implied 0.983 realized 0.995.

## Correction 1: residual-queue accounting — but use STORAGE, not jam length

`demand_bin = served_count + (Q_end - Q_start)`. Two implementation details decide
whether it works at all.

**Q must be the number of vehicles PRESENT on the approach, not the E2 jam length.**
`jamLengthInVehicles` measures the compact standing platoon; an oversaturated
approach is a long *crawling* queue whose vehicles are mostly above the halting
threshold. Verified at the worst bin: ~258 vehicles were on the approach while the
E2 residual jam length read ~68. Sample `LAST_STEP_VEHICLE_NUMBER` on the E2 chain
via TraCI (E2 interval output reports maxima, not the value at the bin boundary).

**The E2 chain must span the WHOLE approach.** A chain covering 1489 m of a 2080 m
approach missed 112 vehicles at the peak — the correction is an input-output
identity and any uncovered upstream metres are silently dropped.

**Once an approach is queue-corrected, stop reconciling its downstream approaches to
their own counts** (`--trust-propagation`). A downstream approach fed by a
queue-constrained one is *metered*: its counted volume is a capacity, and rescaling
the corrected upstream stream to it re-truncates the correction.

Peak-hour demand error on the saturated through movement, and the resulting
performance:

| variant | demand err | delay | LOS | Q95 | residual |
|---|---|---|---|---|---|
| ground truth | — | 66.8 s | E | 126 veh | 85 veh |
| counts used directly | **-15.5 %** | 45.7 s | **D** | 67 | 0 |
| corrected, E2 jam length | -13.5 % | 56.4 s | E | 75 | 40 |
| corrected, approach storage | -7.1 % | 71.3 s | E | 127 | 77 |
| **storage + trust-propagation** | **-2.7 %** | **65.1 s** | **E** | **140** | 58 |

Delay and Q95 return inside the 4-seed noise band. In the undersaturated arm the
paired correction is harmless (delay 27.07 -> 26.83 s, inside noise) but the
storage correction *without* trust-propagation over-shoots (+2.6 sd on delay,
+41 % on Q95) — **apply the pair together or neither.**

## Correction 2: iterating on count fit does not recover demand

An iterative loop that scales movement demand until simulated stop-bar counts match
observed ones, run from two starting points (the truncated demand, and 1.5x it).
After 3 iterations the two branches emitted **2041 and 3347** vehicles in the
critical peak hour — a factor of **1.64** — with the truth (2152) between them, and
count fits of **99.8 % and 98.3 % GEH < 5** (mean GEH 1.02 and 1.15), both far above
the conventional 85 % bar. The inflated branch **diverged** (+28 % -> +55 %) instead
of converging: once every candidate saturates the stop bar, the objective's gradient
vanishes and the iterate wanders. Its implied delay across the base branch's four
iterations went 45.7 -> 85.4 -> 66.5 -> 77.5 s, i.e. non-monotone and swinging by a
factor of ~1.9 while the objective moved by 0.2 percentage points. **Report the
equifinal spread, never a single "calibrated" demand.**

## The decision rule, with the measured threshold

Over 9 approach-arm cases carrying more than 1000 veh in the peak hour, the
uncorrected peak-hour demand error separates cleanly on the **stop-bar-measured
PHF**:

| measured PHF | n | uncorrected peak-hour demand error |
|---|---|---|
| 0.879 – 0.940 | 6 | -2.4 % to -1.4 % |
| 0.976 – 0.983 | 3 | -14.7 % |

**A stop-bar approach PHF >= 0.95 is a truncation signature, not a flat arrival
profile.** Below it, use the counts directly. At or above it, the storage-based
queue correction plus trust-propagation is mandatory.

Two qualifiers that matter:

- **Apply the test only above ~1000 veh/h.** On the 15 approaches below that, the
  uncorrected error averaged 4.5 % and reached 11.5 % from Poisson count noise
  alone, with no congestion involved.
- **The queue diagnostic is necessary but not sufficient, and PHF beats it.** In the
  oversaturated arm only ONE approach stored a queue (69.5 veh; every other
  approach 0.0–0.2), yet the two downstream arterial approaches were truncated by
  14.7 % each with **zero queue of their own** — they are metered by the upstream
  signal. PHF flagged all three (0.976–0.983); the queue flagged one.

## Gotchas

- **`--lateral-resolution 0` kills SUMO during load** (SIGKILL, no error message);
  omit the option instead of setting it to zero.
- **An E2 `endPos` must clear the junction-shortened lane length** — an 80 m bay
  compiles to 68.8 m and `endPos="80"` is a hard error. Use `endPos="-0.5"`.
- **E2 `jamLengthInVehicles` is not approach storage** (see above).
- **A partial E2 chain silently truncates a storage-based correction.**
- **E1 aggregate output has no vehicle-type breakdown** — add a parallel loop set
  with `vTypes="hgv"`.
- **`<entryExitDetector openEntry="false">` discards vehicles that leave without
  entering** and warns for each one; that is the desired behaviour when the exit
  cross-sections are shared with cross-street traffic, but the warning log reached
  11 MB per run.
- **Sort `<flow>` elements by `begin`** or SUMO drops the out-of-order ones.
- **Skip the first hop when auto-detecting mid-block access** or every link gets a
  spurious one.
- **Poisson demand plus small movement volumes dominates everything.** Establish the
  realized-vs-nominal gap and a multi-seed noise floor before attributing any
  sub-10 % effect to a method.

## Related

- `estimate-od-matrix-with-odme` — the same count-fit-vs-recovery separation and
  equifinality discipline at the zone level; this skill is its intersection-level
  counterpart and reuses its "count fit is what you optimised, so it is not
  evidence" rule verbatim.
- `conduct-driveway-signal-warrant-traffic-impact-analysis` — the incidental
  PHF-slicing pattern (`1/(4*PHF)` on the peak quarter) this skill turns into a
  measured, searched and validated quantity, and the demand-vs-served-volume trap
  in its stop-controlled form.
- `generate-hcm-los-report-and-validate-against-microsimulation` — the control-delay
  measurement scope discipline and the residual-queue truncation bias; this skill's
  delay figures are segment-scoped E3 time loss over a stated segment length.
- `build-atspm-pipeline-and-retime-arterial` — stop-bar detector semantics and the
  "stop-bar presence detectors are not volume counters" finding; this skill's
  internal-lane movement loops are the volume-faithful alternative.
- `design-arterial-signal-progression-and-verify-bandwidth` — the coordinated
  arterial test bed and the offset conventions.
- `quantify-sumo-run-to-run-variability` — the multi-seed noise floor every
  GT-vs-rerun difference here is read against.
- `validate-congested-scenario-results-against-teleport-artifacts` — the
  `--time-to-teleport -1` + running-count-freeze + insertion-backlog checks applied
  to both arms.
- `calibrate-demand-with-routesampler`, `reconstruct-demand-with-dfrouter` — the
  other count-based demand builders; neither addresses the saturated-count
  truncation this skill measures.
- [[field-counts-to-simulation-demand-and-the-saturated-count-truncation-trap]] —
  the workflow definitions, the verified numbers and the decision rule.
- [[geh-statistic]], [[hcm-control-delay-vs-sumo-delay-metrics]],
  [[mutcd-signal-warrants-and-the-demand-vs-served-volume-trap]],
  [[od-matrix-estimation-and-underdetermination]].
