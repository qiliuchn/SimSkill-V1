#!/usr/bin/env python3
"""
Tuning probe: does SUMO's default driving model ever let a road vehicle come to
a STANDSTILL on the rail-crossing footprint (the MUTCD failure mode), or does
its junction-blocking avoidance always stop the vehicle short of the crossing?

Runs the corridor at a range of EB demands and vType/option settings, and
reports, for each: the max number of vehicles STOPPED (speed < 0.1 m/s) whose
physical extent overlaps junction X's footprint, at any instant.
"""
import json
import os
import subprocess
import sys

sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import traci  # noqa: E402
import common as C  # noqa: E402
import build_scenario as B  # noqa: E402

OUT = os.path.join(C.ROOT, "outputs", "instrumentation")
os.makedirs(OUT, exist_ok=True)
TMP = os.path.join(OUT, "probe")
os.makedirs(TMP, exist_ok=True)


def make_rou(path, eb, keepclear):
    B.write_routes(path, eb, 300, 400, 300, 1500, keepclear=keepclear)


def run(label, eb, keepclear, extra_opts=()):
    rou = os.path.join(TMP, f"probe_{label}.rou.xml")
    make_rou(rou, eb, keepclear)
    cfg = ["sumo", "-n", C.NET_FILE, "-r", rou, "--begin", "0", "--end", "1500",
           "--step-length", "1", "--seed", "42", "--no-step-log", "true",
           "--time-to-teleport", "-1"] + list(extra_opts)
    traci.start(cfg, label=label)
    con = traci.getConnection(label)
    max_stopped_on = 0
    max_any_on = 0
    stopped_events = []
    while con.simulation.getTime() < 1500:
        con.simulationStep()
        occ = C.occupancy(con)
        stopped = [v for v, _o, s in occ if s < 0.1]
        if len(stopped) > max_stopped_on:
            max_stopped_on = len(stopped)
        if len(occ) > max_any_on:
            max_any_on = len(occ)
        if stopped:
            stopped_events.append((con.simulation.getTime(), stopped))
    con.close()
    return {"label": label, "eb_vph": eb, "jmIgnoreKeepClearTime": keepclear, "opts": list(extra_opts),
            "max_stopped_on_footprint": max_stopped_on,
            "max_any_on_footprint": max_any_on,
            "n_instants_with_stopped_vehicle_on_crossing": len(stopped_events),
            "first_events": [[t, v] for t, v in stopped_events[:5]]}


if __name__ == "__main__":
    res = []
    # NEGATIVE CONTROL: SUMO default keep-clear (-1 = never violate) at three
    # demand levels including heavily oversaturated.
    for eb in (450, 600, 750, 1200):
        res.append(run(f"default_kc-1_eb{eb}", eb, -1))
    # with keep-clear violation enabled (drivers queue across the tracks)
    for eb in (450, 600, 750, 1200):
        res.append(run(f"kc0_eb{eb}", eb, 0))
    with open(os.path.join(OUT, "junction_blocking_probe.json"), "w") as f:
        json.dump(res, f, indent=2)
    print(json.dumps(res, indent=2))
