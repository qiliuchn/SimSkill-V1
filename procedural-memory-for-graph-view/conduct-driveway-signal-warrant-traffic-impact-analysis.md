---
name: conduct-driveway-signal-warrant-traffic-impact-analysis
description: Use this skill when the user wants a development Traffic Impact Analysis (TIA) in SUMO - build vs no-build site trip generation from ITE-style rates with a pass-by fraction, a multi-hour diurnal demand profile, and a MUTCD signal-warrant determination (Warrant 1 eight-hour with Conditions A/B and the 80% combination, Warrant 2 four-hour curve, Warrant 3 peak-hour curve, the 70% reduced column) computed from measured detector output rather than assumed volumes - and/or wants to test whether installing the warranted signal actually improves total intersection performance against non-signal mitigations (driveway right-turn lane, right-in/right-out). Covers the demand-vs-served-volume metering trap that makes stop-bar counts understate minor-street demand exactly where the warrant is nearly met, multi-hour time-sliced flow generation with a peak-hour factor, and the E3 detEntry placement bug that silently zeroes a whole movement. Trigger on mentions of traffic impact analysis, TIA, signal warrant, MUTCD warrant, ITE trip generation, pass-by trips, driveway access, build vs no-build, or right-in/right-out.
related_skills:
  - compare-unsignalized-intersection-control-types
  - measure-saturation-flow-and-validate-webster-method
  - generate-hcm-los-report-and-validate-against-microsimulation
  - control-signals-with-actuated-tls
  - design-actuated-signal-detector-placement-and-fault-tolerance
  - design-left-turn-storage-bay-length
  - validate-congested-scenario-results-against-teleport-artifacts
  - quantify-sumo-run-to-run-variability
  - switch-signal-plans-by-time-of-day-with-waut
related_skills_for_graph_view:
  - "[[compare-unsignalized-intersection-control-types]]"
  - "[[measure-saturation-flow-and-validate-webster-method]]"
  - "[[generate-hcm-los-report-and-validate-against-microsimulation]]"
  - "[[control-signals-with-actuated-tls]]"
  - "[[design-actuated-signal-detector-placement-and-fault-tolerance]]"
  - "[[design-left-turn-storage-bay-length]]"
  - "[[validate-congested-scenario-results-against-teleport-artifacts]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[switch-signal-plans-by-time-of-day-with-waut]]"
related_pages:
  - "[[mutcd-signal-warrants-and-the-demand-vs-served-volume-trap]]"
  - "[[unsignalized-vs-signalized-intersection-control]]"
---

# Conduct a Driveway Signal-Warrant Traffic Impact Analysis

Builds the full engineering deliverable a development TIA has to produce — a diurnal
build/no-build demand set, a MUTCD volume-warrant worksheet computed from *measured*
detector output, an LOS/queue comparison of two-way stop control against a signal and
against non-signal mitigations, and a written recommendation — and, more importantly,
tests the two places where that deliverable is most likely to be wrong: the **volume basis**
the warrant is evaluated on, and the assumption that a met warrant implies improved
operations.

This is the first skill in memory to treat a **regulatory threshold test** as an object of
study rather than a given, and the first to build ITE-style **build vs. no-build site trip
generation with pass-by accounting** on top of a diurnal background profile. (Other skills
do span multiple periods — `switch-signal-plans-by-time-of-day-with-waut` and
`measure-travel-time-reliability-with-simulated-days` — but none generates an hourly demand
profile from a land-use trip-generation calculation.) It reuses
`compare-unsignalized-intersection-control-types` for the TWSC geometry and foe-matrix
verification, `measure-saturation-flow-and-validate-webster-method` for the measured `s`
and lost time that feed Webster, `generate-hcm-los-report-and-validate-against-microsimulation`
for measured control delay, and `control-signals-with-actuated-tls` for the actuated arm.

`scripts/` is the complete, runnable pipeline in dependency order:
`build_networks.py` → `gen_demand.py` → `gen_detectors.py` → `calibrate_saturation.py` →
`make_signal.py` → `run_scenarios.py` → `analyze.py` / `analyze_sweep.py` /
`curve_sensitivity.py` / `verify_extras.py` / `verify_lane_balance.py` →
`make_plots.py` → `make_report.py`.
Edit the paths in `common.py` and the demand tables in `gen_demand.py`; everything else is
scenario-independent. `mutcd_warrants.py` is a standalone warrant engine usable on its own.

## The central finding: a saturated stop bar measures capacity, not demand

**MUTCD warrants are defined on demand volumes, but a saturated minor approach meters its
own throughput — so a stop-bar count understates the minor-street volume most severely
exactly when the warrant is closest to being met.** Verified across a 10-point site-intensity
sweep (93 hour-observations), the ratio of stop-bar count to realised generated demand on
the driveway approach was:

