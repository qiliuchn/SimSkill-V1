---
name: sweep-rerouting-device-market-penetration
description: Use this skill when the user wants to sweep the FRACTION of drivers equipped with SUMO's rerouting device (--device.rerouting.probability) as a treatment variable — rather than treating rerouting as a binary all-or-nothing switch — to study whether real-time traffic information is a congestible good, how private benefit to informed drivers changes with market penetration, and whether aggressive route-weight adaptation causes herding/oscillation. Covers subgroup attribution (equipped vs. unequipped travel time), a static-split reference technique for decomposing reactive-rerouting shortfalls into timing failures vs. allocation failures, and dual oscillation metrics (amplitude and flip-flop rate). Trigger on mentions of information penetration, rerouting market penetration, partial equipage, congestible information, or "does everyone having live traffic info help or hurt."
---

# Sweep Rerouting-Device Market Penetration

Studies how the *fraction* of drivers equipped with real-time rerouting information affects both those drivers and the network as a whole — as opposed to `simulate-incident-rerouting`'s baseline-vs-fully-equipped comparison, which treats the rerouting device as a binary switch. This skill sweeps `--device.rerouting.probability` as the primary treatment variable and adds the subgroup, timing-decomposition, and oscillation analysis needed to test whether information behaves as a **congestible good** — valuable to a lone informed driver, but with diminishing or even negative returns as more drivers share it.

## Subgroup attribution: separate private benefit from system benefit

The core methodological move: report travel time **separately** for equipped and unequipped vehicles (not just network-wide), by tagging vType and cross-checking the resulting partition against `tripinfo`'s own `devices` attribute — this turns "the subgroups are correctly classified" from an assumption into a checkable fact (a `device_vtype_mismatches` count of exactly zero across every run is strong, cheap evidence the partition is real).

**Verified finding: private benefit to being informed decays with penetration and can reverse.** At low penetration, informed drivers gained substantially over uninformed ones; as penetration rose, informed drivers' own travel time stayed roughly flat while uninformed drivers' travel time *fell* — because uninformed drivers increasingly free-ride on the informed minority's diversion (an uninformed vehicle that happens to be routed onto the now-less-congested main route benefits without ever needing information itself). Past a moderate penetration threshold, being equipped was actually *worse* than not being equipped. This is the textbook signature of a congestible good: value to an individual decays, and can go negative, as more people share it — verify this at multiple penetration levels rather than assuming a monotone "more informed drivers is strictly better for the informed" relationship.

**Verified finding: system-wide benefit can be genuinely non-monotonic (a real U-shape or inverted-U), with both legs statistically significant** — not just a diminishing-returns curve that flattens. In one verified test, network-wide mean travel time fell sharply from 0% to a mid-range penetration optimum, then rose again toward 100% penetration — though full penetration still substantially beat zero penetration, so the effect should be framed honestly as "losing part of the achievable benefit at the extremes," not "full penetration is worse than no information at all."

## The timing-vs-allocation decomposition: a static-split reference

To understand *why* a given penetration level underperforms, build a **static-split reference sweep**: force a fixed fraction of vehicles onto the alternate route (independent of any live rerouting device) at several fixed fractions, and find the fraction that minimizes network travel time (the system-optimal static split). Compare each reactive-rerouting penetration level's **realized average route share** against this static-optimal share:

- If the realized share matches the optimal share closely, but travel time is still worse than the static-optimal run's travel time, the shortfall is a **timing** problem — the average allocation is right, but *when* vehicles reach that allocation (herding, synchronized reaction, oscillation) costs real time that a instantaneous/pre-planned split wouldn't.
- If the realized share differs materially from the optimal share, the shortfall is (at least partly) an **allocation** problem — the reactive system isn't even converging to the right average split, regardless of timing.

**Verified finding these two failure modes can dominate at opposite ends of the same penetration sweep**: in one test, full-penetration reactive rerouting matched the system-optimal static split almost exactly on average, yet was still measurably worse — a pure timing failure. A mid-range penetration level, by contrast, matched a *worse* static split than optimal — an allocation (under-diversion) failure, not a timing one. Don't assume the same failure mode explains underperformance at every penetration level; check both.

## Testing herding/oscillation: two metrics, not one, and don't assume smoothing helps

