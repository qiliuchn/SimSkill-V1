#!/usr/bin/env python3
"""Instrument every approach the way a signal agency would.

  * STOP-BAR PRESENCE detectors: E2 laneAreaDetector on EVERY lane of EVERY
    approach at all 4 signals.
      - through lanes   : 15 m  (typical stop-bar presence loop)
      - left-turn bays  : 30 m  (typical LONG left-turn presence loop -- this
        length asymmetry is deliberate: it is the mechanism behind the
        "short queue on a long detector" ATSPM false positive)
  * ADVANCE / SETBACK COUNT detectors: E1 inductionLoop 110 m upstream of the
    stop bar on the through lanes of the COORDINATED (EB / WB arterial)
    approaches only -- the Purdue Coordination Diagram's input.

Writes:
  outputs/det/detectors.add.xml   -- the SUMO additional file
  outputs/det/detector_config.csv -- the ATSPM "detector configuration" table
      (channel -> signal, phase, movement, type). This is CONFIGURATION
      METADATA, exactly what a real ATSPM deployment stores; the downstream
      analysis is allowed to read it, but it contains no simulator state.

NOTE: these detectors are OBSERVATION-ONLY. SUMO's NEMA controller generates
its own internal actuation detectors (detector-length params); ours are a
separate, parallel instrumentation layer so that the event log is a pure
observation of the controller, never an input to it.
"""
import csv
import os
import sys

sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import sumolib  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
NET = os.path.join(ROOT, "outputs", "net", "arterial.net.xml")
OUT = os.path.join(ROOT, "outputs", "det")
os.makedirs(OUT, exist_ok=True)

SETBACK = 110.0          # m upstream of stop bar for advance detectors
LEN_THRU = 15.0
LEN_LEFT = 30.0

J = ["J0", "J1", "J2", "J3"]
NEIGH = {
    "J0": {"W": "AW", "E": "J1", "N": "N_J0", "S": "S_J0"},
    "J1": {"W": "J0", "E": "J2", "N": "N_J1", "S": "S_J1"},
    "J2": {"W": "J1", "E": "J3", "N": "N_J2", "S": "S_J2"},
    "J3": {"W": "J2", "E": "AE", "N": "N_J3", "S": "S_J3"},
}
# approach direction -> (source-node key, through NEMA phase, left NEMA phase)
APPROACH = {"EB": ("W", 6, 1), "WB": ("E", 2, 5), "SB": ("N", 8, 3), "NB": ("S", 4, 7)}
COORD_APPROACHES = ("EB", "WB")

net = sumolib.net.readNet(NET)
add = ['<?xml version="1.0" encoding="UTF-8"?>', "<additional>"]
rows = [("signal_id", "channel", "det_id", "det_class", "sumo_type", "lane",
         "phase", "approach_dir", "movement", "length_m", "setback_m")]

for j in J:
    ch = 0
    adv_ch = 20
    for d, (nk, p_thru, p_left) in APPROACH.items():
        eid = f"{NEIGH[j][nk]}_{j}"
        edge = net.getEdge(eid)
        lanes = edge.getLanes()
        n = len(lanes)
        for li, lane in enumerate(lanes):
            is_left = (li == n - 1)
            phase = p_left if is_left else p_thru
            mv = f"{d}L" if is_left else (f"{d}TR" if li == 0 else f"{d}T")
            length = LEN_LEFT if is_left else LEN_THRU
            ch += 1
            did = f"SB_{j}_{d}_{li}"
            add.append(f'    <laneAreaDetector id="{did}" lane="{lane.getID()}" '
                       f'pos="-{length:.1f}" length="{length:.1f}" friendlyPos="true" '
                       f'period="99999" file="det_dump.xml"/>')
            rows.append((j, ch, did, "stopbar", "e2", lane.getID(), phase, d, mv,
                         f"{length:.1f}", "0.0"))
        if d in COORD_APPROACHES:
            for li in range(n - 1):        # through lanes only
                lane = lanes[li]
                if lane.getLength() < SETBACK + 20:
                    raise SystemExit(f"lane {lane.getID()} too short for {SETBACK} m setback")
                adv_ch += 1
                did = f"ADV_{j}_{d}_{li}"
                add.append(f'    <inductionLoop id="{did}" lane="{lane.getID()}" '
                           f'pos="-{SETBACK:.1f}" friendlyPos="true" '
                           f'period="99999" file="det_dump.xml"/>')
                rows.append((j, adv_ch, did, "advance", "e1", lane.getID(), p_thru, d,
                             f"{d}T", "2.0", f"{SETBACK:.1f}"))
add.append("</additional>")

with open(os.path.join(OUT, "detectors.add.xml"), "w") as f:
    f.write("\n".join(add) + "\n")
with open(os.path.join(OUT, "detector_config.csv"), "w", newline="") as f:
    csv.writer(f).writerows(rows)

n_sb = sum(1 for r in rows[1:] if r[3] == "stopbar")
n_ad = sum(1 for r in rows[1:] if r[3] == "advance")
print(f"Wrote {OUT}/detectors.add.xml and detector_config.csv")
print(f"  stop-bar E2 presence detectors : {n_sb}  (4 signals x 4 approaches x lanes)")
print(f"  advance   E1 count detectors   : {n_ad}  ({SETBACK:.0f} m setback, EB/WB through lanes)")
print(f"  free-flow setback travel time at 15 m/s = {SETBACK/15.0:.2f} s")
