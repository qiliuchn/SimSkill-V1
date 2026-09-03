#!/usr/bin/env python3
"""SUB-GOAL 3 -- parameterized climbing-lane facility generator (reusable
artifact).

Builds an 8 km rural multilane divided highway (2 lanes/direction) with a
sustained grade of configurable pct/length in the uphill (EB) direction, and
its mirror-terrain downhill (WB) direction (same elevation profile, opposite
travel order -- one real hill, two carriageways). Three EB variants:
  - "base": no added lane, 2 lanes throughout.
  - "climbing_gp": a general-purpose 3rd lane added over the grade with entry
    taper (2->3 lanes) and exit taper/lane-drop (3->2 lanes), open to all
    vClasses -- reuses the added-lane-with-tapers template from
    `evaluate-two-lane-highway-with-hcm-and-passing-lanes`.
  - "climbing_restricted": identical geometry, but trucks/slow vehicles are
    DISALLOWED from the two general lanes over the widened stretch (forcing
    them into the added lane) -- reuses `model-vclass-lane-permissions`'s
    allow/disallow-then-let-netconvert-regenerate-connections discipline.

WB is always 2 lanes / no climbing lane (climbing lanes are an upgrade-side
treatment; the downgrade arm of the study uses WB's "base" geometry as-is).

Every variant is geometry-matched: same 6-node split (N0..N5) on EB in every
variant, so the only difference between base/GP/restricted is lane count and
permissions -- not extra junction-trimming artifacts.
"""
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import NETCONVERT_BIN, NET

TOTAL_LEN = 8000.0
TAPER_LEN = 200.0
WB_Y_OFFSET = -40.0
SPEED = 27.78  # 100 km/h


def _grade_profile(grade_pct, grade_len_m, total_len=TOTAL_LEN):
    flat = (total_len - grade_len_m) / 2.0
    n1 = flat
    n3 = flat + grade_len_m
    return n1, n3


