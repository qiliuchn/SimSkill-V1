---
summary: A verified, honestly-negative SUMO result for closed-loop coordinated adaptive signal control (the SCATS/SCOOT class) — the adaptive controller did not beat well-tuned fixed-time coordination and its disadvantage widened, not narrowed, under unpredictable demand, traced to detector-based degree-of-saturation estimates that grow systematically more biased (not noisier) as true saturation rises because queue spillback delays vehicles past the advance loop; the update-interval design curve showed no interior optimum (adapting every cycle was best), ruling out transition churn as the cause; coordinated-actuated control outperformed the adaptive controller outright at far lower complexity; and a cycle-cap failsafe against oversaturation runaway delivered only a modest, not dramatic, recovery.
keywords:
  - adaptive-signal-control
  - SCATS
  - SCOOT
  - degree-of-saturation-estimation
  - detector-bias
  - signal-transition-cost
  - coordinated-adaptive-control
created: 2026-08-07T01:30:23
last_updated: 2026-08-07T01:30:23
sources:
  - "[[episodic-memory/2026-08-07_01-26-11/attempts/attempt-1/action-agent-output.md]]"
  - "[[episodic-memory/2026-08-07_01-26-11/attempts/attempt-1/critic-agent-feedback.md]]"
related_pages:
  - "[[max-pressure-signal-control]]"
  - "[[waut-time-of-day-signal-plan-switching]]"
  - "[[automated-traffic-signal-performance-measures]]"
  - "[[webster-method]]"
  - "[[arterial-signal-progression-resonance-bandwidth-and-delay]]"
related_skills:
  - implement-scats-style-coordinated-adaptive-signal-control
  - implement-maxpressure-traci-controller
  - switch-signal-plans-by-time-of-day-with-waut
  - build-atspm-pipeline-and-retime-arterial
  - measure-saturation-flow-and-validate-webster-method
  - control-signals-with-actuated-tls
related_skills_for_graph_view:
  - "[[implement-scats-style-coordinated-adaptive-signal-control]]"
  - "[[implement-maxpressure-traci-controller]]"
  - "[[switch-signal-plans-by-time-of-day-with-waut]]"
  - "[[build-atspm-pipeline-and-retime-arterial]]"
  - "[[measure-saturation-flow-and-validate-webster-method]]"
  - "[[control-signals-with-actuated-tls]]"
---

# Coordinated Adaptive Signal Control: Detector Bias and Transition Cost

Closed-loop, cycle-based coordinated adaptive signal control (the SCATS/SCOOT/InSync class) had no coverage in memory — every existing adaptive controller either abandons a common cycle entirely (`[[max-pressure-signal-control]]`) or adapts only locally within a fixed background plan (`control-signals-with-actuated-tls`). This page holds the verified findings from the first build of this controller class, obtained on a 5-signal ~2 km arterial under stationary, reversing, surge, and incident-diversion demand regimes, compared against fixed-time, time-of-day switching, actuated, coordinated-actuated, and max-pressure arms. See `implement-scats-style-coordinated-adaptive-signal-control` for the full controller architecture and methodology.

## Headline: adaptive did not beat fixed-time, and the disadvantage widened under uncertainty

Under stationary, well-forecast demand, the adaptive controller was statistically indistinguishable from a well-tuned fixed-time coordinated plan (not significantly different, in either direction). Under a mix of directional reversal, an unannounced surge, and an incident-induced diversion, the adaptive controller's disadvantage relative to fixed-time **widened rather than narrowed** — the opposite of the intuitive expectation that adaptive control should earn its value precisely when demand becomes less predictable. Coordinated-actuated control (actuated splits inside a fixed background cycle and offset — far simpler than a full 3-layer adaptive system) outright **beat** the adaptive controller in both regimes. This is a genuine, measured negative result for one specific implementation, not a claim that the whole controller class is unworkable — but it is strong evidence that "adaptive" does not automatically mean "better," and that where the benefit fails to appear is itself informative (see below).

## Root cause, isolated: detector-based degree-of-saturation bias, not transition churn

