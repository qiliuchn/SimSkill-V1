---
summary: SUMO's container/transport/tranship/containerStop object family has multiple silent-failure modes (an unwaited transport stage never loads, capacity overflow and late arrivals fail without warning, undelivered containers are invisible in tripinfo, no traci.container domain exists) that must be verified empirically rather than assumed; modeling freight demand as delivery tours rather than independent single-OD trips matters a great deal (the trip shortcut substantially overstates truck VKT, emissions, and freight-attributable car delay); an exempted truck restriction's exchange rate can refute the standard "reduces exposure but worsens emissions" framing entirely if the exempt class is cleaner per km, while a blanket restriction is service destruction rather than a tradeoff; a loading-bay deficit's delay curve is not automatically convex on single-lane streets (no escape lane means a double-park is already a complete blockage from the first deficit unit); fleet consolidation has a genuine delay crossover rather than a monotonic win; off-peak shifting's benefit curve can be convex with a large noise counter-cost; and a critical vClass-assignment gotcha (screening candidate vehicle classes by edge permission rather than round-trip route feasibility) can manufacture a fabricated non-monotone "partial restrictions worse than complete restrictions" finding, discovered and withdrawn in this episode's own first draft after independent review.
keywords:
  - urban-freight
  - delivery-tours
  - container
  - containerStop
  - truck-route-restriction
  - loading-bay
  - fleet-consolidation
  - off-peak-delivery
  - reachability-failure
created: 2026-08-03T13:30:00
last_updated: 2026-08-03T13:30:00
sources:
  - "[[episodic-memory/2026-08-03_13-00-00/outputs/FINDINGS.md]]"
  - "[[episodic-memory/2026-08-03_13-00-00/outputs/probe/PROBE_FINDINGS.md]]"
  - "[[episodic-memory/2026-08-03_13-00-00/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[vehicle-class-lane-permissions]]"
  - "[[heavy-vehicle-passenger-car-equivalent-in-sumo]]"
  - "[[curbside-delivery-blocking-externality]]"
  - "[[public-transport-and-intermodal-routing]]"
related_skills:
  - model-urban-freight-delivery-tours
  - model-vclass-lane-permissions
  - measure-heavy-vehicle-passenger-car-equivalent
  - model-curbside-delivery-and-lane-blocking-externality
  - simulate-fleet-emissions
related_skills_for_graph_view:
  - "[[model-urban-freight-delivery-tours]]"
  - "[[model-vclass-lane-permissions]]"
  - "[[measure-heavy-vehicle-passenger-car-equivalent]]"
  - "[[model-curbside-delivery-and-lane-blocking-externality]]"
  - "[[simulate-fleet-emissions]]"
---

# Urban Freight Delivery Tours: Container Semantics and Policy Levers

The project's first use of SUMO's container/logistics object family and its first non-single-OD,
multi-stop-tour demand form. A parameterized 6x6-block urban district (arterial ring + bisecting
arterial + interior local streets) carried tour-based freight demand (nearest-neighbour + 2-opt
sequencing, explicit `<container>` objects, per-stop dwell scaling with parcel count) alongside
background car traffic, tested against seven policy hypotheses with CRN replication. See
`model-urban-freight-delivery-tours` for the full construction methodology.

## Verified finding: SUMO's container object family has multiple silent-failure modes