def build_variant(grade_pct, grade_len_km, variant, out_dir=None, taper_len=TAPER_LEN,
                   total_len=TOTAL_LEN, speed=SPEED):
    """variant in {'base','climbing_gp','climbing_restricted'}. Returns dict
    with net path and the AUTHORED (intended) node x-positions, for the
    caller to cross-check against what actually survives compilation."""
    assert variant in ("base", "climbing_gp", "climbing_restricted")
    grade_len_m = grade_len_km * 1000.0
    n1, n3 = _grade_profile(grade_pct, grade_len_m, total_len)
    n2 = n1 + taper_len
    n4 = n3 + taper_len
    n0, n5 = 0.0, total_len
    total_rise = grade_len_m * grade_pct / 100.0

    def z(x):
        if x <= n1:
            return 0.0
        if x <= n3:
            return (x - n1) / grade_len_m * total_rise
        return total_rise

    tag = "fac_g%g_L%g_%s" % (grade_pct, grade_len_km, variant)
    out_dir = out_dir or NET
    os.makedirs(out_dir, exist_ok=True)

    eb_xs = [n0, n1, n2, n3, n4, n5]
    eb_ids = ["E%d" % i for i in range(6)]

    if variant == "base":
        eb_lanes = [2, 2, 2, 2, 2]  # approach, taper_in(unused,still 2), grade, taper_out(2), departure
    else:
        eb_lanes = [2, 3, 3, 2, 2]  # approach, taper_in(3), grade(3), taper_out(2, drop), departure

    eb_edge_ids = ["approach", "taper_in", "grade", "taper_out", "departure"]

    nod_path = os.path.join(out_dir, tag + ".nod.xml")
    edg_path = os.path.join(out_dir, tag + ".edg.xml")
    net_path = os.path.join(out_dir, tag + ".net.xml")

    with open(nod_path, "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<nodes>\n')
        for i, x in enumerate(eb_xs):
            f.write('  <node id="%s" x="%.2f" y="0.0" z="%.4f"/>\n' % (eb_ids[i], x, z(x)))
        # WB: same terrain z(x), traversed from n5 -> n0 (opposite order == downhill
        # mirror of the same hill), offset in y purely for visual/geometric clarity.
        wb_ids = ["W%d" % i for i in range(6)]
        for i, x in enumerate(eb_xs):
            f.write('  <node id="%s" x="%.2f" y="%.2f" z="%.4f"/>\n' % (wb_ids[i], x, WB_Y_OFFSET, z(x)))
        f.write('</nodes>\n')

    with open(edg_path, "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<edges>\n')
        for i in range(5):
            eid = eb_edge_ids[i]
            frm, to = eb_ids[i], eb_ids[i + 1]
            nl = eb_lanes[i]
            f.write('  <edge id="%s" from="%s" to="%s" numLanes="%d" speed="%.2f"' % (eid, frm, to, nl, speed))
            if variant == "climbing_restricted" and eid in ("taper_in", "grade"):
                f.write('>\n')
                for li in range(nl - 1):  # lanes 0..nl-2 are the general/through lanes
                    f.write('    <lane index="%d" disallow="truck trailer"/>\n' % li)
                f.write('  </edge>\n')
            else:
                f.write('/>\n')
        # WB: reverse travel order, always 2 lanes, no restriction
        for i in range(5):
            eid = "wb_" + eb_edge_ids[4 - i]
            frm, to = wb_ids[5 - i], wb_ids[4 - i]
            f.write('  <edge id="%s" from="%s" to="%s" numLanes="2" speed="%.2f"/>\n' % (eid, frm, to, speed))
        f.write('</edges>\n')

    cmd = [NETCONVERT_BIN, "-n", nod_path, "-e", edg_path, "-o", net_path,
           "--no-turnarounds", "true", "--junctions.corner-detail", "0"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("netconvert failed for %s:\n%s" % (tag, r.stderr))

    return {
        "tag": tag, "net_path": net_path, "variant": variant,
        "grade_pct": grade_pct, "grade_len_km": grade_len_km,
        "authored_eb_x": dict(zip(eb_ids, eb_xs)),
        "authored_eb_lanes": dict(zip(eb_edge_ids, eb_lanes)),
        "eb_edge_ids": ["E0E1" if False else None],  # placeholder, real ids below
        "eb_edge_id_list": ["%s" % eid for eid in eb_edge_ids],
        "eb_node_ids": eb_ids,
    }


def _parse_lane_shape(shape):
    pts = []
    for p in shape.split():
        c = [float(v) for v in p.split(",")]
        if len(c) == 2:
            c.append(0.0)
        pts.append(c)
    return pts


def verify_facility(net_path):
    """Read back the COMPILED net: per-edge realized grade from lane shape
    z-data (never trust source), per-edge lane count, and where (compiled x)
    the taper/lane-drop boundaries actually landed."""
    root = ET.parse(net_path).getroot()
    rows = []
    for e in root.findall("edge"):
        if e.get("function") == "internal":
            continue
        lanes = e.findall("lane")
        if not lanes:
            continue
        ln0 = lanes[0]
        pts = _parse_lane_shape(ln0.get("shape"))
        (x0, y0, z0), (x1, y1, z1) = pts[0], pts[-1]
        horiz = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        grade_pct = 100.0 * (z1 - z0) / horiz if horiz > 1e-6 else 0.0
        rows.append({
            "edge_id": e.get("id"), "from": e.get("from"), "to": e.get("to"),
            "n_lanes": len(lanes), "lane_length_m": round(float(ln0.get("length")), 2),
            "x_start": round(x0, 2), "x_end": round(x1, 2),
            "z_start": round(z0, 3), "z_end": round(z1, 3),
            "realized_grade_pct": round(grade_pct, 4),
        })
    return rows


def verify_lane_permissions(net_path, edge_ids=("taper_in", "grade")):
    root = ET.parse(net_path).getroot()
    out = {}
    for e in root.findall("edge"):
        if e.get("id") in edge_ids:
            lanes = []
            for ln in e.findall("lane"):
                lanes.append({"index": ln.get("index"), "allow": ln.get("allow"), "disallow": ln.get("disallow")})
            out[e.get("id")] = lanes
    return out


if __name__ == "__main__":
    import json
    for variant in ("base", "climbing_gp", "climbing_restricted"):
        info = build_variant(4.0, 2.0, variant)
        rows = verify_facility(info["net_path"])
        print("=== %s ===" % variant)
        for r in rows:
            if r["edge_id"].startswith("wb_"):
                continue
            print("  %-10s lanes=%d len=%8.2f grade=%7.3f%%  x[%7.1f -> %7.1f]" %
                  (r["edge_id"], r["n_lanes"], r["lane_length_m"], r["realized_grade_pct"],
                   r["x_start"], r["x_end"]))
        if variant == "climbing_restricted":
            perms = verify_lane_permissions(info["net_path"])
            print("  lane permissions:", json.dumps(perms))
