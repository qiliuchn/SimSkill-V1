---
summary: SUMO's documented junction-model yielding parameter (jmIgnoreFoeProb) has zero effect unless a second undocumented-in-practice parameter (jmIgnoreFoeSpeed) is also set, and even then only spans ~2%-77% realised yielding — never the field-documented 10-95%+ range crossing treatments require — so a working TraCI yield-rate controller was built and verified instead; the resulting six-treatment comparison (uncontrolled/RRFB/PHB/full-signal/refuge/no-crossing) found pedestrian delay is driven by realised yielding rate rather than device identity, a full pedestrian signal's vehicle cost is flat (not linear) in pedestrian volume while a PHB's is sublinear, naive TTC mis-ranks the full signal as most dangerous when PET ranks it safest, and the MUTCD Section 4F PHB warrant is systematically conservative (over-warrants in 12/32 tested cells, under-warrants in zero) relative to simulated pedestrian-delay benefit.
keywords:
  - midblock-crossing
  - motorist-yielding
  - rrfb
  - pedestrian-hybrid-beacon
  - phb
  - mutcd-warrant
  - gap-acceptance
  - refuge-island
  - junctionmodel-parameters
created: 2026-08-05T15:00:00
last_updated: 2026-08-05T15:00:00
sources:
  - "[[episodic-memory/2026-08-05_15-00-00/outputs/results/probe_channels.json]]"
  - "[[episodic-memory/2026-08-05_15-00-00/outputs/results/yield_calibration_summary.csv]]"
  - "[[episodic-memory/2026-08-05_15-00-00/outputs/results/phb_state_char_verification.json]]"
  - "[[episodic-memory/2026-08-05_15-00-00/outputs/results/controls_rrfb_vs_phb_equivalence.csv]]"
  - "[[episodic-memory/2026-08-05_15-00-00/outputs/results/H2_volume_threshold.csv]]"
  - "[[episodic-memory/2026-08-05_15-00-00/outputs/results/adams_vs_simulation.csv]]"
  - "[[episodic-memory/2026-08-05_15-00-00/outputs/results/controls_staging_matched_yield.csv]]"
  - "[[episodic-memory/2026-08-05_15-00-00/outputs/results/H3_pedvolume_scaling.csv]]"
  - "[[episodic-memory/2026-08-05_15-00-00/outputs/results/H5_within_cell.csv]]"
  - "[[episodic-memory/2026-08-05_15-00-00/outputs/results/safety_encounter_level.csv]]"
  - "[[episodic-memory/2026-08-05_15-00-00/outputs/results/warrant_boundary_comparison.csv]]"
  - "[[episodic-memory/2026-08-05_15-00-00/outputs/results/decision_rule.csv]]"
related_pages:
  - "[[pedestrian-crossings-and-signal-phasing]]"
  - "[[mutcd-signal-warrants-and-the-demand-vs-served-volume-trap]]"
  - "[[surrogate-safety-measures]]"
  - "[[car-following-parameter-calibration-and-identifiability]]"
  - "[[sumo-stochastic-variability-and-replication-design]]"
  - "[[right-turn-on-red-and-leading-pedestrian-interval]]"
  - "[[pedestrian-flow-theory-and-striping-model-artifacts]]"
related_skills:
  - calibrate-motorist-yielding-and-select-midblock-crossing-treatment
  - build-pedestrian-crossings-and-phasing
  - conduct-driveway-signal-warrant-traffic-impact-analysis
  - analyze-intersection-safety-with-ssm
  - calibrate-car-following-parameters-against-field-targets
  - quantify-sumo-run-to-run-variability
related_skills_for_graph_view:
  - "[[calibrate-motorist-yielding-and-select-midblock-crossing-treatment]]"
  - "[[build-pedestrian-crossings-and-phasing]]"
  - "[[conduct-driveway-signal-warrant-traffic-impact-analysis]]"
  - "[[analyze-intersection-safety-with-ssm]]"
  - "[[calibrate-car-following-parameters-against-field-targets]]"
  - "[[quantify-sumo-run-to-run-variability]]"
---

# Motorist Yielding Calibration and Midblock Crossing Treatment Selection

Every pedestrian-crossing finding already in memory
([[pedestrian-crossings-and-signal-phasing]]) inherits SUMO's default
assumption that motorists always yield at a crossing. This page treats
yielding as a variable to be measured and calibrated, and evaluates six
midblock crossing treatments — no crossing, uncontrolled marked crosswalk,
rectangular rapid-flashing beacon (RRFB), pedestrian hybrid beacon (PHB),
full pedestrian signal, and a refuge island (two-stage crossing) — against
each other and against MUTCD Section 4F's warrant curve.

