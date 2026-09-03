---
name: implement-nema-dual-ring-controller
description: Use this skill when the user wants to implement a NEMA dual-ring, ring-barrier, coordinated-actuated traffic signal controller in SUMO (tlLogic type="NEMA") — the industry-standard US arterial controller that combines fixed-cycle coordination (a green wave) with per-phase gap-based actuation, unlike SUMO's plain actuated or fixed-time tlLogic types. Covers the ring/barrier/coordinated-phase XML structure, minDur/maxDur/vehext actuation parameters, per-intersection offsets, a documented ambiguity in which barrier parameter designates the coordinated phases, and verifying the green wave and force-off/gap-out behavior from live simulation rather than trusting the config. Trigger on mentions of NEMA, dual-ring, ring-barrier, coordinated-actuated signal, or force-off/gap-out.
---

# Implement a NEMA Dual-Ring Controller

Configures SUMO's `tlLogic type="NEMA"` — a dual-ring, ring-barrier, coordinated-actuated signal controller, the real-world standard for US signalized arterials. This is the one controller type in SimSkill that *unifies* two capabilities every other signal skill treats separately: fixed-cycle coordination for a green wave (`optimize-signals-by-tlscoordinator`) and gap-based per-phase actuation (`control-signals-with-actuated-tls`).

## Ring-barrier structure

NEMA's standard 8-phase layout splits movements into two rings, each divided by a barrier into two phase groups. Ring/phase numbering convention (adjust compass mapping to the specific network's orientation):

| | Barrier group 1 | Barrier group 2 |
|---|---|---|
| Ring 1 | 1 (EB left) | 2 (WB through) |
|  | 3 (SB left) | 4 (NB through) |
| Ring 2 | 5 (WB left) | 6 (EB through) |
|  | 7 (NB left) | 8 (SB through) |

Phases on the same side of a barrier (e.g. 1&5, or 2&6) run concurrently; the barrier forces both rings to cross into the next group together. In a `<tlLogic type="NEMA">`, each phase is still an ordinary `<phase>` element with a `state` string, but carries NEMA-specific attributes (`minDur`, `maxDur`, `vehext`) and the ring/barrier/coordination structure is declared via `<param>` elements, not phase ordering alone:

```xml
<tlLogic id="J0" type="NEMA" programID="NEMA" offset="0">
    <param key="total-cycle-length" value="90"/>
    <param key="ring1" value="1,2,3,4"/>
    <param key="ring2" value="5,6,7,8"/>
    <param key="barrierPhases" value="4,8"/>
    <param key="barrier2Phases" value="2,6"/>
    <param key="coordinate-mode" value="true"/>
    <param key="minRecall" value="2,6"/>
    <phase duration="90" minDur="8" maxDur="38" vehext="2" yellow="3" red="2" name="2" state="rrrGGGrrrrrrrr"/>
    <!-- ...one <phase> per NEMA phase number, 8 total... -->
</tlLogic>
```

See `templates/nema_4junction_example.add.xml` for a complete, verified 4-junction working example (all 8 phases, offsets forming a green wave).

## Actuation parameters

`minDur`/`maxDur` bound a phase's green (the "split"); `vehext` (vehicle extension) is the gap-based extension increment — a phase holds green as long as a vehicle arrives within `vehext` seconds of the last one, up to `maxDur`. This is the same gap-based mechanism as plain `type="actuated"` tlLogic, applied per-phase within the ring-barrier structure rather than to a flat phase sequence.

## Coordinated phases and the barrierPhases/barrier2Phases ambiguity

**SUMO's own NEMA documentation is internally inconsistent about which parameter designates the coordinated phases** — its parameter reference table states `barrier2Phases` holds the coordinated phases (typically the arterial through movements, "usually 2,6"), but its own inline XML example sets `barrierPhases="2,6"` instead. Don't trust either in isolation; **verify empirically** which assignment actually produces coordinated behavior on the real network: run with the arterial phases in one parameter, check (via `verify_nema_coordination.py` below) whether those phases hold long and stable while the other barrier group's phases actuate normally; if the arterial phases instead run short and the cross-street group gets the long hold, swap the assignment. In one verified build, putting the arterial through phases (2,6) in `barrier2Phases` (matching the table, not the example) produced correct coordination; `barrierPhases` held the *cross-street* phases (4,8) as the non-coordinated actuated group.

