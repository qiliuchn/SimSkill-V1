---
summary: A controlled comparison of RCUT/superstreet and Michigan-Left/MUT at-grade alternative intersections against a conventional signalized junction found that banning a movement and rerouting it through a downstream median U-turn can raise VMT by ~2.5% while cutting VHT by up to ~38%, but each design has a demand-share and crossover-spacing threshold beyond which it fails catastrophically, and the conflict-point reduction is partly a genuine elimination and partly latent crossover conflicts becoming activated rather than points physically relocating.
keywords:
  - rcut
  - restricted-crossing-u-turn
  - superstreet
  - michigan-left
  - median-u-turn
  - mut
  - alternative-intersection-design
  - conflict-points
  - vmt-vht-tradeoff
created: 2026-08-01T16:59:00
last_updated: 2026-08-06T23:54:30
sources:
  - "[[episodic-memory/2026-08-01_16-30-00/outputs/FINDINGS.md]]"
  - "[[episodic-memory/2026-08-01_16-30-00/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[dynamic-user-equilibrium-and-wardrop]]"
  - "[[diverging-diamond-interchange-unopposed-lefts]]"
  - "[[diamond-interchange-signal-offset-and-spillback]]"
  - "[[unsignalized-vs-signalized-intersection-control]]"
  - "[[left-turn-treatment-tradeoffs]]"
  - "[[teleport-artifacts-and-gridlock-resolution-validity]]"
  - "[[corridor-access-management-twltl-representation-and-density-effects]]"
related_skills:
  - design-restricted-crossing-uturn-and-michigan-left-intersections
  - build-diverging-diamond-interchange
  - design-left-turn-storage-bay-length
  - compare-unsignalized-intersection-control-types
  - analyze-intersection-safety-with-ssm
  - evaluate-corridor-access-management-and-median-treatments
related_skills_for_graph_view:
  - "[[design-restricted-crossing-uturn-and-michigan-left-intersections]]"
  - "[[build-diverging-diamond-interchange]]"
  - "[[design-left-turn-storage-bay-length]]"
  - "[[compare-unsignalized-intersection-control-types]]"
  - "[[analyze-intersection-safety-with-ssm]]"
  - "[[evaluate-corridor-access-management-and-median-treatments]]"
---

# RCUT and Michigan-Left Alternative Intersection Design

At-grade alternative intersections eliminate a movement from the main junction
entirely — instead of protecting it with a signal phase, the movement is banned and
rerouted onto a right-turn-then-downstream-median-U-turn detour. **Restricted
Crossing U-Turn (RCUT)/superstreet** bans the minor street's through and left
movements; **Median U-Turn (MUT)/Michigan Left** bans the arterial's left turns. Both
are distinct from grade-separated unconventional geometry (see
[[diverging-diamond-interchange-unopposed-lefts]]) — the detour happens at grade, via
an ordinary median crossover, not a flyover or interchange ramp.

## Verified finding: driving farther can get you there sooner, inside an envelope

A controlled comparison (one shared geometry, only the junction connection list
varied per design; OD-fair routing recomputed per variant; signals sized
independently by Webster from each variant's own movement volumes) found cases where
an alternative design raises vehicle-miles-traveled (VMT) while *lowering* mean
travel time and vehicle-hours-traveled (VHT):

- **Strongest case**: MUT at a 400 m crossover spacing, 4800 veh/h demand, 50% minor-
  street share — **+2.46% VMT, −43.1% mean total travel time, −37.6% VHT**, with both
  the conventional baseline and MUT completing 100% of loaded demand (not a
  survivorship effect). The mechanism is the signal, not the routing: dropping the
  arterial protected-left phase frees cycle time for the movements that were starved.
- RCUT achieved a comparable qualitative result at lower demand (e.g. +0.43% VMT,
  −3.3% time at 2400 veh/h, 10% minor share, 100 m spacing).

**The gain is not shared evenly, and the two designs have opposite distributional
signatures.** MUT concentrates its entire cost on the one banned class: arterial-left
drivers pay (+792 m detour for +14.4 s) while every other class — including the
*un-banned* minor-street movements — gains 185-310 s. RCUT instead **transfers delay
from the arterial onto minor-street users**: banned minor-street through/left drivers
pay a large per-vehicle penalty (detour + delay) while every arterial class gains,
and reporting only the network-mean travel time hides this transfer entirely — always
decompose by OD movement class, not just the network mean.

## Verified finding: each design has a demand-share and spacing threshold, and RCUT/MUT are near-complementary

Sweeping minor-street demand share found **RCUT's threshold is roughly 0.22-0.25**
(wins below it, loses above it — the detour cost on minor users starts to outweigh the
arterial signal-efficiency gain), while **MUT's threshold runs the opposite direction,
roughly 0.25** (starts winning above it). RCUT is a low-minor-share treatment; MUT is
a high-minor-share treatment — the two are near-complementary rather than one
dominating the other. Sweeping crossover spacing found each design has its own
spacing threshold too (in one tested condition, RCUT ~250-300 m, MUT ~500-600 m), and
**sensitivity to spacing is monotone while the crossover doesn't overflow (more
spacing = more detour, worse) but non-monotone once it does (more spacing = more
storage, dramatically better)** — a design's spacing sensitivity can reverse sign
depending on whether the crossover itself has become the bottleneck. At high demand
the governing question shifts entirely from "signal efficiency vs. detour cost" to
"does the crossover survive at all," with catastrophic failure (900+ second penalties)
on the losing side of that threshold.

