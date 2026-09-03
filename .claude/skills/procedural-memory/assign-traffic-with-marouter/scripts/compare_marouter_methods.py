"""
Parse and compare marouter's route-alternatives output (and, if present, its
--netload-output edge-load data) across multiple assignment-method runs on the
same OD demand -- e.g. all-or-nothing vs. incremental vs. UE/SUE.

Classifies each route by whether it contains a given "marker" edge id, so it
works for any two-route (or more) comparison without hand-editing route names
per network.

Usage:
    python compare_marouter_methods.py \
        --out-dir marouter_out \
        --run "all-or-nothing=aon" --run "incremental=incremental" --run "UE/SUE=ue" \
        --route-markers "short:SHORT,long_a:LONG" \
        --out-json split_summary.json
"""

import argparse
import json
import os
import xml.etree.ElementTree as ET


def parse_args():
    p = argparse.ArgumentParser(description="Compare marouter route-alternatives output across assignment methods.")
    p.add_argument("--out-dir", required=True, help="Directory containing <tag>.rou.xml (and optionally <tag>_netload.xml) per run")
    p.add_argument("--run", action="append", required=True, help="label=tag, repeatable, in the order to display")
    p.add_argument("--route-markers", required=True, help='Comma-separated "edge_id:label" pairs; a route is classified by the first marker edge found in its edge list')
    p.add_argument("--out-json", default="split_summary.json")
    return p.parse_args()


def classify(edges, markers):
    edge_set = set(edges.split())
    for marker_edge, label in markers:
        if marker_edge in edge_set:
            return label
    return edges  # fallback: show the raw edge list if no marker matched


def parse_routes(out_dir, tag, markers):
    root = ET.parse(os.path.join(out_dir, f"{tag}.rou.xml")).getroot()
    flow = root.find("flow")
    rows = []
    for r in flow.find("routeDistribution").findall("route"):
        label = classify(r.get("edges"), markers)
        rows.append((label, float(r.get("probability")), float(r.get("cost"))))
    return rows


def parse_netload(out_dir, tag):
    path = os.path.join(out_dir, f"{tag}_netload.xml")
    if not os.path.isfile(path):
        return None
    root = ET.parse(path).getroot()
    return {e.get("id"): {"entered": float(e.get("entered")), "traveltime": float(e.get("traveltime")),
                           "flowCapacityRatio": float(e.get("flowCapacityRatio"))}
            for e in root.find("interval").findall("edge")}


def main():
    args = parse_args()
    markers = [tuple(m.split(":")) for m in args.route_markers.split(",")]
    labels = [label for _, label in markers]

    print("=" * 90)
    print("MAROUTER ROUTE-FLOW SPLIT ACROSS ASSIGNMENT METHODS")
    print("=" * 90)
    header = f"{'method':<18}" + "".join(f"{lbl + ' flow':>14}" for lbl in labels) + "".join(f"{lbl + ' cost':>14}" for lbl in labels) + f"{'cost gap%':>12}"
    print(header)
    print("-" * len(header))

    summary = {}
    for spec in args.run:
        name, tag = spec.split("=", 1)
        rows = parse_routes(args.out_dir, tag, markers)
        by_label = {}
        for label, prob, cost in rows:
            by_label[label] = (prob, cost)
        flows = [by_label.get(lbl, (0.0, float("nan")))[0] for lbl in labels]
        costs = [by_label.get(lbl, (0.0, float("nan")))[1] for lbl in labels]
        used_costs = [c for f, c in zip(flows, costs) if f > 0]
        gap = (max(used_costs) - min(used_costs)) / min(used_costs) * 100 if len(used_costs) > 1 else float("nan")
        summary[name] = {"flows": dict(zip(labels, flows)), "costs": dict(zip(labels, costs)), "cost_gap_pct": gap}
        line = f"{name:<18}" + "".join(f"{f:>14.1f}" for f in flows) + "".join(f"{c:>14.1f}" for c in costs) + f"{gap:>12.2f}"
        print(line)

    print()
    print("=" * 90)
    print("REALIZED EDGE LOADS (from --netload-output, if present)")
    print("=" * 90)
    for spec in args.run:
        name, tag = spec.split("=", 1)
        loads = parse_netload(args.out_dir, tag)
        if loads is None:
            continue
        print(f"\n[{name}]")
        for eid, d in loads.items():
            print(f"  {eid:<10} entered={d['entered']:>8.1f}  traveltime={d['traveltime']:>10.1f}  flowCapacityRatio={d['flowCapacityRatio']:>6.2f}")

    with open(args.out_json, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nsaved {args.out_json}")


if __name__ == "__main__":
    main()
