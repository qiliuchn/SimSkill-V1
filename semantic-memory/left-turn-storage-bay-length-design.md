---
summary: Treating left-turn storage bay length as a design variable in SUMO found that signal retiming recovers essentially none of an undersized bay's throughput loss (0% in 20 of 21 tested cells), while actuated control can recover 40-110% of the loss but can be dramatically worse than fixed-time (2x+ worse in one case) at very short bay lengths via a detector-starvation mechanism; critical bay length is criterion-dependent (throughput-based and delay-based thresholds differ substantially), a standard design rule of thumb was found simultaneously conservative for capacity but unsafe for delay because it misses through-queue spillback (not left-turn volume) as the actual delay-driving mechanism, the two failure modes (overflow, blockage) trade off non-monotonically along the bay-length axis, and which movement bears the aggregate delay cost flips with left-turn demand share.
keywords:
  - left-turn-bay
  - storage-length
  - bay-overflow
  - bay-blockage
  - turn-pocket-design
  - queue-spillback
created: 2026-08-01T06:20:00
last_updated: 2026-08-06T23:54:30
sources:
  - "[[episodic-memory/2026-08-01_11-30-00/outputs/FINDINGS.md]]"
  - "[[episodic-memory/2026-08-01_11-30-00/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[left-turn-treatment-tradeoffs]]"
  - "[[corridor-access-management-twltl-representation-and-density-effects]]"
related_skills:
  - design-left-turn-storage-bay-length
  - compare-left-turn-signal-treatments
  - validate-congested-scenario-results-against-teleport-artifacts
  - evaluate-corridor-access-management-and-median-treatments
related_skills_for_graph_view:
  - "[[design-left-turn-storage-bay-length]]"
  - "[[compare-left-turn-signal-treatments]]"
  - "[[validate-congested-scenario-results-against-teleport-artifacts]]"
  - "[[evaluate-corridor-access-management-and-median-treatments]]"
---

# Left-Turn Storage Bay Length Design

Left-turn storage bay (pocket) length is one of the most common geometric design decisions in signalized-intersection practice, and the interaction between network geometry and signal control it represents had never been studied in this memory — [[left-turn-treatment-tradeoffs]] compares *how* left turns are signaled (permissive/protected/protected-permissive) using a fixed-length bay purely as scaffolding, never varying the bay's own length or instrumenting its two classic failure modes. This page documents the first treatment of bay length itself as a design variable, using `design-left-turn-storage-bay-length`'s dual-failure-mode measurement methodology.

## The two failure modes

An undersized left-turn bay fails in two physically distinct ways: **overflow** (the bay is full, so an additional left-turning vehicle stops in the upstream through lane, blocking through traffic) and **blockage/starvation** (a through queue extends past the bay's own entrance point, physically preventing left-turners from even reaching the bay while the protected left phase is green, wasting that green time). These were measured as separate event rates, cross-validated between live vehicle tracking and an independent offline trajectory re-derivation, agreeing almost exactly.

## Verified finding: critical bay length depends on which failure criterion is used

"The critical bay length" is not a single number — a bay long enough to preserve nearly all achievable **throughput** can still be far too short to avoid substantial **delay**. In one verified sweep, the throughput-preserving critical length was roughly 12-64m (depending on left-turn demand share) while the delay-preserving critical length was 50m to over 150m for the same conditions — several times longer. Any bay-length recommendation should specify which failure criterion it targets.

## Verified finding: signal retiming cannot fix a geometric shortfall; actuation can help, but can also backfire

**Reallocating green time within a fixed-time signal plan recovered essentially none of the throughput lost to an undersized bay** (0% recovery in the large majority of tested conditions) — a bay-length deficiency is a physical-capacity problem, not a signal-timing allocation problem, and rearranging a fixed pool of green time cannot manufacture storage space that doesn't exist. **Switching to actuated control, by contrast, genuinely helped in most tested conditions** (recovering roughly 40-110% of the throughput loss), because it can dynamically extend green in response to real detected demand rather than a fixed a priori split. **But at the shortest tested bay lengths, actuated control was found to be substantially worse than fixed-time** (over twice as bad in one verified case) — too short a bay fails to keep the actuated detector's presence signal continuously active, so the controller's own gap-out logic ends the protected phase prematurely even while real left-turn demand remains, unable to reach the already-full bay. Actuated control is not a universally safe upgrade for an undersized bay; its effect can reverse sign at very short lengths.

## Verified finding: a standard design rule of thumb is conservative for capacity but unsafe for delay

Checking a standard left-turn-bay design rule (sized from expected arrivals per signal cycle) against measured SUMO behavior found it **conservative for throughput** — a rule-length bay preserved nearly all achievable throughput, using notably more length than the measured throughput-critical minimum — but **not conservative for delay**: the same rule-length bay still produced substantial excess left-turn delay and left a meaningful share of protected green time wasted to blockage. **The mechanism the rule misses**: the delay-driving failure mode was found to track the **through** movement's own queue length far more closely than the left-turn arrival volume the rule is based on — measured 95th-percentile through-queue length was several times longer than the measured 95th-percentile left-turn queue in the same conditions. A bay sized purely against its own movement's arrival volume can still be starved by an unrelated through-queue spilling back past its entrance — a genuine blind spot in a purely volume-based design rule.

## Verified finding: the two failure modes trade off non-trivially with bay length

Overflow decays monotonically as bay length increases, as expected. **Blockage/starvation is genuinely non-monotone** — it can rise, peak at an intermediate bay length, then fall, rather than monotonically decreasing throughout the tested range. A longer bay is not guaranteed to strictly improve every failure mode simultaneously.

## Verified finding: which movement bears the aggregate delay cost flips with left-turn demand share

Per individual vehicle, the left-turn movement always suffers more delay from an undersized bay than the through movement. **But weighted by total volume (aggregate vehicle-hours of excess delay across the whole approach), the answer inverts at low left-turn shares**: the uninvolved through movement — purely a collateral victim of bay-induced blockage — can bear the majority of total network excess delay when left-turn share is low, simply because there are far more through vehicles overall. At high left-turn shares, the left movement itself carries the majority of the aggregate cost. Whether a bay-length deficiency is "mostly a left-turner's problem" or "mostly everyone else's problem" depends on the traffic mix, not just the bay geometry.

## Practical takeaways

- Verify a bay's compiled length matches its intended length — `netconvert` can shorten an authored bay substantially due to junction geometry, and this can silently invalidate a bay-length comparison.
- Report both throughput-based and delay-based critical bay lengths — they can differ by a large factor, and a design adequate for one can be inadequate for the other.
- Don't expect signal retiming to compensate for insufficient bay storage — it's a capacity problem, not a timing-allocation problem.
- Verify actuated control's effect at the specific bay length in question before assuming it's a safe substitute for fixed-time — it can be worse at very short bay lengths.
- Check a design rule of thumb against the through-queue length, not just left-turn arrival volume, when assessing delay-based adequacy — through-queue spillback can starve a bay that's correctly sized for its own movement's demand.
- Don't assume a longer bay strictly improves every failure mode — blockage/starvation specifically can be non-monotone in bay length.

See the `design-left-turn-storage-bay-length` skill for the full compiled-length calibration, dual-failure-mode instrumentation, and design-rule verification methodology.
