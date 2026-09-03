#!/usr/bin/env python3
"""Emit parking areas, BRT stops+schedule, and intermodal person demand
for the park-and-ride corridor.

All knobs (lot capacity, lot siting, BRT headway, demand size) are CLI args so
the sensitivity sweeps re-use exactly this generator.
"""
import argparse
import os
import random
import re

# --- BRT geometry: (edge, length) along the eastbound busway ----------------
EB_ROUTE = ["BW_W_BW_ST", "BW_ST_BW_MID", "BW_MID_BW_CG", "BW_CG_BW_CC", "BW_CC_BW_E"]
WB_ROUTE = ["BW_E_BW_CC", "BW_CC_BW_CG", "BW_CG_BW_MID", "BW_MID_BW_ST", "BW_ST_BW_W"]
EDGE_LEN = {"BW_W_BW_ST": 400.0, "BW_ST_BW_MID": 2400.0, "BW_MID_BW_CG": 1800.0,
            "BW_CG_BW_CC": 800.0, "BW_CC_BW_E": 200.0}
EDGE_LEN.update({"BW_E_BW_CC": 200.0, "BW_CC_BW_CG": 800.0, "BW_CG_BW_MID": 1800.0,
                 "BW_MID_BW_ST": 2400.0, "BW_ST_BW_W": 400.0})
BW_SPEED = 22.22
DWELL = 20

# eastbound stops: (stop id, edge it sits on, access list [(lane,pos,length)])
EB_STOPS = [
    ("BS_ST_E",  "BW_ST_BW_MID", [("ST_STLOT_0", 30.0, 300.0), ("SUB21_ST_0", 700.0, 300.0)]),
    ("BS_MID_E", "BW_MID_BW_CG", [("A0_A1_0", 1150.0, 280.0)]),
    ("BS_CG_E",  "BW_CG_BW_CC",  [("CBD01_CBD11_0", 20.0, 280.0)]),
    ("BS_CC_E",  "BW_CC_BW_E",   [("CBD21_CBD31_0", 20.0, 280.0)]),
]
WB_STOPS = [
    ("BS_CC_W", "BW_CC_BW_CG", [("CBD21_CBD31_0", 25.0, 280.0)]),
    ("BS_CG_W", "BW_CG_BW_MID", [("CBD01_CBD11_0", 25.0, 280.0)]),
    ("BS_MID_W", "BW_MID_BW_ST", [("A0_A1_0", 1155.0, 280.0)]),
    ("BS_ST_W", "BW_ST_BW_W",   [("ST_STLOT_0", 35.0, 300.0), ("SUB21_ST_0", 705.0, 300.0)]),
]

SUB_ORIGIN_EDGES = []
for i in range(3):
    for j in range(3):
        if i + 1 < 3:
            SUB_ORIGIN_EDGES.append("SUB%d%d_SUB%d%d" % (i, j, i + 1, j))
        if j + 1 < 3:
            SUB_ORIGIN_EDGES.append("SUB%d%d_SUB%d%d" % (i, j, i, j + 1))

CBD_DEST_EDGES = []
for i in range(4):
    for j in range(3):
        if i + 1 < 4:
            CBD_DEST_EDGES.append("CBD%d%d_CBD%d%d" % (i, j, i + 1, j))
        if j + 1 < 3:
            CBD_DEST_EDGES.append("CBD%d%d_CBD%d%d" % (i, j, i, j + 1))
# drop the arterial gate edge itself so destinations are genuinely inside the CBD
CBD_DEST_EDGES = [e for e in CBD_DEST_EDGES if not e.startswith("CBD01_CBD11")]


def write_parking(path, cap_main, cap_overflow, cap_mid, cap_mid2=0, only=None):
    """siting: 'suburban' (lot at the ST station) or 'intermediate' (lot at A1)."""
    lines = ['<additional>']
    # PR_MAIN: dead-end stub next to the suburban station
    lines.append('    <parkingArea id="PR_MAIN" lane="ST_STLOT_1" startPos="5.0" endPos="235.0" '
                 'roadsideCapacity="%d" onRoad="false" length="7.0" angle="90"/>' % cap_main)
    # PR_OVER: secondary/overflow lot on the return side of the same stub
    lines.append('    <parkingArea id="PR_OVER" lane="STLOT_ST_1" startPos="5.0" endPos="235.0" '
                 'roadsideCapacity="%d" onRoad="false" length="7.0" angle="90"/>' % cap_overflow)
    # PR_MID: intermediate lot at the A1 station, 2.4 km closer to the CBD
    lines.append('    <parkingArea id="PR_MID" lane="A0_A1_1" startPos="900.0" endPos="1150.0" '
                 'roadsideCapacity="%d" onRoad="false" length="7.0" angle="90"/>' % cap_mid)
    # PR_MID2: secondary/overflow lot for PR_MID, downstream on the next arterial
    # link so a vehicle turned away from PR_MID reaches it by continuing forward.
    lines.append('    <parkingArea id="PR_MID2" lane="A1_A2_1" startPos="30.0" endPos="280.0" '
                 'roadsideCapacity="%d" onRoad="false" length="7.0" angle="90"/>' % cap_mid2)
    if only is not None:
        keep = set(only)
        lines = [lines[0]] + [l for l in lines[1:]
                              if re.search(r'id="([^"]+)"', l).group(1) in keep]
    lines.append('</additional>')
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def write_rerouter(path, primary, alternatives, edges):
    lines = ['<additional>',
             '    <rerouter id="rr_%s" edges="%s">' % (primary, " ".join(edges)),
             '        <interval begin="0" end="200000">']
    for a in [primary] + [x for x in alternatives if x != primary]:
        lines.append('            <parkingAreaReroute id="%s" visible="true"/>' % a)
    lines += ['        </interval>', '    </rerouter>', '</additional>']
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def write_stops(path):
    lines = ['<additional>']
    for sid, edge, acc in EB_STOPS + WB_STOPS:
        line_tag = "BRT_E" if sid.endswith("_E") else "BRT_W"
        lines.append('    <busStop id="%s" lane="%s_1" startPos="10.0" endPos="40.0" '
                     'lines="%s" friendlyPos="true">' % (sid, edge, line_tag))
        for lane, pos, length in acc:
            lines.append('        <access lane="%s" pos="%.1f" length="%.1f" friendlyPos="true"/>'
                         % (lane, pos, length))
        lines.append('    </busStop>')
    lines.append('</additional>')
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def _schedule(route, stops, t0, slack=1.15):
    """Return [(stop_id, until)] for a departure at t0."""
    out = []
    t = t0
    stop_by_edge = {s[1]: s[0] for s in stops}
    for e in route:
        if e in stop_by_edge:
            # 40 m into the edge before the stop end position
            t += (40.0 / BW_SPEED) * slack
            out.append((stop_by_edge[e], int(round(t))))
            t += DWELL
            t += ((EDGE_LEN[e] - 40.0) / BW_SPEED) * slack
        else:
            t += (EDGE_LEN[e] / BW_SPEED) * slack
    return out


