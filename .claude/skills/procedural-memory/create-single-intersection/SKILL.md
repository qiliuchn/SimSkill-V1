---
name: create-single-intersection
description: Use this skill when the user wants a minimal SUMO network with exactly one intersection (a single junction with N approach arms — typically a 4-way cross or 3-way T) rather than a grid, spider, or real-world map. This is the standard network shape for isolated signal-timing research — fixed-time, actuated, or RL-based traffic signal control algorithms (e.g. Webster's method, max-pressure, LLMLight/MPLight-style single-agent control). Trigger on mentions of a single intersection, isolated intersection, 4-way/3-way intersection network, one-junction SUMO network, or per-arm/per-approach control over lanes, length, or speed at one intersection.
---

# Create Single Intersection

Builds a SUMO network containing exactly one junction with a configurable number of approach arms, where **every arm can be tuned independently** (length, incoming lanes, outgoing lanes, speed). This is the standard test bed for single-point signal-timing algorithms, where a real map or a multi-junction network would just add confounds.

## Why netconvert + plain XML instead of netgenerate

`netgenerate` (used by the `create-grid-network` and `create-spider-network` skills) cannot produce a clean isolated single junction with independently configurable arms — its grid/spider modes always produce multiple junctions, and all arms/streets in a given axis share the same length and lane count.

To get real per-arm control, this skill instead writes SUMO's **plain-XML** node and edge definitions (`.nod.xml`, `.edg.xml`) directly and compiles them with **`netconvert`** — the same tool used underneath `netgenerate`, but driven from explicit node/edge specs. This is more verbose but gives full control, which is the whole point here. Reference: https://sumo.dlr.de/docs/Networks/PlainXML.html

## Locating the binary

`netconvert` ships next to `sumo`/`sumo-gui`/`netgenerate`, and has the same PATH quirk (not always linked even when `sumo` is, e.g. on macOS framework installs like `/Library/Frameworks/EclipseSUMO.framework/Versions/<ver>/EclipseSUMO/bin/`). `scripts/generate_intersection.py` resolves it automatically: `$PATH` → same directory as `sumo` → `$SUMO_HOME/bin`.

## Quick usage

**Uniform 4-way intersection** (all arms identical):
```bash
python scripts/generate_intersection.py -o intersection.net.xml \
    --arms 4 --arm-length 250 --lanes-in 2 --lanes-out 2 --speed 13.89
```

**3-way T-junction:**
```bash
python scripts/generate_intersection.py -o t_junction.net.xml --arms 3 --arm-length 200
```

**Asymmetric intersection** (major road N-S with more lanes, minor road E-W) via a JSON config — this is the fine-grained path:
```bash
python scripts/generate_intersection.py -o intersection.net.xml --config arms.json
```
```json
[
  {"name": "N", "length": 300, "lanes_in": 3, "lanes_out": 3, "speed": 16.67},
  {"name": "S", "length": 300, "lanes_in": 3, "lanes_out": 3, "speed": 16.67},
  {"name": "E", "length": 150, "lanes_in": 2, "lanes_out": 2, "speed": 11.11},
  {"name": "W", "length": 150, "lanes_in": 2, "lanes_out": 2, "speed": 11.11}
]
```
Any field left out of an arm falls back to the script's `--lanes-in`/`--lanes-out`/`--speed`/`--arm-length` defaults, so a config can override just the arms that need to differ.

Recognized compass names (`N`, `NE`, `E`, `SE`, `S`, `SW`, `W`, `NW`, case-insensitive) are placed at their real compass angle regardless of their order in the JSON list — so listing arms as `N, S, E, W` still puts `S` opposite `N`, not adjacent to it. Non-compass names (e.g. `"major_in"`) fall back to even angular spacing in list order, or set an explicit `"angle"` field (degrees, 0 = north, clockwise) to place any arm precisely.

## Script options

| Flag | Meaning | Default |
| --- | --- | --- |
| `-o, --output` | output `.net.xml` path | `intersection.net.xml` |
| `--arms` | number of arms for a uniform intersection (ignored if `--config` given) | 4 |
| `--arm-length` | distance from center junction to each arm's outer (fringe) node, in meters | 200 |
| `--lanes-in` | lanes on each incoming approach (toward the junction) | 1 |
| `--lanes-out` | lanes on each outgoing departure (away from the junction) | 1 |
| `--speed` | default speed limit in **m/s** | 13.89 (≈50 km/h) |
| `--config <FILE>` | JSON file with a list of per-arm overrides (see above); takes precedence over `--arms` | — |
| `--junction-type` | center junction control type: `traffic_light`, `priority`, `right_before_left`, `allway_stop` | `traffic_light` |
| `--turn-lanes <INT>` | add INT dedicated left-turn lane(s) at the junction (passed to netconvert) | 0 |
| `--keep-plain` | keep the intermediate `.nod.xml`/`.edg.xml` files next to the output instead of discarding them | off |
| `--dry-run` | print the generated node/edge XML and the netconvert command without running it | off |

Arms are placed evenly around the center starting from north (12 o'clock) and going clockwise, so with `--arms 4` and no config the default names are `N, E, S, W`; with `--arms 3` they become `N, SE, SW` (evenly spaced, still starting from north). Custom names come from the `name` field in a `--config` file.

## What each arm becomes in the network

Each arm produces **two directed edges** between the center junction and that arm's fringe node:
- `in_<name>` — fringe → center, with `lanes_in` lanes (the approach the signal-timing algorithm actually controls queuing on)
- `out_<name>` — center → fringe, with `lanes_out` lanes (the departure)

This mirrors how real intersection approaches are typically modeled: incoming and outgoing directions are independent edges, so asymmetric lane counts (common on real minor/major road approaches) are natural.

## After generating the network

A bare intersection has no traffic or detectors. Typical next steps for signal-timing work:
- **Routes**: hand-write turning-movement flows/routes through `in_<name>` → `out_<name>` pairs (skip the U-turn pair unless intended), or use `randomTrips.py`/`jtrrouter` for stochastic demand.
- **Detectors**: signal-timing algorithms (actuated control, max-pressure, RL state) usually need induction loops — add `<e1Detector>`/`<e2Detector>` via an additional file once the network exists; not generated by this skill.
- **TraCI control loop**: once the network + routes + detectors exist, the `run-simulation` skill covers stepping the simulation and reading/writing `traci.trafficlight.*` state.

## Gotchas

- `--speed` is in **m/s**, not km/h/mph.
- If `--junction-type traffic_light` (the default) and the user's algorithm wants to define its own signal phases rather than netconvert's auto-generated default program, the generated `.net.xml` will still contain a default program — the user will need to either overwrite it via an additional `tlLogic` file passed to `sumo`, or set the program via `traci.trafficlight.setProgram`/`setRedYellowGreenState` at runtime.
- A 2-arm "intersection" is really just a straight road with a junction in the middle, not a meaningful signal-control scenario — `--arms` below 3 is technically allowed by the script but almost certainly not what's wanted.
- netconvert overwrites the output file silently if it already exists.

## Related

- `design-signal-change-and-clearance-intervals` — builds a parameterized 4-approach network on this skill's foundation (with approach speed, grade, and heavy-vehicle share swept independently) to study yellow/all-red interval design and the classical dilemma zone.