| nominal v/c | n | mean stop-bar / generated |
|---|---:|---:|
| below 0.95 | 60 | 1.00 |
| 0.95 – 1.05 | 5 | 0.904 |
| 1.05 – 1.25 | 5 | 0.835 |
| 1.25 – 1.60 | 8 | 0.564 |
| 1.60 – 2.20 | 7 | 0.301 |
| 2.20 – 3.50 | 5 | 0.129 |
| above 3.50 | 3 | 0.085 |

The transition is sharp and sits at v/c ≈ 1. Below it the two bases agree to within
Poisson sampling noise; above it the detector diverges fast.

**The measured minor-approach volume is non-monotone in development size.** In the verified
study the PM-peak stop bar counted 95 veh/h at 0.5× site intensity and only 39 veh/h at
3.0× — so the *most* congested case produced the *weakest* apparent warrant case. On the
demand basis, 3.0× intensity gave Warrant 1 Condition A in 10 hours and Condition B in 11;
on the detector basis the same run gave 1 and 4 hours, i.e. **Warrant 1 NOT MET at the worst
intensity tested.** The two bases first disagreed systematically at 0.5× intensity and the
gap widened monotonically thereafter.

**Warrant 3 Condition A's delay test fails the same way, and worse.** It requires ≥ 4
vehicle-hours of stopped-time delay on the minor approach. In one verified hour of the
highest-intensity run that quantity measured **0.0 vehicle-hours**, because the vehicles
were not on the approach at all — the insertion backlog attributable to that hour alone was
909 vehicle-hours (not even the run's largest single-hour backlog — an earlier hour reached
1158). A delay-based test evaluated on the approach can read zero at the exact moment the
approach is most broken.

**Practical rule: evaluate warrants on demand, never on a raw saturated stop-bar count.**
If field counts are the only data, pair them with a queue survey. In SUMO the three bases
are all recoverable from raw output and should always be reported side by side:
nominal (the flow file), realised-generated (`tripinfo` `depart − departDelay`),
inserted (`tripinfo` `depart`), and served (E1 `nVehContrib`).

## Measure the insertion backlog — it is the queue inside the site

Run with **no `--max-depart-delay`** so blocked vehicles accumulate rather than being
silently dropped, and compute the peak backlog as vehicles whose intended departure has
passed but which are not yet inserted. Verified in the high-intensity case: Q95 on the
driveway saturated at its full 250 m storage while a further **1 534 vehicles**
(≈ 11.5 km equivalent) stood behind the network boundary — 5 283 vehicle-hours of delay
that appears in *no* detector and in no `timeLoss` figure. Report
`veh-h timeLoss` and `veh-h insertion backlog` separately and sum them; a comparison
that uses `timeLoss` alone will understate an oversaturated arm by an order of magnitude
(verified: 466 vs 5 749 vehicle-hours).

## Warrant met ≠ signal helps — build the 2×2 and test it

Run the signalized arm for the **no-build** scenario too, not just the build scenarios;
otherwise the "does the warrant give good advice?" question cannot be answered. Verified
outcome at the 100% column (12-hour total delay, mean of 3 seeds):

| scenario | any warrant met (demand, 100%) | TWSC veh-h | actuated signal veh-h | agree? |
|---|---|---:|---:|---|
| no-build | False | 23.7 | 52.1 (+120%) | YES |
| build | True | 465.4 | 69.9 (−85%) | YES |
| high-intensity build | True | 5 749.1 | 118.1 (−98%) | YES |

They agree — but **not automatically**, and the reason is worth stating: the minor
approach's gap-acceptance capacity collapses at the same arterial volumes that drive the
warrant curve's major-street axis, so both tests are downstream of the same physical
quantity. They come apart when the wrong volume basis is used, or when the **70% column** is
applied without its qualifying condition.

**The 70% column is where the warrant gives genuinely bad advice.** Verified: in the
no-build scenario nothing is warranted at the 100% column, but at 70% Warrant 1 Condition B
was satisfied in all 12 study hours and Warrants 2 and 3 as well — while installing the
signal raised total delay by 120% and eastbound through travel time by 42%. The 70% column
requires major-street 85th-percentile speed > 70 km/h **or** an isolated community below
10 000 population; at a 55 km/h posted arterial the speed criterion does not apply. Always
state which criterion is being invoked.

**Signalizing does penalise the arterial, and that must be reported separately.** Verified
PM-peak through travel time over a fixed 350 m segment, high-intensity case: 26.4 s (TWSC) →
52.8 s (fixed) / 46.1 s (actuated). The intersection-wide result is still strongly positive
only because the driveway's per-vehicle delay is two orders of magnitude larger.

## Report LOS with the right thresholds and the right scope

