---
summary: A rigorous SUMO study of arterial signal progression (the green wave) found two-way through-bandwidth is periodic (not monotonic) in block spacing with sharp resonance peaks at L=n*v*C/2; that bandwidth-optimal and delay-optimal offsets and cycle lengths genuinely differ (a maximum-bandwidth plan can be statistically indistinguishable from no coordination at all, while a zero-analytic-bandwidth practical-tool plan can nearly match a delay-optimized one); that lead-lag left-turn phasing recovers substantial bandwidth at non-resonant spacings at essentially no left-turn delay cost in a green-time-neutral, protected-left construction; that a fitted platoon-dispersion factor mostly measures fleet speed heterogeneity rather than a fixed physical constant; and that queue spillback can reverse coordination's benefit at a measurable demand threshold because the same platooning that makes a green wave work delivers a compact burst into limited downstream storage.
keywords:
  - arterial-signal-progression
  - green-wave
  - bandwidth
  - MAXBAND
  - platoon-dispersion
  - signal-offset
  - resonance
  - queue-spillback
created: 2026-08-02T19:30:00
last_updated: 2026-08-06T02:00:00
sources:
  - "[[episodic-memory/2026-08-02_19-00-00/outputs/FINDINGS.md]]"
  - "[[episodic-memory/2026-08-02_19-00-00/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[tlscoordinator]]"
  - "[[tlscycleadaptation]]"
  - "[[diamond-interchange-signal-offset-and-spillback]]"
  - "[[one-way-vs-two-way-grid-performance-crossover]]"
  - "[[simulation-in-the-loop-ga-signal-optimization]]"
  - "[[automated-traffic-signal-performance-measures]]"
  - "[[multimodal-signal-progression-and-the-bicycle-green-wave]]"
related_skills:
  - design-arterial-signal-progression-and-verify-bandwidth
  - optimize-signals-by-tlscoordinator
  - optimize-signals-by-tlscycleadaptation
  - compare-one-way-vs-two-way-street-grid-conversion
  - build-diamond-interchange-with-signal-offset-spillback
  - design-multimodal-signal-progression-for-bicycles-and-cars
related_skills_for_graph_view:
  - "[[design-arterial-signal-progression-and-verify-bandwidth]]"
  - "[[optimize-signals-by-tlscoordinator]]"
  - "[[optimize-signals-by-tlscycleadaptation]]"
  - "[[compare-one-way-vs-two-way-street-grid-conversion]]"
  - "[[build-diamond-interchange-with-signal-offset-spillback]]"
  - "[[design-multimodal-signal-progression-for-bicycles-and-cars]]"
---

# Arterial Signal Progression: Resonance, Bandwidth, and Delay

Arterial signal progression (a "green wave") coordinates a sequence of signals so
vehicles traveling along the corridor can pass through consecutive intersections
without stopping. This page treats progression as a theory-and-design object —
when is a two-way green wave physically possible, how close do practical tools get
to the theoretical optimum, and when is maximizing bandwidth actually the wrong
design objective.

## Verified finding: progression quality is periodic in block spacing, with sharp resonance peaks

