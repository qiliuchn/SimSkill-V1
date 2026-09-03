---
summary: MUTCD volume warrants (Warrant 1 eight-hour, Warrant 2 four-hour, Warrant 3 peak-hour) are defined on DEMAND volumes, but a saturated stop-controlled minor approach meters its own throughput, so a stop-bar detector count understates minor-street volume most severely exactly where the warrant is closest to being met; verified in SUMO the measured minor-approach volume is non-monotone in development size and can flip an eight-hour warrant from met to not-met at the most congested intensity tested, while Warrant 3 Condition A's stopped-delay test reads 0.0 vehicle-hours in the hour when the approach is most broken.
keywords:
  - mutcd-signal-warrant
  - traffic-impact-analysis
  - ite-trip-generation
  - pass-by-trips
  - demand-vs-served-volume
  - driveway-access-management
  - right-in-right-out
created: 2026-08-04T14:00:00
last_updated: 2026-08-05T16:00:00
sources:
  - "[[episodic-memory/2026-08-04_14-00-00/outputs/TIA_RECOMMENDATION.md]]"
  - "[[episodic-memory/2026-08-04_14-00-00/outputs/WARRANT_SUMMARY.md]]"
  - "[[episodic-memory/2026-08-04_14-00-00/outputs/LOS_QUEUE_COMPARISON.md]]"
related_pages:
  - "[[unsignalized-vs-signalized-intersection-control]]"
  - "[[hcm-control-delay-vs-sumo-delay-metrics]]"
  - "[[webster-method]]"
  - "[[left-turn-storage-bay-length-design]]"
  - "[[left-turn-treatment-tradeoffs]]"
  - "[[actuated-traffic-signals]]"
  - "[[teleport-artifacts-and-gridlock-resolution-validity]]"
  - "[[field-counts-to-simulation-demand-and-the-saturated-count-truncation-trap]]"
  - "[[sumo-stochastic-variability-and-replication-design]]"
  - "[[sumo-output-files]]"
  - "[[rcut-and-michigan-left-alternative-intersection-design]]"
  - "[[waut-time-of-day-signal-plan-switching]]"
  - "[[motorist-yielding-calibration-and-midblock-crossing-treatment-selection]]"
related_skills:
  - conduct-driveway-signal-warrant-traffic-impact-analysis
  - compare-unsignalized-intersection-control-types
  - measure-saturation-flow-and-validate-webster-method
  - generate-hcm-los-report-and-validate-against-microsimulation
  - control-signals-with-actuated-tls
  - design-left-turn-storage-bay-length
  - calibrate-motorist-yielding-and-select-midblock-crossing-treatment
related_skills_for_graph_view:
  - "[[conduct-driveway-signal-warrant-traffic-impact-analysis]]"
  - "[[compare-unsignalized-intersection-control-types]]"
  - "[[measure-saturation-flow-and-validate-webster-method]]"
  - "[[generate-hcm-los-report-and-validate-against-microsimulation]]"
  - "[[control-signals-with-actuated-tls]]"
  - "[[design-left-turn-storage-bay-length]]"
  - "[[calibrate-motorist-yielding-and-select-midblock-crossing-treatment]]"
---

# MUTCD Signal Warrants and the Demand-vs-Served-Volume Trap

A signal warrant is the regulatory gate a development Traffic Impact Analysis has to pass
before a traffic signal can be installed at a site driveway. The MUTCD volume warrants are
threshold tests on two numbers per clock hour: the **total major-street volume** on both
approaches, and the volume on the **higher-volume minor-street approach**. This page records
what happens when those two numbers are measured from a microsimulation instead of assumed —
and the answer is that the second one is systematically wrong in the regime the warrant
exists to detect. See `conduct-driveway-signal-warrant-traffic-impact-analysis` for the full
workflow.

## The warrants, as implementable tests

