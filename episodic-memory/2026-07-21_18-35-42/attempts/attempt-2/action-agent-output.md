---
task: "Generate a 3x3 road network. The central east-west and north-south corridors should each consist of six lanes (three lanes per direction), while all other roads should consist of four lanes (two lanes per direction). At every intersection, provide one additional approach lane on each incoming leg for channelization. Generate one-hour morning peak traffic demand. Assume that the central business district (CBD) is located to the northeast of the network. Create two traffic demand scenarios, representing weekday and weekend conditions. Equip all intersections with traffic signals. Using Webster's method, optimize the signal timing plans for each demand scenario, including phase design and signal timing parameters."
success: true
---

## Method
Per `critic-agent`'s feedback on attempt 1, extended `create-grid-network`'s own generator to accept per-corridor lane overrides and rebuild through `netconvert` properly, instead of post-editing generated XML. CBD-directed demand used `generate-random-trips --fringe-factor` biased toward the northeast corner. Weekday and weekend demand were generated as two independent sets at different volumes — signal timing is demand-dependent, so each scenario needed its own `optimize-signals-by-tlscycleadaptation` pass rather than sharing one plan.

## Scripts
- `scripts/build_asymmetric_grid.py` — builds the 3×3 grid with central corridors at 3 lanes/direction, other roads at 2, plus one channelization lane per incoming approach; regenerates via `netconvert` (no post-editing).
- `scripts/generate_demand_weekday.py` — weekday AM-peak demand via `generate-random-trips --fringe-factor`, biased northeast.
- `scripts/generate_demand_weekend.py` — same, lower weekend volume.
- `scripts/optimize_signals.sh` — runs `optimize-signals-by-tlscycleadaptation` once per scenario.

## How to Reproduce
```bash
python3 scripts/build_asymmetric_grid.py --out ../../../outputs/network.net.xml
python3 scripts/generate_demand_weekday.py --net ../../../outputs/network.net.xml --out ../../../outputs/weekday_trips.rou.xml
python3 scripts/generate_demand_weekend.py --net ../../../outputs/network.net.xml --out ../../../outputs/weekend_trips.rou.xml
bash scripts/optimize_signals.sh --net ../../../outputs/network.net.xml --routes ../../../outputs/weekday_trips.rou.xml --out ../../../outputs/weekday_signals.add.xml
bash scripts/optimize_signals.sh --net ../../../outputs/network.net.xml --routes ../../../outputs/weekend_trips.rou.xml --out ../../../outputs/weekend_signals.add.xml
sumo -n ../../../outputs/network.net.xml -r ../../../outputs/weekday_trips.rou.xml -a ../../../outputs/weekday_signals.add.xml --tripinfo-output ../../../outputs/weekday_tripinfo.xml
sumo -n ../../../outputs/network.net.xml -r ../../../outputs/weekend_trips.rou.xml -a ../../../outputs/weekend_signals.add.xml --tripinfo-output ../../../outputs/weekend_tripinfo.xml
```

## Results
*(Illustrative numbers — this example folder is a format-demonstration, not a real run.)*

Both scenarios ran cleanly, zero collisions, zero teleports. Webster-optimized cycle length: 92 s weekday, 78 s weekend (shorter cycle reflects lighter weekend demand).

| Metric | Weekday | Weekend |
|---|---|---|
| Vehicles inserted | 2,400 | 1,050 |
| Trips completed | 2,371 (98.8%) | 1,048 (99.8%) |
| Mean travel time | 312 s | 198 s |
| Mean wait time | 41 s | 12 s |

Full per-vehicle detail: `outputs/weekday_tripinfo.xml`, `outputs/weekend_tripinfo.xml`.

## Failures & Retries
Attempt 1 widened the central corridors by hand-editing `network.net.xml` after generation, without re-running `netconvert` — `critic-agent` caught that this leaves lane/connection/junction geometry inconsistent with the declared lane count, producing a network `netconvert` would reject on re-validation. This attempt fixed it by extending the generator itself to emit correct per-corridor lane counts from the start, rebuilding through `netconvert` properly rather than patching its output.
