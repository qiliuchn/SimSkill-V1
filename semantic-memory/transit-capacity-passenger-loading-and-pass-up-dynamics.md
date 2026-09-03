---
summary: What SUMO actually does when a transit vehicle's personCapacity binds — boarding is FIFO by arrival at the stop, alighting is unaffected and capacity is re-evaluated mid-dwell, dwell is max(door, boardingDuration x (boarded+alighted)) with no alightingDuration existing at all, and a pass-up is invisible in every output channel with zero warnings — plus the measured consequences: a binding capacity truncates the bunching feedback loop so headway CV looks 35% better while passenger time rises 80%, holding control flips from helping to harming passengers, and frequency-vs-vehicle-size ranks matched configurations oppositely on total time and pass-ups.
keywords:
  - transit-capacity
  - personCapacity
  - pass-up
  - denied-boarding
  - left-behind-passenger
  - load-profile
  - max-load-point
  - load-factor
  - crowding-multiplier
  - dwell-time-law
  - boardingDuration
  - headway-cv
  - bunching-truncation
  - frequency-vs-vehicle-size
created: 2026-08-11T19:05:00
last_updated: 2026-08-11T19:05:00
sources:
  - "[[episodic-memory/2026-08-11_18-30-39/summary.md]]"
related_pages:
  - "[[bus-bunching-and-forward-headway-holding]]"
  - "[[bus-stop-infrastructure-design-parking-mechanism-and-tsp-interaction]]"
  - "[[public-transport-and-intermodal-routing]]"
  - "[[sumo-output-files]]"
  - "[[sumo-stochastic-variability-and-replication-design]]"
  - "[[transit-signal-priority]]"
  - "[[downs-thomson-paradox-and-mode-choice-equilibrium]]"
related_skills:
  - model-capacity-constrained-transit-passenger-loading
  - demonstrate-and-control-bus-bunching
  - design-bus-stop-placement-type-and-spacing
  - simulate-multimodal-transit
related_skills_for_graph_view:
  - "[[model-capacity-constrained-transit-passenger-loading]]"
  - "[[demonstrate-and-control-bus-bunching]]"
  - "[[design-bus-stop-placement-type-and-spacing]]"
  - "[[simulate-multimodal-transit]]"
---

# Transit Capacity, Passenger Loading and Pass-Up Dynamics

A transit vehicle's `personCapacity` is normally set high in SUMO studies precisely so it
never binds — a too-low capacity censors ridership and quietly corrupts every downstream
metric. But a binding capacity is what real crowded lines have, and letting it bind turns
out to change not just how bad service is, but which conclusions the standard reliability
metrics support.

All figures below come from a 10-stop corridor with a non-uniform boarding/alighting OD
(genuine interior max-load point), endogenous dwell, and 130 runs at 5 Common-Random-Number
replications per arm.

## SUMO's boarding semantics under a binding capacity

Verified by probe, then re-verified with independently designed, stricter probes:

- **Capacity genuinely binds.** `personCapacity=3` with five queued gives
  `loadedPersons=3`.
- **Service is FIFO by arrival at the stop** — not insertion order, not depart time.
  Separating these requires differential `<access>` walk lengths so arrival and insertion
  order disagree, and a 4-person / capacity-2 design to distinguish all four candidate
  orderings (FIFO/LIFO × arrival/insertion); a 3-person design cannot.
- **A denied person simply remains and boards a later vehicle.** No event, no loss.
- **Alighting is unaffected and capacity is re-evaluated mid-dwell**: a bus arriving full
  has one passenger alight and immediately fills that seat within the same stop.
- `--time-to-teleport.ride` **defaults to −1 (disabled)**, so stranded passengers wait
  indefinitely rather than teleporting.

## A pass-up is invisible in every SUMO output channel

This is the load-bearing fact of the whole domain. Confirmed at the schema level in
SUMO 1.27.1:

- `--stop-output` exposes only `initialPersons / loadedPersons / unloadedPersons` — no
  denial field. The one indirect hint is `initial − unloaded + loaded == personCapacity`.
