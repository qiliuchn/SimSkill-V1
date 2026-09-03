---
summary: On a 10 km freeway corridor with three storage-limited metered on-ramps and a 3-to-2 lane-drop bottleneck, 444 CRN-replicated SUMO runs found that no control arm changed bottleneck throughput at all (3844-3848 veh/h across all seven arms) because the bottleneck has no measurable capacity drop, so metering only transfers delay - isolated ALINEA cut mainline delay 35-43% while raising Total System Delay 12-19% once ramp, surface-street and never-inserted delay were counted; HERO-style coordination was significantly worse than isolated control at every demand, its only benefit being a 92% reduction in per-ramp delay inequality, and a queue-flush override made the controller statistically indistinguishable from no control at only ~5% duty cycle.
keywords:
  - coordinated-ramp-metering
  - HERO
  - delay-transfer
  - ramp-storage-ratio
  - total-system-travel-time
  - queue-override
  - capacity-drop
created: 2026-08-03T21:00:00
last_updated: 2026-08-07T09:15:07
sources:
  - "[[episodic-memory/2026-08-03_21-00-00/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-08-03_21-00-00/outputs/DEPLOYMENT_DECISION_RULE.md]]"
  - "[[episodic-memory/2026-08-03_21-00-00/outputs/tables/hypotheses_report.txt]]"
related_pages:
  - "[[ramp-metering-with-alinea]]"
  - "[[variable-speed-limits-and-e2-detectors]]"
  - "[[diamond-interchange-signal-offset-and-spillback]]"
  - "[[sumo-stochastic-variability-and-replication-design]]"
  - "[[teleport-artifacts-and-gridlock-resolution-validity]]"
  - "[[zipper-merge-lane-drop-discharge]]"
  - "[[mfd-based-perimeter-gating]]"
  - "[[kinematic-wave-theory-validity-across-car-following-models]]"
  - "[[integrated-corridor-management-factorial-interaction-findings]]"
  - "[[sumo-output-files]]"
related_skills:
  - implement-coordinated-corridor-ramp-metering
  - implement-alinea-ramp-metering
  - build-diamond-interchange-with-signal-offset-spillback
  - implement-variable-speed-limits
  - quantify-sumo-run-to-run-variability
  - validate-congested-scenario-results-against-teleport-artifacts
  - evaluate-integrated-corridor-management-with-factorial-interaction-design
related_skills_for_graph_view:
  - "[[implement-coordinated-corridor-ramp-metering]]"
  - "[[implement-alinea-ramp-metering]]"
  - "[[build-diamond-interchange-with-signal-offset-spillback]]"
  - "[[implement-variable-speed-limits]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[validate-congested-scenario-results-against-teleport-artifacts]]"
  - "[[evaluate-integrated-corridor-management-with-factorial-interaction-design]]"
---

# Coordinated Ramp Metering, Delay Transfer and Ramp-Storage Limits

[[ramp-metering-with-alinea]] established, on a single isolated on-ramp, that ALINEA's
mainline benefit is real while its effect on network-wide delay is "sensitive to how much
ramp storage actually exists". This page reports what happens when that question is asked
properly, on a **corridor** — 9.9 km, three metered on-ramps with signalized
storage-limited terminals, two off-ramps, a 3→2 zipper lane-drop bottleneck — with seven
control arms, six demand levels, eight Common-Random-Numbers seeds, and a Total System
Travel Time accounting that charges metering for **every** delay it creates, including
demand that never gets inserted into the network at all. See
`implement-coordinated-corridor-ramp-metering` for the full build/control/validate recipe.

## The measurement that inverts the conclusion: origin-insertion delay

A ramp meter that backs a queue out through the ramp terminal and past the surface-street
origin produces vehicles that **never appear in `tripinfo`, never appear in `edgeData`,
and are invisible to every conventional metric**. `tripinfo`'s `departDelay` (the field
[[ramp-metering-with-alinea]] correctly identifies as where single-ramp queuing cost
hides) only covers vehicles that were eventually inserted.

The complete measure is the integral of the insertion backlog:

```python
pend_integral += len(traci.simulation.getPendingVehicles()) * dt   # vehicle-seconds
```

