---
name: design-and-control-freeway-work-zone-lane-closures
description: Use this skill when the user wants to model a PLANNED freeway work zone as a design-and-control object rather than an incident - building a full MUTCD-style zone (advance-warning, taper/transition, activity, termination areas) with sweepable lanes-closed / work-zone length / taper length / advance-warning distance / posted work-zone speed, measuring work-zone queue-discharge capacity per open lane against the HCM ~1600 pc/h/ln reference, choosing between static early merge, static late merge (zipper), dynamic late merge and VSL, sweeping VMS detour-compliance share for a corridor-wide TSTT optimum, or costing a partial-closure-vs-full-closure-with-detour schedule in road-user cost. Also covers the three ways to express a lane closure in SUMO (rerouter closingLaneReroute, a disallow permission edit, a rebuilt geometric lane drop) and which is defensible for a long-term closure. Trigger on mentions of work zone, lane closure, MUTCD taper, advance warning area, activity area, merge control, early merge, late merge, zipper merge, dynamic late merge, work-zone capacity, road-user cost, or closure scheduling.
related_skills:
  - compare-zipper-vs-default-merge-at-lane-drop
  - simulate-incident-rerouting
  - implement-variable-speed-limits
  - implement-coordinated-corridor-ramp-metering
  - choose-time-discretization-and-integration-method
  - quantify-sumo-run-to-run-variability
  - validate-congested-scenario-results-against-teleport-artifacts
  - measure-saturation-flow-and-validate-webster-method
related_skills_for_graph_view:
  - "[[compare-zipper-vs-default-merge-at-lane-drop]]"
  - "[[simulate-incident-rerouting]]"
  - "[[implement-variable-speed-limits]]"
  - "[[implement-coordinated-corridor-ramp-metering]]"
  - "[[choose-time-discretization-and-integration-method]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[validate-congested-scenario-results-against-teleport-artifacts]]"
  - "[[measure-saturation-flow-and-validate-webster-method]]"
related_pages:
  - "[[freeway-work-zone-capacity-closure-representation-and-merge-control]]"
---

# Design and Control Freeway Work-Zone Lane Closures

Treats a planned lane closure as **infrastructure you design**, not an incident you react
to. Distinct from `simulate-incident-rerouting` (a temporary disruption whose object of
study is the rerouting device) and from `compare-zipper-vs-default-merge-at-lane-drop`
(a bare 2->1 lane drop with no MUTCD zone, no detour and no controller): here the taper
length, advance-warning distance, posted work-zone speed, merge-control strategy,
diversion share and closure schedule are all decision variables.

## 1. Settle the representation question first -- it is not cosmetic

There are three ways to close a lane in SUMO, and they are **not** three different
models:

| representation | how | visible in the compiled net? |
|---|---|---|
| R1 rerouter | `<rerouter><interval><closingLaneReroute id="fE_0" disallow="all"/>` | **no** |
| R2 permission | write `disallow="all"` onto the lane in the compiled `.net.xml` | yes |
| R3 geometric | rebuild with `netconvert`: the activity-area edge has fewer lanes | yes |

**Verified: R1 and R2 are the same mechanism.** A `closingLaneReroute` is implemented as
a *runtime mutation of the lane's permissions*. Querying it live mid-interval
(`traci.lane.getDisallowed("fE_0")`) returns all 33 vClasses blocked while the neighbour
lane returns none — and the two representations produced **bit-identical** capacity,
duration and hard-braking counts on all four CRN seeds (paired difference exactly
`+0.0`, p = 1.0). Choose between them on bookkeeping grounds (R1 is time-windowed and
self-documenting; R2 survives inspection of the net), never expecting a behavioural
difference.

**`traci.lane.getAllowed` returns an EMPTY list to mean "all vClasses permitted".** The
allowed list alone cannot distinguish "everything allowed" from "nothing allowed" — always
read `getDisallowed` too.

