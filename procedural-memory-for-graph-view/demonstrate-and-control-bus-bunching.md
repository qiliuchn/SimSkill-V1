---
name: demonstrate-and-control-bus-bunching
description: Use this skill when the user wants to model bus bunching (transit headway instability, where buses pair up) on a SUMO loop route and/or implement a holding controller to suppress it — as opposed to simulate-multimodal-transit's routing/modal-split focus. Covers building a genuinely closed-loop network with circularity verification, the dwell-time-scales-with-boarding-load feedback mechanism that causes bunching, confirming genuine bunching emerges in an uncontrolled baseline BEFORE building a controller (not assuming it), and a forward-headway-only TraCI holding controller that holds early buses and never speeds up late ones. Trigger on mentions of bus bunching, headway instability, transit holding control, bus pairing, or headway coefficient of variation.
related_skills:
  - simulate-multimodal-transit
  - simulate-taxi-and-drt-dispatch
  - implement-emergency-vehicle-preemption
  - model-capacity-constrained-transit-passenger-loading
related_skills_for_graph_view:
  - "[[simulate-multimodal-transit]]"
  - "[[simulate-taxi-and-drt-dispatch]]"
  - "[[implement-emergency-vehicle-preemption]]"
  - "[[model-capacity-constrained-transit-passenger-loading]]"
related_pages:
  - "[[bus-bunching-and-forward-headway-holding]]"
  - "[[transit-capacity-passenger-loading-and-pass-up-dynamics]]"
---

# Demonstrate and Control Bus Bunching

Models bus bunching — the classic transit headway-instability feedback loop where a slightly-delayed bus accumulates more waiting passengers, dwells longer, falls further behind, while its follower (facing a thinner crowd) catches up and pairs with it — and a forward-headway holding controller that suppresses it. Distinct from `simulate-multimodal-transit`'s routing/modal-split focus: this skill is about transit *operations* dynamics.

## Building a genuinely closed loop

Author a network where every edge has exactly one successor forming a single cycle (no dead ends, no turnarounds) — verify this directly from the compiled net, don't assume a visually circular layout is actually traversable indefinitely:

```python
# check_loop.py pattern: walk successor links from any edge and confirm
# you return to the start after visiting every edge exactly once
```

Place at least 6 evenly-spaced `busStop`s around the loop. A route's `repeat` attribute repeats driving edges but **not** `<stop>` children — stops must be written out explicitly for every lap a bus makes.

## The bunching feedback mechanism: dwell scales with boarding load

Give the bus vType a realistic per-passenger `boardingDuration` so dwell time at a stop is proportional to how many passengers board — this is the actual causal mechanism of bunching, not an assumption:

```xml
<vType id="bus" boardingDuration="2.0" personCapacity="35" .../>
```

A realistic (not unlimited) `personCapacity` matters: a full bus leaving passengers behind caps the lagging bus's dwell growth, which is part of what makes holding-based recovery actually work later.

## Confirm genuine bunching before building a controller

**Run the uncontrolled baseline first and verify bunching actually emerges** — don't build a holding controller assuming the phenomenon will appear; if it doesn't with your first parameter choice, adjust demand rate, `boardingDuration`, or fleet size until it genuinely does. A report demonstrating a "control for a phenomenon we didn't actually observe" is not a valid study. Verify via:

1. **Rising headway coefficient of variation (CV)** across laps at a reference stop, computed directly from raw `--stop-output` (stopinfo) arrival timestamps.
2. **Bus pairing**: headways should bifurcate into a near-zero cluster (buses nearly touching) and a large-gap cluster — check the actual distribution, not just a single summary statistic.
3. **The dwell-load correlation itself**: dwell time vs. passengers boarded+alighted should show a strong positive (near-linear, given a constant `boardingDuration`) correlation, directly confirming the causal mechanism rather than just its downstream symptom.

## Forward-headway-only holding controller

At each stop arrival, compute the bus's headway to the preceding bus at that same stop. **If the headway is below a target even value, the bus is early — hold it** (extend its dwell via `traci.vehicle.setBusStop(vid, stop_id, duration=hold_seconds)`) until the target is restored, capped at a maximum hold. **If the bus is on-time or late, release it immediately — never hold a late bus** (holding a late bus would make bunching worse, not better). Log every arrival's headway, early/late classification, and hold decision to a CSV so the controller's correctness is independently auditable, not just asserted.

See `scripts/holding_controller.py` for the full working implementation and `scripts/analyze_bunching.py` for the headway/CV recomputation from raw stop-output.

