#!/usr/bin/env python3
"""Goal 4's 'correct fix' demonstration: replace naive boundary insertion at
buf0_meso_high's 8 injection-face edges with a SUMO <calibrator> whose target
flow is the TRUE micro full-region reference's measured crossing rate on
those same edges (not the meso-parent's over-estimated handoff). Since the
meso-parent-cut's route file over-supplies relative to that true rate, the
calibrator sheds the surplus (vaporizes/delays it) instead of letting SUMO
force-insert everything at the parent's (too-fast) schedule.
"""
import os
import sys
import xml.etree.ElementTree as ET
from collections import Counter

sys.path.append(os.path.dirname(__file__))
from common import WD, read_edgedata_intervals

NAME = "buf0_meso_high"
CUTDIR = os.path.join(WD, "cuts", NAME)
INJECTION_EDGES = ["C3D3", "C4D4", "D2D3", "D5D4", "E2E3", "E5E4", "F3E3", "F4E4"]
SEEDS_REF = [42, 43, 44, 45, 46]
BINS = [(i * 300, (i + 1) * 300) for i in range(12)]  # 0..3600


def true_reference_rates():
    """Mean entered-count per 300s bin per edge, from the 5-seed full micro
    reference at high demand -- the TRUE metered crossing rate."""
    per_seed = []
    for s in SEEDS_REF:
        path = os.path.join(WD, "micro", "full", "micro_high_seed%d_edgedata_fine.xml" % s)
        per_seed.append(read_edgedata_intervals(path, set(INJECTION_EDGES)))
    out = {}
    for e in INJECTION_EDGES:
        rates = []
        for b, e_ in BINS:
            vals = []
            for pset in per_seed:
                for (bb, ee, d) in pset.get(e, []):
                    if abs(bb - b) < 1e-6:
                        vals.append(d.get("entered") or 0.0)
            vals = vals or [0.0]
            rates.append(sum(vals) / len(vals))
        out[e] = rates
    return out


def representative_route(routes_xml, edge):
    root = ET.parse(routes_xml).getroot()
    seqs = Counter()
    for v in root.findall("vehicle"):
        eds = v.find("route").get("edges").split()
        if eds[0] == edge:
            seqs[tuple(eds)] += 1
    if not seqs:
        return None
    return seqs.most_common(1)[0][0]


def main():
    rates = true_reference_rates()
    routes_xml = os.path.join(CUTDIR, "rou_%s.rou.xml" % NAME)

    add_lines = ["<additional>"]
    route_id_map = {}
    for e in INJECTION_EDGES:
        seq = representative_route(routes_xml, e)
        rid = "calroute_%s" % e
        route_id_map[e] = rid
        add_lines.append('    <route id="%s" edges="%s"/>' % (rid, " ".join(seq)))

    calstats_dir = os.path.join(CUTDIR, "calib")
    os.makedirs(calstats_dir, exist_ok=True)
    for e in INJECTION_EDGES:
        add_lines.append('    <calibrator id="cal_%s" edge="%s" pos="1.0" '
                          'output="calib/calstats_%s.xml" period="300" jamThreshold="0.5">'
                          % (e, e, e))
        for (b, e_), rate in zip(BINS, rates[e]):
            vph = rate * 3600.0 / 300.0
            add_lines.append('        <flow begin="%d" end="%d" route="%s" vehsPerHour="%.2f" speed="13.89"/>'
                              % (b, e_, route_id_map[e], vph))
        add_lines.append('    </calibrator>')
    add_lines.append("</additional>")

    out_path = os.path.join(CUTDIR, "calibrator_fix.add.xml")
    with open(out_path, "w") as fh:
        fh.write("\n".join(add_lines) + "\n")
    print("wrote", out_path)
    for e in INJECTION_EDGES:
        print("  %s: true-reference target rates (veh/h by 300s bin) = %s"
              % (e, [round(r * 12, 0) for r in rates[e]]))


if __name__ == "__main__":
    main()
