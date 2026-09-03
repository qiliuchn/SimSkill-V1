---
name: switch-signal-plans-by-time-of-day-with-waut
description: Use this skill when the user wants a SUMO traffic signal to switch between multiple distinct fixed-time programs on a time-of-day schedule (e.g. an AM-peak plan, a midday plan, and a PM-peak plan) — SUMO's native WAUT (Wochenendauswanderungsteuerung / time-of-day) mechanism — as opposed to a single static plan that runs unchanged for the whole simulation (tlsCycleAdaptation, tlsCoordinator) or a live adaptive controller (actuated, NEMA, max-pressure, GLOSA, TSP). Covers the native WAUT/wautJunction/wautSwitch XML schema, deriving multiple axis-skewed fixed-time programs for a reversing demand pattern, verifying switch timing via a TraCI getProgram log (including a real, deterministic +1s observation lag at each switch), and comparing time-of-day switching against every single-plan-all-day baseline. Trigger on mentions of WAUT, time-of-day signal plan, signal-plan switching, multiple traffic-light programs, or AM/PM peak signal timing.
related_skills:
  - optimize-signals-by-tlscycleadaptation
  - create-single-intersection
  - control-signals-with-actuated-tls
  - implement-maxpressure-traci-controller
related_skills_for_graph_view:
  - "[[optimize-signals-by-tlscycleadaptation]]"
  - "[[create-single-intersection]]"
  - "[[control-signals-with-actuated-tls]]"
  - "[[implement-maxpressure-traci-controller]]"
related_pages:
  - "[[waut-time-of-day-signal-plan-switching]]"
---

# Switch Signal Plans by Time of Day with WAUT

SUMO's native **WAUT** mechanism switches a traffic light's active `tlLogic` program on a schedule — the standard way to model real-world time-of-day signal-plan switching (an AM-peak plan, a midday plan, a PM-peak plan), as opposed to every other signal-control skill in memory, which runs a single program (fixed, actuated, NEMA, or a live TraCI controller) for the entire simulation.

## Defining multiple programs for one junction

Give the same junction ID multiple `<tlLogic>` blocks with distinct `programID`s, each with green splits skewed toward the demand pattern it's meant to serve — keep the cycle length identical across programs so WAUT can switch between them cleanly (see `scripts/example_programs.add.xml` for a worked 3-program example: NS-heavy, balanced, EW-heavy, all sharing an 84s cycle):

```xml
<tlLogic id="center" type="static" programID="A" offset="0">
    <phase duration="54" state="GGggrrrrGGggrrrr"/>
    <phase duration="3"  state="yyyyrrrryyyyrrrr"/>
    <phase duration="24" state="rrrrGGggrrrrGGgg"/>
    <phase duration="3"  state="rrrryyyyrrrryyyy"/>
</tlLogic>
<tlLogic id="center" type="static" programID="B" ...>...</tlLogic>
```

**Verify the programs are genuinely different, not cosmetic ID relabeling** — check the actual green-time splits differ meaningfully and are skewed toward each period's claimed dominant movement before trusting a comparison.

## The native WAUT schema

```xml
<additional>
    <WAUT id="tod" refTime="0" startProg="A">
        <wautSwitch time="600"  to="B"/>
        <wautSwitch time="1200" to="C"/>
    </WAUT>
    <wautJunction wautID="tod" junctionID="center" procedure="Immediate"/>
</additional>
```

- `<WAUT>` defines the switch schedule: `startProg` is the program active from `refTime`, and each `<wautSwitch>` names an absolute simulation time and the programID to switch to.
- `<wautJunction>` binds a WAUT schedule to a specific junction. `procedure="Immediate"` forces the program change at the exact scheduled time, with no cycle-alignment interpolation — use this unless you specifically want SUMO to wait for the current program's cycle to complete before switching.
- Verify this schema against your installed SUMO's own `additional_file.xsd` before assuming syntax — WAUT is a less commonly used SUMO feature and worth confirming empirically rather than guessing.

## Verifying switch timing: expect a deterministic +1s observation lag

Log the active program every simulation step via `traci.trafficlight.getProgram(junction_id)` to a CSV (see `scripts/run_all.py`). **A switch scheduled at time T is first externally observable via `getProgram` at T+1, not T** — SUMO enacts the switch during the T→T+1 step update. This is a fixed, deterministic one-step offset at every switch boundary, not drift — verified directly: switches configured at t=600 and t=1200 were logged at t=601 and t=1201 in both cases, with the program still reading its pre-switch value at the exact configured instant. Don't mistake this for a bug or inconsistent timing; it's a normal artifact of when TraCI polling happens relative to SUMO's internal update order.

## Comparison methodology: WAUT vs. every single-plan-all-day baseline

Run the WAUT-switched scenario alongside one baseline run per program, each holding that program fixed for the entire simulation via `traci.trafficlight.setProgram` at the start (not WAUT) — all on identical demand and network. Compare total/mean waiting time and mean travel time from tripinfo across all runs. **Check completed-vehicle counts too, not just waiting time** — a badly-mismatched fixed program under reversing demand can produce genuine queue spillback, with vehicles that never even depart (a lower `inserted` count than `loaded` in `summary.xml`) rather than merely higher delay; this makes that baseline's own waiting-time figure an understatement of how bad it really is, which should be called out explicitly rather than silently favoring the weakest baseline.

## Verified finding

On a single 4-arm intersection under a demand pattern that reverses its dominant direction across three periods (NS-heavy, balanced, EW-heavy), WAUT time-of-day switching between three axis-skewed programs cut total waiting time by **20.6%** relative to the best single fixed-time plan held all day (which itself was only optimal for the balanced middle period) — and far more relative to a plan mismatched to two of the three periods, which additionally suffered genuine queue spillback (vehicles failing to even depart). This is a directly quantified case for why real signal systems switch plans by time of day rather than running one compromise plan continuously.

## Gotchas

- **A switch scheduled at time T is observable at T+1 via `getProgram`, not exactly at T** — a deterministic one-step lag from SUMO's internal update order, not a configuration error.
- **Verify programs are genuinely distinct** — check the actual green-split numbers, don't just trust distinct `programID`s.
- **Use `procedure="Immediate"` for exact-time switching** — other procedures may wait for cycle completion, delaying the observed switch.
- **A mismatched fixed-time baseline can spill back and understate its own delay** — check `summary.xml`'s `inserted` vs `loaded` counts, not just waiting time, when a baseline looks surprisingly not-terrible.
- **Keep programs on a shared cycle length** for a clean, predictable switch (avoids leaving a partial phase mid-execution at the switch boundary).

## Related

- `optimize-signals-by-tlscycleadaptation` — Webster-style green-split derivation for a single demand period; run once per period to derive each of this skill's multiple programs.
- `create-single-intersection` — the standard network shape this skill's verified scenario uses.
- `control-signals-with-actuated-tls`, `implement-maxpressure-traci-controller` — the live-adaptive alternatives to time-of-day plan switching, useful contrast for choosing which control strategy fits a given demand pattern.
- [[waut-time-of-day-signal-plan-switching]] — the underlying WAUT mechanics, the verified switch-timing lag, and the quantified time-of-day-switching benefit.
