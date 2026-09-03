---
summary: A reservation-based Autonomous Intersection Management (AIM) controller in SUMO, verified to achieve a genuinely measured (not assumed) zero-collision guarantee after a four-part race-condition bug was found and fixed, beats a well-tuned actuated signal at low demand but becomes dramatically worse than even an all-way stop above roughly 600 veh/h/approach because a denied reservation forces a per-vehicle full stop instead of a signal's per-platoon loss; mixed autonomy degrades non-monotonically, with every tested penetration level worse than both pure regimes; a batching reservation policy beats FCFS on equity only in a narrow demand window at a real delay cost, while both AIM policies are more equitable than a signal at every demand tested; AIM achieves zero collisions while showing dramatically fewer severe surrogate-safety conflicts than signals (buying its margin with delay, not tight clearances); and the collision-free guarantee has a sharp communication-latency/position-noise cliff rather than a gradual degradation.
keywords:
  - autonomous-intersection-management
  - AIM
  - reservation-based-control
  - signal-free-intersection
  - connected-automated-vehicles
  - mixed-autonomy
  - surrogate-safety-measures
created: 2026-08-02T17:30:00
last_updated: 2026-08-02T17:30:00
sources:
  - "[[episodic-memory/2026-08-02_17-00-00/outputs/FINDINGS.md]]"
  - "[[episodic-memory/2026-08-02_17-00-00/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[unsignalized-vs-signalized-intersection-control]]"
  - "[[surrogate-safety-measures]]"
  - "[[actuated-traffic-signals]]"
  - "[[max-pressure-signal-control]]"
related_skills:
  - implement-reservation-based-autonomous-intersection-management
  - implement-maxpressure-traci-controller
  - control-signals-with-actuated-tls
  - analyze-intersection-safety-with-ssm
  - compare-unsignalized-intersection-control-types
related_skills_for_graph_view:
  - "[[implement-reservation-based-autonomous-intersection-management]]"
  - "[[implement-maxpressure-traci-controller]]"
  - "[[control-signals-with-actuated-tls]]"
  - "[[analyze-intersection-safety-with-ssm]]"
  - "[[compare-unsignalized-intersection-control-types]]"
---

# Autonomous Intersection Management: Safety and Performance Envelope

Reservation-based Autonomous Intersection Management (AIM) replaces a traffic
signal entirely with a TraCI infrastructure agent that grants each approaching
connected/automated vehicle a time-space reservation through the junction. This
page documents a rigorously verified test of whether AIM genuinely delivers on its
central promise (collision-free, signal-free crossing) and how it compares to
well-tuned signalized control across demand, mixed autonomy, reservation policy,
and safety metrics.

## Verified finding: the zero-collision guarantee is real, but getting there required finding and fixing a genuine four-part bug

