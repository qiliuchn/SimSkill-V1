---
summary: In a full cloverleaf system interchange the loop-off and loop-on ramps of adjacent quadrants share one mainline auxiliary lane, so capacity is governed by the single most heavily-weaved carriageway rather than by total volume; verified in SUMO to cost 13.3% of deliverable capacity, of which collector-distributor roads recover ~40% by relocating (not removing) the weaving, while a directional flyover removes it entirely but only pays off when left-turn demand is concentrated — its +16.4% advantage falls to -1.0% when the same left-turn volume is split evenly.
keywords:
  - system-interchange
  - cloverleaf
  - loop-ramp-weaving
  - collector-distributor-road
  - directional-flyover
  - insertion-capacity-ceiling
created: 2026-08-04T09:00:00
last_updated: 2026-08-05T12:40:00
sources:
  - "[[episodic-memory/2026-08-04_09-00-00/outputs/tables/design_comparison_full.md]]"
  - "[[episodic-memory/2026-08-04_09-00-00/outputs/tables/network_verification.json]]"
  - "[[episodic-memory/2026-08-04_09-00-00/outputs/tables/capacity_analysis.json]]"
  - "[[episodic-memory/2026-08-04_09-00-00/outputs/tables/lanechange_concentration_scale1.20.json]]"
related_pages:
  - "[[freeway-weaving-segment-turbulence]]"
  - "[[diamond-interchange-signal-offset-and-spillback]]"
  - "[[macroscopic-fundamental-diagram]]"
  - "[[sumo-stochastic-variability-and-replication-design]]"
  - "[[teleport-artifacts-and-gridlock-resolution-validity]]"
  - "[[abstract-network-generation]]"
  - "[[lane-change-model-calibration-and-identifiability-at-a-diverge]]"
  - "[[zipper-merge-lane-drop-discharge]]"
related_skills:
  - build-and-evaluate-system-interchange
  - model-freeway-weaving-segment
  - build-diamond-interchange-with-signal-offset-spillback
  - build-macroscopic-fundamental-diagram
  - quantify-sumo-run-to-run-variability
related_skills_for_graph_view:
  - "[[build-and-evaluate-system-interchange]]"
  - "[[model-freeway-weaving-segment]]"
  - "[[build-diamond-interchange-with-signal-offset-spillback]]"
  - "[[build-macroscopic-fundamental-diagram]]"
  - "[[quantify-sumo-run-to-run-variability]]"
---

# System-Interchange Weaving and Design Selection

A freeway-to-freeway (*system*) interchange connects two freeways with no at-grade movement at all —
distinct from the *service* interchange of [[diamond-interchange-signal-offset-and-spillback]], whose
ramps terminate at signalised surface intersections. In a full cloverleaf each quadrant holds one
270° loop ramp (serving a left turn) inside one 90° outer directional ramp (serving a right turn).
This page records the mechanism by which that layout loses capacity, and what actually recovers it.

## The geometry is not free: three quantities are locked together

With carriageway centrelines offset `MED` from their freeway's axis and loop radius `R_loop`, tangential
closure puts the loop-off gore at station `+(MED + R_loop)` and the loop-on gore at `-(MED + R_loop)`.
Hence:

> **weaving-section length = 2 × (MED + R_loop)**

The weaving length is a *consequence* of the loop radius, not an independent design knob. A tight
cloverleaf loop (R ≈ 65 m, ~45 km/h) forces a ~150 m weaving section — which is precisely why classic
cloverleafs weave badly. Lengthening the weave requires enlarging the loops, which enlarges the whole
interchange footprint.

The outer-ramp radius is likewise constrained, not chosen: the outer ramp and the loop share a quadrant,
and their circles intersect unless the outer ramp is pushed outside the loop
(`sqrt(2)·(a − b) ≥ (a − MED) + R_loop + clearance`, with `a` the outer gore station and
`b = MED + R_loop`). For `MED = 12 m, R_loop = 65 m` this forces `a ≥ ~427 m`. Picking a
plausible-looking outer radius without solving this produces ramps that overlap in plan at the same
elevation.

