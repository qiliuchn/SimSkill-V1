#!/usr/bin/env python3
"""
Run the four scenarios for the WAUT time-of-day study on the single intersection.

  Run 1 (waut):    WAUT additional active -> program switches A@0, B@600, C@1200
  Run 2 (fixedA):  program A held all 1800s (no WAUT)
  Run 3 (fixedB):  program B held all 1800s (no WAUT)
  Run 4 (fixedC):  program C held all 1800s (no WAUT)

All four use identical demand. Every run logs the active program each step via
traci.trafficlight.getProgram to <run>_progswitch.csv, and writes tripinfo +
summary output. Waiting/travel stats are parsed from tripinfo afterward.
"""
import os
import sys
import csv

WORK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NET = os.path.join(WORK, "intersection.net.xml")
ROU = os.path.join(WORK, "demand.rou.xml")
PROGRAMS = os.path.join(WORK, "programs.add.xml")
WAUT = os.path.join(WORK, "waut.add.xml")
TLS_ID = "center"
END = 1800

os.environ.setdefault("SUMO_HOME",
    "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo")
sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import traci  # noqa: E402
from sumolib import checkBinary  # noqa: E402

SUMO = checkBinary("sumo")


def run(name, add_files, force_program=None):
    tripinfo = os.path.join(WORK, f"{name}_tripinfo.xml")
    summary = os.path.join(WORK, f"{name}_summary.xml")
    logcsv = os.path.join(WORK, f"{name}_progswitch.csv")

    cmd = [SUMO, "-n", NET, "-r", ROU,
           "-a", ",".join(add_files),
           "--tripinfo-output", tripinfo,
           "--summary-output", summary,
           "--duration-log.statistics", "true",
           "--no-step-log", "true",
           "--time-to-teleport", "-1",
           "-b", "0", "-e", str(END)]
    traci.start(cmd)
    if force_program is not None:
        traci.trafficlight.setProgram(TLS_ID, force_program)
    rows = []
    step = 0
    while step < END:
        traci.simulationStep()
        step = int(traci.simulation.getTime())
        prog = traci.trafficlight.getProgram(TLS_ID)
        rows.append((step, prog))
    traci.close()

    with open(logcsv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "activeProgram"])
        w.writerows(rows)
    return logcsv


def switch_points(logcsv):
    """Return list of (time, from_prog, to_prog) where the active program changed."""
    changes = []
    prev = None
    with open(logcsv) as f:
        r = csv.DictReader(f)
        for row in r:
            p = row["activeProgram"]
            if prev is not None and p != prev:
                changes.append((int(row["time"]), prev, p))
            prev = p
    return changes


if __name__ == "__main__":
    print("=== Run 1: WAUT (time-of-day switching) ===")
    log = run("waut", [PROGRAMS, WAUT])
    print("switch points (time, from, to):", switch_points(log))

    print("=== Run 2: fixed program A all day ===")
    run("fixedA", [PROGRAMS], force_program="A")
    print("=== Run 3: fixed program B all day ===")
    run("fixedB", [PROGRAMS], force_program="B")
    print("=== Run 4: fixed program C all day ===")
    run("fixedC", [PROGRAMS], force_program="C")
    print("DONE")