| Warrant | Test | Hours required |
|---|---|---|
| 1, Condition A — Minimum Vehicular Volume | major and minor both ≥ Table 4C-1 values | 8 of an average day |
| 1, Condition B — Interruption of Continuous Traffic | major and minor both ≥ Table 4C-1 values | 8 |
| 1, Combination | neither A nor B alone, but **both** at their 80% values | the same 8 |
| 2 — Four-Hour Vehicular Volume | point on/above the Figure 4C-1 curve | 4 |
| 3 — Peak Hour (Condition B) | point on/above the Figure 4C-3 curve | 1 |
| 3 — Peak Hour (Condition A) | minor stopped delay ≥ 4 veh-h (1-lane) **and** minor ≥ 100 veh/h **and** total entering ≥ 800 veh/h (4-leg) | 1 |

Warrant 1 comes from a numeric table and is exact. For a major street with 2+ lanes each
approach and a 1-lane minor approach, the 100% column is **600/150** (Condition A) and
**900/75** (Condition B); the 80%, 70% and 56% columns are those values scaled.

**Warrants 2 and 3 are plotted curves, not tables** (Figures 4C-1 and 4C-3, with 4C-2 and
4C-4 the 70% versions). Any implementation therefore encodes a *digitisation* of a figure,
and any conclusion drawn from it needs a stated sensitivity test. Re-evaluating every
conclusion with the curve scaled 0.90–1.10 is cheap and worth doing: in one verified study,
of six scenario x volume-basis combinations exactly one was unstable in that band — a
no-build case whose peak hour sat at a margin of 0.981 (1.9% below the digitised Warrant 3
curve), flipping "any warrant met" between scale 0.95 and 1.00. Every other conclusion held
across the full band. That is a far more useful statement than asserting the digitisation is
fine. The figures' own axis notes give hard floors — 80 veh/h (Warrant 2) and
100 veh/h (Warrant 3) for a one-lane minor approach, 115 and 150 for two or more — and those
*are* exact.

## The trap: a saturated stop bar measures capacity, not demand

The warrants are defined on demand. A stop-controlled minor approach that is over capacity
discharges at its capacity, so a detector at its stop bar counts capacity. Because the
approach's gap-acceptance capacity falls as the major street gets busier, the count is most
depressed at exactly the major-street volumes that push the warrant curve's x-axis to the
right — i.e. the measurement error is worst where the decision is hardest.

Verified in SUMO over a 10-point site-intensity sweep of a one-lane full-movement driveway on
a 4-lane 55 km/h arterial (93 hour-observations), the ratio of stop-bar count to realised
generated demand:

| driveway nominal v/c | n | mean stop-bar / generated |
|---|---:|---:|
| below 0.95 | 60 | ≈ 1.00 |
| 0.95 – 1.05 | 5 | 0.904 |
| 1.05 – 1.25 | 5 | 0.835 |
| 1.25 – 1.60 | 8 | 0.564 |
| 1.60 – 2.20 | 7 | 0.301 |
| 2.20 – 3.50 | 5 | 0.129 |
| above 3.50 | 3 | 0.085 |

The transition is sharp and centred on v/c = 1. Below it, differences between the demand
basis and the detector basis are Poisson sampling noise and can go either way.

### The measured volume is non-monotone in development size

This is the consequence that makes the trap dangerous rather than merely conservative.
Verified PM-peak stop-bar counts on the same driveway: **95 veh/h at 0.5× site intensity and
39 veh/h at 3.0×**. Because the warrant thresholds are monotone in minor volume, an analyst
using measured counts sees the case for a signal get *weaker* as the development gets bigger.
In the verified study the demand basis gave Warrant 1 Condition A in 10 hours and Condition B
in 11 at 3.0× intensity — comfortably warranted — while the detector basis on the same run
gave 1 and 4 hours, i.e. **Warrant 1 not met at the most congested intensity tested**. The
two bases first disagreed systematically at 0.5× intensity and the gap widened monotonically
after that.

### Warrant 3 Condition A's delay test fails the same way, and worse

