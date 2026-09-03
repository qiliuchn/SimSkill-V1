---
name: model-toll-plaza-as-queueing-facility
description: Use this skill when the user wants to model a toll plaza, weigh station, border crossing, drive-through, gate, or any other physical queueing SERVICE FACILITY in SUMO — a row of parallel single-lane channels where each vehicle must stop for a stochastic service time — and wants to compare the resulting delay against closed-form queueing theory (M/M/c, M/D/c, M/G/c Allen-Cunneen, c independent M/M/1 or M/G/1), size the facility, or find the electronic-toll penetration at which it can be removed. Covers hand-authored plain-XML fan-out/fan-in plaza geometry, per-vehicle random `<stop>` service, measuring the car-following move-up headway floor that makes real booth capacity ~35% below 3600/E[S], a TraCI join-the-shortest-queue assigner, and spillback/booth-count sizing. Trigger on mentions of toll plaza, toll booth, queueing theory validation, M/M/c, Erlang-C, service time distribution, booth capacity, electronic toll collection / ETC / transponder penetration, open-road tolling, or "does SUMO reproduce queueing theory."
---

# Model a Toll Plaza as a Queueing Service Facility

Builds a freeway toll plaza in SUMO as a genuine multi-server stochastic queueing system —
a 2-lane mainline fanning out into `c` parallel single-lane booth channels and back — and
validates the resulting delay against closed-form queueing theory. This is the first skill
in memory where a SUMO scenario is a **service facility** (customers stop, are served for a
random time, and leave) rather than a link/junction capacity problem, so the natural
benchmark is Erlang-C / Pollaczek-Khinchine rather than an HCM capacity formula.

Distinct from `model-cordon-tolling-with-generalized-cost-surcharge`, which models a toll as
a purely *perceived-cost* surcharge with real travel time and capacity untouched. That
abstraction is a correct model of an all-electronic gantry and a badly wrong model of a
manual plaza (verified: it understates delay ~16x at rho=0.86 and cannot represent
spillback at all). Use this skill when the queue itself is the object of study.

## The headline result: SUMO is NOT M/M/c, and that is not a bug

A `c`-booth plaza with random booth choice behaves as **`c` independent M/G/1 queues**, not
as one pooled M/M/c queue, and its service time is the booth transaction **plus a
car-following move-up floor**. With both corrections, Pollaczek-Khinchine matches simulation
to within 10% over rho = 0.40-0.88. Without them, M/M/c is wrong by up to 88x. See
[[toll-plaza-queueing-and-the-service-headway-floor]] for the full verified numbers.

## Building the network (`scripts/build_plaza_network.py`)

Hand-author `.typ`/`.nod`/`.edg`/`.con` and compile with netconvert, following
`create-single-intersection`'s plain-XML technique and `implement-alinea-ramp-metering`'s
linear-corridor adaptation:

```
app (2 lanes, ~1200 m queue storage)
  -> fan  (c lanes, ~140 m, lane changes ALLOWED  - the fan-out taper)
  -> lock (c lanes, ~115 m, lane changes FORBIDDEN - booth choice commits here)
  -> chin_i (1 lane) -> booth_i (1 lane, 30 m island) -> chout_i (1 lane)
  -> post (c lanes) -> exit (2 lanes, zipper drop)
```

```bash
python3 scripts/build_plaza_network.py --booths 6 --out-dir net/          # all-manual
python3 scripts/build_plaza_network.py --booths 6 --etc-booths 2 --out-dir net/  # 2 ETC-only
```

Design points that matter:

- **A separate `fan` (changes allowed) then `lock` (changes forbidden) is required.** Putting
  the no-change restriction directly where the mainline widens strands any vehicle that
  enters on the wrong lane. `fan` lets vehicles sort themselves; `lock` then commits them.
- **`app`'s two lanes must map to the `c` taper lanes without crossing connections**
  (lane 0 -> taper 0..c/2-1, lane 1 -> the rest). Crossing connections create internal
  junction conflicts that block the diverge.
- **Booth channels must be separate single-lane edges**, not lanes of one edge, so each booth
  is an independent server with its own detectors and its own queue.