## The mechanism: one shared auxiliary lane per carriageway

On each carriageway the loop-*on* ramp from the previous quadrant and the loop-*off* ramp to the next
quadrant are joined by a single auxiliary lane. Entering loop traffic must cross left out of it while
exiting traffic crosses right into it — the shared-auxiliary-lane topology of
[[freeway-weaving-segment-turbulence]], but here it occurs four times in a closed network, and each
carriageway's loop-off ramp *is* the next carriageway's loop-on ramp, so the four sections are coupled.

Verified on a 3-lane/120 km/h interchange with a 182 m compiled weaving section and 2 300 veh/h of
weaving traffic: `--lanechange-output` binned by absolute station showed **9.15×** the lane-change
density inside the weave zone as elsewhere on the mainline. Time-space maps show the low-speed band
forming between the outer-off gore and the loop-off gore — centred on the weaving section — and then
propagating *upstream* as a growing wedge. Weaving-section space-mean speed fell from 16.1 m/s at half
demand to 2.3 m/s at 1.35× demand.

Because the loop-off ramp is fed *from the mainline auxiliary lane*, its queue has nowhere to go but the
mainline: at 1.35× demand the loop-off ramp was ≥85 % full 19.3 % of the time and the queue escaped onto
the mainline upstream of the weave 10.0 % of the time.

## Verified finding: capacity is governed by the worst carriageway, not the total volume

Full cloverleaf sustained capacity was **14 802 veh/h**, i.e. **86.7 %** of what its own approaches could
deliver, followed by a 7.6 % capacity drop beyond the peak — **13.3 % of capacity lost purely to
loop-ramp weaving**.

But that number is a property of the *split*, not of the layout. With the identical total OD volume and
identical through/right movements, and only the 3 250 veh/h of left-turn demand redistributed from
1300/1000/500/450 to an even 812/813/812/813, **the same cloverleaf never broke down at all**, serving
17 293 veh/h against 14 308 for the concentrated split at the same demand.

> A full cloverleaf is not inherently low-capacity. It is inherently **intolerant of an unbalanced
> left-turn split**, because its capacity is set by whichever single carriageway carries the heaviest
> weaving pair.

## Verified finding: C-D roads relocate the weaving rather than removing it

Collector-distributor roads recovered **916 veh/h — about 40 % of the cloverleaf's loss**. The mechanism
is visible directly in the lane-change data, and it is relocation, not elimination:

| lane-change concentration in the weave zone | value |
|---|---|
| cloverleaf, mainline | 9.15× |
| C-D design, mainline | **0.41×** (less churn than an average mainline location) |
| C-D design, the C-D roadway itself | **42.3×** |

Loop-ramp queueing was almost unchanged (spillback fraction 0.160 vs 0.193) — but contained on the C-D,
so mainline spillback fell 73 %. Splitting the lane-change profile by roadway is essential; a combined
profile hides exactly the effect a C-D is built to produce.

**The cost lands on the movements C-D roads do not help.** Contrary to the usual framing, the loop
movements got *faster* (heavy-left mean duration 288.6 s → 269.4 s uncongested, despite a 30 m longer
route, because the vehicle decelerates once to 80 km/h instead of dropping 120 → 45 km/h and
re-accelerating on a busy auxiliary lane). It is the **right-turn/outer-ramp** traffic, forced onto the
80 km/h C-D although it never weaves, that pays: +11.5 s (+5.6 %). Through traffic was unaffected.

## Verified finding: a directional flyover only pays off for a concentrated left turn

Replacing the single heaviest loop with a 2-lane semi-directional flyover *deletes* the crossing pair on
two carriageways at once (the origin loses its loop-off, the destination its loop-on), halving mainline
lane-change concentration to 4.71×. That design never broke down within the demand range testable.

Its advantage is nevertheless entirely conditional:

