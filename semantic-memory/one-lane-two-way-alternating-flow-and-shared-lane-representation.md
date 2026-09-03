---
summary: SUMO has no native primitive for a shared bidirectional lane, so a one-lane two-way work-zone crossing must be built from spatially coincident opposing edges with mutual exclusion enforced entirely by control logic — and verified independently via FCD, because --collision-output reports zero collisions even when two 5m vehicle bodies occupy the exact same chainage; measured capacity degrades with the lost-time fraction (not length directly), Webster's closed-form optimal-cycle formula overshoots by up to 37% when clearance time dominates the cycle while numerically minimizing its own delay function still tracks simulation to within about 13%, and actuated/flagger/pilot control that looks catastrophically worse than pretimed at a long work zone is mostly a max-green-cap confound — controlling for an equal cap shows actuated converges to pretimed while flagger and pilot retain a genuine, large, highly significant advantage.
keywords:
  - one-lane-two-way
  - alternating-flow
  - flagger
  - pilot-car
  - shared-bidirectional-lane
  - portable-traffic-signal
  - mutcd-part-6
  - clearance-interval
created: 2026-08-05T20:00:00
last_updated: 2026-08-06T23:54:30
sources:
  - "[[episodic-memory/2026-08-05_20-00-00/outputs/representation/representation_tests.json]]"
  - "[[episodic-memory/2026-08-05_20-00-00/outputs/representation/headon_separation.json]]"
  - "[[episodic-memory/2026-08-05_20-00-00/outputs/verification/mutual_exclusion.json]]"
  - "[[episodic-memory/2026-08-05_20-00-00/outputs/verification/mutual_exclusion_true_clearance_correction.json]]"
  - "[[episodic-memory/2026-08-05_20-00-00/outputs/verification/clearance_mechanism.json]]"
  - "[[episodic-memory/2026-08-05_20-00-00/outputs/saturation/saturation_summary.json]]"
  - "[[episodic-memory/2026-08-05_20-00-00/outputs/saturation/lost_time.json]]"
  - "[[episodic-memory/2026-08-05_20-00-00/outputs/data/table_E9_capacity_vs_length.csv]]"
  - "[[episodic-memory/2026-08-05_20-00-00/outputs/data/table_E7_capacity_probe.csv]]"
  - "[[episodic-memory/2026-08-05_20-00-00/outputs/data/table_E3_cycle_sweep.csv]]"
  - "[[episodic-memory/2026-08-05_20-00-00/outputs/data/table_E1_paired_vs_pretimed.csv]]"
  - "[[episodic-memory/2026-08-05_20-00-00/outputs/data/table_E8_equal_greencap.csv]]"
  - "[[episodic-memory/2026-08-05_20-00-00/outputs/data/table_E4_maxgreen.csv]]"
  - "[[episodic-memory/2026-08-05_20-00-00/outputs/data/table_E2_failure_envelope.csv]]"
  - "[[episodic-memory/2026-08-05_20-00-00/outputs/data/table_E6_safe_clearance_cost.csv]]"
related_pages:
  - "[[freeway-work-zone-capacity-closure-representation-and-merge-control]]"
  - "[[webster-method]]"
  - "[[opposite-direction-overtaking-mechanics]]"
  - "[[sumo-stochastic-variability-and-replication-design]]"
  - "[[two-lane-highway-follower-density-and-passing-lane-effectiveness]]"
  - "[[hcm-control-delay-vs-sumo-delay-metrics]]"
  - "[[corridor-access-management-twltl-representation-and-density-effects]]"
related_skills:
  - control-one-lane-two-way-alternating-flow-through-a-work-zone
  - design-and-control-freeway-work-zone-lane-closures
  - measure-saturation-flow-and-validate-webster-method
  - model-opposite-direction-overtaking
  - quantify-sumo-run-to-run-variability
  - evaluate-corridor-access-management-and-median-treatments
related_skills_for_graph_view:
  - "[[control-one-lane-two-way-alternating-flow-through-a-work-zone]]"
  - "[[design-and-control-freeway-work-zone-lane-closures]]"
  - "[[measure-saturation-flow-and-validate-webster-method]]"
  - "[[model-opposite-direction-overtaking]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[evaluate-corridor-access-management-and-median-treatments]]"
---

# One-Lane Two-Way Alternating Flow and Shared-Lane Representation

A rural two-lane highway work zone where one direction's lane is closed
forces both directions to alternate through the single remaining lane —
one of the most common temporary-traffic-control configurations in
practice, and one SUMO has no built-in primitive for. This page records
how to represent the shared segment, why SUMO's own safety output cannot
be trusted to verify it, and how capacity/delay/control-strategy
comparisons behave when clearance time is a large fraction of the cycle.

## Representing the shared segment

