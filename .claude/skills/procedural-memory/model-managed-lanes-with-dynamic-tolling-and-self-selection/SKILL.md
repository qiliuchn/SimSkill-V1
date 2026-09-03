---
name: model-managed-lanes-with-dynamic-tolling-and-self-selection
description: Use this skill when the user wants to model freeway managed lanes (HOV/HOT/express lanes) in SUMO — a lane restricted to high-occupancy or paying vehicles alongside general-purpose lanes — including a heterogeneous fleet with explicit vehicle occupancy and value-of-time, a TraCI self-selection controller that lets vehicles buy into the managed lane only when the toll is worth it, a dynamic feedback toll, and gated-vs-continuous access design. Covers per-VOT-quartile equity reporting, person-throughput (not just vehicle-throughput) accounting, the "empty lane paradox" (a static HOV lane can make person-throughput AND person-hours worse below a carpool-share threshold), and testing whether the throughput-optimal toll differs from the revenue-optimal toll. Trigger on mentions of HOV lane, HOT lane, express lane, managed lane, congestion pricing on a specific lane, value of time, or person-throughput.
---

# Model Managed Lanes with Dynamic Tolling and Self-Selection

Builds a freeway corridor with a lane restricted to high-occupancy or toll-paying
vehicles and measures whether it actually moves more *people*, not just more
vehicles. Distinct from `model-cordon-tolling-with-generalized-cost-surcharge` (a
zone-entry toll driving a route choice) — a managed lane is a **lane choice**, not a
route choice, and the eligibility mechanism, tolling target, and validity checks are
correspondingly different.

## Network and the managed lane itself

Hand-author the freeway corridor plain-XML (a corridor with on-ramps/off-ramps needs
`implement-alinea-ramp-metering`'s zipper-merge/priority-diverge construction, since
`netgenerate` cannot express real ramp topology). Build the managed lane as the
leftmost lane with a restricted `allow` list (e.g. `allow="hov bus"`) via
`model-vclass-lane-permissions`'s plain-XML editing and netconvert recompilation.
Verify from the compiled net that the restriction genuinely took effect and that
ramp/merge connections have the expected state (zipper vs. priority) — don't assume
the lane-count and permission changes compiled as intended.

**For gated (limited-access) vs. continuous access, use per-lane
`changeLeft`/`changeRight` connection attributes, not a permission restriction.**
Outside a small number of designated gate segments, set
`changeLeft="authority" changeRight="authority"` (or symmetric) on the managed lane's
connections to forbid ordinary vehicles from crossing into or out of it — the same
technique documented in `measure-roundabout-capacity-and-implement-metering` for
forbidding ring weaving. **`changeLeft="none"`/`""` are invalid netconvert
attributes**; the working idiom is a vClass token no demand vehicle actually carries
(e.g. `"authority"`).

## Heterogeneous fleet: explicit occupancy and value-of-time

Generate demand as explicit `<vehicle>` elements (not flows) carrying, per vehicle,
an occupancy (single-occupant, carpool 2-3, bus ~N(40, σ)) and a value-of-time (VOT)
drawn from a lognormal distribution — persist both in a side-channel file (e.g. a
CSV keyed by vehicle id) alongside the route file, since SUMO itself has no native
per-vehicle VOT attribute. **The identical demand/fleet file must feed every policy
arm** — this is what makes a cross-arm comparison a clean policy comparison rather
than a demand-generation confound.

## Self-selection: a TraCI buy-in controller, not a route-choice reroute

