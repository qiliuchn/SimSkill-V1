"""
Generate E2 lane-area detector stations along a freeway corridor (one detector
per lane per station, ~station-spacing apart), plus E1 induction loops at a
given discharge edge, and write one additional-file per run label so runs
never clobber each other's detector output. Also writes stations.json mapping
each station to its cumulative distance along the corridor -- the x-axis data
a time-space speed-contour plot needs.

Usage:
    python gen_e2_stations.py \
        --net freeway.net.xml --edge-order e0,e1,e2,e3,e4,e5 \
        --station-spacing 500 --discharge-edge e5 --discharge-pos 480 \
        --out-dir detectors --run-labels baseline,vsl \
        --output-dir-template "outputs/{label}"
"""

import argparse
import json
import os
import sys


def parse_args():
    p = argparse.ArgumentParser(description="Generate E2 lane-area detector stations + E1 discharge loops along a corridor.")
    p.add_argument("--net", required=True)
    p.add_argument("--edge-order", required=True, help="Comma-separated edge ids in travel-direction order (defines the corridor for the x-axis of a speed-contour plot)")
    p.add_argument("--station-spacing", type=float, default=500.0, help="Target distance between stations (m); edges longer than 1.4x this are split into multiple stations")
    p.add_argument("--period", type=float, default=30.0, help="Detector aggregation interval (s)")
    p.add_argument("--discharge-edge", required=True, help="Edge to place E1 induction loops on for throughput/discharge counting")
    p.add_argument("--discharge-pos", type=float, default=None, help="Position along discharge-edge for the E1 loops (default: near its end)")
    p.add_argument("--out-dir", default="detectors")
    p.add_argument("--run-labels", required=True, help="Comma-separated run labels (e.g. baseline,vsl) -- one additional-file per label")
    p.add_argument("--output-dir-template", default="outputs/{label}", help="Where each label's detector XML output is written; {label} is substituted")
    return p.parse_args()


def main():
    args = parse_args()
    sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
    import sumolib  # noqa: E402

    net = sumolib.net.readNet(args.net)
    edge_order = args.edge_order.split(",")

    edge_start = {}
    d = 0.0
    for eid in edge_order:
        edge_start[eid] = d
        d += net.getEdge(eid).getLength()
    corridor_len = d

    stations = []
    for eid in edge_order:
        length = net.getEdge(eid).getLength()
        if length > args.station_spacing * 1.4:
            n_segs = round(length / args.station_spacing)
            seg_len = length / n_segs
            segs = [(i * seg_len, seg_len) for i in range(n_segs)]
        else:
            segs = [(0.0, length)]
        for pos, seg_len in segs:
            stations.append({"edge": eid, "pos": pos, "length": seg_len,
                              "dist": edge_start[eid] + pos + seg_len / 2.0})

    def lanes_of(eid):
        return [ln.getID() for ln in net.getEdge(eid).getLanes()]

    disch_pos = args.discharge_pos
    if disch_pos is None:
        disch_pos = max(0.0, net.getEdge(args.discharge_edge).getLength() - 20.0)

    os.makedirs(args.out_dir, exist_ok=True)
    e2_ids_by_edge = {}
    for label in args.run_labels.split(","):
        outdir = args.output_dir_template.format(label=label)
        os.makedirs(outdir, exist_ok=True)
        out_e2 = os.path.join(outdir, "det_e2.xml")
        out_e1 = os.path.join(outdir, "det_e1_discharge.xml")
        lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<additional>"]
        for si, st in enumerate(stations):
            for li, lane in enumerate(lanes_of(st["edge"])):
                did = f"e2_s{si:02d}_{st['edge']}_l{li}"
                lines.append(f'  <laneAreaDetector id="{did}" lane="{lane}" pos="{st["pos"]:.1f}" '
                             f'length="{st["length"]:.1f}" period="{args.period}" file="{out_e2}" friendlyPos="true"/>')
                e2_ids_by_edge.setdefault(st["edge"], []).append(did)
        for li, lane in enumerate(lanes_of(args.discharge_edge)):
            did = f"e1_disch_l{li}"
            lines.append(f'  <inductionLoop id="{did}" lane="{lane}" pos="{disch_pos:.1f}" '
                         f'period="{args.period}" file="{out_e1}"/>')
        lines.append("</additional>")
        add_path = os.path.join(args.out_dir, f"detectors_{label}.add.xml")
        with open(add_path, "w") as f:
            f.write("\n".join(lines) + "\n")
        print(f"{label}: wrote {add_path}")

    info = {
        "corridor_len": corridor_len, "period": args.period, "stations": stations,
        "e2_ids_by_edge": e2_ids_by_edge,
        "discharge_e1": [f"e1_disch_l{li}" for li in range(len(lanes_of(args.discharge_edge)))],
    }
    with open(os.path.join(args.out_dir, "stations.json"), "w") as f:
        json.dump(info, f, indent=2)
    print(f"corridor_len={corridor_len:.1f} m, {len(stations)} stations")


if __name__ == "__main__":
    main()
