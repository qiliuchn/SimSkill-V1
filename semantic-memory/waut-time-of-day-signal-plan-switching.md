---
summary: SUMO's native WAUT (WAUT/wautJunction/wautSwitch additional-file elements) switches a traffic light between multiple fixed-time programs on an absolute time-of-day schedule; a scheduled switch is observable via traci.trafficlight.getProgram one second after its configured time (a deterministic step-update artifact, not drift), and verified time-of-day switching between three axis-skewed programs cut total waiting time 20.6% versus the best single fixed-time plan held all day under reversing demand.
keywords:
  - WAUT
  - time-of-day-signal-control
  - wautJunction
  - wautSwitch
  - signal-plan-switching
created: 2026-07-28T14:55:00
last_updated: 2026-08-07T01:30:23
sources:
  - "[[episodic-memory/2026-07-28_09-43-49/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-28_09-43-49/attempts/attempt-1/critic-agent-feedback.json]]"
  - https://sumo.dlr.de/docs/Simulation/Traffic_Lights.html
related_pages:
  - "[[actuated-traffic-signals]]"
  - "[[nema-dual-ring-controller]]"
  - "[[simulation-in-the-loop-ga-signal-optimization]]"
  - "[[coordinated-adaptive-signal-control-detector-bias-and-transition-cost]]"
related_skills:
  - switch-signal-plans-by-time-of-day-with-waut
  - optimize-signals-by-tlscycleadaptation
  - create-single-intersection
  - implement-scats-style-coordinated-adaptive-signal-control
related_skills_for_graph_view:
  - "[[switch-signal-plans-by-time-of-day-with-waut]]"
  - "[[optimize-signals-by-tlscycleadaptation]]"
  - "[[create-single-intersection]]"
  - "[[implement-scats-style-coordinated-adaptive-signal-control]]"
---

# WAUT Time-of-Day Signal Plan Switching

SUMO's **WAUT** mechanism (`<WAUT>`, `<wautJunction>`, `<wautSwitch>` additional-file elements) switches a traffic light between multiple pre-defined fixed-time `tlLogic` programs on an absolute schedule — the standard mechanism for modeling real-world time-of-day signal control (an AM-peak plan, a midday plan, a PM-peak plan), distinct from every other signal-control approach in memory, which runs one program (static, actuated, NEMA, or a live TraCI controller) for an entire simulation.

## Schema

```xml
<WAUT id="tod" refTime="0" startProg="A">
    <wautSwitch time="600"  to="B"/>
    <wautSwitch time="1200" to="C"/>
</WAUT>
<wautJunction wautID="tod" junctionID="center" procedure="Immediate"/>
```

`<WAUT>` names the switch schedule (`startProg` active from `refTime`, then a `<wautSwitch>` per subsequent absolute-time transition); `<wautJunction>` binds that schedule to a specific junction, whose `tlLogic` must define every referenced `programID`. `procedure="Immediate"` forces the switch at the exact scheduled time rather than waiting for the current program's cycle to complete.

## Verified: a deterministic +1 second observation lag at every switch

**A WAUT switch scheduled at time T is first observable via `traci.trafficlight.getProgram()` at T+1, not at T itself.** This was verified directly across two independent switch boundaries (t=600→601 and t=1200→1201): in both cases the program still read its pre-switch value at the exact configured instant, changing only one simulation step later. This is a deterministic artifact of SUMO's internal step-update order (the switch is enacted during the T→T+1 update, so a query issued exactly at T still sees the old state) — not drift, not a bug, and not something that compounds across multiple switches. Anyone verifying WAUT switch timing from a TraCI log should expect this fixed one-step offset rather than treating it as an inconsistency.

## Verified finding: time-of-day switching substantially beats any single fixed-time plan under reversing demand

On a single 4-arm signalized intersection under a demand pattern whose dominant direction reverses across three periods (heavy NS / balanced / heavy EW), a WAUT schedule switching between three programs each skewed toward its period's dominant axis cut total waiting time by **20.6%** relative to the best single fixed-time plan held for the entire simulation (a balanced-split program, itself optimal only for the middle period) — and a much larger margin relative to a plan mismatched to two of the three periods, which additionally suffered genuine queue spillback: a meaningful fraction of vehicles never even departed (visible as `inserted < loaded` in `summary.xml`), which understates that baseline's true delay if only its completed-vehicle waiting time is examined. This is a directly quantified case for real-world time-of-day signal plan switching over any single compromise plan.

See the `switch-signal-plans-by-time-of-day-with-waut` skill for the full network, program-derivation, and verification workflow.