Vary route-weight adaptation speed (SUMO's `--device.rerouting.adaptation-interval`/`adaptation-steps`, or equivalent smoothing parameters) between an aggressive fast-updating setting and a smoothed setting, and measure the route-split time series after the incident with **two distinct statistics**:

1. **Amplitude** (e.g. standard deviation of the alternate-route share over time) — how large the swings are.
2. **Flip-flop rate** (e.g. mean absolute step-to-step change) — how *fast* the split oscillates.

**These can move in opposite directions, so measuring only one gives an incomplete or even wrong picture.** Verified finding: fast adaptation produced a higher flip-flop rate (as expected — it reacts to noise faster) but *smoothing actually increased overall amplitude* by causing the split to latch at an extreme value for an extended period before crashing back — the opposite of the naive "smoothing reduces oscillation" assumption. Smoothed adaptation also produced worse average travel time than fast adaptation at every penetration level tested in this case. **Don't assume a smoothing/damping intervention improves an oscillation problem — measure both the amplitude and rate, and check the actual outcome metric, since a plausible-sounding mitigation can make things worse.** Also check for **pre-incident spurious diversion** — fast/noisy adaptation can divert a meaningful fraction of traffic onto a strictly-worse route before any incident even begins, purely from noise-chasing; a properly smoothed baseline should show essentially zero pre-incident diversion, and comparing this pre-incident-diversion rate is itself a useful diagnostic for how noise-sensitive a given adaptation configuration is.

## Honest equilibrium reference: report a failure to converge, don't paper over it

Run `duaIterate.py` (see `compute-dynamic-user-equilibrium`) as an equilibrium reference point on the same incident scenario. **A time-varying (incident) scenario may not let `duaIterate` converge within a reasonable iteration budget** — if the route split is still drifting monotonically at the final logged iteration with no sign of settling, and the per-bin cost gap plateaus without closing, report this as a genuine non-convergence, not as an equilibrium result to be trusted at face value. It can still serve as an approximate reference point (appropriately caveated) even without having converged — state clearly what it does and doesn't establish.

**Wardrop's principle must be tested per departure-time bin in any time-varying scenario, not pooled across the whole run.** Pooling vehicles that departed before/after the incident window together with those caught in it produces a large, mostly-spurious cost gap that reflects mixing two different regimes, not a real equilibrium failure — always bin by departure time relative to the incident window before computing a route-cost gap.

## Gotchas

- **Verify the equipped/unequipped subgroup partition against an independent source** (e.g. tripinfo's own device attribute), don't just trust that vType tagging alone produced the intended split.
- **Route classification must read the LAST route in a vehicle's `routeDistribution`, not the first** — a vehicle that reroutes onto the alternate keeps its original (main-route) choice as the first entry; misclassifying by the first entry silently mislabels every actually-diverted vehicle as having stayed on its original route. Quantify the size of this error (count of vehicles that would be misclassified) as a concrete sanity check.
- **SUMO lane 0 is the rightmost lane** — feeding a diverging alternate route from the wrong lane can make `netconvert` classify the diverge as a minor (yielding) movement against through traffic, silently capping diversion capacity and producing a spuriously bad "diversion made things worse" result. Check the compiled network's junction connection `state` (major `M` vs. minor `m`) before trusting any diversion-capacity finding.
- **`departLane="free"` can insert vehicles onto a lane their planned route can't actually use** (e.g. a dedicated diverge lane), stranding them and deadlocking a junction — use `departLane="best"` for a route-choice study.
- **A buffer edge between a diverge and a downstream closure only stores as much queue as its throughput-lane capacity, not its full multi-lane geometric length**, if one lane's traffic drains while the other queues — don't assume a wide buffer edge's total length translates directly into queue storage capacity.
- **A static-split reference sweep is a cheap, general-purpose tool for decomposing any reactive-control shortfall into "wrong average behavior" vs. "right average behavior, wrong timing"** — not specific to rerouting; consider it whenever a reactive/adaptive system underperforms an offline-optimized baseline and the reason isn't obvious.

## Related

- `simulate-incident-rerouting` — the binary baseline-vs-fully-equipped comparison and network/incident-design techniques (diverge placement, `closingLaneReroute` over `closingReroute`, route classification) this skill directly extends to a penetration sweep.
- `compute-dynamic-user-equilibrium` — the `duaIterate.py`/Wardrop-checking methodology used as this skill's equilibrium reference; the per-departure-bin Wardrop check is a further specialization for time-varying (incident) scenarios.
- `quantify-sumo-run-to-run-variability` — the Common-Random-Numbers/replication methodology this skill's penetration sweep applies.
- [[information-penetration-and-congestible-routing]] — the verified private-benefit-reversal, non-monotonic-system-benefit, timing-vs-allocation decomposition, and herding-mitigation-refutation findings.
- `model-cruising-for-parking-search-externality` — reproduces this skill's congestible-good/herding finding in the parking-guidance domain, and further isolates the failure as a coordination problem (informed drivers converging on the same reported-free space) fixable by a reservation layer, rather than an information-processing problem.
