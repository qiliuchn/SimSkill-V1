---
name: design-arterial-signal-progression-and-verify-bandwidth
description: Use this skill when the user wants to design or analyze arterial signal progression ("the green wave") in SUMO as a theory-and-design object — computing the theoretical two-way through-bandwidth from signal offsets/splits/cycle/geometry, comparing it against measured progression from vehicle trajectories, and determining when coordinating signals is actually worth it versus re-timing for delay. Covers an exact interval-algebra bandwidth calculator, verifying SUMO's tlLogic offset sign convention, reconciling analytic bandwidth against FCD-measured zero-stop progression, the resonance relationship between block spacing and bandwidth, why bandwidth-optimal and delay-optimal offsets/cycles differ, lead-lag left-turn phasing as a bandwidth-recovery tool, platoon dispersion, and when queue spillback reverses coordination's benefit. Trigger on mentions of green wave, signal progression, arterial coordination, through-band, MAXBAND, tlsCoordinator theory, platoon dispersion, or "when is coordinating signals worth it."
---

# Design Arterial Signal Progression and Verify Bandwidth

Extends `optimize-signals-by-tlscoordinator`'s tool-usage skill (run the script, get
offsets) into the underlying theory: when is a two-way green wave physically
possible, how close does a practical tool's output get to the theoretical optimum,
and — the more consequential question — when is maximizing bandwidth actually the
*wrong* objective compared to just re-timing for delay.

## Foundational prerequisite: verify the offset sign convention first