**R3 is the defensible choice for a long-term closure, for a reason that is structural,
not statistical.** All three agreed on capacity to within ~1 % (R1/R2 1562, R3a 1578
pc/h/ln, paired difference −15.3 [−39.3, +8.6], p = 0.13). But **only R3 can express
merge discipline at all**: R1 and R2 keep a 3-lane-to-3-lane connection set, so there is
no contested downstream lane and `type="zipper"` on the drop node has nothing to act on.
Only the rebuilt net produces the `ZZM` connection-state signature (both lanes feeding
the surviving lane get `Z`, the uncontested lane keeps `M`). Verify it:

```bash
grep 'from="fD".*to="fE"' net.xml     # expect state="Z" twice + state="M" once
```

And the behavioural difference that follows is large: switching the drop node from
`priority` to `zipper` on the *same* rebuilt geometry cut near-taper hard-braking events
from 777 to 314 (−60 %) at equal capacity.

**The merge-position profile is the diagnostic that actually separates them.** Compute
the share of vehicles observed in the closing lane at each E2 station versus distance.
R1/R2/R3-priority all show a gradual drain (0.29 at 200 m falling to 0.09 by 4600 m):
SUMO's strategic lane-change lookahead spreads the merge over kilometres. R3-zipper holds
~0.30 all the way to the taper — the late-merge signature — **without any controller**.
Report this profile; a table of aggregate capacities hides the entire difference.

## 2. Build the zone parameterised, and expand the corridor rather than overrunning it

Hand-author `.nod/.edg/.con/.tll` XML (`netgenerate` cannot express this) with one edge
per MUTCD area — `fC` advance warning, `fD` taper, `fE` activity, `fF` termination — so
each length is a single sweepable parameter. Put the on-ramp merge node at
`end_of_termination + 1000 m` rather than at a fixed chainage, or a long advance-warning
variant silently overruns it.

**SUMO cannot render a continuously narrowing lane.** A "taper" is a lane-count drop at
a node plus an edge whose *length* is the taper length; the lateral shift appears only in
the internal-junction geometry. Say so rather than implying a geometric taper was modelled.
`netconvert` also trims the taper edge (200 m -> 196 m at a zipper node) — read lengths
back from the compiled net.

Apply activity-area driver behaviour (`speedFactor`, `sigma`) over TraCI on entry to the
activity edge and restore on exit; these are vType attributes with no edge-scoped form.
Do it **identically in every arm**, including do-nothing.

## 3. Measure capacity as queue discharge -- and do not let insertion masquerade as capacity

**Definition used throughout**: mean flow over queued 60 s intervals at an E1 station 15 m
before the end of the activity area, per OPEN lane, excluding the first 300 s after queue
onset. Use 100 % passenger cars so veh/h/ln == pc/h/ln and the HCM value needs no PCE
conversion. Gate "queued" on an upstream station reading below 0.6 x free-flow speed.

**The trap that cost a whole matrix here: a flat overloaded demand CANNOT saturate a
free-flowing multilane freeway in SUMO.** Loading 8400 veh/h into a 3-lane corridor
inserted only 4650 of 8447 vehicles and produced ~4100 veh/h at *both* the upstream and
downstream stations — i.e. the corridor was running at SUMO's **insertion** throughput
(~1370 veh/h/ln at `departSpeed="max"`), not at road capacity. Reporting that as the
"unobstructed per-lane reference" understates capacity by ~26 %.

**Fix: build the queue physically, then release it** (`scripts/exp_capacity_probe.py`).
Park blocker vehicles across every lane at the start of the termination area
(`vehicle.add` + `setStop` + `setSpeedMode(0)`), hold ~900 s so a standing queue forms
back over the activity area, remove them, and measure discharge from
`release + 120 s`. Raise `--time-to-teleport` above the blockage duration or the probe
manufactures teleports out of its own gate.

Measured this way, on an identical segment:

| configuration | queue-discharge capacity |
|---|---:|
| 3 lanes, 120 km/h (unobstructed) | **1826** pc/h/ln |
| 3 lanes, 80 km/h (speed reduction only) | 1717 pc/h/ln (−6.0 %) |
| 1 lane closed, 2 open, 80 km/h | 1599 pc/h/ln (−12.4 %) |
| 2 lanes closed, 1 open, 80 km/h | 1274 pc/h/ln (−30.2 %) |

