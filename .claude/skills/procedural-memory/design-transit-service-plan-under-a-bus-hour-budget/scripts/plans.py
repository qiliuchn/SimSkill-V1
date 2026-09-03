"""Three structurally different service plans over the 6x6 grid.

Node grid: columns A..F (x = 0..4000 m), rows 0..5 (y = 0..4000 m).
Zones are 2x2 node blocks; CBD = zone 4 = {C2,C3,D2,D3}.
"""
from tspcore import Line, ServicePlan

# ---------------------------------------------------------------- COVERAGE ---
# 8 direct radial/crosstown routes, every peripheral corner gets a one-seat ride
# to the CBD.  Many routes -> each can only be given a low frequency.
COVERAGE = [
    ("cv1", ["A0", "B0", "C0", "C1", "C2", "C3"]),      # SW corner  -> CBD
    ("cv2", ["A5", "B5", "C5", "C4", "C3", "C2"]),      # NW corner  -> CBD
    ("cv3", ["F0", "E0", "D0", "D1", "D2", "D3"]),      # SE corner  -> CBD
    ("cv4", ["F5", "E5", "D5", "D4", "D3", "D2"]),      # NE corner  -> CBD
    ("cv5", ["A2", "B2", "C2", "D2", "E2", "F2"]),      # E-W row 2 through CBD
    ("cv6", ["A3", "B3", "C3", "D3", "E3", "F3"]),      # E-W row 3 through CBD
    ("cv7", ["A1", "B1", "C1", "D1", "E1", "F1"]),      # southern crosstown
    ("cv8", ["A4", "B4", "C4", "D4", "E4", "F4"]),      # northern crosstown
]

# -------------------------------------------------------- TRUNK AND FEEDER ---
# 2 high-frequency trunks crossing at the CBD, 4 short feeders that terminate at
# a trunk hub (B2 west, E2 east) -> peripheral riders must transfer.
TRUNKFEEDER = [
    ("tk1", ["A2", "B2", "C2", "D2", "E2", "F2"]),      # E-W trunk through CBD
    ("tk2", ["C0", "C1", "C2", "C3", "C4", "C5"]),      # N-S trunk through CBD
    ("tk3", ["D0", "D1", "D2", "D3", "D4", "D5"]),      # 2nd N-S trunk
    ("fd1", ["A0", "B0", "B1", "B2"]),                  # SW feeder  -> hub B2
    ("fd2", ["A5", "B5", "B4", "B3", "B2"]),            # NW feeder  -> hub B2
    ("fd3", ["F0", "E0", "E1", "E2"]),                  # SE feeder  -> hub E2
    ("fd4", ["F5", "E5", "E4", "E3", "E2"]),            # NE feeder  -> hub E2
]

# ------------------------------------------------------------ FREQUENT GRID ---
# 4 long routes only, all through the CBD core, very high frequency.
# Coverage of the corners is deliberately poor; transfers are common but untimed.
FREQGRID = [
    ("fg1", ["A2", "B2", "C2", "D2", "E2", "F2"]),      # E-W row 2
    ("fg2", ["A3", "B3", "C3", "D3", "E3", "F3"]),      # E-W row 3
    ("fg3", ["C0", "C1", "C2", "C3", "C4", "C5"]),      # N-S col C
    ("fg4", ["D0", "D1", "D2", "D3", "D4", "D5"]),      # N-S col D
]

PLAN_DEFS = {"coverage": COVERAGE, "trunkfeeder": TRUNKFEEDER, "freqgrid": FREQGRID}


def make_plan(name, buses=None, offsets=None):
    defs = PLAN_DEFS[name]
    lines = []
    for i, (lid, nodes) in enumerate(defs):
        n = (buses or {}).get(lid, 2)
        off = (offsets or {}).get(lid, 0.0)
        lines.append(Line(lid, nodes, n, off))
    return ServicePlan(name, lines)