- **HCM LOS thresholds differ by control type** — unsignalized A≤10 / B≤15 / C≤25 / D≤35 /
  E≤50 / F>50 s/veh; signalized A≤10 / B≤20 / C≤35 / D≤55 / E≤80 / F>80. Applying the
  signalized table to a TWSC approach flatters it by a whole grade or more. Carry an explicit
  `LOS_basis` column.
- **HCM does not define an intersection-wide LOS for two-way stop control**, and the verified
  run shows exactly why: no-build TWSC came out at 8.8 s/veh "LOS A" intersection-wide while
  its minor-street approach was at 140.8 s/veh, LOS F. If an intersection-wide TWSC number is
  shown at all, show it next to the worst approach and label it as non-standard.

## Non-signal mitigations a real TIA must consider

Verified, 12-hour total delay against the TWSC baseline:

| mitigation | build | high-intensity build |
|---|---:|---:|
| exclusive right-turn lane on the driveway | −67% | −73% |
| right-in / right-out | −85% | −90% |
| Webster fixed-time signal | −81% | −97% |
| actuated signal | −85% | −98% |

The right-turn lane works by unblocking right-turners the shared lane's left-turners were
holding up; it does nothing for the left-turn movement, whose queue simply relocates into
the new left-only lane (verified Q95 249 m of a 250 m approach). RIRO essentially matches
the actuated signal at build intensity but leaves ~4.7× its delay at high intensity.

**Model RIRO honestly.** Banning the movements by connection alone and leaving the demand
un-rerouted would silently delete trips. Re-route the banned movements through an explicit
U-turn at a downstream median opening (add a `<connection>` from the outbound edge back to
the inbound edge at a fringe node) so the out-of-direction travel is genuinely simulated.
Verified consequence: PM-peak volume across the measured cross-sections rose from 1 808 to
2 742 veh/h because the site's traffic crosses the intersection twice — a cost that is
invisible in `timeLoss` (extra free-flow distance loses no time) and only appears in total
vehicle-hours of *travel*. Report both.

## Building the multi-hour demand

Nothing in memory previously built a diurnal profile. The pattern (`gen_demand.py`):

- One `<flow>` per movement per **15-minute slice** per clock hour, so each hour's volume is
  independently controlled. Apply a documented **peak-hour factor** by giving the peak
  quarter a share of `1/(4·PHF)` and splitting the rest evenly (PHF 0.92 peak / 0.95 off-peak
  used in the verified study).
- Use `period="exp(<veh/s>)"` for Poisson arrivals, not `vehsPerHour` (deterministic).
- ITE-style site trips: state land use, size, daily and AM/PM peak-hour rates, an hourly
  distribution calibrated so the peak hours equal the ITE peak-hour rates, an in/out split
  that **differs** between AM and PM, a directional distribution, and a pass-by fraction.
- **Pass-by bookkeeping**: a pass-by *vehicle* generates two driveway trip ends (one in, one
  out), so `P_vehicles = trip_ends × passby_fraction / 2`. Subtract `P` from the background
  arterial *through* volume in the corresponding direction — pass-by traffic was already on
  the road. Only `trip_ends − 2P` are NEW trips. Verified the accounting closes: total
  driveway volume = NEW in + NEW out + 2P exactly.
- `t = 0` should map to the start of the study hours (07:00) so E1 `period="3600"` intervals
  land on exact clock hours with no post-processing.
- Simulate well past the demand period (verified: demand to 43 200 s, `--end 54000`) so every
  run drains to `running = 0` and residual-queue delay is not truncated out of `tripinfo`.

## Gotchas

- **An E3 `<detEntry pos="0">` never registers, and neither does one at `pos ≤ vehicle
  length`.** A vehicle must physically *cross* the position, and with the default
  `departPos="base"` its front bumper starts at `length` metres. Verified: driveway and
  minor-street movements produced `vehicleSum="0"` in every interval of every run — silently,
  with no warning — until the entry cross-section was moved to 15 m. Symptom is a whole
  movement missing from the results, not an error. Always check `vehicleSum > 0` per movement
  before analysing E3 output.
- **`--time-to-teleport` needs its own log**: with `--no-warnings` on (required here, because
  a shared-entry E3 emits one "arrived inside" warning per vehicle per non-matching movement
  and produced a 2.5 MB log per run), teleport and collision counts must come from
  `statistics.xml`'s `<teleports total="…">` / `<safety collisions="…">`, which are
  authoritative cumulative counters.
