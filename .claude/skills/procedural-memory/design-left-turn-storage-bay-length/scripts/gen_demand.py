#!/usr/bin/env python3
"""
Demand for the bay-length study.

TOTAL north-approach demand is held CONSTANT at N_TOTAL veh/h in every cell;
only its COMPOSITION changes with the left-turn share, so throughput/delay
differences across cells cannot come from a different amount of traffic.

  N approach:  left  = share * N_TOTAL
               right = 0.10  * N_TOTAL     (fixed)
               thru  = rest
  S/E/W:       450 veh/h each, 15% left / 10% right / 75% through (fixed)

Vehicle ids are prefixed <approach>_<movement> (e.g. "N_L.13") so the
trajectory analysis can classify every vehicle's intended movement without
re-reading its route.
"""
import argparse

N_TOTAL = 800.0
N_RIGHT_SHARE = 0.10
SIDE_TOTAL = 450.0
SIDE_LEFT, SIDE_RIGHT = 0.15, 0.10

# approach -> (through dest, right dest, left dest)
MOV = {
    "N": dict(T="out_S", R="out_W", L="out_E"),
    "S": dict(T="out_N", R="out_E", L="out_W"),
    "E": dict(T="out_W", R="out_N", L="out_S"),
    "W": dict(T="out_E", R="out_S", L="out_N"),
}


def approach_edges(appr, full):
    if appr != "N":
        return [f"in_{appr}"]
    return ["in_N_bay"] if full else ["in_N_up", "in_N_bay"]


def write(path, left_share, full, end=3600, seed=42):
    rows = []
    routes = []
    for appr in "NSEW":
        if appr == "N":
            vols = {"L": N_TOTAL * left_share,
                    "R": N_TOTAL * N_RIGHT_SHARE,
                    "T": N_TOTAL * (1.0 - left_share - N_RIGHT_SHARE)}
        else:
            vols = {"L": SIDE_TOTAL * SIDE_LEFT,
                    "R": SIDE_TOTAL * SIDE_RIGHT,
                    "T": SIDE_TOTAL * (1.0 - SIDE_LEFT - SIDE_RIGHT)}
        base = approach_edges(appr, full)
        for m in ("L", "T", "R"):
            rid = f"r_{appr}_{m}"
            routes.append(f'    <route id="{rid}" edges="{" ".join(base + [MOV[appr][m]])}"/>')
            rows.append(f'    <flow id="{appr}_{m}" route="{rid}" begin="0" end="{end}" '
                        f'vehsPerHour="{vols[m]:.1f}" departLane="best" departSpeed="max" '
                        f'type="car"/>')
    out = ['<?xml version="1.0" encoding="UTF-8"?>', "<routes>",
           '    <vType id="car" vClass="passenger" length="5.0" minGap="2.5" '
           'accel="2.6" decel="4.5" sigma="0.5" tau="1.0" maxSpeed="16.0" '
           'lcStrategic="1.0" lcCooperative="1.0"/>']
    out += routes + rows + ["</routes>"]
    open(path, "w").write("\n".join(out) + "\n")
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--left-share", type=float, required=True)
    ap.add_argument("--full", action="store_true")
    a = ap.parse_args()
    print(write(a.out, a.left_share, a.full))
