---
summary: A SUMO freeway weaving segment (on-ramp merge immediately followed by an off-ramp diverge sharing one auxiliary lane) genuinely concentrates lane-change activity spatially (verified via --lanechange-output binned by position) and imposes a measurable throughput/speed penalty versus a properly-disjoint control; a valid no-weave control requires genuinely disjoint on-ramp/off-ramp lane connectivity, not merely increased ramp spacing on the same shared lane, and must be checked at a demand level that doesn't self-bottleneck its own reduced-lane-count mainline section.
keywords:
  - weaving-segment
  - lane-change-output
  - ramp-merge-diverge
  - auxiliary-lane
  - HCM-weaving
created: 2026-07-29T09:20:00
last_updated: 2026-08-06T00:30:00
sources:
  - "[[episodic-memory/2026-07-28_20-44-20/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-28_20-44-20/attempts/attempt-2/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-28_20-44-20/attempts/attempt-2/critic-agent-feedback.json]]"
related_pages:
  - "[[ramp-metering-with-alinea]]"
  - "[[macroscopic-fundamental-diagram]]"
  - "[[sumo-output-files]]"
  - "[[system-interchange-weaving-and-design-selection]]"
  - "[[lane-change-model-calibration-and-identifiability-at-a-diverge]]"
  - "[[stochastic-freeway-capacity-and-breakdown-probability]]"
related_skills:
  - model-freeway-weaving-segment
  - implement-alinea-ramp-metering
  - build-macroscopic-fundamental-diagram
  - estimate-stochastic-freeway-capacity-and-breakdown-probability
related_skills_for_graph_view:
  - "[[model-freeway-weaving-segment]]"
  - "[[implement-alinea-ramp-metering]]"
  - "[[build-macroscopic-fundamental-diagram]]"
  - "[[estimate-stochastic-freeway-capacity-and-breakdown-probability]]"
---

# Freeway Weaving Segment Turbulence

A freeway weaving segment — an on-ramp merge immediately followed by an off-ramp diverge sharing one auxiliary lane — forces entering and exiting traffic to cross paths within a confined space, a classic HCM (Highway Capacity Manual) phenomenon distinct from an isolated merge (see [[ramp-metering-with-alinea]]) or a simple lane-drop bottleneck (see [[macroscopic-fundamental-diagram]]).

## `--lanechange-output` positively confirms and spatially localizes turbulence

SUMO's `--lanechange-output` flag logs every lane-change event with position, reason, and speeds — a data source that directly answers "where is weaving turbulence actually happening?" rather than inferring it from aggregate throughput alone. Binning lane-change events by position (e.g. 50m intervals) shows a genuine weaving segment's lane changes sharply concentrated within the shared auxiliary-lane span — verified: 3.3x higher density within a weave zone than across a disjoint control's two separated merge/diverge zones.

## A valid no-weave control requires genuinely disjoint lane connectivity

**A common methodological trap: building a "no-weave control" by simply increasing the distance between the on-ramp and off-ramp gores while keeping them connected to the same shared auxiliary lane.** This does not eliminate weaving — the aux lane is still shared, just over a longer span — and does not satisfy a genuine "no weaving turbulence occurs" requirement, even though it is a legitimate secondary comparison (isolating weave-segment *length* as an independent turbulence driver, consistent with how HCM parameterizes weaving analysis). **A genuine no-weave control requires the on-ramp and off-ramp to connect to fully disjoint edges/lanes** — verify this directly from the compiled network's connection elements at the edge and lane level, not just from increased physical distance in the source XML.

## A control with fewer effective lanes can become an artificial bottleneck

If the disjoint control's mainline section has fewer lanes than the weave case's auxiliary-lane-augmented section, running both scenarios at the same total demand risks the control's mainline saturating on its own — an artificial capacity constraint confounding the weaving-vs-no-weaving comparison. **Verify the control's mainline is genuinely unsaturated at the chosen demand level with real evidence**, not an assumption: capture SUMO's `--duration-log.statistics` stdout to a file and confirm essentially all vehicles insert with negligible depart delay in the control run. If a literal disjoint control at the weave scenario's original demand level would saturate, reduce demand uniformly across both scenarios (keeping them volume-matched) until the control is confirmed unsaturated.

## Insertion/completion data must be file-traceable

A demand-metering effect — vehicles failing to insert due to upstream congestion — can be the most decisive evidence of a genuine capacity constraint, sometimes more informative than completed-vehicle throughput/speed statistics alone. Any claim about a specific number of failed insertions or elevated depart delay must be traceable to a preserved file (captured `--duration-log.statistics` output, or `--summary-output` XML) rather than asserted from memory or estimation — an unverifiable headline number undermines an otherwise rigorous comparison.

## Verified findings

On a real weaving-vs-genuinely-disjoint-control comparison at identical, control-safe demand: lane-change concentration ratio 3.3x; downstream throughput -2.6%, mean speed -6.5% in the weave case; and the weave scenario failed to insert some vehicles at its approach (elevated depart delay) while the disjoint control inserted essentially all vehicles with negligible delay — directly demonstrating the weaving segment itself, not network capacity elsewhere, as the binding constraint. A secondary, length-varied comparison (same shared-lane topology, only ramp spacing differing) at higher demand showed an even larger penalty (-10.3% throughput, -7.9% speed), consistent with weave-segment length as an additional, independent turbulence driver on top of mere lane-sharing.

See the `model-freeway-weaving-segment` skill for the full network, demand-level-selection, and verification workflow. [[system-interchange-weaving-and-design-selection]] generalizes this isolated-segment case to a closed-loop system interchange (a cloverleaf), where two adjacent quadrants' loop ramps share one mainline auxiliary lane and the weaving-driven capacity loss propagates back onto the freeway mainline itself, plus compares collector-distributor and directional-flyover mitigations.
