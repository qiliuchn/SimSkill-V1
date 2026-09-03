"""
Generate a straight single-corridor network as one or more elevation variants
-- geometrically identical in plan (x/y), differing only in node z-coordinates
(a constant grade) -- compile each with netconvert, and verify the REALIZED
per-edge slope by reading it back from the compiled net.xml's own lane-shape
z-coordinates. Never assume the grade took effect; always read it back.

Usage:
    python gen_gradient_corridor.py --out-dir net/ --n-edges 4 --edge-length 400 \
        --grades flat:0.0,uphill:0.04,downhill:-0.04 --speed 13.9
"""

import argparse
import os
import subprocess
import xml.etree.ElementTree as ET


def parse_args():
    p = argparse.ArgumentParser(description="Generate elevation-differing straight-corridor network variants and verify realized slope.")
    p.add_argument("--out-dir", default="net")
    p.add_argument("--n-edges", type=int, default=4)
    p.add_argument("--edge-length", type=float, default=400.0)
    p.add_argument("--grades", required=True, help='Comma-separated "name:dz_dx" pairs, e.g. "flat:0.0,uphill:0.04,downhill:-0.04"')
    p.add_argument("--speed", type=float, default=13.9, help="Edge speed limit (m/s)")
    p.add_argument("--num-lanes", type=int, default=1)
    return p.parse_args()


def node_ids(n_edges):
    return [chr(ord("A") + i) for i in range(n_edges + 1)]


def write_variant(out_dir, name, grade, n_edges, edge_len, speed, num_lanes):
    ids = node_ids(n_edges)
    xs = [i * edge_len for i in range(n_edges + 1)]

    nod = ['<?xml version="1.0" encoding="UTF-8"?>', "<nodes>"]
    for nid, x in zip(ids, xs):
        z = round(grade * x, 3)
        nod.append(f'    <node id="{nid}" x="{x}" y="0.0" z="{z}"/>')
    nod.append("</nodes>")
    nod_path = os.path.join(out_dir, f"corridor_{name}.nod.xml")
    with open(nod_path, "w") as f:
        f.write("\n".join(nod) + "\n")

    edg = ['<?xml version="1.0" encoding="UTF-8"?>', "<edges>"]
    for i in range(n_edges):
        a, b = ids[i], ids[i + 1]
        edg.append(f'    <edge id="{a}{b}" from="{a}" to="{b}" numLanes="{num_lanes}" speed="{speed}"/>')
    edg.append("</edges>")
    edg_path = os.path.join(out_dir, f"corridor_{name}.edg.xml")
    with open(edg_path, "w") as f:
        f.write("\n".join(edg) + "\n")

    net_path = os.path.join(out_dir, f"corridor_{name}.net.xml")
    # Deliberately no --flatten (that strips z). netconvert preserves node z by
    # default -- no special flag is needed for elevation to survive compilation.
    cmd = ["netconvert", "--node-files", nod_path, "--edge-files", edg_path,
           "--output-file", net_path, "--no-turnarounds", "true"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(f"[{name}] netconvert rc={r.returncode}")
    if r.stderr.strip():
        print(f"[{name}] stderr:\n{r.stderr.strip()}")
    if r.returncode != 0:
        raise SystemExit(f"netconvert failed for variant {name}")
    return net_path


def realized_slopes(net_path, name):
    """Read the compiled net back and compute per-edge grade from lane shape z.
    This is the verification step -- never assume the source z propagated correctly."""
    root = ET.parse(net_path).getroot()
    rows = []
    for edge in root.findall("edge"):
        if edge.get("function") == "internal":
            continue
        lane = edge.find("lane")
        shape = lane.get("shape")
        length = float(lane.get("length"))
        pts = []
        for pt in shape.split():
            vals = [float(v) for v in pt.split(",")]
            if len(vals) == 2:  # z omitted in the shape string -> flat (z=0)
                vals.append(0.0)
            pts.append(tuple(vals))
        (x0, y0, z0), (x1, y1, z1) = pts[0], pts[-1]
        horiz = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        dz = z1 - z0
        grade_pct = 100.0 * dz / horiz if horiz else 0.0
        rows.append((edge.get("id"), length, z0, z1, dz, round(grade_pct, 3)))

    print(f"\n=== realized per-edge slope [{name}] (from compiled net.xml) ===")
    print(f"{'edge':6} {'lane_len':>9} {'z_from':>8} {'z_to':>8} {'dz':>7} {'grade%':>8}")
    for eid, length, z0, z1, dz, g in rows:
        print(f"{eid:6} {length:9.3f} {z0:8.2f} {z1:8.2f} {dz:7.2f} {g:8.3f}")
    return rows


def main():
    args = parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    for spec in args.grades.split(","):
        name, grade = spec.split(":")
        net_path = write_variant(args.out_dir, name, float(grade), args.n_edges,
                                  args.edge_length, args.speed, args.num_lanes)
        realized_slopes(net_path, name)


if __name__ == "__main__":
    main()
