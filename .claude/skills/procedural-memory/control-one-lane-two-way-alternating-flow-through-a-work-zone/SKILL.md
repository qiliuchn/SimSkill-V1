---
name: control-one-lane-two-way-alternating-flow-through-a-work-zone
description: Use this skill when the user wants to model a rural two-lane highway work zone where one direction's lane is closed and both directions must alternate through a single shared lane (portable traffic signals, a flagger, or pilot-car/convoy operation), needs to represent a shared bidirectional lane in SUMO (which has no native primitive for this), or wants to know whether Webster's closed-form cycle-length formula still applies when clearance time is large relative to the cycle. Covers why SUMO's --collision-output cannot be trusted as a safety check for this configuration, the correct FCD-based verification method, why actuated/flagger/pilot control can be dramatically WORSE than pretimed at long work zones (and why that reverses to dramatically better at short ones), and how to measure saturation flow/lost time/critical clearance directly instead of assuming HCM/MUTCD defaults. Trigger on mentions of one-lane two-way, alternating flow, flagger, pilot car, portable traffic signal, temporary traffic control, MUTCD Part 6, or shared bidirectional lane.
---

# Control One-Lane Two-Way Alternating Flow Through a Work Zone

**SUMO has no native primitive for a shared bidirectional lane**, and its
`--collision-output` cannot be trusted to catch a failure of whatever
representation is chosen. Verified on 1110 CRN-replicated runs (1.99M
vehicles) across two representations and four control strategies.

## Representing the shared segment: three attempts, one defensible choice

- **A literal single edge with vehicles routed both directions is not
  routable at all** — SUMO rejects it outright (`Error: Vehicle ... has no
  valid route`) because a single edge has one direction by construction.
- **SUMO's opposite-direction driving (`lcOpposite`) on a single lane ID
  works, but only for a short, sparse blockage** — verified with one
  stationary blocker on the work-zone lane: 37 distinct opposing vehicles
  genuinely used the opposite lane to pass it, min head-on separation
  9.25 m, zero collisions, with no signal control at all (LC2013's own gap
  acceptance did the exclusion). **It fails outright as the production
  representation of a full-length work zone**: chaining blockers across
  the full segment length left every opposing vehicle stranded (0 of the
  batch ever committed to the opposite lane — LC2013 will not commit to an
  overtake with no return gap).
- **The defensible choice is spatially coincident opposing one-lane
  edges** (`spreadType="center"` with **`--geometry.avoid-overlap
  false`** — the avoid-overlap flag is required too; `spreadType="center"`
  alone still shifts each edge's shape by half a lane width, verified from
  the compiled net, 1.60 m off-centre each side instead of both at
  y=0.00), with mutual exclusion enforced entirely by the control logic
  (signal, flagger, or pilot) and verified externally via FCD, never
  assumed. A side-by-side `<neigh>` build behaves identically under every
  control arm tested but misrepresents the shared geometry — prefer
  coincident edges for a shared lane specifically.

## SUMO's own collision detector is worthless for this representation — verify from FCD instead

Because the two directions occupy **different lane IDs** even when their
shapes coincide, SUMO has no cross-edge conflict detection off a junction
— **`--collision-output` reported zero collisions in every test run in
this study, including runs deliberately built to fail.** A positive
control (all-red clearance forced down to 0.5 s) produced genuine,
severe physical violations — two 5 m vehicle bodies at the *exact same
chainage* (true separation 0.00 m, i.e. −5.0 m of clearance once vehicle
length is subtracted) on both the coincident and `<neigh>` builds — and
SUMO's own collision counter still read zero throughout. **This is not a
network-authoring bug to fix; it is a structural SUMO limitation to design
around**: a shared bidirectional lane built from two same-shape edges will
never trigger SUMO's collision detector regardless of how badly the
control logic fails.

**Verify with your own FCD scan, and get the geometry of the check right.**
Reconstruct a common chainage for both directions (eastbound position =
`pos`; westbound position = `wz_len − pos`), then compute the minimum
**absolute** separation `|chain_EB − chain_WB| − vehicle_length` between
every simultaneously-present pair, every frame. **Do not use a signed gap**
(`chain_WB − chain_EB`) and take its minimum — that statistic is dominated
by well-separated pairs that happen to be "crossed" in chain order (one
direction's vehicle has a numerically larger chainage than the other's,
which just reflects how many vehicles have queued on each side, not
physical proximity) and can read as a huge, physically meaningless
negative number while missing a genuine same-position coincidence
entirely. Verified in this study: a signed-gap scan of one actuated,
1600 m run reported "−466.73 m clearance," which traced to two vehicles
that were **461.73 m physically apart**; re-scanning the identical raw
FCD with true `|a−b|` found the run's actual worst moment was two vehicle
bodies at the exact same position (true clearance −5.0 m, i.e. full-body
coincidence) — a real, severe, and more informative violation the signed
statistic had missed.