**Separate the segment's capacity from the merge's capacity.** The release probe measures
the roadway; the naturally-formed work-zone queue measures the roadway *plus* the forced
merge. The gap between them is the merge's own cost, and it grows sharply with lanes
closed: 1599 vs 1534 at one lane closed (merge costs 4 %), 1274 vs 1108 at two
(merge costs 13 %). Report both or the mechanism is invisible.

## 4. Choose the step length -- work-zone capacity is a dt-FRAGILE metric

Run `choose-time-discretization-and-integration-method` for real. Its stored per-metric
trust table puts capacity and mean trip duration in the "trustworthy at dt = 1.0 s"
class. **That does not transfer to a work zone.** Measured here with reaction time
pinned, against a dt = 0.25 s reference:

| dt (ballistic, `actionStepLength` 1.0 s) | WZ capacity | mean duration |
|---|---:|---:|
| 1.0 s | **+6.2 %** | **−14.6 %** |
| 0.5 s | +1.1 % | −4.0 % |

Work-zone capacity is set by *forced lane-change gap acceptance in a taper*, so it belongs
with the merge/SSM family, not the equilibrium-FD family. **Use dt <= 0.5 s.** Surrogate
safety is worse still — near-taper hard-braking counts were −45.8 % at dt = 0.5 s versus
the reference — so report safety *levels* only from a fine-dt confirmation run and rely on
CRN-paired contrasts elsewhere.

## 5. Control arms, and the detector-placement error that fakes a win

Five arms plus a negative control, all on one CRN route file and seed list, all through
the identical TraCI harness (`scripts/run_wz.py`):

| arm | net | mechanism |
|---|---|---|
| `donothing` | drop node `priority` | SUMO's own merge |
| `early` | drop node `priority` | closing lane prohibited from the START of the advance-warning area |
| `late` | drop node `zipper` | lane open to the taper + strategic lane-changes suppressed upstream |
| `dynamic` | drop node `zipper` | EARLY <-> LATE on smoothed upstream occupancy, two-sided hysteresis + dwell |
| `vsl` | drop node `priority` | upstream speed ladder |
| `negctrl` | drop node `priority` | full controller plumbing, actuation clamped off |

Static early merge is implemented as `traci.lane.setDisallowed` on the closing lane of
the advance-warning and taper edges — i.e. **moving the merge point is the same operation
as closing the lane**, which is why the dynamic controller is a single toggle.

**THE ERROR TO AVOID.** The obvious control detector — just upstream of the taper — is
*downstream of the early-merge bottleneck*. With early merge active it read 7-11 %
occupancy while do-nothing at the same demand read 30-39 %. A controller that starts in
EARLY mode is then structurally blind to its own queue: it never switched once in 180
runs, silently degenerating into "static early merge", and **that broken version appeared
to beat both statics at the highest demand** — a controller-configuration artifact
masquerading as a finding, exactly the failure `implement-coordinated-corridor-ramp-metering`
records for ramp metering. Put the station **upstream of every candidate merge point**;
it then read 29.0 vs 32.9 % across the two modes at equal demand, and the fixed controller
switched 3-4 times per run (28-74 % of time in LATE) — and **reversed the finding**.

Calibrate the hysteresis band from no-control runs at the same station rather than
guessing: free-flow demands never exceeded 10 % occupancy there and congested ones reached
29-48 %, so an 18 % ON / 9 % OFF band is well separated.

`negctrl` reproduced `donothing` to `+0.000e+00` veh-h at every demand — keep it.

## 6. Account honestly: TSTT with the origin-insertion integral

```
TSTT = edgeData sampledSeconds over ALL edges (withInternal="true")
     + integral of len(traci.simulation.getPendingVehicles()) dt
classes: freeway | ramps | detour arterial | internal | origin
```

This matters more here than in most scenarios: early/dynamic merge **hold vehicles out of
the network** (43.0 and 41.5 origin veh-h at 4000 veh/h against 8.0 for do-nothing).
Without the origin term they would look better than they are. Report
`loaded / inserted / completed / still-running / never-inserted` per cell.

**Do not use tripinfo `timeLoss` as the headline** — the VSL arm changes the posted limit
and `timeLoss` is computed against the legally-observed limit
(`implement-variable-speed-limits`).