- tripinfo `<ride>` exposes `waitingTime / vehicle / depart / arrival / arrivalPos /
  duration / routeLength / timeLoss`. `waitingTime` correctly *includes* the pass-up wait
  but a 1200 s wait from three refused buses is indistinguishable from a 1200 s headway.
- `--person-summary-output`'s `waitingForRide` is the only aggregate oversubscription
  signal and attributes nothing to a bus, stop or person.
- TraCI has no denied-boarding counter.
- **SUMO emits zero warnings.** A line refusing a third of its passengers looks healthy.

So pass-ups must be **reconstructed**: person *p* waiting at stop *s* over
`[wait_start, board)` was passed up by every bus whose stop-output record at *s* has
`wait_start < ended < board`, with `wait_start = ride.depart − ride.waitingTime`. Two
properties make this exact — `ride.depart` equals the boarding bus's `ended` to the
decimal, and SUMO measures `waitingTime` from the **end of the `<access>` walk**, so
buses missed while still walking are correctly excluded.

`traci.busstop.getPersonIDs()` is **not** a boarding queue and must not be used for this:
it also contains persons who just alighted there and persons still on the inbound walk,
and its order is not the service order — measured, it over-counts by ~11%, concentrated
at alighting-heavy stops. Validate any implementation against a non-binding control,
which must return exactly 0 pass-ups.

## The dwell law, and the attribute that does not exist

```
dwell = max(door_time, boardingDuration × (boarded + alighted))
```

Zero residual across 19 configurations, re-confirmed across 14 more varying
`boardingDuration` ∈ {0.5, 1, 2} and door ∈ {4, 20}. Boarding and alighting are strictly
**serial** and share one duration parameter, and the fixed door time is **absorbed, not
added** (5 board + 5 alight at bd=2 with door 4 → 20.00 s, not 24; with door 20 → 20.00 s).

**There is no `alightingDuration` in SUMO 1.27.1** — the vType schema has only
`boardingDuration`, `loadingDuration` (containers) and `boardingFactor`. Worse, a bogus
`alightingDuration` is **accepted silently with exit code 0**; only
`--xml-validation always` reports `attribute 'alightingDuration' is not declared for
element 'vType'`. Validate a vType once when authoring it, or an imagined attribute will
sit in the file doing nothing.

## Binding capacity truncates the bunching feedback loop

[[bus-bunching-and-forward-headway-holding]] establishes that dwell is near-perfectly
linear in boarding load, and that this linearity is the engine of bunching. A binding
capacity destroys that loop gain, because a bus arriving full boards nobody:

| arm | dwell-on-crowd slope (s/pax) | r |
|---|---|---|
| non-binding | +1.005 | +0.483 |
| non-binding, crowds 10–20 | **+1.995** (= the configured `boardingDuration`) | +0.827 |
| binding | **−0.033** | −0.056 |
| binding, bus arrives full | **−0.190** | −0.463 |

**The trap this creates:** from an identical dispatch perturbation, headway CV amplifies
**×2.25** along the corridor when capacity is non-binding but only **×1.20** when it
binds (pooled CV 0.219 vs 0.338, and zero paired buses under binding capacity). The
capacity-constrained line looks **35% more regular** — while total passenger time is
**+80.5%** (122.6 vs 67.9 pax-h), mean wait triples (518.5 vs 166.5 s) and p90 wait
quintuples (1520 vs 318 s). Binding capacity buys headway regularity by refusing service,
so headway CV must never be reported as a service-quality result without first checking
whether capacity binds.

Note that *mean* dwell barely moves (16.55 vs 19.00 s in the loaded window) — it is
specifically the variance-generating **slope** that is truncated. Measure inside the
loaded window; a whole-run average diluted by buses dispatched past the demand period
hides even that difference.

## Holding control flips sign once capacity binds

