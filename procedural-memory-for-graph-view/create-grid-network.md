---
name: create-grid-network
description: Use this skill when the user wants to generate a grid (Manhattan-style) road network — rather than importing a real-world map. Covers the netgenerate command-line tool, particularly its grid mode (equally-spaced rows/columns of junctions forming a Manhattan-style network), for producing a .net.xml file usable by sumo, sumo-gui, or other SUMO applications. Trigger on mentions of netgenerate, grid network, Manhattan network, synthetic/abstract/toy SUMO network, or requests to quickly spin up a test network for simulation, RL training, or algorithm benchmarking.
---

# Create Grid Network (netgenerate)

Generates a synthetic grid-shaped road network using SUMO's `netgenerate` tool — useful for testing, benchmarking, RL environments, or algorithm prototyping when a real-world map isn't needed. Reference: https://sumo.dlr.de/docs/netgenerate.html

## Locating the binary

`netgenerate` ships alongside `sumo`/`sumo-gui` in the same `bin/` directory, but it is **not always on `$PATH`** even when `sumo` is (this is common on macOS framework installs, e.g. `/Library/Frameworks/EclipseSUMO.framework/Versions/<ver>/EclipseSUMO/bin/`). Resolve it robustly rather than assuming `netgenerate` is directly callable:

```bash
# 1. Try PATH directly
which netgenerate

# 2. Fall back to the same directory as `sumo`
dirname "$(which sumo)"        # netgenerate should be right next to it

# 3. Fall back to $SUMO_HOME/bin
echo "$SUMO_HOME"
```

`scripts/generate_grid.py` does this resolution automatically (PATH → next to `sumo` → `$SUMO_HOME/bin`) — prefer it over hand-rolling the lookup.

## Quick usage

```bash
python scripts/generate_grid.py -o grid.net.xml
python scripts/generate_grid.py -o grid.net.xml --x-number 5 --y-number 3 --x-length 200 --y-length 150 --lanes 2
python scripts/generate_grid.py -o grid.net.xml --tls-guess
python scripts/generate_grid.py -o grid.net.xml --extra "--seed 42" --extra "--no-turnarounds"
```

This wraps the netgenerate call:

```bash
netgenerate --grid -o grid.net.xml \
    --grid.x-number 5 --grid.y-number 5 \
    --grid.x-length 200 --grid.y-length 200 \
    --default.lanenumber 1 --default.speed 13.89
```

## Key grid options (from netgenerate docs)

| Option | Meaning | Default |
| --- | --- | --- |
| `--grid` | forces grid-network mode | — |
| `--grid.number` | junctions in both directions (square grid) | 5 |
| `--grid.x-number` / `--grid.y-number` | junctions per axis; each overrides `--grid.number` for that axis | 5 |
| `--grid.length` | street length in both directions | 100 |
| `--grid.x-length` / `--grid.y-length` | street length per axis; overrides `--grid.length` | 100 |
| `--grid.attach-length` | length of dangling streets attached at the outer boundary (0 = none); useful for giving border edges somewhere for traffic to originate/vanish | 0 |
| `--grid.x-attach-length` / `--grid.y-attach-length` | per-axis version of the above | 0 |

**Note the terminology:** `--grid.number` is the number of *junctions* per side, not the number of blocks — an `--grid.number 5` grid produces a 5×5 junction lattice (4×4 blocks).

## Other commonly-relevant options

These aren't grid-specific but shape the output network people usually want to set:

- `-L, --default.lanenumber <INT>` — lanes per edge (default 1)
- `-S, --default.speed <FLOAT>` — default speed limit in **m/s** (default 13.89 ≈ 50 km/h)
- `-j, --default-junction-type <STR>` — `traffic_light`, `priority`, `right_before_left`, `allway_stop`, etc.
- `--tls.guess <BOOL>` — auto-assign traffic lights at appropriate junctions rather than leaving them all priority-controlled
- `--tls.set <STR[]>` — explicit list of junction IDs to give traffic lights
- `--turn-lanes <INT>` / `--turn-lanes.length <FLOAT>` — dedicated left-turn lanes
- `--seed <INT>` — random seed, relevant if combined with `--random-lanenumber`, `--random-priority`, or `--perturb-x/y/z` for slight irregularity
- `-o, --output-file <FILE>` — output `.net.xml` path (this is the file `sumo`/TraCI will actually load)

Full option reference (spider/random modes, TLS phase timing, pedestrian/bike lanes, etc.) is at the link above — fetch it if the user needs something beyond grid generation.

## After generating the network

A `.net.xml` on its own has no traffic. To actually run a simulation, the user will also need:
- A routes file (`.rou.xml`) — either hand-written or generated with `randomTrips.py` (ships in `$SUMO_HOME/tools/`) or `od2trips`
- A `.sumocfg` tying the net + routes together

If the user's end goal is running/stepping the simulation via TraCI once the network exists, that's covered by the separate `run-simulation` skill.

## Gotchas

- `netgenerate` overwrites the output file silently if it already exists — warn the user or check first if that matters.
- Coordinates are normalized so the lower-left junction sits at (0,0) unless `--offset.x`/`--offset.y` or `--offset.disable-normalization` is given.
- A grid with `--tls.guess` off (the default) leaves every junction as `priority`-controlled (right-of-way by road priority), which is usually fine for uniform grids but means no signal timing exists to tune — pass `--tls-guess` or `-j traffic_light` if the user wants signalized intersections. **In practice, `--tls.guess` alone has been observed to leave 0 junctions signalized on a fully uniform grid** (its heuristic is built around irregular/real-world topologies where some junctions look more "important" than others — on a perfectly regular grid nothing stands out, so it guesses nothing). If every junction should end up with a traffic light, don't rely on `--tls.guess` for a uniform grid — pass `-j traffic_light` / `--default-junction-type traffic_light` directly, which forces it unconditionally.
- `--default.speed` is in **m/s**, not km/h or mph — a common source of "why is everyone driving so slow/fast" confusion.