- **netconvert always writes its own `<tlLogic programID="0">`**, so loading a hand-written
  program with `programID="0"` from an additional file is a hard error
  ("Another logic with id 'C' and programID '0' exists"). Stripping the `tlLogic` out of the
  compiled net does not work either — the junction then has no TLS at all ("The tls 'C' is
  not known"). The working pattern is a distinct `programID` plus a `<WAUT refTime="0"
  startProg="…"/>` + `<wautJunction procedure="Immediate"/>` to activate it at t = 0. Verify
  from `tls_switch.xml` that the observed `programID` is yours.
- **SUMO's keep-right rule badly unbalances a multi-lane approach at moderate demand.**
  Verified by running the identical scenario with and without `lcKeepRight="0"`
  (`scripts/verify_lane_balance.py`, `tables/lane_balance_keepright.csv`): in the 07:00 hour
  an eastbound approach carrying ~508 veh/h split **423 / 84** under SUMO's defaults (83.4% in
  one lane) versus **246 / 262** (51.6%) with keep-right disabled. Across 24 approach-hours
  the mean max-lane share fell from **83.6%** (range 73.1–98.9%) to **55.9%**. Set
  `lcKeepRight="0"` for a US-style arterial, or per-lane v/c, queue and capacity figures are
  meaningless. **But do not attribute every imbalance to the lane-change model** — with
  keep-right off the same approach still reached 90.7% at 17:00 and 99.5% at 18:00, because a
  spilled-back left-turn bay physically blocks the bay-feeding lane. Diagnose from the counts,
  not from the setting.
- **Q95 from a lane-area detector saturates at the storage length** and tells you nothing
  about how much worse it is beyond that. A Q95 equal to the bay or approach length is a
  *censored* observation; pair it with the insertion backlog.
- **Report the site-intensity sweep, not just three scenarios.** The build/no-build/high
  triple alone would have shown the two volume bases agreeing on every headline conclusion;
  only the 10-point sweep exposed the flip at 3.0× and the non-monotonicity.
- **Digitised MUTCD curves need a stated sensitivity test.** Warrants 2 and 3 are plotted
  figures, not tables. `curve_sensitivity.py` re-evaluates every conclusion with the curve
  scaled 0.90–1.10. Verified: of the six scenario x volume-basis combinations tested, exactly
  **one** (no-build on the demand basis) was unstable — its Warrant 3 verdict, and hence "any
  warrant met", flips from NOT MET at curve scale 1.00/1.05/1.10 to MET at 0.95/0.90, because
  its 17:00 hour sits at a margin of 0.981, i.e. 1.9% below the digitised curve. Every other
  conclusion, and every Warrant 1 conclusion (numeric table, not a curve), is stable across
  the full band. Saying that is far more useful than asserting the digitisation is fine.

## Related

- `compare-unsignalized-intersection-control-types` — the TWSC geometry, the
  edge-priority-baked-into-the-shared-edge-file technique, and the compiled-net foe/response
  verification this skill reuses (decode with the rightmost bitstring character = link index 0).
- `measure-saturation-flow-and-validate-webster-method` — the measured `s` / lost time this
  skill feeds into Webster. Verified here: major through 2 101 veh/h/ln (R² = 0.9999),
  exclusive left bay 1 439, driveway 1 540, minor street 1 537, with the exclusive-left bay
  by far the most fit-sensitive lane group (1 439 at `--step-length` 0.1 vs 1 600 at 0.5,
  ±11%, because it discharges only 5.6–15 veh/cycle).
- `generate-hcm-los-report-and-validate-against-microsimulation` — measured-not-geometric
  free-flow datum and paired-detector control delay; this skill uses E3 `meanTravelTime`
  minus a measured datum instead of instant loops, which is far more compact over 12 hours.
- `control-signals-with-actuated-tls` / `design-actuated-signal-detector-placement-and-fault-tolerance`
  — the actuated arm and the custom-detector binding verification protocol (verified: mean
  cycle 58.7 s intended vs 56.9 s with detectors deliberately misplaced, so the
  `<param key="<laneID>">` binding genuinely took effect).
- `design-left-turn-storage-bay-length` — the bay-length compile calibration and lane-area
  queue instrumentation.
- `validate-congested-scenario-results-against-teleport-artifacts` — teleport discipline
  (verified max 0.08% of inserted vehicles; a `--time-to-teleport -1` re-test of the worst
  case was byte-identical with no running-count freeze).
- `quantify-sumo-run-to-run-variability` — 3-seed Common Random Numbers design and the
  "capacity is the peak of the served-flow-vs-demand curve" definition used for the
  empirical hourly driveway capacity.
- `switch-signal-plans-by-time-of-day-with-waut` — the WAUT mechanism used here purely to
  activate a custom program, not to switch plans.
- [[mutcd-signal-warrants-and-the-demand-vs-served-volume-trap]] — the underlying theory,
  the warrant threshold tables, and the verified findings.
- [[unsignalized-vs-signalized-intersection-control]] — the delay-crossover framing this
  skill turns into a regulatory test.
