---
name: evaluate-right-turn-on-red-and-leading-pedestrian-interval
description: Use this skill when the user wants to model or evaluate RIGHT-TURN control at a signalized SUMO intersection — right-turn-on-red (RTOR) permission vs a no-turn-on-red (NTOR) ban, a leading pedestrian interval (LPI), an exclusive vs shared right-turn lane, or the capacity-versus-pedestrian-safety tradeoff between them. Covers SUMO's 's' signal state ("green right-turn arrow requires stopping") as the correct and only faithful representation of RTOR and how to prove behaviourally that it differs from both 'r' and 'g', building LPI phases that hold every vehicle link red while the parallel crossings walk, counting the ON-RED vs ON-GREEN turn volume via TraCI and cross-checking it against an internal-via-lane instantInductionLoop, and separating genuine pedestrian ENCROACHMENT from queue-creep approach exposure. Trigger on mentions of right turn on red, RTOR, turn on red, no turn on red, leading pedestrian interval, LPI, exclusive right-turn lane, channelized right turn, or right-turn capacity vs pedestrian safety.
---

# Evaluate Right-Turn-on-Red and the Leading Pedestrian Interval

Right-turn control is a design object in its own right — separate from the left-turn treatments
covered by `compare-left-turn-signal-treatments` and from the exclusive-vs-concurrent pedestrian
phasing covered by `build-pedestrian-crossings-and-phasing`. The two levers that define practice
are **RTOR permission** and the **LPI**, and they trade capacity against pedestrian exposure in
opposite directions and at wildly different exchange rates.

## The one thing to get right: `s` is RTOR

SUMO's `<tlLogic>` state alphabet contains a character specifically for this:

