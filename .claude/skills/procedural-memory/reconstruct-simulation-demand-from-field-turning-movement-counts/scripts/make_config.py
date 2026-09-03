#!/usr/bin/env python3
"""Write the corridor configuration counts_to_demand.py consumes.

Everything here is information a real analyst has: which intersections were
counted, which edge each approach is, where each corridor entry is, which
movements at one intersection feed which approach at the next, the free-flow
link travel time, and which queue detectors cover which approach.  No demand
information is included.
"""
import json
import os

from common import (SCEN, JUNCTIONS, EB_BAY, WB_BAY, EB_FEED, WB_FEED,
                    SB_IN, NB_IN, DESIGN_SPEED)

CFG = os.path.join(SCEN, "corridor_config.json")
SPACING = 400.0


def build():
    approach_edge, origin_edge, queue_map = {}, {}, {}
    for j in JUNCTIONS:
        approach_edge["%s|EB" % j] = EB_BAY[j]
        approach_edge["%s|WB" % j] = WB_BAY[j]
        approach_edge["%s|SB" % j] = SB_IN[j]
        approach_edge["%s|NB" % j] = NB_IN[j]
        origin_edge["%s|EB" % j] = EB_FEED[j]
        origin_edge["%s|WB" % j] = WB_FEED[j]
        origin_edge["%s|SB" % j] = SB_IN[j]
        origin_edge["%s|NB" % j] = NB_IN[j]
        for app in ("EB", "WB"):
            queue_map["%s|%s" % (j, app)] = ["q_%s_%s_F0" % (j, app),
                                             "q_%s_%s_F1" % (j, app),
                                             "q_%s_%s_BAY" % (j, app)]
        for app in ("SB", "NB"):
            queue_map["%s|%s" % (j, app)] = ["q_%s_%s_ALL" % (j, app)]

    entries = [["J1", "EB"], ["J3", "WB"]] + \
              [[j, app] for j in JUNCTIONS for app in ("SB", "NB")]

    EB_UP = [["EB", "T"], ["SB", "L"], ["NB", "R"]]
    WB_UP = [["WB", "T"], ["NB", "L"], ["SB", "R"]]
    links = [
        dict(name="EB_J1_J2", up_j="J1", up_mv=EB_UP, down_j="J2", down_app="EB"),
        dict(name="EB_J2_J3", up_j="J2", up_mv=EB_UP, down_j="J3", down_app="EB"),
        dict(name="WB_J3_J2", up_j="J3", up_mv=WB_UP, down_j="J2", down_app="WB"),
        dict(name="WB_J2_J1", up_j="J2", up_mv=WB_UP, down_j="J1", down_app="WB"),
    ]
    tt = {L["name"]: round(SPACING / DESIGN_SPEED, 2) for L in links}

    cfg = dict(junctions=JUNCTIONS, approach_edge=approach_edge,
               origin_edge_map=origin_edge, entries=entries, links=links,
               travel_time=tt, queue_map=queue_map, pending_approach="J1|EB",
               spacing_m=SPACING, design_speed_mps=DESIGN_SPEED)
    with open(CFG, "w") as f:
        json.dump(cfg, f, indent=1)
    return CFG


if __name__ == "__main__":
    print("wrote", build())
