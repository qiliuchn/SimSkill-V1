---
name: create-spider-network
description: Use this skill when the user wants to generate an abstract/synthetic SUMO road network shaped as a spider/radial web — concentric circles connected by radiating arms around a central junction — rather than importing a real-world map. Covers the netgenerate command-line tool's spider mode for producing a .net.xml file usable by sumo, sumo-gui, or other SUMO applications. Trigger on mentions of netgenerate, spider network, radial network, web network, star/hub-and-spoke SUMO network, or requests for a synthetic network with a central intersection and radiating arms (e.g. for studying congestion converging toward a CBD-like center).
---

# Create Spider Network (netgenerate)

Generates a synthetic spider-web-shaped road network using SUMO's `netgenerate` tool: radiating "arms" crossed by concentric "circles" around a central junction. Useful for radial/hub-and-spoke traffic studies (e.g. congestion converging toward a center, evacuation modeling, or any scenario where a real map's layout doesn't matter but a non-grid topology does). Reference: https://sumo.dlr.de/docs/netgenerate.html

## Locating the binary

`netgenerate` ships alongside `sumo`/`sumo-gui` in the same `bin/` directory, but it is **not always on `$PATH`** even when `sumo` is (this is common on macOS framework installs, e.g. `/Library/Frameworks/EclipseSUMO.framework/Versions/<ver>/EclipseSUMO/bin/`). Resolve it robustly:

```bash
# 1. Try PATH directly
which netgenerate

# 2. Fall back to the same directory as `sumo`
dirname "$(which sumo)"

# 3. Fall back to $SUMO_HOME/bin
echo "$SUMO_HOME"
```

`scripts/generate_spider.py` does this resolution automatically (PATH → next to `sumo` → `$SUMO_HOME/bin`) — prefer it over hand-rolling the lookup.

## Quick usage

```bash
python scripts/generate_spider.py -o spider.net.xml
python scripts/generate_spider.py -o spider.net.xml --arm-number 10 --circle-number 3 --space-radius 150
python scripts/generate_spider.py -o spider.net.xml --omit-center --tls-guess
python scripts/generate_spider.py -o spider.net.xml --extra "--seed 42" --extra "--no-turnarounds"
```

This wraps the netgenerate call:

```bash
netgenerate --spider -o spider.net.xml \
    --spider.arm-number 8 --spider.circle-number 4 \
    --spider.space-radius 100
```

## Key spider options (from netgenerate docs)

| Option | Meaning | Default |
| --- | --- | --- |
| `--spider` | forces spider-network mode | — |
| `--spider.arm-number` | number of radiating axes ("spokes") in the net | 7 |
| `--spider.circle-number` | number of concentric circles crossing the arms | 5 |
| `--spider.space-radius` | radial distance between consecutive circles | 100 |
| `--spider.omit-center` | drop the central junction (arms don't converge to a single hub) | false |
| `--spider.attach-length` | length of dangling streets attached at the outer boundary (0 = none); gives the outermost ring somewhere for traffic to originate/vanish | 0 |

**Shape intuition:** `arm-number` controls how many spokes radiate outward (angular resolution), `circle-number` controls how many rings cross them (radial resolution), and `space-radius` controls how far apart those rings are — so total extent ≈ `circle-number × space-radius`.

## Other commonly-relevant options

Not spider-specific, but shape the output network people usually want to set:

- `-L, --default.lanenumber <INT>` — lanes per edge (default 1)
- `-S, --default.speed <FLOAT>` — default speed limit in **m/s** (default 13.89 ≈ 50 km/h)
- `-j, --default-junction-type <STR>` — `traffic_light`, `priority`, `right_before_left`, `allway_stop`, etc.
- `--tls.guess <BOOL>` — auto-assign traffic lights at appropriate junctions
- `--tls.set <STR[]>` — explicit list of junction IDs to signalize (e.g. just the center)
- `--turn-lanes <INT>` / `--turn-lanes.length <FLOAT>` — dedicated left-turn lanes
- `--seed <INT>` — random seed, relevant with `--random-lanenumber`, `--random-priority`, or `--perturb-x/y/z`
- `-o, --output-file <FILE>` — output `.net.xml` path (this is what `sumo`/TraCI actually loads)

Full option reference (grid/random modes, TLS phase timing, pedestrian/bike lanes, etc.) is at the link above — fetch it if the user needs something beyond spider generation.

## After generating the network

A `.net.xml` on its own has no traffic. To run a simulation, the user will also need:
- A routes file (`.rou.xml`) — hand-written, or generated with `randomTrips.py` (ships in `$SUMO_HOME/tools/`) or `od2trips`. For a spider network, radial-to-center or circle-to-circle trip patterns are a natural fit for studying convergent congestion.
- A `.sumocfg` tying the net + routes together

If the user's end goal is running/stepping the simulation via TraCI once the network exists, that's covered by the separate `run-simulation` skill. For a grid instead of a spider, see the `create-grid-network` skill.

## Gotchas

- `netgenerate` overwrites the output file silently if it already exists — warn the user or check first if that matters.
- The central junction (unless `--spider.omit-center` is set) is where every arm meets — with a high `arm-number` this becomes a many-legged intersection, which SUMO can build but which is unrealistic and may need `--junctions.corner-detail` or a wider `--default.junctions.radius` to render cleanly.
- Coordinates are normalized so the lower-left point sits at (0,0) unless `--offset.x`/`--offset.y` or `--offset.disable-normalization` is given — the "center" junction is not necessarily at (0,0) in the output file.
- `--default.speed` is in **m/s**, not km/h or mph.
