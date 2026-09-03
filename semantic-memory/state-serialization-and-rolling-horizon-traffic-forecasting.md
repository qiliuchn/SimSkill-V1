---
summary: SUMO's --save-state/--load-state mechanism is not bit-identical across a save-load-continue cycle (deterministic scenarios diverge from float-precision truncation alone, fixable via --save-state.precision; stochastic scenarios diverge mainly from unrestored RNG streams), traffic-light phase bookkeeping corrupts on round-trip while detector accumulators are never saved at all, and restoring a state's <flowState> onto a different route file silently double-counts demand (+44.8% first-bin inflow) unless stripped; built on this, a rolling-horizon simulation-based "digital twin" forecaster delivered essentially zero skill beyond a historical-average baseline during a non-recurrent incident despite running full microsimulation, because its apparent skill against persistence was entirely an artifact of the incident-blind twin's flat error versus the naive baseline's error growing with horizon — and error decomposition found state-initialization error dominates at 5-10 minute horizons while demand-forecast error dominates at 15-30 minutes. Refined by a later controlled fork matrix: the flowState double count requires the forecast's flow ids to DIFFER from the state's (matching ids merge cleanly), TraCI loadState and CLI --load-state agree on that matrix but NOT on stripping the same route file (the warm TraCI process back-fills missed insertions, the CLI does not), and the traffic-light bookkeeping corruption is only cosmetic for a self-scheduling program - for a TraCI-driven one getSpentDuration returns 0.0 against truth in 100% of post-switch samples.
keywords:
  - save-state
  - load-state
  - state-serialization
  - digital-twin
  - rolling-horizon-forecast
  - flowstate
  - short-term-traffic-prediction
created: 2026-08-06T06:00:00
last_updated: 2026-08-18T00:35:00
sources:
  - "[[episodic-memory/2026-08-06_06-00-00/outputs/state_semantics/summary.txt]]"
  - "[[episodic-memory/2026-08-06_06-00-00/outputs/state_semantics/flowstate_fork_leak.json]]"
  - "[[episodic-memory/2026-08-06_06-00-00/outputs/analysis/state_pending_leak.json]]"
  - "[[episodic-memory/2026-08-06_06-00-00/outputs/analysis/report.txt]]"
  - "[[episodic-memory/2026-08-06_06-00-00/outputs/analysis/scores.csv]]"
  - "[[episodic-memory/2026-08-06_06-00-00/outputs/analysis/records.json]]"
  - "[[episodic-memory/2026-08-06_06-00-00/outputs/analysis/verification.json]]"
  - "[[episodic-memory/2026-08-06_06-00-00/outputs/analysis/timing_serial.json]]"
related_pages:
  - "[[value-of-anticipation-in-predictive-signal-control]]"
  - "[[sumo-stochastic-variability-and-replication-design]]"
  - "[[traffic-state-estimation-sensor-bias-and-sensing-tradeoffs]]"
  - "[[mesoscopic-simulation]]"
  - "[[travel-time-reliability-metrics-in-sumo]]"
  - "[[sumo-output-files]]"
related_skills:
  - implement-predictive-rolling-horizon-signal-control
  - build-rolling-horizon-traffic-forecast-with-state-warm-start
  - emulate-and-evaluate-partial-sensor-traffic-state-estimation
  - quantify-sumo-run-to-run-variability
  - run-mesoscopic-simulation
related_skills_for_graph_view:
  - "[[implement-predictive-rolling-horizon-signal-control]]"
  - "[[build-rolling-horizon-traffic-forecast-with-state-warm-start]]"
  - "[[emulate-and-evaluate-partial-sensor-traffic-state-estimation]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[run-mesoscopic-simulation]]"
---

# State Serialization and Rolling-Horizon Traffic Forecasting