Adding this as a fourth TSTT component (mainline | ramp | surface | **origin**) changed
the sign of the headline result. At demand 1.30x capacity, isolated ALINEA's in-network
ledger reads −302 veh-h mainline, +19 ramp, +131 surface = **−152 veh-h, an apparent
system-wide win**. The origin term is **+292 veh-h**, turning it into a **+139 veh-h
loss** (+16.2%, 95% CI [+130, +149], p<0.0001, 8/8 seeds agreeing in sign). Any corridor
metering study without this term is measuring the wrong thing.

## Verified finding: with no capacity drop, metering cannot change throughput at all

A dedicated 60-run steady-demand measurement (10 levels x 6 seeds, breakdown classified
from a clean upstream detector) found the 3→2 lane drop had **no capacity drop**:
free-flow maximum discharge 3 824 veh/h, congested queue-discharge 3 837 veh/h, a drop of
**−0.3%**. Breakdown probability was 0% at ≤3 900 veh/h, 33% at 4 000 and 100% at ≥4 200 —
a genuinely stochastic threshold, but no lost capacity on either side of it.

The consequence was verified directly and is the single most useful number in the study:
**bottleneck discharge was 3 844–3 848 veh/h in every one of the seven control arms at
every one of the six demand levels — a total spread of 0.1%.** No control law moved
throughput. Everything any of them achieved was a **redistribution of delay**, so every
unit of restriction converted directly into system delay.

This independently reproduces, on a different bottleneck geometry and with a completely
different controller, the null capacity-drop result recorded for VSL in
[[variable-speed-limits-and-e2-detectors]], and is consistent with
[[kinematic-wave-theory-validity-across-car-following-models]]. **Treat "does this
bottleneck have a capacity drop" as the first measurement of any freeway-control study,
never as an assumption** — it determines whether the study can have a positive answer.

## Verified finding: delay transfer is large, and its net sign flips at ~1.15x capacity

Isolated per-ramp ALINEA vs no control, paired by CRN seed:

| demand / capacity | mainline delay | ramp | surface | origin | **Total System Delay** |
|---|---|---|---|---|---|
| 0.75, 0.89 | 0.0% | 0.0% | 0.0% | 0.0% | **+0.0%** (never armed) |
| 1.02 | −0.9% n.s. | +2.4% | +0.1% | −0.0% | **−0.7%** n.s. |
| 1.16 | **−34.9%** | +283% | +320% | +114 veh-h | **+19.3%** p<0.0001 |
| 1.30 | **−36.6%** | +223% | +482% | +292 veh-h | **+16.2%** p<0.0001 |
| 1.43 | **−42.7%** | +27% | +737% | +540 veh-h | **+11.8%** p<0.0001 |

Below ~1.05x capacity a correctly calibrated controller never arms and the outcome is
**byte-identical** to no control — metering is neither harmful nor useful. Above ~1.15x it
arms hard and is decisively net-negative. The mainline benefit is entirely real
(−35 to −43% mainline delay, visible as a much shorter upstream queue on a speed contour);
it is simply paid for, roughly 1.5x over, by everyone else.

## Verified finding: coordination LOSES to isolated control when there is no capacity to defend

HERO-style master/slave recruitment (bottleneck-adjacent ramp as master; upstream ramps
recruited when the downstream cluster member's queue-to-storage ratio exceeds a threshold;
slaves metered to equalise queue ratios) was **significantly worse** than isolated
per-ramp ALINEA at every demand where either armed: +1.0% (n.s.), **+6.2%** (p=0.0006) and
**+2.8%** (p<0.0001) of Total System Delay. Adding a third arm — single-ramp ALINEA on the
bottleneck detector, no recruitment — localised the loss to the **recruitment** itself
(+59.0 veh-h, p=0.0004) rather than to detector placement (+3.3 veh-h, n.s.).

The mechanism is the previous section: recruiting upstream ramps withholds more vehicles,
but the bottleneck discharges the same 3 844 veh/h either way.

**The scaling claim survives even though the direction does not.** Sweeping the
bottleneck-adjacent ramp's storage 80 → 640 m with corridor length held constant, the
metering penalty falls monotonically (isolated ALINEA +22.4% → +9.7%; coordinated +28.7% →
+14.2%) and the storage-exceeded fraction falls 19% → 0% of control intervals — so the
**ramp-storage ratio, not corridor length, is the governing variable**, exactly as
hypothesised. It simply never reaches break-even within an 8x sweep.

