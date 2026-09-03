---
summary: How SUMO represents a car-to-transit (park-and-ride) person trip — personTrip modes="car public", duarouter's --persontrip.transfer.car-walk options, and the fact that the router never actually parks the car in a parkingArea — plus measured park-and-ride mode share, lot-occupancy, corridor-relief and undersized-lot failure findings.
keywords:
  - park-and-ride
  - intermodal-transfer
  - persontrip-transfer-car-walk
  - parkingArea-coupling
  - kiss-and-ride
created: 2026-08-04T05:00:00
last_updated: 2026-08-04T05:00:00
sources:
  - "[[episodic-memory/2026-08-04_05-00-00/attempts/attempt-1/action-agent-output.json]]"
  - https://sumo.dlr.de/docs/Simulation/Intermodal_Routing.html
  - https://sumo.dlr.de/docs/Simulation/ParkingArea.html
  - https://sumo.dlr.de/docs/Specification/Persons.html
related_pages:
  - "[[public-transport-and-intermodal-routing]]"
  - "[[parking-areas-and-rerouters]]"
  - "[[duarouter]]"
  - "[[sumo-output-files]]"
  - "[[downs-thomson-paradox-and-mode-choice-equilibrium]]"
  - "[[bus-stop-infrastructure-design-parking-mechanism-and-tsp-interaction]]"
  - "[[cruising-for-parking-search-externality-and-remedies]]"
  - "[[teleport-artifacts-and-gridlock-resolution-validity]]"
  - "[[dynamic-user-equilibrium-and-wardrop]]"
related_skills:
  - build-and-evaluate-park-and-ride-corridor
  - model-parking-with-rerouting
  - simulate-multimodal-transit
  - convert-trips-to-routes
related_skills_for_graph_view:
  - "[[build-and-evaluate-park-and-ride-corridor]]"
  - "[[model-parking-with-rerouting]]"
  - "[[simulate-multimodal-transit]]"
  - "[[convert-trips-to-routes]]"
---

# Car-to-Transit Intermodal Transfer and Park-and-Ride

[[public-transport-and-intermodal-routing]] covers the *walk*-to-transit half of SUMO's
intermodal model. This page covers the *car*-to-transit half: a person who drives, leaves the
car, and finishes by bus/BRT/rail. It joins that page's `busStop`/`line`/`<access>` machinery
to [[parking-areas-and-rerouters]]' `parkingArea` machinery — and the joint between the two is
much weaker than it looks.

## Expressing the demand

```xml
<person id="am_0" depart="135.10">
    <personTrip from="SUB20_SUB21" to="CBD02_CBD12" modes="car public" vTypes="car"/>
</person>
```

`modes="car public"` lets `duarouter` choose per person between drive-all-the-way and
drive-part-way-then-ride. Where the car may be left is controlled by a separate option:

```
--persontrip.transfer.car-walk STR[]   # 'parkingAreas', 'ptStops', 'allJunctions' (combinable)
```

The mode set and the transfer rule are independent; getting `modes` right but leaving the
default transfer rule in place changes what P+R even means in the run.

## The three transfer options are three different policies

Measured on one corridor, same demand (1 200 persons), same congested weights:

| option | resulting plan | lot coupling | P+R share | walk-access | arterial delay vs no-P+R |
|---|---|---|---|---|---|
| `parkingAreas` | `ride(car)` → `walk` → `access` → `ride(PT)` → `access` → `walk` | car leg ends inside a `parkingArea` | 15.7 % | 362 s | −40.9 % |
| `ptStops` | `ride(car, busStop=…)` → `ride(PT)` → `walk` | **none** — car leg ends *at the stop* | 23.1 % | 204 s | −55.4 % |
| `allJunctions` | car abandoned at any junction, then walk | incidental only | 18.5 % | 357 s | −65.5 % |

`ptStops` is really **kiss-and-ride**: the car delivers the traveller to the platform and
vanishes, so there is no walk-access penalty and no parking supply involved at all. It scores
best on mode share precisely because it is the least constrained — which makes it the wrong
option for any study whose subject is parking capacity, since `roadsideCapacity` is then never
touched. `allJunctions` is the most permissive of all (abandon the car anywhere), which is why
it relieves the corridor most and why its numbers should be read as an upper bound, not a
policy.

## The critical gotcha: the router does not park the car

**Verified on SUMO 1.27.1.** With `--persontrip.transfer.car-walk parkingAreas`, `duarouter`
treats `parkingArea` elements as *permitted transfer geometry only*. It ends the car leg at
the lot's position, but the `<vehicle>` it generates carries **no parking stop**:

```xml
<vehicle id="am_0_0" type="car" depart="triggered">
    <route edges="SUB20_SUB21 SUB21_ST ST_A0 A0_A1"/>   <!-- no <stop parkingArea=.../> -->
</vehicle>
<person id="am_0" depart="135.10">
    <ride from="SUB20_SUB21" to="A0_A1" arrivalPos="1025.00" lines="am_0_0"/>
    <walk edges="A0_A1" busStop="BS_MID_E"/>
    <ride busStop="BS_CG_E" intended="BRT_E_2" depart="767.00"/>
    <walk edges="CBD01_CBD11 CBD01_CBD02 CBD02_CBD12"/>
</person>
```

The coupling to a space is **implicit and geometric** — via `arrivalPos` falling inside the
lot's `[startPos,endPos]` — never explicit. At simulation time the car just arrives and is
removed. Measured directly: a 20-person P+R run produced `peak_occupancy = 0` for every lot
while all 20 persons executed complete P+R plans. `roadsideCapacity` is therefore inert, and
any capacity, pricing, or overflow experiment layered on top is silently meaningless.

The remedy is a post-processing pass that injects the missing stop into each P+R vehicle:

```xml
<stop parkingArea="PR_MID" duration="100000" parking="true"/>
```

With the stop present, the same run reports peak occupancy 20/20 and the cars remain in the
lot — spaces are held for the full parked duration, with **no turnover** in an AM-only peak.
The rider disembarks at the space SUMO actually assigns (e.g. `arrivalPos 901.25`, the first
free space), not at the position the plan named. `build-and-evaluate-park-and-ride-corridor`
bundles this as `attach_parking_stops.py`.

## Free-flow routing gives 0 % park-and-ride

Under default (free-flow) edge weights, every one of 1 200 persons chose drive-all-the-way:
driving ~6 km at 22 m/s beats any walk + wait + ride chain outright. P+R only appears once the
router can see congestion. A two-pass assignment — run a drive-only baseline, write `edgeData`,
feed it back as `duarouter -w baseline/edgedata.xml` — produced the 15.7 % share above.

This is a **one-shot informed assignment, not an equilibrium** (contrast
[[dynamic-user-equilibrium-and-wardrop]]). The visible signature: after 15.7 % shifted off the
road, drive-alone travellers improved from 1 478 s to 1 185 s, while the P+R users who did the
shifting realised 1 477 s — i.e. the switchers ended up *worse off than the people they
relieved*, which is a non-equilibrium artifact of routing on stale weights, not a finding about
P+R.

## Measured corridor results

Baseline (same demand, `modes="car"` only): 1 200 drive-alone, mean door-to-door 1 478 s,
492.8 person-hours, CBD gate link carrying 1 200 veh at a mean 683.5 s (free-flow 54 s).

With `parkingAreas` P+R at 15.7 % share:

- CBD gate volume 1 200 → 1 012 (−15.7 %), mean link travel time 683.5 → 468.6 s (−31.5 %).
- Total arterial time loss 1 153 015 → 681 186 veh-s (**−40.9 %**) — the payoff is strongly
  nonlinear in the volume removed, because the gate was oversaturated.
- Corridor person-hours 492.8 → 410.2 (−16.8 %).
- Door-to-door decomposition for a P+R traveller (mean, s): drive 318 / walk-access 362 /
  wait 147 / ride 151 / egress 499. **The in-vehicle transit leg is the smallest component** —
  access, egress and wait together are 4.6× the ride itself. P+R competitiveness in SUMO is
  governed almost entirely by stop-access geometry (`<access length=…>`) and headway, not by
  transit line speed.

## Undersized lots: what actually happens, and why it is worse than no P+R

`duarouter` is **capacity-blind** — it assigned all 188 P+R trips to a lot regardless of whether
that lot had 400, 100, 50 or 20 spaces, with no warning. SUMO does not silently drop the
surplus and does not self-reroute it. The observed chain, sweeping `roadsideCapacity`:

| capacity | realised P+R | never arrived | teleports | arterial time loss vs no-P+R |
|---|---|---|---|---|
| 400 / 200 | 188 | 0 | 0 / 1 | −41 % / −43 % |
| 100 | 176 | 12 | 79 | **+29 %** |
| 50 | 129 | 59 | 83 | **+114 %** |
| 20 | 130 | 58 | 113 | **+152 %** |

A car turned away from a full lot **waits on the approach lane for a space** — mean P+R car-leg
duration 5 191 s, max 18 586 s at capacity 50 — and blocks through traffic behind it. The lot's
own link's time loss rose from 3 096 to 1 871 877 veh-s (~600×), and the bottleneck simply moved
upstream from the CBD gate to the lot mouth. `--time-to-teleport` is what converts the stall
into a countable failure (see [[teleport-artifacts-and-gridlock-resolution-validity]]).

Two silent-failure signatures worth grepping for:

- persons still in `traci.person.getIDList()` at simulation end (never arrived) — and note that
  **most of them were drive-alone travellers**, collateral damage from the lot queue, not the
  P+R users themselves;