## SUMO's documented yielding parameters do not do what their names say

`jmIgnoreFoeProb` and `jmIgnoreFoeSpeed` are the only advertised
junction-model yielding controls. Verified from
[[episodic-memory/2026-08-05_15-00-00/outputs/results/probe_channels.json]]:
with `jmIgnoreFoeSpeed = 0` (SUMO's default), `jmIgnoreFoeProb` has **zero**
measurable effect across its entire 0.0–1.0 range — realised yielding stays
bit-identical to three decimals (0.021 at `priority="false"`, 0.768 at
`priority="true"`). Only with `jmIgnoreFoeSpeed` also set nonzero does
`jmIgnoreFoeProb` move anything, and even then across a narrow band
(0.768 → 0.708). **The documented channel spans exactly two usable
operating points — roughly 2% or roughly 71–77% yielding — never the
field-documented targets of 10–30% (uncontrolled), 70–90% (RRFB), or 95%+
(PHB).** `traci.vehicle.setParameter` cannot set `junctionModel.ignoreFoeProb`
at runtime at all (`does not support junctionModel parameter`); only
`junctionModel.ignoreIDs`/`ignoreTypes` are runtime-settable, and
`ignoreTypes` requires the vType **id**, not the vClass — `"pedestrian"`
(the vClass) did nothing, `"ped"` (the actual vType id) worked.

A real continuum was built instead with a TraCI kinematic yield controller:
each vehicle entering a decision zone with a pedestrian present and a
comfortable stop still possible draws Bernoulli(target rate); yielders are
commanded toward a real stop and held until the crossing is clear 1.0 s.
Verified commanded-to-realised mapping (from raw trajectories, not
assumed): 0.0→0.021, 0.2→0.200, 0.5→0.565, 0.8→0.786, 1.0→0.992. Two
implementation traps had to be fixed first and are worth re-checking if
this controller is reused: a presence test that only checks zone entry
(not continuously) double-counts queued followers as fresh yields, and
`slowDown()` alone produces creeping rather than a real stop.

## Which PHB phases SUMO can and cannot represent

Characterized per signal-head state in isolation (120 s per state, 180 s
warm-up):

| state | maps to | veh/h through | stop fraction |
|---|---|---|---|
| `O` | dark | 1470 | 0.254 |
| `o` | flashing yellow | 1080 | 0.543 |
| `y` | steady yellow | **0** | 0.998 |
| `r` | steady red + WALK | 0 | 1.000 |
| `s` | **flashing red** | 660 | 0.567 |
| `G` | reference | 2130 | 0.299 |

The flashing-red clearance phase — stop-then-proceed if clear — is
genuinely representable (`s`, 660 veh/h). Not representable: any actual
flashing indication (only steady states exist); a dilemma-zone "go"
decision on yellow (`y` passes 0 vehicles, stops 99.8% — **overstates** PHB
vehicle delay); a dark PHB letting pedestrians cross on a natural gap (the
implementation blocks pedestrians entirely while dark — **overstates** PHB
pedestrian delay at low volume); and pedestrian clearance countdown
semantics. In a live 1800 s run at 900 veh/h/dir and 80 ped/h, only **2 of
917** vehicles crossed the conflict point while a pedestrian occupied it
(0.22%) — and both leaked encroachments occurred during the one state (`s`)
that is faithfully modelled, meaning the approximation is not hiding risk
so much as concentrating exactly where the real device also carries
residual risk.

## Pedestrian delay is driven by yielding rate, not by device identity

At fixed volume, uncontrolled-crossing pedestrian delay is monotone in
realised yielding: 0.0 → 20.5 s, 1.0 → 7.7 s. CRN-paired RRFB-vs-PHB
comparisons at matched yielding confirm device identity is not the causal
variable — indistinguishable at 300 and 900 veh/h/dir across the whole
RRFB yield range (p = 0.20–0.96), RRFB *beats* PHB by 3.7–5.3 s at 1200
veh/h/dir once its realised yielding reaches ≥0.48 (p ≤ 0.003). With the
beacon-presence trap fixed, a correctly-tuned RRFB at realised 0.70–0.81
(the field-documented band) beat a PHB by 4.5–6.1 s under platooned
arrivals (p ≤ 0.03). **Calibrate to the yielding rate a device is expected
to produce, then choose the cheapest device that reaches it.**

## The uncontrolled crossing's volume threshold is arrival-process-dependent

Sweeping 600–3600 major veh/h: platoon-coordinated arrivals through
zero-offset signals never explode in the tested range (LOS B throughout,
7.5–9.9 s) because coordination guarantees a crossable window every cycle.
Poisson arrivals on 2 lanes reach LOS F by 1800 veh/h/dir (48–58 s, 81–97%
waiting >30 s). Poisson arrivals on 1 lane are **non-monotone** — 13.1 →
23.2 → 17.9 → 14.1 s across 600/1200/1800/2400 veh/h — coinciding with the
arterial itself saturating above ~1200 veh/h (time loss rising from 21 to
193 s/veh). **The exact mechanism is only partly pinned down**: the
whole-run mean-accepted-gap statistic stays roughly flat (16.6–17.4 s)
across this same sweep rather than rising, so "congestion creates larger
accepted gaps" is a plausible but not directly measured explanation for
the delay drop — a local, at-the-crossing gap or approach-speed measure
would be needed to confirm the mechanism rather than just its outcome.

## The measured critical gap does not scale with crossing width

Minimum accepted gap measured directly from trajectories: **4.2–6.5 s at
the 12.8 m (2-lane) full crossing, 6.7–9.5 s at the 6.4 m (1-lane) full
crossing** — the wider crossing shows the smaller gap, the reverse of a
nominal-crossing-time model (`τ = L/1.2 + 1` predicts 11.67 s and 6.33 s
respectively). Half-crossings (refuge stages) show the same weak-to-inverse
relationship: the 3.2 m one-lane stage measures 4.8–7.8 s, the 6.4 m
two-lane stage measures 4.1–6.8 s. Crossing width is a poor predictor of
SUMO's pedestrian accepted gap.

Cross-checking the uncontrolled arm against Adams/Tanner gap-acceptance
theory: agreement holds to within a factor of 1.4–2.2 under Poisson
arrivals below capacity, and departs in a fully explained way above
capacity (Adams assumes free-flowing traffic). Under platooned arrivals it
is wrong by up to 12× because signal metering violates the Poisson
assumption outright — theory only applies where its own assumptions hold.

## The refuge island: theory's sign is right only at low volume, then reverses — and it is the worst safety arm everywhere

Because of the gap-width non-scaling above, the two-independent-gaps refuge
theory (predicted benefit rising monotonically: +3.7/+12.7/+34.5/+87.4 s)
only holds at low-to-moderate Poisson volume: **+10.2 s** observed at 1200
veh/h/dir total demand (within ~20% of the +12.7 s prediction), then
**reverses sign**, reaching **−33.5 s** at 2400 veh/h/dir total. Under
platooned arrivals it is negative at every volume tested (−3.5 to −19.9 s,
all p ≤ 0.003). Both figures are from the `commanded_yield = 0.0` condition
in `controls_staging_matched_yield.csv`, where the confirmed-fixed
comparison holds both arms at exactly 0.00 realised yielding. Mechanism,
verified from trajectories: SUMO's pedestrian crosses stage 1 at the first
adequate near-direction gap **without checking the far direction**, then
can be marooned mid-refuge; combined with the accepted gap not shrinking
for the shorter half-crossing, the intended benefit erodes with volume.

The refuge also raises pedestrian-vehicle conflict exposure (PET<2s) in
**every one of the 16 demand/yielding cells tested — p<0.05 in all 16,
p≤0.001 in 11 of 16** — by +0.36 to +1.14 events per pedestrian. It is the
worst-performing arm on safety in every condition tested, not merely on
average.

## A full pretimed signal's vehicle cost is flat in pedestrian volume; a PHB's is sublinear

Sweeping pedestrian volume 10→150/h at fixed 900 veh/h/dir: PHB vehicle
delay's log-log slope against pedestrian volume is **0.261** (21.4 → 44.5
s/veh across a 15× pedestrian-volume increase) — genuinely sublinear,
driven by call consolidation (peds/call rises 1.00 → 1.48 as the 20 s
minimum recurrence interval binds). A **full pedestrian signal's slope is
0.001** — essentially flat (30.4 → 30.5 s/veh) — because its pedestrian
phase runs on recall every cycle regardless of demand, a fixed toll rather
than a demand-responsive cost. There is a crossover near 70–80 ped/h below
which the PHB is cheaper for vehicles and above which the flat-cost
pretimed signal is; the PHB beats the full signal on pedestrian delay at
every volume tested (10.3–14.7 s vs 22.4–28.1 s).

