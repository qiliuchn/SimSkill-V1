---
name: implement-railroad-preemption-at-a-signalized-intersection
description: Use this skill when the user wants MUTCD/ITE-style RAILROAD preemption of a traffic signal located close downstream of an at-grade rail crossing in SUMO - the case where a red-signal queue backs up over the tracks and vehicles are trapped when the gates come down. Covers building the rail_crossing-plus-nearby-signal corridor, discovering at runtime that SUMO exposes the rail_crossing as a TraCI traffic light (id = node id, 2 road links, GG/yy/rr/uu, gate red exactly 15 s before train arrival), measuring track occupancy geometrically from polled vehicle extents rather than from queue length, the critical finding that SUMO's DEFAULT driving model makes the trapped-vehicle failure mode structurally impossible until jmIgnoreKeepClearTime is set, the full ITE preemption FSM (advance preempt call, right-of-way transfer with pedestrian-interval truncation to its legal minimum, track clearance green, dwell/limited service, exit), and deriving the advance-preemption-time design curve by sweeping advance time against demand. Trigger on mentions of railroad preemption, grade crossing preemption, advance preemption time, track clearance green, queue clearance time, dwell/limited service, MUTCD minimum track clearance distance, or a signal too close to a rail crossing.
---

# Implement Railroad Preemption at a Signalized Intersection

Models the MUTCD/ITE hazard where a signalized intersection sits a few car
lengths downstream of an at-grade rail crossing: the signal's red queue extends
back over the tracks, and a train arrives while vehicles are standing on it.
This is categorically different from `implement-emergency-vehicle-preemption`
(one vehicle to be served, grant held until it clears) and from
`implement-transit-signal-priority` (bounded perturbation of the current phase):
here the *external* event is a gate closure whose timing is not under the
controller's control, and the objective is a **geometric** one - zero vehicles
inside the crossing envelope at the gate-down instant.

## Network: rail_crossing plus a signal one storage-length downstream

Reuse `build-rail-road-grade-crossing`'s verified pattern for the crossing
(explicit `type="rail_crossing"` node, bidirectional `spreadType="center"` rail
edges), and put a `type="traffic_light"` node ~55 m downstream on the same road.
See `scripts/build_scenario.py` for the complete two-pass build.

Three things must be read back from the **compiled** `.net.xml`, never assumed:

1. **Junction X's actual `type`** - netconvert silently reverts an invalid
   `rail_crossing` to `priority`.
2. **The crossing's real footprint along the road.** With default lane widths
   the compiled junction is only ~6 m long - too short for a vehicle to stand
   inside. Setting the rail edges' `width` is a purely geometric lever that sets
   this length: `width="14"` compiles to a 17.0 m footprint, a realistic MUTCD
   *minimum track clearance distance* for a double-track gated crossing. It does
   not touch train dynamics.
3. **The `linkIndex` of every movement at the signal.** Compile once with
   netconvert's default TLS, read the `linkIndex` off the `<connection>`
   elements, author the `tlLogic` against that mapping, then recompile with
   `netconvert -i signal.tll.xml` so your program *is* programID "0". (Loading a
   same-id/same-programID `tlLogic` as a `-a` additional aborts SUMO with
   `Another logic with id 'J' and programID '0' exists`.)

Restrict the signal to through-only movements with an explicit `.con.xml`. That
makes the design question - *which movements feed vehicles back toward the
crossing?* - unambiguous, which is what the dwell phase depends on.

## Instrument BEFORE writing the controller

`scripts/instrument.py` establishes both observation channels and writes them to
disk. Two findings that the controller then depends on:

**The rail_crossing IS a TraCI traffic light.** `traci.trafficlight.getIDList()`
returns the crossing node's id alongside the real signal. It controls only the
**road** links (2 links here, one per road direction - the rail links are not
TLS-controlled), and its program has four phases: `GG` (0.001 s), `yy` (5 s),
`rr` (0.001 s), `uu` (3 s). Gate-down is therefore `getRedYellowGreenState(X) ==
"rr"`, and gate-up is the `uu` (red-yellow) transition. **The `rr` onset occurs
15 s before the train reaches the crossing** (SUMO's rail-crossing time-gap
default; measured 14.69 s at 1 s polling, i.e. the switch falls inside the
sampling interval). That constant is what makes advance preemption predictable:
`predicted_gate_down = now + dist_to_crossing/train_speed - 15`. Verify it
yourself rather than trusting the number - `nearest_train()` (distance from
`traci.lane.getLength` minus `getLanePosition` on the rail approach edges) is
the fallback channel and also the ETA source.

