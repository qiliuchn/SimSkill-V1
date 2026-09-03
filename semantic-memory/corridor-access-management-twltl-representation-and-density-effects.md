---
summary: SUMO has no native primitive for a continuous two-way left-turn lane (TWLTL) — only a discretized per-driveway pocket design (absorbed into junction geometry, not a continuous open edge) compiles and verifies safe via FCD, behaving as a single-vehicle refuge rather than a multi-car queue lane; on a controlled corridor with total demand held fixed across access-point densities, through-vs-access delay decomposition shows TWLTL's ranking against undivided flips with density even though its access-travel-time and conflict-rate advantage holds throughout, SSM conflict rate per Mvkm falls (not rises) as density increases under fixed total demand, a raised median never recovers its detour VMT as a net VHT win at any tested density, and driveway consolidation recovers delay but increases conflict rate.
keywords:
  - access-management
  - TWLTL
  - two-way-left-turn-lane
  - driveway-density
  - median-treatment
  - raised-median
  - driveway-consolidation
  - corridor-access-spacing
created: 2026-08-06T23:54:30
last_updated: 2026-08-06T23:54:30
sources:
  - "[[episodic-memory/2026-08-06_23-50-09/attempts/attempt-1/action-agent-output.md]]"
  - "[[episodic-memory/2026-08-06_23-50-09/attempts/attempt-1/critic-agent-feedback.md]]"
related_pages:
  - "[[one-lane-two-way-alternating-flow-and-shared-lane-representation]]"
  - "[[rcut-and-michigan-left-alternative-intersection-design]]"
  - "[[left-turn-storage-bay-length-design]]"
  - "[[surrogate-safety-measures]]"
  - "[[mutcd-signal-warrants-and-the-demand-vs-served-volume-trap]]"
related_skills:
  - evaluate-corridor-access-management-and-median-treatments
  - control-one-lane-two-way-alternating-flow-through-a-work-zone
  - design-restricted-crossing-uturn-and-michigan-left-intersections
  - design-left-turn-storage-bay-length
  - analyze-intersection-safety-with-ssm
  - conduct-driveway-signal-warrant-traffic-impact-analysis
related_skills_for_graph_view:
  - "[[evaluate-corridor-access-management-and-median-treatments]]"
  - "[[control-one-lane-two-way-alternating-flow-through-a-work-zone]]"
  - "[[design-restricted-crossing-uturn-and-michigan-left-intersections]]"
  - "[[design-left-turn-storage-bay-length]]"
  - "[[analyze-intersection-safety-with-ssm]]"
  - "[[conduct-driveway-signal-warrant-traffic-impact-analysis]]"
---

# Corridor Access Management: TWLTL Representation and Density Effects

Access management — how driveway/curb-cut density and median treatment jointly govern the mobility-vs-access tradeoff on a suburban arterial — had no coverage in memory beyond single-driveway (`conduct-driveway-signal-warrant-traffic-impact-analysis`) and single-junction (`design-restricted-crossing-uturn-and-michigan-left-intersections`) scales. This page holds the corridor-scale findings, verified on a controlled 3 km, 3-signal arterial with three median variants (undivided / TWLTL / raised median with U-turn crossovers) sharing one geometry, swept across four access-point densities with total corridor demand held fixed. See `evaluate-corridor-access-management-and-median-treatments` for the full methodology.

## SUMO has no TWLTL primitive — only a discretized pocket design works

A two-way left-turn lane is a continuous median refuge entered midblock from both directions — SUMO has no built-in way to express this. Three candidate encodings were tested:

