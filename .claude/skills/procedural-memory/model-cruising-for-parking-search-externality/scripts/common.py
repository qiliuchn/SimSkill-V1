"""Shared paths / SUMO binary resolution for the cruising-for-parking study."""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.dirname(HERE)                     # .../outputs
NET_DIR = os.path.join(OUT, "net")
DATA_DIR = os.path.join(OUT, "data")
FIG_DIR = os.path.join(OUT, "figures")
RUN_DIR = os.path.join(OUT, "runs")
for d in (NET_DIR, DATA_DIR, FIG_DIR, RUN_DIR):
    os.makedirs(d, exist_ok=True)


def _bin(name):
    p = shutil.which(name)
    if p:
        return p
    sumo = shutil.which("sumo")
    if sumo:
        cand = os.path.join(os.path.dirname(sumo), name)
        if os.path.exists(cand):
            return cand
    sh = os.environ.get("SUMO_HOME")
    if sh:
        cand = os.path.join(sh, "bin", name)
        if os.path.exists(cand):
            return cand
    raise RuntimeError("cannot locate %s" % name)


SUMO = _bin("sumo")
NETGENERATE = _bin("netgenerate")
NETCONVERT = _bin("netconvert")
DUAROUTER = _bin("duarouter")

# SUMO_HOME for tools/sumolib
_SUMO_HOME = os.environ.get("SUMO_HOME")
if not _SUMO_HOME or not os.path.exists(os.path.join(_SUMO_HOME, "tools")):
    # framework layout: <...>/EclipseSUMO/bin/sumo -> <...>/EclipseSUMO/share/sumo
    cand = os.path.join(os.path.dirname(os.path.dirname(SUMO)), "share", "sumo")
    if os.path.exists(os.path.join(cand, "tools")):
        _SUMO_HOME = cand
        os.environ["SUMO_HOME"] = cand
if _SUMO_HOME:
    sys.path.insert(0, os.path.join(_SUMO_HOME, "tools"))
SUMO_HOME = _SUMO_HOME


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        raise RuntimeError("FAILED: %s\nSTDOUT:%s\nSTDERR:%s" % (" ".join(cmd), r.stdout, r.stderr))
    return r