SUMO's `--save-state`/`--load-state` mechanism — the enabling primitive
for any warm-started, rolling-horizon, or predictive use of the
simulator — had zero coverage anywhere in memory until this page.
Verified on a 5 km freeway corridor, 5 CRN-replicated ground-truth days,
and 770 rolling-horizon forecast runs testing whether a simulation-based
"digital twin" actually beats naive forecasting baselines.

## State serialization: what is and is not preserved

A saved state holds route, vType, and per-vehicle records, lane
occupancy, pending flow schedules (`flowState`), routing-engine edge
weights, and `tlLogic` programs. RNG state is saved only with
`--save-state.rng`.

**A save-load-continue run is not bit-identical to an uninterrupted
run.** The two diverge at the very first comparable timestep after the
load, even with `--save-state.rng` set. Checked from both directions: on
a fully deterministic scenario, the only divergence source is
float-precision truncation in the saved state file — the default
`--save-state.precision` (2 decimal digits) left 11 of 599 vehicles with
a differing trip duration (max 4 s); raising precision to 6 or 12
eliminated every difference exactly. On a stochastic scenario, precision
is nearly irrelevant (identically-reproduced vehicle fraction moved only
5.1% → 7.1% from precision 2 to 6) — unrestorable internal RNG stream
state dominates there instead, confirmed via a round-trip test: reloading
a state and immediately re-saving it changes the recorded RNG stream
positions, because `--load-state` re-parses the entire route file on
load rather than resuming from a frozen point. Use
`--save-state.precision 6`+ and `--save-state.rng` as defaults for any
warm-start workflow, and design comparisons paired-by-seed rather than
assuming reproducibility.

**Traffic-light phase bookkeeping is corrupted on round-trip, even
though the logic and actuated-detector state restore exactly.** A static
program's stored `duration` changed from a real cycle length to the
absolute load timestamp; an actuated program's `cycleTime` reset to 0.
The absolute next switch time is preserved and the next phase change
still fires on schedule — the corrupted fields are cosmetic, not
functional, but code reading them directly rather than trusting SUMO's
own scheduling will see wrong values.

**"Cosmetic, not functional" holds only for a program SUMO schedules
itself; for a TraCI-driven program the corruption is functional.** A
later study ([[value-of-anticipation-in-predictive-signal-control]])
probed this at every control decision rather than once: phase index and
absolute next-switch time restore **100%** correctly, but
`getSpentDuration` — elapsed time in the current phase — returns **0.0
against a true 6.0 s**, matching in **0.00%** of samples. With a
TraCI-driven switch at a known instant:

```
MAIN t=108.0 phase=3 spent= 8.0  |  SHADOW t=108.0 phase=3 spent=0.0
MAIN t=116.0 phase=3 spent=16.0  |  SHADOW t=116.0 phase=3 spent=0.0
```

Any min-green enforcement that reads SUMO's phase clock after a load
therefore believes the green has just started. The workaround that works
is to drive the phase wholly externally (`setPhase` plus a large
`setPhaseDuration`) and carry elapsed green in the controller's own
state. **A probe that samples only the first decision after startup
cannot detect this** — at that point the shadow has been on phase 0
since t=0, so elapsed green trivially equals simulation time and the
round-trip looks clean.

**Detector accumulators are never saved at all** — no E1/E2/E3 elements
appear in the state under any tested option. Consequences, verified: an
E1/E2 aggregation window re-bases at the exact load instant with zero
guaranteed overlap against a pre-save run's bins; an E3 detector loses
its in-flight vehicle set entirely, producing "left detector without
entering" warnings for every mid-detection vehicle.

**`--load-state.offset` does not move the simulation clock** — it
subtracts the offset from timestamps stored inside the state itself,
which can produce a *negative* reported trip duration at a negative
offset. `--load-state.remove-vehicles` works as documented, booking
removed vehicles as "ended" exactly at the load instant.

**Mesoscopic and microscopic states are mutually unloadable** — loading
either under the other engine fails immediately. A mesoscopic
forecasting pipeline needs its own independent state chain.

## The critical trap: restoring `<flowState>` onto a different route file double-counts demand

