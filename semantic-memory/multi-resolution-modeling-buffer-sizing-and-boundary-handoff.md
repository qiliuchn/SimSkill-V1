---
summary: In SUMO Multi-Resolution Modeling (a coarse regional model handing boundary demand to a fine study-area cut), GEH-on-volumes does not discriminate buffer adequacy under fixed-route demand — delay RMSE and VHT-proxy bias do — a micro-resolution parent needs no buffer at all while a mesoscopic parent needs 2-3 blocks depending on congestion, a macroscopic (marouter) parent's own capacity reference can be off by >30x versus true measured micro capacity, and a coarser parent's un-metered boundary crossings cause a genuine "over-injection trap" under congestion that buffer size alone cannot fix — only a calibrator-based congestion-aware boundary injection can (verified ~50% entry-delay reduction, +6.7% completions).
keywords:
  - multi-resolution-modeling
  - MRM
  - subarea-buffer-sizing
  - boundary-handoff
  - over-injection-trap
  - resolution-transfer
  - marouter-capacity-mismatch
created: 2026-08-06T21:24:14
last_updated: 2026-08-06T21:24:14
sources:
  - "[[episodic-memory/2026-08-06_21-20-06/attempts/attempt-1/action-agent-output.md]]"
  - "[[episodic-memory/2026-08-06_21-20-06/attempts/attempt-1/critic-agent-feedback.md]]"
related_pages:
  - "[[cutroutes-and-subnetwork-extraction]]"
  - "[[mesoscopic-simulation]]"
  - "[[marouter-macroscopic-assignment]]"
  - "[[sumo-calibrator]]"
  - "[[teleport-artifacts-and-gridlock-resolution-validity]]"
  - "[[geh-statistic]]"
  - "[[sumo-stochastic-variability-and-replication-design]]"
related_skills:
  - extract-subnetwork-scenario-with-boundary-demand
  - run-mesoscopic-simulation
  - assign-traffic-with-marouter
  - calibrate-flow-with-in-simulation-calibrator
  - quantify-sumo-run-to-run-variability
  - validate-congested-scenario-results-against-teleport-artifacts
related_skills_for_graph_view:
  - "[[extract-subnetwork-scenario-with-boundary-demand]]"
  - "[[run-mesoscopic-simulation]]"
  - "[[assign-traffic-with-marouter]]"
  - "[[calibrate-flow-with-in-simulation-calibrator]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[validate-congested-scenario-results-against-teleport-artifacts]]"
---

# Multi-Resolution Modeling: Buffer Sizing and Boundary Handoff

Multi-Resolution Modeling (MRM) — a coarse regional model (macroscopic or mesoscopic) handing boundary demand to a fine microscopic study-area model — is the standard large-agency workflow for scoping a detailed intersection/corridor study without microsimulating an entire region. `[[cutroutes-and-subnetwork-extraction]]` and `extract-subnetwork-scenario-with-boundary-demand` already establish the cutting mechanics and a same-resolution (micro parent → micro child) fidelity protocol; this page holds what changes when the parent is a **different, coarser** resolution — the actual MRM case — verified on a 64-junction regional grid with a nested 2x2 study area, buffer rings at 0/1/2/3 blocks, and two demand levels (undersaturated v/c≈0.6, oversaturated v/c≈1.0-1.1 with verified spillback across the study-area boundary).

## GEH does not discriminate buffer adequacy here — delay and VHT bias do

Under fixed-route demand (no in-simulation rerouting), `cutRoutes.py` preserves each vehicle's exact edge sequence regardless of buffer size, so **GEH-on-volumes sits flat at or near the micro replication noise floor at every buffer, for either parent resolution**. A buffer-sizing study that only checks GEH will conclude buffer doesn't matter — wrongly. **Delay RMSE and VHT-proxy bias are the metrics that actually respond to buffer size and parent resolution**, and are what should drive the buffer decision.

## Minimum buffer depends on parent resolution and congestion

Verified findings, both demand levels:

