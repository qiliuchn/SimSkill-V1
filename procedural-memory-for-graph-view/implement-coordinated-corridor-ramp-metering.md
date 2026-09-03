---
name: implement-coordinated-corridor-ramp-metering
description: Use this skill when the user wants ramp metering on a FREEWAY CORRIDOR with several on-ramps and a shared downstream bottleneck — coordinated/HERO-style master-slave metering, whether coordination beats per-ramp isolated ALINEA, ramp-queue storage limits and spillback into a signalized surface ramp terminal, queue-override (flush) rules, or an honest Total System Travel Time accounting that charges metering for the ramp, surface-street and never-inserted delay it creates. Covers hand-authored multi-ramp corridor networks with a lane-drop bottleneck, storage-limited ramps with signalized terminals, a three-part measurement layer (E1 mainline + E2 ramp queue cross-validated against FCD + TSTT decomposition), and CRN-replicated multi-arm comparison. Trigger on mentions of coordinated ramp metering, HERO, corridor metering, ramp queue override/flush, ramp storage limits, delay transfer, or "does metering help the system or just move the delay."
related_skills:
  - implement-alinea-ramp-metering
  - build-diamond-interchange-with-signal-offset-spillback
  - implement-variable-speed-limits
  - quantify-sumo-run-to-run-variability
  - validate-congested-scenario-results-against-teleport-artifacts
  - compare-zipper-vs-default-merge-at-lane-drop
related_skills_for_graph_view:
  - "[[implement-alinea-ramp-metering]]"
  - "[[build-diamond-interchange-with-signal-offset-spillback]]"
  - "[[implement-variable-speed-limits]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[validate-congested-scenario-results-against-teleport-artifacts]]"
  - "[[compare-zipper-vs-default-merge-at-lane-drop]]"
related_pages:
  - "[[coordinated-ramp-metering-delay-transfer-and-ramp-storage]]"
---

# Implement Coordinated Corridor Ramp Metering

Generalises `implement-alinea-ramp-metering` from one isolated on-ramp to a multi-ramp
corridor with a single shared downstream bottleneck, and — more importantly — replaces
"the mainline got better" with an honest **system-wide** verdict that charges metering
for every delay it creates: ramp queues, surface-street delay at the ramp terminal, and
demand that never gets inserted at all.

## 1. Build the corridor: plain XML + netconvert

`netgenerate` cannot express this. Hand-author `.nod/.edg/.con.xml` (see
`scripts/build_corridor.py`), then verify the **compiled** net (`scripts/verify_net.py`):

- **Mainline** ~10 km, 3 lanes, with a **3→2 lane drop** as the recurrent bottleneck.
  Give the drop node `type="zipper"`; verify the compiled connection states show `Z` on
  both lanes feeding the contested downstream lane.
- **On-ramp merges** also `type="zipper"` — a `priority` merge lets the ramp fully yield
  and gives metering nothing to do (the lesson `implement-alinea-ramp-metering` verified).
  Verify `Z` on the mainline **and** ramp side of the contested lane, `M` on an
  uncontested lane.
- **Off-ramps** as `priority` diverges off mainline lane 0.
- **Storage-limited ramp with a signalized terminal** for every metered ramp:
  `surface approach → terminal (traffic_light) → STORAGE segment (length L) → meter
  (traffic_light) → acceleration lane → zipper merge`. The storage segment's length is
  the physical ramp storage; set it explicitly with the edge `length` attribute and
  verify from the compiled `.net.xml`.

### Two geometry traps that silently wreck the scenario

- **Sharp internal-link angles throttle the meter.** If the storage edge arrives at the
  meter junction at a large angle to the acceleration lane, `netconvert` warns
  "Speed of straight connection ... reduced by 15.00 due to turning radius" and the
  meter can then discharge at ~2 m/s. Give both ramp edges an explicit `shape=` so the
  storage edge **arrives parallel** to the acceleration lane (0° internal link), and set
  `length=` explicitly so the shaped polyline does not change the storage capacity.
