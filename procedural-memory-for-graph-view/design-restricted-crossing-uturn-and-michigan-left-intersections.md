---
name: design-restricted-crossing-uturn-and-michigan-left-intersections
description: Use this skill when the user wants to model and evaluate AT-GRADE alternative intersection designs in SUMO that eliminate a movement from the main junction by rerouting it through a downstream median U-turn crossover — Restricted Crossing U-Turn (RCUT)/superstreet (bans minor-street through+left) and Median U-turn (MUT)/Michigan Left (bans arterial left) — against a conventional full-movement signalized baseline. Covers building one shared geometry with only the junction connection list varying per variant, verifying banned/allowed movements and U-turn yield relationships from the compiled net, making the comparison OD-fair via per-variant duarouter routing, sizing each variant's signal independently by Webster, sweeping crossover spacing (which is also a U-turn storage-length sweep) crossed with demand and demand-share, instrumenting the crossover as a bottleneck, and checking the classic "32 conflict points -> 14" claim against measured SSM conflicts. Trigger on mentions of RCUT, restricted crossing U-turn, superstreet, Michigan left, median U-turn, MUT, J-turn, alternative intersection design, or "does driving farther get you there sooner."
related_skills:
  - build-diverging-diamond-interchange
  - design-left-turn-storage-bay-length
  - compare-unsignalized-intersection-control-types
  - convert-od-matrix-to-trips
  - convert-trips-to-routes
  - measure-saturation-flow-and-validate-webster-method
  - analyze-intersection-safety-with-ssm
  - quantify-sumo-run-to-run-variability
  - validate-congested-scenario-results-against-teleport-artifacts
  - simulate-incident-rerouting
related_skills_for_graph_view:
  - "[[build-diverging-diamond-interchange]]"
  - "[[design-left-turn-storage-bay-length]]"
  - "[[compare-unsignalized-intersection-control-types]]"
  - "[[convert-od-matrix-to-trips]]"
  - "[[convert-trips-to-routes]]"
  - "[[measure-saturation-flow-and-validate-webster-method]]"
  - "[[analyze-intersection-safety-with-ssm]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[validate-congested-scenario-results-against-teleport-artifacts]]"
  - "[[simulate-incident-rerouting]]"
related_pages:
  - "[[rcut-and-michigan-left-alternative-intersection-design]]"
---

# Design Restricted-Crossing-U-Turn and Michigan-Left Intersections

Builds three at-grade designs sharing one geometry — CONVENTIONAL (full-movement
signal), RCUT/superstreet (bans minor-street through+left), MUT/Michigan-Left (bans
arterial left) — and empirically tests whether banning a movement at the main
junction and rerouting it through a downstream median U-turn crossover can raise
vehicle-miles-traveled (VMT) while *lowering* vehicle-hours-traveled (VHT). This is
SimSkill's at-grade counterpart to `build-diverging-diamond-interchange`/
`build-diamond-interchange-with-signal-offset-spillback` (grade-separated
unconventional geometry) and extends `compute-dynamic-user-equilibrium`'s
OD-fair-routing discipline to a case where the geometry change itself forces a
demand-routing change, not just a congestion-driven route choice.

## Shared geometry, varied connection list only

Build **one** topology: a divided arterial (separate one-way edges per direction, a
few metres of median offset, 2-3 lanes per direction) crossing a two-way minor street
at a signalized junction `J`, with two median U-turn crossovers `XW`/`XE` placed
symmetrically at `+/-D` from `J`. **Both crossovers exist physically, identically, in
every variant** — same nodes, edges, lane counts, speeds, and crossover connections.
The *only* thing that differs between variants is `J`'s own connection list:

| variant | banned at `J` | consequence |
|---|---|---|
| conventional | nothing | full-movement signal, protected lefts |
| RCUT/superstreet | minor-street through AND left | minor approach becomes dual-right-turn-only |
| MUT/Michigan-Left | arterial left (both directions) | arterial left bay becomes a third through lane |

This single-geometry-multiple-connection-list pattern (shared with
`build-diverging-diamond-interchange`) is what makes every downstream comparison
clean — nothing except the movement bans differs, so any measured effect is
attributable to the geometry treatment.