A literal single edge routed in both directions is not routable at all —
SUMO rejects it (`no valid route`), since an edge has one direction by
construction. SUMO's opposite-direction driving (`lcOpposite`) on a single
lane ID works for a short, sparse blockage (verified: 37 distinct
vehicles used the opposite lane past one stationary blocker, min
separation 9.25 m, zero collisions, with no signal at all — LC2013's own
gap acceptance did the exclusion) but fails outright as a full
work-zone representation: chaining blockers across the full length left
every opposing vehicle stranded, because LC2013 will not commit to an
overtake with no return gap.

**The defensible representation is spatially coincident opposing one-lane
edges** (`spreadType="center"` **plus** `--geometry.avoid-overlap false`
— the flag is required too; `spreadType="center"` alone still offsets
each edge's shape by half a lane width, verified from the compiled net),
with mutual exclusion enforced entirely by the control logic and verified
externally, never assumed. A side-by-side `<neigh>` build behaves
identically under every control arm tested but misrepresents the shared
geometry.

## SUMO's own collision detector is worthless here — verify from FCD instead

Because the two directions occupy **different lane IDs** even when their
shapes coincide, SUMO has no cross-edge conflict detection off a
junction. **`--collision-output` reported zero collisions in every run in
this study, including runs deliberately built to fail** (all-red
clearance forced to 0.5 s as a positive control). Re-scanning the raw FCD
of that positive-control run directly found two 5 m vehicle bodies at the
exact same chainage — true physical separation 0.00 m, i.e. −5.0 m of
clearance once vehicle length is subtracted — and SUMO's own collision
counter still read zero. **This is a structural SUMO limitation to design
around, not a network-authoring bug**: a shared bidirectional lane built
from two same-shape edges will never trigger SUMO's collision detector
regardless of how badly the control logic fails.

**Get the FCD-scan geometry right, not just its existence.** Reconstruct a
common chainage for both directions (eastbound position = `pos`;
westbound position = `wz_len − pos`), then compute the minimum
**absolute** separation `|chain_EB − chain_WB| − vehicle_length` between
every simultaneously-present pair. Do not minimize a *signed* gap instead
— that statistic is dominated by well-separated pairs that happen to be
"crossed" in chain order (reflecting how deep each direction's queue has
built, not physical proximity) and can report a large, physically
meaningless negative number while missing a genuine same-position
coincidence. In this study, a signed-gap scan initially reported "−466.73 m
clearance" for one run, which traced to two vehicles that were actually
**461.73 m physically apart**; re-scanning the same raw FCD with the
correct `|a−b|` metric found the run's true worst moment was the −5.0 m
full-body coincidence described above — a real, severe violation the
signed statistic had missed entirely.

## The clearance-interval formula under-estimates the required time

`r = (L_wz + vehicle_length) / v_wz` assumes a vehicle already travelling
at the posted work-zone speed. Under short actuated greens, the last
vehicle to enter is still accelerating out of a standing queue (measured
entry speed 9.98 m/s at a 400 m zone and 8.88 m/s at 1600 m under actuated
control, versus 11.52 m/s and 10.86 m/s under pretimed at the same
demand, both below the 12.5 m/s posted work-zone speed), and a
`speedFactor` floor as low as 0.75 makes it worse — producing measurable
FCD overlap violations at both tested lengths even though the programmed
intergreen ran exactly as designed. **Sizing the clearance on the
speedFactor floor**, `r_safe = (L_wz + vehicle_length + internal_length) /
(0.75 × v_wz) + margin`, eliminated every violation.

The safe clearance is not free everywhere, though the cost is
concentrated rather than pervasive: across 12 tested demand/length/arm
cells, throughput differences reached statistical significance in 6, but
5 of those 6 were small (≤3.6%, two of them actually higher throughput
under the safe clearance). One cell showed a genuinely large cost: **1600 m
zone, 900 veh/h, actuated control: −14.45% throughput (p=0.0002) and
+139% delay (p=0.0004)** — a real safety-vs-capacity trade under a short
max-green cap.

## Capacity degrades with the lost-time fraction, not with length directly

Measured saturation flow **s = 1820 veh/h** (green-duration regression,
R² = 0.997), startup lost time **l₁ = 1.25 s**, and only **0.72 s of a
5.5 s yellow** usable for discharge (SUMO drivers are near-perfectly
compliant, unlike HCM's mixed-compliance assumption). At a fixed 300 s
cycle with a permanently-queued probe, capacity fell from 1627.8 veh/h
(100 m zone, lost-time fraction 0.111) to 156.9 veh/h (1600 m zone,
fraction 0.911) — an independently-implemented analytic model using the
same measured parameters matched this to within roughly 0.02–3.5% at
every tested length. **Holding lost-time fraction constant by scaling
cycle length with work-zone length leaves capacity nearly invariant to
length instead** (1197–1242 veh/h across the same 100–1600 m range):
length costs capacity only through the cycle length needed to amortise
its clearance time, and that required cycle is what becomes operationally
impossible in practice.

## Webster's closed form breaks down when lost time dominates

The Webster closed-form optimal cycle `C = (1.5·L + 5)/(1 − Y)`
progressively overshoots the true simulated delay-minimizing cycle as
lost time grows relative to the cycle — up to a **+37% overshoot** at the
longest, most heavily loaded tested cell. But numerically minimizing
**Webster's own delay function** over a cycle grid, rather than solving it
in closed form, tracked the true simulated optimum to within roughly
−13%/+9% at every tested cell — the delay *model* survives this regime;
only the closed-form shortcut for finding its minimum does not. The
optimum is also **sharp, not flat**: only 1–3 of 10 grid points tested
fell within 5% of the true minimum in every cell — a work-zone signal
timing plan needs real numerical optimization, not a rough closed-form
estimate, once clearance time is a large share of the cycle.

## Actuated/flagger/pilot control: the length reversal is a max-green-cap confound

At short work zones (100–400 m), responsive control clearly wins — flagger
cut delay 38.7% at 100 m/1200 veh/h and 18.6% at 400 m/1200 veh/h (both
p<0.001) at no measurable throughput cost. At a long work zone (1600 m),
the same comparison reverses completely — actuated, flagger, and pilot
control all showed dramatically higher delay and lower throughput than
pretimed at 1600 m/1200 veh/h (delay up roughly 300–540%, throughput down
30–48%, all p≤0.0043).

**This reversal is a comparison confound, not a genuine control-logic
failure.** The original comparison ran the three responsive arms under a
120 s MUTCD-style max-green cap while pretimed ran an *uncapped*
Webster-optimal cycle (1231 s at the worst tested cell). Re-running
pretimed capped at the same 120 s green gives 846.6 veh/h served (versus
1203.1 veh/h uncapped — a 29.6% loss from the cap alone), and at that
equal cap, **actuated converges to within about 0.8% of pretimed** (839.8
vs 846.6 veh/h). Flagger and pilot, however, **retain a genuine, large,
highly significant residual advantage even at the identical cap**: +16.9%
throughput (p<1e-7) and +35.2% throughput (p<1e-11) respectively over
capped pretimed at the same cell — their control logic (measure-and-wait
clearance for the flagger; convoy speed for the pilot) genuinely differs
from a fixed-green signal, not merely because of the cap. **Always
equalize the max-green cap before concluding responsive control beats or
loses to pretimed at a long work zone.**

## The MUTCD max-green cap costs real capacity at long, heavily loaded zones

A 120 s cap is capacity-neutral at short, lightly-loaded zones but costs
measurable throughput at a long, heavily-loaded one: **1600 m/900 veh/h,
120 s cap: −6.71% throughput (p=0.0065)** relative to a 240 s cap, with
the cost growing sharply as the cap tightens further (−20.9% at 90 s,
−38.8% at 60 s, −51.0% at 45 s, −63.5% at 30 s, all significant).

## Failure envelope and a safety flag independent of capacity failure

An uncapped pretimed signal never failed to serve demand anywhere in the
tested 200–1400 veh/h × 100–1600 m range — but only by growing the cycle
to as long as 1818 s (30 minutes) at the worst cell, not a deliverable
real-world design. A realistically capped actuated signal (120 s) does
fail at specific cells (800 m at 1400 veh/h: 80.7% served; 1600 m at
1000/1200/1400 veh/h: 85.2%/70.9%/60.5% served).

A separate safety threshold is crossed well before any capacity failure:
measured maximum queue length exceeded a 300 m MUTCD-style
advance-warning-sign distance at demand levels far below the failure
envelope — as low as 600 veh/h two-way at a 1600 m work zone. Check queue
length against advance-warning sign placement independently of any
capacity or delay metric.

## Gotchas

- Do not model a pilot car via `traci.vehicle.add` + `moveTo` into a
  standing queue — this produced genuine SUMO-detected collisions in a
  smoke test. Cap the platoon leader's speed instead.
- A parallel sweep that re-invokes `netconvert` to a shared output path
  can truncate a sibling worker's in-progress network file — verified via
  a `net.xml` parse-error traceback matching this signature. Use a
  distinct output path per worker plus a serial pre-build pass.
- Oversaturated delay in a fixed-horizon run is not stationary — report
  still-running vehicle counts alongside any such figure.
- A capacity number measured from actual (non-saturating) demand is
  demand-limited, not a capacity measurement — label it as such.

See `control-one-lane-two-way-alternating-flow-through-a-work-zone` for
the full build/verification/control-comparison workflow, and
[[freeway-work-zone-capacity-closure-representation-and-merge-control]]
for the representation-first discipline this page's shared-lane approach
extends to a two-way facility.
