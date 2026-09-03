---
name: model-freeway-weaving-segment
description: Use this skill when the user wants to model a freeway WEAVING SEGMENT in SUMO — an on-ramp merge immediately followed by an off-ramp diverge that share a single auxiliary lane, forcing entering and exiting traffic to cross paths — as opposed to an isolated merge (implement-alinea-ramp-metering) or a simple lane-drop bottleneck (build-macroscopic-fundamental-diagram). Covers hand-authoring the shared-auxiliary-lane connection topology, building a genuinely non-weaving control with DISJOINT (not just farther-apart) ramp connectivity, choosing a control demand level that avoids an artificial capacity bottleneck of its own, using SUMO's --lanechange-output event stream to positively confirm and spatially localize weaving turbulence, and quantifying the resulting throughput/speed penalty via E1 detectors. Trigger on mentions of weaving segment, weave section, ramp merge-diverge, auxiliary lane, or --lanechange-output.
---

# Model Freeway Weaving Segment

Models a freeway weaving segment — an on-ramp merge immediately followed by an off-ramp diverge sharing one auxiliary lane, forcing merging and diverging traffic to cross paths — and quantifies the turbulence penalty against a genuine no-weave control.

## Network: shared vs. genuinely disjoint auxiliary-lane topology

**The weave case**: an auxiliary (4th) lane fed by the on-ramp at one end and draining to the off-ramp at the other, with the mainline through-lanes merging back in between:

```xml
<connection from="ml_in"  to="weave"   fromLane="0" toLane="1"/>
<connection from="ml_in"  to="weave"   fromLane="1" toLane="2"/>
<connection from="ml_in"  to="weave"   fromLane="2" toLane="3"/>
<connection from="onramp" to="weave"   fromLane="0" toLane="0"/>
<connection from="weave"  to="ml_out"  fromLane="1" toLane="0"/>
<connection from="weave"  to="ml_out"  fromLane="2" toLane="1"/>
<connection from="weave"  to="ml_out"  fromLane="3" toLane="2"/>
<connection from="weave"  to="offramp" fromLane="0" toLane="0"/>
```

**The control must be genuinely disjoint, not just farther apart.** A common mistake: building a "control" that keeps the same shared auxiliary-lane edge but simply lengthens the distance between the two ramp gores. This is a legitimate *secondary* comparison (isolating weave-segment length as HCM defines it), but it does NOT satisfy a "no weaving turbulence occurs" requirement — the aux lane is still shared. A genuine no-weave control needs the on-ramp and off-ramp connecting to **fully disjoint edges/lanes** with an ordinary, unshared mainline section between them:

```xml
<!-- control: on-ramp merges into its own segment, ramps far apart, no shared lane -->
<connection from="onramp"  to="merge"    fromLane="0" toLane="0"/>
<connection from="merge"   to="mid"      .../>   <!-- plain 3-lane mainline -->
<connection from="mid"     to="diverge"  .../>
<connection from="diverge" to="offramp"  fromLane="0" toLane="0"/>
```

Verify from the compiled `.net.xml` that the weave case's on-ramp-fed edge and off-ramp-drained edge are the same, and the control's are genuinely different — see `scripts/analyze_primary.py`'s Finding-1 logic, which checks this at both the edge and lane level.

## Choosing a control demand level that doesn't self-bottleneck

**If the control's plain mainline section is fewer lanes than the weave case's auxiliary-lane-augmented section, running both at the same total demand can make the control's own mainline saturate — an artificial bottleneck unrelated to weaving turbulence, which would confound the comparison.** Verify the control's mainline section is genuinely unsaturated at your chosen demand (compute veh/h/lane against a reasonable single-lane capacity, ~1800-2000 veh/h/lane) — and back this up with real evidence, not just a chosen number: capture SUMO's `--duration-log.statistics` stdout to a file and confirm essentially all vehicles insert with negligible depart delay in the control scenario. If the control does still show elevated depart delay or unfulfilled insertions, that's a sign the demand level needs reducing (uniformly across both scenarios, to keep the comparison volume-matched) before the comparison is valid.

## Detecting and localizing turbulence: `--lanechange-output`

Enable `--lanechange-output` on both scenarios — it logs every lane-change event with position (`x`), reason, and speeds. Bin lane-change events by 50m position intervals and compare: the weave case should show a sharp concentration within the shared auxiliary-lane span, while the disjoint control's lane-change activity should split into two separate, spatially distant zones (one at the merge, one at the diverge) rather than a single concentrated band. See `scripts/analyze_primary.py` for the binning and concentration-ratio computation.

## Quantifying the penalty and verifying insertion data honestly

Compare downstream E1 throughput (veh/h) and space-mean speed (harmonic mean, weighted by vehicle count) between scenarios. **Also check insertion/completion data, not just completed-vehicle statistics** — a demand-metering effect (vehicles failing to insert due to upstream congestion) can be the most decisive signal of a real capacity constraint, and is often more informative than the completed-vehicle throughput/speed numbers alone. Always make insertion/completion claims file-derivable: capture `--duration-log.statistics` stdout to a preserved log file (or use `--summary-output`) rather than asserting a specific failed-insertion count from memory or estimation — a claim that can't be traced to a specific file and line is not verifiable and shouldn't be presented as a raw-data finding.

## Verified findings

On a real weaving-vs-disjoint-control comparison at identical, control-safe demand: lane changes concentrated 3.3x more densely within the weave zone than across the control's two separated zones; downstream throughput fell 2.6% and mean speed fell 6.5% in the weave case; and the weave scenario failed to insert some vehicles at its approach (elevated depart delay) while the control inserted essentially all vehicles with negligible delay — directly demonstrating the weaving segment, not network capacity elsewhere, as the binding constraint. A secondary, length-varied comparison at higher demand showed an even larger penalty, consistent with HCM's treatment of weave-segment length as an additional, independent turbulence driver.

## Gotchas

- **A "no-weave control" built by merely increasing ramp spacing while keeping the shared aux-lane topology does not satisfy a genuine no-weaving-possible requirement** — verify disjoint edge/lane connectivity directly from the compiled net, not just increased distance.
- **A control with fewer effective lanes than the weave case can become its own artificial bottleneck at the same demand** — verify (with a captured stats log, not an assumption) that the control's mainline is genuinely unsaturated before trusting a throughput/speed comparison.
- **Insertion/completion claims must be file-traceable** — capture `--duration-log.statistics` stdout or `--summary-output`, don't assert a specific failed-insertion count without a preserved artifact backing it.
- **`--lanechange-output` events are logged by position (`x`), not by edge alone** in some geometries — bin by absolute position for a genuinely spatial concentration analysis rather than relying on edge identity alone, especially when comparing across scenarios with different edge lengths/layouts.

## Related

- `implement-alinea-ramp-metering` — the hand-authored motorway/ramp plain-XML pattern this skill's network construction reuses.
- `build-macroscopic-fundamental-diagram` — E1 detector definition/interpretation as a standalone measurement instrument.
- `analyze-simulation-outputs` — general tripinfo/detector comparison methodology.
- [[freeway-weaving-segment-turbulence]] — the underlying weaving-turbulence mechanics, the verified lane-change concentration and throughput/speed findings, and the verified no-weave-control-must-be-disjoint methodological lesson.
- `model-managed-lanes-with-dynamic-tolling-and-self-selection` — reuses this skill's `--lanechange-output` spatial-concentration technique to test whether gated (vs. continuous) managed-lane access localizes weaving, and found the localization effect was clean and significant while the corresponding performance/safety benefit was not — a genuine dissociation between the two.
