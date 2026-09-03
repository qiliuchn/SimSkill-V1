#!/usr/bin/env python3
"""
Field instrumentation.

  1. MOVEMENT stop-bar E1 loops.  One <inductionLoop> is placed at the head of
     every junction-INTERNAL lane, i.e. immediately past the stop bar.  An
     internal lane is by construction (fromLane -> toEdge), so summing the loops
     that belong to one turning movement yields exactly the DEPARTURES across
     the stop bar for that movement -- which is what a TMC / video / ATSPM count
     actually records.  Aggregated at 900 s.
  2. LANE stop-bar E1 loops on every approach lane, 2 m upstream of the stop
     line, aggregated at 900 s.  Independent cross-check of (1) and the source
     of lane occupancy.
  3. Stop-bar instant loops on the J1 eastbound approach only (3 lanes) -- the
     per-vehicle crossing times needed to MEASURE saturation flow.  Restricted to
     one approach because instant-loop output is per-step-per-vehicle and would
     otherwise be hundreds of MB.
  4. MID-BLOCK / ATR E1 stations 1900 m upstream of the J1 EB and J3 WB stop
     bars, deliberately beyond the peak back of queue (verified in verify_run.py
     against the E2 maximum jam length).
  5. E2 laneAreaDetector queue chains covering each approach's left bay and
     through lanes plus as much of the feed as the link allows -- the queue
     measurement the residual-queue correction consumes.

SUMO resolves an additional file's `file=` attribute relative to THAT FILE's own
directory, so a copy of the additional file is written into every run directory.
"""
import os
import xml.etree.ElementTree as ET

from common import (SCEN, NET, JUNCTIONS, EB_BAY, WB_BAY, EB_FEED, WB_FEED,
                    SB_IN, NB_IN, BIN)

STOPBAR_POS = -2.0
INTERNAL_POS = 0.5
ATR_POS = 100.0
ATR_EDGE = {"EB": "eb_WF_J1_feed", "WB": "wb_EF_J3_feed"}

FEED_LEN = {"eb_WF_J1_feed": 2000.0, "wb_EF_J3_feed": 2000.0,
            "eb_MB_J2_feed": 120.0, "wb_MB_J1_feed": 120.0,
            "eb_J2_J3_feed": 320.0, "wb_J3_J2_feed": 320.0}
MAX_CHAIN_FEED = 1e9   # cover the FULL approach: a partial chain
                       # silently truncates the storage-based queue correction

DIR2MV = {"s": "T", "l": "L", "r": "R"}


def movement_internal_lanes(net_path=NET):
    """{(J, approach, movement): [internal lane ids]} from the COMPILED net."""
    root = ET.parse(net_path).getroot()
    app_of = {}
    for j in JUNCTIONS:
        app_of[EB_BAY[j]] = (j, "EB")
        app_of[WB_BAY[j]] = (j, "WB")
        app_of[SB_IN[j]] = (j, "SB")
        app_of[NB_IN[j]] = (j, "NB")
    out = {}
    for c in root.findall("connection"):
        frm = c.get("from")
        if frm not in app_of or c.get("tl") is None:
            continue
        j, app = app_of[frm]
        m = DIR2MV[c.get("dir")]
        out.setdefault((j, app, m), []).append(c.get("via"))
    return out


def approach_lane_chains():
    out = {}
    for j in JUNCTIONS:
        for app, bay, feed in (("EB", EB_BAY[j], EB_FEED[j]),
                               ("WB", WB_BAY[j], WB_FEED[j])):
            flen = FEED_LEN[feed]
            pos = flen - min(flen, MAX_CHAIN_FEED)
            out[(j, app, "F0")] = ([feed + "_0", bay + "_0"], pos, ["T", "R"])
            out[(j, app, "F1")] = ([feed + "_1", bay + "_1"], pos, ["T", "L"])
            out[(j, app, "BAY")] = ([bay + "_2"], 0.0, ["L"])
        for app, edge in (("SB", SB_IN[j]), ("NB", NB_IN[j])):
            out[(j, app, "ALL")] = ([edge + "_0"], 0.0, ["L", "T", "R"])
    return out


def approach_lanes():
    out = {}
    for j in JUNCTIONS:
        out[(j, "EB")] = [EB_BAY[j] + "_%d" % i for i in range(3)]
        out[(j, "WB")] = [WB_BAY[j] + "_%d" % i for i in range(3)]
        out[(j, "SB")] = [SB_IN[j] + "_0"]
        out[(j, "NB")] = [NB_IN[j] + "_0"]
    return out


SEGMENT_TARGET = 250.0     # HCM-style intersection influence area, m