- **Give the diverge junction room.** netconvert grows the junction with the lateral spread
  of the channels: with `chin` nominally 50 m the compiled edge was trimmed to **8 m** (all
  of it swallowed by internal junction lanes, leaving nowhere to put a detector or store a
  queue). Push the booth-island nodes ~120 m downstream of the diverge node and re-check the
  compiled lengths.
- **Compiled `lock` lane length shrinks as `c` shrinks.** Any e2 detector `endPos` must be
  read from the compiled net (`plaza_lib.lane_lengths()`), not hard-coded — a constant that
  works for c=6 is a fatal `does not lie on the given lane` error at c=3.

### `changeLeft="none"` does not work — use `"authority"`

Verified against netconvert 1.27.1:

| value | result |
|---|---|
| `changeLeft="none"` | **Error**: `Unknown vehicle class 'none' encountered` |
| `changeLeft=""` | **Error**: `Attribute 'changeLeft' ... is empty` |
| `changeLeft="ignoring"` | compiles "Success" but is **silently dropped** from the `.net.xml` |
| `changeLeft="authority"` | compiles, appears in the `.net.xml`, and actually blocks changes |

`"ignoring"` is the dangerous one — it looks like it worked. **Verify behaviourally, not by
grepping the net**: `scripts/verify_no_weaving.py` drives the scenario over TraCI, calls
`setLaneChangeMode(vid, 0)` (every autonomous rule and safety check off) then
`changeLane()` toward a neighbour, and counts how many actually move. Expect 0 successes on
`lock` and a healthy success rate on `fan` as the positive control (verified: 0/89 vs
123/181).

## The service mechanism: use `<stop>`, never a low-speed edge

Model each booth as a per-vehicle `<stop>` on the booth lane with a random `duration`, either
written into the route file or imposed at runtime with `vehicle.setStop`:

```xml
<vehicle id="v17" type="manual" route="r3" depart="812.40" departLane="best" departSpeed="max">
    <stop lane="booth_3_0" endPos="25.0" duration="9.37" parking="false"/>
</vehicle>
```

`parking="false"` is essential — the vehicle must block its lane so followers queue behind it.

**A speed-based booth (`variableSpeedSign` or a low-speed edge) does NOT work and this was
verified as a negative result.** A 30 m segment at 3.75 m/s ("8 s service") produced a mean
saturated departure headway of 5.892 s versus 5.871 s with **no booth at all** — within 0.4%
of imposing no constraint whatsoever. The reason is structural: a 30 m low-speed *segment*
holds ~4 vehicles simultaneously at car-following spacing, so it is a slow *link* with
capacity `v/(v*tau + L + minGap)` ~ 1200 veh/h/lane, not a single-customer *server*. Anyone
modelling a booth, gate or drive-through as a low-speed edge is modelling the wrong object.

## Always measure the move-up headway floor before applying any formula

Run the plaza deliberately over-saturated (`scripts/verify_mechanism.py`) so every booth has
a standing queue, then read from `--stop-output`:

```
floor = mean( started[k+1] - ended[k] )   per booth, over the saturated window
```

This is the time for the follower to release, accelerate from rest and roll forward into the
booth. Verified: **4.28 s, essentially independent of the service-time distribution and of
its mean** (4.28 / 4.28 / 4.29 / 4.33 s for exponential-8 s, Erlang-8, deterministic-8 and
exponential-3 s). Two consequences, both large:

- **Effective service time `S' = S + floor`.** Booth capacity is `3600/E[S']`, not
  `3600/E[S]`: 289 veh/h instead of 450 at 8 s service (**-35.7%**), and 489 instead of 1200
  at 3 s (**-59.3%**, worse because the fixed floor is a bigger share of a shorter
  transaction). Sizing on `3600/E[S]` cost **three extra booths** in a real design case here.
- **The floor is deterministic, so it *reduces* variability.** A nominally exponential
  (C^2 = 1) transaction becomes a shifted exponential with **C^2_s = 0.39** measured from the
  saturated departure headways. The plaza is M/G, not M/M, purely because of car-following.

Always cross-check that the measurement window really is saturated: compare the measured
departure headway against the arrival headway `3600/(rate/c)`. Two of six variants in the
first pass here were silently demand-limited and produced meaningless "capacity" numbers.

## Measuring queue delay correctly

