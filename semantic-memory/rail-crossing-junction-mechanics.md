---
summary: "SUMO's rail_crossing junction type — where passing trains automatically halt road traffic at an at-grade crossing — must be explicitly authored on the shared node (type=\"rail_crossing\"); netconvert does not auto-detect it from an unset type even at a genuinely qualifying rail/road junction, and it validates the declaration against the actual edge mix, reverting to a priority junction with a warning if the mix doesn't qualify. Verified: road-vehicle stopping intervals coincide 1:1 with train-in-block intervals, with zero queue at all other times, and each gate closure imposes a real, quantifiable road delay isolated cleanly via a with/without-trains control comparison."
keywords:
  - rail_crossing
  - level-crossing
  - grade-crossing
  - netconvert-junction-type
  - rail-road-interaction
created: 2026-07-28T20:10:00
last_updated: 2026-08-04T20:00:00
sources:
  - "[[episodic-memory/2026-07-28_16-13-34/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-28_16-13-34/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[rail-simulation-and-railsignal]]"
  - "[[railroad-preemption-of-nearby-signalized-intersections]]"
related_skills:
  - build-rail-road-grade-crossing
  - build-rail-corridor-with-railsignal
related_skills_for_graph_view:
  - "[[build-rail-road-grade-crossing]]"
  - "[[build-rail-corridor-with-railsignal]]"
---

# Rail Crossing Junction Mechanics

SUMO's `rail_crossing` junction type models an at-grade level crossing — a road corridor and a rail track sharing one junction, where an approaching/passing train automatically halts road traffic, without any manually-authored `tlLogic`.

## Explicit authoring required — no auto-detection

**netconvert does not auto-detect a `rail_crossing` junction from an unset node type in hand-authored plain XML, even when the junction's actual edge mix (pure-rail edges plus non-rail road edges) would clearly qualify for one.** The shared node must explicitly declare `type="rail_crossing"`:

```xml
<node id="X" x="0" y="0" type="rail_crossing"/>
```

Leaving the type unset at an otherwise-qualifying rail/road junction compiles to an ordinary `priority` junction instead — verified directly by compiling an identical edge geometry with the node type unset and confirming the result.

## netconvert validates the declaration, doesn't blindly trust it

**Declaring `type="rail_crossing"` on a node whose actual edge mix doesn't genuinely qualify (e.g. all-road, or all-rail edges) does not produce a `rail_crossing` junction** — netconvert emits a console warning (`Converting invalid rail_crossing to priority junction '<id>'`) and silently reverts the compiled junction to `priority`. This was verified directly: an explicit `type="rail_crossing"` declaration on a node joining only road edges produced exactly this warning and reverted to `priority` in the compiled net. **Always check the compiled `.net.xml`'s actual junction `type` attribute after compilation** — a declared type in the source `.nod.xml` is not a guarantee of the compiled result.

## Verified: road/train stopping coupling is exact

On a real crossing scenario (10 scheduled trains at ~120s headway, steady bidirectional road flow), road-vehicle stopping intervals extracted independently from raw FCD output coincided 1:1 with train-in-crossing-block intervals — exactly 10 train passages, exactly 10 road-halt windows, every pair overlapping, and zero road queue at any time outside those windows. This confirms the `rail_crossing` mechanism genuinely and precisely couples train occupancy to road right-of-way, rather than approximating it.

## Verified: quantifiable, isolable delay penalty

Each gate closure in the verified test imposed roughly 70.6 seconds of aggregate road-vehicle waiting time (706 seconds total across 10 closures), cleanly isolated as attributable to the trains via an identical with-trains-vs-without-trains control run on the same road demand and seed (0 seconds of road waiting with the train schedule removed). This is a directly transferable methodology for quantifying any grade-crossing's real-world delay impact in a SUMO study.

See the `build-rail-road-grade-crossing` skill for the full network-construction, instrumentation, and verification workflow.