**Measure track occupancy geometrically, not from queue length.** Take each road
vehicle's front-bumper position (`traci.vehicle.getPosition`) and project its
body backwards along its heading (SUMO's angle is degrees clockwise from north,
so the heading vector is `(sin a, cos a)`), then intersect that extent with the
crossing footprint read from the junction shape. Require a minimum overlap
(0.5 m) so a vehicle stopped exactly at the gate stop line is not miscounted.
**Report the bare-footprint count and the MUTCD-margin count separately** - a
vehicle waiting *at* the gate is safe; a vehicle *inside* the footprint is
trapped. Conflating them inflated the measured failure rate by ~3x across 70
baseline gate events (121 vs 39 vehicle-instances; 64 vs 18 events), and it is
also what any "residual occupancy" after a successful preemption turns out to
be - 0 on the footprint but 95 in the margin across 134 events at or above the
design advance time.

## The failure mode does not exist under SUMO defaults

**SUMO's default driving model will never let a road vehicle come to a
standstill inside the crossing junction.** `scripts/probe_junction_blocking.py`
is the negative control: across EB demands of 450/600/750/1200 veh/h (the last
heavily oversaturated) the maximum number of *stopped* vehicles overlapping the
crossing footprint was **exactly 0 at every instant**, and neither
`--ignore-junction-blocker`, `jmIgnoreJunctionFoeProb`, `jmIgnoreFoeProb`, nor
`impatience="1"` changed it.

The parameter that does is **`jmIgnoreKeepClearTime`** on the vType (default
`-1` = never violate keep-clear). Setting it to `0` produced up to **3**
simultaneously stopped vehicles on the same 17 m footprint, at 239-632 distinct
instants depending on demand. Like the dilemma zone in
`design-signal-change-and-clearance-intervals`, **the non-compliance that creates
the real-world hazard has to be deliberately injected, and the negative control
has to be run and reported** - otherwise a study concludes "SUMO shows no
trapped vehicles" and mistakes a modelling default for a safety result.

## The controller: an ITE sequence, not a phase jump

`scripts/preempt_sim.py` implements the full sequence as an FSM; every
transition is logged with its timestamp and the actual state string written.

```
NORMAL
  -> PREEMPT_CALL          when predicted_gate_down - now <= advance_preemption_time
  -> PED_HOLD              hold the current green for the REMAINDER of the
                           concurrent pedestrian minimum (WALK + FDW =
                           7 + ceil(W/1.2) s). Truncate TO the legal minimum,
                           never below.
  -> ROW_YELLOW  (>= 3 s)  terminate ONLY the movements that must lose green.
                           A movement that is green in the target state keeps
                           its green - do not drop a continuing green.
  -> ROW_ALLRED  (>= 2 s)  red clearance for the terminated movements only.
  -> TRACK_CLEAR           green for the approach LYING ACROSS the tracks,
                           discharging toward the downstream signal.
  -> TC_YELLOW / TC_ALLRED
  -> DWELL                 limited service: only movements that do NOT feed
                           vehicles back toward the crossing (here, the cross
                           street through movements). Held for the gate-down.
  -> EXIT_YELLOW / EXIT_ALLRED -> setProgram(native) -> NORMAL
```

Two implementation details that are easy to get wrong:

- **End `TRACK_CLEAR` on "the gate has been down at some point since the call",
  not on "the gate is down right now".** If the minimum track-clearance green is
  longer than the gate-down period, a `gate_down` test strands the FSM until the
  *next* train, silently skipping preemption for 40-50% of events. Add a hard
  cap so a mispredicted call cannot hang the intersection either.
- **Log every transition's state string.** `ryrG` (WB terminated, EB green
  retained) and `rrrG` (WB red clearance while EB continues) are the auditable
  signature that the right-of-way transfer terminated only what it had to.

## The design curve

