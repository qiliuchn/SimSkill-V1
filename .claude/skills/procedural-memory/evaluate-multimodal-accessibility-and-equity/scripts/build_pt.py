#!/usr/bin/env python3
"""Hand-author the public-transport layer (busStops + scheduled lines) for the
base/A network and for policy B (halved headways + peripheral feeder route).

Every stop gets an <access> child linking the driving lane to the sidewalk lane,
and every <stop> carries an absolute `until=` timetable -- without `until` the
duarouter intermodal router silently resolves every person to walk-only
(see [[public-transport-and-intermodal-routing]]).
"""
import os
import sys
import json

SUMO_HOME = os.environ["SUMO_HOME"]
sys.path.append(os.path.join(SUMO_HOME, "tools"))
import sumolib  # noqa: E402

WORK = sys.argv[1]
NET = sumolib.net.readNet(os.path.join(WORK, "base.net.xml"))

HORIZON = 5400          # generate departures over 0..HORIZON s
DWELL = 20              # s per stop
BUS_SPEED_FACTOR = 0.75  # buses realise ~75% of free-flow link speed (accel/decel)

# ---------------------------------------------------------------- line defs
def arm_route(arm, inbound):
    """radial route along one arm between ring G (outer) and the centre A1"""
    letters = ["G", "F", "E", "D", "C", "B", "A"]
    nodes = [("A1" if L == "A" else "%s%d" % (L, arm)) for L in letters]
    if not inbound:
        nodes = nodes[::-1]
    return ["%s%s" % (nodes[i], nodes[i + 1]) for i in range(len(nodes) - 1)]


def ring_route(letter, cw):
    order = list(range(1, 9)) + [1]
    if not cw:
        order = order[::-1]
    return ["%s%d%s%d" % (letter, order[i], letter, order[i + 1]) for i in range(8)]


BASE_LINES = {}
for arm, hw in ((1, 600), (3, 600), (7, 900)):
    BASE_LINES["L%d_in" % arm] = dict(route=arm_route(arm, True), headway=hw, offset=0)
    BASE_LINES["L%d_out" % arm] = dict(route=arm_route(arm, False), headway=hw, offset=hw // 2)
BASE_LINES["LC_cw"] = dict(route=ring_route("C", True), headway=600, offset=0)
BASE_LINES["LC_ccw"] = dict(route=ring_route("C", False), headway=600, offset=300)

FEEDER = ["C5D5", "D5E5", "E5F5", "F5G5", "G5G6", "G6G7", "G7G8",
          "G8F8", "F8E8", "E8D8", "D8C8", "C8C7", "C7C6", "C6C5"]

ALT_B_LINES = {}
for k, v in BASE_LINES.items():
    ALT_B_LINES[k] = dict(route=v["route"], headway=v["headway"] // 2,
                          offset=v["offset"] // 2)
ALT_B_LINES["LF"] = dict(route=FEEDER, headway=600, offset=0)


def bus_lane(edge_id):
    e = NET.getEdge(edge_id)
    for l in e.getLanes():
        if l.allows("bus"):
            return l
    return None


def ped_lane(edge_id):
    e = NET.getEdge(edge_id)
    for l in e.getLanes():
        if l.allows("pedestrian"):
            return l
    return None


def build(lines, tag):
    """emit <tag>_busstops.add.xml and <tag>_ptvehicles.rou.xml"""
    stops = {}          # stop id -> (edge, lane, startPos, endPos, lines)
    line_stops = {}     # line -> list of (stop_id, edge_index)
    for ln, spec in lines.items():
        seq = []
        for i, eid in enumerate(spec["route"]):
            bl = bus_lane(eid)
            pl = ped_lane(eid)
            if bl is None or pl is None:
                continue
            L = NET.getEdge(eid).getLength()
            if L < 40:
                continue
            start, end = max(5.0, L - 35.0), max(20.0, L - 15.0)
            sid = "bs_%s" % eid
            if sid not in stops:
                stops[sid] = dict(edge=eid, lane=bl.getID(), ped=pl.getID(),
                                  start=start, end=end, lines=set())
            stops[sid]["lines"].add(ln)
            seq.append((sid, i))
        line_stops[ln] = seq

    with open(os.path.join(WORK, "%s_busstops.add.xml" % tag), "w") as f:
        f.write("<additional>\n")
        for sid, s in sorted(stops.items()):
            f.write('    <busStop id="%s" lane="%s" startPos="%.1f" endPos="%.1f" '
                    'lines="%s" friendlyPos="true">\n'
                    % (sid, s["lane"], s["start"], s["end"], " ".join(sorted(s["lines"]))))
            f.write('        <access lane="%s" pos="%.1f"/>\n'
                    % (s["ped"], (s["start"] + s["end"]) / 2.0))
            f.write("    </busStop>\n")
        f.write("</additional>\n")

    with open(os.path.join(WORK, "%s_ptvehicles.rou.xml" % tag), "w") as f:
        f.write("<routes>\n")
        f.write('    <vType id="bus" vClass="bus" length="12" maxSpeed="18" '
                'accel="1.2" decel="2.5" personCapacity="60"/>\n')
        nveh = 0
        for ln, spec in sorted(lines.items()):
            route = spec["route"]
            seq = line_stops[ln]
            # free-flow-ish cumulative running time to each stop
            cum, t = {}, 0.0
            for i, eid in enumerate(route):
                e = NET.getEdge(eid)
                t += e.getLength() / (min(e.getSpeed(), 18.0) * BUS_SPEED_FACTOR)
                cum[i] = t
            dep = spec["offset"]
            while dep <= HORIZON:
                f.write('    <vehicle id="%s.%d" type="bus" line="%s" depart="%d" '
                        'departPos="0" departLane="best">\n' % (ln, nveh, ln, dep))
                f.write('        <route edges="%s"/>\n' % " ".join(route))
                for k, (sid, i) in enumerate(seq):
                    until = dep + cum[i] + DWELL * (k + 1)
                    f.write('        <stop busStop="%s" duration="%d" until="%d"/>\n'
                            % (sid, DWELL, int(round(until))))
                f.write("    </vehicle>\n")
                nveh += 1
                dep += spec["headway"]
        f.write("</routes>\n")
    print("%s: %d stops, %d bus vehicles, lines=%s"
          % (tag, len(stops), nveh, sorted(lines)))
    return stops, line_stops


stops_base, ls_base = build(BASE_LINES, "base")
stops_b, ls_b = build(ALT_B_LINES, "altB")
import shutil
for ext in ("busstops.add.xml", "ptvehicles.rou.xml"):
    shutil.copy(os.path.join(WORK, "base_" + ext), os.path.join(WORK, "altA_" + ext))

json.dump(dict(base={k: dict(route=v["route"], headway=v["headway"]) for k, v in BASE_LINES.items()},
               altB={k: dict(route=v["route"], headway=v["headway"]) for k, v in ALT_B_LINES.items()},
               n_stops_base=len(stops_base), n_stops_altB=len(stops_b)),
          open(os.path.join(WORK, "pt_lines.json"), "w"), indent=1)
