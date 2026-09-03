#!/usr/bin/env python3
"""
Derive the geometric CONFLICT POINT of every conflicting movement pair from the
compiled net's internal-lane shapes.

The junction foes matrix (conflicts.py) says WHICH movement pairs conflict; this
adds WHERE along each movement's internal path the conflict physically is, which
is what lets the AIM safety supervisor release a shared resource as soon as a
vehicle has passed that point instead of holding the whole internal lane.

For each foe pair (i, j) we take the earliest arclength pair (s_i, s_j) at which
the two concatenated internal polylines come within `--near` metres of each
other (falling back to the global closest approach).  For crossing movements this
is the crossing point; for merging movements (two links entering the same
outgoing lane) the polylines converge near their ends, so it lands at the merge.

Usage: python conflict_points.py --net inter_static.net.xml --conflicts conflicts.json \
           --out conflicts.json
"""
import argparse
import json
import math
import xml.etree.ElementTree as ET


def lane_shapes(net_path):
    root = ET.parse(net_path).getroot()
    sh = {}
    for e in root.findall("edge"):
        for ln in e.findall("lane"):
            pts = []
            for p in ln.get("shape").split():
                x, y = p.split(",")
                pts.append((float(x), float(y)))
            sh[ln.get("id")] = pts
    return sh


def polyline(chain, shapes):
    pts = []
    for lane in chain:
        s = shapes[lane]
        if pts and abs(pts[-1][0] - s[0][0]) < 1e-6 and abs(pts[-1][1] - s[0][1]) < 1e-6:
            pts.extend(s[1:])
        else:
            pts.extend(s)
    arc = [0.0]
    for k in range(1, len(pts)):
        arc.append(arc[-1] + math.hypot(pts[k][0] - pts[k - 1][0], pts[k][1] - pts[k - 1][1]))
    return pts, arc


def densify(pts, arc, step=0.5):
    """Resample the polyline at ~`step` m so closest-approach search is accurate."""
    out = []
    total = arc[-1]
    n = max(2, int(total / step) + 1)
    k = 0
    for m in range(n + 1):
        s = total * m / n
        while k < len(arc) - 2 and arc[k + 1] < s:
            k += 1
        seg = arc[k + 1] - arc[k]
        f = 0.0 if seg <= 0 else (s - arc[k]) / seg
        x = pts[k][0] + f * (pts[k + 1][0] - pts[k][0])
        y = pts[k][1] + f * (pts[k + 1][1] - pts[k][1])
        out.append((s, x, y))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", required=True)
    ap.add_argument("--conflicts", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--near", type=float, default=2.5)
    a = ap.parse_args()

    C = json.load(open(a.conflicts))
    shapes = lane_shapes(a.net)
    n = C["n_links"]

    dense = {}
    for i in range(n):
        pts, arc = polyline(C["int_chain"][str(i)], shapes)
        dense[i] = densify(pts, arc)

    cp = {}
    report = []
    for i in range(n):
        for j in C["foes"][str(i)]:
            if j < i:
                continue
            best = None          # (dist, s_i, s_j)
            first = None         # earliest s_i with dist < near
            for (si, xi, yi) in dense[i]:
                for (sj, xj, yj) in dense[j]:
                    d = math.hypot(xi - xj, yi - yj)
                    if best is None or d < best[0]:
                        best = (d, si, sj)
                    if d < a.near and first is None:
                        first = (d, si, sj)
            use = first if first is not None else best
            key = "%d|%d" % (i, j)
            cp[key] = {"s_i": round(use[1], 2), "s_j": round(use[2], 2),
                       "dist": round(use[0], 2), "fallback": first is None}
            report.append((i, j, use[1], use[2], use[0], first is None))

    C["conflict_points"] = cp
    json.dump(C, open(a.out, "w"), indent=1, sort_keys=True)

    print("%d conflicting pairs; conflict points written" % len(cp))
    fb = [r for r in report if r[5]]
    print("pairs with no sub-%.1fm approach (fallback to global min): %d" % (a.near, len(fb)))
    for r in fb:
        print("   %d-%d  s_i=%.1f s_j=%.1f dist=%.2f" % (r[0], r[1], r[2], r[3], r[4]))
    print("\nsample (link i, link j, arclength on i, on j, separation):")
    for r in report[:14]:
        print("   %2d-%-2d  %6.2f %6.2f  %5.2f" % (r[0], r[1], r[2], r[3], r[4]))
    import statistics as st
    print("\nmean conflict-point arclength on link i: %.2f m (internal path lengths %.1f-%.1f)"
          % (st.mean(r[2] for r in report),
             min(C["int_len"].values()), max(C["int_len"].values())))


if __name__ == "__main__":
    main()