def write_pt(path, headway, begin, end, pm_begin=None, pm_end=None):
    lines = ['<routes>',
             '    <vType id="brt" vClass="bus" length="18.0" accel="1.2" decel="3.0" '
             'personCapacity="120" color="0,0.6,1"/>']
    n = 0
    spans = [(begin, end)]
    if pm_begin is not None:
        spans.append((pm_begin, pm_end))
    for (b, e) in spans:
        t = b
        while t <= e:
            for tag, route, stops in (("BRT_E", EB_ROUTE, EB_STOPS), ("BRT_W", WB_ROUTE, WB_STOPS)):
                lines.append('    <vehicle id="%s_%d" type="brt" line="%s" depart="%d" departPos="free">'
                             % (tag, n, tag, t))
                lines.append('        <route edges="%s"/>' % " ".join(route))
                for sid, until in _schedule(route, stops, t):
                    lines.append('        <stop busStop="%s" duration="%d" until="%d"/>'
                                 % (sid, DWELL, until))
                lines.append('    </vehicle>')
            n += 1
            t += headway
    lines.append('</routes>')
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def write_persons(path, n, begin, end, modes, seed, pm_share=0.0,
                  pm_begin=0, pm_end=0):
    rng = random.Random(seed)
    lines = ['<routes>',
             '    <vType id="car" vClass="passenger" length="5.0" color="1,0.6,0"/>']
    recs = []
    for i in range(n):
        o = rng.choice(SUB_ORIGIN_EDGES)
        d = rng.choice(CBD_DEST_EDGES)
        dep = rng.uniform(begin, end)
        recs.append(("am_%d" % i, dep, o, d))
    if pm_share > 0:
        for i in range(int(n * pm_share)):
            o = rng.choice(CBD_DEST_EDGES)
            d = rng.choice(SUB_ORIGIN_EDGES)
            dep = rng.uniform(pm_begin, pm_end)
            recs.append(("pm_%d" % i, dep, o, d))
    recs.sort(key=lambda r: r[1])
    for pid, dep, o, d in recs:
        lines.append('    <person id="%s" depart="%.1f">' % (pid, dep))
        lines.append('        <personTrip from="%s" to="%s" modes="%s" vTypes="car"/>'
                     % (o, d, modes))
        lines.append('    </person>')
    lines.append('</routes>')
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return len(recs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--cap-main", type=int, default=400)
    ap.add_argument("--cap-overflow", type=int, default=150)
    ap.add_argument("--cap-mid", type=int, default=400)
    ap.add_argument("--cap-mid2", type=int, default=400)
    ap.add_argument("--only-lots", default=None, help="comma list of parkingArea ids to keep")
    ap.add_argument("--headway", type=int, default=300)
    ap.add_argument("--persons", type=int, default=1200)
    ap.add_argument("--begin", type=int, default=0)
    ap.add_argument("--end", type=int, default=5400)
    ap.add_argument("--pt-end", type=int, default=9000)
    ap.add_argument("--modes", default="car public")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--pm-share", type=float, default=0.0)
    ap.add_argument("--pm-begin", type=int, default=0)
    ap.add_argument("--pm-end", type=int, default=0)
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    j = lambda f: os.path.join(a.out_dir, f)
    write_parking(j("parking.add.xml"), a.cap_main, a.cap_overflow, a.cap_mid, a.cap_mid2,
                  a.only_lots.split(",") if a.only_lots else None)
    write_stops(j("stops.add.xml"))
    write_pt(j("brt.rou.xml"), a.headway, 0, a.pt_end,
             a.pm_begin if a.pm_share > 0 else None,
             a.pm_end + 3600 if a.pm_share > 0 else None)
    n = write_persons(j("persons.trips.xml"), a.persons, a.begin, a.end, a.modes, a.seed,
                      a.pm_share, a.pm_begin, a.pm_end)
    print("wrote scenario in %s (%d persons)" % (a.out_dir, n))


if __name__ == "__main__":
    main()
