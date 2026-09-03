---
summary: SUMO's connection `visibility` attribute has zero measured effect on gap acceptance / critical gap (6.1225s in every tested condition from 200m to 7.5m, confirmed independently via Raff's method) — the entire capacity effect instead runs through follow-up headway via a vehicle-spacing/minGap threshold, and SUMO's own undocumented default (4.5m) is already a severely sight-restricted condition that partly explains why SUMO agrees with HCM's TWSC formula at defaults but disagrees badly (+38% to +108%) once the sight triangle is cleared; the capacity loss from a sight restriction is not proportionate to what AASHTO's Case B intersection-sight-distance standard would call unsafe, SUMO's SSM safety device shows crossing conflicts falling (not rising) under restriction with only rear-end conflicts increasing, and the AASHTO-logical countermeasure of lowering the major-road speed limit genuinely worsens delay in SUMO under both restricted and cleared sight conditions.
keywords:
  - intersection-sight-distance
  - isd
  - sight-triangle
  - sumo-visibility-attribute
  - aashto-case-b
  - twsc
  - critical-gap
  - follow-up-headway
created: 2026-08-05T22:30:00
last_updated: 2026-08-05T22:30:00
sources:
  - "[[episodic-memory/2026-08-05_22-30-00/outputs/analysis/D2_fine_first_riser.csv]]"
  - "[[episodic-memory/2026-08-05_22-30-00/outputs/analysis/B_gapfit.csv]]"
  - "[[episodic-memory/2026-08-05_22-30-00/outputs/analysis/D_tc_tf.csv]]"
  - "[[episodic-memory/2026-08-05_22-30-00/outputs/analysis/F_spacing_summary.csv]]"
  - "[[episodic-memory/2026-08-05_22-30-00/outputs/analysis/A_speed_profiles.csv]]"
  - "[[episodic-memory/2026-08-05_22-30-00/outputs/analysis/A_capacity_fingerprint.csv]]"
  - "[[episodic-memory/2026-08-05_22-30-00/outputs/analysis/G_hcm_comparison.csv]]"
  - "[[episodic-memory/2026-08-05_22-30-00/outputs/analysis/G_aashto_isd_mapping.csv]]"
  - "[[episodic-memory/2026-08-05_22-30-00/outputs/analysis/C_cells.csv]]"
  - "[[episodic-memory/2026-08-05_22-30-00/outputs/analysis/E_cells.csv]]"
  - "[[episodic-memory/2026-08-05_22-30-00/outputs/analysis/E_ranking.csv]]"
  - "[[episodic-memory/2026-08-05_22-30-00/outputs/analysis/validity_audit.csv]]"
related_pages:
  - "[[demand-arrival-process-and-unsignalized-capacity]]"
  - "[[unsignalized-vs-signalized-intersection-control]]"
  - "[[surrogate-safety-measures]]"
  - "[[hcm-control-delay-vs-sumo-delay-metrics]]"
  - "[[roundabout-capacity-law-and-demand-metering]]"
related_skills:
  - model-intersection-sight-distance-restriction-at-a-twsc-junction
  - model-demand-arrival-process-and-its-effect-on-capacity-and-delay
  - compare-unsignalized-intersection-control-types
  - analyze-intersection-safety-with-ssm
  - quantify-sumo-run-to-run-variability
related_skills_for_graph_view:
  - "[[model-intersection-sight-distance-restriction-at-a-twsc-junction]]"
  - "[[model-demand-arrival-process-and-its-effect-on-capacity-and-delay]]"
  - "[[compare-unsignalized-intersection-control-types]]"
  - "[[analyze-intersection-safety-with-ssm]]"
  - "[[quantify-sumo-run-to-run-variability]]"
---

# Intersection Sight Distance and SUMO's Visibility Parameter

