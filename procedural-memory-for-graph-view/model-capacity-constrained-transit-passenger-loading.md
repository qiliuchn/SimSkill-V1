---
name: model-capacity-constrained-transit-passenger-loading
description: Use this skill when a transit vehicle's `personCapacity` is allowed to BIND rather than being configured away — passengers denied boarding (pass-ups / left-behinds), load profiles and the max-load point, load factor, crowding-weighted perceived travel time, and the operator's frequency-versus-vehicle-size decision at matched offered capacity. Every other transit skill in memory sets `personCapacity` high on purpose and treats a binding capacity as a bug that censors ridership; here it is the object of study. Critically, SUMO has NO pass-up observable at all — no output field, no TraCI counter, no warning — so pass-ups must be reconstructed by joining `--stop-output` with tripinfo `<ride>`, and this skill bundles that reconstruction. Also covers what SUMO actually does when capacity binds (FIFO by arrival at the stop, alighting unaffected, capacity re-evaluated mid-dwell), the real dwell law `max(door_time, boardingDuration x (boarded + alighted))` and the fact that `alightingDuration` does not exist, and the finding that a binding capacity TRUNCATES the bus-bunching feedback loop so headways look more regular while passengers are far worse off. Trigger on mentions of transit capacity, personCapacity, full bus, pass-up, passenger left behind, denied boarding, standing passengers, crowding or crowding multiplier, load factor, max-load point, transit load profile, bus size versus frequency, articulated versus standard bus, or overcrowded transit line.
related_skills:
  - demonstrate-and-control-bus-bunching
  - design-bus-stop-placement-type-and-spacing
  - simulate-multimodal-transit
  - quantify-sumo-run-to-run-variability
  - analyze-simulation-outputs
  - visualize-trajectories-and-timeseries
related_skills_for_graph_view:
  - "[[demonstrate-and-control-bus-bunching]]"
  - "[[design-bus-stop-placement-type-and-spacing]]"
  - "[[simulate-multimodal-transit]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[analyze-simulation-outputs]]"
  - "[[visualize-trajectories-and-timeseries]]"
related_pages:
  - "[[transit-capacity-passenger-loading-and-pass-up-dynamics]]"
  - "[[bus-bunching-and-forward-headway-holding]]"
  - "[[bus-stop-infrastructure-design-parking-mechanism-and-tsp-interaction]]"
  - "[[public-transport-and-intermodal-routing]]"
  - "[[sumo-output-files]]"
---

# Model Capacity-Constrained Transit: Passenger Loading and Pass-Ups

Lets a bus line's `personCapacity` actually bind, and measures what that does to
passengers *and* to service stability — two things that move in opposite directions.

Every other transit skill in memory configures this away on purpose:
`equilibrate-endogenous-mode-choice-with-transit-supply-feedback` sets
`personCapacity="4000"`, and `design-bus-stop-placement-type-and-spacing` warns "set
capacity high enough for the demand under test — a too-low capacity silently censors
ridership." That warning is correct *as a warning*, and it is also the mechanism that,
in real operations, is the binding constraint. This skill inverts it.

## The one thing to know first: SUMO cannot tell you a passenger was left behind

There is **no pass-up observable anywhere in SUMO 1.27.1** — verified at the schema
level, not just by inspection:

- `--stop-output` (`stopinfo_file.xsd`) has only `initialPersons / loadedPersons /
  unloadedPersons` (+ container analogues). No denial count, flag, or name. The only
  indirect hint is `initial − unloaded + loaded == personCapacity`.
- tripinfo `<ride>` has `waitingTime / vehicle / depart / arrival / arrivalPos /
  duration / routeLength / timeLoss`. `waitingTime` **does** correctly include the
  pass-up wait, but a 1200 s wait from three refused buses is indistinguishable from a
  1200 s headway.
- `--person-summary-output`'s `waitingForRide` is the only *aggregate* oversubscription
  signal, and never attributes a denial to a bus, stop, or person.
- TraCI has `getPersonCapacity` / `getPersonNumber` / `busstop.getPersonIDs`, but no
  denied-boarding counter.
