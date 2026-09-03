---
name: model-intersection-sight-distance-restriction-at-a-twsc-junction
description: Use this skill when the user wants to model restricted intersection sight distance (ISD) at a two-way-stop-controlled (TWSC) junction in SUMO, needs to know what SUMO's connection `visibility` attribute actually does (and its undocumented default), wants to compare simulated capacity against the HCM TWSC gap-acceptance formula or AASHTO Case B ISD sight-triangle requirements, or is evaluating countermeasures for a sight-restricted minor approach (clearing the sight triangle, lowering the major-road speed limit, converting to all-way stop, signalizing). Covers the verified, mechanistically-explained finding that SUMO's visibility parameter does NOT alter gap acceptance / critical gap at all — the entire capacity effect runs through follow-up headway via a vehicle-spacing threshold — plus a surprising, both-directions-checked null on the speed-limit countermeasure. Trigger on mentions of sight distance, intersection sight distance, ISD, sight triangle, SUMO visibility attribute, foeVisibility, or restricted sight at a stop-controlled intersection.
---

# Model Intersection Sight Distance Restriction at a TWSC Junction

**SUMO's connection `visibility` attribute does not alter gap-acceptance
behavior at all.** Verified on 2132 CRN-replicated runs (0 collisions, 0
teleports, 0 censoring): every capacity and delay effect attributed to
"restricted sight distance" in a naive SUMO study is actually a
vehicle-spacing/queue-discharge effect, not a sight-distance effect. This
skill covers how to discover and verify that mechanism, and what to do
about it.

## The critical gap is invariant to visibility; only follow-up headway moves

Measured a SUMO-effective critical gap directly from a deterministic
conflicting-stream capacity staircase (reusing the technique from
`model-demand-arrival-process-and-its-effect-on-capacity-and-delay`),
0.02 s grid resolution: **6.1225 s in every one of 5 tested
(control-type, visibility) combinations, from 200 m down to 7.5 m,
identical to the fourth decimal.** Cross-checked independently with Raff's
method fit to the empirical accepted/rejected gap distribution: 5.88–5.90 s
across all 16 tested (control, visibility) combinations — likewise
invariant. **Gap acceptance genuinely does not respond to `visibility` at
all, at any tested level.**

The entire measured capacity effect runs through **follow-up headway**
instead: stop-control `t_f` measured at 3.031 s for visibility ≥30 m,
rising to 4.187 s at 7.5 m and at SUMO's (undocumented) default. Verify
this split yourself before attributing any capacity change to "sight
distance" — it is easy to conflate the two if you only look at aggregate
capacity or delay.

## The mechanism is vehicle spacing, not line-of-sight — verified causally

Before generalizing this surprising result, it was checked causally, not
just correlationally: the stopped lead vehicle in the minor-approach queue
is at essentially zero distance from the stop line in every tested
condition (min speed 0.000 m/s at 0.10 m from the stop line, confirmed
across 47 FCD profiles including at 200 m visibility) — the vehicle whose
gap-acceptance decision actually matters can always see, regardless of the
restriction. **The restriction acts only on vehicles further back in the
queue**, via SUMO's junction-visibility-based waiting-position placement,
not via any driver's gap-acceptance judgment.

A direct causal test confirmed the vehicle-spacing hypothesis: sweeping
inter-vehicle spacing in the minor queue at fixed visibility showed the
visibility effect appears or vanishes depending on whether spacing crosses
a length-plus-minGap threshold — at 6.0 m spacing, visibility 7.5 m gave
458.0 veh/h against the default's 368.0 veh/h (a real, spacing-dependent
difference), while at 7.5/10.0/10.5 m spacing all tested visibility values
collapsed to the same capacity floor. **The threshold tracks vehicle
length + minGap, not any sight-distance scale.**

## SUMO's true default is undocumented, hard-coded, and already a restricted condition

netconvert writes no `visibility` attribute at all when none is specified
— the default is silent. Identified and confirmed via two independent
methods: (1) the FCD speed profile at the default matches the explicit
`visibility="4.5"` profile exactly (minimum speed 6.230 m/s at 4.25 m from
the stop line) and differs measurably from explicit 4.0 m or 5.0 m; (2)
the capacity fingerprint at the default (591.0 veh/h, headway 4.269 s)
matches the explicit 4.5 m condition to the decimal. **SUMO's true default
minor-approach visibility is 4.5 m — an out-of-the-box SUMO TWSC junction
is already a severely sight-restricted one** by any real-world standard.

## SUMO's HCM agreement is partly an artifact of that hidden default

At the (hidden) default 4.5 m visibility, simulated potential capacity
matched HCM's TWSC gap-acceptance formula closely: −0.4% to +8.4% error
across a 296–1389 veh/h major-flow sweep. **Clearing the sight triangle to
200 m makes SUMO disagree badly with HCM instead**: +37.9% to +108.3%
over-prediction across the same sweep. This is the reverse of the naive
expectation — HCM's formula assumes adequate sight distance is already
provided, so it is *SUMO's default restriction*, not any deliberate
modeling choice, that is doing the work of matching HCM. Any prior or
future capacity validation against HCM at a TWSC intersection should
state the `visibility` value used, or risk an unexamined default silently
determining whether the comparison passes.

## The capacity loss is not consistent with what AASHTO calls unsafe