## 7. Diversion: the optimum compliance share is below 100 %

Assign compliance as a **nested** per-vehicle draw fixed by the demand seed, so raising
phi only ever adds diverters — the sweep is then itself a CRN design.

Verified: TSTT vs phi is an inverted U **only when the freeway is genuinely
oversaturated**. At a demand below work-zone capacity the optimum was phi = 0 (any
diversion strictly hurt). At an oversaturated demand the optimum was **phi = 0.20**,
with TSTT 843 -> 491 -> 2378 veh-h across phi = 0 / 0.20 / 1.00. The mechanism is
directly observable and is the same delay transfer as
[[coordinated-ramp-metering-delay-transfer-and-ramp-storage]]: the arterial's discharge
saturates at ~1500-1680 veh/h, so beyond phi ~ 0.3 sending more traffic *reduces* what the
detour delivers (1678 vehicles offered vs 1513 delivered at phi = 0.6), and the surplus
lands in the origin-insertion term (0 -> 1499 veh-h). **Sizing the recommendation to the
detour's saturation flow, not to the freeway's deficit, is the whole design problem.**

## 8. Scheduling: road-user cost against a no-work-zone reference

```
RUC = (TSTT_closure − TSTT_nowork) * VOT
    + (fuel_closure − fuel_nowork) * fuel price
    + (CO2_closure  − CO2_nowork)  * carbon price
```

Fuel/CO2 from HBEFA3 `edgeData type="emissions"` (covers every vehicle-second incl.
internal edges), not from tripinfo. Compare a partial closure under the daytime profile
against a full closure with mandatory detour under a night profile **at matched demand
levels**, and read the crossover off the RUC curves.

## Gotchas

- **`closingLaneReroute` is invisible in the compiled net** — verify it live over TraCI, and
  remember `getAllowed` returns `[]` for "all permitted".
- **A flat overload does not measure capacity in SUMO** — it measures insertion. Use the
  blocker-release probe.
- **Raise `--time-to-teleport` above any deliberate blockage** or the probe manufactures
  its own teleports.
- **A control detector between the two candidate merge points is blind in one of them** —
  and produces a plausible-looking false positive.
- **`--lateral-resolution` with `laneChangeModel="LC2013"` is a hard error**
  ("not compatible with sublane simulation") — drop it or switch to SL2015.
- **Close the TraCI connection before parsing SUMO's output files**; they are only flushed
  on shutdown, and parsing early raises `ParseError: unclosed token`.
- **Work-zone capacity and safety are both dt-fragile** — dt <= 0.5 s for capacity, 0.25 s
  for safety levels.
- **Do not assume dynamic late merge wins.** Verified here: with a correctly-placed
  detector it beat do-nothing but **lost to static early merge** at every oversaturated
  demand (+38 to +50 veh-h TSTT, all significant).

## Related

- `compare-zipper-vs-default-merge-at-lane-drop` — the bare lane-drop testbed and the
  compiled-net `Z`-state verification this skill's R3 variant reuses; its finding that
  zipper can *depress* discharge is reproduced here as a safety-vs-throughput trade.
- `simulate-incident-rerouting` — the `closingLaneReroute` mechanics, here shown to be a
  runtime permission mutation identical to a static `disallow`.
- `implement-variable-speed-limits` — the VSL arm, the E2 station convention, the speed
  contour, and the `timeLoss` confound.
- `implement-coordinated-corridor-ramp-metering` — the TSTT/origin-insertion accounting,
  the `negctrl` discipline, and the detector-calibration failure mode this skill hit again.
- `choose-time-discretization-and-integration-method` — applied here, and re-qualified:
  work-zone capacity is dt-fragile where the stored table says capacity is dt-robust.
- `quantify-sumo-run-to-run-variability` — CRN/paired-CI design.
- `validate-congested-scenario-results-against-teleport-artifacts` — teleport discipline.
- `measure-saturation-flow-and-validate-webster-method` — the queue-build-and-release idea
  behind the capacity probe.
- [[freeway-work-zone-capacity-closure-representation-and-merge-control]] — the verified
  findings.