## The clearance interval formula under-estimates the required time

The textbook `r = (L_wz + vehicle_length) / v_wz` assumes a vehicle
already travelling at the posted work-zone speed. **Under short actuated
greens the last vehicle to enter is still accelerating out of a standing
queue** — measured entry speed 9.98 m/s (400 m zone) and 8.88 m/s (1600 m
zone) under actuated control, versus 11.52 m/s and 10.86 m/s under
pretimed at the same demand, both below the posted 12.5 m/s work-zone
speed — and a `speedFactor` distribution with values as low as 0.75 makes
it worse still. This produced measurable FCD overlap violations at both
lengths under actuated control despite the programmed intergreen running
exactly as designed (SUMO did not shorten it). **Size the clearance on the
speedFactor floor**, `r_safe = (L_wz + vehicle_length + internal_length) /
(0.75 × v_wz) + margin`, which eliminated every violation in both tested
lengths.

**The safe clearance is not free.** Across 12 tested demand/length/arm
cells, throughput differences reached statistical significance in 6, but
5 of those 6 were small (≤3.6%, two of them actually *higher* throughput
under the safe clearance). One cell showed a real, large cost: **1600 m
work zone, 900 veh/h, actuated control: −14.45% throughput (p=0.0002) and
+139% delay (p=0.0004)** — a genuine safety-vs-capacity trade under a
short max-green cap, not a free correction.

## Measure saturation flow and lost time directly — don't assume HCM defaults

Measured from an oversaturated gate (rear-bumper crossings via
`instantInductionLoop`, `actionStepLength` pinned to 1.0 s): saturation
flow **s = 1820 veh/h** (green-duration regression, R² = 0.997), startup
lost time **l₁ = 1.25 s**, and only **0.72 s of a 5.5 s yellow interval**
usable for discharge (SUMO drivers are near-perfectly compliant, so almost
none of the yellow is "wasted" the way HCM assumes for mixed real-world
compliance) — giving lost time per phase = l₁ + (yellow − e) + all-red =
6.03 s + all-red.

## Capacity degrades with the LOST-TIME FRACTION, not with length directly

At a fixed 300 s cycle and demand-saturated (permanently-queued) probe,
capacity fell from 1627.8 veh/h (100 m zone) to 156.9 veh/h (1600 m zone)
as lost-time fraction rose from 0.111 to 0.911 — and an independently
implemented analytic model (same measured s, l₁, e, plus the geometric
clearance formula) matched measured capacity to within roughly 0.02–3.5%
at every tested length. **Holding lost-time fraction constant (~0.33) by
scaling cycle length with work-zone length instead leaves capacity nearly
invariant to length** (1197–1242 veh/h across the same 100–1600 m range)
— length only costs capacity through the cycle length needed to amortise
its clearance time, and that cycle length is what becomes operationally
impossible at real work zones (see the failure envelope below).

## Webster's closed form breaks down when lost time dominates — minimize the delay function numerically instead

The Webster closed-form optimal cycle `C = (1.5·L + 5)/(1 − Y)`
progressively **overshoots** the simulated delay-minimizing cycle as lost
time grows relative to the cycle — from negligible error at a short,
lightly-loaded zone up to a **+37% overshoot** at the longest, most heavily
loaded tested cell. But the **argmin of Webster's own delay function**,
evaluated numerically over a cycle grid rather than solved in closed form,
tracked the true simulated optimum to within roughly −13%/+9% at every
tested cell — the delay *model* survives large lost time; only the
closed-form *shortcut* for finding its minimum does not. **The optimum is
sharp, not flat**, in this regime: only 1–3 of 10 grid points tested fell
within 5% of the true minimum in every cell — the opposite of the usual
"flat near the optimum" folklore, meaning a work-zone signal timing plan
needs real optimization, not a rough closed-form estimate.

## Actuated/flagger/pilot control: decisively better at short zones, catastrophically worse at long ones — and the reversal is a confound, not a real control-logic failure

At a short work zone (100–400 m), responsive control clearly wins:
flagger cut delay 38.7% at 100 m/1200 veh/h and 18.6% at 400 m/1200 veh/h
(both p<0.001) with no measurable throughput cost. **At a long work zone
(1600 m), the same comparison reverses completely** — actuated, flagger,
and pilot control all showed dramatically *higher* delay and *lower*
throughput than pretimed (e.g. at 1600 m/1200 veh/h: delay up
roughly 300–540% across the three arms, throughput down 30–48%, all
p≤0.0043).