- **SUMO emits zero warnings.** A line refusing a third of its passengers looks exactly
  like a healthy one.

So the headline metric of this entire domain is a *derived* quantity. Get it right, and
prove it with a negative control.

## Scripts

`scripts/passup_from_xml.py` — pass-up reconstruction from raw `--stop-output` +
tripinfo, standalone (no TraCI, no run harness):

```bash
python3 scripts/passup_from_xml.py stopinfo.xml.gz tripinfo.xml.gz
# riders=600  total pass-ups=765  per rider=1.275
# by stop: {'bs3': 168, 'bs4': 455, 'bs5': 142}
# boarded the k-th bus: {1: '57.5%', 2: '16.0%', 3: '8.5%', ... 11: '0.2%'}
```

The rule: person *p* waiting at stop *s* over `[wait_start, board)` was passed up by
every bus whose stop-output record at *s* has `wait_start < ended < board`, where
`wait_start = ride.depart − ride.waitingTime`. Two properties make this exact rather
than approximate — `ride.depart` equals the boarding bus's `ended` to the decimal (so
the strict inequality excludes the bus actually boarded), and SUMO measures
`waitingTime` from the **end of the `<access>` walk** (so buses missed while the person
was still walking are correctly not counted as pass-ups).

`reconstruct()` also returns the **waiting crowd each bus saw on arrival**, which is the
x-axis of the dwell-vs-crowd fit below.

**Do not instrument this with `traci.busstop.getPersonIDs()`.** That list also contains
persons who just *alighted* there (lingering in their egress `<access>` stage) and
persons still on the inbound walk, and its order is not the service order. Measured, it
over-counted pass-ups by ~11%, concentrated entirely at alighting-heavy stops.

**Always run the non-binding negative control** — same scenario, `personCapacity` raised,
everything else identical. It must return exactly **0.000** pass-ups. The bundled script
does (verified across 5 replications); if yours does not, it is counting something else.

A complete worked implementation (corridor, mechanism probes, 130-run matrix, crowding
weighting, five figures) is in
`episodic-memory/2026-08-11_18-30-39/attempts/attempt-1/scripts/`.

## What SUMO actually does when capacity binds

All verified by probe, and independently re-verified with a stricter probe design:

- **Capacity genuinely binds.** `personCapacity=3` with five queued → `loadedPersons=3`.
- **Boarding is FIFO by arrival at the stop** — not by insertion order, not by depart
  time. Prove this with differential `<access>` walk lengths so arrival order and
  insertion order disagree; a 4-person / capacity-2 design separates all four candidate
  orderings (FIFO/LIFO × arrival/insertion), a 3-person design cannot.
- **The denied person simply stays and takes the next vehicle.** Nothing is lost, no
  event fires.
- **Alighting is unaffected, and capacity is re-evaluated mid-dwell.** A bus arriving
  full has a passenger alight and immediately fills that seat within the same stop
  (`initial=3, unloaded=1, loaded=1`).
- **Set `--time-to-teleport.ride` explicitly.** It defaults to −1 (disabled), so stranded
  passengers wait forever — which is what you want here, but state it rather than
  inherit it.

## The dwell law is a max(), not a sum — and `alightingDuration` does not exist

Both matter for any endogenous-dwell transit model, capacity-constrained or not:

```
dwell = max(door_time, boardingDuration × (boarded + alighted))
```

Fit with **zero residual** across 19 configurations, and re-confirmed independently
across 14 more varying `boardingDuration` ∈ {0.5, 1, 2} and door ∈ {4, 20}. Two
consequences people get wrong:

- Boarding and alighting are **strictly serial** and share one `boardingDuration`.
  **There is no `alightingDuration` in SUMO 1.27.1** — the vType schema has only
  `boardingDuration`, `loadingDuration` (containers) and `boardingFactor`.
- The fixed door time is **absorbed, not added**: 5 board + 5 alight at
  `boardingDuration=2`, door 4 → 20.00 s (not 24), and door 20 → 20.00 s.

