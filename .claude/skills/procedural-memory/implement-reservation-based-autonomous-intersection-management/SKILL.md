---
name: implement-reservation-based-autonomous-intersection-management
description: Use this skill when the user wants to implement signal-free, reservation-based Autonomous Intersection Management (AIM) in SUMO for connected/automated vehicles — a TraCI infrastructure agent that grants each approaching vehicle a time-space reservation through the junction instead of using a traffic light, enforced via setSpeed/setSpeedMode with junction right-of-way checks disabled inside the control zone. Covers deriving the genuine reservation conflict set from the compiled net's foe matrix, verifying a hard zero-collision safety guarantee with a negative control, mixed-autonomy fallback control for human-driven vehicles (and its race-condition failure mode), reservation-policy design (FCFS vs. batching) and equity, and communication-latency/position-noise sensitivity testing. Trigger on mentions of autonomous intersection management, AIM, reservation-based intersection control, signal-free intersection, connected automated vehicle intersection, or "replace the traffic light."
---

# Implement Reservation-Based Autonomous Intersection Management (AIM)

Builds a TraCI infrastructure agent that replaces a traffic signal entirely: instead
of a phase plan, approaching automated vehicles request and receive a time-space
reservation through the junction, and the agent enforces that no two vehicles with
conflicting reservations are ever physically present in a shared conflict zone at
the same time. This is a fundamentally different control paradigm from every signal
skill in memory (`control-signals-with-actuated-tls`,
`implement-maxpressure-traci-controller`, etc.) — there is no phase, no green/yellow/
red cycle, and (at full penetration) no reason for a vehicle to ever stop at all.

## Deriving the genuine reservation conflict set

Do not assume a conflict table from geometry — decode it from the **compiled** net's
junction request/response foe matrix (the same technique `compare-unsignalized-
intersection-control-types` uses for right-of-way verification), and self-check the
decoding against structural invariants (e.g. every movement conflicts with itself;
conflict is symmetric; a movement's foe set size is consistent across equivalent
lanes). Two movements are reservation-conflicting if and only if their compiled foe
bits say so — not because they "look like" they cross geometrically. For pipelining
(letting genuinely non-conflicting streams share time slots rather than fully
serializing every request), further decompose each foe pair into the specific
conflict **point** (an arc-length position within the junction) where the paths
actually intersect, so a reservation only needs to lock the shared point, not the
entire junction, for the overlap duration.

## The reservation agent and enforcement mechanism

Each approaching vehicle sends a request (via a TraCI polling loop reading vehicle
position/speed/route — the vehicle doesn't need to "know" anything, the
infrastructure agent tracks it). The agent computes an arrival-time/trajectory
assignment such that no two vehicles holding conflicting reservations (per the
decoded conflict set) overlap in time at a shared conflict point, plus a
configurable **safety buffer**. Enforce the assigned trajectory via `setSpeed`/
`slowDown` (accelerate/hold/decelerate to hit the assigned arrival time) with
`setSpeedMode` used to **disable junction right-of-way checks specifically inside
the control zone** (SUMO's default safety checks assume normal right-of-way rules
that don't apply once a vehicle is operating under an external reservation), then
**restore normal speed mode on exit**. Verify the enforcement mechanism actually
took effect — don't just assume `setSpeedMode` bits mean what you think; test with
a deliberately unsafe reservation config and confirm collisions genuinely appear
(see Verification below).

## Verification: a hard, measured zero-collision guarantee

**"Zero collisions" must be a measured result, not an assumed one.** Run a negative
control with the reservation-conflict interlock deliberately disabled (or a known
scheduling bug reintroduced) and confirm the *same* network under the *same* demand
produces real, nonzero collisions — this proves the collision-checking pathway you're
relying on for the "zero" claim actually fires, rather than being silently disabled
or simply never triggered by the tested scenario. In one verified case, disabling the
interlock produced over 100 junction collisions at a single demand level on a network
that showed zero with it enabled — strong evidence the zero is load-bearing, not
vacuous.

**Also include a safety-buffer negative control**: sweep the configurable safety
buffer from very small to very large and confirm (a) zero collisions at every buffer
size and (b) delay/efficiency degrades **monotonically and continuously** as the
buffer grows, eventually crossing an all-way-stop reference — a reservation system
with an absurdly conservative buffer should be *worse* than the simplest possible
unsignalized control, and confirming this is a sanity check on the whole reservation
math, not just a curiosity.

**When a genuine collision bug is found during development, root-cause it fully
before declaring victory on a fix.** Verified case: a single visible collision
traced back to not one but **four separate compounding defects** (see Gotchas below)
— fixing only the first-discovered cause left the system still unsafe under
different conditions. After any fix, **prove it didn't perturb behavior that was
already correct**: re-run every previously-passing configuration and byte-compare
its output (e.g. `tripinfo` records) against the pre-fix version — identical output
proves the fix is correctly scoped to the failure mode it targets, not a change with
unintended side effects elsewhere.

## Mixed autonomy: a hybrid fallback, and its own race-condition risk

For mixed autonomy (some human-driven vehicles present), a common design is a
**hybrid fallback**: reserve a virtual signal phase for human-driven vehicles,
interspersed with the reservation-controlled flow for automated vehicles. **This
fallback boundary is itself a genuine collision risk, not just an efficiency
question, and deserves the same hard verification as the core reservation logic.**
Verified failure mode: a race where a new human-driven-vehicle "green window" could
open while an automated vehicle was still committed to (or physically occupying) a
conflicting movement — and once that automated vehicle is inside the junction under
disabled right-of-way checks, SUMO's own collision detection does not catch the
resulting conflict either, since the vehicle is "supposed to" be there. **A phase
serving human-driven vehicles must only open when no automated vehicle currently
holds or occupies a conflicting reservation** — check both the reservation table and
actual occupancy, not just one.

**A related pitfall: a deferred phase-open decision must be self-terminating.**
If a human-driven-vehicle phase is deferred because an automated vehicle holds a
conflicting reservation, and new automated-vehicle requests keep re-acquiring the
very conflict points being waited on, the deferral can starve human traffic
indefinitely. Fix by having the deferred request immediately claim a pending lock on
the conflict points it's waiting for, so it wins the next available opportunity
rather than being perpetually out-competed by fresh requests.

**A gap-out/handback detector needs a genuinely reachable "zero" condition.** If a
human-vehicle-presence detector's range is set too generously (e.g. covering the
full visible approach), it may never actually read zero under realistic traffic,
causing a phase serving human vehicles to never hand back control — verified case:
a 90 m detection radius that was never empty caused 100% green time for human
traffic and mass non-arrival of automated vehicles. Size the detection zone tightly
enough that it genuinely empties under normal conditions, and pair it with a
demand-proportional maximum window so control returns even if the detector never
clears.