## Delay-induced risk-taking reverses sign with the arrival process

Within-cell correlation of pedestrian delay against minimum accepted gap
(volume fixed, only yielding varied — pooling across volume would confound
this): under **Poisson** arrivals, longer waits genuinely predict shorter
accepted gaps (r = −0.70 to −0.78, p < 1e−6). Under **platooned** arrivals
the sign **reverses** (r = +0.35 to +0.44, p ≤ 0.029) — a long wait there
means the pedestrian rode out a platoon and crossed in the large
inter-platoon gap that follows, not that they grew impatient. The
conflict-exposure half (delay vs. PET<2s) stays positive in both regimes.
Reporting only the Poisson half — the more intuitive, "expected" result —
would have been actively wrong for platooned demand; both directions were
checked and both are reported, per this project's standing practice after
a prior episode was caught reporting only the convenient half of an
asymmetric result.

## A safety-metric trap: naive TTC mis-ranks a signalized crossing as most dangerous

At Poisson arrivals, 600 veh/h/dir — a demand/arrival-process cell chosen
as illustrative; the same qualitative pattern (full signal highest on
naive TTC among real crossing treatments, low on PET) holds across all 8
demand/arrival-process cells tested — the **full pedestrian signal** scores
*highest* on naive encounter-level TTC<1.5s (0.504 events/pedestrian) of
any real crossing treatment, while scoring near-lowest on PET<2s (0.005).
The refuge shows the reverse pattern: near-safest on TTC (0.005) while
worst by nearly two orders of magnitude on PET (1.370). **Naive
distance/speed TTC flags a vehicle approaching a red light at speed as an
imminent collision even though it is decelerating to a stop under
command** — a measurement artifact, not a real safety signal. Rank
crossing treatments by PET or encroachment rate (a vehicle physically
present in the conflict zone while a pedestrian occupies it), not by
distance/speed TTC, whenever any arm includes a controlled approach.

