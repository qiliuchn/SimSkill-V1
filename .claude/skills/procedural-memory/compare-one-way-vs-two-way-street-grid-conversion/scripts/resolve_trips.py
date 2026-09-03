#!/usr/bin/env python3
"""Resolve an abstract OD file (gen_demand.py) onto one network variant.

SEG tokens name a physical block face.  In the two-way network that block face
has two directional edges; we pick whichever gives the SHORTER free-flow path
for that particular trip -- i.e. the two-way network is given the benefit of the
doubt in every ambiguous case, so any residual circuity penalty measured for the
one-way network is a lower bound on the advantage two-way enjoys, never an
artefact of an arbitrary tie-break.

In the one-way networks exactly one directional edge exists, so there is nothing
to choose: the vehicle must reach the block face from the legal direction, and
that is precisely where the one-way circuity penalty comes from.
"""
import argparse
import csv
import os
import sys

sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import sumolib  # noqa: E402

VTYPE = ('    <vType id="car" accel="2.6" decel="4.5" sigma="0.5" length="5.0"\n'
         '           minGap="2.5" maxSpeed="16.7" speedDev="0.1" tau="1.0"\n'
         '           carFollowModel="Krauss"/>\n')


def candidates(net, token):
    if token.startswith("BND:"):
        lab = token[4:]
        return [e for e in ("in_" + lab, "out_" + lab) if net.hasEdge(e)]
    kind, a, b = token[4:].split("_")
    suf = ("E", "W") if kind == "EW" else ("N", "S")
    return [x for x in ("%s_%s_%s_%s" % (kind, a, b, s) for s in suf)
            if net.hasEdge(x)]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("-n", "--net", required=True)
    p.add_argument("--od", required=True)
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--dist-out", default=None,
                   help="optional CSV of resolved free-flow path distances")
    a = p.parse_args()

    net = sumolib.net.readNet(a.net)
    cache = {}

    def best(otok, dtok):
        key = (otok, dtok)
        if key in cache:
            return cache[key]
        bestv = None
        for oe in candidates(net, otok):
            if oe.startswith("out_"):
                continue                    # an `out_` stub leaves the network
            for de in candidates(net, dtok):
                if de.startswith("in_"):
                    continue                # an `in_` stub enters the network
                if oe == de:
                    continue
                try:
                    path, _ = net.getOptimalPath(net.getEdge(oe), net.getEdge(de))
                except Exception:
                    path = None
                if not path:
                    continue
                dist = sum(e.getLength() for e in path)
                if bestv is None or dist < bestv[2]:
                    bestv = (oe, de, dist)
        cache[key] = bestv
        return bestv

    rows = list(csv.DictReader(open(a.od)))
    out, dists, skipped = [], [], 0
    for r in rows:
        b = best(r["origin"], r["dest"])
        if b is None:
            skipped += 1
            continue
        out.append((r["id"], float(r["depart"]), b[0], b[1], r["kind"]))
        dists.append((r["id"], r["kind"], b[2]))

    with open(a.out, "w") as f:
        f.write('<routes xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
                ' xsi:noNamespaceSchemaLocation='
                '"http://sumo.dlr.de/xsd/routes_file.xsd">\n')
        f.write(VTYPE)
        for vid, t, oe, de, kd in out:
            f.write('    <trip id="%s" type="car" depart="%.2f" from="%s" to="%s"'
                    ' departLane="best" departSpeed="max" arrivalLane="current"/>\n'
                    % (vid, t, oe, de))
        f.write('</routes>\n')

    if a.dist_out:
        with open(a.dist_out, "w") as f:
            f.write("id,kind,ff_path_dist_m\n")
            for vid, kd, d in dists:
                f.write("%s,%s,%.2f\n" % (vid, kd, d))
    print("%s: %d trips written, %d unroutable" % (a.out, len(out), skipped))


if __name__ == "__main__":
    main()
