#!/usr/bin/env python3
"""Config construction helpers shared by the verification, sweep and fault drivers."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tls_common import GREEN_ORDER

GENERIC_MAXDUR = 50.0     # the "generic large value" default actuated maxDur
MIN_GREEN = 7.0

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "work")
NET = os.path.join(WORK, "net", "inter.net.xml")
PLANS = json.load(open(os.path.join(WORK, "webster_plans.json")))


def rou(level, seed):
    return os.path.join(WORK, "demand", f"{level}_s{seed}.rou.xml")


def webster_green(level):
    return {gp: float(PLANS[level]["green"][str(gp)]) for gp in GREEN_ORDER}


def webster_cfg(level):
    return dict(mode="webster", green=webster_green(level), level=level)


def actuated_cfg(level, setback, max_gap, maxdur="generic",
                 dead_lanes=(), stuck_on_lanes=(), det_overrides=None):
    """maxdur: 'generic' -> 50 s for every phase
               'webster' -> the Webster displayed green for this demand level"""
    wg = webster_green(level)
    if maxdur == "webster":
        mx = {gp: max(MIN_GREEN + 1, wg[gp]) for gp in GREEN_ORDER}
    else:
        mx = {gp: GENERIC_MAXDUR for gp in GREEN_ORDER}
    return dict(mode="actuated", level=level,
                green={gp: MIN_GREEN for gp in GREEN_ORDER},   # nominal duration
                min_dur={gp: MIN_GREEN for gp in GREEN_ORDER},
                max_dur=mx, setback=float(setback), max_gap=float(max_gap),
                maxdur_mode=maxdur,
                dead_lanes=list(dead_lanes), stuck_on_lanes=list(stuck_on_lanes),
                det_overrides=dict(det_overrides or {}))