## Verified finding: the median U-turn crossover has three distinct failure modes

Because U-turn storage length equals crossover spacing (absent a dedicated bay), a
spacing sweep is simultaneously a storage-length sweep, and the crossover can fail
three separate ways, each independently measured:

1. **Storage overflow** — the U-turn lane's queue fills the entire segment.
2. **Spillback onto the arterial through lanes** — measured on the *other* lanes of
   the same edge (which carry no U-turn traffic); up to ~300 m of through-lane queue
   observed when the U-turn lane is overflowing, versus 0 m otherwise.
3. **Yield-gap starvation** — an unsignalized U-turn can produce maximum single-
   vehicle halting durations of 15-30+ minutes even without storage overflow, because
   the vehicle can't find an acceptable gap in the arterial stream — a fundamentally
   different mechanism from queueing behind a signal.

**Signalising an overflowing/gap-starved crossover is not a general fix.** It helps
only the gap-starvation case; on a storage-limited or gridlocked crossover, forcing a
red onto the arterial through stream makes total system time worse. A signalised
crossover can also increase mean *survivor* travel time while simultaneously
completing more trips — a metric-choice trap (more of the badly-delayed vehicles
finish and pull the completed-trip mean up), analogous to the survivorship-censoring
issue in [[teleport-artifacts-and-gridlock-resolution-validity]].

## Verified finding: conflict points are activated, not relocated — and check simulated conflicts too

Counting conflict points directly from the compiled network's foe matrix reproduced
the textbook figures exactly in one tested case (conventional main junction = 32;
RCUT system total = 14). **But the standard "32 → 14, points relocated to the
crossover" framing is imprecise**: because both median crossovers exist physically
and identically in *every* design variant (including the conventional baseline, where
no vehicle ever uses them), their conflict points don't move anywhere — they are
latent and unused in the conventional design, and only become *activated* (carry real
traffic) once a design forces movements through them. The correct reading is that a
substantial number of conflict points are genuinely eliminated at the main junction,
and the system-wide total nets against already-existing-but-previously-inert
crossover points.

Cross-checking the topological conflict-point count against actually **simulated**
conflicts (SUMO's SSM device, TTC/DRAC/PET) found the reduction shows up as a real
safety gain at moderate demand (one tested case: −6.3% total simulated conflicts,
−18.6% severe TTC<1.5s conflicts, normalized per 1000 vehicle-km) but the ranking can
**invert** at high demand, where simulated-conflict counts get swamped by stop-and-go
link queueing unrelated to the junction's own geometry — the topological count is a
geometry property; the simulated count also reflects whatever congestion the design
happens to cause at a given demand level, and the two can disagree.

**A degenerate SSM artifact recurs at the U-turn merge**: SUMO's SSM device can log
`type="111"` ("collision") encounters with `minTTC=0.00`/`PET=NA` at the collinear
merge point where a U-turning vehicle rejoins the arterial stream it's completing a
U-turn into, even when SUMO's own collision counter reports zero actual collisions.
This is the same artifact class [[unsignalized-vs-signalized-intersection-control]]
documents for collinear opposing left turns, recurring at a different collinear-merge
geometry. Flag and count these separately from genuine near-misses — and verify any
downstream summary table you claim excludes them actually does, not just that the
artifact was disclosed in prose.

## Practical takeaways

- Build one shared geometry and vary only the junction connection list across design
  variants — this isolates the geometry treatment as the sole cause of any measured
  difference.
- Make demand comparisons OD-fair, not route-fair: recompute routes independently per
  variant from one shared OD matrix, and verify no OD pair became unroutable or
  silently dropped.
- Size each variant's signal independently from its own measured movement volumes
  (counting rerouted traffic's return pass through the main junction), so phase count
  is a consequence of the geometry rather than an assumption.
- Always decompose VMT/VHT results by OD movement class — the two designs have
  opposite (and easily hidden) distributional signatures.
- Instrument a median U-turn crossover for all three failure modes (overflow,
  spillback, gap-starvation) separately, since they have different causes and
  different remedies.
- Treat "conflict points relocated" claims skeptically when the relocation target
  (the crossover) is structurally identical across every compared variant — check
  whether points are being activated rather than moved.

See `design-restricted-crossing-uturn-and-michigan-left-intersections` for the full
build/verification/analysis workflow, including two reproducible SUMO gotchas
(`--xml-validation never` silently emptying additional-file detector outputs, and a
`tlLogic` loaded from an additional file rejecting a reused `programID="0"`).