- **Two `G` links targeting the same downstream lane deadlock the terminal.** SUMO warns
  "Unsafe green phase ... Lane X is targeted by 2 'G'-links"; in practice the two
  approaches block each other in the junction box and the whole surface approach jams in
  the *baseline*, destroying the experiment. One lane → one downstream lane.

### Making ramp-queue spillback physically representable

Two design decisions do the work; without them H4-style spillback can never happen:

1. The ramp-bound movement is the **left turn out of the left lane**, so an overflowing
   ramp queue blocks arterial through traffic sharing that lane (left-turn-bay overflow).
2. `keepClear="false"` **only** on that ramp-bound connection: when storage is full the
   ramp-bound vehicle stalls inside the junction box and physically blocks the cross
   street. With SUMO's default keep-clear the queue politely holds at the stop bar and
   the interchange can never be blocked by a ramp queue at all.

## 2. Calibrate on the CORRIDOR, not on a mainline-only sweep

A mainline-only (ramps closed) sweep is the obvious calibration and **it does not
transfer to a corridor**. Verified the hard way, at the cost of an entire 444-run matrix:

- The station ~100 m upstream of a lane drop sits inside a **permanent merge-turbulence
  zone**. With the on-ramps active it read **15.8 m/s and 7.0% occupancy at a demand 25%
  BELOW the corridor's capacity**, where the mainline-only sweep read 32 m/s and 4%. Its
  flow-occupancy curve is nearly flat (3600-4080 veh/h across 8-31% occupancy), so its
  critical occupancy is 22.7%, not the 5.8% the mainline-only sweep implied.
- A controller regulating that detector to the mainline-only setpoint was **restrictive
  40-44% of control intervals at a demand 25% below capacity** and cost +29% system delay
  for zero mainline benefit - a controller-configuration error masquerading as a finding
  about metering.

**Do it this way instead** (`scripts/calibrate_corridor.py`): pool every control interval
from a set of no-control **corridor** runs across all demand levels and seeds, bin by each
station's own occupancy, and read off the occupancy where that station's own flow peaks.
This costs zero extra simulation if a no-control matrix already exists. Then:

- **control on a clean station** (just downstream of the master ramp's merge, several
  hundred metres upstream of the drop), and
- **keep the near-bottleneck detector for breakdown REPORTING only** - using it for
  breakdown detection is equally wrong, since it reads below any sensible speed threshold
  even in free flow, so "breakdown onset" measured there comes out identical in every arm
  and is meaningless.

Separately, measure the **capacity drop** with a dedicated multi-seed steady-demand sweep
(`scripts/capacity_drop.py`) straddling the breakdown threshold, **using the same vehicle
heterogeneity as the real scenario**, classifying each run as broken-down or not from the
clean upstream station. Comparing a demand-limited free-flow observation against a queue
discharge - or sweeping with a different `speedDev` than the scenario uses - manufactures
an apparent capacity drop that vanishes under proper replication: an apparent 6.6% drop
from a single-seed homogeneous sweep became **-0.3%, i.e. none**, over 60 properly
classified runs. See `implement-variable-speed-limits` /
[[variable-speed-limits-and-e2-detectors]], which recorded the same null on a similar
lane drop. Re-measure it; never assume it.


## 3. Control arms

Share the identical network, route file and `sumo --seed` across every arm (CRN).

| arm | what it is |
|---|---|
| `nocontrol` | meters held permanently green |
| `fixed` | fixed release rate while the activation window is open |
| `alinea` | per-ramp **isolated** ALINEA on that ramp's own local downstream E1 |
| `bnalinea` | single-ramp ALINEA at the bottleneck-adjacent ramp, on the **bottleneck** detector |
| `coord` | HERO-style master/slave (below) |
| `coord_flush` | `coord` + a strict ramp-queue override |
| `negctrl` | the full `coord` controller runs, logs and actuates, but its rate is clamped open so it can never restrict |

