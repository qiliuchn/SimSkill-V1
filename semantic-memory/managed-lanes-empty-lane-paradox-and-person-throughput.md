---
summary: A controlled SUMO comparison of freeway managed-lane policies (static HOV, fixed-toll HOT, ALINEA-style dynamic-toll HOT) found a static HOV lane makes both corridor person-throughput and person-hours-traveled worse below a carpool-share threshold around 52-57% (the "empty lane paradox"), that the vehicle- and person-throughput-optimal toll can both sit at the price floor because the lane's own capacity constraint means it is never oversold (while the revenue-optimal toll sits far higher, at real throughput cost), that gated access strongly concentrates lane-changing at designated gates without a measurable performance or safety benefit, and that converting HOV to performance-priced HOT improves every value-of-time quartile's outcome roughly proportionally rather than being regressive.
keywords:
  - managed-lanes
  - hov-lane
  - hot-lane
  - express-lane
  - congestion-pricing
  - person-throughput
  - empty-lane-paradox
  - value-of-time
created: 2026-08-02T15:30:00
last_updated: 2026-08-04T17:30:00
sources:
  - "[[episodic-memory/2026-08-02_15-00-00/outputs/FINDINGS.md]]"
  - "[[episodic-memory/2026-08-02_15-00-00/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[cordon-tolling-and-e3-detectors]]"
  - "[[ramp-metering-with-alinea]]"
  - "[[vehicle-class-lane-permissions]]"
  - "[[dynamic-hard-shoulder-running-with-traci-lane-permissions]]"
  - "[[cruising-for-parking-search-externality-and-remedies]]"
  - "[[toll-plaza-queueing-and-the-service-headway-floor]]"
related_skills:
  - model-managed-lanes-with-dynamic-tolling-and-self-selection
  - model-cordon-tolling-with-generalized-cost-surcharge
  - implement-alinea-ramp-metering
  - implement-dynamic-hard-shoulder-running
  - model-freeway-weaving-segment
  - model-cruising-for-parking-search-externality
related_skills_for_graph_view:
  - "[[model-managed-lanes-with-dynamic-tolling-and-self-selection]]"
  - "[[model-cordon-tolling-with-generalized-cost-surcharge]]"
  - "[[implement-alinea-ramp-metering]]"
  - "[[implement-dynamic-hard-shoulder-running]]"
  - "[[model-freeway-weaving-segment]]"
  - "[[model-cruising-for-parking-search-externality]]"
---

# Managed Lanes: Empty-Lane Paradox and Person-Throughput

Freeway managed lanes (HOV, HOT, express lanes) restrict a lane to high-occupancy or
toll-paying vehicles. This page concerns whether such a lane actually moves more
*people* — the metric that matters for a policy justified on congestion relief — as
opposed to merely restricting a lane to fewer *vehicles*, and what pricing and access
design maximize person-throughput specifically.

## Verified finding: the empty-lane paradox is real, with a quantified dual threshold

A static HOV-only lane (compared against an all-general-purpose baseline on
identical demand) was found to make **both** corridor person-throughput lower **and**
total person-hours-traveled higher below a carpool-share threshold measured at
roughly 52-57% (varying with total demand level relative to corridor capacity) — a
genuinely counter-intuitive result, since dedicating capacity to carpools is usually
assumed to help, not hurt, aggregate outcomes. The mechanism: at low carpool share,
removing a lane's worth of capacity from the general-purpose lanes (which carry the
large majority of person-trips) costs more in general-purpose congestion than the
mostly-empty managed lane gains back.

**Throughput and delay do not necessarily cross the same threshold together.**
Sweeping a fixed carpool share across demand levels found a case where the HOV lane
cost essentially zero measurable person-throughput but still cost a substantial
increase in person-hours-traveled — a result that would be missed entirely if only
one of the two metrics were checked. Report both person-throughput and person-hours
(or an equivalent delay measure) as independent findings, not a single combined
verdict.

## Verified finding: the throughput-optimal toll and the revenue-optimal toll can diverge sharply — because the lane can't be oversold

