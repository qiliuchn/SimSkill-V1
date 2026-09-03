#!/usr/bin/env python3
"""Verify from the COMPILED nets that (1) the eastbound and westbound
representations of each physical lane occupy exactly the same pavement, and
(2) what permissions netconvert assigned to the INTERNAL junction connector
lanes in the open- vs closed-compiled variants.

Writes outputs/analysis/geometry_verification.json
"""
import json
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (NETDIR, ANADIR, PHYS_LANES, PHYS_Y, DIR_EDGES, lane_id,
                    ensure_dirs)


def parse(netfile):
    root = ET.parse(netfile).getroot()
    lanes, conns = {}, []
    for edge in root.findall("edge"):
        for lane in edge.findall("lane"):
            pts = [tuple(float(v) for v in p.split(","))
                   for p in lane.get("shape").split()]
            lanes[lane.get("id")] = dict(
                edge=edge.get("id"), function=edge.get("function", "normal"),
                allow=lane.get("allow"), disallow=lane.get("disallow"),
                length=float(lane.get("length")),
                y_start=pts[0][1], y_end=pts[-1][1])
    for c in root.findall("connection"):
        conns.append(c.attrib)
    return lanes, conns


def main():
    ensure_dirs()
    res = {}
    for name in ("encB_open", "encB_closed"):
        nf = os.path.join(NETDIR, name + ".net.xml")
        lanes, conns = parse(nf)

        # --- (1) geometric coincidence, on the 3 km corridor edges
        geom = {}
        for phys in PHYS_LANES:
            eb = lane_id("EB", "COR_EB", phys)
            wb = lane_id("WB", "COR_WB", phys)
            # westbound lane runs the other way: compare its END to EB's START
            dy1 = abs(lanes[eb]["y_start"] - lanes[wb]["y_end"])
            dy2 = abs(lanes[eb]["y_end"] - lanes[wb]["y_start"])
            geom[phys] = dict(
                design_y=PHYS_Y[phys], eb_lane=eb, wb_lane=wb,
                eb_y=[round(lanes[eb]["y_start"], 3), round(lanes[eb]["y_end"], 3)],
                wb_y=[round(lanes[wb]["y_start"], 3), round(lanes[wb]["y_end"], 3)],
                max_lateral_offset_m=round(max(dy1, dy2), 4),
                coincident=max(dy1, dy2) < 0.01,
                eb_length=round(lanes[eb]["length"], 2),
                wb_length=round(lanes[wb]["length"], 2),
                eb_permissions=dict(allow=lanes[eb]["allow"], disallow=lanes[eb]["disallow"]),
                wb_permissions=dict(allow=lanes[wb]["allow"], disallow=lanes[wb]["disallow"]),
            )

        # --- (2) internal connector permissions for the reversible lanes
        internals = {}
        for d in ("EB", "WB"):
            edges = DIR_EDGES[d]
            for phys in ("L3", "L4"):
                for a, b in zip(edges[:-1], edges[1:]):
                    frm = lane_id(d, a, phys)
                    fe, fi = frm.rsplit("_", 1)
                    hit = [c for c in conns
                           if c.get("from") == fe and c.get("fromLane") == fi
                           and c.get("to") == b]
                    for c in hit:
                        via = c.get("via")
                        il = lanes.get(via, {})
                        internals[f"{d}:{frm}->{b}_{c.get('toLane')}"] = dict(
                            via=via, internal_allow=il.get("allow"),
                            internal_disallow=il.get("disallow"))
        res[name] = dict(net=nf, corridor_lane_geometry=geom,
                         internal_connector_permissions=internals)

    # concise summary of the trap test
    summary = {}
    for name in res:
        ic = res[name]["internal_connector_permissions"]
        restricted = {k: v for k, v in ic.items()
                      if v["internal_allow"] not in (None, "")}
        summary[name] = dict(
            n_internal_connectors_checked=len(ic),
            n_internal_connectors_restricted=len(restricted),
            restricted=restricted,
            all_six_lane_pairs_coincident=all(
                g["coincident"] for g in res[name]["corridor_lane_geometry"].values()))
    res["_summary"] = summary

    out = os.path.join(ANADIR, "geometry_verification.json")
    with open(out, "w") as f:
        json.dump(res, f, indent=2)
    print(json.dumps(res["encB_open"]["corridor_lane_geometry"], indent=2))
    print("\n--- SUMMARY ---")
    print(json.dumps(summary, indent=2))
    print("\nwrote", out)


if __name__ == "__main__":
    main()
