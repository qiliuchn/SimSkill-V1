---
name: design-multimodal-signal-progression-for-bicycles-and-cars
description: Use this skill when the user wants a signalized arterial that serves both bicycles and cars, is deciding whether a "bicycle green wave" is worth building, needs to model a dedicated bike lane in SUMO without silently getting the wrong answer, or wants to know whether cycle length or offsets is the stronger lever for a slow, dispersed mode. Covers a critical measurement trap — SUMO's default lane model makes a dedicated bike lane look WORSE for cyclists than mixed traffic, purely because it cannot represent in-lane overtaking — plus verified findings on bandwidth realization asymmetry between fast and slow modes, why pooling both directions of a one-way-tuned wave can hide a net loss, the design-speed tolerance window (which scales as 1/v²), and how far a bicycle platoon actually survives before dispersing. Trigger on mentions of bicycle green wave, multimodal progression, bike lane signal coordination, or slow-mode arterial coordination.
---

# Design Multimodal Signal Progression for Bicycles and Cars

**A dedicated bike lane can measure as WORSE for cyclists than mixed
traffic in SUMO, purely as a modeling artifact — not a real finding —
unless the sublane model is enabled.** Verified on a 6-signal, 400 m
spacing arterial with dedicated-lane and mixed-traffic geometry variants,
identical demand (600 cars/h/dir, 250 bicycles/h/dir), 401 CRN-replicated
sweep runs.

## Establish what SUMO actually does with bicycles before analyzing anything

- **Desired speed**: realised speed = `min(desiredMaxSpeed, edgeSpeed) ×
  speedFactor`, capped by `maxSpeed`. Bicycle default `desiredMaxSpeed` ≈
  5.56 m/s. **`speedFactor="1.0"` is not deterministic** — the default
  `speedDev=0.1` still applies (measured sd 0.547 m/s even with Krauss
  `sigma=0`); set `speedDev` explicitly if you need a controlled
  dispersion level.
- **Lane occupancy**: verified from FCD, bicycles stayed on the dedicated
  lane 100.000% of samples (117,280/117,280) in the dedicated-lane
  geometry; in mixed traffic, bicycles used the rightmost lane 82.6% of
  the time.
