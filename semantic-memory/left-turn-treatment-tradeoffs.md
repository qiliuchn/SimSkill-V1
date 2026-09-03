---
summary: Permissive, protected, and protected-permissive left-turn signal treatments trade safety against efficiency in SUMO, but not always in the textbook "protected-permissive sits neatly between" pattern; verified on a dedicated-left-turn-lane intersection that protected-only can have the HIGHEST overall delay of the three (a full protected phase's capacity cost outweighing its benefit at moderate left-turn volume), while protected-permissive was the BEST on both overall delay and left-turn wait, not merely intermediate — even as the expected safety ordering (protected safest, permissive least safe) held cleanly.
keywords:
  - left-turn-treatment
  - permissive-left-turn
  - protected-left-turn
  - protected-permissive
  - turn-pocket
created: 2026-07-29T09:45:00
last_updated: 2026-08-04T19:00:00
sources:
  - "[[episodic-memory/2026-07-29_09-24-33/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-29_09-24-33/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[surrogate-safety-measures]]"
  - "[[pedestrian-crossings-and-signal-phasing]]"
  - "[[unsignalized-vs-signalized-intersection-control]]"
  - "[[diverging-diamond-interchange-unopposed-lefts]]"
  - "[[left-turn-storage-bay-length-design]]"
  - "[[rcut-and-michigan-left-alternative-intersection-design]]"
  - "[[right-turn-on-red-and-leading-pedestrian-interval]]"
  - "[[network-safety-screening-and-crash-prediction]]"
related_skills:
  - compare-left-turn-signal-treatments
  - analyze-intersection-safety-with-ssm
  - create-single-intersection
  - design-left-turn-storage-bay-length
  - design-restricted-crossing-uturn-and-michigan-left-intersections
related_skills_for_graph_view:
  - "[[compare-left-turn-signal-treatments]]"
  - "[[analyze-intersection-safety-with-ssm]]"
  - "[[create-single-intersection]]"
  - "[[design-left-turn-storage-bay-length]]"
  - "[[design-restricted-crossing-uturn-and-michigan-left-intersections]]"
---

# Left-Turn Treatment Tradeoffs

SUMO can model three standard left-turn signal-control treatments at a dedicated-left-turn-lane intersection: **permissive** (left-turners share the through green, must yield to oncoming through traffic — the left-turn link carries a lowercase `g`), **protected** (an exclusive leading arrow phase, `G`, with no permissive turning allowed at any other time), and **protected-permissive** (a leading protected arrow phase followed by a permissive fill-in period during the through-green, using both `G` and `g` for the same link across different phases).

## Safety ordering matches textbook expectations

Verified on a genuine 4-approach intersection with heavy (38.5%) left-turn demand, using SSM conflicts filtered specifically to left-turn-vs-oncoming-through movement pairs: protected-only nearly eliminated dangerous conflicts, permissive-only was the most conflict-prone with genuine near-misses (worst TTC 0.46s), and protected-permissive fell cleanly in between (216 conflicts vs. 334 permissive / 46 protected) — though it still contained dangerous permissive-period encounters (worst TTC 0.25s, even lower than permissive-only's, since the permissive-period near-misses in protected-permissive occur against a smaller remaining gap-acceptance window).

## Efficiency ordering does NOT always match textbook expectations

**The common heuristic that protected-permissive's efficiency sits between permissive (most efficient) and protected (least efficient) is not universally true.** Verified directly: protected-only had the *highest* overall intersection delay of all three treatments in a scenario where left-turn demand (250 veh/h, 38.5% of its approach) did not fully justify the capacity cost of a dedicated leading phase — the exclusive left phase steals green time from through movements without providing enough throughput benefit to offset it. Protected-permissive, meanwhile, was the *best* treatment on both overall delay and left-turn wait — not merely intermediate — because left-turners benefited from both a protected head-start and a permissive fill-in opportunity, extracting efficiency from both mechanisms simultaneously, while permissive-only left-turners paid the highest wait cost from yielding to sustained heavy oncoming traffic.

**Practical implication**: don't apply the permissive/protected/protected-permissive efficiency heuristic uncritically — verify a specific demand level's actual capacity-cost tradeoff via simulation, since a full protected phase can be a net efficiency loss (not just a safety gain) when left-turn volume doesn't justify its dedicated green time.

## Robust state-string generation prevents a subtle class of bug

Hand-typing three separate `tlLogic` state strings for three treatments — each requiring precise `G`/`g`/`r` placement at the same left-turn link index across different phases — is genuinely error-prone; a single mistyped case silently invalidates the entire comparison without SUMO raising any error (a lowercase `g` where `G` was intended just yields more than the modeler intended, with no crash or warning). **Generate state strings programmatically from the compiled network's own `linkIndex`/`dir` connection attributes** rather than hand-authoring them, and print an annotated per-phase table before running to visually confirm the intended pattern.

See the `compare-left-turn-signal-treatments` skill for the full network, program-generation, and verification workflow.
