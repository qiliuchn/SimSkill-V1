#!/usr/bin/env python3
"""Shared parsing / metric utilities for the MRM study."""
import math
import os
import xml.etree.ElementTree as ET

WD = "/private/tmp/claude-501/-Users-liuqi-Desktop-simskill/07cb182d-88df-492d-b918-d753d888c5e5/scratchpad/mrm"

STUDY_EDGES = ["D3E3", "E3D3", "D4E4", "E4D4", "D3D4", "D4D3", "E3E4", "E4E3"]
BUFFER1_EDGES = ["C3D3", "D3C3", "F3E3", "E3F3", "D2D3", "D3D2", "E4E5", "E5E4"]
BUFFER2_EDGES = ["B3C3", "C3B3", "G3F3", "F3G3", "D1D2", "D2D1", "E5E6", "E6E5"]
BUFFER3_EDGES = ["A3B3", "B3A3", "H3G3", "G3H3", "D0D1", "D1D0", "E6E7", "E7E6"]

BUFFER_BOX = {
    0: (660.0, 660.0, 880.0, 880.0),
    1: (440.0, 440.0, 1100.0, 1100.0),
    2: (220.0, 220.0, 1320.0, 1320.0),
    3: (0.0, 0.0, 1540.0, 1540.0),
}


def geh(m, c):
    if m + c <= 0:
        return 0.0
    return math.sqrt(2.0 * (m - c) ** 2 / (m + c))


def read_edgedata(path, edge_ids=None):
    """Return {edge_id: {attr: float}} for the single <interval>."""
    root = ET.parse(path).getroot()
    iv = root.find("interval")
    out = {}
    for e in iv.findall("edge"):
        eid = e.get("id")
        if edge_ids is not None and eid not in edge_ids:
            continue
        d = {}
        for k in ("sampledSeconds", "speed", "traveltime", "timeLoss",
                   "waitingTime", "departed", "arrived", "entered", "left",
                   "density", "laneDensity"):
            v = e.get(k)
            d[k] = float(v) if v is not None else None
        out[eid] = d
    return out


def read_edgedata_intervals(path, edge_ids=None):
    """For the fine-grained (multi-interval) edgeData file: return
    {edge_id: [(begin,end,{attrs}), ...]}"""
    root = ET.parse(path).getroot()
    out = {}
    for iv in root.findall("interval"):
        b, e_ = float(iv.get("begin")), float(iv.get("end"))
        for edge in iv.findall("edge"):
            eid = edge.get("id")
            if edge_ids is not None and eid not in edge_ids:
                continue
            d = {}
            for k in ("sampledSeconds", "speed", "timeLoss", "waitingTime",
                       "entered", "left", "departed", "arrived"):
                v = edge.get(k)
                d[k] = float(v) if v is not None else None
            out.setdefault(eid, []).append((b, e_, d))
    return out


def read_tripinfo(path):
    root = ET.parse(path).getroot()
    trips = []
    for t in root.findall("tripinfo"):
        trips.append({
            "id": t.get("id"), "depart": float(t.get("depart")),
            "departDelay": float(t.get("departDelay")),
            "arrival": float(t.get("arrival")),
            "duration": float(t.get("duration")),
            "routeLength": float(t.get("routeLength")),
            "timeLoss": float(t.get("timeLoss")),
            "waitingTime": float(t.get("waitingTime")),
        })
    return trips


def vht_vkt(trips):
    """Vehicle-hours-traveled / vehicle-km-traveled over a trip list."""
    vht = sum(t["duration"] for t in trips) / 3600.0
    vkt = sum(t["routeLength"] for t in trips) / 1000.0
    return vht, vkt


def count_teleports(stderr_log):
    if not os.path.exists(stderr_log):
        return 0, []
    n = 0
    edges = []
    with open(stderr_log) as fh:
        for line in fh:
            # actual SUMO 1.27 format: "Warning: Teleporting vehicle 'X';
            # waited too long (reason), lane='EDGE_LANE', time=T."
            if "Teleporting vehicle" in line:
                n += 1
                if "lane='" in line:
                    lane = line.split("lane='")[1].split("'")[0]
                    edges.append(lane.rsplit("_", 1)[0])
    return n, edges


def mean_ci95(vals):
    n = len(vals)
    if n == 0:
        return float("nan"), float("nan"), float("nan")
    m = sum(vals) / n
    if n < 2:
        return m, float("nan"), float("nan")
    var = sum((v - m) ** 2 for v in vals) / (n - 1)
    sd = math.sqrt(var)
    # t critical value approx (small tables for typical small n)
    tcrit = {2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776, 6: 2.571, 7: 2.447,
             8: 2.365, 9: 2.306, 10: 2.262}.get(n, 1.96)
    hw = tcrit * sd / math.sqrt(n)
    return m, sd, hw