A two-way-stop-controlled (TWSC) intersection with an obstructed sight
triangle is one of the most common real-world geometric-design
deficiencies, and a standard AASHTO countermeasure item. This page records
what SUMO's connection `visibility` attribute actually does when used to
model it — which, verified on 2132 CRN-replicated runs, turns out to be
almost nothing at the gap-acceptance level, with a genuine, mechanistically
explained null result at the center of the finding.

## The critical gap is invariant to visibility; only follow-up headway moves

Measured directly from a deterministic conflicting-stream capacity
staircase, 0.02 s grid resolution: SUMO's effective critical gap is
**6.1225 s in every one of 5 tested (control-type, visibility)
combinations, from 200 m down to 7.5 m, identical to the fourth decimal**.
Cross-checked independently via Raff's method on the empirical accepted/
rejected gap distribution: 5.88–5.90 s across all 16 tested (control,
visibility) combinations — likewise invariant. **Gap acceptance does not
respond to `visibility` at all, at any tested level.**

The entire measured capacity effect instead runs through **follow-up
headway**: stop-control `t_f` measured at 3.031 s for visibility ≥30 m,
rising to 4.187 s at 7.5 m and at SUMO's undocumented default. Attributing
a capacity or delay change to "sight distance" without separately checking
critical gap and follow-up headway risks crediting the wrong mechanism.

## The mechanism is vehicle spacing, not line-of-sight

Checked causally rather than assumed: the stopped lead vehicle in the
minor-approach queue sits at essentially zero distance from the stop line
in every tested condition (minimum speed 0.000 m/s at 0.10 m from the
stop line, confirmed across 47 FCD profiles including at 200 m
visibility) — the vehicle whose gap-acceptance decision actually matters
can always see, regardless of the restriction. The restriction acts only
on vehicles further back in the queue, via SUMO's junction-visibility-based
waiting-position placement, not via any driver's gap-acceptance judgment.

A direct causal test confirmed a vehicle-spacing hypothesis: at 6.0 m
inter-vehicle spacing in the minor queue, visibility 7.5 m gave 458.0
veh/h against the default's 368.0 veh/h — a real, spacing-dependent
difference — while at 7.5/10.0/10.5 m spacing all tested visibility
values collapsed to the same capacity floor. **The threshold tracks
vehicle length + minGap, not any sight-distance scale.**

## SUMO's true default is undocumented, hard-coded, and already a restricted condition

netconvert writes no `visibility` attribute when none is specified — the
default is silent. Confirmed via two independent methods: the FCD speed
profile at the default matches the explicit `visibility="4.5"` profile
exactly (minimum speed 6.230 m/s at 4.25 m) and differs measurably from
explicit 4.0 m or 5.0 m; the capacity fingerprint at the default (591.0
veh/h, headway 4.269 s) matches the explicit 4.5 m condition to the
decimal. **SUMO's true default minor-approach visibility is 4.5 m — an
out-of-the-box SUMO TWSC junction is already a severely sight-restricted
one** by any real-world standard.

## SUMO's HCM agreement is partly an artifact of that hidden default

At the hidden default (4.5 m), simulated potential capacity matched HCM's
TWSC gap-acceptance formula closely: −0.4% to +8.4% error across a
296–1389 veh/h major-flow sweep. **Clearing the sight triangle to 200 m
makes SUMO disagree badly with HCM instead**: +37.9% to +108.3%
over-prediction across the same sweep. HCM's formula assumes adequate
sight distance is already provided — it is SUMO's default restriction,
not a deliberate modeling choice, that is doing the work of matching HCM.
Any capacity validation against HCM at a TWSC intersection should state
the `visibility` value used.

## The capacity loss is not proportionate to what AASHTO calls unsafe