| | headway CV | mean wait | pass-ups/pax | total pax time |
|---|---|---|---|---|
| non-binding + holding | 0.338 → 0.132 (−60.8%) | 166.5 → 156.6 (**−6.0%**) | 0 → 0 | −0.7% n.s. |
| binding + holding | 0.219 → 0.113 (−48.4%) | 518.5 → 537.6 (**+3.7%**) | 1.215 → 1.267 (**+4.3%**) | **+3.8%** |

(paired 95% CIs exclude 0 except where marked n.s.) Forward-headway holding keeps its
regularity benefit under a binding capacity but pushes **every** passenger metric the
wrong way: the held bus arrives at the next stop to a crowd it cannot take, converting
headway variance into refused boardings (the worst stop's pass-ups grew 111.8 → 135.6).
Under a binding capacity, holding is a regularity intervention paid for by passengers.

## Frequency versus vehicle size at matched offered capacity

Holding seats/h constant and varying the split (20 seats/200 s, 30/300 s, 45/450 s):

- **Total passenger time**: small+frequent < medium < large+rare (110.0 / 122.6 / 142.4
  pax-h). At matched seats/h the only thing frequency buys is wait, and wait dominates.
- **Pass-up rate**: large+rare < medium < small+frequent (0.853 / 1.215 / 1.802 per
  passenger). Large vehicles buy *buffer* against stochastic surges, paying in dwell
  (11.95 vs 6.87 s/stop) and in-vehicle time (244 vs 199 s).

The two objectives rank the matched set **oppositely**, so the answer depends entirely on
which one the operator is optimizing.

**The demand crossover is a convergence, not a sign flip**: the small-bus advantage
shrinks monotonically (−18.8% / −10.2% / −4.1% / −0.1% n.s. / +0.1% n.s. at v/c 0.82 /
1.24 / 1.65 / 2.06 / 2.47), because once essentially everyone must queue for a later
vehicle the wait is set by the deficit rate (seats/h vs demand), which is matched. The
pass-up ordering stays clean at every demand level — so at high v/c the configurations
are statistically indistinguishable on total time while still differing ~35% in pass-ups.

## Two spatial and valuation findings

**Pass-ups concentrate upstream of the max-load point.** Measured: bs3 111.8, **bs4
482.0** (66% of all), bs5 133.0, ~0 elsewhere — while the max-load *segment* is bs5→bs6.
The hotspot is the last stop with heavy **boarding** demand before the load peaks. Site
relief interventions off the boarding-demand profile, not the load profile.

**Crowding weighting changes the level, not usually the ranking.** Applying a
Wardman & Whelan / PDFH-style multiplier in load factor (seated 1.00 → 1.13 at LF=1 →
1.47 at LF=2; standing 1.62 → 2.44) per ride segment leaves the matched-arm ranking
identical unweighted, weighted, and with wait valued at 2×. The reason is structural: at
matched offered capacity with a constant seat share, every matched arm runs at nearly the
same load factor per seat (1.47 / 1.39 / 1.39), so crowding rescales them almost equally.
It does bite on the **level**, unevenly — inflating the over-supplied arm most (×1.19),
whose passengers spend proportionally more of the journey in-vehicle rather than waiting.

## Practical notes

- A **non-uniform** boarding/alighting OD is required for a genuine interior max-load
  point: `w_ij ∝ b_i·a_j` for `j>i`, renormalised per origin, front-loaded boarding
  weights against back-loaded alighting weights.
- An **exactly periodic dispatch makes headway amplification unmeasurable** — it enters
  the line with CV 0 and the amplification ratio divides by ~0. Inject seed-controlled
  terminal jitter (sd ≈ 0.12 × headway), shared across arms as a common random number.
- SUMO **drops route entries whose `depart` precedes the last one loaded**, with
  `Warning: Route file should be sorted by departure time, ignoring '<id>'!` — which
  `--no-warnings true` hides. Sort person plans by departure time.
- `--tripinfo` can emit **`<ride depart="-1">` for a ride that actually completed** (1 in
  98 000 observed); guard any `ride.depart` arithmetic.
- Audit **completed vs still-waiting vs riding** person counts explicitly. In this domain
  passengers genuinely can be left behind, so a clean exit proves nothing.
