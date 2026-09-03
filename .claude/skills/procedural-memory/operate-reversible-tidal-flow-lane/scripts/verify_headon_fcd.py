#!/usr/bin/env python3
"""INDEPENDENT (offline) head-on verification from SUMO's own FCD output.

This does not use the controller's live TraCI scan at all -- it re-derives
opposing-direction co-occupancy of a physical reversible lane straight from the
raw fcd-output XML, so the two checks share no code path.

Because the eastbound and westbound representations of a physical lane are
geometrically COINCIDENT (verified in geometry_verification.json), a head-on
exposure shows up directly as two vehicles at the same (x, y) travelling in
opposite directions.

Usage:
  python3 verify_headon_fcd.py --fcd run/fcd.xml --out run/headon_fcd.json
"""
import argparse
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DIR_EDGES, PHYS_LANES, PHYS_Y, lane_id

try:
    from lxml import etree as LET
    HAVE_LXML = True
except ImportError:
    import xml.etree.ElementTree as LET
    HAVE_LXML = False


def build_lane_index():
    """SUMO lane id -> (physical lane, direction)."""
    idx = {}
    for d in ("EB", "WB"):
        for e in DIR_EDGES[d]:
            for phys in PHYS_LANES:
                idx[lane_id(d, e, phys)] = (phys, d)
    return idx


def iter_timesteps(path):
    if HAVE_LXML:
        ctx = LET.iterparse(path, events=("end",), tag="timestep")
        for _, el in ctx:
            yield float(el.get("time")), [v.attrib for v in el]
            el.clear()
            while el.getprevious() is not None:
                del el.getparent()[0]
    else:
        for ev, el in LET.iterparse(path, events=("end",)):
            if el.tag == "timestep":
                yield float(el.get("time")), [v.attrib for v in el]
                el.clear()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fcd", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default="")
    a = ap.parse_args()

    idx = build_lane_index()
    steps_with_exposure = 0
    total_pairs = 0
    overlap_pairs = 0
    min_gap = float("inf")
    min_ttc = float("inf")
    min_y_sep = float("inf")
    per_phys = defaultdict(int)
    events = []
    n_steps = 0

    for t, vehs in iter_timesteps(a.fcd):
        n_steps += 1
        buckets = defaultdict(lambda: {"EB": [], "WB": []})
        for v in vehs:
            key = idx.get(v.get("lane"))
            if key is None:
                continue
            phys, d = key
            buckets[phys][d].append(
                (v.get("id"), float(v.get("x")), float(v.get("y")), float(v.get("speed"))))
        exposed = False
        for phys, b in buckets.items():
            if not b["EB"] or not b["WB"]:
                continue
            exposed = True
            per_phys[phys] += 1
            for ide, xe, ye, ve in b["EB"]:
                for idw, xw, yw, vw in b["WB"]:
                    total_pairs += 1
                    gap = xw - xe
                    min_y_sep = min(min_y_sep, abs(ye - yw))
                    min_gap = min(min_gap, gap)
                    if gap <= 0:
                        overlap_pairs += 1
                    closing = ve + vw
                    if closing > 0.1:
                        min_ttc = min(min_ttc, max(gap, 0.0) / closing)
                    if len(events) < 3000:
                        events.append(dict(t=t, phys=phys, eb=ide, wb=idw,
                                           x_eb=round(xe, 2), x_wb=round(xw, 2),
                                           y_eb=round(ye, 2), y_wb=round(yw, 2),
                                           gap_m=round(gap, 2),
                                           closing_speed_mps=round(closing, 2)))
        if exposed:
            steps_with_exposure += 1

    rep = dict(
        label=a.label, fcd=a.fcd, fcd_timesteps_scanned=n_steps,
        steps_with_opposing_cooccupancy=steps_with_exposure,
        opposing_pair_samples=total_pairs,
        overlapping_pair_samples=overlap_pairs,
        min_headon_longitudinal_gap_m=None if min_gap == float("inf") else round(min_gap, 2),
        min_headon_ttc_s=None if min_ttc == float("inf") else round(min_ttc, 3),
        min_lateral_separation_m=None if min_y_sep == float("inf") else round(min_y_sep, 3),
        exposure_steps_by_physical_lane=dict(per_phys),
        verdict=("PASS: zero opposing-direction co-occupancy on any physical lane"
                 if steps_with_exposure == 0 else
                 f"FAIL: {steps_with_exposure} timesteps with opposing co-occupancy"),
        n_event_records=len(events), events=events)
    with open(a.out, "w") as f:
        json.dump(rep, f, indent=2)
    print(json.dumps({k: v for k, v in rep.items() if k != "events"}, indent=2))


if __name__ == "__main__":
    main()