- **Red compliance**: 0 red-junction entries out of thousands checked in
  both geometries — SUMO bicycles do stop at red reliably. **Measurement
  trap**: detecting "junction entry" from an x-position threshold at the
  end of the approach lane produced spurious violations (a queued
  vehicle's front legitimately rests exactly on the stop line) — detect
  entry from the FCD lane identity (internal `:J*` lane IDs) instead.
- **Saturation discharge**: measured bicycle headway 2.109 s → ~1707
  bicycles/h/lane in this study's vType, versus ~1881 veh/h/lane for
  cars in the same run — dominated by car-following `tau` (±0.4 s moves
  the discharge rate ±250 bikes/h).
- **Right-turn interaction**: right-turning vehicles genuinely yield to
  bicycles at junctions (verified: compiled-net foe relationships plus
  448 TraCI-observed yield events). Isolating the *attributable* delay
  cost requires care: naively deleting bicycles from the demand and
  comparing right-turn cohort delay overstates the effect, because
  removing bicycles also removes ~9% of total demand system-wide. Use a
  difference-in-differences design against a matched control cohort (e.g.
  left-turners, who see the same demand reduction but don't interact with
  the bicycle-yield mechanism) to isolate the true attributable delay.
- **What SUMO does NOT model at all**: riding two abreast, a bike box /
  advanced stop line (no representable analogue — a leading bicycle green
  interval only reproduces departure order, not storage geometry), and —
  critically — **overtaking within a single-file dedicated bike lane
  under the default lane-changing model**. Bicycles in a single dedicated
  lane can never pass a slower rider ahead of them unless the sublane
  model (`--lateral-resolution`) is enabled.

## The critical measurement trap: a dedicated bike lane looks worse than mixed traffic under the default lane model

Identical demand, identical route lengths (to the metre), only the lane
model toggled:

| geometry | lane model | bicycle progression speed | bicycle delay | car delay |
|---|---|---|---|---|
| dedicated lane | default | 3.82 m/s | **86.2 s/km** | 44.7 s/km |
| dedicated lane | sublane | 4.29 m/s | **36.8 s/km** | 45.0 s/km |
| mixed traffic | default | 4.35 m/s | 49.6 s/km | 91.2 s/km |
| mixed traffic | sublane | 4.31 m/s | 37.4 s/km | 50.1 s/km |

Under the **default** lane model, moving bicycles into their own
dedicated lane makes their delay nearly *double* relative to riding in
mixed traffic (86.2 vs 49.6 s/km) — a nonsensical result. Enabling the
**sublane** model cuts dedicated-lane bicycle delay by 57% (86.2 → 36.8
s/km) and restores the expected ordering (dedicated ≤ mixed for both
modes), while car delay in the dedicated-lane geometry barely changes
(44.7 → 45.0 s/km) — confirming the effect is entirely internal to the
bike lane. Root cause, cross-verified from lane-change event data: under
the default model in a single-file dedicated lane, bicycles show **0
overtaking events out of 1326+ opportunities**; enabling sublane produces
genuine overtaking (134/1485 events, 5337 side-by-side pairs observed).
**Any SUMO bicycle-infrastructure study run at non-trivial bicycle volume
under the default lane model risks getting the bicycle-side conclusion
qualitatively backwards — always enable the sublane model for a dedicated
single bike lane, and verify overtaking is actually occurring from
lane-change event data before trusting a delay comparison.**

## Bandwidth realization is asymmetric between a fast and a slow mode

An analytic MAXBAND-style progression band hands each mode a fair-share
window on paper, but realized delivery differs sharply: cars realized
**101.7%** of their analytic band (measured zero-stop fraction /
band-over-cycle-ratio), while bicycles realized only **39.9%** of theirs
in the identical study, at the same demand and geometry. A bicycle-tuned
progression's benefit to bicycles was **not statistically distinguishable
from simply running the car-tuned progression instead** (p=0.059,
CRN-paired), while tuning for bicycles cost cars their *entire* measured
benefit (car realized band dropped from 101.7% to 0% when the plan
switched from car-tuned to bike-tuned offsets). **A slower, more
speed-dispersed mode does not benefit proportionally from a progression
band sized the same way as a fast, tightly-distributed mode's band.**

## Pooling both directions can hide a real net loss — check the per-direction split

A one-way-tuned progression (offsets computed for the eastbound direction
only) improved eastbound bicycle delay by 6.81 s/km relative to no
coordination, but worsened westbound bicycle delay by 13.67 s/km — a net
**+3.26 s/km increase in pooled bicycle delay**, i.e. **bicycles were
worse off, on average across both directions, than with no coordination
at all**, despite the plan being labeled and evaluated as delivering a
real eastbound improvement. **Always report both directions separately
before pooling — a directional progression plan evaluated only on its
designed direction can look like a clear win while making the mode it
was built for worse off overall.**

## The design-speed tolerance window scales as 1/v² — a slow mode has a much narrower absolute (but wider relative) tolerance

The exact interval-algebra bound on how far a chosen design speed `v_d`
can deviate from the calibrated stream speed `v` while still delivering
useful bandwidth is `|1/v_d − 1/v| ≤ g_T / ((n−1)·L)` (independent of
which mode; a pure geometric identity). Evaluated at this study's
geometry: bicycles' usable design-speed window was **[3.60, 4.30] m/s
(±9.0% relative)**; cars' was **[9.68, 17.40] m/s (±31.0% relative)** —
roughly 11× wider in absolute speed terms, but only about 3.4× wider in
*relative* terms. **State which tolerance ratio (absolute or relative)
you mean — they give substantially different pictures of how forgiving
the design is.** Consequence, measured directly: mistuning a bicycle
progression's design speed by +13% relative to the true calibrated stream
speed (using a plausible but wrong nominal speed instead of the measured
one) degraded 5-intersection platoon survival to 0.0746 — **worse than
running no coordination at all (0.0882)**. Always calibrate the design
speed from measured stream speed, not a nominal/assumed value, and prefer
the *stream's* progression speed (paced by its slowest riders) over an
individual free-flow speed — in this study the calibrated stream speed
(3.91 m/s) was measurably below individual free-cruise p85 (4.50 m/s).

## Platoon coherence: a bicycle green wave survives roughly 2-3 signals, not the whole corridor

Measured per-intersection survival factor (fraction of the platoon that
has not yet had a full stop, matched wave conditions at a realistic
speed-dispersion level): **cars 0.871**, **bicycles 0.714**. Compounding
across even a modest corridor makes the difference stark: over 5
intersections cars retained roughly half the platoon coherent (0.520)
while bicycles retained only about a fifth (0.204) under their own
matched wave — and under no coordination at all bicycles retained only
0.048 by the fifth intersection. **A bicycle green wave is a real,
worthwhile intervention for the first 2-3 signals of a corridor and
delivers rapidly diminishing value beyond that** — set expectations and
corridor scope accordingly rather than promising system-wide bicycle
progression.

## Cycle length is a far stronger lever than offset tuning for a slow mode

At fixed cycle length (90 s), the best available offset choice improved
bicycle delay by only 1.67 s/km over no coordination. Shortening the
cycle length alone (90 s → 55 s, at matched arterial green ratio) improved
bicycle delay by 10.10 s/km — **roughly 6× the best offset effect** — and
cost the cross street nothing at this study's demand level (though this
will not hold at higher cross-street v/c). Across an 80-plan Pareto
frontier search over both delay dimensions, **every non-dominated plan
was a shorter-cycle plan; not one plan using the baseline 90 s cycle with
any offset choice (one-way-tuned, two-way MAXBAND, or directionally
asymmetric) reached the frontier**. For two-way bicycle progression
specifically, hitting the resonant cycle length `C = 2L / (n · v_bike)`
(here predicted at 102/68/51 s for progressing across 2/3/4 links, and
confirmed at those measured cycle lengths) can make even a zero-offset
plan bandwidth-optimal. **When bicycles are a design priority, sweep
cycle length before spending effort on offset optimization.**