| total demand | gain over cloverleaf, **concentrated** lefts | gain over cloverleaf, **balanced** lefts |
|---|---|---|
| 14 700 veh/h | +1.4 % | −0.1 % |
| 17 640 veh/h | +9.7 % | −0.5 % |
| 19 845 veh/h | **+16.4 %** | **−1.0 %** |

A flyover serves exactly one of four left turns. When left-turn demand is concentrated (here the served
movement was 40 % of all left-turn demand *and* one half of the critical weaving pair) it is decisively
the better choice. When left-turn demand is even, it does nothing — slightly worse than nothing, since
its long ramp and extra merge do not pay for themselves — and the correct remedies are C-D roads, which
help every carriageway simultaneously, or a fully directional interchange.

## SUMO-specific caveats that decide whether these numbers are believable

**`--lanechange.duration` is the dominant parameter and SUMO's default is the optimistic one.** SUMO
defaults to `0`, i.e. instantaneous lane changes that occupy no time in the target lane. Re-running with
the default raised cloverleaf throughput by **+10.4 %** but the flyover's by only **+1.6 %** — the gain
scales with how much weaving a design contains, which is evidence the parameter acts through the weaving
mechanism rather than as a global offset. The measured design gap roughly **halves**. Any freeway
weaving-capacity result produced with the default should be read as an optimistic bound.

**A boundary-insertion ceiling is easily mistaken for a capacity.** SUMO could insert only
~4 400 veh/h onto a plain 3-lane 120 km/h edge *with no downstream bottleneck at all*
(1 466 veh/h/lane — far below what the same road carries once traffic is flowing; `departSpeed="max"`
raises it only to ~4 620, and `--eager-insert` changes nothing). Four such approaches capped the whole
network near 17 000 veh/h, which is exactly where the flyover design plateaued — so **the flyover's
capacity was never measured, only bounded below**. The diagnostic: a flat upstream-detector reading
across rising demand *combined with a free-flowing interior* (low time loss, no teleports) is an entry
ceiling, not a capacity. Measuring past it requires injecting demand inside the network rather than at
the boundary.

**`timeLoss` is not comparable across designs with different posted speeds**, because SUMO measures it
against the speed limit of the lanes actually used — an 80 km/h C-D scores well simply by being slow
(heavy-left `timeLoss` 22.0 s on the C-D vs 69.5 s on the cloverleaf, while the honest gap in `duration`
is 19.2 s). Use `duration` across designs; keep `timeLoss` within a design.

**`--time-to-teleport -1` can hang an oversaturated run indefinitely** — verified. Use a long finite
value (900 s) so ordinary heavy queueing is never teleported away, and report teleport counts per run
(see [[teleport-artifacts-and-gridlock-resolution-validity]]).

**Tangential ramp gores make netconvert redesign the network.** A ramp leaving exactly tangentially
separates so slowly that netconvert builds a ~60 m junction polygon, which moves the mainline edge
endpoints (a designed 154 m weaving section compiled to 196 m) and compresses the ramp's whole height
change into an 8 m remnant reported as a spurious 15.6 % grade. A 5 m/40 m gore taper (≈7° divergence;
9 m/45 m for a 428 m-radius outer ramp) plus holding ramp `z` flat over the first/last ~35 m removed
every warning. Even then, netconvert absorbs the gore areas into junctions, so **report compiled
dimensions, not nominal ones** (154 m designed → 182.5 m compiled).

**Grade separation must be verified geometrically, not only topologically.** Zero connections between
freeway-A and freeway-B edges does not prove a flyover clears the road it flies over — SUMO creates no
junction where two edges merely cross in plan. Enumerate every planar crossing between edges sharing no
junction and measure its vertical clearance (verified minima: 10.00 m cloverleaf, 7.14 m C-D, 5.39 m
flyover).

See `build-and-evaluate-system-interchange` for the full rotationally-symmetric build, verification and
sweep workflow, and [[freeway-weaving-segment-turbulence]] for the isolated single-segment case this
generalises.