> **`s`** — "green right-turn arrow" requires stopping — vehicles may pass the junction if no
> vehicle uses a higher priorised foe stream. They **always stop before passing**. This is only
> generated for junction type `traffic_light_right_on_red`.
> (https://sumo.dlr.de/docs/Simulation/Traffic_Lights.html)

**"Only generated for" is about netconvert's generator, not about validity.** `s` written by hand
into an additional-file `<tlLogic>` on an ordinary `type="traffic_light"` junction is accepted,
survives into the loaded program byte-identically (check with
`traci.trafficlight.getAllProgramLogics`), and produces the documented behaviour. Neither
netconvert nor sumo emits any warning about it — verified on SUMO 1.27.1.

Represent the three states this way and nothing else:

| policy | character on the right-turn link while its approach is red |
| --- | --- |
| No-turn-on-red (NTOR) | `r` |
| Right-turn-on-red (RTOR) | `s` |
| (not a policy — a modelling error) | `g` |

`g` is *not* an acceptable RTOR stand-in. It yields to the same foes but skips the stop, so it
over-serves the movement and under-produces the deceleration that is the safety-relevant part of
the manoeuvre. Prove the distinction rather than assuming it — `scripts/probe_s_state.py` runs a
`{r, s, g} x {conflicting traffic on/off} x {pedestrians on/off}` factorial at 0.1 s step on one
fixed geometry and reports, per condition, the on-red volume, the minimum speed in the last 15 m
of the approach, the full-stop fraction, and the stop-line speed. Expect: `r` → exactly 0 on-red
volume; `s` → non-zero volume, **full-stop fraction 1.000**, and volume that *falls* when either
conflicting vehicles or pedestrians are switched on (that fall is the proof it yields to both);
`g` → non-zero volume with a low stop fraction and a higher stop-line speed.

**Classify by PHASE, not by character, when `g` is one of the arms.** Under a `g`-on-red program
the character is identical on red and on green, so a character-based classifier reports zero
on-red volume for a purely definitional reason. This is exactly why SUMO needs a separate `s`.

## Network: two geometry variants, one demand set

Hand-author `.nod.xml`/`.edg.xml`/`.con.xml` and compile with

```bash
netconvert -n base.nod.xml -e base.edg.xml -x base.con.xml \
    --sidewalks.guess --crossings.guess --walkingareas \
    --no-turnarounds true --tls.default-type static -o net.xml
```

`scripts/build_networks.py` builds both variants:

- **A, exclusive right-turn lane** — vehicle lanes `[R] [T] [L]`, right turn its own connection
  from its own lane.
- **B, shared through+right** — vehicle lanes `[T+R] [L]`; B is the same intersection *without*
  the added lane, which is the actual design decision.

**`--sidewalks.guess` prepends the sidewalk as lane 0 and shifts every vehicle lane index by one.**
The `fromLane`/`toLane` you wrote in `.con.xml` refer to pre-sidewalk indices and netconvert
remaps them — do not assume either way, read the compiled net back. Put the right turn and the
through movement into the *same* receiving lane so the RTOR merge is a real merge the SSM device
can see.

Verify on the compiled net, never on netconvert's exit code:
`state-string length == count(<connection tl=...>) for vehicle links + count for crossing links`.
`scripts/build_networks.py` does this and dumps the whole linkIndex map; `outputs/net_verification.txt`
in the reference episode shows what a PASS looks like (16 = 12 vehicle + 4 crossing).

## Generate every state string from the compiled net's own link map

`scripts/linkmap.py` turns a compiled net into a `LinkMap` exposing `right(a)`, `thru(a)`,
`left(a)`, `leg_xing[a]`, `parallel_crossings(pair)` and `foe_crossings_of_right(a)` — all derived
from `<connection tl=... linkIndex=...>` and each crossing edge's own `crossingEdges` attribute.
`scripts/gen_programs.py` builds all four RTOR x LPI programs from it. Never hand-type a state
string; a single mistyped `g`/`s`/`r` silently invalidates the comparison (same lesson as
`compare-left-turn-signal-treatments`).

Which crossings are which matters and is easy to get backwards:

- The crossings **parallel** to a direction pair's vehicle green are the ones on the *other*
  pair's legs (during an N-S green, the E-leg and W-leg crosswalks walk).
- A right turn's foe crossings are the crossing on **its own approach leg** and the one on **its
  receiving leg**. So the *permitted on-green* right turn conflicts with the receiving-leg
  crossing, and the *on-red* right turn conflicts with the crossing on its own leg (which is
  green during the cross street's phase). Both exist; they are different conflicts.

## Build the LPI by splitting the green, not by adding time

An LPI must not change the cycle, the phase boundaries, or the pedestrian WALK interval — only the
vehicle green:

```
no LPI :  ... all-red 2 s | THRU 30 s (through=G, right=g, parallel crossings=G) | yellow 3 s ...
LPI    :  ... all-red 2 s | LPI 5 s (ALL vehicle links r, parallel crossings=G)
                          | THRU 25 s (through=G, right=g, parallel crossings=G) | yellow 3 s ...
```

Pedestrian green is 30 s in both; vehicle green drops 30 → 25 s. That isolation is what makes any
measured pedestrian-conflict difference attributable to the LPI rather than to a different
pedestrian service rate — confirm it by checking that pedestrian crossing wait and walk `timeLoss`
are statistically identical across the LPI and no-LPI cells.

**During the LPI, right-turn links must be hard `r`, not `s`** — that is the definition of a
leading pedestrian interval, and it is also where the LPI's entire capacity cost comes from.

An additional-file `<tlLogic>` cannot reuse the net's own `programID` and is **not** activated
automatically; give it a distinct id and call `traci.trafficlight.setProgram(tls, id)` after
`traci.start()` (same trap as `build-pedestrian-crossings-and-phasing`).

## Counting turns on red — and why an upstream detector cannot do it

Do not infer that RTOR worked from aggregate delay. Count it.

**Primary instrument (TraCI, `scripts/run_cell.py`)**: for every right-turning vehicle, read the
character at *its own* right-turn link index at the simulation step in which the vehicle's front
first appears on that turn's internal `via` lane. `r`/`s` → on-red, `g`/`G` → on-green, `y` →
on-yellow. In the NTOR cells the count of `r` crossings must be **exactly zero**; if it is not,
the NTOR representation is wrong.

**Independent cross-check**: an `instantInductionLoop` **on the right turn's internal via lane**
at `pos="1.0"`, classified by an *analytic* reconstruction of the phase table (durations only, no
TraCI). Validate the reconstruction itself by comparing it to `getRedYellowGreenState` at every
step — it should mismatch zero times.

> **An upstream stop-bar detector cannot classify turns on red.** A loop 2 m before the line
> agrees on total volume but mislabels a large share of RTOR vehicles, because a vehicle *held at
> the line* has already passed every upstream detector: the loop times the ARRIVAL at the line,
> not the DEPARTURE from it, and the gap between the two is the whole RTOR waiting time. Put the
> detector on the internal lane.

## Measure capacity in a separate saturated regime

Right-turn *capacity* is only observable when the movement is oversaturated. Run two demand
regimes on the same cells:

- **capacity** — right-turn demand far above capacity (e.g. 1200 veh/h/approach) so served volume
  *is* capacity, decomposed into on-green and on-red;
- **operational** — right-turn demand at a defensible v/c against the *measured* NTOR capacity
  (`scripts/calibrate_demand.py` measures it first), for delay, pedestrian and conflict metrics.

Setting the operational demand without measuring capacity first will silently produce a degenerate
NTOR baseline: **permitted right-turn capacity is dominated by the conflicting pedestrian volume,
not by green time** — measured 468 → 305 → 218 → 150 veh/h/lane as the parallel crossing goes
0 → 100 → 200 → 400 ped/h. Always state the crossing volume next to any right-turn capacity.

Use `--time-to-teleport -1` and check teleports and collisions are zero
(`validate-congested-scenario-results-against-teleport-artifacts`).

## Pedestrian conflict exposure: split encroachment from approach exposure

SUMO's SSM device has no pedestrian-aware mode ([[surrogate-safety-measures]]), so this is a TraCI
measurement. Gate: a right-turning vehicle within 8 m of a pedestrian on one of *that turn's* foe
crossings, with `d/v < 2 s` while the vehicle moves at `>= 1 m/s`.

**That gate alone is not enough.** It also fires for a vehicle still upstream of the stop line —
creeping in a queue or decelerating — which is why a heavily-queued NTOR baseline reports a large
"on-red conflict" count for vehicles that never legally enter anything. Record whether the vehicle
was **past the stop line (on the internal via lane)** at the moment of minimum distance and report
two numbers:

- **encroachment** — vehicle inside the junction. This is the safety-relevant count.
- **approach exposure** — same proximity, vehicle still upstream. This is a congestion artefact.

Without the split, the conflict comparison measures congestion as much as it measures the
treatment.

For the vehicle-vehicle side, use the SSM device and filter to right-turn merges: ego is a
right-turner, encounter `type` in `{6,7,8,19}` (merging), and the foe's destination edge equals the
right-turner's. **Parse the SSM XML with `iterparse` and call `el.clear()` only on `<conflict>`** —
clearing every element wipes the `<minTTC>` child's attributes before the parent's end event fires
and silently yields zero conflicts.

## Delay convention

Use the project's HCM segment convention ([[hcm-control-delay-vs-sumo-delay-metrics]]): 250 m
upstream of the stop line to 100 m past the junction, minus a **measured** per-movement free-flow
datum. `scripts/measure_freeflow.py` measures it with **one isolated single-movement run per
movement** — an all-green program with every movement loaded gridlocks. Pin
`speedFactor="1.0" speedDev="0"`. Measured 27.0–28.5 s against a geometric datum of 25.20 s; using
the geometric datum would inflate every control delay by 1.8–3.3 s.

## What the comparison tends to show

Verified on a 4-leg intersection, 100 s cycle, ~200 ped/h per crossing, 34.7 % right-turn share,
10 seeds per cell (see [[right-turn-on-red-and-leading-pedestrian-interval]] for the numbers with
confidence intervals):

- RTOR roughly **2.4x**es right-turn capacity with an exclusive lane; **~56 %** of that gain
  survives a shared through+right lane, and the on-red *share* collapses from ~65 % to ~16 %.
- A 5 s LPI gives back only **~1.7 %** of the RTOR capacity gain, and its cost falls on the
  **through** movement, not the right turn — because at a concurrent crossing the permitted right
  turn is pedestrian-constrained and was not using those seconds anyway.
- **Banning RTOR can increase measured pedestrian encroachment**, because forcing the whole
  right-turn demand to discharge inside the green drives it straight into the pedestrian platoon.
  The LPI is the cheap lever; the ban is not a lever at all on this axis.
- Crediting the measured on-red volume as capacity gained (the HCM convention) **over-states** it,
  because turning on red cannibalises the green: it removes the standing queue that would have
  discharged at saturation headway.

Do not carry these magnitudes to another pedestrian volume or demand mix — every one of them is a
strong function of the conflicting crossing volume.

## Gotchas

- **`s` only appears in netconvert output for `traffic_light_right_on_red` junctions, but it is
  valid anywhere** — write it yourself and verify it round-trips through the loaded program.
- **Never classify RTOR by state character when a `g`-on-red arm is in the comparison** — classify
  by phase.
- **An upstream stop-bar loop cannot time a departure from the stop line.** Use the internal via
  lane.
- **`--sidewalks.guess` shifts vehicle lane indices** — re-derive every index from the compiled net.
- **A ped-vehicle proximity count without a past-the-stop-line filter measures queueing**, not the
  treatment.
- **SSM `iterparse` + blanket `el.clear()` silently returns zero conflicts.**
- **A concurrent-crossing right turn's capacity is set by pedestrians, not green time** — measure
  it before choosing a demand level, or the baseline cell will be degenerate.

## Related

- `build-pedestrian-crossings-and-phasing` — the crossing/walkingarea infrastructure, crossing link
  indexing and TraCI ped-vehicle exposure technique this skill specialises for right turns.
- `compare-left-turn-signal-treatments` — the sibling turn-treatment study (left turns) and the
  generate-state-strings-from-the-link-map discipline.
- `create-single-intersection`, `run-simulation`, `analyze-simulation-outputs` — base network,
  execution and output-parsing skills.
- `measure-saturation-flow-and-validate-webster-method` — the discharge-headway estimator reused
  here for the on-green and on-red saturation flows.
- `analyze-intersection-safety-with-ssm` — the SSM device configuration and encounter-type codes.
- `quantify-sumo-run-to-run-variability` — the seed-replication/CI discipline used for every cell.
- `validate-congested-scenario-results-against-teleport-artifacts` — the teleport/collision health
  checks the capacity regime needs.
- [[right-turn-on-red-and-leading-pedestrian-interval]] — the underlying mechanics, the verified
  numbers and the HCM comparison.
- [[pedestrian-crossings-and-signal-phasing]], [[surrogate-safety-measures]],
  [[hcm-control-delay-vs-sumo-delay-metrics]], [[left-turn-treatment-tradeoffs]].
