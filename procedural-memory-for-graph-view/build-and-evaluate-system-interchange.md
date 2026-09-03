---
name: build-and-evaluate-system-interchange
description: Use this skill when the user wants to build a FREEWAY-TO-FREEWAY (system) interchange in SUMO by hand-authoring plain-XML node/edge/connection/type files — a full cloverleaf with loop ramps, a cloverleaf with collector-distributor (C-D) roads, or a partial-cloverleaf/semi-directional variant with a directional flyover — and compare the designs' capacity, breakdown point and weaving behaviour under a 12-movement freeway OD demand sweep. Covers rotationally-symmetric carriageway generation, loop/outer-ramp arc geometry that does not self-overlap, the gore-taper trick that stops netconvert distorting edge lengths, verifying grade separation both topologically and by planar-crossing clearance, and diagnosing a boundary-insertion ceiling masquerading as a capacity. Distinct from build-diamond-interchange-with-signal-offset-spillback (a service interchange with signalised ramp terminals) and from model-freeway-weaving-segment (one isolated weaving segment rather than four coupled ones in a closed interchange). Trigger on mentions of cloverleaf, system interchange, freeway-to-freeway interchange, loop ramp, collector-distributor road, C-D road, directional flyover, or partial cloverleaf.
related_skills:
  - model-freeway-weaving-segment
  - build-diamond-interchange-with-signal-offset-spillback
  - build-macroscopic-fundamental-diagram
  - quantify-sumo-run-to-run-variability
  - validate-congested-scenario-results-against-teleport-artifacts
  - analyze-simulation-outputs
related_skills_for_graph_view:
  - "[[model-freeway-weaving-segment]]"
  - "[[build-diamond-interchange-with-signal-offset-spillback]]"
  - "[[build-macroscopic-fundamental-diagram]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[validate-congested-scenario-results-against-teleport-artifacts]]"
  - "[[analyze-simulation-outputs]]"
related_pages:
  - "[[system-interchange-weaving-and-design-selection]]"
---

# Build and Evaluate a Freeway-to-Freeway System Interchange

Builds a four-leg system interchange in SUMO from hand-authored plain XML and measures what its
loop-ramp weaving costs, versus C-D roads and versus a directional flyover. This generalises
`model-freeway-weaving-segment` from one isolated weaving segment to four coupled weaving sections
inside a closed network, where each carriageway's loop-off ramp is the next carriageway's loop-on ramp.

## Generate the whole interchange by 90° rotation

Index the four one-way carriageways `k = 0..3` (EB, NB, WB, SB), each a 90° CCW rotation of the
previous. Address every point as `(k, s, d)`: `s` = station along the direction of travel from the
crossing point, `d` = lateral offset. Then:

- **through** stays on carriageway `k`;
- **right turn** from `k` → outer directional ramp → carriageway `(k-1) % 4`;
- **left turn** from `k` → 270° loop ramp → carriageway `(k+1) % 4`.

Four legs × 3 destinations = the 12 movements. Build one carriageway's node/edge/connection chain and
one loop/outer ramp, then emit all four by rotation — the C-D variant costs nothing extra because it
rotates too. See `scripts/build_networks.py`.

## Ramp arc geometry that closes exactly, and does not self-overlap

With carriageway centrelines offset `MED` from their freeway's axis, tangential closure forces both
radii:

- **Loop** (270°, clockwise): centre at local `(MED+R_loop, -(MED+R_loop))`, so the loop-off gore sits
  at station `+(MED+R_loop)` and the loop-on gore on the next carriageway at `-(MED+R_loop)`.
  **The weaving-section length is therefore `2*(MED+R_loop)` — it is set by the loop radius, not chosen
  independently.** A tight cloverleaf loop (R≈65 m) inevitably gives a ~150 m weave.
- **Outer** (90°): gore at station `-(MED+R_outer)`, landing at `+(MED+R_outer)` on carriageway `k-1`.

**The outer radius is not free.** The outer ramp and the loop share a quadrant, and their circles
intersect unless the outer ramp is pushed outside the loop. Requiring
`sqrt(2)*(a - b) >= (a - MED) + R_loop + clearance`, where `a` = outer gore station and
`b = MED + R_loop`, gives `a >= ~427 m` for `MED=12, R_loop=65`. Choosing a "reasonable-looking"
outer radius without this check produces ramps that overlap in plan at the same elevation — verify it,
don't assume it.

