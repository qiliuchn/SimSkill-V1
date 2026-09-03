#!/usr/bin/env python3
"""Shared paths / binary resolution / small helpers for the driveway TIA study."""
import os
import shutil
import subprocess
import sys

EPISODE = "/Users/liuqi/Desktop/simskill/episodic-memory/2026-08-04_14-00-00"
SCRIPTS = os.path.join(EPISODE, "attempts", "attempt-1", "scripts")
OUT = os.path.join(EPISODE, "outputs")
SCEN = os.path.join(OUT, "scenario")       # net / detectors / demand
RUNS = os.path.join(OUT, "runs")           # raw sumo output per run
TABLES = os.path.join(OUT, "tables")       # csv deliverables
CAL = os.path.join(OUT, "calibration")

for d in (OUT, SCEN, RUNS, TABLES, CAL):
    os.makedirs(d, exist_ok=True)

# ---------------------------------------------------------------- study clock
SIM_START_CLOCK = 7          # t = 0 s  <=>  07:00
N_HOURS = 12                 # 07:00 - 19:00
HOUR = 3600
DEMAND_END = N_HOURS * HOUR  # 43200 s
DRAIN_END = 54000            # +3 h drain so residual queues are counted

STEP_LENGTH = 0.5            # main runs
CAL_STEP_LENGTH = 0.1        # saturation-flow calibration only
ACTION_STEP = 1.0            # PINNED reaction time (see measure-saturation-flow skill)


def hour_label(h_index):
    """h_index 0..11 -> '07:00-08:00'"""
    a = SIM_START_CLOCK + h_index
    return "%02d:00-%02d:00" % (a, a + 1)


def find_bin(name):
    p = shutil.which(name)
    if p:
        return p
    sumo = shutil.which("sumo")
    if sumo:
        c = os.path.join(os.path.dirname(sumo), name)
        if os.path.isfile(c):
            return c
    sh = os.environ.get("SUMO_HOME")
    if sh:
        c = os.path.join(sh, "bin", name)
        if os.path.isfile(c):
            return c
    sys.exit("cannot find binary: " + name)


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    return r


def write(path, text):
    with open(path, "w") as f:
        f.write(text)
    return path