Sweeping a static toll level to separately locate the toll that maximizes
managed-lane vehicle throughput, the toll that maximizes corridor person-throughput,
and the toll that maximizes toll revenue found that, in one tested corridor
configuration, **both throughput optima sat at the price floor ($0 toll)** — a
non-obvious negative result, well-supported by the underlying variance rather than an
artifact of insufficient testing. The mechanism, independently confirmed with a
capacity probe pushing demand to well over double the tested range: the managed
lane's own physical capacity saturated at a relatively low fraction of the general-
purpose lanes' capacity, meaning the lane was never actually at risk of being
oversold under any policy-relevant demand level tested — a toll in that regime can
only ever *subtract* flow, never optimize a genuine congestion tradeoff, since there
is no congestion on the managed lane itself to price away. **The revenue-maximizing
toll, by contrast, sat dramatically higher** (in one tested case, tens of times the
throughput-optimal price) and operating there cost real, measurable throughput and
delay — a clear demonstration that a managed-lane operator optimizing for revenue and
one optimizing for person-throughput are not pursuing the same objective, and can
reach opposite pricing conclusions from the identical demand and infrastructure.

**Don't assume a managed lane's throughput-vs-toll relationship is automatically
meaningful without first checking whether the lane can actually saturate** under the
demand levels being tested — a null or floor-seeking result may reflect the lane's
own capacity headroom rather than a genuine absence of a throughput-toll tradeoff.

## Verified finding: gated access concentrates weaving but does not automatically improve performance or safety

Comparing continuous managed-lane access (lane changes permitted anywhere along the
lane) against limited access with designated ingress/egress gates found gating
strongly and measurably concentrates lane-changing activity at the gates (in one
tested case, the share of managed-lane-adjacent lane changes occurring inside
designated gate zones rose from roughly 30-50% to roughly 80%, with total corridor
lane-change count falling by a double-digit percentage) — a clean confirmation that
gating does what it's designed to do structurally. **But this weaving-localization
effect did not translate into a measurable improvement in corridor throughput,
person-hours, or a surrogate-safety-measure conflict rate** in the same test — all
three showed no statistically significant difference between gated and continuous
access. **A design change that visibly and significantly alters where weaving happens
does not automatically alter whether it matters for the outcomes usually cited to
justify it** — report weaving-localization and performance/safety effects as
separate, independently-tested claims, and be willing to report a genuine null result
on the performance side even when the structural effect is unambiguous.

## Verified finding: converting HOV to performance-priced HOT benefits every income/value-of-time quartile roughly proportionally

Breaking outcomes down by value-of-time (VOT) quartile found that converting a static
HOV-only lane to a dynamically-priced HOT lane improved generalized cost for
**every** VOT quartile by a comparable proportional amount (in one tested case,
roughly 28-29% across all four quartiles), including the lowest-VOT quartile, which
overwhelmingly does *not* buy into the priced lane (single-digit-percent take rate)
but still benefits substantially because paying vehicles leaving the general-purpose
lanes measurably raises general-purpose speed. **The absolute-dollar burden gap
between the highest and lowest VOT quartiles looked regressive when reported only in
dollar terms, but this was almost entirely an artifact of higher-VOT travelers simply
valuing the identical time savings more highly in dollar terms — the proportional
burden (as a fraction of each quartile's own generalized cost) was flat within a few
percentage points across all quartiles.** Report both the absolute-dollar and
proportional framings of a pricing-equity claim explicitly; defaulting to only the
dollar framing can produce a misleadingly regressive-looking headline for a policy
that is, in relative terms, close to distributionally neutral.

## Practical takeaways

- Always report person-throughput (occupancy-weighted), not just vehicle-throughput,
  for a managed-lane policy comparison — the two can point in opposite directions.
- Test for the empty-lane paradox explicitly by sweeping carpool share and demand
  level, and check throughput and delay as separate metrics since they can cross
  different thresholds.
- Before drawing conclusions from a toll-level sweep, verify with a capacity probe
  whether the managed lane can actually saturate under tested demand — a
  floor-seeking throughput optimum may reflect capacity headroom, not toll
  irrelevance.
- Locate the revenue-maximizing toll separately from the throughput-maximizing toll —
  they are not the same objective and can diverge sharply.
- Test weaving-localization and downstream performance/safety effects of an
  access-design change (gated vs. continuous) as independent claims — one can hold
  without the other.
- Report a pricing-equity finding in both absolute-dollar and proportional terms —
  the two framings can tell very different stories about the same underlying result.

See `model-managed-lanes-with-dynamic-tolling-and-self-selection` for the full
managed-lane construction, self-selection-controller, dynamic-tolling, and
access-design methodology. The VOT-based self-selection pattern here transfers directly to curb-vs-garage parking choice in [[cruising-for-parking-search-externality-and-remedies]], which reaches the **opposite** equity conclusion for its domain — curb performance-pricing there was found regressive by value-of-time quartile, not roughly-proportional as this page's HOV-to-HOT conversion was — a useful contrast when generalizing either equity finding to a new pricing scenario without re-checking it.