Every claim below was checked against raw output, not documentation: a `<transport from="edge">`
stage alone never loads a container and produces **no warning**; loading/unloading blocks the
vehicle and is per-container additive (`max(authored dwell, loadingDuration * n_containers)`);
capacity overflow, an orphan `lines=` reference, and a late-arriving container all fail **completely
silently** (exit code 0, empty stderr); `<containerinfo>` appears in `tripinfo` only for containers
that **completed** their itinerary, so an in-transit or never-boarded container is invisible even
with `--tripinfo-output.write-unfinished true`; **no `traci.container` domain exists** in SUMO
1.27.1's Python TraCI; `expectedContainers` genuinely holds a vehicle for a late container (verified
to hold for hundreds of extra seconds) but without it a late container is missed in silence; and a
route file mixing `<container>`/`<vehicle>` elements out of departure-time order makes SUMO **drop
the out-of-order element with only a warning**, applying to both element types. **The practical
consequence: a freight study using containers must reconcile offered parcels against
`unloadedContainers` (stop-output) and completed `<containerinfo>` count (tripinfo) explicitly as a
standing validity check** — SUMO will not surface a silent failure on its own.

## Verified finding: the tour-vs-trip demand-modeling shortcut substantially overstates freight impact

Modeling identical total parcel demand as independent single-OD truck trips (the common shortcut
when a dedicated tour generator isn't available) produced a large, one-signed bias in a verified
comparison — overstating truck VKT, freight CO2, and freight-attributable car delay, and roughly
doubling the apparent spatial concentration of truck presence, relative to genuine tour-based
demand with the same total parcels delivered. The mechanism is straightforward once stated: a tour
serves many nearby stops with much shorter marginal travel between consecutive stops than a set of
independent single-OD trips would each require, so the trip approximation systematically inflates
distance, emissions, and the delay imposed on other traffic. **Any freight-impact study should
disclose which demand paradigm it used** — the two are not interchangeable approximations of the
same underlying quantity, and the direction of the error (overstatement) is consistent enough to be
a genuine methodological finding, not scenario noise.

## Verified finding: an exempted restriction's exchange rate does not automatically make emissions worse

The standard practitioner framing — banning trucks from residential streets reduces exposure but
increases total freight VKT and therefore emissions — held for the exposure side but was **refuted**
for the emissions side in a verified comparison: total freight CO2 **fell** as heavy-truck
restriction coverage rose (with a delivery-van exemption in place), because the exempt class's
emission profile was cleaner per kilometer than the restricted class's, more than offsetting the
extra kilometers driven. This is not automatic in general — it depends on the specific fleet's
emission-class assumptions — but it demonstrates the standard exchange-rate framing should be
checked against actual per-class emission factors rather than assumed. Separately, **a blanket
restriction banning every freight class is not a tradeoff at all — it is service destruction
proportional to coverage**, since there is no legal fallback class; exchange-rate reasoning (a
continuous cost/benefit curve) is the wrong model for that scenario.

## Verified finding: a loading-bay deficit's delay curve is not automatically convex — it depends on escape-lane geometry

A prior verified finding ([[curbside-delivery-blocking-externality]]) found loading-bay deficit
produces a convex, "few bays short costs far more than proportionally" delay curve on a multi-lane
street. This episode found that shape **does not transfer to a single-lane residential street**: the
delay curve there was statistically indistinguishable from linear. The mechanistic reason is that a
single-lane street offers no escape lane, so a double-park is already a complete blockage at the
first deficit unit — there is no partial-blockage regime left for a convex knee to emerge from. **A
convex bay-deficit shape found in one geometry should not be assumed to transfer to a different road
geometry without checking whether an escape lane exists.**

## Verified finding: fleet consolidation has a genuine delay crossover, not a monotonic win

Replacing many smaller delivery vehicles with fewer, larger ones (equal parcel throughput) cut total
vehicle-km monotonically in a verified sweep, but per-vehicle PCE, dwell time, and lane-blocking
duration all rose with vehicle size — past a specific fleet-size threshold, further consolidation
began costing more network delay (and reducing parcels successfully delivered) than the VKT
reduction saved, even as driven distance kept falling. No corresponding emissions crossover was
found within the tested range (total emissions were worse than the least-consolidated fleet at every
consolidation level tested) — the delay and emissions crossovers need not coincide, and consolidation
should not be assumed a free win at any scale without locating its actual crossover point for the
specific network and fleet.

## Verified finding: off-peak delivery shifting can have a convex (not saturating) benefit curve, with a real noise counter-cost

Shifting a growing fraction of delivery tours into an off-peak/night window produced a **convex**
person-hours benefit curve in a verified sweep — a small shift bought disproportionately little
benefit, with most of the achievable gain appearing only once a large majority of tours had shifted,
and no saturation point found below full shifting — the opposite of the commonly-assumed
concave/saturating shape where early shifting captures most of the benefit. The counter-cost (night-
weighted residential noise exposure) was large enough to outweigh the daytime benefit entirely in
the tested scenario. **Report both the person-hours benefit and the noise counter-cost together**;
neither alone characterizes the policy tradeoff.

## Verified finding: aggressive freight bans can strand addresses through second-order network effects, not just direct edge bans

Under a blanket freight restriction, addresses not directly on a banned street can still become
unservable through two distinct second-order mechanisms worth separating: **no-path** (no legal
route exists to the address at all) and **trap** (a legal route exists *into* the address but none
*out*, e.g. because U-turns are disabled and the only legal continuation requires passing back
through a now-banned street). In a verified comparison, 30-61% of addresses not directly touched by
the ban still became unservable at 50-75% blanket-restriction coverage — a coverage percentage alone
does not predict this outcome; the actual network-topology consequence must be measured directly.

## Verified (and self-corrected) finding: a vClass-assignment gotcha can manufacture a fabricated non-monotone restriction finding

**This episode's own first draft fell into this exact trap and had to withdraw the finding after
independent review** — recorded here specifically because the failure mode is general and worth
guarding against in any future restriction-coverage sweep. A fleet-assignment heuristic that screens
each address's candidate vehicle class by **edge permission alone** (does the address's own street
allow this class?) rather than **round-trip route feasibility** (can this class actually complete a
depot-to-address-and-back trip through the whole network?) can badly misclassify service failures
under a *partial*, exempted restriction: an address on a still-legal-for-truck street can sit behind
a restriction-fragmented truck sub-network with no legal route in or out, while the exempt van class
routes there without difficulty — but a permission-only heuristic that never retries the exempt class
will report the address as unservable. Because a **complete** restriction forces every address onto
the exempt class immediately (no edge permits the non-exempt class anywhere), the bug cannot fire
there, making 100% coverage look anomalously *better* than 50-75% coverage — manufacturing exactly
the shape of a "partial restrictions are worse than complete restrictions" finding that is entirely a
demand-generator artifact, not a real network effect. **Fix: always retry every network-legal vClass
with an actual round-trip route-feasibility check before declaring an address unservable.** Any study
reporting a non-monotone service-vs-coverage curve should check this specific failure mode first —
and check whether its own verification tables already contain contradicting evidence (in this
episode's case, an independent `duarouter`-based reachability table had already shown 240/240 van
trips routing successfully on the same networks where the buggy generator reported failures — the
disagreement between two tables in the same report was the tell, and was not chased down until an
independent critic review).

## Practical takeaways

- Reconcile `parcels_by_design = parcels_delivered + parcels_undelivered` exactly in every arm as a
  standing validity check on any container-based freight study.
- Disclose which demand paradigm (tour vs. trip) was used when reporting freight impact metrics.
- Check actual per-vehicle-class emission factors before assuming a restriction's exposure/emissions
  tradeoff direction.
- Check for an escape lane before assuming a convex bay-deficit delay shape transfers between
  studies.
- Locate a consolidation policy's actual delay and emissions crossovers rather than assuming
  consolidation is monotonically beneficial.
- Before reporting a non-monotone restriction-coverage finding, verify the demand generator screens
  vehicle-class assignment by round-trip route feasibility, not edge permission alone — and
  cross-check against any independent reachability table already in the study.

See the `model-urban-freight-delivery-tours` skill for the full tour-generation methodology, the
container-semantics verification protocol, and the vClass-fallback fix.
