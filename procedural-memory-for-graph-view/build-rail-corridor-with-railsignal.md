---
name: build-rail-corridor-with-railsignal
description: Use this skill when the user wants to model rail/train traffic in SUMO — a single-track bidirectional rail corridor with a passing siding, trains using vClass="rail" and the Rail car-following model, and rail_signal junctions that arbitrate meets between opposing trains. Covers hand-authoring bidirectional rail track (verifying bidi-recognition and turnout wiring from the compiled net), defining train vTypes with carFollowModel="Rail"/trainType, scheduling station dwell stops, and verifying — from FCD/stop-output, not assumption — that a rail_signal genuinely resolved a meet at a siding rather than producing a head-on conflict or an origin-station standoff. Trigger on mentions of rail, train, railSignal, rail_signal, single-track, passing siding, or carFollowModel="Rail".
related_skills:
  - create-roundabout-network
  - model-vclass-lane-permissions
  - simulate-multimodal-transit
  - run-simulation
  - analyze-simulation-outputs
related_skills_for_graph_view:
  - "[[create-roundabout-network]]"
  - "[[model-vclass-lane-permissions]]"
  - "[[simulate-multimodal-transit]]"
  - "[[run-simulation]]"
  - "[[analyze-simulation-outputs]]"
related_pages:
  - "[[rail-simulation-and-railsignal]]"
---

# Build a Rail Corridor with railSignal

Models rail/train traffic in SUMO: a single-track bidirectional corridor between two stations with a mid-point passing siding, and `rail_signal` junctions that arbitrate meets between opposing trains. This is SimSkill's only skill covering SUMO's genuinely distinct railway mechanics — every other "transit" skill (`simulate-multimodal-transit`) models buses as ordinary road vehicles on shared lanes, never touching bidirectional single-track conflict resolution or the `Rail` car-following model.

## Network geometry: bidirectional single track with a passing siding

Rail edges are plain `vClass="rail"`, single-lane edges with `spreadType="center"` so an opposite-direction edge pair overlays exactly and `netconvert` recognizes it as genuinely bidirectional (each edge in the compiled net carries a `bidi=` attribute pointing at its counterpart). A passing siding is two parallel edges between the same two nodes — a straight "main" track and an offset "siding" track (given an explicit `shape=` to route it visibly apart) — so a held train can wait on one track while the other passes.

`templates/rail.nod.xml` and `templates/rail.edg.xml` are a working, verified 6-node reference: `A - SA - W - [main+siding] - E - SB - B` (~3km). Critically, **stations sit on their own dedicated block edges (A↔SA, SB↔B) behind `rail_signal` nodes (SA, SB), not directly on the shared single-track section** — this is the single most important design lesson (see Gotchas).

```bash
netconvert --node-files rail.nod.xml --edge-files rail.edg.xml -o rail.net.xml
```

**Verify the network structure from the compiled net, never assume it from the source XML**: grep for `bidi=` on each edge to confirm bidirectional recognition, and inspect the `<connection>` elements at each `rail_signal` junction to confirm the siding turnout wiring is what was intended (which edges connect to which at W and E) — the same discipline `create-roundabout-network`/`model-vclass-lane-permissions` use for verifying right-of-way/permissions on the compiled net rather than the source.

## Train definitions

```xml
<vType id="ice3" vClass="rail" carFollowModel="Rail" trainType="ICE3" length="200" accel="0.8" decel="0.9" maxSpeed="44.44"/>
```

`carFollowModel="Rail"` switches to SUMO's rail-specific car-following dynamics; `trainType` (e.g. `ICE3`, `Freight`, `RE_DoSto`) supplies realistic traction/resistance/mass behavior on top of it. Set `length`/`accel`/`decel`/`maxSpeed` explicitly for the specific train being modeled — see `templates/trains.rou.xml` for a worked passenger-vs-freight pairing.

Station dwells use ordinary duration-based `<stop>` elements referencing a `busStop` placed on the station's dedicated block edge (`busStop` works for `vClass="rail"`, no separate rail-stop element is needed) — see `templates/stations.add.xml`.