Sweep advance preemption time (0-30 s) x through-demand level, and take, for
each demand, **the smallest advance time from which occupancy is zero and stays
zero for every larger swept advance time.** A single lucky zero at a short
advance time is not a design point - occupancy is *not* monotone in advance time
(see below). `scripts/sweep.py` runs the cells, `scripts/analyze.py` builds the
tables and the curve, `scripts/plot_design_curve.py` draws it.

Compare against the ITE closed form
`APT = right-of-way transfer + queue clearance + separation`, with **measured
rather than assumed** inputs: get the saturation headway `h` and startup lost
time `l1` from an `<instantInductionLoop>` at the stop bar
(`scripts/measure_saturation.py`), taking `h` only over the *saturated band* of
the headway-by-queue-position profile (the variance jumps by an order of
magnitude once the standing queue is exhausted and free arrivals begin).

## Verified findings

- **Preemption drives track occupancy to exactly zero** at and above the design
  advance time, at every demand level and at both train headways tested
  (10 and 22 gate events per run).
- **An inadequate advance time is worse than no preemption at all.** Mean
  occupancy at gate-down as a function of advance time is a *hump*, peaking
  around 10 s: at 750 veh/h it went 0.9 (no preemption) -> 0.9 / 1.6 / **2.3** /
  0.9 / 0.0 at 0/5/10/15/20 s. A too-short call terminates the eastbound green
  for the right-of-way transfer just as the gate drops, freezing on the tracks a
  queue that the normal cycle would have been discharging.
- **The simulated design point lands on the ITE *best-case* branch, not the
  worst case** - because preemption itself re-synchronises the cycle to the
  train schedule, so after the first event the phase at the preempt call is
  deterministic and the pedestrian worst case is never re-sampled. Report the
  worst-case branch as the design basis anyway; a simulation-derived advance
  time is optimistic by the full pedestrian minimum.
- **Trapped vehicles delay the trains, not just the cars.** Train time loss and
  gate-down duration are a clean, independent confirmation of the failure mode.
- **Preemption is what makes a short train headway survivable.** Check whether
  the EB queue at successive gate-downs diverges - that is the compounding test.

## Gotchas

- **`jmIgnoreKeepClearTime` is mandatory** to reproduce the hazard at all; run
  and report the SUMO-default negative control alongside it.
- **The crossing's compiled footprint, not the node coordinate, is the
  occupancy zone** - and with default widths it is too short for a vehicle to
  stand in.
- **Do not treat occupancy as monotone in advance preemption time.** Require
  zero at the candidate value *and at every larger value*.
- **Preemption phase-locks the signal to the train schedule**, which suppresses
  exactly the ROW-transfer variability the ITE worst case exists to cover.
- **Compare against the baseline per train event, and check the baseline is
  stable first** - at an oversaturated demand the no-preemption baseline
  gridlocks, and preemption then improves *every* approach, which is not the
  tradeoff the study is meant to expose.

## Related

- `build-rail-road-grade-crossing` - the `rail_crossing` node authoring and
  compiled-net verification this skill's crossing reuses verbatim.
- `build-rail-corridor-with-railsignal` - the bidirectional rail-track and train
  vType pattern underneath the crossing.
- `implement-emergency-vehicle-preemption` - the forced-state-override,
  manufactured-clearance, logged-FSM controller technique this skill extends
  from a single vehicle to an externally-timed gate event.
- `implement-transit-signal-priority` - the bounded, current-phase-only priority
  this skill's full preemption is contrasted with.
- `design-signal-change-and-clearance-intervals` - the minimum yellow/all-red
  this skill's right-of-way transfer honours, and the
  non-compliance-must-be-injected discipline the keep-clear finding parallels.
- `measure-saturation-flow-and-validate-webster-method` - the stop-bar discharge
  measurement supplying `h` and `l1` to the ITE closed form.
- `control-signals-with-actuated-tls`, `implement-nema-dual-ring-controller` -
  `tlLogic` authoring and phase-structure background.
- `analyze-simulation-outputs` - the tripinfo/edgeData per-approach cost
  comparison methodology.
- [[railroad-preemption-of-nearby-signalized-intersections]] - the verified
  gate-state exposure, keep-clear finding, non-monotone advance-time result and
  ITE-vs-simulation comparison this skill produced.
