#!/usr/bin/env python3
"""Reusable parser for SUMO .rou.alt.xml route-alternatives files.

Deliverable script for sub-goal 7 ("alt-file probability parser"), used throughout
sub-goals 1, 2, 3 of the route-choice-model investigation.
"""
import xml.etree.ElementTree as ET


def parse_alt_file(path):
    """Return {vehicle_id: [(edges_str, cost_float, probability_float), ...]} in file order."""
    tree = ET.parse(path)
    root = tree.getroot()
    out = {}
    for veh in root.findall("vehicle"):
        vid = veh.get("id")
        routes = []
        rd = veh.find("routeDistribution")
        if rd is None:
            continue
        for r in rd.findall("route"):
            edges = r.get("edges")
            cost = float(r.get("cost"))
            prob = float(r.get("probability"))
            routes.append((edges, cost, prob))
        out[vid] = routes
    return out


def parse_alt_file_flows(path):
    """Same as parse_alt_file but also handles <flow> elements (duarouter can emit either)."""
    tree = ET.parse(path)
    root = tree.getroot()
    out = {}
    for tag in ("vehicle", "flow"):
        for veh in root.findall(tag):
            vid = veh.get("id")
            routes = []
            rd = veh.find("routeDistribution")
            if rd is None:
                continue
            for r in rd.findall("route"):
                edges = r.get("edges")
                cost = float(r.get("cost"))
                prob = float(r.get("probability"))
                routes.append((edges, cost, prob))
            out[vid] = routes
    return out


if __name__ == "__main__":
    import sys
    import json
    data = parse_alt_file_flows(sys.argv[1])
    print(json.dumps(data, indent=2))