- `<ride vehicle="NULL" depart="-1" duration="-1"/>` inside `<personinfo>` — the traveller
  reached the platform but no transit vehicle ever came (here, because the lot queue delayed
  them past the end of the service window). The enclosing `<personinfo>` carries
  `duration="-1"`, so any mean computed without filtering these is wrong — and, perversely,
  *looks better* than reality because the worst trips contribute −1.

**Policy conclusion: an undersized P+R lot is worse for the corridor than no P+R at all.**

## The overflow remedy composes safely with person plans

Adding a `<rerouter>` with `<parkingAreaReroute>` alternatives on edges upstream of the lot,
plus `--device.rerouting.probability 1`, fully repaired every undersized case: capacity 50 →
50 parked in the primary lot + 138 in the secondary, **0 teleports, 0 never-arrived**, full
15.7 % P+R share restored, arterial time loss back to −33.5 % vs. baseline (from +114 %).

The non-obvious part is what happens to the *person* riding in a rerouted car. Their plan named
a specific lot and a specific walk edge:

```xml
<ride to="A0_A1" arrivalPos="1150.00" lines="am_872_0"/>
<walk edges="A0_A1" busStop="BS_MID_E"/>
```

At runtime the car was redirected to a lot on a *different edge* (`A1_A2`, pos 30.62). The
person disembarked there and SUMO **re-resolved the walk to `BS_MID_E` from the actual
disembark position** (80.62 m across the junction) rather than stranding them. Walk legs that
target a `busStop` are re-routed from wherever the rider actually gets out; the `edges=`
attribute is not binding. The design requirement this implies: **an overflow lot must have
pedestrian access to a stop on the same line**, or the re-resolved walk becomes very long or
impossible.

## Lot siting, headway, and the PM return

- **Siting**: given both a suburban lot (at the origin-side station) and an intermediate lot
  2.4 km closer to the CBD, **100 % of P+R users chose the intermediate lot** — it lets them
  drive the uncongested part of the arterial and skip only the queued part. Forced separately:
  suburban-only 162 users / 411.8 person-hours; intermediate-only 188 / 410.2. Siting moves
  *who uses it* much more than it moves corridor totals.
- **Headway** (120 / 300 / 600 / 900 s): P+R share 19.3 / 15.7 / 11.6 / 8.9 % — strongly and
  monotonically responsive. Corridor person-hours, however, stayed within 409–440 h across the
  whole sweep: nearly all of the corridor benefit comes from removing the *first* slice of
  traffic from an oversaturated gate, and little more accrues beyond that.
- **PM return**: **SUMO has no notion that a parked car belongs to a person.** A PM
  `personTrip` from the CBD generates a brand-new vehicle at the CBD; the AM car sits in the lot
  indefinitely. Scripting an absolute release (`<stop … until="18000" duration="1"/>`) works
  cleanly — 188 occupied spaces drained to 0 within ~300 s — but note that a stop ends at
  `max(until, arrival+duration)`, so leaving a long `duration` in place makes `until` a silent
  no-op. The return leg was **not** symmetric: all 360 PM travellers drove, correctly, because
  the outbound direction was uncongested in the weights used for routing.

## Observation plumbing

- Lot occupancy over time is still **TraCI-only** (`traci.parkingarea.getVehicleCount` /
  `getVehicleIDs`); no `--parking-output` CLI flag exists as of 1.27.x — see
  [[parking-areas-and-rerouters]].
- `--stop-output` emits a row only when a stop **ends**, so a car still parked at simulation
  end writes nothing at all. `--stop-output.write-unfinished` fixes it.
- The door-to-door decomposition reads straight off `<personinfo>` legs in `tripinfo.xml`
  (see [[sumo-output-files]]): car `<ride>`, pre-transit `<walk>`+`<access>`, `waitingTime` on
  the transit `<ride>`, transit `<ride>` duration, post-transit legs.
- `file=` on an `<edgeData>` element resolves **relative to the additional file's own
  directory**, not the cwd — a cwd-relative path yields a doubled path and a hard abort.
- `summary-output`'s `collisions=` attribute is an **instantaneous state count, not a
  cumulative event count**: summing it across steps returned 18 472 for a run that
  `--collision-output` showed contained exactly one collision (a 0.64 m/s rear-end inside the
  CBD gate queue) whose state persisted to the end of the run. Count collisions with
  `--collision-output`, never by summing the summary attribute.
- A bus-only busway physically **disconnected** from the road network is a perfectly workable
  rail/BRT stand-in: `<access lane="<sidewalk>" length="…"/>` on each `busStop` is the only
  link pedestrians need, and those legs appear explicitly as `<access>` in `<personinfo>`.

See `build-and-evaluate-park-and-ride-corridor` for the bundled build/route/couple/run/analyse
pipeline behind every number on this page.