def e3_segments(net_path=NET):
    """{(J, approach): (entry lane/pos list, exit lane/pos list, segment length)}

    An E3 entry cross-section is placed SEGMENT_TARGET metres upstream of the
    stop bar where the approach is long enough, otherwise as far back as the
    approach allows; the segment length actually achieved is returned and
    reported with every delay figure (a segment-scoped delay is only comparable
    against another measurement over the same segment).
    """
    import sys as _s
    _s.path.insert(0, os.path.join(os.environ.get(
        "SUMO_HOME", "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/"
                     "EclipseSUMO/share/sumo"), "tools"))
    import sumolib
    net = sumolib.net.readNet(net_path)
    out = {}
    for j in JUNCTIONS:
        for app, aedge, feed in (("EB", EB_BAY[j], EB_FEED[j]),
                                 ("WB", WB_BAY[j], WB_FEED[j]),
                                 ("SB", SB_IN[j], None), ("NB", NB_IN[j], None)):
            a = net.getEdge(aedge)
            alen = a.getLength()
            entries = []
            if feed is None:
                pos = max(10.0, alen - SEGMENT_TARGET)
                seg = alen - pos
                entries = [(l.getID(), pos) for l in a.getLanes()]
            else:
                fe = net.getEdge(feed)
                flen = fe.getLength()
                need = SEGMENT_TARGET - alen
                pos = max(10.0, flen - need)
                seg = (flen - pos) + alen
                entries = [(l.getID(), pos) for l in fe.getLanes()]
            exits = []
            for to_edge in a.getOutgoing():
                for l in to_edge.getLanes():
                    exits.append((l.getID(), min(20.0, to_edge.getLength() - 5.0)))
            out[(j, app)] = (entries, exits, seg)
    return out


def additional_xml():
    L = ['<additional>']
    for (j, app), (ent, ex, seg) in sorted(e3_segments().items()):
        L.append('  <entryExitDetector id="e3_%s_%s" period="%d" file="e3_delay.xml" '
                 'timeThreshold="1" speedThreshold="1.39" openEntry="false">'
                 % (j, app, BIN))
        for lane, pos in ent:
            L.append('    <detEntry lane="%s" pos="%.2f"/>' % (lane, pos))
        for lane, pos in ex:
            L.append('    <detExit lane="%s" pos="%.2f"/>' % (lane, pos))
        L.append('  </entryExitDetector>')
    for (j, app, m), lanes in sorted(movement_internal_lanes().items()):
        for k, lane in enumerate(lanes):
            L.append('  <inductionLoop id="mv_%s_%s_%s_%d" lane="%s" pos="%.1f" '
                     'period="%d" friendlyPos="true" file="e1_movement.xml"/>'
                     % (j, app, m, k, lane, INTERNAL_POS, BIN))
            L.append('  <inductionLoop id="hv_%s_%s_%s_%d" lane="%s" pos="%.1f" '
                     'period="%d" friendlyPos="true" vTypes="hgv" file="e1_movement.xml"/>'
                     % (j, app, m, k, lane, INTERNAL_POS, BIN))
    for (j, app), lanes in sorted(approach_lanes().items()):
        for k, lane in enumerate(lanes):
            L.append('  <inductionLoop id="sb_%s_%s_l%d" lane="%s" pos="%.1f" '
                     'period="%d" file="e1_stopbar.xml"/>' % (j, app, k, lane, STOPBAR_POS, BIN))
    for k in range(3):
        L.append('  <instantInductionLoop id="ib_J1_EB_l%d" lane="%s_%d" pos="%.1f" '
                 'file="e1_instant.xml"/>' % (k, EB_BAY["J1"], k, STOPBAR_POS))
    for d, edge in sorted(ATR_EDGE.items()):
        for k in (0, 1):
            L.append('  <inductionLoop id="atr_%s_l%d" lane="%s_%d" pos="%.1f" '
                     'period="%d" file="e1_atr.xml"/>' % (d, k, edge, k, ATR_POS, BIN))
            L.append('  <inductionLoop id="atrhv_%s_l%d" lane="%s_%d" pos="%.1f" '
                     'period="%d" vTypes="hgv" file="e1_atr.xml"/>'
                     % (d, k, edge, k, ATR_POS, BIN))
    for (j, app, key), (lanes, pos, _mv) in sorted(approach_lane_chains().items()):
        L.append('  <laneAreaDetector id="q_%s_%s_%s" lanes="%s" pos="%.1f" endPos="-0.5" '
                 'period="%d" file="e2_queue.xml"/>'
                 % (j, app, key, " ".join(lanes), pos, BIN))
    L.append('</additional>')
    return "\n".join(L) + "\n"


ADD_TEMPLATE = os.path.join(SCEN, "detectors.add.xml")


def write_template():
    with open(ADD_TEMPLATE, "w") as f:
        f.write(additional_xml())
    return ADD_TEMPLATE


def write_for_run(run_dir):
    os.makedirs(run_dir, exist_ok=True)
    p = os.path.join(run_dir, "detectors.add.xml")
    with open(p, "w") as f:
        f.write(additional_xml())
    return p


if __name__ == "__main__":
    mil = movement_internal_lanes()
    for k in sorted(mil):
        print(k, mil[k])
    p = write_template()
    print("wrote", p, "with", sum(1 for l in open(p) if "<" in l) - 2, "detectors")
