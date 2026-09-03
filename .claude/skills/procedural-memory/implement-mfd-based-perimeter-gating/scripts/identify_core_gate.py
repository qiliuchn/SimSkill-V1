#!/usr/bin/env python3
"""
Programmatically identify the CORE region and the GATE set of a netgenerate grid,
by parsing the COMPILED .net.xml only (no hand-written junction/edge lists).

Method
------
1. Read every non-internal junction that is signal-controlled.
2. Take the sorted unique x-coordinates and y-coordinates of those junctions
   (a netgenerate grid is a rectangular lattice).  The CORE is the cartesian
   product of the middle `core_n` x-values and the middle `core_n` y-values.
3. CORE EDGES = normal edges whose `from` AND `to` are both core junctions
   (i.e. edges lying wholly inside the core block).
4. GATE EDGES = normal edges whose `to` is a core junction and whose `from`
   is NOT a core junction  (the inbound connections feeding the core).
5. GATE JUNCTIONS = the `from` junctions of the gate edges.  These are the
   signals whose into-core movements the perimeter controller throttles.
6. ENTRY / EXIT edges = edges leaving / arriving at a dead-end junction
   (the netgenerate `--grid.attach-length` stubs) -- the network's sources
   and sinks.

Everything is written to core_gate.json.
"""
import argparse
import json
import xml.etree.ElementTree as ET


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", required=True)
    ap.add_argument("--core-n", type=int, default=3,
                    help="side length (in junctions) of the inner core block")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    root = ET.parse(args.net).getroot()

    junctions = {}
    for j in root.findall("junction"):
        if j.get("function") == "internal" or j.get("type") == "internal":
            continue
        junctions[j.get("id")] = {
            "x": float(j.get("x")), "y": float(j.get("y")), "type": j.get("type")
        }

    tls_junctions = {k: v for k, v in junctions.items() if v["type"] == "traffic_light"}
    dead_ends = {k for k, v in junctions.items() if v["type"] == "dead_end"}

    def middle(vals, n):
        vals = sorted(set(round(v, 3) for v in vals))
        k = len(vals)
        start = (k - n) // 2
        return set(vals[start:start + n])

    mid_x = middle([v["x"] for v in tls_junctions.values()], args.core_n)
    mid_y = middle([v["y"] for v in tls_junctions.values()], args.core_n)

    core_junctions = sorted(
        k for k, v in tls_junctions.items()
        if round(v["x"], 3) in mid_x and round(v["y"], 3) in mid_y
    )
    core_set = set(core_junctions)

    edges = []
    for e in root.findall("edge"):
        if e.get("function") == "internal":
            continue
        edges.append({
            "id": e.get("id"), "from": e.get("from"), "to": e.get("to"),
            "lanes": [l.get("id") for l in e.findall("lane")],
            "length": float(e.findall("lane")[0].get("length")),
        })

    core_edges = sorted(e["id"] for e in edges
                        if e["from"] in core_set and e["to"] in core_set)
    gate_edges = sorted(e["id"] for e in edges
                        if e["to"] in core_set and e["from"] not in core_set)
    core_outbound_edges = sorted(e["id"] for e in edges
                                 if e["from"] in core_set and e["to"] not in core_set)
    gate_junctions = sorted({e["from"] for e in edges
                             if e["to"] in core_set and e["from"] not in core_set})

    entry_edges = sorted(e["id"] for e in edges if e["from"] in dead_ends)
    exit_edges = sorted(e["id"] for e in edges if e["to"] in dead_ends)

    by_id = {e["id"]: e for e in edges}
    core_lane_ids = [l for eid in core_edges for l in by_id[eid]["lanes"]]
    core_length_m = sum(by_id[eid]["length"] for eid in core_edges)

    # side of each entry/exit stub, derived from the dead-end coordinate
    xs = [junctions[d]["x"] for d in dead_ends]
    ys = [junctions[d]["y"] for d in dead_ends]
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)

    def side_of(dj):
        x, y = junctions[dj]["x"], junctions[dj]["y"]
        if abs(x - xmin) < 1e-6:
            return "left"
        if abs(x - xmax) < 1e-6:
            return "right"
        if abs(y - ymin) < 1e-6:
            return "bottom"
        if abs(y - ymax) < 1e-6:
            return "top"
        return "?"

    entry_side = {e["id"]: side_of(e["from"]) for e in edges if e["from"] in dead_ends}
    exit_side = {e["id"]: side_of(e["to"]) for e in edges if e["to"] in dead_ends}

    out = {
        "net": args.net,
        "core_n": args.core_n,
        "core_junctions": core_junctions,
        "core_edges": core_edges,
        "core_lanes": core_lane_ids,
        "core_total_lane_km": round(core_length_m / 1000.0, 4),
        "gate_junctions": gate_junctions,
        "gate_edges": gate_edges,
        "core_outbound_edges": core_outbound_edges,
        "entry_edges": entry_edges,
        "exit_edges": exit_edges,
        "entry_side": entry_side,
        "exit_side": exit_side,
        "n_tls": len(tls_junctions),
    }
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)

    print(f"signalized junctions : {len(tls_junctions)}")
    print(f"core junctions ({len(core_junctions)}) : {core_junctions}")
    print(f"core edges ({len(core_edges)}), total lane-km = {out['core_total_lane_km']}")
    print(f"gate junctions ({len(gate_junctions)}) : {gate_junctions}")
    print(f"gate edges ({len(gate_edges)}) : {gate_edges}")
    print(f"entry edges {len(entry_edges)}, exit edges {len(exit_edges)}")


if __name__ == "__main__":
    main()
