"""
Verify that jtrrouter (and the simulation that consumes its output) actually
reproduced the turning ratios specified in a <turns> file, by reclassifying
every generated/executed route's movement at each fromEdge directly from its
edge sequence -- not from jtrrouter's own success/exit status, which says
nothing about whether the realized distribution matches the specification.

The specification (which (from, to) edge pairs exist and their target
probability) is read directly from the <turns> file, not hardcoded, so this
works on any jtrrouter scenario without per-network editing.

Usage:
    python verify_turn_ratios.py --turns turns.xml \
        --routes routes.rou.xml --routes vehroutes.out.xml \
        --out comparison.txt
"""

import argparse
import xml.etree.ElementTree as ET
from collections import defaultdict


def parse_args():
    p = argparse.ArgumentParser(description="Verify realized turn ratios against a jtrrouter <turns> specification.")
    p.add_argument("--turns", required=True, help="The <turns> XML file used as jtrrouter's -t input")
    p.add_argument("--routes", action="append", required=True, help="A routes file (jtrrouter output or vehroute-output) to classify, repeatable -- label taken from the filename")
    p.add_argument("--out", default="comparison.txt")
    return p.parse_args()


def load_spec(turns_path):
    """{from_edge: {to_edge: probability}} -- averaged across intervals if the file has more than one."""
    spec = defaultdict(lambda: defaultdict(list))
    root = ET.parse(turns_path).getroot()
    for interval in root.findall("interval"):
        for rel in interval.findall("edgeRelation"):
            spec[rel.get("from")][rel.get("to")].append(float(rel.get("probability")))
    return {frm: {to: sum(ps) / len(ps) for to, ps in tos.items()} for frm, tos in spec.items()}


def classify_routes(route_path, spec):
    """For each vehicle's route, find the first from_edge -> to_edge transition
    that appears in spec, and count it. Returns {from_edge: {to_edge: count}}, total."""
    counts = {frm: {to: 0 for to in tos} for frm, tos in spec.items()}
    total = 0
    root = ET.parse(route_path).getroot()
    for v in root.iter("vehicle"):
        r = v.find("route")
        if r is None:
            continue
        edges = r.get("edges").split()
        for k in range(len(edges) - 1):
            frm, to = edges[k], edges[k + 1]
            if frm in spec and to in spec[frm]:
                counts[frm][to] += 1
                total += 1
                break
    return counts, total


def report(label, counts, total, spec):
    lines = [f"\n=== {label} === (total classified: {total})"]
    agg_realized = defaultdict(int)
    agg_spec_weight = defaultdict(float)
    for frm in spec:
        n_from = sum(counts[frm].values())
        lines.append(f"  {frm}: n={n_from}")
        for to, p_spec in spec[frm].items():
            n = counts[frm][to]
            frac = n / n_from if n_from else 0.0
            lines.append(f"    -> {to}: spec={p_spec:6.1%}  realized={frac:6.1%}  n={n:5d}  dev={frac - p_spec:+6.1%}")
            agg_realized[(frm, to)] = n
            agg_spec_weight[(frm, to)] = p_spec
    max_dev = 0.0
    for frm in spec:
        n_from = sum(counts[frm].values())
        if not n_from:
            continue
        for to, p_spec in spec[frm].items():
            frac = counts[frm][to] / n_from
            max_dev = max(max_dev, abs(frac - p_spec))
    lines.append(f"  max abs deviation (any single from/to pair): {max_dev:.2%}")
    return "\n".join(lines), max_dev


def main():
    args = parse_args()
    spec = load_spec(args.turns)
    out_lines = [f"Specification loaded from {args.turns}: {sum(len(v) for v in spec.values())} from/to relations."]
    for route_path in args.routes:
        counts, total = classify_routes(route_path, spec)
        text, max_dev = report(route_path, counts, total, spec)
        out_lines.append(text)
        print(text)
        print(f"  ({route_path}: max abs deviation = {max_dev:.2%})")

    with open(args.out, "w") as f:
        f.write("\n".join(out_lines) + "\n")
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
