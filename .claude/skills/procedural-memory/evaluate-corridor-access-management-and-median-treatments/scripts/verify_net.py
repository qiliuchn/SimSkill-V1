#!/usr/bin/env python3
"""Verify compiled net.xml for candidates A and C: intended movements present,
unintended movements absent, and print the full connection table for manual
inspection."""
import os
import sys
sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import sumolib

root = os.path.dirname(os.path.abspath(__file__))

for cand in ["candA", "candC"]:
    print(f"\n===== {cand} =====")
    net = sumolib.net.readNet(os.path.join(root, cand, "net.net.xml"), withInternal=True)
    for edge in sorted(net.getEdges(), key=lambda e: e.getID()):
        eid = edge.getID()
        if not (eid.startswith("MED") or eid.startswith("IN_") or eid.startswith("OUT_")):
            continue
        for conn in edge.getOutgoing():
            for lane_conn in edge.getOutgoing()[conn]:
                print(f"  {eid} -> {conn.getID()}  dir={lane_conn.getDirection()} "
                      f"state={lane_conn.getState()} viaLaneID={lane_conn.getViaLaneID()}")

    # check median edges: are both directions genuinely present as separate lanes at same coords?
    med_edges = [e for e in net.getEdges() if e.getID().startswith("MED")]
    print(f"  {len(med_edges)} median edge segments found")
    for e in med_edges:
        shp = e.getShape()
        print(f"   {e.getID()}: from={e.getFromNode().getID()} to={e.getToNode().getID()} "
              f"numLanes={e.getLaneNumber()} shape={shp}")