**`bnalinea` is the arm that makes the comparison interpretable.** Without it, `coord`
beating `alinea` is confounded: `coord` differs from `alinea` in *both* where it measures
(bottleneck vs local detector) *and* whether it recruits upstream ramps.
`alinea → bnalinea` isolates the detector-placement effect; `bnalinea → coord` isolates
the coordination/recruitment effect.

**`negctrl` is a non-binding negative control**, not a formality: it catches an entire
class of bug (a controller that changes outcomes through its plumbing — signal-program
switching, per-step `setRedYellowGreenState`, subscription side effects — rather than
through its decisions). It must reproduce `nocontrol` to floating-point identity.

### The HERO-style coordination law (state it explicitly, it is a design choice)

```
master  = the bottleneck-adjacent ramp; r_master from ALINEA on the BOTTLENECK detector
recruit = walk upstream: if the downstream cluster member's queue-to-storage ratio
          w >= W_HI, recruit the next ramp up; de-recruit below W_LO (hysteresis)
slave   r_slave = d_slave - 3600 * (w_downstream - w_slave) * S_slave / T_BAL
          (d = measured arrival rate, S = storage in vehicles, T_BAL = balancing time
           constant) -- i.e. release less than arrivals in proportion to how much more
           saturated the downstream member is, driving the cluster toward a common
           queue-to-storage ratio
```

Rate→signal translation is `implement-alinea-ramp-metering`'s one-car-per-green
(`C = 3600/r`, green `GREEN_T`, hold green if `C <= GREEN_T`), reused unchanged.

## 4. The three-part measurement layer

**(a) Mainline** — E1 induction loops, one per lane, at ~12 stations, including a
**breakdown-onset detector** just upstream of the lane drop and a **discharge detector**
just downstream of it. `period` (not `freq`). Absolute, per-run output paths.

**(b) Ramp queue** — E2 `laneAreaDetector` spanning the **full** storage segment, plus
one on each surface-approach lane and the cross-street approach. Define the
**ramp-storage-exceeded flag** as a control interval with ≥95% of the segment's vehicle
capacity occupied, and cross-validate the E2 reading against true vehicle positions from
`--fcd-output` (`scripts/fcd_crossvalidate.py`). Compare **instantaneous** readings taken
live over TraCI at the control instants against FCD at the same timestamps — the E2 *XML*
interval output reports interval max/mean and is not comparable instant-for-instant.

**(c) TSTT decomposition** — from `edgeData` (with `withInternal="true"`) plus an
insertion-queue integral:

```
TSTT = vehicle-hours in-network (sampledSeconds, all edges incl. internal)
     + origin-insertion vehicle-hours (integral of len(getPendingVehicles()))
TSD  = the same split using edgeData `timeLoss` for the in-network parts
       + the whole insertion integral
classes: mainline | ramp | surface | origin
```

**The origin-insertion integral is the component that makes the accounting honest.**
A ramp meter that backs a queue out of the network entirely produces vehicles that never
appear in `tripinfo`, never appear in `edgeData`, and are invisible to every conventional
metric. `∫ len(traci.simulation.getPendingVehicles()) dt` captures exactly that cost, and
unlike `tripinfo`'s `departDelay` it also counts vehicles that were *never* inserted.
Report `loaded / inserted / completed / still-running / never-inserted` alongside.

**Report TSD, not TSTT, as the headline.** TSTT rewards an arm that simply serves fewer
vehicles; TSD with the origin term does not.

## 5. Runtime: subscribe, don't poll

A naive controller querying ~150 detector getters per simulation step is **socket-bound,
not simulation-bound** — measured 64 s/run vs 36 s/run for the identical run after moving
every E1/E2 read to `traci.*.subscribe()` + one `getAllSubscriptionResults()` per step.
On a several-hundred-run replication matrix this is the difference between a 25-minute and
a 3-hour batch. Verify the refactor is behaviour-preserving by reproducing one run's
outputs exactly.

