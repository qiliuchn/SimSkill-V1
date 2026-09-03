---
summary: SUMO's mesoscopic mode (--mesosim) replaces car-following with a queue-based segment model, running roughly an order of magnitude faster than microscopic simulation but requiring --meso-junction-control to respect signals at all, and even then systematically underestimating signal delay unless calibrated via --meso-tauff/--meso-taufj.
keywords:
  - mesoscopic-simulation
  - mesosim
  - queue-based-model
  - meso-junction-control
  - meso-tauff
  - simulation-speedup
created: 2026-07-24T21:55:00
last_updated: 2026-08-06T21:24:14
sources:
  - "[[episodic-memory/2026-07-24_21-36-24/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-24_21-36-24/attempts/attempt-1/critic-agent-feedback.json]]"
  - https://sumo.dlr.de/docs/Simulation/Meso.html
related_pages:
  - "[[sumo-command-line]]"
  - "[[sumo-output-files]]"
  - "[[actuated-traffic-signals]]"
  - "[[state-serialization-and-rolling-horizon-traffic-forecasting]]"
  - "[[multi-resolution-modeling-buffer-sizing-and-boundary-handoff]]"
related_skills:
  - run-mesoscopic-simulation
  - run-simulation
  - analyze-simulation-outputs
  - create-grid-network
  - build-rolling-horizon-traffic-forecast-with-state-warm-start
  - extract-subnetwork-scenario-with-boundary-demand
related_skills_for_graph_view:
  - "[[run-mesoscopic-simulation]]"
  - "[[run-simulation]]"
  - "[[analyze-simulation-outputs]]"
  - "[[create-grid-network]]"
  - "[[build-rolling-horizon-traffic-forecast-with-state-warm-start]]"
  - "[[extract-subnetwork-scenario-with-boundary-demand]]"
---

# Mesoscopic Simulation

SUMO's default simulation model is microscopic — individual car-following, lane-changing, and signal-response dynamics per vehicle per timestep. `--mesosim` switches to a **mesoscopic**, queue-based model instead: edges are internally subdivided into segments (default ~98m; shorter edges don't subdivide), each modeled as a queue with aggregate flow dynamics rather than individually-simulated car-following vehicles. This trades fidelity for a substantial runtime speedup, making it a genuinely different engine mode rather than a scenario or controller choice — the only such mode-level distinction in SimSkill's simulation-run coverage.

## Key flags

- `--mesosim` — enables the queue-based model.
- `--meso-junction-control` — **without this, meso ignores traffic-light logic entirely**, not approximately but categorically: on a signalized network, a bare `--mesosim` run produces near-free-flow speeds and near-zero waiting/timeLoss regardless of the actual signal plan. This is the single most consequential flag to get right; always set it when the network has traffic lights and delay metrics matter.
- `--meso-multi-queue` — allows multiple queues per segment (e.g. per turning movement). Its effect is scenario-dependent, not guaranteed — measured on one 36-signal grid, it produced *zero* measurable per-vehicle difference versus the same run without it (verified via a per-vehicle duration diff, not just the flag's presence). Don't assume a meso parameter changed anything without checking.
- `--meso-tauff` / `--meso-taufj` (and related `--meso-tau*` parameters) — tune the effective following/junction headway the queue model applies. These are genuine, effective calibration knobs: raising them increases modeled delay and narrows the gap to microscopic results, at some cost to the remaining speed advantage.

## Measured speedup

On a 6x6 signalized grid (36 traffic lights) with identical demand and seed: mesoscopic simulation with junction control ran roughly **10x faster wall-clock** than the microscopic baseline; without junction control it ran even faster (~13-18x), specifically because skipping signal logic is itself computationally cheap — the same reason its output is invalid on a signalized network. Always measure the speedup honestly via real wall-clock timing (wrap the `sumo` invocation, e.g. with `time`) rather than assuming a documented or expected factor; the exact speedup is scenario- and hardware-dependent.

## Where meso's output diverges from micro's

- **Throughput is exact.** Vehicle arrival counts matched precisely between microscopic and every mesoscopic variant tested — meso doesn't lose or gain vehicles, it changes how their trip metrics are computed.
- **Route length runs slightly short** (on the order of a few percent in one measurement) because meso skips internal junction edges that micro's car-following model traverses explicitly as separate segments.
- **With junction control enabled, meso captures the *direction* of signal delay but systematically underestimates its *magnitude*.** Mean trip duration, timeLoss, and especially mean waiting time all come out lower than microscopic simulation's — waiting time was the least faithful metric in one measurement (off by over 70%), since meso's queue model doesn't reproduce the stop-and-go holding pattern micro's car-following does.
- **`--meso-tauff`/`--meso-taufj` calibration genuinely narrows this gap** when the headway parameters are raised, trading away some of the speed advantage for closer fidelity to microscopic results.

## Recommendation

Use mesoscopic simulation — always with `--meso-junction-control` on any signalized network — for fast large-scale throughput estimates, route-length-scale studies, and *relative* travel-time-trend comparisons across scenarios, where a systematic optimistic bias on absolute delay (roughly 20-50% in the measured case, improvable via `tauff`/`taufj` calibration) is acceptable. Don't use it for absolute intersection waiting-time figures, queue-spillback studies, or signal-timing optimization work — those require the car-following fidelity only microscopic simulation provides.

**The optimistic-bias direction above is not universal.** On an uncontrolled freeway corridor (no signals to smooth over), a rolling-horizon forecasting comparison found mesoscopic mode ran systematically *pessimistic* instead — negative accuracy skill scores throughout, the opposite sign from this page's signalized-grid finding ([[state-serialization-and-rolling-horizon-traffic-forecasting]]). Check the bias direction per facility type and control regime rather than assuming it generalizes from a signalized-network result.

## Gotchas

- **`--` sequences are illegal inside XML comments in a `.sumocfg` file** — a comment referencing a flag like `--mesosim` breaks XML parsing (XML comments cannot contain `--` anywhere in their body), a real, encountered pitfall when authoring config files that document their own meso flags.
- **Verify a meso parameter's effect before reporting it as significant** — the flag being set doesn't guarantee a measurable difference; check with a per-vehicle comparison against an otherwise-identical run.

See the `run-mesoscopic-simulation` skill for the full comparison workflow and bundled scripts.