## Verified findings

On a real 12-edge loop with 6 buses and stochastic passenger demand: an uncontrolled baseline showed headway CV growing from an even start to a pooled value over 1.0, with roughly 18% of headways falling into a "paired" near-zero cluster alongside gaps 50x larger, directly traceable to a near-perfectly linear dwell-vs-load correlation. A forward-headway-only holding controller reduced pooled headway CV by roughly 20%, **eliminated pairing entirely**, and cut mean passenger wait time by about a third — at a real, quantified dwell-time cost (roughly 35% more mean dwell). Because the controller structurally cannot speed up a late bus, one residual large gap persisted even under control — a genuine, disclosed limitation of forward-only holding, not a defect.

## Gotchas

- **A route's `repeat` attribute doesn't repeat `<stop>` children** — write out stops explicitly per lap.
- **Confirm bunching genuinely emerges in the baseline before building the controller** — don't assume the phenomenon; verify it, and tune parameters if it doesn't appear.
- **Never hold a late bus** — only early buses should be held; holding a late bus compounds the instability rather than fixing it.
- **Log every hold/release decision** — this is the only way to verify the controller's early-only behavior rather than asserting it.
- **A finite `personCapacity` matters for recovery dynamics** — an unlimited-capacity bus can absorb unbounded crowds, changing how holding interacts with the feedback loop. This has now been measured, and it is stronger than "matters" — see below.
- **An exactly periodic dispatch makes headway amplification unmeasurable.** A perfectly regular terminal departure enters the line with CV 0, so any along-the-line amplification ratio divides by ~0. Inject seed-controlled terminal jitter (sd ≈ 0.12 × headway), shared across arms as a common random number, if you want to compare how fast CV grows rather than just its pooled level.

## A binding capacity truncates this feedback loop — and flips the controller's sign

Measured on a 10-stop corridor (`model-capacity-constrained-transit-passenger-loading`,
[[transit-capacity-passenger-loading-and-pass-up-dynamics]]). Everything above assumes the bus can always take the crowd it meets. Once `personCapacity` actually binds, a bus arriving full boards nobody, so the dwell-vs-load slope that drives bunching **collapses**: +1.005 s/pax non-binding (and +1.995 — exactly the configured `boardingDuration` — restricted to crowds of 10–20) versus **−0.033 s/pax binding**, and −0.190 for buses that arrive full.

The trap: from an identical dispatch perturbation, headway CV amplifies **×2.25** along the line when capacity is non-binding but only **×1.20** when it binds (pooled 0.338 vs 0.219, zero paired buses under binding capacity). **The capacity-constrained line looks 35% more regular while total passenger time is 80% worse** (122.6 vs 67.9 pax-h, mean wait 518 vs 167 s). Never report a headway-CV improvement as a service result without checking whether capacity binds.

And the holding controller's benefit flips sign for passengers:

| | headway CV | mean wait | pass-ups/pax | total pax time |
|---|---|---|---|---|
| non-binding + holding | 0.338 → 0.132 (−60.8%) | 166.5 → 156.6 (**−6.0%**) | 0 → 0 | −0.7% n.s. |
| binding + holding | 0.219 → 0.113 (−48.4%) | 518.5 → 537.6 (**+3.7%**) | 1.215 → 1.267 (**+4.3%**) | **+3.8%** |

Holding still delivers regularity under a binding capacity, but every passenger metric moves the wrong way — the held bus arrives at the next stop to a crowd it cannot take, converting headway variance into refused boardings. Under a binding capacity this controller is a regularity intervention paid for by passengers, and should be reported as such.

## Related

- `simulate-multimodal-transit` — the busStop/bus-line/person-demand authoring patterns this skill's network and demand construction directly reuse.
- `simulate-taxi-and-drt-dispatch` — a structurally analogous TraCI fleet-control pattern, for on-demand rather than fixed-route service.
- `implement-emergency-vehicle-preemption` — a similarly-structured TraCI controller with careful event logging and a clean before/after comparison design.
- `model-capacity-constrained-transit-passenger-loading` — what happens once `personCapacity` binds: pass-up reconstruction (SUMO has no pass-up observable), the truncated feedback loop above, and the frequency-vs-vehicle-size decision.
- [[bus-bunching-and-forward-headway-holding]] — the underlying feedback mechanics and the verified bunching/holding-control findings.
- [[transit-capacity-passenger-loading-and-pass-up-dynamics]] — the capacity-binding semantics and measured consequences.