**A bogus `alightingDuration` is accepted silently, exit code 0**, unless you pass
`--xml-validation always` — which then reports `attribute 'alightingDuration' is not
declared for element 'vType'`. Run validation once when authoring a vType; otherwise a
typo'd or imagined attribute costs nothing at load time and silently does nothing.

## Binding capacity truncates the bunching feedback loop

`[[bus-bunching-and-forward-headway-holding]]` establishes that dwell is near-perfectly
linear in boarding load, and that this is what drives bunching. A binding capacity
**destroys that loop gain**, because a bus that arrives full boards nobody:

| arm | n | dwell-on-crowd slope (s/pax) | r |
|---|---|---|---|
| non-binding | 576 | **+1.005** | +0.483 |
| non-binding, crowds 10–20 | — | **+1.995** (= the configured `boardingDuration`) | +0.827 |
| binding | 569 | **−0.033** | −0.056 |
| binding, bus arrives FULL | 168 | **−0.190** | −0.463 |

The consequence is a genuine trap for anyone judging a line by its headways: measured
along a 10-stop corridor from an identical dispatch perturbation, headway CV amplifies
**×2.25** (0.198 → 0.446) when capacity is non-binding but only **×1.20** (0.198 →
0.237) when it binds. Pooled CV 0.219 binding vs 0.338 non-binding, and **zero** paired
buses under binding capacity. The capacity-constrained line looks **35% more regular** —
while total passenger time is **+80.5%** (122.55 vs 67.90 pax-h), mean wait triples
(518.5 vs 166.5 s) and p90 wait quintuples (1520 vs 318 s).

**Binding capacity buys headway regularity by refusing service.** Never report headway
CV as a service-quality result without checking whether capacity binds.

Note the *mean* dwell barely moves (16.55 vs 19.00 s in the loaded window) — it is
specifically the variance-generating **slope** that is truncated, not dwell overall. And
measure inside the loaded window: a whole-run average diluted by buses dispatched past
the demand period hides the difference.

## Holding control flips sign once capacity binds

Forward-headway holding (from `demonstrate-and-control-bus-bunching`) on the same
corridor, with and without a binding capacity:

| | headway CV | mean wait | pass-ups/pax | total pax time |
|---|---|---|---|---|
| **non-binding** + holding | 0.338 → 0.132 (−60.8%) | 166.5 → 156.6 (**−6.0%**) | 0 → 0 | −0.7% n.s. |
| **binding** + holding | 0.219 → 0.113 (−48.4%) | 518.5 → 537.6 (**+3.7%**) | 1.215 → 1.267 (**+4.3%**) | **+3.8%** |

All marked figures have paired 95% CIs excluding 0. With capacity non-binding, holding
is a clean win. With capacity binding it **still delivers its headway benefit but every
passenger metric moves the wrong way** — the held bus arrives at the next stop to a
crowd it cannot take, converting headway variance into refused boardings (pass-up
hotspot grew 111.8 → 135.6 at the worst stop). Under a binding capacity, forward-headway
holding is a regularity intervention paid for by passengers, not a passenger-service
intervention.

## Frequency versus vehicle size at matched offered capacity

Hold seats/h constant and vary the split (e.g. 20 seats/200 s, 30/300 s, 45/450 s), and
bracket the matched set with an under- and an over-supplied arm. Measured result:

**The two objectives rank the matched set in opposite directions.**
- Total (and crowding-weighted) passenger time: **small+frequent < medium < large+rare**
  (110.0 / 122.6 / 142.4 pax-h). At matched seats/h the only thing frequency buys is
  wait, and wait dominates.
- Pass-up rate: **large+rare < medium < small+frequent** (0.853 / 1.215 / 1.802 per
  passenger). Larger vehicles buy *buffer* against stochastic surges. They pay in dwell
  (11.95 vs 6.87 s/stop) and hence in-vehicle time (244 vs 199 s).