**U-turn storage = crossover spacing, unless you deliberately build a separate bay.**
With no separate median storage bay, the U-turn lane's usable length is simply the
segment between `J` and the crossover — so a crossover-spacing sweep is
*simultaneously* a detour-length sweep and a storage-length sweep, and the two effects
cannot be separated from that data alone. State this confound explicitly rather than
attributing a spacing effect to detour length only.

## Verify geometry from the COMPILED net, never the input

Per-variant, per-spacing checklist against the compiled `.net.xml` (don't trust the
input connection XML — `netconvert` can silently drop or reshape connections):

1. **Banned movements have zero connections at `J`** in the compiled net, and every
   intended-allowed movement is present *and signal-controlled* (no accidentally
   uncontrolled movement).
2. **Each crossover compiles to a genuine U-turn**: `dir="t"`, `state="m"`, and it
   survives `--no-turnarounds true` (which suppresses every *other* turnaround) — the
   U-turn exists only because it was explicitly declared as a connection.
3. **The yield relationship is the intended one.** Decode the junction request/foe
   matrix with `sumolib` (`node.forbids`, `node.areFoes`): the U-turn link should yield
   to the opposing through movements, and nothing should yield to the U-turn (an
   unsignalized median crossover is realistically always yield-controlled against the
   arterial through stream — it has no meaningful priority case). Read back junction
   types (`traffic_light` at `J`, `priority` at the crossovers) to confirm.

## Making the comparison OD-fair, not route-fair

Define **one** OD matrix (movement-share splits, including a genuinely mixed
minor-street through/left/right share so RCUT actually bites) and run `od2trips`
**once**. Then run `duarouter` **independently per variant** against that variant's
own compiled net, so each variant's route set reflects only its own legal movements —
reusing one variant's route file for another is the "route-fair" mistake this skill
exists to avoid. Verify OD-fairness directly: routed vehicle-id set equals the trips
id set, every departure time matches, every OD pair keeps its exact trip count, and no
OD pair silently vanished (`duarouter --ignore-errors` will otherwise drop unroutable
trips with no loud failure). Confirm the resulting path-length signature changes
*only* on the OD classes whose movement was actually banned, by exactly the added
detour distance, and nothing else moves.

## Sizing each variant's signal independently

Measure saturation flow and startup lost time **on this junction's own geometry** (see
`measure-saturation-flow-and-validate-webster-method`), then derive each variant's
Webster cycle/phase plan from **that variant's own movement volumes** — counted from
that variant's own route file, at `J`, not from an assumed count. **Rerouted traffic
passes `J` twice and must be counted twice**: an RCUT minor-left vehicle enters as a
minor-street trip, exits via the forced right turn, U-turns, and passes back through
`J` as an arterial through movement — omitting the return pass understates that phase's
volume. Verify the resulting phase count is a *consequence* of the geometry (RCUT's
minor-through/left ban should let its main-junction plan collapse toward 2 phases;
MUT's arterial-left ban should shed exactly the arterial protected-left phase while
leaving the minor plan's phase count untouched, since MUT doesn't touch the minor
street) — check this by reading the ACTIVE program back via TraCI, and verify every
phase is conflict-free against the compiled foe matrix, not just assumed correct
because Webster produced it.

## Sweeping and instrumenting the crossover as a bottleneck

Sweep crossover spacing (e.g. 100/200/400/800 m) crossed with total demand and
minor-street demand share. Instrument the crossover-approach edges with
`laneAreaDetector`s and separate **three distinct failure signatures** — they have
different causes and different fixes, so report them separately rather than as one
"crossover congestion" number:

1. **Storage overflow** — the U-turn lane's queue reaches the full segment length
   (jam length / storage length -> 1.0) for a large fraction of the analysis window.
2. **Spillback onto the arterial through lanes** — measure the *other* lanes of the
   same edge (which carry no U-turn traffic) independently; nonzero queue there when
   the U-turn lane is overflowing is spillback contaminating through traffic.
3. **Yield-gap starvation** — an unsignalized U-turn's maximum single-vehicle halting
   duration can reach tens of minutes even without storage overflow, because a vehicle
   is failing to find an acceptable gap in the arterial stream, not queueing behind a
   signal. Compare against the conventional design's equivalent lane (which should show
   ~0 s) as a control.

