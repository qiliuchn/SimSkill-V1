---
summary: SUMO's tlLogic type="NEMA" implements the industry-standard US dual-ring, ring-barrier, coordinated-actuated signal controller, unifying fixed-cycle green-wave coordination with per-phase gap-based actuation; SUMO's own documentation is internally inconsistent about which barrier parameter designates the coordinated phases, requiring empirical verification.
keywords:
  - NEMA
  - dual-ring
  - ring-barrier
  - coordinated-actuated
  - force-off
  - gap-out
  - vehext
created: 2026-07-25T09:50:00
last_updated: 2026-07-25T09:50:00
sources:
  - "[[episodic-memory/2026-07-25_09-27-19/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-25_09-27-19/attempts/attempt-1/critic-agent-feedback.json]]"
  - https://sumo.dlr.de/docs/Simulation/NEMA.html
related_pages:
  - "[[actuated-traffic-signals]]"
  - "[[tlscoordinator]]"
  - "[[tlscycleadaptation]]"
  - "[[waut-time-of-day-signal-plan-switching]]"
  - "[[automated-traffic-signal-performance-measures]]"
related_skills:
  - implement-nema-dual-ring-controller
  - control-signals-with-actuated-tls
  - optimize-signals-by-tlscoordinator
  - optimize-signals-by-tlscycleadaptation
related_skills_for_graph_view:
  - "[[implement-nema-dual-ring-controller]]"
  - "[[control-signals-with-actuated-tls]]"
  - "[[optimize-signals-by-tlscoordinator]]"
  - "[[optimize-signals-by-tlscycleadaptation]]"
---

# NEMA Dual-Ring Controller

SUMO's `tlLogic type="NEMA"` implements the dual-ring, ring-barrier signal controller structure standard on real US signalized arterials — the one controller type that unifies fixed-cycle coordination (a green wave, as in [[tlscoordinator]]) with per-phase gap-based actuation (as in [[actuated-traffic-signals]]) in a single logic, rather than treating them as separate techniques.

## Ring-barrier structure

The standard 8-phase NEMA layout splits movements into two rings, each divided by a barrier into two phase groups (adjust the compass-to-phase mapping to the specific intersection's orientation):

| | Barrier group 1 | Barrier group 2 |
|---|---|---|
| Ring 1 | 1 (EB left) | 2 (WB through) |
|  | 3 (SB left) | 4 (NB through) |
| Ring 2 | 5 (WB left) | 6 (EB through) |
|  | 7 (NB left) | 8 (SB through) |

Phases on the same side of a barrier run concurrently; both rings cross to the next barrier group together. Each phase is an ordinary `<phase>` element carrying NEMA-specific `minDur`/`maxDur`/`vehext` attributes; the ring/barrier/coordination structure itself is declared via `<param>` elements (`ring1`, `ring2`, `barrierPhases`, `barrier2Phases`, `coordinate-mode`, `minRecall`) rather than phase ordering alone.

## Actuation within the ring-barrier structure

`minDur`/`maxDur` bound each phase's green ("the split"); `vehext` is the gap-based extension increment — the same mechanism `type="actuated"` uses, applied per-phase inside the ring-barrier structure rather than to a flat phase sequence. Non-coordinated phases end either by **force-off** (hitting `maxDur`, forced to end regardless of continued demand, to protect the coordinated phase's scheduled arrival) or **gap-out** (no vehicle arrives within `vehext` seconds, ending the phase early).

## The barrierPhases/barrier2Phases documentation ambiguity

**SUMO's own NEMA documentation is internally inconsistent about which parameter designates the coordinated phases**: its parameter reference table states `barrier2Phases` holds them (typically the arterial through movements, "usually 2,6"), but its own inline XML example instead sets `barrierPhases="2,6"`. This is a genuine, checkable contradiction in the shipped documentation, not a matter of interpretation. **Verify empirically on the actual network rather than trusting either source**: assign the arterial phases to one parameter, run the simulation, and check (e.g. via a live green-window duration trace) whether those phases hold long and stable while the other barrier group actuates normally. In a verified build, assigning the arterial through phases (2,6) to `barrier2Phases` (matching the table, not the example) produced correct coordination — assigning them to `barrierPhases` instead caused the *cross-street* phases to receive the long coordinated hold, starving the arterial.

`minRecall` on the coordinated phases prevents them from being skipped on a light-traffic cycle with no detector actuation — omitting it can intermittently break the green wave under light demand.

## Setting offsets

Offset computation is identical to plain coordination (`optimize-signals-by-tlscoordinator`): `offset = distance_from_reference_junction / target_arterial_speed`, wrapped to the background cycle length. The offset only produces a real green wave if the coordinated phases are genuinely held stable across cycles under live actuated demand — this needs separate empirical verification, not assumed from the offset values alone (see below).

## Verifying coordination and actuation from live simulation

A NEMA config that loads without error is not proof it's coordinating correctly. Verification needs two things, both derivable from a live TraCI trace rather than the static config:
1. **Coordinated-phase green-onset progression across junctions**, compared against the intended offset hop (`distance / target speed`) — confirms a green wave is actually forming.
2. **Per-phase green-window duration statistics** — coordinated phases should show long, stable durations near their split; non-coordinated phases should vary, capped by `maxDur` (force-off) or ending early (gap-out). This duration-pattern distinction is the empirical signature that separates a genuinely coordinated-actuated controller from one that's merely fixed-time (all phases equally stable) or merely actuated (no phase reliably held).

Both a junction's controlled-link-to-phase mapping and the green-state trace can be derived programmatically from network geometry (approach compass direction plus turn angle → phase number) rather than hand-mapped link indices, making the verification portable across different intersection layouts.

## Measured finding

On a 4-intersection arterial with identical demand across three controllers: NEMA cut arterial through-traffic stops ~36-37% and lowered arterial corridor travel time versus both a fixed-time (`tlscycleadaptation`) plan and plain gap-based actuated control, with the green wave confirmed via realized coordinated-phase onset lags matching intended offsets within about 1 second across junctions. The cost was higher cross-street/left-turn delay than plain actuated control — plain actuated (no coordination at all) gave the lowest total system delay but the most arterial stops. NEMA's benefit is specifically arterial-progression quality, not overall network efficiency — a real, expected tradeoff, not a shortcoming of the implementation.

See the `implement-nema-dual-ring-controller` skill for a complete worked 4-junction configuration template and the bundled verification script.
