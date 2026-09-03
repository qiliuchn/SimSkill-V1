---
name: build-rail-road-grade-crossing
description: Use this skill when the user wants to model an at-grade rail-road level crossing in SUMO — a shared junction where a road corridor crosses a rail track, and passing trains halt road traffic via SUMO's native rail_crossing junction mechanism (not a manually-authored traffic light). Covers the critical netconvert requirement that a rail_crossing junction must be explicitly authored (auto-detection does not fire for hand-authored plain XML), reusing the bidirectional rail-track construction pattern from build-rail-corridor-with-railsignal, instrumenting the road approach to verify train/road stopping coupling, and isolating the grade-crossing delay penalty via a with/without-trains control comparison. Trigger on mentions of rail crossing, level crossing, grade crossing, rail_crossing junction, or train gate/barrier delay.
---

# Build Rail-Road Grade Crossing

Models a SUMO at-grade rail-road level crossing — a road corridor and a rail track sharing one junction, where a passing train automatically halts road traffic via SUMO's native `rail_crossing` junction type, not a manually-authored `tlLogic`.

## Critical finding: `rail_crossing` must be explicitly authored, not auto-detected

**netconvert does NOT auto-detect a `rail_crossing` junction from an unset node type in hand-authored plain XML, even when the edge mix (pure-rail plus non-rail road edges) at that junction would otherwise clearly qualify.** The shared node must be explicitly declared `type="rail_crossing"` in the `.nod.xml`:

```xml
<node id="X" x="0" y="0" type="rail_crossing"/>
```

**netconvert then validates this declaration rather than blindly trusting it** — it keeps the type only if the node genuinely joins pure-rail edges (`allow="rail"`) and non-rail road edges (`allow="passenger"` or similar); on a node whose actual edge mix doesn't qualify (e.g. all-road, or all-rail), it emits a warning (`Converting invalid rail_crossing to priority junction '<id>'`) and silently reverts the junction to a standard `priority` type. Verify the compiled `.net.xml` directly for the junction's actual `type` attribute after every compile — don't assume the declaration took effect.

## Network construction

Reuse `build-rail-corridor-with-railsignal`'s verified bidirectional rail-track pattern directly for the rail side: single-lane `vClass="rail"` edges with `spreadType="center"` so the opposite-direction pair overlays exactly (verify `bidi=` attributes appear on the compiled rail edges as confirmation). Cross a normal two-way road corridor (`allow="passenger"`, ordinary priority endpoint nodes) through the same shared node as the rail track — see `scripts/example_cross.nod.xml`/`example_cross.edg.xml` for a minimal working 4-arm crossing (road N↔S, rail W↔E, sharing junction X).

```bash
netconvert -n cross.nod.xml -e cross.edg.xml -o cross.net.xml
grep -A2 'junction id="X"' cross.net.xml   # confirm type="rail_crossing", no tlLogic
```

## Demand and instrumentation

Schedule trains at a fixed headway (a `<flow>` or repeated `<vehicle>` entries on the rail route) and a steady road flow across the crossing, identical demand across any comparison scenarios. Instrument the road approach (E2 detector and/or FCD output) to record vehicle speed/queue over time, and record train positions (FCD, or the train route's known schedule) to determine exactly when each train occupies the crossing block.

## Verifying the coupling: don't just assert it

Extract train-in-crossing-block time windows and road-vehicle-halted time windows independently from raw output, then confirm every road-halt window coincides with a train-in-block window and that the road queue is zero at all other times — a strict, countable 1:1 correspondence (verified: 10 train passages, 10 road-halt windows, all 10 coinciding, zero queue elsewhere in a real test). See `scripts/analyze.py` for the extraction and comparison logic (adapt the lane IDs, crossing coordinate, and block-detection window to your own network's geometry).

## Isolating the delay penalty: with-trains vs. without-trains control

Run the identical road demand and seed with the train schedule present and with it removed entirely (empty rail route/flow) — the difference in total/mean road waiting time is the genuine grade-crossing-induced delay, cleanly isolated from any other confound. Compute per-closure delay (total delay ÷ number of gate closures) as a normalized figure that doesn't depend on the specific number of trains scheduled.

## Gotchas

- **`rail_crossing` requires explicit node-type authoring** — it is not auto-detected from an unset type, even at a genuinely qualifying rail/road junction.
- **netconvert validates the junction type against the actual edge mix** — an explicit `type="rail_crossing"` declaration on a node that doesn't genuinely mix rail and non-rail edges silently reverts to `priority` with only a console warning; check for this warning and the compiled net's actual junction type.
- **Reuse the rail-track construction pattern verbatim** from `build-rail-corridor-with-railsignal` — the crossing mechanism is the only genuinely new part of this scenario.
- **Verify the temporal coupling by extraction and counting, not eyeballing a plot** — confirm every stop window has a matching train window and there's no unexplained queue activity.

## Related

- `build-rail-corridor-with-railsignal` — the bidirectional rail-track and train-vType construction pattern this skill's rail side reuses directly.
- `create-single-intersection` — general single-junction network authoring background (not directly applicable to the crossing-specific junction type, but useful context).
- [[rail-crossing-junction-mechanics]] — the underlying `rail_crossing` netconvert mechanics and the verified train/road coupling and delay findings.