### The ramp-storage ratio, as an explicit deployment number

```
required storage (veh) = (demand at bottleneck − bottleneck capacity) x peak duration
available storage (veh) = Σ ramp storage length / (vehicle length + min gap)
```

At 1.30x capacity: 1 147 veh/h excess over a 40-minute peak = **765 vehicles to withhold**,
against (280+220+160) m / 7.5 m = **88 vehicles available**. **Storage ratio 0.115.** The
other 677 vehicles queued out of the network. No control law can succeed at that ratio,
and the ratio — not the algorithm — is what should be checked first.

## Verified finding: a queue-flush override does not degrade the controller, it switches it off

Ramp meters are almost always deployed with a queue override protecting the surface
street. Adding a strict one (flush at 85% of storage, release at 50%):

| demand / capacity | override share of armed time | TSD vs no control | mainline benefit retained |
|---|---|---|---|
| 1.16 | 4.9% | +0.4% (p=0.27) | 3.7 of 40.4 pp |
| 1.30 | 5.3% | +0.6% (p=0.11) | 1.9 of 54.9 pp |
| 1.43 | 21.1% | +0.2% (p=0.34) | 1.6 of 56.7 pp |
| 1.43, flush at 70% | 32.5% | +0.1% (p=0.43) | — |

**At an override duty cycle of only ~5% the controller is already statistically
indistinguishable from no control** on system delay, on bottleneck discharge (3 847 vs
3 848 veh/h) and on queue extent (5.12 vs 5.25 detector stations). There is no graceful
intermediate regime — the expectation that an override "progressively" erodes performance
is wrong. The reason is the storage ratio again: a flush threshold at 85% of a 21-vehicle
segment caps the withheld demand at ~18 vehicles against the 765 that need withholding.
**Measure the override duty cycle; above roughly 5% of armed time the meter is decorative.**

## Verified finding: coordination's real product is equity, and it is priced at zero throughput

Isolated metering concentrates the entire burden on the bottleneck-adjacent ramp. Per-ramp
mean wait per released vehicle at 1.30x capacity, [upstream, middle, bottleneck-adjacent]:

| arm | waits (s) | Gini | max/mean |
|---|---|---|---|
| isolated ALINEA | [20.1, 23.0, **103.2**] | 0.386 | 2.12 |
| coordinated | [105.4, 105.8, 93.5] | **0.031** | **1.06** |

Coordination cut the Gini coefficient by **91.9%** (p<0.0001, 8/8 seeds; −80.8% and −79.3%
at the neighbouring demand levels). **The throughput price of imposing near-equal ramp
delay is exactly zero throughput and +6.2% system delay** (+62.3 veh-h) — because
bottleneck discharge is unchanged by construction. That is a defensible price if equity is
a stated objective, and the only thing coordination demonstrably bought.

## Verified finding: metering never prevented breakdown (null result)

Sweeping the activation occupancy threshold with matched hysteresis from early (7.5%) to
late (20%) moved the mainline benefit −55.7% → −51.1% and the system penalty +23.3% →
+20.6% — a smooth monotone trade, **not** a prevention/recovery threshold. Breakdown onset
measured at a clean upstream detector was **1 841–1 856 s in every arm, including no
control at 1 856 s**, and 8/8 seeds broke down under every arm.

This is the honest cross-check the hypothesis demanded: with no capacity drop there is no
retained capacity for prevention to deliver, so **"prevention beats recovery" is not a
real effect at this bottleneck**. Any positive result here would have been an artifact.

## Verified finding: surface-delay coupling is super-linear WITHIN a policy, linear across policies

Regressing surface-street delay on total ramp-queue vehicle-hours in log-log space:

- **within a fixed control policy**: exponent **1.25 ± 0.02** (isolated ALINEA),
  **1.31 ± 0.02** (bottleneck-ALINEA), **1.08 ± 0.01** (coordinated), R² 0.99 — all
  significantly super-linear.
- **pooled across policies**: **0.96 ± 0.03** — indistinguishable from linear, because the
  policies have structurally different queue→surface mappings (the flush arm's exponent is
  0.30).