**Defense in depth for permissive movements**: a permissively-controlled
human-driven movement (e.g. an unprotected left) can leave a vehicle waiting
*inside* the junction's internal lanes, where nothing else checks it once an
automated vehicle is already committed under disabled right-of-way. Add an explicit
speed cap on any committed automated vehicle so it stops short of any conflict point
shared with a currently-occupied human-driven movement, as a backstop independent of
the reservation/handback logic above.

## Reservation policy: FCFS vs. batching, and equity

First-come-first-served (FCFS) is the textbook baseline reservation policy. Test it
explicitly for fairness under unbalanced approach demand (e.g. an 80/20 major/minor
split) using an explicit inequality statistic (e.g. a Gini coefficient across
approaches or vehicle classes) — don't assume FCFS is fair just because it's
first-come-first-served; sequencing by arrival time on an unbalanced network can
still produce very uneven waiting outcomes. **Test a batching/platoon-forming policy
(granting consecutive same-direction requests together, amortizing the safety-buffer
overhead across a group) as an explicit alternative**, and compare on both delay and
the equity statistic — expect batching to trade some delay for equity, but check
whether that trade is significant at every demand level, or only in a specific
window; don't generalize a single-demand-level result. **Also compare against a
signalized baseline's own equity** — a reservation-based scheme, even simple FCFS,
can turn out to be substantially *more* equitable than a fixed-time or actuated
signal, since a signal structurally denies an entire approach's green time on a
fixed cycle regardless of relative demand, while a reservation scheme services every
request in arrival order.

## Safety metrics: collisions vs. surrogate safety measures point in different directions

**Do not assume a zero-collision result also means the best surrogate-safety-measure
(SSM) profile — measure both, and expect them to potentially diverge, in either
direction.** A reservation system that achieves genuine zero collisions by design can
still show *better or worse* SSM conflict counts (TTC/PET/DRAC) than a signal,
depending on how it buys its safety margin. Verified case: a reservation system
bought its zero-collision guarantee with **delay**, not tight clearances — it showed
dramatically *fewer* severe simulated conflicts than either signalized baseline
(essentially zero severe TTC events vs. roughly a hundred per run), because vehicles
were held back rather than squeezed through small gaps. This is a genuinely
non-obvious result worth checking rather than assuming — a reservation scheme's
mechanism (assign non-overlapping time-space slots with a buffer) is not
automatically the same thing as "compressed spatial margins," and the actual
tradeoff should be measured, not presumed. Check for the collinear-opposing-
movement SSM artifact documented in `compare-unsignalized-intersection-control-types`
when reporting any AIM-vs-signal SSM comparison.

## Communication realism: find the breaking point, don't just assume perfection