## 6. Why the answer usually comes out negative

The single most consequential measurement is Gate 0 of the decision rule: **if the
bottleneck has no capacity drop, metering cannot raise throughput at all.** Verified
directly here -- bottleneck discharge was 3844-3848 veh/h across *all seven control arms
and all six demand levels*, a spread of 0.1%. Everything metering then does is
redistribution, so any restriction is a pure system-delay loss. Measure this before
interpreting any arm comparison; it explains coordination losing to isolated control,
the queue override being free, and prevention-vs-recovery being a null result, all at once.

The second is the **storage ratio**: `available ramp storage (veh)` divided by
`(demand - capacity) x peak duration`. At 0.115 here (88 vehicles of storage against 765
that needed withholding), no control law can succeed, and the excess simply queues out of
the network into the insertion buffer.

## 7. Replication and validation discipline

- ≥8 CRN seeds; paired t-tests on seed-wise differences, report the CI, the paired
  correlation ρ and the per-seed sign-agreement rate (`quantify-sumo-run-to-run-variability`).
- **Metering-rate verification**: compare each interval's realized release (E1 just
  downstream of the meter) against the commanded rate, restricted to intervals where the
  meter was actually restrictive **and** a queue was present — otherwise the ramp is
  demand-limited and the comparison is meaningless.
- **Teleport-artifact check** per `validate-congested-scenario-results-against-teleport-artifacts`:
  report the teleport-affected share, and re-run a subset at `--time-to-teleport` 120 and
  `-1` checking for a running-count freeze.
- **One authoritative definition per metric**, cited identically everywhere
  (`build-diamond-interchange-with-signal-offset-spillback`).
- **Report a spillback exponent per control policy, not pooled.** A log-log regression of
  surface delay on ramp-queue vehicle-hours gave 1.25-1.31 (super-linear) *within* each
  metering policy but 0.96 (linear) pooled across policies, because the policies have
  structurally different queue-to-surface mappings. Pooling silently converts a real
  super-linear coupling into a null result.

## Gotchas

- **`--device.fcd.period` offsets each vehicle's sampling by that vehicle's own departure
  time**, so almost no vehicle is ever sampled on a control instant. For instant-for-instant
  validation, report FCD every step and subsample.
- **`--fcd-output.filter-edges.input-file` takes a netedit SELECTION file** (`edge:<id>`
  per line), not an `<additional>` XML. Passing XML matches nothing and silently produces
  an FCD file with 6000 timesteps and zero vehicles.
- **Detector `file=` paths resolve relative to the additional file's own directory** --
  always absolutize, and give every run its own output directory.
- **`netconvert` emits its own `programID="0"` for every `traffic_light` node**; a
  hand-authored `tlLogic` must use a different `programID` and be switched to with
  `traci.trafficlight.setProgram`, or SUMO exits with "Another logic with id X and
  programID 0 exists".
- **A `priority`-type merge lets the ramp yield entirely** -- use `zipper`, and verify
  `Z` in the compiled connection states (inherited from `implement-alinea-ramp-metering`).

## Related

- `implement-alinea-ramp-metering` — the single-ramp feedback law, zipper-merge
  construction and rate→signal translation this skill generalises.
- `build-diamond-interchange-with-signal-offset-spillback` — signalized ramp-terminal and
  internal-link spillback machinery reused for the storage-limited terminals.
- `implement-variable-speed-limits` — the other mainline bottleneck controller; its
  capacity-drop caveat is what §2's capacity-drop measurement answers.
- `quantify-sumo-run-to-run-variability` — the CRN replication design.
- `validate-congested-scenario-results-against-teleport-artifacts` — teleport discipline.
- `compare-zipper-vs-default-merge-at-lane-drop` — the lane-drop bottleneck this corridor's
  recurrent bottleneck is built from.
- [[coordinated-ramp-metering-delay-transfer-and-ramp-storage]] — the verified findings.
