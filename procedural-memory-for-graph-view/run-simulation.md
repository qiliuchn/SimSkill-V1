---
name: run-simulation
description: Use this skill when the user wants to run a SUMO (Simulation of Urban MObility) traffic simulation — either as a plain command-line run that just produces output files (tripinfo, summary, FCD, etc.) with no live interaction, or via the TraCI (Traffic Control Interface) Python API for step-by-step control, querying, or closed-loop/RL-style interaction. Trigger on mentions of SUMO, TraCI, sumolib, libsumo, .sumocfg/.net.xml/.rou.xml files, or requests to simulate a road network, whether that means "just run it and give me the output" or "control it live while it runs."
---

# Running a SUMO Simulation: Command Line or TraCI

There are two distinct ways to run a SUMO simulation, and picking the right one matters:

1. **Command line only** — start `sumo`/`sumo-gui` with a config and let it run start-to-finish on its own, producing output files (tripinfo, summary statistics, FCD traces, etc.). No Python loop, no live interaction. Use this whenever the goal is just "run the simulation and give me the results" — evaluating a fixed-time signal plan, generating a baseline for comparison, batch-running many scenarios, or anything that doesn't need to read or change state *during* the run.
2. **TraCI (or libsumo)** — drive the simulation step-by-step from Python, reading and writing state live. Use this whenever the simulation needs to be observed or controlled while it's running — RL environments, adaptive/actuated control logic built outside SUMO's own actuated-TLS support, live vehicle queries, anything from the `get-vehicles-state`/`set-vehicle-state` skills, etc.

If it's not obvious which is needed: if the task can be fully described as "run this and then look at the output files," command-line is simpler and faster (no Python/TraCI overhead at all). If it needs anything mid-simulation, TraCI/libsumo is required.

## Prerequisites

SUMO must already be installed and `SUMO_HOME` set (e.g. `/usr/share/sumo` or wherever it was installed). Check before doing anything else:

```bash
echo $SUMO_HOME
which sumo sumo-gui
python -c "import traci" 2>&1 || echo "traci not on path yet"
```

If `traci` isn't importable but `SUMO_HOME` is set, it's because the `traci` package lives inside SUMO's `tools/` directory rather than being pip-installed — add it to `sys.path` (see script below) rather than trying to `pip install traci` (that PyPI package is a different, largely unrelated thing).

If `SUMO_HOME` is unset, ask the user where SUMO is installed, or find it with `find / -iname "traci" -path "*/tools/*" 2>/dev/null`.

## Option 1: Command line only

Just invoke `sumo` (headless) or `sumo-gui` (visual) directly with a config file — no TraCI connection at all. This is a plain subprocess call: SUMO runs the entire simulation on its own and writes whatever output files were requested, then exits.

```bash
sumo -c config.sumocfg --tripinfo-output tripinfo.xml --summary-output summary.xml
```

Use `scripts/run_sumo_cli.py` rather than hand-building this command — it resolves the `sumo`/`sumo-gui` binary (`$PATH` → `$SUMO_HOME/bin`), wraps the commonly-requested output files, and supports `--dry-run` to preview the command.

```bash
python scripts/run_sumo_cli.py --config config.sumocfg --tripinfo-output tripinfo.xml --summary-output summary.xml
python scripts/run_sumo_cli.py --net-file net.net.xml --route-file routes.rou.xml --duration-log-statistics
python scripts/run_sumo_cli.py --config config.sumocfg --gui
python scripts/run_sumo_cli.py --config config.sumocfg --begin 0 --end 3600 --step-length 0.5
```

Common output flags (all optional, combine freely):

| Flag | Produces |
| --- | --- |
| `--tripinfo-output <FILE>` | per-vehicle summary: duration, waiting time, time loss, route length, etc. |
| `--summary-output <FILE>` | per-timestep aggregate: running/waiting vehicle counts, mean speed |
| `--duration-log-statistics` | print aggregate duration/waiting-time statistics to stdout at the end (no file) |
| `--fcd-output <FILE>` | Floating Car Data — every vehicle's position every timestep (large files) |
| `--netstate-output <FILE>` | full network state dump each timestep |
| `--queue-output <FILE>` | per-lane queue length over time |
| `--emission-output <FILE>` | per-vehicle emissions (requires an emission-capable vehicle class) |

This mode is the natural way to evaluate output from `optimize-signals-by-tlscycleadaptation`/`optimize-signals-by-tlscoordinator` (load the `.add.xml` they produce with `-a`) or to run a trained policy's *baseline comparison* — though a trained RL policy itself still needs TraCI/`sumo-rl` to actually act during the run, since the policy isn't expressed as static SUMO config.

## Option 2: TraCI / libsumo

### Two ways to connect

- **`traci`** — talks to a SUMO subprocess over a socket. Works with `sumo` (headless) or `sumo-gui` (visual). Supports multiple simultaneous connections/simulations (via `traci.connect`/labels). Slower due to IPC overhead. Use this whenever the user wants to *see* the simulation, or needs multi-client/multi-simulation setups.
- **`libsumo`** — same API, but links SUMO in-process as a C++ library. No subprocess, no socket, meaningfully faster (often 2-10x for step-heavy workloads). No GUI, and only one simulation per process. Use this for headless batch runs, training loops, or anything performance-sensitive.