Its first clause is ≥ 4 vehicle-hours of stopped-time delay *on the minor approach*. In one
verified hour of the highest-intensity run (nominal driveway demand 396 veh/h, 35 vehicles
actually served) that quantity measured **0.0 vehicle-hours** — the vehicles were not on the
approach, they were still on the site behind a full 250 m of storage. The insertion backlog
attributable to that one hour was **909 vehicle-hours** (not even the largest single-hour
backlog in the run — that was 1158 vehicle-hours, one hour earlier). A delay test scoped to
the approach can read zero at the exact moment the approach is most broken.

### What to use instead

Evaluate warrants on **demand**: projected/ITE-derived turning movements, counts taken where
and when the approach is not metered, or counts corrected upward by an observed residual
queue. In a simulation all the bases are recoverable from raw output and should be reported
together — nominal (the flow file), realised-generated (`tripinfo` `depart − departDelay`),
inserted (`tripinfo` `depart`), served (E1 `nVehContrib`) — see [[sumo-output-files]]. If
field counts at a saturated stop bar are the only data available, they must be paired with a
queue survey.

## "Warrant met" and "the signal helps" are different questions

They usually agree, because both are downstream of the same physical quantity — the number of
usable gaps in the major stream. Verified 12-hour totals (mean of 3 seeds) on the same
network:

| scenario | any volume warrant met (demand, 100%) | TWSC veh-h delay | actuated signal veh-h | agree? |
|---|---|---:|---:|---|
| no-build | False | 23.7 | 52.1 (+120%) | yes |
| build | True | 465.4 | 69.9 (−85%) | yes |
| high-intensity build | True | 5 749.1 | 118.1 (−98%) | yes |

**They come apart at the 70% column.** With no development at all, nothing was warranted at
the 100% column, but at the 70% column Warrant 1 Condition B was satisfied in all 12 study
hours and Warrants 2 and 3 as well — while installing the signal raised total delay by 120%
and eastbound through travel time by 42%. The 70% column requires major-street 85th-percentile
speed above 70 km/h **or** an isolated community below 10 000 population; on a 55 km/h
arterial the speed criterion does not apply, so invoking it needs the population
justification. It is a policy allowance for locations where drivers cannot reasonably find
gaps — **not** a prediction that operations will improve.

**Signalizing does penalise the arterial, measurably.** Verified PM-peak through travel time
over a fixed 350 m segment in the high-intensity case: 26.4 s under two-way stop control,
52.8 s with a Webster fixed-time plan, 46.1 s actuated. The intersection-wide result is still
strongly positive only because the driveway's per-vehicle delay is two orders of magnitude
larger. This trade should be reported explicitly rather than buried in an aggregate.

## Delay that no detector can see

An oversaturated driveway's queue length is *censored* by its storage: a lane-area detector's
Q95 saturates at the approach length and says nothing about how much worse it is. Verified
high-intensity case: Q95 pinned at the full 250 m approach while a further **1 534 vehicles**
(≈ 11.5 km equivalent at 7.5 m/veh) were waiting to be inserted — **5 283 vehicle-hours** of
delay that appears in no detector and in no `timeLoss` figure. Total delay for that arm was
466 vehicle-hours of `timeLoss` versus 5 749 vehicle-hours once the insertion backlog is
counted: **an order of magnitude**. Any oversaturated-arm comparison built on `timeLoss` alone
is wrong by that factor. In SUMO, run with **no `--max-depart-delay`** so the backlog
accumulates and is measurable rather than being silently dropped.

## LOS reporting for a mixed comparison

- **HCM LOS thresholds differ by control type**: unsignalized A≤10 / B≤15 / C≤25 / D≤35 /
  E≤50 / F>50 s per vehicle; signalized A≤10 / B≤20 / C≤35 / D≤55 / E≤80 / F>80. A TWSC-vs-
  signal table must carry both and label which was applied — see
  [[hcm-control-delay-vs-sumo-delay-metrics]] for the delay definition itself.
- **HCM does not define an intersection-wide LOS for two-way stop control.** The verified run
  shows why: a no-build TWSC intersection scored 8.8 s/veh ("LOS A") volume-weighted while its
  minor-street approach was at 140.8 s/veh, LOS F. An intersection-wide TWSC average is
  dominated by the uninterrupted major street and hides the failing approach entirely.