For a C-D variant, re-reference both formulas to the C-D alignment (offset `MED + |CD_LAT|` from the
axis) rather than the mainline, and add short tangent stubs so the C-D gores land on the same stations
as the mainline gores — otherwise the two designs' weaving sections differ in length and the comparison
is confounded.

## Give every ramp a gore taper, or netconvert will silently redesign your network

A ramp whose shape leaves the mainline *exactly* tangentially separates from it so slowly
(`offset = R(1-cos θ)`) that netconvert builds a ~60 m junction polygon. That polygon then **moves the
mainline edge endpoints**: a designed 154 m weaving section compiled to 196 m, and the ramp's entire
height change was compressed into an 8 m end remnant and reported as a spurious 15.6 % grade.

Fix: offset the ramp polyline to the right of its direction of travel by `w`, ramped in linearly over
the first/last `ltap` metres (`w=5 m, ltap=40 m` ≈ 7° divergence for a 65 m loop; `w=9 m, ltap=45 m`
for a 428 m outer ramp). Also hold the ramp's `z` **constant over the first/last ~35 m**, since
netconvert trims the end segment but keeps the node's `z`. Together these took a build from 12
warnings to **zero**.

Then report **compiled** dimensions, not nominal ones — netconvert still absorbs the gore areas into
junctions (154 m designed → 182.5 m compiled here).

## Lane arithmetic at gores

netconvert's own convention for adding a lane on the right is one source lane feeding several target
lanes, and it accepts it without warning:

```xml
<connection from="EB_in" to="EB_dec" fromLane="0" toLane="0"/>   <!-- new aux lane -->
<connection from="EB_in" to="EB_dec" fromLane="0" toLane="1"/>
<connection from="EB_in" to="EB_dec" fromLane="1" toLane="2"/>
<connection from="EB_in" to="EB_dec" fromLane="2" toLane="3"/>
```

The weaving section itself is the shared-auxiliary-lane pattern from `model-freeway-weaving-segment`:
mainline into lanes 1..3, loop-on into lane 0, lane 0 out to the loop-off, lanes 1..3 onward. A 2-lane
exit (flyover, C-D) needs the approach widened to 5 lanes so lanes 0–1 leave and 2–4 continue.

## Verify from the compiled net, including planar crossings

Connection topology alone is **not** sufficient for grade separation. Check both:

1. zero `<connection>` elements join a freeway-A edge to a freeway-B edge, and no node is shared
   between the two mainlines; **and**
2. every pair of edges that crosses *in plan* but shares no junction — SUMO will not create a junction
   there, so each is a physical structure — has real vertical clearance. Without check 2 a flyover
   passing straight through a mainline at the same elevation looks perfectly healthy.

Also confirm the loop-on-fed lane and the loop-off-drained lane are literally the same lane id, and
that the variant that is *supposed* to have no weaving reports none. `scripts/verify_networks.py`
does all of this plus fitted ramp radii, max grades, ramp-pair clearances, orphan lanes, and a
12-movement `duarouter` routability check.

## Measurement

- E1 chain (every lane, ~40 stations, 60 s) along the critical carriageway → discharge-vs-demand and
  time-space speed/occupancy maps. **Leave cells with zero vehicles empty rather than plotting speed 0**,
  or the post-flow drain-out reads as a corridor-wide jam.
- E2 spanning each weaving section, each loop ramp, and the mainline immediately upstream of each weave.
- **Spillback fraction**: fraction of intervals in which the queue on the *worst lane* of a section
  reaches ≥85 % of its length (worst-of-lanes, per `build-diamond-interchange-with-signal-offset-spillback`).
  A loop-off ramp fed from a mainline auxiliary lane pushes its queue straight onto the mainline.
- `--lanechange-output` binned by absolute station, **split by roadway (mainline vs C-D)** — a combined
  profile hides exactly the effect a C-D design is meant to produce. Records carry `(edge, pos)`, so map
  them onto stations by walking the compiled lane polyline.
- Fixed routes, **no rerouting device**, or the designs differ in path choice as well as geometry.

## Two traps that will invalidate the capacity numbers

**A boundary-insertion ceiling looks exactly like a capacity.** SUMO inserted at most ~4 400 veh/h onto
a plain 3-lane 120 km/h edge *with no downstream bottleneck at all* (1 466 veh/h/lane — far below what
the same road carries once flowing). Four such approaches cap the whole network at ~17 000 veh/h.
Diagnose it: if the most upstream detector's flow is flat across demand levels **while the interior is
free-flowing** (low time loss, no teleports), that plateau is the entry ceiling, not a capacity — report
the design's capacity as a lower bound. Run the one-edge control experiment
(`scripts/test_insertion_ceiling.py`) rather than guessing.