`minRecall` on the coordinated phases (`value="2,6"`) ensures they're called every cycle even with no detector actuation, guaranteeing the coordinated green appears on schedule rather than being skipped if traffic happens to be light.

## Setting offsets for a green wave

Set each downstream junction's `offset` attribute to the travel time from the first junction at the target arterial progression speed: `offset = distance_from_first_junction / target_speed_m_s`, wrapped to the cycle length. This is the same offset-computation logic as `optimize-signals-by-tlscoordinator`, but applied to a controller that also actuates — meaning the offset only produces a real green wave if the coordinated phases are actually held stable across cycles, which needs separate verification (see below), not assumed from the offset values alone.

## Verifying coordination and actuation from live simulation, not the config

**A NEMA config that parses and loads is not proof it's coordinating correctly** — verify the green wave and the coordinated-vs-actuated distinction from actual simulated behavior:

```bash
python scripts/verify_nema_coordination.py \
    --net arterial.net.xml --routes routed.rou.xml --add nema.add.xml \
    --junction-order J0,J1,J2,J3 --spacing 400 --arterial-speed-ms 15 \
    --cycle 90 --coordinated-phases 2,6 --end 1200 --warmup 270 --out-dir outputs/
```

This classifies every phase's controlled links directly from network geometry (approach compass direction + turn angle → NEMA phase number — no hand-mapped link indices needed), then traces per-second green state over a run and reports:
- **(A) Coordinated-phase onset progression**: the realized lag between consecutive junctions' coordinated-phase green onset, compared against the intended offset hop — confirms the green wave is genuinely forming, not just configured.
- **(B) Per-phase green-window duration statistics**: coordinated phases should show long, stable durations near their split (held by min-recall/force-off); non-coordinated actuated phases should vary and be capped by `maxDur` (force-off) or end early on a gap (gap-out) — this distinction is the empirical signature of genuine coordinated actuation, distinguishing it from a controller that's merely fixed-time or merely actuated.

## What a well-configured NEMA controller shows against fixed-time and plain actuated

Measured on a 4-intersection arterial, identical demand across all three controllers: NEMA cut arterial through-traffic stops ~36-37% and lowered arterial corridor travel time versus both fixed-time and plain gap-based actuated control, with the green wave confirmed via realized coordinated-phase onset lags matching intended offsets within ~1 second across junctions. The cost was higher cross-street/left-turn delay than plain actuated control (the classic coordination tradeoff) — plain actuated (no coordination) gave the lowest total system delay but the most arterial stops. NEMA's benefit is specifically arterial-progression quality, not overall network efficiency; report both sides of the tradeoff, not just the arterial win.

## Gotchas

- **`barrierPhases` vs. `barrier2Phases` for coordinated-phase designation is genuinely ambiguous in SUMO's own documentation** — verify empirically on the actual network rather than trusting either the parameter table or the example.
- **A NEMA config loading without error is not proof of correct coordination** — verify green-wave onset progression and coordinated-vs-actuated phase-duration behavior from live simulation, not from the config alone.
- **`minRecall` on coordinated phases prevents them from being skipped under light demand** — omitting it can cause the coordinated phase to not appear on a light-traffic cycle, breaking the green wave intermittently.

## Related

- `optimize-signals-by-tlscoordinator` — pure offset-coordination on a fixed-time plan; this skill's coordinated phases build on the same offset-computation logic but inside an actuated controller.
- `control-signals-with-actuated-tls` — pure gap-based actuation; this skill's non-coordinated phases use the identical gap-out mechanism.
- `optimize-signals-by-tlscycleadaptation` — a natural fixed-time baseline for benchmarking a NEMA plan against.
- `run-simulation`, `analyze-simulation-outputs` — general run/comparison skills this one specializes for the three-way NEMA/fixed-time/actuated benchmark.
- [[nema-dual-ring-controller]] — the underlying ring-barrier concepts, the documentation-ambiguity gotcha, and the verified coordination-tradeoff finding.