Every active `<flow>`'s pending schedule is captured in `flowState` and
**keeps emitting vehicles from that schedule regardless of what route
file is supplied at load time.** Forking a forecast directly from a
ground-truth state onto the forecast's own (necessarily different)
demand file spiked first-bin corridor inflow **+44.8%** (449 vs. 310
vehicles) and ran the mean inflow **+14.0%** high across the forecast
window. Stripping `<flowState>` before forking fixed this to within
about 1–3% (mean −1.3% first bin) — genuine assimilation noise, not
double-counting. The fix must apply unconditionally on every fork but
must be *skipped* when genuinely continuing the same route file (the
twin's own forecast chain), since there the restored flow IDs are
correct and stripping them would truncate legitimate future demand.

### Two refinements, measured on a controlled fork matrix

A later study ([[value-of-anticipation-in-predictive-signal-control]])
re-tested this with a clean design — 900 veh/h flow, fork at t = 600 s,
120 s window, **30 departures expected** — across both the TraCI
`loadState` and CLI `--load-state` paths, and independently reproduced
by a second agent from scratch:

| fork configuration | TraCI `loadState` | CLI `--load-state` |
|---|---|---|
| forecast flow has its **own id**, `begin` = fork, unstripped | **60 (exactly double)** | **60 (exactly double)** |
| same, **stripped** | **30 (correct)** | **30 (correct)** |
| forecast **re-declares the same flow id** | 30 | 30 |
| continuing the same chain, unstripped | 30 | 30 |
| continuing the same chain, **stripped** | **102–143 (back-filled)** | **30** |

**(a) The double count requires the forecast's flow ids to *differ* from
the state's.** When the ids match, SUMO merges the restored schedule into
the parsed flow object and there is no inflation. So the trap is really
"a *new* flow id plus a restored schedule for the old one," which is the
normal case when forking onto a different demand file but is avoidable by
re-declaring the same id.

**(b) The TraCI and CLI paths agree on the double-count matrix but not on
stripping the same route file.** There, a warm TraCI process back-fills
the 600 s of insertions it missed (102–143 vehicles against 30 expected)
while the CLI does not (30). So this page's "never strip when continuing
the same route file" is specifically a **TraCI-path hazard** — on the CLI
path stripping the same file is merely unnecessary rather than harmful.

A third practical note: demand written as explicit `<vehicle>` elements
puts no `flowState` in the state at all, so the trap cannot fire — a
clean way to sidestep it entirely in a study that controls its own
demand generation.

**A caution about testing this.** An earlier attempt at the same
re-test concluded the opposite — that stripping *breaks* the correct case
and the behaviour differs between TraCI and CLI. Both conclusions were
artifacts of test construction: its two route files used **different flow
ids** (so double-counting was structurally impossible), and both flows
began at `t=0` while the fork was at `t=600`, so the inflation it
measured was a new flow back-filling missed insertions, which *masked*
the real double count. When designing this test, match the flow id
deliberately in one arm and set the forecast flow's `begin` at the fork
time, or the confounds will hide the effect you are looking for.

A second, related trap: a route file that ends before the simulation
horizon is fully parsed at t=0, so a vehicle scheduled to depart far in
the future can already appear "pending" inside a state taken long
before its real departure — in this study an incident-triggering
vehicle appeared in every ground-truth state roughly 75 minutes before
it actually entered the network, which can let a "perfect state" oracle
used for error decomposition see an upcoming incident far too early.
Fix with `--load-state.remove-vehicles` for not-yet-departed vehicles
before using a state as an oracle. The measured effect was metric- and
horizon-dependent: roughly 0–1.3% RMSE change on the aggregate
corridor-travel-time metric, but up to roughly 38% on an isolated speed
metric for the single segment nearest the incident — check per-metric,
not just an aggregate summary, before dismissing a leak like this as
negligible.

## The headline result: apparent forecast skill during an incident is an illusion

Scoring a rolling-horizon twin's corridor-travel-time predictions
against persistence across 5/10/15/30-minute horizons: during the
recurrent-congestion period, the twin never significantly beat
persistence (skill scores roughly −0.56, −0.05, +0.10, and a
significantly *worse* −0.54 at 30 minutes). During the incident period,
scores looked more favorable at some horizons — but this is an artifact:
the twin's incident-period RMSE stayed essentially flat across all four
horizons (roughly 361/362/362/353 s) because it is entirely blind to
the incident, while persistence's error instead grew sharply with
horizon (roughly 283/393/446/337 s) as the true corridor diverged
further from its pre-incident value. **The twin only "wins" because the
baseline degrades, not because the twin improves.** Scored against a
historical average instead — a baseline equally blind to the incident —
the twin's incident-period skill collapsed to essentially zero (roughly
+0.002/−0.001/−0.001/+0.023): during a non-recurrent event, a full
microsimulation twin driven only by sensor-assimilated state delivered
no more value than knowing the historical pattern. Congested-extent
predictions confirm the point directly: the twin predicted zero
congestion at every short/medium-horizon incident-window forecast while
true congestion ran 500–1250 m; the only exceptions were two
30-minute-horizon forecasts issued *before* the incident occurred,
which instead saturated at a maximum-value ceiling — a different
failure mode, not evidence of anticipation.