**This reversal is a comparison confound, not a genuine control-logic
failure — verified by re-running the comparison at an equalized cap.**
The original comparison ran the three responsive arms under a 120 s
MUTCD-style max-green cap while pretimed ran an *uncapped* Webster-optimal
cycle (1231 s at the worst tested cell) — an enormous, unequal handicap.
Re-running pretimed capped at the same 120 s green gives 846.6 veh/h
served (vs. 1203.1 veh/h uncapped — a 29.6% loss from the cap alone), and
under that equal cap, **actuated converges to within about 0.8% of
pretimed** (839.8 vs 846.6 veh/h) — essentially no difference once the cap
is equalized. Flagger and pilot, however, **retain a genuine, large,
highly significant residual advantage even at the identical cap**: +16.9%
throughput (p<1e-7) and +35.2% throughput (p<1e-11) respectively over
capped pretimed at the same 1600 m/1200 veh/h cell — because their control
logic (measure-and-wait clearance for the flagger; convoy speed for the
pilot) genuinely differs from a fixed-green signal, not merely because of
the cap. **Always control for the max-green cap before concluding
responsive control beats or loses to pretimed at a long work zone.**

## The MUTCD max-green cap costs real capacity, and the cost scales sharply with work-zone length

A 120 s cap (a realistic MUTCD compliance ceiling) is capacity-neutral at
short, lightly-loaded zones but costs measurable throughput at a long,
heavily-loaded one: **1600 m/900 veh/h, 120 s cap: −6.71% throughput
(p=0.0065)** relative to a 240 s cap — with the cost growing sharply as
the cap tightens further (−20.9% at 90 s, −38.8% at 60 s, −51.0% at 45 s,
−63.5% at 30 s, all significant).

## Failure envelope and a safety flag independent of capacity failure

An uncapped pretimed signal, allowed to run any cycle length Webster's
equation demands, **never failed to serve demand anywhere in the tested
200–1400 veh/h × 100–1600 m range** — but only by growing the cycle to as
long as 1818 s (30 minutes) at the worst cell, which is not a deliverable
real-world design. A realistically capped actuated signal (120 s) **does
fail** at specific, identifiable cells (800 m at 1400 veh/h: 80.7% served;
1600 m at 1000/1200/1400 veh/h: 85.2%/70.9%/60.5% served).

**A separate safety threshold is crossed well before any capacity
failure.** Measured maximum queue length exceeded a 300 m MUTCD-style
advance-warning-sign distance at demand levels far below the failure
envelope — as low as **600 veh/h two-way at a 1600 m work zone** — meaning
the advance-warning sign itself would be overrun by queued traffic long
before the facility statistically fails to serve demand. Check queue
length against sign placement distance independently of any capacity or
delay metric; queue-length values that pin at the modeled approach length
indicate storage exhaustion, not the true (larger) queue.

## Gotchas

- **Do not model a pilot car by inserting a literal escort vehicle via
  `traci.vehicle.add` + `moveTo` into a standing queue** — this produced
  genuine SUMO-detected collisions in a smoke test. Model the pilot as a
  hard speed cap (e.g. 8.33 m/s) on the platoon leader instead.
- **A parallel sweep that re-invokes `netconvert` to a shared output path
  can truncate a sibling worker's in-progress network file** — a real race
  condition hit in this study (confirmed via a `net.xml` parse-error
  traceback matching the signature), fixed with an explicit per-worker
  output path and a serial pre-build pass before the parallel sweep.
- **Oversaturated delay in a fixed-horizon run is not stationary** — some
  vehicles are still in the network when the run ends; report and account
  for still-running vehicle counts alongside any oversaturated delay
  figure rather than treating it as steady-state.
- A capacity number measured from actual demand (not a permanently-queued
  probe) is demand-limited, not a capacity measurement — label it as such.

See `design-and-control-freeway-work-zone-lane-closures` for the
representation-first discipline and queue-build capacity-probe method this
skill extends to a two-way facility, `measure-saturation-flow-and-validate-webster-method`
for the saturation-flow/lost-time measurement and Webster methodology
reused here, `model-opposite-direction-overtaking` for the `lcOpposite`/
`--opposites.guess` mechanics behind the T2/T3 representation tests, and
`quantify-sumo-run-to-run-variability` for the CRN-paired replication
design used throughout.
