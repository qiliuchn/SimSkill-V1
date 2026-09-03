---
name: design-left-turn-storage-bay-length
description: Use this skill when the user wants to treat left-turn storage bay length as a design variable in SUMO — determining critical bay length, whether signal retiming or actuated control can compensate for an undersized bay, and how a standard design rule of thumb compares against measured behavior — as opposed to compare-left-turn-signal-treatments, which uses a fixed-length bay purely as scaffolding for comparing signal phasing. Covers compiled-bay-length calibration (netconvert shortens edges by junction geometry), instrumenting bay overflow and bay blockage/starvation as two SEPARATE failure modes with independent FCD cross-validation, distinguishing throughput-based from delay-based critical bay length, and comparing signal retiming against actuated control as compensation strategies. Trigger on mentions of left-turn bay, turn pocket length, storage length, bay overflow, bay blockage, or left-turn queue spillback.
related_skills:
  - compare-left-turn-signal-treatments
  - create-single-intersection
  - quantify-sumo-run-to-run-variability
  - validate-congested-scenario-results-against-teleport-artifacts
  - design-restricted-crossing-uturn-and-michigan-left-intersections
related_skills_for_graph_view:
  - "[[compare-left-turn-signal-treatments]]"
  - "[[create-single-intersection]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[validate-congested-scenario-results-against-teleport-artifacts]]"
  - "[[design-restricted-crossing-uturn-and-michigan-left-intersections]]"
related_pages:
  - "[[left-turn-storage-bay-length-design]]"
---

# Design Left-Turn Storage Bay Length

Treats left-turn storage bay length as a measurable geometric design variable in SUMO — the interaction between network geometry and signal control that `compare-left-turn-signal-treatments` never studies (that skill uses a fixed-length bay purely as scaffolding for comparing signal phasing treatments).

## Compiled bay length differs from authored length — calibrate iteratively

**`netconvert` shortens edges based on junction geometry, so a naively-authored bay length can undershoot the intended value substantially.** Verified case: a nominal 50m bay compiled to only 35.6m of real storage — a 29% error, large enough to invalidate a bay-length sweep if not corrected. Build an iterative calibration loop: compile, measure the actual bay length from the compiled network's lane geometry, adjust the source node/edge coordinates to compensate, recompile, repeat until the compiled length matches the intended value within a small tolerance (e.g. 0.15m). Also verify the upstream (through-only) section plus the bay section sum to a constant total approach length across every bay-length variant, so only the bay/through split changes between conditions, not total approach length.

## Verify lane isolation — don't assume the geometry works as intended