## Running and verifying a meet was genuinely resolved

Run microscopically with `--fcd-output`, `--tripinfo-output`, and `--stop-output` enabled — FCD is essential here because it's the only way to directly observe *where* a train was held, not just *that* it waited (from `tripinfo`'s `waitingTime`).

**Don't trust that a rail_signal "worked" just because the run completed without a collision or teleport** — verify specifically:
1. Which train was held, where, and for how long — a stationary period (near-zero speed) that is *not* a scheduled station dwell.
2. The two trains' occupancy of the genuinely single-track section(s) was time-disjoint — never simultaneously present on the same single-track bidi edge.
3. No teleports/collisions occurred (check `summary.xml`/`--collision-output`), and both trains actually arrived (non-negative arrival time in tripinfo) — confirming no deadlock.

`scripts/verify_rail_meet.py` automates all three checks: it reads scheduled station-dwell windows directly from `--stop-output` (so a train sitting at a platform isn't misreported as a signal hold), classifies FCD positions into named sections via an edge-to-base-name mapping, and reports each train's held periods, section-occupancy windows, and any head-on co-occupancy.

```bash
python scripts/verify_rail_meet.py --fcd outputs/fcd.xml --stop-output outputs/stops.xml \
    --trains train_AB,train_BA \
    --edge-pairs "SA_W=SA-W,W_SA=SA-W,E_SB=E-SB,SB_E=E-SB,main_WE=main,main_EW=main,sid_WE=sid,sid_EW=sid" \
    --single-track-bases SA-W,E-SB
```

## What a well-designed meet scenario shows

Measured on the reference 3km corridor: a faster passenger train (ICE3) departing alongside a slower freight train from opposite ends was held 72s at the siding turnout — genuinely stationary in FCD, matching `tripinfo`'s `waitingTime` exactly — while the freight train passed through the shared single-track section on the parallel siding track. The two trains' occupancy of the conflicted section was confirmed time-disjoint; zero collisions, zero teleports, both completed. The freight train (which entered the contested section first) was never held at all — signal priority in this scenario followed entry order, not train class or speed.

## Gotchas

- **A station platform placed directly on the shared single-track section (not behind its own signal block) can produce an origin-station standoff instead of a siding meet.** In one build, an initial design without dedicated station-entrance signals (SA/SB) was collision- and deadlock-free, but held the waiting train *at its origin station* rather than at the siding — because the opposing train's platform occupied the shared single-track block from the very start of the simulation. Give each station its own block behind a `rail_signal` (or equivalent) so a dwelling train doesn't itself block the through section.
- **`spreadType="center"` on both directions of an edge pair is what makes `netconvert` recognize bidirectional track** — omitting it or offsetting the pair can prevent the `bidi=` relationship from being established.
- **`busStop` works fine for rail vClass station platforms** — no separate rail-specific stop element is needed.
- **Verify holds and section occupancy from FCD, not from `tripinfo` alone** — `waitingTime` confirms *that* a train waited, but only FCD confirms *where*, which is what distinguishes a genuine siding meet from an origin-station standoff or (in a broken design) a head-on.

## Related

- `create-roundabout-network`, `model-vclass-lane-permissions` — the hand-authored-plain-XML-plus-verify-from-compiled-net discipline this skill applies to rail track and `rail_signal` junctions.
- `simulate-multimodal-transit` — SimSkill's other scheduled-vehicle skill (buses on ordinary road lanes), contrasted with this skill's dedicated rail infrastructure and signal semantics.
- `run-simulation`, `analyze-simulation-outputs` — general run/analysis skills this one specializes for rail tripinfo/FCD/stop-output verification.
- [[rail-simulation-and-railsignal]] — the underlying SUMO rail concepts (bidirectional track, `rail_signal` block semantics, `carFollowModel="Rail"`/`trainType`, and the verified deadlock-free-meet finding).