**Report the exponent per policy, not pooled**; pooling silently converts a real
super-linear coupling into a null result. Explicit instrumentation (not inference from
aggregate delay) confirmed the channel: the cross-street queue at the ramp terminals rose
from 14.5 veh-h under no control to 45.2 veh-h under coordinated metering.

**The interchange never gridlocked**, despite `keepClear="false"` deliberately permitting
junction-box blocking on the ramp-bound movement: 0 incomplete trips and 0 teleports in all
444 runs. The overflow escaped upward into the insertion queue rather than locking the
junction — so the "spillback can gridlock the interchange" expectation was **not** borne out
in this configuration.

## The calibration failure that cost a whole 444-run matrix

The occupancy setpoint was first taken from a **mainline-only** (ramps closed) sweep — the
method [[ramp-metering-with-alinea]] describes, correct for a single isolated ramp. **It
does not transfer to a corridor.**

Pooling every control interval from 48 no-control *corridor* runs gave a very different
picture. The station ~100 m upstream of the lane drop sits inside a **permanent
merge-turbulence zone**: with the on-ramps active it reads 15.8 m/s and 7.0% occupancy at
a demand **25% below** the corridor's capacity, where the mainline-only sweep read 32 m/s
and 4%. Its flow-occupancy curve is nearly flat (3 600–4 080 veh/h across 8–31% occupancy),
so its critical occupancy is 22.7%, not the 5.8% the mainline-only sweep implied. A
controller regulating it to the mainline-only setpoint was **restrictive 40–44% of control
intervals at 25% below capacity** and cost +29% system delay for zero mainline benefit.

Two rules follow. **Calibrate on the corridor with its ramps active** — pooling existing
no-control runs costs no extra simulation. And **separate the control detector from the
breakdown-reporting detector**: a station inside a merge-turbulence zone reads below any
sensible speed threshold even in free flow, so "breakdown onset" measured there comes out
identical in every arm and is meaningless.

## Measurement-layer validation results worth reusing

- **E2 vehicle count is exact; E2 jam length is not.** Cross-validating 1 200 paired
  instants against raw FCD vehicle positions: `LAST_STEP_VEHICLE_NUMBER` matched the true
  count to a mean absolute error of **0.24–0.29 vehicles**, while `jamLengthInMeters`
  correlated only r = **0.85** with an FCD reconstruction, MAE **30.8 m** on queues up to
  265 m, and a 5-point sensitivity sweep of the reconstruction's halting-speed and
  jam-distance thresholds swung the bias from +30.8 m to −45.5 m. **Use vehicle count over
  storage capacity as a controller's queue state.**
- **The one-car-per-green rate→signal translation systematically under-delivers.** Realized
  release rate vs commanded, restricted to intervals where the meter was actually
  restrictive *and* ≥2 vehicles were queued: **−5.9% to −35.1%** bias, MAPE 20–37%, over
  2 961–7 364 intervals per arm. Verify it; a "commanded rate" is not what the ramp released.
- **`--device.fcd.period` offsets each vehicle's sampling by its own departure time**, so
  almost nothing lands on a control instant; and `--fcd-output.filter-edges.input-file`
  takes a netedit selection file (`edge:<id>` per line), not `<additional>` XML — passing
  XML matches nothing and silently yields an FCD file with 6 000 timesteps and zero vehicles.
- **TraCI subscriptions, not per-step getters.** Querying ~150 detector getters per
  simulation step was socket-bound rather than simulation-bound: 64 s/run became 36 s/run
  after moving every E1/E2 read to `subscribe()` + one `getAllSubscriptionResults()` per
  step, verified behaviour-preserving by reproducing a run's outputs exactly.

## Deployment decision rule

The full gated rule is in the episode's `DEPLOYMENT_DECISION_RULE.md`. In short: measure the
capacity drop first (no drop ⇒ metering cannot add throughput); do not deploy below ~1.05x
capacity (the controller will not even arm); do not deploy below a ramp-storage ratio of
~0.5; deploy for mainline level-of-service only if mainline time is valued ≈1.5x everyone
else's; coordinate only when a real capacity drop exists or equity is an objective; and
expect a queue override above ~5% duty cycle to neutralise the controller entirely.
**On the corridor studied here every gate fails, and the honest recommendation is not to
meter** — a real result following from a bottleneck with no capacity drop and ramps holding
11% of the storage the policy would need.
