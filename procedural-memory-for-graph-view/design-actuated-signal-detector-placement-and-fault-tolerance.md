---
name: design-actuated-signal-detector-placement-and-fault-tolerance
description: Use this skill when the user wants to treat detector placement (setback distance, gap tolerance) as a design variable for SUMO actuated traffic-signal control, needs to bind CUSTOM detectors to an actuated tlLogic instead of relying on SUMO's auto-generated ones, or wants to study what happens when an actuated intersection's detectors fail (stuck-off, stuck-on, partial). Covers the exact SUMO syntax for custom detector-to-tlLogic binding (undocumented in prior memory), a manipulation-plus-negative-control protocol for proving any SUMO config flag actually takes effect, instrumenting the two distinct detector-placement failure mechanisms (premature gap-out vs. blind-zone green-cuts), physically modeling a stuck-on detector fault, and a censoring-robust delay metric that corrects for survivorship bias in fault analysis. Trigger on mentions of detector placement, detector setback, custom detector binding, actuated signal detector fault, stuck detector, or blind-zone green-cut.
related_skills:
  - control-signals-with-actuated-tls
  - measure-saturation-flow-and-validate-webster-method
  - validate-congested-scenario-results-against-teleport-artifacts
  - quantify-sumo-run-to-run-variability
  - measure-roundabout-capacity-and-implement-metering
  - emulate-and-evaluate-partial-sensor-traffic-state-estimation
related_skills_for_graph_view:
  - "[[control-signals-with-actuated-tls]]"
  - "[[measure-saturation-flow-and-validate-webster-method]]"
  - "[[validate-congested-scenario-results-against-teleport-artifacts]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[measure-roundabout-capacity-and-implement-metering]]"
  - "[[emulate-and-evaluate-partial-sensor-traffic-state-estimation]]"
related_pages:
  - "[[actuated-signal-detector-design-and-fault-tolerance]]"
---

# Design Actuated Signal Detector Placement and Fault Tolerance

Treats detection — where a loop detector sits, how much gap tolerance it has, and what happens when it fails — as a first-class design variable for SUMO's built-in actuated signal control, extending `control-signals-with-actuated-tls` beyond its assumption of always-working, auto-generated detection.

## Binding custom detectors to an actuated tlLogic

SUMO auto-generates E1 detectors for `type="actuated"` junctions by default (see `control-signals-with-actuated-tls`), placed at `detector-gap × speed` meters upstream. To override this with hand-declared detectors at custom positions:

```xml
<!-- additional file: define the E1 detector as usual -->
<inductionLoop id="det_EC_0" lane="EC_0" pos="-40" friendlyPos="true" period="1" file="dummy.xml"/>
```

```xml
<!-- on the tlLogic element itself -->
<tlLogic id="center" type="actuated" ...>
    <param key="EC_0" value="det_EC_0"/>   <!-- key is the LANE ID, not "detector:<laneID>" -->
    <param key="EW_0" value="NO_DETECTOR"/> <!-- disables actuation for this lane -->
    ...
</tlLogic>
```

**The `<param>` key is the lane ID itself** — not `detector:<laneID>` or any prefixed form (verify against current SUMO documentation before assuming, since this project has direct precedent of assuming a plausible-sounding syntax that turned out wrong). A special value `NO_DETECTOR` disables actuation-driven extension for that lane entirely (the phase falls back to `minDur`). **Only E1 (`inductionLoop`) detectors are accepted** — attempting to bind an E2 `laneAreaDetector` this way is a hard SUMO error, not a silent failure.

## Never trust a config flag works without proving it — the manipulation-plus-negative-control protocol

**This project has a documented precedent of a plausible-sounding SUMO config flag (`--tls.default-type` on an already-compiled network) silently doing nothing.** Apply the same skepticism to any newly-discovered binding syntax: don't just confirm the absence of an error — prove the mechanism is genuinely wired in with a **manipulation that must change behavior if it's real**, alongside a **negative control that must NOT change behavior**.