Mapped each tested visibility value to the AASHTO Case B sight-triangle
leg length it falls short of, at a 70 km/h major-road design speed:
AASHTO requires 146.0 m (Case B1, left turn from minor) / 126.5 m (Case
B2–B3, right turn or crossing). **A visibility of 120 m — already
AASHTO-deficient — cost only 3.9% of stop-controlled minor capacity at
700 veh/h** (681.6 vs 709.6 veh/h); **7.5 m, a severe real-world
restriction, cost 46.4%.** Under **yield** control (as opposed to stop),
the effect across the same 200 m→15 m range was a flat statistical null
(820.8±44.6 vs 816.8±50.3 veh/h) — yield control's continuous
gap-evaluation behavior appears to make it structurally insensitive to
this parameter over the range tested. **A geometric deficiency AASHTO
would flag as unsafe does not translate into a proportionate simulated
capacity penalty in SUMO** — the two measures are answering different
questions (design-standard adequacy vs. simulated throughput), and a study
using one to validate the other should say so explicitly.

## Safety (SSM) shows a null-to-favorable result under restriction — read it carefully

Running the SSM conflict device across the visibility sweep found crossing
conflicts fall slightly under restriction (240.8 → 232.4 events at
400 veh/h major flow), and the worst-case crossing minimum TTC at
1200 veh/h flow is *safer* under 200 m visibility (1.39 s) than under
7.5 m (1.80 s is the *better*, higher number — restriction narrows the gap
vehicles will attempt to use, which reduces close-call crossing
encounters in this device's TTC/PET accounting). PET < 1.0 s conflicts
were exactly zero in all 24 tested cells. **The only conflict type that
rose under restriction was rear-end** (396.4 → 451.6 events, +13.9%) —
consistent with the queue-discharge/follow-up-headway mechanism above,
not with any crossing-conflict mechanism. Do not assume restricted sight
distance increases crossing-conflict counts in SUMO's SSM output without
checking — in this study it did the opposite, and only the queue-internal
conflict type moved in the expected direction.

## Countermeasures, and a checked-both-directions null on the speed-limit fix

At the most restricted setting and 800 veh/h major flow, minor-approach
delay ranked: all-way stop (6.83 s) < clearing the sight triangle
(18.32 s) ≈ signalizing (18.46 s) < doing nothing (30.12 s) < lowering the
speed limit to 50 km/h (40.01 s) < lowering it to 40 km/h (58.11 s). Total
intersection delay re-ranks differently: clearing the sight triangle
(4.43 s) < baseline (7.27 s) < all-way stop (9.26 s) < signalizing
(10.27 s) — the countermeasure that is best for the disadvantaged minor
movement is not the same one that is best system-wide.

**The AASHTO-logical countermeasure (lowering the major-road speed limit,
which reduces the required ISD) was checked from both directions and
genuinely hurts delay in SUMO under both tested conditions** — restricted
sight (30.12 s → 40.01 s going from baseline to 50 km/h) and even under a
*cleared* sight triangle (18.32 s → 21.30 s at 50 km/h) — because SUMO's
gap-acceptance logic does not treat a lower speed limit as making a fixed
physical gap more traversable the way the design-standard logic behind
ISD does; it simply reduces major-stream throughput/spacing at the
approach without a compensating gap-acceptance benefit. **Do not assume a
design-standard-logical countermeasure produces a SUMO-simulated benefit
without checking — this is a genuine SUMO behavioral limitation, not
merely counterintuitive advice.**

## Gotchas

- **`foeVisibility` does not exist as a connection attribute** in the
  tested SUMO version (1.27.1) — do not assume it is a real, settable
  parameter without verifying against the version in use.
- **`visibility ≤ 0.1 m` gives exactly zero measured capacity** — useful
  as a hard floor / sanity check, but not a meaningful "extremely
  restricted but nonzero" condition.
- **Junction `radius` is a bigger lever than most of the visibility
  sweep**: increasing it from 4 m to 10 m at fixed visibility cost 6.7% of
  capacity — check and hold this parameter fixed across a visibility
  sweep, or its effect will contaminate the visibility result.
- **A control-delay datum computed from each control arm's own network can
  go negative for a signalized arm**, because the free-flow probe itself
  waits at a red light. Measure the free-flow datum from a shared,
  control-free twin network (same geometry/speeds, `priority` junction
  type, unrestricted visibility) instead.
- **`--device.fcd.period`** is the correct option name for FCD sampling
  interval; clearing every XML element while iterating an FCD trace with
  `iterparse` will silently empty the parsed trace if done incorrectly —
  verify a nonzero vehicle count came out before trusting a downstream
  statistic.
- **The stop-bar detector must sit on the internal (junction) lane**, not
  the incoming approach lane, to correctly measure discharge at the stop
  line itself.
- A static "how many queued vehicles fit inside the visibility radius"
  model correctly predicts the first one or two queue-position capacity
  risers but fails at the fourth — don't extrapolate it past what's been
  directly verified.

See `model-demand-arrival-process-and-its-effect-on-capacity-and-delay`
for the deterministic-staircase critical-gap/follow-up-time measurement
method reused here, `compare-unsignalized-intersection-control-types` for
the shared-geometry TWSC/AWSC/signal build pattern, and
`analyze-intersection-safety-with-ssm` for the SSM device configuration
used for the conflict-rate comparison.
