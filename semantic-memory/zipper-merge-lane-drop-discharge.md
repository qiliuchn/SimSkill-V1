---
summary: SUMO's zipper junction type (cooperative alternating late-merge, compiled connection state "Z") is a fairness/merge-discipline mechanism, not a capacity booster — verified directly at an oversaturated 2-lane-to-1-lane work-zone bottleneck, it reduced sustained discharge throughput by ~5.7% and raised mean time loss/depart delay relative to SUMO's default priority merge, robust across multiple random seeds.
keywords:
  - zipper-merge
  - lane-drop
  - work-zone-bottleneck
  - late-merge
  - discharge-throughput
  - merge-junction
created: 2026-07-31T00:35:00
last_updated: 2026-08-06T00:30:00
sources:
  - "[[episodic-memory/2026-07-31_00-21-48/outputs/FINDINGS.md]]"
  - "[[episodic-memory/2026-07-31_00-21-48/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[ramp-metering-with-alinea]]"
  - "[[toll-plaza-queueing-and-the-service-headway-floor]]"
  - "[[stochastic-freeway-capacity-and-breakdown-probability]]"
related_skills:
  - compare-zipper-vs-default-merge-at-lane-drop
  - implement-alinea-ramp-metering
  - analyze-simulation-outputs
  - estimate-stochastic-freeway-capacity-and-breakdown-probability
related_skills_for_graph_view:
  - "[[compare-zipper-vs-default-merge-at-lane-drop]]"
  - "[[implement-alinea-ramp-metering]]"
  - "[[analyze-simulation-outputs]]"
  - "[[estimate-stochastic-freeway-capacity-and-breakdown-probability]]"
---

# Zipper Merge vs Default Merge at a Lane Drop

SUMO's `zipper` junction type implements a cooperative, alternating "late merge" discipline at a junction where multiple approach lanes converge into fewer downstream lanes — the compiled network marks every contested connection into the shared lane with `state="Z"`, as opposed to the default `priority`-type junction's asymmetric `m`(minor, must-yield)/`M`(major, right-of-way) split that picks one approach to yield unconditionally. This mechanism was first used in this memory in the context of a ramp merging onto a mainline (see `implement-alinea-ramp-metering`); this page documents its effect in a different, and more common, real-world topology: a straight work-zone lane drop, where both approach lanes are structurally equal and simply converge into one downstream lane.

**Retroactive qualification** ([[stochastic-freeway-capacity-and-breakdown-probability]]): the sustained-discharge figures below are a single deterministic queue-discharge measurement, of the same kind independently shown elsewhere to sit around the 3rd–5th percentile of a bottleneck's true stochastic capacity distribution, not its mean. Read the 1900.4/1791.3 veh/h contrast below as comparing two low-percentile discharge rates, not two central-tendency capacities.

## Verified finding: zipper reduced discharge and raised delay at saturation

On a 1046m 2-lane approach dropping to a 596m single-lane bottleneck, with sustained demand (2400 veh/h) engineered to genuinely oversaturate single-lane capacity (car-following `tau` raised to 1.5s so per-lane capacity was ~2030 veh/h — at SUMO's default `tau≈1.0s`, single-lane capacity is high enough, ~2600+ veh/h, that 2400 veh/h did *not* actually oversaturate and produced zero queue):

- **Sustained discharge throughput** (edgeData `entered`, excluding the startup transient): 1900.4 veh/h (default) vs. **1791.3 veh/h (zipper) — a 5.7% reduction**.
- **Mean time loss**: 209.9s (default) vs. 252.7s (zipper) — **+20.4%**.
- **Mean depart delay** (time queued at origin before insertion): 267.9s vs. 356.5s — **+33.1%**.
- Direction (zipper worse) held robustly across 4 independent random seeds.

**Max upstream on-road queue length tied at the full 1046m approach length in both variants** — a ceiling effect, since the finite approach fully filled with queued vehicles either way. This means depart delay, not on-road queue length, was the metric that actually revealed the real difference between the two merge disciplines — the excess congestion under zipper spilled into vehicles waiting to even enter the network, invisible to an on-road queue-length metric alone.

## Interpretation

`zipper` is best understood as a **fairness/merge-discipline mechanism** — it forces strict alternation between the two converging approaches, regardless of which approach happens to have a vehicle ready to merge sooner. At an already-saturated 2-into-1 drop, this verified test found that forcing strict alternation slightly **depresses** discharge relative to the default priority merge, which can opportunistically let whichever lane has a closer/faster vehicle proceed without waiting its turn. **This directly contradicts the naive assumption that "cooperative/smarter" implies "higher throughput"** — zipper's design goal (fairness between approaches) is not the same as maximum discharge, and the two can trade off against each other under saturation. Always measure a merge-discipline change's actual effect on the specific metric that matters (throughput vs. fairness vs. delay) rather than assuming a more sophisticated mechanism is strictly better.

## Practical takeaways

- Confirm a demand level genuinely oversaturates (nonzero sustained queue, not just a number that sounds high relative to a textbook capacity figure) before trusting any bottleneck comparison — SUMO's actual per-lane capacity depends on car-following parameters like `tau`, not just lane count.
- Apply any car-following parameter change identically across compared runs.
- Watch for a queue-length ceiling effect on a short/finite approach — a tied on-road queue length doesn't mean the two configurations perform identically; check depart delay too.
- Diff the full compiled network between variants to confirm only the intended junction-type change differs, not an incidental geometry difference.

See the `compare-zipper-vs-default-merge-at-lane-drop` skill for the full network-build, compiled-net verification, and analysis workflow.
