"""Partition a SUMO network into a grid of traffic analysis zones and write TAZ files.

Assigns every loadable edge (function=normal, allows the given vClass) to exactly one
zone by its shape midpoint, then writes weighted <tazSource>/<tazSink> TAZ files.

Two files are written so the centroid-connector placement pitfall can be measured:
  <out>.taz.xml            connectors exclude the edge types named by --exclude-type
  <out>_allconnectors.taz.xml   every edge in the zone is a connector

Verification performed (assertions, not prints): full coverage of loadable edges,
no edge assigned twice, no empty zone, every zone has >=1 connector.

Usage:
  python make_zone_taz.py -n net.net.xml -o zones --cols 4 --rows 4 --exclude-type arterial
"""
import argparse
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.environ.get("SUMO_HOME", ""), "tools"))
import sumolib  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--net-file", required=True)
    ap.add_argument("-o", "--out-prefix", required=True,
                    help="writes <prefix>.taz.xml, <prefix>_allconnectors.taz.xml, <prefix>.json")
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--rows", type=int, default=4)
    ap.add_argument("--vclass", default="passenger")
    ap.add_argument("--exclude-type", action="append", default=[],
                    help="edge type(s) never used as a centroid connector "
                         "(repeatable; use for high-capacity arterials/freeways)")
    ap.add_argument("--weight", choices=("lanekm", "length", "uniform"), default="lanekm")
    args = ap.parse_args()

    net = sumolib.net.readNet(args.net_file)
    loadable = [e for e in net.getEdges()
                if e.getFunction() in ("", "normal") and e.allows(args.vclass)]
    assert loadable, "no loadable edges found for vClass %s" % args.vclass

    xs, ys = [], []
    mids = {}
    for e in loadable:
        shp = e.getShape()
        mx = sum(p[0] for p in shp) / len(shp)
        my = sum(p[1] for p in shp) / len(shp)
        mids[e.getID()] = (mx, my)
        xs.append(mx)
        ys.append(my)
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)

    def b(v, lo, hi, n):
        if hi <= lo:
            return 0
        return min(n - 1, int((v - lo) / (hi - lo + 1e-9) * n))

    zmap = defaultdict(list)
    for e in loadable:
        mx, my = mids[e.getID()]
        c, r = b(mx, x0, x1, args.cols), b(my, y0, y1, args.rows)
        zmap["Z%02d" % (r * args.cols + c + 1)].append(e)

    zones = ["Z%02d" % (r * args.cols + c + 1)
             for r in range(args.rows) for c in range(args.cols)]
    assigned = sum(len(v) for v in zmap.values())
    assert assigned == len(loadable), "coverage gap: %d/%d" % (assigned, len(loadable))
    empty = [z for z in zones if not zmap[z]]
    assert not empty, ("empty zones %s -- reduce --cols/--rows or the partition does "
                       "not match the network's shape" % empty)

    def w_of(e):
        if args.weight == "length":
            return e.getLength()
        if args.weight == "uniform":
            return 1.0
        return e.getLength() * e.getLaneNumber()

    meta = {}
    for z in zones:
        pts = [mids[e.getID()] for e in zmap[z]]
        meta[z] = {
            "centroid": [round(sum(p[0] for p in pts) / len(pts), 1),
                         round(sum(p[1] for p in pts) / len(pts), 1)],
            "n_edges": len(zmap[z]),
            "edges": sorted(e.getID() for e in zmap[z]),
            "connectors": sorted(e.getID() for e in zmap[z]
                                 if e.getType() not in args.exclude_type),
        }
        assert meta[z]["connectors"], "zone %s has no connector after --exclude-type" % z

    def write(path, exclude):
        with open(path, "w") as f:
            f.write("<tazs>\n")
            for z in zones:
                es = [e for e in zmap[z] if not (exclude and e.getType() in args.exclude_type)]
                tot = sum(w_of(e) for e in es)
                f.write('    <taz id="%s" x="%.1f" y="%.1f">\n'
                        % (z, meta[z]["centroid"][0], meta[z]["centroid"][1]))
                for tag in ("tazSource", "tazSink"):
                    for e in es:
                        f.write('        <%s id="%s" weight="%.6f"/>\n'
                                % (tag, e.getID(), w_of(e) / tot))
                f.write("    </taz>\n")
            f.write("</tazs>\n")
        print("wrote", path)

    write(args.out_prefix + ".taz.xml", True)
    write(args.out_prefix + "_allconnectors.taz.xml", False)
    with open(args.out_prefix + ".json", "w") as f:
        json.dump({"zones": zones, "meta": meta}, f, indent=1)
    print("wrote %s.json -- %d loadable edges over %d zones (%d-%d edges per zone)"
          % (args.out_prefix, len(loadable), len(zones),
             min(len(zmap[z]) for z in zones), max(len(zmap[z]) for z in zones)))


if __name__ == "__main__":
    main()