**`timeLoss` is not comparable across designs with different posted speeds.** SUMO measures it against
the speed limit of the lanes actually used, so an 80 km/h C-D scores well by being slow. Use `duration`
for cross-design travel-cost comparisons; keep `timeLoss` for within-design comparisons only.

Also: **do not use `--time-to-teleport -1`** here. Disabling teleporting to get "physically honest"
queueing hung a severely oversaturated run indefinitely. Use a long finite value (900 s) and report
teleport counts per run so their influence stays auditable.

## Verified findings

On a 3-lane/120 km/h system interchange with a 182 m mainline weaving section, 14 700 veh/h base OD
containing one dominant left (1 300 veh/h) that is half of a 2 300 veh/h weaving pair, swept 0.50→1.90
over 14 demand levels × 5 seeds:

- Full cloverleaf sustained **14 802 veh/h = 86.7 %** of what its own approaches could deliver, then
  dropped 7.6 % beyond the peak. **13.3 % of capacity lost purely to loop-ramp weaving.**
- C-D roads recovered **916 veh/h = 40 % of that loss** by relocating, not removing, the weaving:
  mainline lane-change concentration in the weave zone fell from **9.15× to 0.41×** while the C-D
  roadway carried **42.3×**; mainline spillback fell 73 %. The cost fell on the *right-turn* movements
  forced onto the 80 km/h C-D (+11.5 s), not on the loop movements, which were 19 s **faster**.
- The directional flyover never broke down (its 17 080 veh/h plateau was the entry ceiling), halving
  mainline lane-change concentration to 4.71× by deleting the crossing pair rather than moving it.
- **The flyover's advantage is entirely conditional on concentrated left-turn demand**: +16.4 % over
  the cloverleaf with lefts split 1300/1000/500/450, but **−1.0 %** with the identical total volume
  split evenly. With balanced lefts the cloverleaf itself never broke down (17 293 veh/h).
  **A full cloverleaf's capacity is governed by its single most heavily-weaved carriageway, not by its
  total volume** — it is not inherently low-capacity, it is intolerant of an unbalanced left-turn split.
- `--lanechange.duration` drives all of this: with SUMO's default of `0` (instantaneous), cloverleaf
  throughput rose **+10.4 %** but the flyover's only +1.6 %, roughly halving the measured design gap.

## Gotchas

- **The weaving length is a consequence of the loop radius** (`2*(MED+R_loop)`), not an independent knob.
- **The outer-ramp radius must be solved for, not chosen** — otherwise it overlaps the loop in its quadrant.
- **Tangential ramp gores make netconvert move your mainline edge endpoints** — taper every gore, and
  hold ramp `z` flat over the first/last ~35 m.
- **Verify grade separation geometrically as well as topologically** — zero A↔B connections does not
  prove a flyover clears the road it flies over.
- **A flat upstream detector reading with a free-flowing interior is an insertion ceiling, not a capacity.**
- **`--time-to-teleport -1` can hang the run**; use a long finite value and report teleports.
- **Split lane-change profiles by roadway** when comparing a C-D design, or the relocation effect is invisible.
- Run-to-run spread peaks at the capacity knee (one seed differed 10× in mean time loss from its four
  siblings) — see `quantify-sumo-run-to-run-variability`; use ≥5 seeds near the knee.

## Related

- `model-freeway-weaving-segment` — the shared-auxiliary-lane topology, the `--lanechange-output`
  spatial-concentration method, and the position-binning gotcha this skill reuses and extends from one
  isolated segment to four coupled ones.
- `build-diamond-interchange-with-signal-offset-spillback` — the *service* interchange counterpart
  (signalised ramp terminals); its grade-separation-verification and worst-of-lanes spillback definition
  are reused here.
- `build-macroscopic-fundamental-diagram` — the demand-sweep/E1 capacity-measurement discipline, and the
  rule that capacity is the *peak* of the flow-demand curve, not the flow at the heaviest demand.
- `quantify-sumo-run-to-run-variability` — replication design; variability peaks exactly at the knee
  this skill measures.
- `validate-congested-scenario-results-against-teleport-artifacts` — teleport auditing for the
  oversaturated end of the sweep.
- `analyze-simulation-outputs` — tripinfo/summary parsing conventions.
- [[system-interchange-weaving-and-design-selection]] — the underlying mechanism, the verified
  capacity/mechanism numbers, and the movement-split design rule.
