#!/usr/bin/env python3
"""Sub-goal 4a: offline fixed-time plan optimized for AVERAGE demand, via
Webster's method computed from THIS study's own measured saturation flow
(det/satflow_result.txt) -- reusing `measure-saturation-flow-and-validate-webster-method`'s
`webster.py` (imported directly, not reimplemented)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "demand"))
sys.path.insert(0, "/Users/liuqi/Desktop/simskill/.claude/skills/procedural-memory/"
                "measure-saturation-flow-and-validate-webster-method/scripts")
from webster import WebsterDesign  # noqa: E402
from rate_schedule import thru_rate, SEG_RAMP  # noqa: E402
import numpy as np  # noqa: E402

S_MEAS = 1604.4
L1 = 2.0
YELLOW, ALLRED = 3.0, 0.0
ART_LEFT_FIXED = 8.0     # s, held fixed (subordinate protected-left stage)
CROSS_RATE_TOTAL = 160.0 + 70.0   # crossR+crossL (veh/h) at a typical junction, both lanes... (SB approach, 1 lane)


def average_demand_rates(regime="unpred", n_samples=200):
    ts = np.linspace(SEG_RAMP[1], 3900.0, n_samples)  # skip ramp-up
    eb = np.mean([thru_rate("EB", t, regime) for t in ts])
    wb = np.mean([thru_rate("WB", t, regime) for t in ts])
    return eb, wb


def compute_plan(regime="unpred"):
    eb, wb = average_demand_rates(regime)
    q_art = max(eb, wb) + 70.0     # + arterial side-turn (EB only, ~constant); use max as critical lane
    q_cross = CROSS_RATE_TOTAL
    # two "phases" for Webster purposes: ART (2 lanes), CROSS (1 lane) -- lost
    # time per phase = l1 + (yellow - discharge extension, approximated as
    # yellow itself, a standard simplification) = L1 + YELLOW
    wd = WebsterDesign(s_vph=S_MEAS, l1=L1, l2=YELLOW, yellow=YELLOW, allred=ALLRED)
    crit_flows = [q_art / 2.0, q_cross / 1.0]   # PER LANE critical flow (Webster is per-lane by convention here)
    c_opt, Y, L = wd.c_opt(crit_flows)
    if c_opt is None:
        c_opt = 150.0  # oversaturated fallback -- use max cycle
    c_opt = max(30.0, min(150.0, c_opt))
    geff, gdisp = wd.splits(c_opt, crit_flows, min_green=10.0)
    # gdisp are the "displayed" green including l1 correction; reserve
    # ART_LEFT_FIXED off the top, then split the remainder using the same
    # ART:CROSS ratio Webster computed
    fixed_overhead = 3 * YELLOW  # 3 clearance intervals (no allred in this program)
    avail = c_opt - fixed_overhead - ART_LEFT_FIXED
    ratio = gdisp[0] / (gdisp[0] + gdisp[1])
    g_art = max(10.0, avail * ratio)
    g_cross = avail - g_art
    return dict(C=c_opt, art_main=g_art, art_left=ART_LEFT_FIXED, cross=g_cross,
               q_art=q_art, q_cross=q_cross, Y=Y, L=L)


if __name__ == "__main__":
    for regime in ("pred", "unpred"):
        p = compute_plan(regime)
        print(regime, p)