A naive reservation implementation is not automatically safe. Development of one
tested AIM controller surfaced a real collision in mixed-autonomy traffic, which
root-caused to **four separate, compounding defects**, not one: (1) a race where a
human-driven-vehicle control window could open on top of an already-committed
automated vehicle, which SUMO's own collision detection does not catch once a
vehicle is operating under disabled right-of-way checks; (2) a deferred-phase
mechanism that was not self-terminating, letting fresh automated-vehicle requests
perpetually starve human traffic; (3) a presence-detector radius sized too
generously to ever genuinely read empty, causing 100% control time for human
traffic and mass non-arrival of automated vehicles; (4) an unprotected permissive
movement leaving a human-driven vehicle waiting unchecked inside the junction's
internal lanes. **Fixing only the first-discovered cause would have left the system
still unsafe** — all four had to be addressed. After the fix, the zero-collision
claim was established as **measured, not assumed**: a negative control with the
fix's interlock deliberately disabled reproduced over 100 real collisions at a
single demand level on the identical network, and a fix-scoping verification
(re-running every previously-passing configuration and byte-comparing output before
and after the fix) confirmed the fix didn't perturb any already-correct behavior.
**The same defect class — clearing a conflict area on a timer instead of verified
occupancy — was independently found in an unrelated signalized baseline controller**
(a max-pressure TraCI controller that skipped its program's all-red clearance),
reinforcing that "clear on occupancy, not a timer" is a general principle for any
custom junction controller, signal-based or reservation-based.

## Verified finding: AIM's demand-scaling advantage reverses sign — it can be worse than a stop sign

Comparing AIM against a well-tuned actuated signal across a demand sweep found AIM
winning decisively at low demand but its advantage **reversing sign** above roughly
600 vehicles/hour/approach in the tested configuration, becoming dramatically worse
than even the simplest possible unsignalized control (an all-way stop) at the
highest tested demand. The mechanism, confirmed from the controller's own
instrumentation: the junction was genuinely at capacity, but a denied reservation
forces the requesting vehicle to a **full stop**, converting what a signal handles
as a per-*platoon* start-up delay into a per-*vehicle* reservation-denial delay —
a structurally worse scaling behavior under saturation. **AIM's low-demand
advantage should not be assumed to persist or scale gracefully into congested
conditions; it should be tested across the full demand range**, since the
mechanism that makes it efficient when uncongested (no waiting for an unrelated
phase to finish) becomes a liability once genuine capacity constraints bind.

## Verified finding: mixed autonomy degrades non-monotonically — every mixture is worse than either pure extreme

Sweeping human-driven-vehicle penetration with a hybrid fallback (a virtual
signal-like phase serving human traffic, interleaved with reservation-controlled
automated traffic) found delay is **not monotonic or even simply super-linear** in
penetration — **every tested mixed-autonomy configuration performed worse than
both the all-human and all-automated pure regimes**, with as little as 5% automated
penetration roughly tripling delay relative to the all-human baseline in one tested
condition. The practical implication: the "penetration threshold" question is not
"how much automation is needed before AIM starts helping" but rather that **any
partial penetration can be actively harmful relative to no automation at all**,
until penetration reaches a point close to complete. This should temper any
deployment expectation that AIM benefits phase in gradually as automated-vehicle
adoption grows — the transition period itself may be the worst regime, not a
smooth interpolation between the two ends.

## Verified finding: reservation-policy equity is real but narrow, and both AIM policies beat a signal on equity

Testing first-come-first-served (FCFS) against a batching/platoon-forming
reservation policy under unbalanced (e.g. 80/20 major/minor) approach demand found
batching improved an explicit equity statistic (a Gini coefficient across
approaches) meaningfully only in a **narrow demand window**, and only at a real
delay cost — outside that window, the difference between the two policies was not
statistically significant, and FCFS was **not** shown to be unstable (contradicting
a natural prior that first-come-first-served must starve a minority approach under
sustained imbalance). **A separate, more decisive equity finding**: both tested
AIM reservation policies were substantially **more equitable than the signalized
baseline at every demand level tested** — a fixed-time or actuated signal
structurally denies an entire approach's green time on a cycle regardless of
relative demand, while a reservation scheme (even simple FCFS) services every
request in arrival order, which turns out to produce a flatter delay distribution
across approaches than a signal does.

## Verified finding: AIM's zero collisions and its surrogate-safety profile point the SAME direction here — it buys margin with delay, not with tight clearances

A natural hypothesis is that a reservation system achieves collision-free crossing
by deliberately compressing spatial/temporal margins in a way that would still
register as elevated conflict risk on a surrogate safety measure (SSM) like
time-to-collision, even without a real collision. **This was tested directly and
found not to hold** in the tested configuration: AIM showed dramatically **fewer**
severe simulated conflicts (near-zero TTC-under-threshold events) than either
signalized baseline (which logged roughly a hundred such events per run), because
the tested AIM implementation's mechanism for guaranteeing safety was to hold
vehicles back (accept delay) rather than to thread them through small gaps. **This
is a genuinely non-obvious result and should not be assumed to generalize** — a
different reservation implementation with a smaller safety buffer or a more
aggressive scheduling policy could plausibly show the opposite pattern (tight
clearances rather than delay) — but it demonstrates that "zero collisions" and
"deliberately-compressed spatial margins reading as elevated SSM conflict" are not
the same claim, and both should be measured independently for a given
implementation rather than one being inferred from the other.

## Verified finding: the collision-free guarantee has a sharp communication-realism cliff, not a gradual degradation

Injecting request/actuation latency and position noise into the reservation
pipeline found the collision-free guarantee breaks **sharply, not gradually**:
collision count jumped from zero to a large number at a single control step's
worth of latency (or roughly a meter of position error in the tested
configuration), then barely changed further as the imperfection grew an order of
magnitude larger. Adding an explicit compensating distance margin (proportional to
`speed x latency` plus a multiple of the position-noise standard deviation)
meaningfully extended the safe operating range but did not eliminate the cliff —
beyond a certain latency, the control loop itself is too stale for any
stopping-distance-style margin to compensate. **A related measurement trap**: with
collisions configured to warn rather than remove vehicles, a naive delay metric
computed only over arriving vehicles can *improve* as the collision rate rises,
because a collision effectively deletes the very queuing constraint that was
causing delay — any communication-realism sensitivity result must report collision
count alongside delay, never delay alone.

## Practical takeaways

- Do not deploy reservation-based AIM as a general capacity-improvement measure —
  test the full demand range explicitly, since the advantage at low demand can
  reverse to a real disadvantage (worse than an all-way stop) under saturation.
- Do not assume partial automated-vehicle penetration is a safe, gradually-improving
  intermediate state — test the full penetration range, since a mixed-autonomy
  regime can be worse than either pure extreme.
- Test a reservation policy's equity properties under genuinely unbalanced demand
  with an explicit statistic, and compare against the signalized alternative's own
  equity, not just against a different reservation policy.
- Measure collision count and surrogate safety measures independently — one is not
  a reliable proxy for the other, and the direction of any divergence should be
  measured, not assumed.
- Treat a reservation controller's zero-collision claim as unverified until backed
  by a negative control (proving the collision-checking pathway genuinely fires)
  and a fix-scoping verification (proving a bug fix didn't perturb already-correct
  behavior).
- Budget an explicit distance margin for communication latency and position error,
  and specify a hard maximum acceptable latency — beyond it, no margin helps.

See `implement-reservation-based-autonomous-intersection-management` for the full
conflict-set-derivation, reservation-agent, mixed-autonomy-fallback, and
communication-realism-testing methodology, including the specific four-part bug
and its fix.
