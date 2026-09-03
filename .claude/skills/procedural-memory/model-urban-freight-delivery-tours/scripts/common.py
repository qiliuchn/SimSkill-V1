#!/usr/bin/env python3
"""Shared configuration, paths and binary resolution for the urban-freight study."""
import os, sys, shutil, subprocess, math

SUMO_HOME = os.environ.get("SUMO_HOME")
if SUMO_HOME and os.path.join(SUMO_HOME, "tools") not in sys.path:
    sys.path.append(os.path.join(SUMO_HOME, "tools"))

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))          # .../outputs
NET = os.path.join(ROOT, "net")
DEMAND = os.path.join(ROOT, "demand")
RUNS = os.path.join(ROOT, "runs")
FIG = os.path.join(ROOT, "figures")
TAB = os.path.join(ROOT, "tables")
for d in (NET, DEMAND, RUNS, FIG, TAB):
    os.makedirs(d, exist_ok=True)


def _bindir():
    s = shutil.which("sumo")
    if s:
        return os.path.dirname(s)
    if SUMO_HOME:
        return os.path.join(SUMO_HOME, "bin")
    raise RuntimeError("cannot locate SUMO binaries")


BIN = _bindir()
SUMO = os.path.join(BIN, "sumo")
NETCONVERT = os.path.join(BIN, "netconvert")
DUAROUTER = os.path.join(BIN, "duarouter")
TOOLS = os.path.join(SUMO_HOME, "tools")


def sh(cmd, cwd=None, check=False):
    r = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True,
                       text=True, cwd=cwd)
    if check and r.returncode != 0:
        raise RuntimeError("cmd failed (%d): %s\n%s" % (r.returncode, cmd, r.stderr[-3000:]))
    return r


# ----------------------------------------------------------------------------
# District geometry -----------------------------------------------------------
N = 7                 # junctions per side -> 6x6 blocks
BLOCK = 200.0         # m
ART_LANES = 2
LOC_LANES = 1
ART_SPEED = 50 / 3.6      # 13.889 m/s
LOC_SPEED = 30 / 3.6      # 8.333 m/s
BISECT_I = 3          # column index of the bisecting arterial

SIM_END = 5400        # 3600 s of car demand + drain long enough for tours to close
DEMAND_END = 3600


def nid(i, j):
    return "J%d%d" % (i, j)


def eid(a, b):
    return "%s_%s" % (a, b)


def is_arterial(i1, j1, i2, j2):
    """Edge between two adjacent grid nodes: is it part of the ring or the bisector?"""
    if i1 == i2 == 0 or i1 == i2 == N - 1:      # west / east ring legs
        return True
    if j1 == j2 == 0 or j1 == j2 == N - 1:      # south / north ring legs
        return True
    if i1 == i2 == BISECT_I:                    # bisecting arterial (vertical)
        return True
    return False


def node_degree(i, j):
    d = 0
    for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        if 0 <= i + di < N and 0 <= j + dj < N:
            d += 1
    return d


def on_arterial(i, j):
    return i in (0, N - 1) or j in (0, N - 1) or i == BISECT_I


def is_signalized(i, j):
    """Signalise every node that lies on an arterial AND has a conflicting approach
    (degree >= 3).  Corners (degree 2) stay priority-controlled."""
    return on_arterial(i, j) and node_degree(i, j) >= 3


def grid_streets():
    """Yield (i1,j1,i2,j2) for every undirected street segment of the lattice."""
    for i in range(N):
        for j in range(N):
            if i + 1 < N:
                yield (i, j, i + 1, j)
            if j + 1 < N:
                yield (i, j, i, j + 1)


# ----------------------------------------------------------------------------
# Fleet -----------------------------------------------------------------------
VTYPES = {
    "car": dict(vClass="passenger", length=4.5, accel=2.6, decel=4.5, tau=1.0,
                maxSpeed=16.7, sigma=0.5, emissionClass="HBEFA3/PC_G_EU4",
                guiShape="passenger", color="0.8,0.8,0.8"),
    "van": dict(vClass="delivery", length=7.5, accel=2.0, decel=4.0, tau=1.2,
                maxSpeed=22.0, sigma=0.5, emissionClass="HBEFA3/LDV_D_EU4",
                containerCapacity=60, loadingDuration=1, guiShape="delivery",
                color="0,0.7,1"),
    "rigid": dict(vClass="truck", length=10.0, accel=1.3, decel=3.5, tau=1.4,
                  maxSpeed=20.0, sigma=0.5, emissionClass="HBEFA3/HDV_D_EU4",
                  containerCapacity=140, loadingDuration=1, guiShape="truck",
                  color="1,0.55,0"),
    "semi": dict(vClass="truck", length=16.5, accel=1.0, decel=3.0, tau=1.6,
                 maxSpeed=18.0, sigma=0.5, emissionClass="HBEFA3/HDV_D_EU5",
                 containerCapacity=260, loadingDuration=1, guiShape="truck",
                 color="1,0,0"),
}
FREIGHT_TYPES = ("van", "rigid", "semi")


def vtype_xml():
    out = []
    for tid, a in VTYPES.items():
        attrs = " ".join('%s="%s"' % (k, v) for k, v in a.items())
        out.append('    <vType id="%s" %s/>' % (tid, attrs))
    return "\n".join(out)


# ----------------------------------------------------------------------------
DEMAND_LEVELS = {"low": 0.30, "mid": 0.60, "high": 0.85}   # target arterial v/c
SEEDS = list(range(1, 9))                                  # >= 8 seeds, CRN
TIME_TO_TELEPORT = 300                                     # > longest red phase
