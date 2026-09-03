---
name: build-rolling-horizon-traffic-forecast-with-state-warm-start
description: Use this skill when the user wants to understand SUMO's --save-state/--load-state semantics (what is and isn't restored, whether a save-load-continue run is reproducible), build a rolling-horizon simulation-based short-term traffic forecaster ("digital twin") that warm-starts from sensor-assimilated state, or is deciding whether a microsimulation-based forecast is actually worth building versus a naive persistence/historical-average baseline. Covers a critical, high-impact measurement trap — restoring a saved state's <flowState> onto a different route file silently double-counts demand — plus verified findings on what state serialization does and does not preserve (traffic-light phase bookkeeping corrupts on round-trip; detector accumulators are never saved; meso and micro states are mutually unloadable), and an honest negative result: a full microsimulation twin can deliver essentially zero forecast skill beyond a historical average during a non-recurrent incident, despite running the "real" model. Trigger on mentions of save-state, load-state, digital twin, rolling-horizon forecast, traffic prediction, or warm-started simulation.
---

# Build a Rolling-Horizon Traffic Forecast with State Warm-Start

**A microsimulation "digital twin" built from real state serialization can
deliver essentially zero forecast skill beyond a historical average during
exactly the event (a non-recurrent incident) it would be most valuable
for.** Verified on a 5 km freeway corridor, 5 CRN-replicated ground-truth
days, 770 rolling-horizon forecast runs, and a from-scratch, first-in-memory
verification of SUMO's `--save-state`/`--load-state` mechanism.

## State serialization: what is and is not preserved

A saved state (`<snapshot type="micro">`) holds route, vType, and
per-vehicle records (position/speed/angle/lateral position/internal
state/distance/waiting time/lane-change state, with `<stop>` and
`<device>` children), lane occupancy (as a lane's child element, not an
attribute), pending flow schedules (`flowState`), routing-engine edge
weights, and `tlLogic` programs. RNG state and edge-control internals are
saved **only** with `--save-state.rng`.

**A save-load-continue run is NOT bit-identical to an uninterrupted
run** — verified: the two summary outputs diverge at the very first
comparable timestep after the load, even with `--save-state.rng` set.
Checked the mechanism from both directions: on a fully **deterministic**
scenario (zero speed dispersion, fixed-period flows), the *only*
divergence source is float-precision truncation in the saved state file
— `--save-state.precision` at its default (2 decimal digits) left 11 of
599 vehicles with a differing trip duration (max difference 4 s);
raising precision to 6 or 12 eliminated every difference (0/599, exactly
0.0 s max). On a **stochastic** scenario, precision is nearly irrelevant
(the fraction of identically-reproduced vehicles moved only from 5.1% to
7.1% going from precision 2 to 6) — there, un-restorable internal RNG
stream state dominates, confirmed by a round-trip test: reloading a
state and immediately re-saving it at the same simulation time changes
the recorded RNG counters (route-handler and insertion-control stream
positions both advanced), because `--load-state` still re-parses the
entire route file on load rather than resuming from a frozen point.
**Always use `--save-state.precision 6` or higher and `--save-state.rng`
as defaults for any warm-start workflow**, and design comparisons
paired-by-seed rather than assuming a save-load-continue run reproduces
its uninterrupted counterpart.