The two-way through-bandwidth achievable at a signalized arterial, computed exactly
via interval algebra from offsets/splits/cycle/geometry, is **periodic in uniform
block spacing, not monotonically improving with any particular spacing choice** —
it peaks sharply near `L = n * v * C / 2` (n a positive integer, v the corridor's
progression speed, C the shared cycle length), with weaker secondary peaks near the
quarter-wave points. The peak-to-peak relationship matches the closed-form
prediction essentially exactly. **The resonance peaks are sharp, not broad**: a
spacing error of a modest fraction of the resonant wavelength can cost a large
fraction of the achievable bandwidth — this is directly actionable for corridor
geometric design, not just a qualitative "aim for even spacing" heuristic. A
genuinely counter-intuitive **degenerate case** was found at spacing exactly equal
to `v*C` (one full cycle's worth of travel time between signals), where the
*uncoordinated* baseline plan turned out to be the actual optimum — not every
spacing the resonance formula might suggest is "good" behaves as expected, and this
specific degenerate geometry is worth checking for explicitly.

## Verified finding: bandwidth-optimal and delay-optimal offsets are genuinely different objectives

Comparing three offset sets — the analytic maximum-two-way-bandwidth plan, a
practical coordination tool's output, and offsets directly optimized against
measured total delay — found real, sometimes surprising divergence:

- At a non-resonant spacing, the maximum-bandwidth plan was **statistically
  indistinguishable from doing nothing at all**, while still costing measurable
  delay relative to the delay-optimized plan — pursuing bandwidth is not a free
  efficiency win at every geometry, and can be actively wasteful.
- A practical coordination tool's output, despite computing **zero analytic
  bandwidth**, still closely matched the delay-optimized plan's performance —
  bandwidth and delay are correlated in general, but not tightly enough that one
  can substitute for measuring the other directly.
- The delay-optimal offset set discovered a strongly **asymmetric, one-way**
  progression rather than the two-way band a bandwidth-maximizing objective
  explicitly targets — this asymmetry is only visible if per-direction results are
  reported as signed differences, not folded into an absolute value.
- A claim that "the bandwidth-vs-delay gap widens with rising demand/saturation"
  needs to specify **in which sense**: it can widen in absolute terms (seconds of
  delay) while simultaneously narrowing in relative terms (percent) — both should
  be reported, since a headline claim can otherwise imply a stronger result than is
  actually supported.
- A more sophisticated simulation-in-the-loop delay-optimization search is **not
  guaranteed to beat a simpler practical coordination tool at every tested
  condition** — an honest study should report a loss at any tested condition, not
  only the conditions where the sophisticated method wins.

## Verified finding: bandwidth-optimal and delay-optimal cycle length also diverge, and "delay" itself is ambiguous

Sweeping cycle length found the bandwidth-optimal cycle differs substantially from
the delay-optimal cycle, because **absolute bandwidth trivially grows with a longer
cycle** (more green time per cycle available to fit a band into) while delay does
not improve monotonically with cycle length — a longer cycle increases average wait
for every movement that must wait through a red phase, including the cross street.
**Bandwidth efficiency (bandwidth as a fraction of cycle length) is a substantially
better proxy for delay than absolute bandwidth** and should be used when comparing
cycle-length choices. Additionally, **which cycle counts as "delay-optimal" depends
on whose delay is being measured** — the cycle minimizing corridor-through delay
specifically differed materially from the cycle minimizing network-wide delay in one
tested case, since cross-street delay rises roughly monotonically with cycle length.
"Optimal cycle length" implicitly bakes in an equity choice about whose delay
matters most, and that choice should be made explicit rather than assumed.

## Verified finding: lead-lag phasing recovers bandwidth at non-resonant spacing, without necessarily costing left turns

Testing lead-lag left-turn phasing (one direction's protected left phase placed
before its through movement, the opposing direction's placed after) against
symmetric lead-lead phasing at non-resonant spacings — where symmetric phasing
structurally cannot achieve a good two-way band — found lead-lag recovers
substantial bandwidth, with a correctly-vanishing benefit exactly at resonant
spacing (where symmetric phasing was already adequate). **In a green-time-neutral
construction with fully protected left turns, lead-lag did not cost the left-turn
movements delay — it genuinely improved left-turn delay** at the same time it
improved through-bandwidth, contradicting the common assumption that bandwidth
recovery via phase reordering necessarily trades against the reordered movement's
own performance. This finding's scope is explicitly bounded: it depends on the
phasing change being green-time-neutral (only phase *order*, not phase *duration*,
changes) and on the left turns being fully protected — a permissive-left program
introduces a "yellow trap" safety hazard this specific finding does not model, and
the tradeoff could differ under permissive phasing.

## Verified finding: a fitted platoon-dispersion factor mostly measures fleet speed heterogeneity

Fitting Robertson's platoon dispersion model (`F = 1/(1+alpha*beta*T)`) to measured
headway/occupancy spread downstream of a signal found the fitted `alpha*beta`
parameter, in a fleet with low driver-to-driver speed variance, came out far below a
typical real-world literature reference value. A sensitivity sweep over the fleet's
speed-variance parameter confirmed the fitted dispersion factor tracks it closely,
bracketing the literature value as speed variance increased toward realistic levels
— **the dispersion factor is substantially a measurement of fleet speed
heterogeneity, not a fixed physical constant of platoon behavior in general.** A
downstream-link-length threshold ("coordination stops paying beyond distance X")
derived from a low-speed-variance simulated fleet should not be assumed to transfer
directly to a more realistic heterogeneous-fleet scenario without re-testing at a
comparable speed-variance level — with an unrealistically homogeneous fleet,
detuning from resonance, not genuine platoon dispersion, may be the actually-binding
constraint on progression quality.

## Verified finding: queue spillback reverses coordination's benefit, and the mechanism is the platooning itself

Raising demand until an arterial link's queue approached its physical storage
capacity found network-wide coordination benefit **collapses and reverses sign at a
specific, measurable demand threshold**, with the mechanism directly observable from
detector data spanning each link: the **coordinated** plan built a **longer** queue
than the uncoordinated one at high demand, because a well-timed green wave delivers
a compact platoon of vehicles into the downstream link in a concentrated burst — and
once that link is near its storage limit, concentrated arrival overwhelms it faster
than the more spread-out arrival pattern an uncoordinated plan produces. **The exact
mechanism that makes a green wave beneficial at moderate demand (platooning vehicles
together) is what makes it actively harmful once downstream storage is tight.** The
specific numeric demand threshold is corridor-specific (dependent on link length and
storage capacity), but the mechanism and the diagnostic — monitor queue/storage
ratio directly, not just delay — generalize.

## Practical takeaways

- Verify SUMO's `tlLogic` offset sign convention (`(t-offset) mod C`) via live
  observation before trusting any bandwidth calculation built on it.
- Design or evaluate block spacing against the resonance formula `L = n*v*C/2`, and
  budget for how sharp the resonance peak is — a modest spacing error can cost a
  large fraction of achievable bandwidth.
- Never use absolute bandwidth alone as a design objective — compare against
  bandwidth efficiency (`b/C`) and, more importantly, against directly measured
  delay; bandwidth and delay are correlated but not interchangeable.
- Consider lead-lag left-turn phasing specifically at non-resonant spacings — it
  can recover bandwidth without necessarily costing the reordered movement delay,
  in a green-time-neutral, protected-left design.
- Don't extrapolate a fitted platoon-dispersion parameter from a homogeneous-speed
  simulated fleet to a realistic heterogeneous fleet without re-checking at
  comparable speed variance.
- Monitor the queue/storage ratio on coordinated links explicitly — coordination's
  benefit is not monotone in demand, and can reverse exactly because of the
  platooning mechanism that makes it work at lower demand.

See `design-arterial-signal-progression-and-verify-bandwidth` for the full
construction, verification, exact-bandwidth-calculator, and hypothesis-testing
methodology.
