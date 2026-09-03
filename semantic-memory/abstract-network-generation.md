---
summary: netgenerate builds synthetic grid, spider, and random road networks for SUMO without importing a real map, controlled by axis-specific junction counts/spacing, arm/circle counts, or randomization parameters.
keywords:
  - netgenerate
  - grid-network
  - spider-network
  - random-network
  - synthetic-network
created: 2026-07-21T14:00:00
last_updated: 2026-07-23T19:28:51
sources:
  - "[[raw-materials/netgenerate - SUMO Documentation.md]]"
  - https://sumo.dlr.de/docs/netgenerate.html
  - "[[raw-materials/Abstract Network Generation.md]]"
  - https://sumo.dlr.de/docs/Networks/Abstract_Network_Generation.html
related_pages:
  - "[[sumo-command-line]]"
  - "[[openstreetmap]]"
  - "[[random-trips]]"
  - "[[ramp-metering-with-alinea]]"
related_skills:
  - create-grid-network
  - create-spider-network
  - implement-alinea-ramp-metering
related_skills_for_graph_view:
  - "[[create-grid-network]]"
  - "[[create-spider-network]]"
  - "[[implement-alinea-ramp-metering]]"
---

# Abstract Network Generation

`netgenerate` builds one of three abstract (non-real-world) network types — **grid**, **spider**, or **random** — selected with `--grid`, `--spider`, or `--rand`. Output goes to `-o`/`--output-file <FILE>` (default `net.net.xml`). These are the natural choice when a test/benchmark network is wanted without the overhead of a real map ([[openstreetmap]] covers that path instead).

## Grid networks

A rectangular lattice of junctions. Symmetric grids use `--grid.number` (junctions per side) and `--grid.length` (meters between them); asymmetric grids use `--grid.x-number`/`--grid.y-number` and `--grid.x-length`/`--grid.y-length` independently per axis. `--grid.number 5` produces a 5×5 *junction* lattice (4×4 blocks) — the count is junctions, not blocks.

`--grid.attach-length <FLOAT>` adds dangling streets at the outer boundary so every junction, including edge ones, ends up with four legs (there's currently no way to give different attach lengths per axis).

```bash
netgenerate --grid --grid.number=10 --grid.length=400 --output-file=MySUMOFile.net.xml
netgenerate --grid --grid.x-number=20 --grid.y-number=5 --grid.y-length=40 --grid.x-length=200 -o out.net.xml
```

## Spider networks

Concentric circles crossing radiating arms around a (usually) central junction. `--spider.arm-number`/`--arms` sets the number of spokes (default 13), `--spider.circle-number`/`--circles` the number of rings (default 20), and `--spider.space-radius`/`--radius` the meters between consecutive rings (default 100). Total network extent is roughly circles × space-radius.

The central junction, if kept, can end up with a very large number of converging edges — too many for SUMO to build as a signalized junction, so the center is always left unregulated. `--spider.omit-center`/`--nocenter` drops it entirely, which also doubles as a way to generate a plain circle network (13 elements, 100 m radius, with the defaults).

```bash
netgenerate --spider --spider.arm-number=10 --spider.circle-number=10 --spider.space-radius=100 -o out.net.xml
```

## Random networks

`--rand` grows a network iteratively from randomized parameters: `--rand.iterations`, `--rand.bidi-probability` (chance of a reverse edge), `--rand.max-distance`/`--rand.min-distance` (edge length bounds), `--rand.min-angle`, `--rand.num-tries`, `--rand.connectivity`, and a set of `--rand.neighbor-distN` parameters. Setting `--rand.grid` additionally enforces a grid-like structure: new nodes branch off existing ones in cardinal directions at multiples of `--rand.min-distance` up to `--rand.max-distance`, giving a network with grid-like macro-structure but edges still at varied angles.

```bash
netgenerate --rand -o MySUMOFile.net.xml --rand.iterations=200
```

## Options shared across all three modes

- `-j`/`--default-junction-type-option`: default junction type (`priority`, `traffic_light`, etc.)
- `--turn-lanes` / `--turn-lanes.length`: add dedicated turn lanes at every junction; the length parameter (0–5) controls which combination of left-turn, right-turn, and turn-around-only lanes get added and in what left-to-right order
- `--perturb.x` / `--perturb.y` / `--perturb.z`: randomly jitter node positions along an axis, up to the given amount
- The same street-default and traffic-light-default options as [netconvert](https://sumo.dlr.de/docs/netconvert.html) apply here too (e.g. `--default.lanenumber`, `--default.speed`, `--tls.guess`), plus most other netconvert options such as `--lefthand`.

Every abstract network still has no traffic on its own — the natural next step is [[random-trips]] or a routed demand file.

## When netgenerate isn't enough

None of the three modes here can express an asymmetric, purpose-built topology like a freeway on-ramp merge (a mainline with a single lower-priority lane joining at one specific point) — that needs hand-authored plain-XML `.nod.xml`/`.edg.xml` compiled with `netconvert` directly, the same technique `create-single-intersection` uses for per-arm control. See [[ramp-metering-with-alinea]] for a worked example.
