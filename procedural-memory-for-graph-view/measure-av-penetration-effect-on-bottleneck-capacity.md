---
name: measure-av-penetration-effect-on-bottleneck-capacity
description: Use this skill when the user wants to measure how connected/automated-vehicle (CAV) market penetration affects freeway bottleneck capacity in SUMO, and — critically — whether any measured benefit comes from the ACC/CACC car-following model structure itself or merely from a shorter assumed reaction time. Covers building a mechanism-isolating "gap-matched Krauss" negative control, an isolated two-vehicle probe for measuring a car-following model's actual effective time gap and leader-awareness, a penetration sweep with a real (not eyeballed) linear/quadratic curve-shape fit, an arrangement-effect test (random vs. platooned AV placement) with directly-measured leader-is-AV fractions, and the departSpeed insertion-capacity trap. Trigger on mentions of AV market penetration, mixed autonomy, connected vehicle penetration rate, ACC/CACC capacity, or "does automation increase freeway capacity."
related_skills:
  - demonstrate-and-stabilize-phantom-traffic-jams
  - form-platoons-with-simpla
  - compare-zipper-vs-default-merge-at-lane-drop
  - quantify-sumo-run-to-run-variability
related_skills_for_graph_view:
  - "[[demonstrate-and-stabilize-phantom-traffic-jams]]"
  - "[[form-platoons-with-simpla]]"
  - "[[compare-zipper-vs-default-merge-at-lane-drop]]"
  - "[[quantify-sumo-run-to-run-variability]]"
related_pages:
  - "[[av-penetration-and-carfollowing-model-mechanism]]"
---

# Measure AV Penetration's Effect on Bottleneck Capacity

Measures how bottleneck capacity changes as automated/connected vehicles (ACC/CACC) replace human drivers in SUMO — and, critically, decomposes any measured effect into "shorter reaction time" vs. "car-following model structure," a distinction the naive HUMAN-vs-ACC-vs-CACC comparison conflates. This is memory's first mixed-autonomy market-penetration study — `demonstrate-and-stabilize-phantom-traffic-jams` uses exactly one AV on a bottleneck-free ring, and `form-platoons-with-simpla` forms CACC platoons but never measures a capacity-vs-penetration curve.

## The essential mechanism control: gap-matched Krauss

**Never compare HUMAN vs. ACC/CACC alone.** Any observed difference conflates two independent things: the shorter time gap (`tau`) typically configured for automated vehicles, and whatever the ACC/CACC car-following model itself does differently from ordinary Krauss/IDM car-following. Add a **negative/mechanism control vType**: plain Krauss, `sigma=0` (removing driver imperfection), with `tau` set to *exactly* the AV fleet's own configured time gap. This isolates "what does a shorter reaction time alone buy" from "what does the ACC/CACC model structure additionally buy or cost."

**Verified finding this control can invert the naive conclusion**: in one test, this gap-matched Krauss control achieved dramatically *higher* bottleneck discharge than SUMO's own ACC model at the identical time gap, and far higher than CACC at the identical time gap (which fell *below* the human baseline). A study that only compared HUMAN vs. ACC vs. CACC would have concluded "ACC gives a small gain, CACC is harmful" — the mechanism-isolated conclusion was instead "the shorter headway alone is worth a large gain, and the ACC/CACC model structures give back most of it." Always include this control; it is not a footnote, it can change what the entire study means.

## Verifying the control is genuinely gap-matched, not just relabeled

Run an isolated two-vehicle probe (leader + one follower, single lane, `speedFactor` pinned to exactly 1.0 to remove speed-factor noise) and measure the follower's realized steady-state gap/time-headway directly from FCD. Confirm the gap-matched control and the AV model converge to the same effective `tau` behind an identical leader before trusting any comparison between them.

## The same probe reveals whether a cooperative model actually cooperates

**Verified, decisive finding**: run the probe with the SAME follower vType (e.g. two different CACC configurations with different configured `tau`) behind (a) their own type as leader and (b) a plain human-model leader. In one verified test, CACC configurations with genuinely different `tau` (e.g. 0.9s vs. 0.6s) converged to *nearly identical* gaps behind a **non-CACC** leader — both settling to a hard-coded fallback headway (~1.0s) that ignored their own configured `tau` entirely — while honoring their own `tau` exactly when following their own type. **This means a cooperative car-following model can silently degrade to something *worse* than a simpler, leader-agnostic model (like ACC, which stayed at its own configured `tau` regardless of leader type) in exactly the mixed-traffic conditions a market-penetration study cares about.** Never assume a "cooperative" model's advertised parameters apply uniformly — verify its actual behavior behind a foreign leader type, since SUMO's C-ACC/ACC implementations can have leader-awareness fallbacks not obvious from configuration alone.

## The `departSpeed` insertion-capacity trap