They're API-compatible — code written against `traci.xxx` mostly works unchanged if you instead `import libsumo as traci`. Default to `traci` unless the user cares about speed and doesn't need the GUI, in which case ask or default to `libsumo`.

### The core pattern

1. Start SUMO with a config (or explicit net/route files) and a connection.
2. Loop: `traci.simulationStep()` advances one timestep, then read/write state through the various API modules (`traci.vehicle`, `traci.trafficlight`, `traci.lane`, `traci.edge`, `traci.simulation`, `traci.junction`, `traci.person`, etc.).
3. Stop when the loop's exit condition is hit (no vehicles left, `simulation.getMinExpectedNumber() <= 0`, a max-step count, or a custom condition).
4. Always `traci.close()` in a `finally` block — a crashed script that skips this leaves the SUMO subprocess and/or socket dangling.

Use `scripts/run_traci_simulation.py` as the starting template rather than writing this loop from scratch — copy it in and adapt the step-loop body to whatever the user actually wants to measure or control. It already handles the SUMO_HOME path setup, connection, clean shutdown, and the traci/libsumo switch.

### Common API surface

Cheat-sheet of what gets reached for most often — full docs are at https://sumo.dlr.de/docs/TraCI.html, fetch that (or the module-specific page, e.g. `.../TraCI/Vehicle_Value_Retrieval.html`) if something specific isn't covered here.

**Simulation control / info**
```python
traci.simulationStep()                        # advance one step (or traci.simulationStep(time) to jump to a time)
traci.simulation.getTime()                     # current sim time (s)
traci.simulation.getMinExpectedNumber()        # vehicles still to come + currently running; 0 means sim is effectively done
traci.simulation.getDepartedIDList()           # vehicles that departed this step
traci.simulation.getArrivedIDList()            # vehicles that arrived/left this step
traci.simulation.getCollidingVehiclesIDList()  # collisions this step
```

**Vehicles**
```python
traci.vehicle.getIDList()                      # all vehicle IDs currently in the network
traci.vehicle.getSpeed(veh_id)
traci.vehicle.getPosition(veh_id)               # (x, y)
traci.vehicle.getRoadID(veh_id)
traci.vehicle.getLaneID(veh_id)
traci.vehicle.getRoute(veh_id)

traci.vehicle.setSpeed(veh_id, speed)           # m/s; -1 releases back to normal car-following
traci.vehicle.slowDown(veh_id, speed, duration)
traci.vehicle.changeLane(veh_id, lane_index, duration)
traci.vehicle.setRoute(veh_id, edge_id_list)
traci.vehicle.add(veh_id, route_id, typeID=..., depart=...)  # inject a new vehicle mid-simulation
```

**Traffic lights**
```python
traci.trafficlight.getIDList()
traci.trafficlight.getRedYellowGreenState(tls_id)     # e.g. "GrGr"
traci.trafficlight.setRedYellowGreenState(tls_id, "rGrG")
traci.trafficlight.getPhase(tls_id)
traci.trafficlight.setPhase(tls_id, phase_index)
traci.trafficlight.setPhaseDuration(tls_id, duration)
```

**Lanes / edges**
```python
traci.lane.getLastStepVehicleNumber(lane_id)
traci.lane.getLastStepMeanSpeed(lane_id)
traci.edge.getLastStepVehicleNumber(edge_id)
traci.edge.getTraveltime(edge_id)
```

**GUI (only meaningful with `sumo-gui` + `traci`, not `libsumo`)**
```python
traci.gui.setZoom("View #0", 500)
traci.gui.trackVehicle("View #0", veh_id)
traci.gui.screenshot("View #0", "/path/out.png")
```

## Common gotchas

**Command-line mode:**
- **No mid-run interaction at all.** If a task turns out to need reading or changing state partway through (even just printing progress based on live vehicle counts), that's a sign TraCI/libsumo is actually needed, not command-line mode — there's no way to add that after the fact without switching approaches.
- **`--end` is respected** here, unlike under TraCI where it's ignored in favor of the client controlling shutdown (see below).
- Output files are overwritten silently on rerun, same as any SUMO application (see `sumo-command-line` conventions).

**TraCI mode:**
- **IDs are strings, not ints.** `getIDList()` returns strings like `"veh0"`, `"E12"`, not indices.
- **A vehicle only exists between departure and arrival.** Calling `traci.vehicle.getSpeed()` on an ID not currently in `getIDList()` raises a `TraCIException` — check membership or wrap in try/except when iterating over a fixed list across steps.
- **`sumo-gui` needs a display.** In a headless environment (most servers, containers, CI) use `sumo` or `libsumo`, not `sumo-gui`, or it will hang/fail on connect.
- **Port conflicts.** If a previous run crashed without closing cleanly, the old SUMO process may still hold the port — `traci.start(...)` will fail to connect. Kill stale `sumo`/`sumo-gui` processes or let `traci.start` pick a free port automatically (default behavior when no port is passed).
- **libsumo is single-instance per process.** You can't run two libsumo simulations concurrently in the same Python process the way you can with multiple labeled `traci` connections.
- **Config vs. explicit files.** `traci.start(["sumo", "-c", "config.sumocfg"])` is usually cleaner than passing `-n net.xml -r routes.xml` separately, unless the user wants to override specific settings inline (in which case those flags can be added to the same command list).
- **`--end` is ignored** when SUMO is run as a TraCI server — the simulation runs until the client sends the close command, not until a fixed end time.