The eligibility decision ("should this vehicle use the managed lane") is a
**per-vehicle, per-trip lane choice conditioned on the vehicle's own value-of-time**,
not a route reroute — implement it as a TraCI loop that, for each un-eligible vehicle
approaching the managed-lane segment, estimates the time saving from using it
(e.g. from recent per-lane corridor speeds measured via detectors) and grants
eligibility — via `traci.vehicle.setVehicleClass(vid, 'hov')` against a net
**already compiled with the restriction** — only if `time_saving * own_VOT >
current_toll`. **This side-steps a real pitfall entirely**: `traci.lane.setAllowed`
(SUMO's more obvious-looking API for this) only gates *future* lane entry and can trap
already-committed vehicles at a junction if the net was compiled with the lane closed
(see `implement-dynamic-hard-shoulder-running`'s connectivity gotcha) —
`setVehicleClass` against a net compiled *open* avoids this failure mode entirely
and is the simpler, more robust mechanism for this specific use case.

**Fit an empirical price-elasticity curve from the buy-in log**: regress
`ln(take-rate)` against `ln(toll)` across a swept range of static toll levels — expect
a clean power-law relationship (constant elasticity) over a substantial price range,
with the take-rate transitioning from inelastic (below some price) to elastic (above
it). This is a genuinely useful, reusable diagnostic for characterizing how sensitive
a specific corridor's demand is to price, separate from any throughput conclusion.

## Dynamic tolling: repurpose ALINEA's feedback law as a price law

An ALINEA-style feedback controller (`implement-alinea-ramp-metering`'s
`r(k) = r(k-1) + K*(target - measured)`) adapts directly into a dynamic toll: replace
the metered release rate with a toll level, and replace mainline occupancy with
managed-lane occupancy (or speed) measured by E1/E2 detectors on the managed lane
itself. **Calibrate the target/setpoint from the SAME lane's own unrestricted
flow-occupancy curve** (load it as an ordinary GP lane in the baseline arm and read
the occupancy at its own measured peak flow) rather than importing a generic
textbook target — verified case: the textbook ALINEA occupancy range (15-25%) did not
match a real measured critical occupancy of ~13% for this specific lane/vehicle-mix
combination. Clip the toll to a sensible floor/ceiling and expect a well-tuned
dynamic toll to converge, unaided, close to whatever price a manual static sweep
would separately identify as best.

## Measuring person-throughput, not just vehicle-throughput

**Every headline metric in a managed-lane study should be reported in persons, not
just vehicles** — multiply per-vehicle counts by each vehicle's occupancy before
aggregating. This is the entire point of the exercise: a managed lane can look good
on vehicle-throughput while being bad on person-throughput, or vice versa, and only
person-based accounting reveals which.

## Testing whether a managed lane helps: the empty-lane paradox

**Test explicitly whether a static HOV-only lane can make BOTH corridor
person-throughput AND total person-hours-traveled worse than an all-general-purpose
baseline, and find the specific carpool-share/demand threshold below which this
happens.** The mechanism: at low carpool share, dedicating a lane to a small
minority of high-occupancy vehicles removes real capacity from the general-purpose
lanes (which carry the bulk of person-trips) while the managed lane itself is
under-utilized — sweep carpool share, total demand, and transit (bus) volume to find
where this reverses. **Check throughput and delay separately — they don't
necessarily cross at the same threshold.** A verified case found a demand level where
the HOV lane cost *zero* measurable throughput but still cost substantial person-hours
(a genuine finding that would be missed by checking only one metric).

## Testing whether the toll can be "wrong": throughput-optimal vs. revenue-optimal

**Sweep the static toll level and separately locate the toll that maximizes
managed-lane vehicle throughput, the toll that maximizes corridor person-throughput,
and the toll that maximizes revenue — do not assume these three optima coincide.**
A managed lane's own physical capacity constraint can make this test come out
differently than expected: if the lane saturates (its own flow-occupancy curve peaks)
at a low fraction of demand relative to the general-purpose lanes' capacity, both the
vehicle-throughput and person-throughput optima can sit at the toll floor (giving away
free access, since a price can only ever *subtract* flow from a lane that's nowhere
near being oversold) — while the *revenue*-maximizing toll can sit dramatically
higher, at real cost to both throughput objectives. **Verify this mechanism directly
with a capacity probe** (push demand to well above the tested range on the managed
lane specifically, e.g. 200%+) to confirm the lane genuinely never approaches its own
saturation point under realistic policy-relevant demand, rather than assuming a null
throughput-vs-toll result is evidence the optima "don't matter."

## Testing access design: gated vs. continuous

Compare continuous access (lane changes into/out of the managed lane permitted along
its full length) against limited access with designated gates (implemented via the
`changeLeft`/`changeRight` restriction above). **Measure weaving localization
directly** (the fraction of managed-lane-adjacent lane changes occurring inside vs.
outside designated gate zones, and a spatial concentration statistic such as the
lane-change rate at gates relative to a uniform-distribution baseline) — expect gating
to concentrate lane-change activity sharply at the gates and reduce total corridor
lane-change count. **Do not assume this concentration automatically translates into a
measurable throughput, delay, or safety benefit — test it separately, and report a
genuine null result if the performance/safety metrics don't move**, rather than
inferring a performance benefit from the weaving-localization result alone.

## Per-value-of-time-quartile equity reporting

Break every headline outcome down by value-of-time quartile: buy-in/take rate,
generalized cost (time cost plus toll paid), and travel-time change, each reported
per quartile rather than only as a fleet-wide mean. **Check both the absolute-dollar
and proportional framing before concluding a pricing scheme is regressive.** A
verified case found the absolute-dollar burden gap between the highest and lowest
value-of-time quartiles looked regressive, but this was almost entirely an artifact
of high-value-of-time travelers valuing the *same* time savings more in dollar terms
— the *proportional* burden (as a fraction of each quartile's own generalized cost)
was flat within a few percentage points across all quartiles, and the lowest quartile
(which mostly does not buy in) still benefited substantially from the general-purpose
lanes' improved speed once paying vehicles left them. Report both framings explicitly
rather than defaulting to whichever one is more dramatic.

## Gotchas

- **`traci.lane.setAllowed` can trap already-committed vehicles at a junction if the
  net was compiled with the managed lane closed** — for a self-selection eligibility
  controller, prefer `traci.vehicle.setVehicleClass` against a net compiled with the
  restriction already in place; this avoids the connectivity trap entirely rather
  than requiring the open-then-gate-at-t=0 workaround `implement-dynamic-hard-shoulder-running` documents for `setAllowed`.
- **`changeLeft="none"`/`""` are invalid netconvert connection attributes** — use a
  vClass token no demand vehicle carries (e.g. `"authority"`) to forbid lane-change
  access outside designated gates.
- **Calibrate a dynamic feedback toll's setpoint from the SAME lane's own
  unrestricted flow-occupancy curve, not a generic textbook occupancy target** — the
  critical/target occupancy is lane- and vehicle-mix-specific and can differ
  substantially from commonly-cited reference ranges.
- **A managed lane's own capacity constraint can make the throughput-optimal toll sit
  at the price floor** — verify this with an explicit high-demand capacity probe on
  the managed lane before concluding a null toll-sweep result means the toll level
  doesn't matter; it may mean the lane simply never saturates under tested demand.
- **Report person-throughput, not just vehicle-throughput, for every headline
  metric** — a managed lane's effect on the two can point in different directions.
- **Weaving-localization from gated access does not automatically imply a
  performance or safety benefit** — measure and report them as separate, independently
  testable claims.
- **Check both absolute-dollar and proportional framings of an equity/burden
  statistic** — a gap that looks regressive in dollar terms can be flat or even
  progressive in proportional terms, since high-value-of-time travelers value the same
  time savings more.

## Related

- `model-vclass-lane-permissions` — the base lane-restriction editing mechanism this
  skill's managed lane is built from.
- `model-cordon-tolling-with-generalized-cost-surcharge` — the closest structural
  analog (a synthetic generalized-cost mechanism gating vehicle behavior via TraCI),
  contrasted here: a zone-entry route choice there vs. a per-vehicle lane choice here.
- `implement-alinea-ramp-metering` — the feedback-control law this skill's dynamic
  toll directly repurposes, and the zipper-merge/ramp-geometry construction technique
  this skill's corridor is built from.
- `implement-dynamic-hard-shoulder-running` — the `setAllowed`-vs-junction-connectivity
  gotcha this skill's `setVehicleClass` eligibility mechanism was specifically chosen
  to avoid.
- `model-cruising-for-parking-search-externality` — transplants this skill's VOT-based
  self-selection controller pattern to curb-vs-garage-vs-balk parking choice, and found
  curb pricing regressive by VOT quartile — contrast with this skill's own finding that
  HOV-to-HOT conversion improved every VOT quartile roughly proportionally.
- `model-freeway-weaving-segment` — the on-ramp/off-ramp topology and
  `--lanechange-output` weaving-quantification technique this skill's access-design
  test (H3) directly reuses.
- `measure-roundabout-capacity-and-implement-metering` — shares this skill's
  `changeLeft`/`changeRight="authority"` technique for forbidding lane-change access
  in a specific segment, applied there to a roundabout ring rather than a managed
  lane's gate zones.
- `quantify-sumo-run-to-run-variability` / `validate-congested-scenario-results-against-teleport-artifacts` — the CRN replication and teleport/completion validity discipline applied throughout this skill's multi-arm comparison.
- [[managed-lanes-empty-lane-paradox-and-person-throughput]] — the verified
  empty-lane-paradox threshold, the toll-optimum-saturation finding, the
  weaving-localization-without-performance-effect finding, and the proportional
  equity finding this skill's methodology produced.