## Non-signal mitigation, and how to model right-in/right-out honestly

Verified 12-hour total delay relative to the TWSC baseline:

| mitigation | build | high-intensity build |
|---|---:|---:|
| exclusive right-turn lane on the driveway | −67% | −73% |
| right-in / right-out | −85% | −90% |
| Webster fixed-time signal | −81% | −97% |
| actuated signal | −85% | −98% |

An exclusive right-turn lane works by unblocking right-turners that the shared lane's
left-turners were holding up; it does nothing for the left-turn movement itself, whose queue
simply relocates into the new left-only lane (verified Q95 249 m of a 250 m approach). RIRO
essentially matched the actuated signal at build intensity but left ~4.7× its delay at high
intensity.

**Banning movements by connection alone silently deletes trips.** RIRO must re-route the
banned movements through a real alternative — e.g. a U-turn at a downstream median opening,
modelled by an explicit `<connection>` from the outbound edge back to the inbound edge at a
fringe node. Verified consequence of doing it properly: PM-peak volume across the measured
cross-sections rose from 1 808 to 2 742 veh/h, because the site's traffic now crosses the
intersection twice. That cost is invisible in `timeLoss` — extra distance travelled at free
flow loses no time — and appears only in total vehicle-hours of *travel*. Report both.

## ITE trip generation and pass-by bookkeeping

A TIA's site trips come from published ITE rates, and the arithmetic that most often goes
wrong is pass-by. A pass-by **vehicle** generates *two* driveway trip ends (one in, one out),
so:

```
P_vehicles   = site_trip_ends * passby_fraction / 2
new_in       = site_in  - P_vehicles
new_out      = site_out - P_vehicles
background_through_volume -= P_vehicles     (split by trip distribution direction)
```

Pass-by trips **load the driveway** but must be **subtracted from the arterial's through
volume**, because they were already on the road; only `trip_ends − 2·P` are NEW trips added to
the network. The accounting closes when total driveway volume = new_in + new_out + 2·P.

For the multi-hour profile itself: one `<flow>` per movement per 15-minute slice per clock
hour, with a documented peak-hour factor applied by giving the peak quarter a share of
`1/(4·PHF)`; Poisson arrivals via `period="exp(<veh/s>)"` rather than the deterministic
`vehsPerHour`; and `t = 0` mapped to the first study hour so `period="3600"` detector
intervals land on exact clock hours.

## Related SUMO instrumentation pitfalls found while building this

- **An E3 `<detEntry>` at `pos="0"` — or at any position ≤ the vehicle length — never
  registers.** A vehicle must physically cross the position, and with the default
  `departPos="base"` its front bumper starts at `length` metres. Verified: two whole
  approaches produced `vehicleSum="0"` in every interval of every run, silently and with no
  warning, until the entry cross-section was moved to 15 m. Always check `vehicleSum > 0` per
  movement before analysing E3 output.
- **SUMO's keep-right lane-change rule badly unbalances a multi-lane approach.** Verified by
  running the identical scenario with and without `lcKeepRight="0"`: in the 07:00 hour an
  eastbound approach carrying ~508 veh/h split 423/84 under SUMO's defaults (83.4% in one
  lane) versus 246/262 (51.6%) with keep-right disabled; over 24 approach-hours the mean
  max-lane share fell from 83.6% to 55.9%. Per-lane v/c, queue and capacity figures are
  meaningless without checking this. Note however that not every imbalance is a lane-change
  artifact — with keep-right off the same approach still reached 90.7% and 99.5% in the two
  hours when the left-turn bay had spilled back and was physically blocking the bay-feeding
  lane.
- **netconvert always writes its own `<tlLogic programID="0">`.** Loading a hand-written
  program with the same id and programID is a hard error, and deleting the auto-generated
  `tlLogic` from the compiled net leaves the junction with no TLS at all. The working pattern
  is a distinct `programID` activated at t = 0 by `<WAUT refTime="0" startProg="…"/>` plus
  `<wautJunction procedure="Immediate"/>` — see [[waut-time-of-day-signal-plan-switching]].
