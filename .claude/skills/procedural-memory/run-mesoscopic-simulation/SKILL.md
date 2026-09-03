---
name: run-mesoscopic-simulation
description: Use this skill when the user wants to run SUMO in mesoscopic (queue-based) mode instead of the default microscopic (car-following) model — for large-scale/fast-turnaround runs — and/or wants to characterize the speed-vs-fidelity tradeoff between meso and micro on a given network. Covers the --mesosim flag, --meso-junction-control (whether signals are respected at all), --meso-multi-queue, --meso-tauff/--meso-taufj headway calibration, honest wall-clock speedup measurement, and where meso's output diverges from micro's (throughput vs. delay vs. route length). Trigger on mentions of mesoscopic simulation, meso, --mesosim, queue-based simulation, or simulation speedup/scaling.
---

# Run Mesoscopic Simulation

Runs SUMO in its mesoscopic mode — a queue-based model that trades car-following fidelity for a large runtime speedup — and characterizes exactly where its output diverges from the default microscopic model. This is SimSkill's only skill covering a different *simulation engine mode* rather than a different scenario or controller; every other `run-simulation`-based skill uses the default microscopic model implicitly.

## Enabling mesoscopic mode

```bash
sumo -n net.xml -r routes.rou.xml --mesosim \
    --meso-junction-control \
    --tripinfo-output tripinfo.xml --summary-output summary.xml
```

Key flags:
- `--mesosim` — switches the simulation engine to the queue-based mesoscopic model. Edges are internally split into segments (default ~98m; edges shorter than this don't subdivide) each modeled as a queue rather than individual car-following vehicles.
- `--meso-junction-control` — **without this, meso ignores traffic-light logic entirely.** On a signalized network, omitting it produces near-free-flow speeds and near-zero waiting/timeLoss regardless of actual signal timing — not a subtle inaccuracy, a categorically wrong result. Always set it when the network has traffic lights and delay/waiting metrics matter.
- `--meso-multi-queue` — allows multiple queues per segment (e.g. per turning movement) instead of one FIFO queue per segment. Its actual effect is scenario-dependent — verify it changes anything on the specific network rather than assuming it does (see Gotchas).
- `--meso-tauff` / `--meso-taufj` (and related `--meso-tau*` headway parameters) — tune the effective vehicle-following/junction headway the queue model uses. These are genuine calibration knobs: raising them increases modeled delay, letting meso's aggregate output track micro's more closely at some remaining accuracy cost.

## Measuring the speedup honestly

Wrap each `sumo` invocation in a wall-clock timer and keep the raw output — don't estimate the speedup:

```bash
{ time sumo -n net.xml -r routes.rou.xml --mesosim --meso-junction-control ... ; } 2> outputs/meso_jc/time.txt
```

Compare against an identical microscopic run (same network, same route file, same seed) timed the same way. `scripts/compare_micro_meso.py` parses each run's `tripinfo.xml`/`summary.xml`/`time.txt` and computes both the wall-clock and SUMO-internal-compute-time speedup factors alongside the metric comparison:

```bash
python scripts/compare_micro_meso.py \
    --baseline micro=outputs/micro \
    --run meso_default=outputs/meso_default --run meso_jc=outputs/meso_jc \
    --diff-pair meso_jc,meso_jc_multiqueue \
    --out-csv outputs/comparison.csv
```

The `--diff-pair` option reports per-vehicle duration divergence between two runs — the way to confirm whether a meso parameter (e.g. `--meso-multi-queue`) actually changed anything, rather than assuming it did from the flag alone.

## What tends to diverge, and by how much

Measured on a 6x6 signalized grid (36 traffic lights), identical demand and seed across all runs:

- **Speedup**: meso with junction control ran ~10x faster wall-clock than micro on this scenario; meso *without* junction control ran even faster (~13-18x) specifically because it skips signal logic entirely — which is also why its output is unusable on a signalized network (see above).
- **Throughput is exact** — arrival counts matched precisely between micro and every meso variant. Meso doesn't lose or gain vehicles; it changes how their trip metrics are computed.
- **Route length runs slightly short under meso** (~4-5% in one measurement) because meso skips internal junction edges that micro's car-following model traverses explicitly.
- **With junction control enabled, meso captures the *direction* of signal delay but systematically underestimates its *magnitude*** — mean duration, timeLoss, and especially waiting time all come out lower than micro's, sometimes substantially (waiting time was the least faithful metric in one measurement, off by over 70%). Meso's queue model doesn't reproduce stop-and-go holding the way micro's car-following does.
- **`--meso-tauff`/`--meso-taufj` genuinely narrow this gap** when raised — a real, effective calibration lever, at the cost of some of the runtime speedup's margin (though still far faster than micro).
- **`--meso-multi-queue` may have no measurable effect at all on a given network** — verified via a `--diff-pair` per-vehicle comparison showing zero vehicles differing between otherwise-identical runs. Don't assume a meso flag matters without checking.

## Recommendation

Use meso — always with `--meso-junction-control` on a signalized network — for fast large-scale throughput estimates, route-length-scale studies, and *relative* travel-time-trend comparisons across scenarios, where a systematic ~20-50% optimistic bias on absolute delay is acceptable or can be calibrated out via `tauff`/`taufj`. Don't use meso for absolute intersection waiting-time figures, queue-spillback studies, or signal-timing optimization work — those need the car-following fidelity only the microscopic model provides.

## Gotchas

- **`--` sequences are illegal inside XML comments in a `.sumocfg` file** — a comment like `<!-- run with --mesosim -->` breaks XML parsing (XML comments can't contain `--`); avoid embedding flag names with double-dashes in `.sumocfg` comments, or escape/reword them.
- **Meso without `--meso-junction-control` silently ignores signals** — this is the single most consequential flag omission; always verify it's set when the network has traffic lights and delay matters.
- **A meso flag's effect is not guaranteed** — verify with a per-vehicle diff (`--diff-pair`) before reporting that toggling it "changed" anything.
- **Verify edges actually subdivide under meso** — an edge shorter than meso's default segment length (~98m) doesn't split into multiple queue segments; very short-edge networks may not exercise meso's segment-level behavior meaningfully.

## Related

- `run-simulation` — the general command-line-vs-TraCI running pattern this skill specializes for the meso-vs-micro engine choice.
- `analyze-simulation-outputs` — general tripinfo/summary comparison; this skill's `compare_micro_meso.py` extends it with wall-clock speedup and per-vehicle divergence checks.
- `create-grid-network`, `generate-random-trips`, `convert-trips-to-routes` — for building the shared network/demand any micro-vs-meso comparison needs to hold identical across runs.
- [[mesoscopic-simulation]] — the underlying SUMO concepts (queue-based segment model, flag semantics, and the verified speedup/fidelity-divergence findings).
