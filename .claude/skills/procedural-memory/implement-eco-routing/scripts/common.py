"""Shared paths / constants for the eco-routing study."""
import os
import shutil
import subprocess

BASE = "/Users/liuqi/Desktop/simskill/episodic-memory/2026-08-04_01-00-00"
SCRIPTS = os.path.join(BASE, "attempts", "attempt-1", "scripts")
WORK = os.path.join(BASE, "attempts", "attempt-1", "work")
OUT = os.path.join(BASE, "outputs")

for d in (WORK, OUT):
    os.makedirs(d, exist_ok=True)


def sumo_bin(name):
    p = shutil.which(name)
    if p:
        return p
    sumo = shutil.which("sumo")
    if sumo:
        cand = os.path.join(os.path.dirname(sumo), name)
        if os.path.exists(cand):
            return cand
    sh = os.environ.get("SUMO_HOME", "")
    for sub in ("bin", "../../bin"):
        cand = os.path.join(sh, sub, name)
        if os.path.exists(cand):
            return cand
    raise RuntimeError("cannot locate " + name)


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        raise RuntimeError("FAILED: %s\nSTDOUT:%s\nSTDERR:%s" % (" ".join(cmd), r.stdout[-4000:], r.stderr[-4000:]))
    return r


NET = os.path.join(WORK, "corridor.net.xml")

# --- route markers -------------------------------------------------------
ART_ENTRY = "A_I1"      # arterial entry from the diverge node A
BYP_ENTRY = "A_P1"      # bypass entry from the diverge node A
ART_EXIT = "I4_M"
BYP_EXIT = "P4_M"

ARTERIAL_EDGES = ["A_I1", "I1_I2", "I2_I3", "I3_I4", "I4_M"]
BYPASS_EDGES = ["A_P1", "P1_P2", "P2_P3", "P3_P4", "P4_M"]

SIM_END = 5400          # seconds of simulation (demand ends at 3600)
DEMAND_END = 3600

EMISSION_CLASS = "HBEFA3/PC_G_EU4"


def classify_route(edges):
    """pure-arterial / pure-bypass / hybrid, from a vehicle's edge list."""
    e = set(edges)
    a_in, b_in = ART_ENTRY in e, BYP_ENTRY in e
    a_out, b_out = ART_EXIT in e, BYP_EXIT in e
    if a_in and a_out and not b_in and not b_out:
        return "arterial"
    if b_in and b_out and not a_in and not a_out:
        return "bypass"
    return "hybrid"
