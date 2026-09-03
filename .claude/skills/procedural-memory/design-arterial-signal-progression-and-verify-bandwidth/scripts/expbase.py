#!/usr/bin/env python3
"""Shared configuration + parallel job runner for the H1-H6 experiments."""
import multiprocessing as mp
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arterial_lib as A     # noqa: E402
import runner as R           # noqa: E402
import scenario as S         # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(HERE, "work")
DATA = os.path.join(HERE, "data")
FIG = os.path.join(HERE, "figures")
for _d in (WORK, DATA, FIG):
    os.makedirs(_d, exist_ok=True)

# ---- base design point ------------------------------------------------------
N_INT = 7
C0 = 90.0            # design cycle (s)
GX0 = 22.0           # cross-street green (s)
GL0 = 10.0           # arterial protected-left green per direction (s)
VPROG = 13.0         # CALIBRATED progression speed (m/s); see
                     # data/speed_calibration.json -- 93.6% of the 13.89 m/s
                     # posted speed, the value that maximises measured
                     # one-way zero-stop fraction on this corridor.
VLIMIT = 13.89
L0 = 400.0           # base uniform block spacing (m)
THRU0, CROSS0, SIDE0 = 800.0, 350.0, 60.0
WARM = 600.0
SEEDS = [1, 2, 3, 4, 5, 6]

NPROC = min(8, mp.cpu_count())


def plan(C=C0, gX=GX0, gL=GL0, modes=None, offs=None, n=N_INT):
    return A.SignalPlan(C=C, gX=gX, gL=gL, n_int=n, modes=modes, offs=offs)


def scaled_split(C):
    """Keep the green-time SHARES of the base plan when the cycle changes.

    gX/gL scale with the available green (C - 12) so that changing C is a pure
    cycle-length experiment, not a covert split experiment.
    """
    avail = C - 12.0
    base = C0 - 12.0
    return GX0 * avail / base, GL0 * avail / base


def _job(a):
    fn, kw = a
    try:
        return fn(**kw)
    except Exception as e:                       # noqa: BLE001
        import traceback
        return dict(error=str(e), tb=traceback.format_exc(), kw=kw)


def pmap(fn, kwlist, nproc=None):
    nproc = nproc or NPROC
    if nproc <= 1:
        return [_job((fn, k)) for k in kwlist]
    with mp.Pool(nproc) as p:
        return p.map(_job, [(fn, k) for k in kwlist])


def uncoordinated_offsets(n=N_INT):
    return [0.0] * n