## The MUTCD Section 4F PHB warrant is systematically conservative here — not aligned, and not the reverse

Digitized MUTCD 4F warrant curve for a 21 ft crosswalk: 400 ped/h required
at 600 major veh/h, 110 at 1200, 28 at 1800. CRN-paired PHB-vs-uncontrolled
benefit testing found simulated pedestrian-delay benefit already
significant at the **lowest tested pedestrian volume (15 ped/h)** at every
major-road volume checked (benefit ≥26.7×, ≥7.3×, ≥1.9× the threshold
needed to matter, at 600/1200/1800 veh/h respectively) — the true benefit
boundary is ≤15 ped/h and remains unresolved below that floor. A
least-intrusive-device decision rule (cheapest device meeting mean delay
≤30 s, share >30 s ≤0.20, PET no worse than baseline) agrees with the
MUTCD warrant in **20 of 32** tested cells; in the other **12**, MUTCD
warrants a PHB where uncontrolled or RRFB already satisfies every
criterion. **Zero cells ran in the reverse direction (under-warranting).**
The disagreement in this testbed is entirely one-directional: MUTCD 4F is
conservative relative to simulated pedestrian-delay benefit, never lax.

**This reverses under platooned arrivals, and the reversal is more
consequential than the headline number**: at a coordinated-signal
arterial, installing a PHB can make pedestrian delay *worse* (+0.4 to +7.1
s at the 21 ft crosswalk), because the existing coordinated signals
already hand the uncontrolled crossing a free gap every cycle, and the PHB
forces pedestrians onto its own actuation cycle instead. Any measured
"benefit" there is a *vehicle*-delay benefit (arterial time loss falling
up to 65.9 s/veh), not a pedestrian-service one, and should not be read as
vindicating the warrant.

## Gotchas

- `priority="true"` crossings skip gap acceptance entirely — pedestrians
  step out unconditionally regardless of the yielding rate. Use
  `priority="false"` for a real accept/reject decision.
- Minimum-accepted-gap statistics computed from a merged passage stream
  are not comparable across lane counts — more lanes means shorter
  apparent gaps independent of any behavior change.
- A shared output path reused across parallel batch workers silently
  corrupted 63 of 2310 runs in this study (a single tripinfo path across
  five parallel yield-target arms); put every swept parameter into the run
  id used for output paths.
- A documented parameter can move nothing at all even at its extreme
  values if the wrong companion parameter is left at its default —
  verify realised behavior from raw trajectories, never trust a parameter
  name at face value.

See `calibrate-motorist-yielding-and-select-midblock-crossing-treatment`
for the full build/calibration/evaluation workflow, and
[[pedestrian-crossings-and-signal-phasing]] for the junction-crossing
construction and phasing this page's midblock treatment extends.