Verified protocol: build several variants of an identical scenario (same network, routes, seed), varying only the detector-binding configuration, and compare phase-transition traces (hashed, e.g. SHA1, for an unambiguous match/no-match signal):
1. **Baseline** — normal custom detector binding.
2. **Manipulation that should change behavior** — move the bound detector to an implausible position (e.g. far upstream): the trace **must** differ from baseline if the binding is real.
3. **`NO_DETECTOR`** — should pin the phase at exactly `minDur`, with SUMO logging a "no controlling detector" warning.
4. **An invalid detector ID** — should produce a hard SUMO error, not silent acceptance.
5. **Negative control: an unrecognized `<param>` key** (not a real lane ID) — the trace **must be byte-identical** to baseline, proving SUMO silently ignores keys it doesn't recognize (which is exactly the failure mode that makes steps 2-4 necessary to check in the first place — if unrecognized keys were rejected loudly, a typo would be obvious; since they're silently ignored, a real functional test is the only way to know the binding actually worked).

This five-step chain (behavior-changing manipulation + boundary conditions + negative control) is the right level of rigor for verifying *any* newly-discovered or assumed-but-unverified SUMO configuration mechanism, not just detector binding specifically.

## Two distinct detector-placement failure mechanisms, wildly asymmetric in cost

1. **Detector too close to the stop line** ("premature gap-out" / "unseen imminent" vehicles): a vehicle is still approaching (not yet past the detector) when the max-gap timer expires, so the phase ends just before that vehicle would have been detected. Cost: small, typically a few seconds per affected vehicle.
2. **Detector too far from the stop line** ("blind zone" green-cuts): vehicles exist between the detector and the stop line — already committed to the approach, potentially queued — that the controller cannot see at all, because they're downstream of where detection happens. The controller ends the phase (having seen no recent detector activity) while a real queue is still discharging. Cost: **verified to be roughly two orders of magnitude larger** than the too-close failure mode (hundreds of seconds per vehicle vs. single digits), including genuine capacity collapse at severe setbacks.

**Instrument both directly from live controller/vehicle state**, not indirectly: count vehicles within a short time-to-stop-line window that haven't yet crossed the detector (mechanism 1), and separately count vehicles (and specifically queued/stopped vehicles) between the detector and the stop line at the moment each green phase ends (mechanism 2). **Confirm the blind-zone mechanism causally, not just correlationally**: raising `minDur` at a problematic setback should directly and dramatically reduce both the blind-zone green-cut fraction and the resulting delay, if the mechanism is genuinely what's identified — verified case: increasing minDur from 7s to 15s at a severe setback cut delay by 6x and the blind-zone-cut fraction by 30x.

## Verified null result: SUMO's default detector-gap placement may already be well-chosen

**Don't assume hand-tuning beats a sensible default without checking.** A dedicated 30-cell hand-tuning sweep (varying setback and max-gap across multiple approach speeds and demand levels) found NO statistically significant improvement over SUMO's own default detector placement formula (`detector-gap × speed`) at any tested demand level — every improvement was within noise of zero. **The "optimum" was a broad plateau, not a sharp point worth expensive tuning effort to find.** Report a genuine null result plainly when hand-tuning doesn't beat a sensible default, rather than reporting whichever cell happened to score marginally best as if it were a real improvement.

## Modeling a stuck-on detector fault physically, not as a software flag

**Don't simulate a "stuck-on" detector fault by simply forcing a boolean flag in the controller logic** — model it physically instead: place a real detector on an isolated dummy edge with a permanently parked vehicle sitting on it, so the detector genuinely, continuously reports a vehicle present (verify via `getTimeSinceDetection()` returning 0 at every sampled timestep). This is more faithful to what a real stuck-on failure looks like (a physical sensor malfunction, not a logical override) and produces the correct downstream behavior automatically through SUMO's own actuated-control logic, rather than requiring a separate hand-coded override path that might not match real SUMO behavior.