1. **Continuous coincident opposite-direction edges** spanning the block (the natural first attempt): compiles, but is an *open edge* with no junction arbitrating access to it. Verified via FCD — never trust `--collision-output` for a shared-lane encoding, per `[[one-lane-two-way-alternating-flow-and-shared-lane-representation]]` — that opposing vehicles genuinely occupy overlapping physical space (true separation as negative as −3.5 m once vehicle length is subtracted) while `--collision-output` reports zero collisions both times. **Structurally unsafe; rejected.**
2. **A single one-directional lane** with connections attempted from both ends: doesn't even compile (topologically invalid — a one-directional edge has no legal far-end entry point). **Rejected.**
3. **A discretized chain of short per-driveway pockets**, same coincident-edge mechanism as (1) but not stitched into a continuous span: compiles cleanly and verifies genuinely safe via an adversarial synced-arrival FCD test (zero simultaneous coincident-lane occupancy across every tested pocket). The reason it works where (1) doesn't: the pocket is short enough that `netconvert` absorbs it entirely into the junction-interior geometry, so ordinary junction foe/priority arbitration governs access — the same mechanism that *does* feed the collision checker. **Chosen.**

**The chosen encoding's real limits, essential to state with any result built on it:**
- Not continuous — no median-running between non-adjacent driveways, only entry/exit at a vehicle's own driveway pocket.
- **Near-zero real storage regardless of authored length.** A pocket authored up to 19 m compiled to 0.13–0.80 m (netconvert absorbs it into the junction polygon almost entirely, shrinking further as driveways get closer together) — this makes it a single-vehicle-at-a-time refuge, not a multi-car queue lane. Any claim about TWLTL performance under high *per-driveway* left-turn volume is outside what this encoding tests.
- Right-in/right-out needs its own explicit connection into the pocket — a first build that wired only the left turn didn't error, it silently sent right-turn trips on a multi-kilometer detour via `duarouter`'s ordinary rerouting (no warning). The fix shares the pocket lane between left- and right-turners, a further disclosed compromise versus a real right-in/out's independence from the median.

## Through-vs-access decomposition: TWLTL's ranking against undivided flips with density

Reporting only a pooled corridor-wide delay mean hides the actual tradeoff. Verified: TWLTL beat undivided on access-vehicle travel time and (mostly) conflict rate **at every tested density** — but on through-corridor delay, TWLTL was statistically tied with undivided at low access density and measurably *worse* at moderate-to-high density. The direction of "is TWLTL worth it" depends on which population (through vs. access traffic) and which density regime you're asking about — a single blended number would have reported a misleadingly consistent answer.

## Access density and safety: conflict rate fell, not rose, under fixed total demand

Access-management literature associates rising crash rate with rising access-point density. Verified in SUMO, holding total corridor demand fixed while spreading it over more driveways: SSM conflict rate **per million vehicle-km fell** as density rose, consistently in sign across every median variant and turn-movement category (not always individually significant). Two explanations were left explicitly open rather than resolved in favor of either: a genuine effect of thinner per-driveway volume under a fixed-total-demand design reducing SSM's proximity-based encounter counting; or an artifact of SSM's TTC/PET/DRAC machinery being blind to driver scanning/distraction burden from frequent curb cuts, which the real-world crash-density relationship may partly reflect. **This is a genuine methodological caveat for anyone using SUMO SSM conflict rates as a stand-in for access-density crash risk — the sign can come out opposite the field literature under this experimental design, and it isn't yet clear whether that's real or an artifact of what the safety-surrogate device can see.**

## Raised median: detour VMT never converts to a VHT win

A raised median's directional U-turn crossovers (reusing `[[rcut-and-michigan-left-alternative-intersection-design]]`'s mechanics, generalized corridor-wide) reliably increase VMT (the detour cost) at every density — but that extra distance never converted into a net VHT (time) saving anywhere in the tested [5, 45] driveways/km range; raised median had higher total VHT than TWLTL at every density tested, with the gap essentially unchanged from low to high density. A raised median's justification in this study's own evidence has to rest on something other than the corridor-time metrics measured here (e.g. an asserted crash-severity benefit not tested by this study).

## Driveway consolidation recovers delay but raises conflict rate

Consolidating several low-volume driveways into fewer, higher-volume access points (same total demand) substantially recovered through-corridor delay — back to roughly the lowest-tested-density level. But conflict rate per Mvkm **increased** materially (+22% to +36%) after consolidation, consistently across every replication seed, despite near-identical trip counts/VMT/spacing to the comparison baseline. This was left as a disclosed, unresolved finding rather than explained away — a delay-improving access-management remedy is not automatically a safety-improving one, and the two metrics should be checked independently rather than assumed to move together.