## Directional-asymmetric offsets do split the benefit, but only cars actually take their share

A directionally-asymmetric plan (short green-wave band to bicycles in one
direction, to cars in the other) delivered exactly the intended trade for
cars — the favored direction's car delay improved by 14.4-14.6 s/km,
checked in both assignment directions — but bicycles captured only a
small fraction of their favored-direction share (1.2 and 0.5 s/km
respectively). **An asymmetric-offset compromise is a real tool for
balancing car-direction priorities, but does not reliably translate into
comparable bicycle benefit even when explicitly designed to.**

## Gotchas

- Enable the sublane model (`--lateral-resolution`) for any dedicated
  single bike lane carrying non-trivial volume, and verify overtaking is
  occurring from lane-change event data before trusting a delay result.
- Set `speedDev` explicitly for bicycles — `speedFactor="1.0"` alone does
  not eliminate speed dispersion.
- Detect junction/red-light entry from FCD lane identity, not an
  x-position threshold — a stopped vehicle's front legitimately rests at
  the stop-line boundary.
- Report each direction of a one-way-tuned progression separately before
  pooling; pooling can hide a genuine net loss to the mode the plan was
  built for.
- Calibrate a progression's design speed from the measured *stream* speed
  (paced by the slowest riders), not an individual free-flow speed or a
  plausible nominal value — mistuning can make coordination worse than
  none at all.
- Sweep cycle length before offsets when optimizing progression for a
  slow, dispersed mode.

See `design-arterial-signal-progression-and-verify-bandwidth` for the
offset-algebra and time-space-diagram bandwidth-verification methodology
this skill extends to a second mode, `model-dedicated-bicycle-lane-infrastructure`
and `model-vclass-lane-permissions` for the bike-lane construction this
skill's geometry variants build on, and `quantify-sumo-run-to-run-variability`
for the CRN-paired replication design used throughout.