**Verified finding: a stuck-on fault shows no gradation between a partial (one-lane) and full (all-lanes) failure** — the two produce essentially identical delay and byte-identical phase-transition traces, because SUMO extends a phase if **any** of its controlling detectors calls (a logical OR across detectors, not an average or majority vote). A single stuck-on detector is as bad as every detector on that movement being stuck-on.

## Correcting fault analysis for survivorship censoring

**A naive tripinfo-based delay metric can make a severe fault look artificially GOOD**, for the same reason established in `validate-congested-scenario-results-against-teleport-artifacts`: `tripinfo` only records vehicles that actually complete their trip, and a severe fault (e.g. a stuck-off detector starving an approach) can prevent many vehicles from ever being inserted into the network at all — those vehicles' catastrophic experience never enters the average. **Compute a censoring-robust delay metric instead**: track every vehicle that was *scheduled* to depart (not just those that actually completed), and charge an appropriate penalty (e.g. remaining simulation time, or a fixed large penalty) to any vehicle that never got inserted. Verified case: a naive tripinfo-based mean delay of ~122s for a stuck-off fault at high demand (which looked *better* than the healthy baseline's ~171s) became ~1202s under the censoring-robust metric once the ~52% of vehicles that never got inserted were properly counted — a roughly 10x correction that **inverted** the naive conclusion from "this fault seems harmless" to "this fault is catastrophic."

## Gotchas

- **A `<param>` key you assume is correct (e.g. a prefixed `detector:<laneID>` form) may not match the actual SUMO syntax** — verify against current documentation and, more importantly, against genuine behavioral proof (the manipulation-plus-negative-control protocol above), not just the absence of an error.
- **An unrecognized `<param>` key is silently ignored by SUMO, not rejected** — a typo in a detector-binding key will not error, it will simply leave that lane on default (auto-generated) detection, silently invalidating any comparison that assumed the custom binding took effect.
- **Only E1 detectors can be bound this way** — an E2 laneAreaDetector produces a hard error, not a silent acceptance.
- **The two detector-placement failure modes are wildly asymmetric in cost** — a too-close detector is a minor inconvenience; a too-far detector can cause real capacity collapse. Don't treat "closer is always safer" or "farther is always safer" as a rule of thumb; both directions have a real failure mode, but they are not equally severe.
- **A naive tripinfo-based delay metric can make a severe capacity-starving fault look artificially GOOD** via survivorship censoring of never-inserted vehicles — always compute a censoring-robust metric for any fault-injection or gridlock-adjacent study.
- **A stuck-on detector fault shows no partial gradation** — one stuck-on detector on a movement is as bad as all of them, because SUMO's actuated logic ORs across a phase's controlling detectors.

## Related

- `control-signals-with-actuated-tls` — the base actuated-signal skill this one extends from SUMO's auto-generated-detector default to custom detector binding, placement, and fault tolerance.
- `measure-saturation-flow-and-validate-webster-method` — the measured (not assumed) saturation-flow methodology used to build this skill's Webster fixed-time reference baseline.
- `validate-congested-scenario-results-against-teleport-artifacts` — the survivorship-censoring discipline this skill's censoring-robust delay metric directly extends from teleport-based gridlock resolution to insertion-backlog censoring.
- `quantify-sumo-run-to-run-variability` — the replication/CI methodology this skill's detector-placement and fault sweeps apply.
- [[actuated-signal-detector-design-and-fault-tolerance]] — the verified failure-mechanism asymmetry, the default-detector-gap null result, the survivorship-censoring correction, the stuck-on no-gradation finding, and the fail-safe maxDur recommendation.
- `measure-roundabout-capacity-and-implement-metering` — a case where this skill's own-approach `<param>`-based detector binding is insufficient (roundabout metering needs a detector on one approach controlling a signal on a different approach) and a TraCI controller is required instead.
- `emulate-and-evaluate-partial-sensor-traffic-state-estimation` — extends this skill's detector-too-far blind-zone finding from an actuation-control context to a state-estimation context, and adds a further sub-vehicle-length occupancy-periodicity artifact discovered while diagnosing setback sensitivity.