A reservation scheme's collision-free guarantee assumes instantaneous, perfect
information about every vehicle's position and intent. **Test this assumption
explicitly** by injecting request/actuation latency and position noise, and find the
level at which the first collision appears. Expect a **cliff, not a gradient**:
verified case found collision count jumped from zero to over a hundred (across a
handful of replications) at a single control step's worth of latency, or at roughly
a meter of position noise, then barely changed further as the imperfection grew an
order of magnitude larger — the guarantee doesn't degrade gracefully, it has a sharp
threshold. **Test an explicit compensating margin** (e.g. reserving extra distance
proportional to `speed * latency + k * position_noise_stddev`) and re-measure the
breaking point — expect it to meaningfully extend the safe range but not eliminate
the cliff entirely, since beyond some latency the control loop itself becomes too
stale for any distance margin to compensate.

**Watch for a specific reporting trap**: if collisions are configured as
`--collision.action warn` (rather than removing/teleporting the colliding vehicles),
a delay metric computed only from arriving vehicles can *improve* as collisions
increase, because a collision effectively deletes the very constraint that was
causing delay (a stuck, conflict-avoiding vehicle collides and both vehicles'
resulting trajectories may clear the junction "faster" in a delay sense than a
safely-negotiated one would have). **Never report delay from a collision-testing
sweep without reporting the collision count in the same table** — a delay
improvement alongside a rising collision count is not a real improvement.

## Gotchas

- **A denied reservation forces a full stop, converting a per-platoon signal loss
  into a per-vehicle reservation loss.** Don't assume reservation control's
  advantage over a signal holds at every demand level — it can be strongly
  demand-dependent and can *reverse sign* at high demand, where the junction is
  genuinely at capacity: a signal serves an entire platoon on one green, while a
  denied-reservation vehicle stops individually, multiplying the start-up delay cost
  per vehicle rather than per group.
- **Mixed autonomy can degrade non-monotonically, not just proportionally to
  human-vehicle share** — a small fraction of automated vehicles mixed into
  otherwise-human traffic can produce *worse* delay than either the all-human or
  all-automated extreme, because the reservation logic and the human-vehicle
  fallback interfere with each other in a way that doesn't scale smoothly with
  mixing ratio. Sweep a genuinely fine-grained penetration range rather than
  assuming a simple linear or super-linear interpolation between the two pure
  regimes.
- **"Clear on a timer" is unsafe wherever "clear on occupancy" is available** — this
  is the single most important, most transferable lesson: any interval meant to
  guarantee a conflict zone is empty (a signal's all-red, a reservation buffer, a
  mixed-autonomy handback) should be verified against actual measured occupancy of
  the relevant lanes/points, with a timer only as a floor or a safety cap, never as
  the sole clearance mechanism.
- **A collision negative control and a fix-scoping verification (byte-comparing
  previously-correct output before and after a fix) are not optional extras for a
  safety-critical controller** — they are what distinguishes a measured zero from an
  assumed one, and what distinguishes a properly-scoped fix from one that might have
  broken something else.
- **`--collision.action warn` can make delay metrics lie during a
  deliberately-unsafe sensitivity sweep** — always report collision count alongside
  any delay number from such a sweep.

## Related

- `compare-unsignalized-intersection-control-types` — the compiled-net foe-matrix
  decoding technique this skill's conflict-set extraction directly reuses, and the
  source of the collinear-opposing-movement SSM artifact to check for.
- `implement-maxpressure-traci-controller` — the closed-loop TraCI control-loop
  pattern (phase/movement mapping, minimum-interval enforcement, clearance
  transitions) this skill's reservation agent follows the same architectural
  discipline as; a real missing-all-red-clearance safety defect was found in that
  skill's own controller while building this skill's baseline comparison, and fixed
  using the same "clear on occupancy, not a timer" principle this skill independently
  arrived at.
- `control-signals-with-actuated-tls`, `measure-saturation-flow-and-validate-webster-method` — the native-actuated and Webster fixed-time baselines this skill's AIM controller is compared against.
- `analyze-intersection-safety-with-ssm` — the SSM device setup used for this
  skill's collision-vs-surrogate-safety divergence test.
- `get-vehicles-state` / `set-vehicle-state` — the read/write TraCI primitives this
  skill's reservation agent is built from.
- `quantify-sumo-run-to-run-variability` / `validate-congested-scenario-results-against-teleport-artifacts` — the CRN and teleport/completion validity discipline applied throughout this skill's demand sweeps.
- [[autonomous-intersection-management-safety-and-performance-envelope]] — the
  verified demand-scaling sign reversal, non-monotonic mixed-autonomy degradation,
  reservation-policy equity findings, safety-vs-delay tradeoff finding, and
  communication-realism breaking point this skill's methodology produced.