Mapped tested visibility values to the AASHTO Case B sight-triangle leg
length they fall short of at a 70 km/h major-road design speed: AASHTO
requires 146.0 m (Case B1, left turn from minor) / 126.5 m (Case B2–B3,
right turn or crossing). A visibility of 120 m — already AASHTO-deficient
— cost only 3.9% of stop-controlled minor capacity at 700 veh/h (681.6 vs
709.6 veh/h); 7.5 m, a severe restriction, cost 46.4%. Under **yield**
control the same 200 m→15 m range produced a flat statistical null
(820.8±44.6 vs 816.8±50.3 veh/h) — yield control's continuous
gap-evaluation behavior appears structurally insensitive to this
parameter over the tested range. A geometric deficiency AASHTO would flag
as unsafe does not translate into a proportionate simulated capacity
penalty in SUMO — the two measures answer different questions.

## Safety (SSM) shows a null-to-favorable result under restriction

Crossing conflicts fell slightly under restriction (240.8 → 232.4 events
at 400 veh/h major flow), and worst-case crossing minimum TTC at 1200
veh/h flow was safer under 200 m visibility (1.39 s) than under 7.5 m
(1.80 s, the better/higher number). PET < 1.0 s conflicts were exactly
zero in all 24 tested cells. The only conflict type that rose under
restriction was rear-end (396.4 → 451.6 events, +13.9%) — consistent with
the follow-up-headway mechanism above, not any crossing-conflict
mechanism. Do not assume restricted sight distance increases
crossing-conflict counts in SUMO's SSM output without checking.

## Countermeasures, and a checked-both-directions null on the speed-limit fix

At the most restricted setting and 800 veh/h major flow, minor-approach
delay ranked: all-way stop (6.83 s) < clearing the sight triangle
(18.32 s) ≈ signalizing (18.46 s) < doing nothing (30.12 s) < lowering the
speed limit to 50 km/h (40.01 s) < to 40 km/h (58.11 s). Total
intersection delay re-ranks: clearing the sight triangle (4.43 s) <
baseline (7.27 s) < all-way stop (9.26 s) < signalizing (10.27 s) — the
countermeasure best for the disadvantaged minor movement is not the same
one best system-wide.

**The AASHTO-logical countermeasure — lowering the major-road speed
limit, which reduces the required ISD — was checked from both directions
and genuinely hurts delay in SUMO under both conditions tested**:
restricted sight (30.12 s → 40.01 s at 50 km/h) and even a *cleared*
sight triangle (18.32 s → 21.30 s at 50 km/h). SUMO's gap-acceptance
logic does not treat a lower speed limit as making a fixed physical gap
more traversable the way design-standard logic behind ISD does; it
simply reduces major-stream throughput/spacing without a compensating
gap-acceptance benefit. Do not assume a design-standard-logical
countermeasure produces a SUMO-simulated benefit without checking.

## Gotchas

- `foeVisibility` does not exist as a connection attribute in the tested
  SUMO version (1.27.1) — verify against the version in use before
  assuming it is settable.
- `visibility ≤ 0.1 m` gives exactly zero measured capacity — a hard
  floor, not a meaningful "extremely restricted but nonzero" condition.
- Junction `radius` is a bigger lever than most of the visibility sweep:
  4 m → 10 m at fixed visibility cost 6.7% of capacity — hold it fixed
  across a visibility sweep or it will contaminate the result.
- A control-delay datum computed from each control arm's own network can
  go negative for a signalized arm, because the free-flow probe itself
  waits at a red light. Measure the free-flow datum from a shared,
  control-free twin network instead.
- The stop-bar detector must sit on the internal (junction) lane, not the
  incoming approach lane, to correctly measure stop-line discharge.
- A static "how many queued vehicles fit inside the visibility radius"
  model correctly predicts the first one or two queue-position capacity
  risers but fails at the fourth — don't extrapolate it past what's
  directly verified.

See `model-intersection-sight-distance-restriction-at-a-twsc-junction`
for the full build/measurement/countermeasure workflow, and
[[demand-arrival-process-and-unsignalized-capacity]] for the
deterministic-staircase critical-gap/follow-up-time measurement method
this page reuses.