`tripinfo`'s `timeLoss` and `waitingTime` cover the whole trip and cannot separate plaza
queueing from the plaza's own geometric speed drop. Define it explicitly instead
(`scripts/metrics.py`):

```
Wq(i) = t_service_start(i) - t_plaza_entry(i) - T_ff(booth(i))
```

- `t_plaza_entry` from an `<instantInductionLoop>` on each mainline lane (per-vehicle
  timestamps with `vehID`, which aggregated e1/e3 output cannot give you).
- `t_service_start` from `--stop-output`'s `started`.
- `T_ff(b)` calibrated as the **mean** entry-to-service-start time per booth in a dedicated
  near-empty run (~60 veh/h over a long horizon).

**Two estimator traps, both hit and fixed here:**

1. **Zero driver speed dispersion, or the noise swamps the signal.** With `speedDev="0.10"`
   the free-flow traverse had sd 3.5-9.3 s on a ~46 s trip — comparable to the delay being
   measured at low rho. Set `speedDev="0"`; the stochasticity of interest is the *service
   time*, not the free-flow speed.
2. **Do not clip negative delays at zero.** Clipping injects a bias of order
   `E[max(-noise,0)]` — measured at **+1.13 s of pure bias at rho=0.30**, larger than the
   true delay at that point. Report the unclipped mean and the fraction negative.

Check Little's Law on an **independent instrument**: the e3 `entryExitDetector` reports both
mean in-zone travel time and mean number in zone, computed by SUMO itself. `L` vs `lambda*W`
agreed to -0.35%..+1.35% across 24 cells here. (Computing `Lq` as a time-average of your own
per-vehicle intervals and comparing it to `lambda * mean(Wq)` is an arithmetic identity, not
a check.)

## Comparing against theory (`plaza_lib.py`)

`erlang_c`, `mmc`, `mdc_cosmetatos`, `allen_cunneen`, `c_mm1`, `c_mg1` are all implemented.
**Compare against the pooled AND the partitioned models** — the whole point is that a plaza
is partitioned:

- Pooled: M/M/c (Erlang-C), M/D/c (Cosmetatos), M/G/c (Allen-Cunneen,
  `Wq ~ Wq_MMc * (Ca^2+Cs^2)/2`).
- Partitioned: `c` independent M/M/1, and **`c` independent M/G/1 (Pollaczek-Khinchine,
  `Wq = rho_i * E[S'] * (1+Cs^2) / (2(1-rho_i))`) — this is the one that fits.**

Feed the formulas `E[S']` and `C^2_s` **measured** from the saturation run, never nominal
values. Define rho against measured capacity too.

## The TraCI join-the-shortest-queue assigner (`run_plaza.py --controller shortest`)

Reads per-booth queue length via lane subscriptions across `fan_j` + `lock_j` + `chin_j` +
`booth_j`, re-routes each arriving vehicle with `setRoute`, imposes its service with
`setStop`, sets `setLaneChangeMode(1621)` and issues an explicit `changeLane` onto the
mainline lane that feeds the chosen booth. Two details are load-bearing:

- **Count vehicles already assigned but still upstream.** Without adding those, the assigner
  sends an entire platoon to the same "shortest" booth on stale information.
- **Use a rotating tie-break**, or equal-length queues systematically favour booth 0.

It closes 69-91% of the gap between random assignment and the pooled M/G/c ideal (65% delay
reduction at rho=0.81), with the residual falling to 1.61x Allen-Cunneen at rho=0.95. The
residual is the **no-jockeying constraint** (a committed vehicle cannot switch to a booth
that empties first), not the headway floor — testable, because the same `E[S']` and `C^2_s`
already fit the random arm to within 10%.

**Counter-intuitive, verified: deciding LATER makes it worse.** Moving the decision point
from 600 m to 1150 m along a 1196 m approach — fresher information, less commitment lag —
was worse at every rho (15.33 vs 12.93 s at rho=0.81) and closed only 44-66% of the gap at
low-to-mid rho (narrowing to 71.8%/81.7% at rho=0.875/0.95, comparable to deciding early).
There is not enough remaining distance to execute the strategic lane change before `lock`
commits the vehicle. Better information is worthless if the vehicle cannot act on it.

## Report per-booth DELAY imbalance, not utilisation imbalance