**Verify entry capacity is not itself the bottleneck before attributing a discharge result to the intended lane-drop/merge bottleneck.** ACC/CACC models can demand an unusually large insertion gap when a vehicle enters at a speed differing from its leader's — `departSpeed="desired"` was observed in one case to cap an ACC fleet's network-entry capacity *below* its own downstream bottleneck capacity, making entry (not the intended bottleneck) the binding constraint and producing a spurious "ACC is worse than human" result purely from an insertion artifact. `departSpeed="last"` (match the vehicle ahead's actual speed) fixed this. **Always build a no-bottleneck control network (same entry/vType setup, but no lane drop) and confirm it never queues under the study's demand** — this positively proves the intended bottleneck, not network entry, is what's actually being measured.

## Penetration sweep: fit the curve shape, don't eyeball it

Sweep AV market share across several levels (a real fit needs at least 5-6 points), assign vehicle types stochastically per vehicle (e.g. `vTypeDistribution`, or an equivalent nested-random-draw scheme giving Common Random Numbers across adjacent penetration levels — verify the two approaches agree, e.g. by cross-checking explicit per-vehicle assignment against `vTypeDistribution`'s own sampling at one penetration level). Fit both a linear and quadratic model to capacity-vs-penetration and use an F-test to determine whether the quadratic term is actually justified — **don't assert convexity/concavity from a plotted curve's apparent shape**. Report per-arm curve quality (adjusted R², RMSE) since different car-following models can have very different curve shapes on the identical network (verified case: one arm was essentially perfectly linear, another was non-monotone and poorly fit by either polynomial degree — the mixing dynamics genuinely differ by model, not just by degree of benefit).

## Arrangement effect: measure the leader-is-AV fraction directly, don't assume p²

To separate "how many AVs" from "how they're arranged," compare random AV placement against deliberately clustered/platooned placement of the *identical* AV count and demand. Measure the realized fraction of AV vehicles whose immediate leader is also an AV directly from FCD/TraCI leader queries — **do not assume this fraction is `p²`** (the naive independence assumption). Verified finding: the naive `p²` model can understate the true leader-AV fraction by many times (e.g. an 8x understatement at low penetration in one test), because AVs are not uniformly distributed through the network (they concentrate differently in congested vs. free-flow zones) and can exhibit mild genuine self-clustering from car-following dynamics alone. Also verified: a substantially higher realized leader-AV fraction from platooning does not guarantee a proportional capacity benefit — in one test it raised the leader-AV fraction by ~20 percentage points but changed capacity by at most ~1%, mostly not statistically distinguishable from zero — a clean negative result worth reporting rather than assuming platooning must help.

## Statistical rigor and honest disclosure

Apply `quantify-sumo-run-to-run-variability`'s replication methodology: multiple seeds per cell, Common Random Numbers where feasible (verify it actually reduces variance — it can fail to help for some vTypes/metrics), empirical warm-up detection before measuring sustained discharge (a scenario driven into oversaturation may have no true stationary regime at all — say so rather than forcing a warm-up estimate), and report which adjacent-penetration-level differences are and aren't statistically distinguishable rather than treating every point estimate as meaningful.

**If a car-following model configuration produces real vehicle-vehicle collisions in SUMO** (a genuine possibility for ACC/CACC at aggressive parameters, even at the documented-minimum step length), **disclose this prominently in the headline/summary, not buried in a limitations section** — a collision-producing configuration's capacity numbers describe a physically-invalid scenario, and burying this caveat risks a reader trusting a number that shouldn't be trusted at face value. Check whether collision count correlates with the reported metric (if it doesn't, the metric isn't being mechanically inflated by the invalid collisions, which is worth stating explicitly) but still flag the affected arm's results as provisional.

## Gotchas

- **Never compare HUMAN vs. ACC/CACC without a gap-matched Krauss mechanism control** — the naive comparison conflates reaction-time effects with model-structure effects and can produce an inverted conclusion.
- **A cooperative car-following model can silently ignore its own configured parameters behind a foreign (non-cooperative) leader type** — verify actual leader-aware behavior via an isolated probe, don't trust the configuration.
- **`departSpeed="desired"` can make network entry, not the intended bottleneck, the binding constraint for ACC/CACC fleets** — use `departSpeed="last"` and verify with a no-bottleneck control network.
- **Small step-length (0.1s) is SUMO's documented requirement for ACC/CACC** — but even at that step length, aggressive ACC/CACC parameter combinations can still produce real collisions; verify collision counts per arm and disclose prominently if nonzero.
- **Don't assume the leader-is-AV fraction is `p²`** — measure it directly; spatial non-uniformity and self-clustering can make the true fraction many times higher than the naive independence assumption at low penetration.
- **Don't assert a capacity-vs-penetration curve's shape (linear/convex/concave) from a plotted line** — fit polynomial models and use an F-test to justify the claimed shape.
- **When labeling a spot-check table with fewer replications than the main analysis (e.g. a single-seed sanity check), say so explicitly** — presenting single-seed and multi-seed numbers under the same unlabeled heading can create an internal inconsistency that undermines trust in an otherwise solid report.

## Related

- `demonstrate-and-stabilize-phantom-traffic-jams` — a different, bottleneck-free (ring) topology studying a single AV's effect on emergent instability; shares the "verify from raw FCD, don't trust configuration" discipline.
- `form-platoons-with-simpla` — the `simpla` platoon-formation mechanic; this skill's arrangement-effect test can use either `simpla` or a simpler block-departure scheme to achieve clustered AV placement.
- `compare-zipper-vs-default-merge-at-lane-drop` — the lane-drop bottleneck construction and oversaturation-verification discipline this skill's network is built on.
- `quantify-sumo-run-to-run-variability` — the replication/CRN/warm-up methodology this skill's statistical analysis applies.
- [[av-penetration-and-carfollowing-model-mechanism]] — the verified gap-matched-control, leader-awareness-fallback, curve-shape, and arrangement-effect findings, plus the honest ACC-collision caveat.