**Traffic-light phase bookkeeping is genuinely corrupted on round-trip,
even though the logic itself and actuated-detector state restore
exactly.** Verified from raw before/after state XML: a static program's
stored `duration` attribute changed from a real cycle length (40000 ms)
to the absolute load timestamp (1750000 ms); an actuated program's
`cycleTime` reset from its true value (33000 ms) to 0. The absolute next
switch time itself, however, is preserved and the next phase change
still occurs on schedule — the corrupted fields are cosmetic bookkeeping,
not functional state, but any code that reads them directly (rather than
trusting SUMO's own scheduling) will see wrong values.

**"Cosmetic" holds only while SUMO schedules the program itself. Under
TraCI control the corruption is functional.** Probed at every decision by
`implement-predictive-rolling-horizon-signal-control`: phase index and
absolute next-switch time restore **100%** correctly, but
`getSpentDuration` (elapsed time in the current phase) comes back **0.0
against a true 6.0 s**, matching in **0.00%** of post-switch samples. Any
min-green enforcement reading SUMO's phase clock after a load therefore
believes the green just started. **Workaround: drive the phase wholly
externally (`setPhase` + a large `setPhaseDuration`) and carry elapsed
green in your own state.** Note a probe that samples only the *first*
decision after startup cannot detect this — the shadow has been on phase
0 since t=0, so elapsed green trivially equals simulation time.

**Detector accumulators are never saved at all** — no E1/E2/E3 elements
appear in the state file under any tested option. Two consequences,
verified: (1) an E1/E2 detector's aggregation-interval boundaries
re-base at the exact load instant, producing **zero overlap** with the
original run's bin boundaries whenever the reload time is not an exact
multiple of the aggregation period; (2) an E3 (entry-exit) detector
loses its in-flight vehicle set entirely, producing "left detector
without entering" warnings for every vehicle that was mid-detection at
save time (48 occurrences on one tested static-signal run, 27 on an
actuated one).

**`--load-state.offset` does not move the simulation clock** — it
subtracts the given offset from timestamps stored inside the state file
itself (vehicle depart times, etc.), without changing when the
simulation resumes. A negative offset can produce a *negative* reported
trip duration in `tripinfo`, since a vehicle's stored depart time can end
up later than its actual completion time. `--begin` alone is silently
ignored if it disagrees with the state's own recorded time; combining a
negative offset with `--begin 0` does rebase the clock but breaks route
continuity for any vehicle whose route depends on edges not present at
the new nominal time. **`--load-state.remove-vehicles` works as
documented** — named vehicles present in a normal continuation's
`tripinfo` are absent from the vehicle-removed run's, and are booked as
"ended" exactly at the load instant.

**Mesoscopic and microscopic states are mutually unloadable** — loading
a microscopic state under `--mesosim`, or a mesoscopic state under the
default engine, both fail immediately (`Invalid vehicles in state (may be
a micro/meso state)!`). A mesoscopic forecasting pipeline needs its own,
entirely separate chain of saved states; you cannot switch engines
mid-chain.

## The critical trap: restoring `<flowState>` onto a different route file double-counts demand

Every active `<flow>` element's pending schedule is captured in the saved
state's `flowState` and — when the state is loaded — **keeps emitting
vehicles from that schedule regardless of what route file is supplied at
load time.** Forking a forecast run from a ground-truth state directly
onto the forecast's own (necessarily different) demand file caused the
corridor's first-bin inflow to spike **+44.8%** above the true value (449
vs. 310 vehicles) and the mean inflow across the forecast window to run
**+14.0%** high. **Fix: strip `<flowState>` from any state before
forking it onto a route file different from the one that generated the
state.** After stripping, the same comparison matched ground truth to
within about 1–3% (mean −1.3% first bin, −2.5% mean) — the small residual
is genuine assimilation noise, not double-counting. This fix must be
applied **unconditionally on every fork**, but must be **skipped** when
genuinely continuing the same route file (e.g. advancing the twin's own
forecast chain), since there the restored flow IDs are the correct,
still-active ones and stripping them would silently truncate legitimate
future demand.

### Two refinements from a controlled fork matrix

Re-tested by `implement-predictive-rolling-horizon-signal-control` with a
clean design (900 veh/h flow, fork at t=600 s, 120 s window, **30
departures expected**) across *both* the TraCI `loadState` and CLI
`--load-state` paths, and independently reproduced:

| fork configuration | TraCI `loadState` | CLI `--load-state` |
|---|---|---|
| forecast flow has its **own id**, `begin`=fork, unstripped | **60 (exactly double)** | **60 (exactly double)** |
| same, **stripped** | **30 (correct)** | **30 (correct)** |
| forecast **re-declares the same flow id** | 30 | 30 |
| continuing the same chain, unstripped | 30 | 30 |
| continuing the same chain, **stripped** | **102–143 (back-filled)** | **30** |

**(a) The double count needs the forecast's flow ids to *differ* from the
state's.** Matching ids merge into the restored schedule and produce no
inflation — so re-declaring the same id is an alternative to stripping.

**(b) The "never strip when continuing the same file" rule is
specifically a TraCI-path hazard.** A warm TraCI process back-fills the
insertions it missed while the state was being forked (102–143 vs 30);
the CLI path does not (30). On the CLI, stripping the same file is
merely unnecessary rather than harmful.

Sidestep entirely by writing demand as explicit `<vehicle>` elements —
the state then contains no `flowState` at all.

**Designing this test is easy to get wrong.** An earlier attempt
concluded the *opposite* (that stripping breaks the correct case, and
that TraCI and CLI differ on the double count). Both were artifacts: its
two route files used **different flow ids**, making double-counting
structurally impossible, and both flows began at `t=0` while the fork was
at `t=600`, so what it measured was a new flow back-filling 600 s of
missed insertions — which *masked* the real double count. Match the flow
id deliberately in one arm, and set the forecast flow's `begin` at the
fork time.

## A second, smaller pending-vehicle trap: a short route file is read to EOF at t=0

A route file that ends before the simulation horizon is fully parsed at
load time, meaning a vehicle scheduled to depart far in the future can
already appear as a "pending" (not-yet-departed) vehicle inside a saved
state taken long before its real departure — in this study, an
incident-triggering vehicle showed up in every ground-truth state from
roughly 75 minutes before it actually entered the network. **This can let
a "perfect state" oracle used for error decomposition see an upcoming
incident far too early**, contaminating exactly the analysis meant to
isolate state-initialization error from demand-forecast error. Fix:
apply `--load-state.remove-vehicles` for any not-yet-departed vehicle
before forking a state for use as an oracle. The measured effect size in
this study was modest but non-negligible and metric-dependent: roughly
0–1.3% RMSE change on the aggregate corridor-travel-time metric, but up
to roughly 38% on an isolated speed metric for the single segment nearest
the incident — check per-metric, not just on an aggregate summary,
before concluding a leak like this doesn't matter.

## The headline result: forecast skill is mostly negative, and a positive-looking incident-period score is an illusion

Scoring the twin's corridor-travel-time predictions against persistence
(last observed value holds) across 5/10/15/30-minute horizons: during
the **recurrent-congestion period**, the twin never significantly beat
persistence (skill scores of roughly −0.56, −0.05, +0.10, and a
significantly *worse* −0.54 at the 30-minute horizon). During the
**incident period**, the twin's apparent skill scores looked more
favorable at several horizons — but this is an artifact, not real
skill: the twin's incident-period RMSE stayed essentially **flat** across
all four horizons (roughly 361, 362, 362, 353 seconds) because it is
entirely **blind** to the incident (it only knows what its sensor
assimilation told it at forecast-issue time), while persistence's error
instead **grew sharply** with horizon (roughly 283, 393, 446, 337
seconds) because the true corridor kept diverging further from its
pre-incident value. **The twin only "wins" because the baseline gets
worse, not because the twin gets better.** Scored against a historical
average instead — a baseline that also doesn't know about the incident —
the twin's incident-period skill collapsed to essentially zero (scores of
roughly +0.002, −0.001, −0.001, +0.023): during a non-recurrent event, a
full microsimulation twin driven only by sensor-assimilated state
delivered no more forecast value than knowing the historical average
pattern. Congested-extent predictions make the same point directly: at
every short/medium forecast horizon the twin predicted zero congestion
throughout the incident window while true congestion ran 500–1250 m; the
only exceptions were two 30-minute-horizon forecasts issued *before* the
incident occurred, which instead saturated at a maximum-value ceiling
rather than reading zero — a different failure mode (an overshoot
artifact), not evidence the twin somehow anticipated the event.