**Sensitivity to spacing is monotone while the crossover doesn't overflow (more
spacing = more detour distance = worse) and non-monotone once it does (more spacing =
more storage = dramatically better)** — don't assume a single direction of effect
across the whole swept range.

**Signalising an overflowing/yield-starved crossover is not a general fix.** It only
helps the specific failure mode of gap starvation (forcing a red onto the conflicting
through stream lets the U-turn clear); on a storage-limited or already-gridlocked
crossover it makes total travel time *worse* by adding unnecessary delay to the
arterial through stream. Test both regimes before generalizing either way, and watch
for a survivorship trap in the completed-trip count when comparing "improved" mean
travel time under signalisation — more vehicles finishing (including previously-stuck
ones) can *raise* the mean survivor time even as total system performance improves.

## Decomposing the VMT/VHT trade-off per movement class

Report the headline result (network-mean dVMT vs. d-mean-total-time, both signed) but
**always decompose by OD movement class** (arterial-through/left/right, minor-
through/left/right) reporting both distance and time per class — the network mean can
hide (or, worse, misrepresent) a highly uneven distributional effect. **RCUT is
expected to transfer delay from the arterial onto minor-street users** (the banned
minor movements pay a large detour+delay penalty while every arterial class gains);
**MUT is expected to concentrate its entire cost on the one banned class** (arterial
left pays a real but modest penalty while every other class, including the *un-banned*
minor-street movements, gains). Confirm this signature rather than assuming it.

## Finding the thresholds, not just one demand point

Sweep minor-street demand share and crossover spacing to find the sign-change
threshold(s) where each design stops winning — report the threshold explicitly
(interpolated between bracketing tested points), not just a single favorable cell.
**RCUT and MUT can be near-complementary in demand share** (RCUT favored at low minor
share, MUT favored at high minor share) — check for this pattern rather than assuming
one design dominates the other everywhere. At high demand the governing question flips
from "signal efficiency vs. detour cost" to "does the crossover survive at all" —
report both regimes separately since they have different failure mechanisms.

## Checking the textbook conflict-point claim against measured foe-matrix counts AND simulated SSM

Count conflict points directly from the compiled net's own foe matrix (crossing = foe
pairs between different approach/exit combinations; merging = per exit edge, feeding
approaches minus one; diverging = per approach, served exits minus one) — don't just
cite the textbook "32 -> 14" figure, derive it. **Because both crossovers exist
physically and identically in every variant, their own conflict points do not
disappear or move anywhere — they are constant across variants, latent/unused in the
conventional design and only carrying real traffic once a design forces movements
through them.** The correct framing of "32 -> 14" is therefore that N points are
genuinely eliminated at the main junction and the system total nets against
already-existing-but-previously-unused crossover points — not that points physically
"relocate." Cross-check the conflict-point-matrix claim against actually **simulated**
conflicts (SSM device, TTC/DRAC/PET) rather than treating the topological count alone
as a safety claim: an undersaturated cell can show the conflict-point reduction
translating cleanly into fewer/less-severe simulated conflicts, while a congested cell
can show the *opposite* ranking because simulated conflict counts get swamped by
stop-and-go link queueing that has nothing to do with the junction's own geometry —
normalize SSM rates per 1000 vehicle-km when variants differ in total VMT, or a
higher-VMT design will look artificially worse.

**Watch for a degenerate SSM artifact at the U-turn merge specifically**: the
collinear geometry of a vehicle merging from a U-turn lane into the arterial stream it
is completing a U-turn into can produce `type="111"` ("collision") SSM encounters with
`minTTC = 0.00`/`PET = NA` even though SUMO's own collision counter reports zero
actual collisions across every run. This is the same artifact class documented in
`compare-unsignalized-intersection-control-types` for collinear opposing lefts,
recurring at a structurally similar collinear-merge geometry. Flag and count these
separately, and **verify your own downstream rate/table columns actually exclude
them** if you claim to exclude them — it is easy to disclose the artifact in prose
while still computing the headline table from an unfiltered field.

## Validity discipline (project standard, applied here)

- **CRN, measured not assumed**: pair by seed across variants and measure the
  variance-reduction factor per cell — it can be large (10-70x) in an uncongested
  regime and near-zero or even negative in a congested one, where paired correlation
  itself can turn negative.