Two follow-up studies were run specifically to find *why* the adaptive controller underperformed, and they point at the same mechanism from two directions:

**Degree-of-saturation estimation grows systematically more biased — not just noisier — as true saturation rises.** Validated against a closed-form ground-truth demand rate (the exact generating rate, not another simulated quantity) across 820 observations: estimation bias was small below moderate saturation (dominated by Poisson counting variance, not bias) but grew **monotonically more negative** as true degree of saturation approached and exceeded 1.0 — reaching roughly −0.73 (a severe under-estimate) at the highest tested saturation. The mechanism: queue spillback increasingly delays vehicles' arrival at the advance detector past the cycle boundary they should have been counted in, so the detector under-reports exactly the condition (near/over capacity) that most needs an accurate signal. **A controller whose cycle-length-adaptation layer trusts this estimate will systematically under-react precisely when the corridor most needs it to react** — a structural, not incidental, limitation of loop-detector-based degree-of-saturation estimation for this control application.

A secondary, counter-intuitive finding on detector placement: a deliberately-too-close advance detector was **not** uniformly worse than a correctly-placed one — at the highest saturation levels it was actually *less* biased, because the shorter setback gives queue spillback less distance in which to "smear" arrivals across the cycle boundary before they're counted. Detector setback's effect on estimator bias should be verified empirically, not assumed monotonic with distance.

**The update-interval design curve found no interior optimum — ruling out transition churn as the cause.** Sweeping how often the controller re-adapts (every 1/2/5/10/20 cycles) found performance degraded roughly monotonically as updates got rarer, with adapting every single cycle performing best. This refutes the a-priori hypothesis that "too-frequent adaptation causes permanent transition churn, too-rare leaves a stale plan, so an interior sweet spot exists" — at least for a controller whose per-cycle slew limits already bound any single update's disruption. When update frequency is *not* the dominant cost, that itself is diagnostic: it points the investigation toward what the controller is adapting *based on* (in this case, the detector bias above) rather than *how often* it adapts.

## Transition mechanics: no free lunch among methods

Comparing four standard plan-transition methods (dwell/hold-then-jump, add-only, subtract-only, spread-over-N-cycles) on an isolated step change: dwell reached the new target fastest but paid the largest one-time cost in lost percent-arrival-on-green; the gentler methods (add-only, spread-N) took measurably longer to reestablish coordination and did not clearly reduce *total* excess delay relative to dwell. There is no dominant method — only a different distribution of the same underlying transition cost across time. Subtract-only is a genuine trap if misapplied: verified to simply never execute a transition when the target requires an *increase* (it has no legal move in that direction), which can look artificially safe in aggregate numbers unless the analysis explicitly checks whether the target plan was actually reached.

A related honest finding: a longer, theoretically higher-capacity cycle is not automatically a steady-state win over a shorter one even under heavy demand — its fixed per-vehicle extra-wait cost can outweigh its marginal capacity benefit, consistent with `[[webster-method]]`'s finding that the delay-minimizing cycle length's advantage sharpens or flattens depending on how close demand sits to capacity.

## Failure and robustness: real effects, honestly-sized

A plausibility-check-based detector-fault detector correctly flagged genuine stuck-on/stuck-off faults on nearly every active tick, with a very low false-positive rate on fault-free control runs — the detection mechanism itself is well-validated. A fallback-to-fixed-plan failsafe's effect on delay outcomes was inconclusive at the small replication count tested (single-seed), reported honestly as such rather than claimed as a clean win.

Sustained oversaturation (demand well beyond capacity, held constant) genuinely drove an unprotected cycle-length-adaptation rule's cycle length to its operational cap and kept it pinned there — a real, measurable runaway. A hard cycle cap's benefit against this was **modest, not dramatic** (a few percent delay reduction, not an order-of-magnitude fix) — because an oversaturated corridor's fundamental problem is a capacity deficit that no amount of cycle-length tuning within a fixed geometry can solve. Report a failsafe's actual measured recovery magnitude rather than assuming a protective mechanism must deliver a large win.