**The demand crossover is a convergence, not a sign flip.** The small-bus advantage
shrinks monotonically — −18.8% / −10.2% / −4.1% / −0.1% n.s. / +0.1% n.s. at v/c of
0.82 / 1.24 / 1.65 / 2.06 / 2.47 — because once essentially everyone must queue for a
later vehicle, wait is set by the deficit rate (seats/h vs demand), which is matched.
The pass-up ordering stays clean at every demand. Report which objective you optimized;
at high v/c the matched configurations are statistically indistinguishable on total time
while still differing by ~35% in pass-ups.

## Pass-ups concentrate upstream of the max-load point

Measured spatial distribution: bs3 111.8, **bs4 482.0** (66% of all), bs5 133.0, and
essentially zero everywhere else — while the max-load *segment* is bs5→bs6. The hotspot
is the last stop with heavy **boarding** demand before the load peaks, which is one stop
upstream. Instrument the boarding-demand profile, not just the load profile, when siting
a relief intervention.

## Crowding weighting changes the level, not usually the ranking

Apply a published-style (Wardman & Whelan / PDFH-type) multiplier in load factor —
seated 1.00 (LF≤0.5) → 1.13 (LF=1) → 1.47 (LF=2), standing 1.62 (LF=1) → 2.44 (LF=2) —
per ride segment, with segment loads reconstructed from the bus's own stop-output
sequence and rescaled so the weighted total still integrates to the true IVT.

On matched-capacity comparisons this **does not change the design you would pick**
(uplifts ×1.14–×1.16 across the matched arms; ranking identical unweighted, weighted,
and with wait valued at 2×). The reason is structural and worth checking before
investing in it: at matched offered capacity with a constant seat share, every matched
arm runs at nearly the same load factor per seat (1.47 / 1.39 / 1.39), so crowding
rescales them almost equally. Where it *does* bite is the **level**, and unevenly — it
inflates the over-supplied arm most (×1.19), because its passengers spend proportionally
more of their journey in-vehicle rather than waiting.

## Gotchas

- **A non-uniform boarding/alighting OD is required** to get a genuine interior max-load
  point. `w_ij ∝ b_i·a_j` for `j>i`, renormalised per origin, with front-loaded boarding
  weights and back-loaded alighting weights, works and is reproducible.
- **An exactly periodic dispatch makes headway amplification unmeasurable** — it enters
  the line with CV 0, so any amplification ratio divides by ~0. Inject seed-controlled
  terminal departure jitter (sd ≈ 0.12 × headway) shared across arms as a common random
  number.
- **SUMO drops route entries whose `depart` precedes the last one loaded**, emitting
  `Warning: Route file should be sorted by departure time, ignoring '<id>'!`. Sort person
  plans by departure. `--no-warnings true` hides this — a good reason to run once
  without it.
- **`--tripinfo` can emit `<ride depart="-1">` for a ride that actually completed** (1 in
  98 000 observed). Guard any `ride.depart` arithmetic; the bundled script does.
- **Audit person accounting explicitly** — completed vs still-waiting vs riding — as
  `design-bus-stop-placement-type-and-spacing` advises. The whole point of this domain is
  that passengers can be left behind, so "the run finished" proves nothing. 98 000
  persons were reconciled to 97 999 served here, with the single loss explained.

## Related

- [[transit-capacity-passenger-loading-and-pass-up-dynamics]] — the knowledge page behind
  this skill
- `demonstrate-and-control-bus-bunching` — the feedback loop this skill truncates, and
  the holding controller reused in the step-6 comparison
- `design-bus-stop-placement-type-and-spacing` — endogenous dwell modelling and the
  person-accounting discipline; its "set capacity high enough" pitfall is what this skill
  inverts
- `simulate-multimodal-transit`, `quantify-sumo-run-to-run-variability`,
  `analyze-simulation-outputs`, `visualize-trajectories-and-timeseries`
- [[bus-bunching-and-forward-headway-holding]],
  [[bus-stop-infrastructure-design-parking-mechanism-and-tsp-interaction]],
  [[public-transport-and-intermodal-routing]], [[sumo-output-files]]