- **A micro-resolution parent needs no buffer at all** — a buffer=0 cut (study area only, no ring) was already statistically indistinguishable from the full-region micro reference on delay RMSE and VHT-proxy bias, at both undersaturated and oversaturated demand.
- **A mesoscopic parent needs a real buffer, and the needed size grows with congestion** — delay RMSE from a meso parent fell 2.36s (buffer=0) → 1.25s (buffer=1) → 0.67s (buffer=2) → 0.61s (buffer=3) at moderate demand, with VHT-proxy bias closing from +7.0% to within the micro-parent's own ±1-2% band by buffer=2. At oversaturated demand the convergence was noisier and did not clearly close within the tested range (buffer=3, near the full region, remained the best-but-imperfect configuration).
- **A macroscopic (`marouter`) parent carries a distinct risk that buffer size cannot fix at all: its own capacity reference can be badly wrong.** `marouter`'s `flowCapacityRatio`-based capacity converged on a per-edge value **more than 30x lower** than the true capacity measured directly in microsimulation on identical geometry (~20 veh/h implied vs. ~750-800 veh/h/edge actually sustained) — a substantially larger mismatch than the case previously documented in `[[marouter-macroscopic-assignment]]`. Never trust `marouter`'s own capacity/saturation reference to decide whether a scenario is under- or oversaturated for an MRM handoff; measure capacity directly (a micro flow-vs-demand sweep, or the "peak of the curve" method in `[[sumo-stochastic-variability-and-replication-design]]`) first.

The general pattern: **the coarser the parent and the more congested the boundary, the larger the buffer needs to be** — budget well beyond the ~300-500 m / 3-5 blocks that suffices for a same-resolution parent handoff.

## The over-injection trap: buffer alone cannot fix a mis-metered boundary rate

This is the sharp, quantified edge of a general MRM hazard: a coarser parent's reported boundary crossings reflect *its own*, typically under-congested, model of the boundary — not the metering a real (or a same-resolution) signal-and-queue-constrained boundary would actually impose. A mesoscopic model in particular underestimates control/queuing delay (see `[[mesoscopic-simulation]]`), so its boundary "throughput" is closer to demand than to true discharge. Handed to a micro child as literal insertion volume, this over-injects.

Verified: at oversaturated demand, a meso-parent cut showed **4-5x higher mean insertion (departure) delay than an equivalent micro-parent cut at every buffer tested** (e.g. ≈55s vs. ≈23s at buffer=2), with 2-4x more vehicles delayed >1s at insertion — **and this gap did not close by buffer=3**, i.e. by nearly the full region. This is the key methodological finding: **buffer size fixes the spatial extent of a coarse parent's missing detail; it does not fix the parent's boundary rate being wrong, and growing the buffer mostly relocates where the mismatch surfaces rather than removing it.**

## The fix: calibrator-based congestion-aware boundary injection

Don't hand a coarse parent's raw boundary crossings to the child as literal insertion demand. Load a `<calibrator>` (see `[[sumo-calibrator]]`, `calibrate-flow-with-in-simulation-calibrator`) on each injection edge, targeting the true congestion-aware boundary rate (measured from even a brief micro reference, or the best available metered estimate) rather than the coarse parent's uncongested crossing count.

Verified result on one oversaturated meso-parent cut (`calstats` confirmed genuine live enforcement, realized flow tracking aspired flow to within ~15%, capped by the real downstream bottleneck): mean entry delay fell **0.27-0.31s → 0.14-0.15s (~50%)**, and completed trips over the same simulation window **rose 6.7%** — smoothing the injection burst relieved a self-inflicted queue that had been throttling downstream throughput generally, not only right at the boundary. Honest tradeoff disclosed: calibrator-inserted shortfall vehicles need a representative continuation route per injection edge rather than each original vehicle's true destination, trading a small amount of route-diversity fidelity for correct boundary metering.

## Decision guidance by question type

- **Regional route choice / corridor diversion** (e.g. does traffic prefer this arterial or a bypass): a mesoscopic full-region model is adequate at roughly an order of magnitude less wall-clock than microsimulation — volumes/route shares tracked the micro reference almost exactly under fixed-route demand. `marouter` must not be used for this without first validating its capacity reference against at least one micro/meso run.
- **Corridor throughput / VKT-scale questions**: mesoscopic (with junction control) is adequate, with a small, roughly-constant VKT undercount (a few percent, from skipping internal junction detail) correctable by a fixed offset. `marouter` is unusable beyond a rough order-of-magnitude estimate given the capacity-mismatch risk above.
- **Intersection LOS / queue design / signal timing / spillback**: only a microsimulated child qualifies — mesoscopic control-delay underestimation is worst under exactly the oversaturated conditions these questions target, disqualifying it outright. Within microsimulated children: a micro-resolution parent cut is safe with no buffer at all; a meso-resolution parent cut needs a real buffer (2 blocks moderate demand, up to the full region if oversaturated) **and** still needs the calibrator-based boundary fix above, since buffer alone leaves a residual over-injection artifact even at large buffer.