**Every downstream bandwidth calculation depends on this being right, and it is easy
to get backwards.** SUMO's `tlLogic` offset semantics are `(t - offset) mod C`, **not**
`(t + offset) mod C`. Verify this directly via live TraCI rather than trusting either
convention by construction: pick several *discriminating* signals (offsets that are
not 0 or C/2, since those values can't distinguish the two conventions — exclude them
from the verification, don't count them as evidence either way), observe the actual
green-onset time at each, and check which convention predicts it with near-zero error.
Getting this backwards silently produces a computed bandwidth of zero and every
green bar mis-placed on a time-space diagram, without any error or warning — the
kind of bug that looks like "coordination didn't work" rather than "the offset
convention is inverted."

## Build a parametric arterial with everything sweepable

Construct a straight corridor of several intersections with a cross-street at each,
parameterizing block spacing, cycle length, design speed, and per-signal left-turn
phasing mode (lead-lead, lead-lag, lag-lead) so all four can be swept independently.
Give the arterial exclusive left-turn bays (verified from the compiled net: the
leftmost arterial lane at each approach should have exactly one outgoing connection,
and it should be the left turn). Put every signal on a **unified cycle**
(`tlsCycleAdaptation.py --unified-cycle`) before computing offsets — a green wave
across signals with different cycle lengths is not well-defined, and `tlsCoordinator.py`
assumes a shared cycle. Verify the unification genuinely took effect (every signal's
compiled/loaded cycle length matches) and that phase-duration budgets, through-window
widths, and window displacements match what the design intended — from the compiled
net and the actual TraCI-loaded programs, not from the input files or design intent.

**Calibrate the assumed progression speed against measured behavior rather than
assuming free-flow/posted speed.** Sweep the design speed used in the bandwidth
calculation against the resulting measured zero-stop fraction and pick the value
that best predicts real vehicle behavior — verified case: the best-fit progression
speed was meaningfully below the posted speed limit (roughly 94% of it), and using
the wrong speed shifts every resonance calculation.

## An exact analytic bandwidth calculator

Compute the two-way through-band via **interval algebra modulo the cycle** (compute
each direction's green-window interval at each signal, propagate along the corridor
by the platoon's travel time, and find the overlap of the intersected intervals) —
this carries no numerical/discretization error, so any disagreement between the
analytic band and measured progression is a genuine physical effect, not calculator
noise. Report, per direction: bandwidth `b_in`/`b_out`, bandwidth efficiency `b/C`
(bandwidth as a fraction of cycle length — a much better cross-scenario comparison
metric than absolute bandwidth, since absolute bandwidth trivially grows with a
longer cycle even when nothing about coordination quality improved), and
**attainability** `b/gT` (bandwidth as a fraction of the through green window itself
— how much of the *theoretically available* band a given offset set actually
achieves).

**When searching for the maximum-bandwidth offset set (a MAXBAND-style search), seed
the search with the closed-form uniform-corridor solution rather than relying on
pure coordinate ascent from an arbitrary starting point.** A pure ascent can converge
to an offset set that is worse than the simple closed-form solution on a nontrivial
fraction of tested configurations — always verify the search's result actually
dominates the closed-form baseline before trusting it, and treat this as a required
sanity check on any bandwidth-search implementation, not an optional nicety.

## Three measurement layers, kept reconciled

Report bandwidth/progression quality on three independent layers, and check that
they agree — don't rely on any single one:

1. **Analytic** — the exact interval-algebra band computed above.
2. **Measured, from FCD** — trace individual vehicle trajectories and compute the
   fraction of corridor-through vehicles that traverse the whole arterial with zero
   stops, plus the empirical arrival-time window that actually clears every signal.
3. **Standard aggregate statistics** — delay, stop count, travel time, computed the
   usual way from `tripinfo`/`summary`.

**Expect a real relationship but not identity between the analytic and measured
layers, and quantify the disagreement rather than assuming one predicts the other
linearly.** Verified pattern: a strong overall correlation between analytic band and
measured zero-stop fraction, but with structure in the disagreement — very small
analytic bands (below some threshold) can deliver essentially *zero* measured
progression even though the theoretical band is nonzero (a real but too-narrow
window gets consumed entirely by ordinary speed variance/driver imperfection before
any vehicle can exploit it), and *equal* analytic bands at different configurations
can produce measurably *unequal* real-world progression. Also expect different
"stop" definitions (an interior-corridor FCD-based definition vs. a whole-trip
`tripinfo` definition that includes the origin/destination legs) to disagree
substantially — report both and be explicit about which one a given number uses.

## H1-style: resonance in block spacing

**Two-way progression quality is periodic in uniform block spacing, not
monotonically improving or worsening — it peaks near `L = n * v * C / 2`** (n a
positive integer, v the calibrated progression speed, C the cycle length), with
secondary, weaker peaks near the quarter-wave points `L = (2n-1) * v * C / 4`. Verify
this by sweeping spacing at fixed cycle/speed and locating local maxima in the
analytic band — expect the peak locations and the peak-to-peak slope to match the
closed-form prediction essentially exactly, since the underlying calculator is exact.
**Report how sharp the resonance peaks are** (how much spacing error costs how much
band) — this is directly actionable for corridor design: a spacing error of a modest
fraction of the resonant wavelength can cost a large fraction of the achievable band,
information a purely qualitative "aim for resonant spacing" recommendation would
miss. Watch for a **degenerate case** at `L = v*C` exactly, where the theoretically
"resonant" spacing can actually make the *uncoordinated* baseline optimal (the
travel time between signals equals exactly one full cycle, which has a special
structural interaction with a symmetric offset plan) — don't assume every spacing
labeled "resonant" by the formula is actually good in every respect.

## H2-style: bandwidth-optimal offsets are not delay-optimal offsets

Compute (at minimum) three offset sets — analytic maximum-two-way-bandwidth, a
practical tool's output (e.g. `tlsCoordinator.py`), and offsets directly optimized
against measured total delay (e.g. via simulation-in-the-loop search) — and compare
all three, not just two. **Expect real, and sometimes surprising, divergence**:

- The maximum-bandwidth plan can be **statistically indistinguishable from doing
  nothing** at a non-resonant spacing, while still costing real delay relative to
  the delay-optimized plan — bandwidth maximization is not a free efficiency
  improvement at every geometry.
- A practical coordination tool's output can have **zero analytic bandwidth** and
  still closely match the delay-optimized plan's performance — bandwidth and delay
  are correlated in general but the correlation is not tight enough to use one as a
  certificate for the other.
- The delay-optimal offset set can turn out to favor a **one-way** progression
  (a strongly asymmetric signed difference between directions) rather than the
  two-way band a MAXBAND-style objective explicitly optimizes for — report signed,
  per-direction statistics (not folded/absolute-value ones) so this asymmetry is
  visible rather than averaged away.
- **State precisely which sense a "gap widens with saturation" claim holds in.** A
  gap between two offset sets' delay cost can widen in absolute terms (seconds) while
  narrowing in relative terms (percent) as demand rises — report both, and don't let
  a headline claim imply the stronger (relative) sense if only the weaker (absolute)
  one is actually supported.
- **A simulation-in-the-loop search is not guaranteed to beat a simpler practical
  tool at every tested condition — report a loss honestly if it occurs**, rather than
  only reporting the conditions where the more sophisticated method wins.

## H3-style: bandwidth-optimal and delay-optimal cycle length also differ

Sweep cycle length and compute both the bandwidth-optimal and delay-optimal cycle
separately — expect them to differ, because absolute bandwidth trivially grows with
a longer cycle (more green time per cycle to fit a band into) while delay does not
improve monotonically with cycle length (a longer cycle increases average wait for
every movement that has to wait through a red, including the cross street). **`b/C`
(bandwidth efficiency) is a much better proxy for delay than absolute bandwidth** —
use it, not raw band width, when comparing cycle-length choices. **Which cycle is
"delay-optimal" also depends on whose delay is being counted** — the cycle that
minimizes corridor-through delay specifically can differ substantially from the
cycle that minimizes network-wide delay, since cross-street delay tends to rise
monotonically with cycle length. Report both framings, since "optimal" implicitly
depends on an equity/whose-delay-matters choice that should be made explicit, not
assumed.

## H4-style: lead-lag phasing as a bandwidth-recovery instrument

Test lead-lag left-turn phasing (one arterial direction's protected left-turn phase
placed before its through movement, the other placed after — SUMO's native
ring-barrier `type="NEMA"` mechanism, see `implement-nema-dual-ring-controller`, is
one way to express this) against symmetric lead-lead phasing, specifically at
**non-resonant** spacings where the symmetric plan cannot achieve a good two-way
band. **Expect lead-lag to recover substantial bandwidth at non-resonant spacings
that symmetric phasing structurally cannot achieve**, with a correctly-vanishing
benefit exactly at resonant spacing (where symmetric phasing was already fine).
**Do not assume lead-lag necessarily costs the left-turn movements delay** — in a
green-time-neutral construction (the total time allocated to left-turn phases is
held constant, only its position within the cycle changes) with fully protected
left turns, lead-lag can genuinely *improve* left-turn delay rather than costing it,
since a well-placed lead or lag phase can reduce a left-turning vehicle's own wait
even as it improves through-band. **State the scope of this finding explicitly**:
it depends on the phasing being green-time-neutral and the left turns being fully
protected (not permissive) — a permissive-left program introduces the "yellow trap"
hazard that this specific finding does not model, and the cost/benefit could differ
under permissive phasing.

## H5-style: platoon dispersion

Measure platoon spread (e.g. headway or occupancy profile) as a function of distance
downstream of a signal from FCD trajectories, and fit Robertson's dispersion model
(`F = 1 / (1 + alpha*beta*T)`, T the travel time from the signal). **Check what the
fitted `alpha*beta` value is actually measuring before citing it against a
literature reference value** — a fleet with low driver-to-driver speed variance
(low `speedDev`) will show much less dispersion than the literature's typical mixed
real-world fleet, and the fitted parameter is largely a measurement of fleet speed
heterogeneity, not a fixed physical constant. Run a sensitivity sweep over the
fleet's speed-variance parameter and confirm the fitted dispersion factor tracks it
— this both validates the fitting methodology and clarifies that "platoon
dispersion" in a homogeneous-speed simulated fleet is a different (weaker)
phenomenon than in a realistic mixed fleet, so a downstream-link-length threshold
derived from a homogeneous-fleet simulation should not be assumed to transfer
directly to a more realistic heterogeneous-fleet scenario without re-testing at a
comparable speed-variance level.

## H6-style: queue spillback reverses coordination's benefit

Raise demand until an arterial link's queue approaches or exceeds its physical
storage length, instrumented with an occupancy/length detector spanning the full
link (see `build-diamond-interchange-with-signal-offset-spillback`'s spillback
methodology). **Expect network-wide coordination benefit to collapse and potentially
reverse sign at a specific, measurable demand threshold**, and verify the mechanism
directly from the detector data rather than only inferring it from the aggregate
delay reversal: a well-timed green wave delivers a compact platoon of vehicles into
a downstream link in a short burst, and if that link is near its storage capacity,
concentrated arrival can build a *longer* queue than the more spread-out arrival
pattern an uncoordinated plan produces — the same offset plan that helps at moderate
demand becomes actively counterproductive once its own platooning mechanism
collides with limited storage. **Report the demand threshold as corridor-specific**
(dependent on link length/storage and block spacing) — the transferable content is
the mechanism and the diagnostic (watch queue/storage ratio, not just delay), not a
universal numeric threshold.

## Gotchas

- **The `(t - offset) mod C` vs `(t + offset) mod C` sign convention must be
  verified via live TraCI observation, not assumed** — getting it backwards
  silently zeroes out every computed bandwidth with no error.
- **A pure coordinate-ascent bandwidth search can converge to a worse-than-closed-form
  result** — always seed with the closed-form solution and verify the search result
  dominates it.
- **Absolute bandwidth is not a fair comparison metric across different cycle
  lengths** — use bandwidth efficiency (`b/C`) or attainability (`b/gT`) instead.
- **A nonzero analytic bandwidth does not guarantee measurable real-world
  progression** — very narrow bands can be entirely consumed by ordinary speed
  variance before any vehicle benefits; check the measured layer, don't infer it
  from the analytic one alone.
- **"Bandwidth-optimal" and "delay-optimal" are different objectives at every level
  tested (offsets, cycle length)** — do not use bandwidth as a proxy for delay
  without checking the correlation is actually tight enough in the specific
  scenario at hand.
- **A fitted platoon-dispersion parameter is largely a measurement of fleet speed
  heterogeneity** — don't compare a homogeneous-fleet simulation's fitted dispersion
  factor against a real-world literature value without accounting for this.
- **Queue spillback can make the SAME coordination plan that helps at moderate
  demand actively harmful at high demand** — the platooning mechanism that makes a
  green wave work is exactly what makes it dangerous once downstream storage is
  tight; watch the queue/storage ratio explicitly, not just delay.

## Related

- `optimize-signals-by-tlscoordinator` / `optimize-signals-by-tlscycleadaptation` —
  the tool-usage layer this skill's theory extends; `--unified-cycle` is the
  required prerequisite for any bandwidth calculation across multiple signals.
- `compare-one-way-vs-two-way-street-grid-conversion` — the source of the original
  `bandwidth.py`/`timespace.py` scripts this skill's exact interval-algebra
  calculator and time-space diagram generalize, and the FCD edge-filter-file-format
  gotcha reused here.
- `build-diamond-interchange-with-signal-offset-spillback` — the offset sign
  convention gotcha and the spillback-instrumentation methodology (E2 detector
  spanning a full link) this skill's queue-spillback test directly reuses.
- `visualize-trajectories-and-timeseries` — the time-space diagram base technique
  this skill's annotated (green/red-bar-overlaid) diagrams extend.
- `implement-nema-dual-ring-controller` — the ring-barrier mechanism used to
  implement lead-lag left-turn phasing.
- `optimize-signal-plan-with-simulation-in-the-loop-ga` — the simulation-optimized
  offset-search technique used as the delay-optimal reference; its search-space-bound
  fairness requirement applies equally here.
- `quantify-sumo-run-to-run-variability` / `validate-congested-scenario-results-against-teleport-artifacts` — the CRN and teleport/completion validity discipline applied throughout this skill's demand and geometry sweeps.
- [[arterial-signal-progression-resonance-bandwidth-and-delay]] — the verified
  resonance law, the bandwidth-vs-delay divergence findings, the cycle-length
  tradeoff, the lead-lag band-recovery finding, the dispersion-vs-heterogeneity
  finding, and the spillback-reversal mechanism this skill's methodology produced.
