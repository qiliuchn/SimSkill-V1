---
summary: TraCI is SUMO's TCP client/server protocol for controlling a running simulation step-by-step; this page covers its architecture, the value-retrieval/state-changing/subscription command families, and performance considerations.
keywords:
  - TraCI
  - client-server
  - libsumo
  - subscriptions
  - remote-port
created: 2026-07-21T14:00:00
last_updated: 2026-07-23T16:46:38
sources:
  - "[[raw-materials/TraCI - SUMO Documentation.md]]"
  - https://sumo.dlr.de/docs/TraCI/index.html
related_pages:
  - "[[change-vehicle-state]]"
  - "[[sumo-command-line]]"
  - "[[sumo-rl-environment]]"
  - "[[max-pressure-signal-control]]"
  - "[[simpla-platooning]]"
  - "[[dynamic-hard-shoulder-running-with-traci-lane-permissions]]"
related_skills:
  - run-simulation
  - get-vehicles-state
  - set-vehicle-state
  - implement-maxpressure-traci-controller
related_skills_for_graph_view:
  - "[[run-simulation]]"
  - "[[get-vehicles-state]]"
  - "[[set-vehicle-state]]"
  - "[[implement-maxpressure-traci-controller]]"
---

# TraCI

**TraCI** ("**Tra**ffic **C**ontrol **I**nterface") is the protocol used to control a running SUMO simulation from an external process: reading simulated object state and manipulating behavior on-line, one step at a time. For raw speed, [libsumo](https://sumo.dlr.de/docs/Libsumo.html) embeds the same API in-process instead of going over a socket — code written against TraCI's Python client is largely portable to libsumo since the function signatures match.

## Architecture

`sumo` (or `sumo-gui`) acts as the TCP server when started with `--remote-port <INT>`. In that mode it prepares the simulation and waits for a client to connect and drive it; the `--end` option is ignored entirely — the simulation runs until the client sends a *close* command. `sumo-gui` as a server additionally needs the *play* button pressed, or `--start`, before it will process TraCI commands.

Multiple clients are supported via `--num-clients <INT>` (default 1); each must specify a unique execution-order integer via the *SetOrder* command, and the simulation only advances once every client has called `simulationStep` for that step — clients are synchronized every step, and the whole simulation waits until all clients have connected before starting at all.

## Command families

- **Value retrieval** — per-domain getters: vehicles, persons, vehicle types, routes, induction loops, lane-area/multi-entry-exit detectors, calibrators, junctions, edges, lanes, traffic lights, bus stops, charging stations, parking areas, overhead wires, rerouters, simulation state, GUI state, POIs, polygons.
- **State changing** — the corresponding setters, e.g. [[change-vehicle-state]] for vehicles, plus equivalents for persons, vehicle types, routes, edges, lanes, traffic lights, and simulation/GUI state. The traffic-light setters (`setPhase`, `setPhaseDuration`) plus `getControlledLinks` for mapping phases to lane movements are the basis of a genuinely custom, closed-loop signal controller — see [[max-pressure-signal-control]].
- **Subscriptions** — repeated notification of a variable's value without re-requesting it every step; can also subscribe to everything *around* an object ("context subscription"). Subscriptions are typically faster than repeated plain retrieval.

Ending a simulation is done by sending the *close* command rather than relying on `--end`; `traci.simulation.getMinExpectedNumber() == 0` indicates every route file's demand has been exhausted and all vehicles have left. A simulation can also be reloaded in place with a new argument list via the *load* command.

## Client libraries

The Python client (`import traci`) ships with the SUMO source and is also on PyPI (`pip install traci`); it's the most complete and actively-tested binding. Other options include libtraci (C++, API-compatible with libsumo), the older/frozen C++ TraCIAPI, .NET, Java (libtraci bindings, or the frozen TraaS), and MATLAB (TraCI4Matlab, though calling the Python client from MATLAB is recommended instead). Any SWIG-supported language can in principle bind to libsumo/libtraci directly.

## Performance

TraCI overhead scales with call count, call type, client-side computation, and client language. As a concrete example, retrieving every vehicle's position each step processes roughly 25,000 vehicles/second with plain calls in Python, versus roughly 50,000/second using subscriptions instead:

```python
# plain retrieval
while traci.simulation.getMinExpectedNumber() > 0:
    for veh_id in traci.vehicle.getIDList():
        position = traci.vehicle.getPosition(veh_id)
    traci.simulationStep()

# subscription-based retrieval
while traci.simulation.getMinExpectedNumber() > 0:
    for veh_id in traci.simulation.getDepartedIDList():
        traci.vehicle.subscribe(veh_id, [traci.constants.VAR_POSITION])
    positions = traci.vehicle.getAllSubscriptionResults()
    traci.simulationStep()
```

If performance genuinely matters, prefer libsumo over TraCI outright — though not every optimization technique (subscriptions in particular) carries over, and subscriptions can even be slower under libsumo.

## Practical notes

- Output files can appear "not closed" if a client reads them while the simulation is still shutting down — wait for shutdown to complete before reading.
- There were two historical generations of the command protocol; the current one uses string IDs matching SUMO's own object IDs directly (no internal int mapping). The first generation only works with `sumo` up to version 0.12.3.