Utilisation is nearly conserved across assignment policies — the same total work is done by
the same servers, so busy fraction has little room to differ. Verified at rho=0.80: the
across-booth CV of busy fraction moved only 0.035 -> 0.014, while the across-booth CV of mean
queue delay moved **0.154 -> 0.053**. Reporting utilisation CV alone would have made the
assigner look nearly useless. Also check throughput CV against the multinomial noise floor
`1/sqrt(n/c)` before calling any imbalance real — under random routing here it matched it
exactly (0.037-0.067 vs 0.065), i.e. there was no imbalance to fix.

## Sizing and the ETC-penetration design study (`scripts/design_study.py`)

Sweep booth count at a fixed design demand against a stated p95-delay threshold **and** an
upstream-storage constraint. Watch for the **queue-length ceiling effect** (the same one
documented in [[zipper-merge-lane-drop-discharge]]): once the queue fills the approach,
on-road queue length saturates and stops discriminating — the excess moves into
`tripinfo`'s `departDelay` (0.3 s -> 120.4 s -> 884.4 s across c=5,4,3 here). Report both.

For the ETC study, implement dedicated lanes as real compiled `allow="custom1"` permissions
on the channel edges, not just as a demand-side assignment rule, and test a
**penetration-matched** dedication (k = round(c*penetration)) as well as a fixed-k one — a
fixed-k policy is a strawman. Verified negative result: **dedicated ETC lanes never beat
all-mixed-use booths at any penetration**, because pooling servers always dominates
partitioning them, and 1/c lane granularity guarantees a mismatch at most penetrations.

## Gotchas

- **`changeLeft="ignoring"` compiles silently to a no-op** — verify lane-change prohibitions
  behaviourally with `setLaneChangeMode(0)`, not by reading the source XML.
- **A low-speed edge is not a server.** Verified within 0.4% of no constraint at all.
- **`3600/E[S]` is not booth capacity** — add the measured move-up floor first.
- **Confirm your capacity-measurement run is actually saturated** by comparing measured
  departure headway to the arrival headway; a demand-limited run yields a meaningless number.
- **e2 `endPos` must come from the compiled net**, since junction trimming makes lane lengths
  depend on the channel count.
- **`speedDev` noise can exceed the delay you are measuring**; zero it for a queueing study.
- **Never clip negative measured delays at zero** — it is a pure positive bias.
- **Five seeds is not enough near rho = 0.95** (CI was +/-41% of the mean here), exactly the
  near-capacity bimodality documented in [[sumo-stochastic-variability-and-replication-design]].
- Every output path in the generated `.sumocfg`/additional file must be **absolute** — the
  `edgeData`/detector `file` attribute resolves relative to the additional file's own
  directory (see `analyze-simulation-outputs`).

## Related

- `create-single-intersection` — the plain-XML + netconvert technique this network build
  adapts.
- `implement-alinea-ramp-metering` — the linear freeway-corridor plain-XML pattern and the
  zipper-state compiled-net verification reused for the fan-in.
- `compare-zipper-vs-default-merge-at-lane-drop` — the fan-in merge pattern, and the
  queue-length ceiling effect that recurs in this skill's spillback study.
- `set-vehicle-state` — `setStop` / `changeLane` / `setLaneChangeMode` semantics used by the
  shortest-queue assigner.
- `model-cordon-tolling-with-generalized-cost-surcharge` — the perceived-cost toll
  abstraction this skill cross-checks against; correct for an all-electronic gantry, wrong
  for a manual plaza.
- `model-managed-lanes-with-dynamic-tolling-and-self-selection` — the empty-lane paradox
  reappears here as the dedicated-ETC-lane result.
- `quantify-sumo-run-to-run-variability` — the replication/CI methodology followed here.
- `validate-congested-scenario-results-against-teleport-artifacts` — teleport discipline;
  zero teleports occurred across all 120 sweep runs here, which is what makes the congested
  results trustworthy.
- `analyze-simulation-outputs` — general tripinfo/summary conventions; the per-vehicle
  instant-loop and stop-output parsing here is a custom addition.
- [[toll-plaza-queueing-and-the-service-headway-floor]] — the verified quantitative findings,
  the theory-model comparison table, and the design-study results.