Verify, from **both** the compiled network's connection structure (the left movement's controlled link sourced only from the bay lane) **and** actual vehicle trace data (every left-turning vehicle's lane occupancy over its full trip), that left-turners genuinely use only the bay lane and through/right vehicles genuinely use only the through lane(s) — zero cross-contamination in either direction. This is the single most safety-critical verification for this kind of study: if vehicles can leak between lanes, the failure-mode measurements (which depend on which lane a vehicle occupies) are meaningless. Use vehicle subscriptions or position queries scoped to the specific approach under study, not intersection-wide, for tractable per-second instrumentation across a large sweep.

## Instrument two failure modes separately, and cross-validate independently

1. **Bay overflow**: a left-turning vehicle stopped in the upstream through-only section because the bay itself is full — it physically cannot fit in the dedicated lane and blocks through traffic instead.
2. **Bay blockage / starvation**: a through queue extending past the bay's entrance point, physically preventing left-turners from reaching the bay even while the protected left-turn phase is green — wasted protected green time.

Measure both as event/duration rates from live TraCI vehicle-position tracking (per-second polling of lane occupancy near the bay entrance and within the bay). **Independently cross-validate the live measurement against an offline re-derivation from raw FCD trajectory output** for at least one representative run — verified case: the two independent measurement paths agreed almost exactly (two metrics matched exactly, two others within ~1%), which is strong evidence the instrumentation is measuring the intended physical phenomena, not an artifact of the live-tracking method.

## Distinguish throughput-based from delay-based critical bay length — they can differ substantially

**"Critical bay length" is not a single number — it depends on which metric is used as the failure criterion, and the two can differ by a large factor.** Verified case: the throughput-preserving critical bay length was roughly 12-64m (depending on left-turn share), while the delay-preserving critical bay length was 50m to over 150m for the same left-turn shares — a bay long enough to preserve nearly all achievable throughput can still impose large, unrecovered delay. Report both criteria explicitly rather than a single "the critical bay length is X" figure.

## Verified finding: signal retiming cannot compensate for a geometric deficiency

**Reallocating green time (adjusting the left-turn phase split within a fixed-time plan) recovered essentially none of the throughput lost to an undersized bay** — 0% recovery in the large majority of tested (bay-length, left-share) conditions, with only one minor exception. This is a strong, general lesson: a bay-length shortfall is a *capacity* problem, and capacity problems from finite storage cannot be fixed by rearranging how the finite capacity's own green time is split — the bottleneck is downstream of the signal timing, in the physical space itself.

## Verified finding: actuated control can help substantially, or backfire badly, depending on bay length

**Switching from fixed-time to actuated control recovered a meaningful fraction (roughly 40-110%) of the throughput lost to an undersized bay in most tested conditions** — unlike signal retiming, actuation can genuinely help, because it reallocates green time dynamically in response to real demand rather than a fixed a priori split. **But at the shortest tested bay lengths, actuated control was found to be substantially *worse* than fixed-time** (over 2x worse in one verified case) — the mechanism: too short a bay fails to keep the actuated detector's presence signal continuously active, so the controller's gap-out logic ends the protected left phase prematurely, even though real left-turn demand is still present and unable to reach the (already-full) bay. **Don't assume actuated control is a safe universal upgrade over fixed-time for an undersized bay** — verify its effect at the specific bay length in question, since the direction of the effect can reverse at short lengths.

## Verified finding: a standard design rule can be simultaneously conservative and unsafe, on different metrics

Checking a standard bay-length design rule of thumb (based on expected left-turn arrivals per signal cycle) against measured behavior found it **conservative for throughput** (a bay built to the rule's recommended length preserved nearly all achievable throughput, using substantially more length than the measured throughput-critical minimum) but **not conservative for delay** (the same rule-length bay still imposed substantial excess left-turn delay and left a meaningful fraction of the protected green time wasted to blockage). **A design rule validated against one failure criterion is not automatically safe against a different failure criterion** — verify a rule of thumb against the specific outcome that matters for the application (throughput vs. delay vs. safety), not just the criterion the rule happens to have been derived from.

## Verified mechanism: the design rule misses through-queue spillback, not just left-turn volume

The standard design rule sizes the bay purely from expected left-turn arrival volume. **Verified finding: the actual delay-based failure mode is driven substantially by the THROUGH movement's own queue length, not the left-turn queue** — measured 95th-percentile through-queue length was several times longer than the measured 95th-percentile left-turn queue length in the same conditions, and the delay-based critical bay length tracked the through-queue length far more closely than the left-turn arrival-based rule would predict. **A bay sized only against its own movement's arrival volume can still starve its own protected phase, if an unrelated through-queue extends past the bay entrance** — this is a genuine blind spot in a purely-volume-based design rule.

## Verified finding: the two failure modes trade off non-trivially along the bay-length axis

Overflow (bay too full to hold left-turners) decays monotonically as bay length increases, as expected. **Blockage/starvation (through queue preventing bay access) is non-monotone** — it can *increase* then *decrease* as bay length grows, peaking at an intermediate length rather than falling throughout the swept range. This means simply lengthening a bay is not guaranteed to monotonically reduce every failure mode — check the specific mode's shape across the full range rather than assuming a longer bay is always strictly better on every measure.

## Verified finding: which movement bears the aggregate delay cost flips with left-turn share

Per individual vehicle, the left-turn movement always suffers more delay from an undersized bay than the through movement does. **But weighted by total volume (aggregate vehicle-hours of excess delay), the answer inverts at low left-turn shares**: the uninvolved through movement — which never turns left and experiences the bay-induced delay purely as collateral blockage — can bear the majority of the network's *total* excess delay when left-turn share is low, simply because there are far more through vehicles. At high left-turn shares, the left movement itself bears the majority. **"Who is hurt most" depends on whether the question is asked per-vehicle or in aggregate, and the aggregate answer depends on the traffic mix, not just the bay geometry.**

## Gotchas

- **A naively-authored bay length can be substantially shorter than intended once compiled** — always verify and iteratively calibrate against the compiled network's actual geometry, not the source XML's stated length.
- **Verify lane isolation from both compiled-network structure and actual vehicle traces** — don't assume a dedicated-lane connection guarantees zero cross-lane leakage in practice.
- **At very short bay lengths, a large fraction of demand may never be inserted into the network at all** (an insertion backlog, not stalled in-network vehicles) — this can make delay-mean statistics severely optimistic for that condition (since the worst-affected vehicles never entered to be measured) while throughput and never-inserted counts remain trustworthy; report both and don't rely on the compromised delay means at the shortest tested lengths.
- **Signal retiming does not fix a geometric bay-length deficiency** — don't expect a green-split adjustment to substitute for adequate storage length.
- **Actuated control can be dramatically worse than fixed-time at very short bay lengths**, via a detector-starvation/early-gap-out mechanism — verify its effect at the specific bay length rather than assuming actuation is always at least as good as fixed-time.
- **A design rule's own validation criterion may not match the criterion that actually matters** — a rule conservative for throughput can be unsafe for delay, or vice versa; check both.
- **Blockage/starvation can be non-monotone in bay length** — don't assume every failure mode strictly improves as a bay gets longer.

## Related

- `compare-left-turn-signal-treatments` — the dedicated left-turn lane geometry and programmatic-tlLogic-generation technique this skill extends with variable bay length and dual failure-mode instrumentation.
- `create-single-intersection` — the base plain-XML+netconvert network-building technique this skill's bay-length variants are built from.
- `quantify-sumo-run-to-run-variability` — the replication/CI methodology this skill's bay-length sweep applies.
- `validate-congested-scenario-results-against-teleport-artifacts` — the teleport-artifact validity methodology this skill applies, given that undersized-bay conditions approach near-gridlock.
- [[left-turn-storage-bay-length-design]] — the verified retiming/actuation-compensation findings, the criterion-dependent critical-length finding, the design-rule verdict, the through-queue mechanism, and the movement-burden-flip finding.
- `design-restricted-crossing-uturn-and-michigan-left-intersections` — extends this skill's overflow-vs-blockage/spillback bottleneck-instrumentation pattern to a third failure mode (yield-gap starvation) at an unsignalized median U-turn crossover.