- **Teleport-artifact / survivorship check** (see
  `validate-congested-scenario-results-against-teleport-artifacts`): at the highest
  demand/tightest-spacing cells, check whether a design's apparent "win" or "loss" is
  teleport-insensitive by sweeping `--time-to-teleport`, and always report the
  completed-trip count alongside any mean-time comparison — a design that completes a
  small fraction of trips can post a *better* mean time than a design completing 100%,
  purely from survivorship censoring.
- **Every reported "win" should have both arms at (or very near) 100% completion.**
  If a design's headline number rests on a partial-completion cell, label it explicitly
  as a survivor mean, not a clean comparison.
- **Route-choice robustness needs a positive control.** Testing whether drivers would
  "naturally" reroute through a U-turn under a live rerouting device (rather than the
  ban forcing them to) is a legitimate check, but a "zero vehicles rerouted" result is
  ambiguous between "the alternative genuinely isn't competitive" and "the rerouter
  never fired at all" (a real, previously-documented SUMO failure mode — see
  `simulate-incident-rerouting`'s gotchas on rerouter misconfiguration). Confirm the
  device is actually altering *some* vehicle's route in the scenario (inspect
  `vehroute-output` for any vehicle with more than one `<route>` element) before
  treating a zero-uptake result as validated.

## Gotchas

- **`--xml-validation never` silently suppresses additional-file output devices.**
  With that flag set, `laneAreaDetector`/`edgeData` output files are created but left
  completely empty (zero `<interval>` elements), with no error or warning at all.
  Removing the flag from an otherwise-identical run produces the expected output.
  Reproduced deterministically in both directions — if a detector output file exists
  but is suspiciously empty, check for this flag before assuming the detector itself
  is misplaced.
- **A `tlLogic` loaded from an additional file cannot reuse `programID="0"`** if the
  network already has a program with that ID — SUMO raises `Error: Another logic with
  id '<junction>' and programID '0' exists`. Load the override under a different
  `programID` (SUMO activates the last-loaded program for that junction), and **verify
  the active program at run time via TraCI** (`traci.trafficlight.getProgram`) rather
  than assuming the override took effect just because SUMO didn't error.
- **Storage length and crossover spacing are the same variable if you don't build a
  separate median bay** — a spacing sweep is inseparably also a storage-length sweep
  unless you deliberately decouple them.
- **Movement volumes for signal sizing must be counted from each variant's own route
  file, including the return pass of rerouted traffic through the main junction** —
  undercounting this understates the phase serving that return movement.

## Related

- `build-diverging-diamond-interchange` — the shared-topology-vary-one-thing pattern,
  compiled-net foe-matrix verification, and completed-vs-still-running counting
  discipline this skill directly reuses, applied to a grade-separated design instead
  of an at-grade one.
- `design-left-turn-storage-bay-length` — the overflow-vs-blockage/spillback
  bottleneck-instrumentation pattern this skill's crossover-instrumentation section
  extends with a third failure mode (yield-gap starvation) specific to an
  unsignalized median crossover.
- `compare-unsignalized-intersection-control-types` — the compiled-net foe-matrix
  control-type verification methodology, and the source of the collinear-opposing-left
  SSM artifact class this skill's U-turn-merge artifact belongs to.
- `convert-od-matrix-to-trips` / `convert-trips-to-routes` — the od2trips/duarouter
  workflow this skill's OD-fair-per-variant-routing methodology is built on.
- `measure-saturation-flow-and-validate-webster-method` — the measured (not assumed)
  saturation-flow/lost-time inputs this skill's independent per-variant Webster sizing
  depends on.
- `analyze-intersection-safety-with-ssm` — the SSM device setup and TTC/PET/DRAC
  schema this skill's simulated-conflict cross-check uses.
- `quantify-sumo-run-to-run-variability` / `validate-congested-scenario-results-against-teleport-artifacts` — the CRN and teleport/survivorship validity disciplines applied throughout.
- `simulate-incident-rerouting` — source of the rerouter-misconfiguration failure mode
  this skill's route-choice-robustness positive-control check guards against.
- [[rcut-and-michigan-left-alternative-intersection-design]] — the verified VMT/VHT
  trade-off finding, redistribution-of-delay finding, threshold results, and corrected
  conflict-point/SSM analysis this skill's methodology produced.