## Where forecast error actually comes from: a horizon-dependent crossover

Decomposing error via two oracle variants (true future demand with
assimilated state; true initial state with forecast demand) found a
clean crossover during the recurrent-congestion period: state-error and
demand-error dominate at different horizons, with state-initialization
error the dominant term at short horizons (5–10 minutes) and
demand-forecast error dominant at longer ones (15–30 minutes), crossing
somewhere between 10 and 15 minutes in this study's geometry and demand
profile. During the incident period, state-initialization error
overwhelms at every tested horizon — unsurprising, since the incident
itself is a state fact no demand forecast can supply. Even a
perfectly-initialized, perfectly-demanded twin carried a nonzero,
horizon-growing irreducible error floor from genuine simulation noise.

## Feasibility: microsimulation is not the bottleneck, and mesoscopic mode's bias direction is not universal

A single rolling-horizon forecast cycle used well under 2% of its
300-second budget in every tested demand regime (roughly 0.8–1.8%,
achieved real-time factor several hundred to nearly a thousand),
measured via a serial, uncontended benchmark. Switching to mesoscopic
mode bought a real 4–7× speedup this scenario didn't need, at a
substantial accuracy cost: mesoscopic forecasts were systematically
*worse* than microscopic ones here, and — notably — in the *opposite*
bias direction from a prior verified finding on a signalized grid
([[mesoscopic-simulation]]), where mesoscopic mode was found to be
systematically optimistic (underestimating delay). Here it ran
systematically pessimistic instead. Mesoscopic mode's accuracy bias
direction is not a fixed engine property — it depends on the facility
type and control regime, and should be checked per-application rather
than assumed from a prior result on a different network.

## Gotchas

- `--save-state.times T` does not fire if `--end` equals `T` exactly —
  run one step past the intended save time.
- Use `--save-state.precision 6`+ and `--save-state.rng` as defaults for
  any warm-start workflow.
- Strip `<flowState>` when forking a state onto a different route file;
  never strip it when continuing the same one.
- Remove not-yet-departed vehicles from a state before using it as a
  "perfect initial state" oracle.
- Detector aggregation windows re-base at the load instant with no
  overlap guarantee — recompute bin boundaries relative to the load
  time.
- A mesoscopic and a microscopic saved state cannot be interchanged.

See `build-rolling-horizon-traffic-forecast-with-state-warm-start` for
the full state-verification/forecasting/scoring workflow, and
[[traffic-state-estimation-sensor-bias-and-sensing-tradeoffs]] for the
sensor-emulation methodology this page's assimilation step builds on.