## Where forecast error actually comes from: a clean horizon-dependent crossover

Decomposing forecast error via two oracle variants — one given the true
future demand but only assimilated (imperfect) initial state, the other
given the true (perfect) initial state but only forecast (imperfect)
future demand — found a clean crossover during the recurrent-congestion
period: **state-initialization error dominates at short horizons** (5–10
minutes; RMSE roughly 4 s vs 36 s at 5 minutes with demand held perfect
vs state held perfect respectively — i.e. state error is small and
demand error is what's left when state is perfect... report both
oracles' own RMSE directly, not a subtraction, since the two error
sources are not simply additive) and **demand-forecast error dominates at
longer horizons** (15–30 minutes), crossing over somewhere between 10
and 15 minutes in this study's geometry and demand profile. During the
**incident period**, state-initialization error overwhelms at every
tested horizon — unsurprising, since the entire incident is itself a
state fact the twin's own forecast demand cannot supply. The irreducible
error floor (both state and demand held perfect) was still nonzero and
grew with horizon (a few seconds at 5 minutes, tens of seconds by 30
minutes in this study) — even a perfectly-initialized, perfectly-demanded
microsimulation twin carries genuine simulation noise that limits
achievable forecast accuracy.

## Computational feasibility: microsimulation is not the bottleneck here, and mesoscopic mode costs accuracy without buying anything needed

A single rolling-horizon forecast cycle (state advance plus the forecast
run itself) used well under 2% of its 300-second forecasting budget in
every tested demand regime (roughly 0.8–1.8%, achieved real-time factor
several hundred to nearly a thousand), measured via a serial (uncontended)
benchmark — a naive parallel-sweep timing measurement was contaminated by
resource contention and should not be used as the primary feasibility
figure. **Switching to mesoscopic mode bought a real 4–7× speedup that
this scenario did not need, at a substantial accuracy cost**: mesoscopic
forecasts were systematically *worse* than microscopic ones on this
uncontrolled freeway corridor (negative skill scores throughout the
recurrent period), and — notably — **in the opposite bias direction**
from a prior verified finding on a signalized grid, where mesoscopic mode
was found to be systematically *optimistic* (underestimating delay).
Here it ran systematically *pessimistic* instead. **Mesoscopic mode's
accuracy bias direction is not a fixed property of the engine — it
depends on the facility type and control regime being simulated, and
should be checked per-application rather than assumed from a prior
result on a different network.**

## Gotchas

- `--save-state.times T` does not fire if the simulation's `--end` is
  exactly `T` — run one step past the intended save time.
- Use `--save-state.precision 6` (or higher) and `--save-state.rng` as
  defaults for any warm-start workflow; the default precision alone
  introduces measurable, avoidable divergence.
- Strip `<flowState>` when forking a state onto a different route file;
  never strip it when continuing the same one.
- Remove not-yet-departed vehicles from a state before using it as a
  "perfect initial state" oracle, or a route file that parses to EOF at
  load time can leak future events into the state far earlier than they
  should be visible.
- Detector aggregation windows re-base at the load instant with no
  overlap guarantee against a pre-save run's windows — recompute detector
  bin boundaries relative to the load time, don't assume continuity.
- A mesoscopic and a microscopic saved state cannot be interchanged — a
  mesoscopic forecasting pipeline needs its own independent state chain.

See `emulate-and-evaluate-partial-sensor-traffic-state-estimation` for
the sensor-emulation and space-mean-speed methodology this skill's
assimilation step reuses, `quantify-sumo-run-to-run-variability` for the
CRN/paired-replication design used throughout, and
`run-mesoscopic-simulation` for the mesoscopic engine mechanics whose
accuracy-bias direction this skill found to be facility-dependent rather
than universal.
