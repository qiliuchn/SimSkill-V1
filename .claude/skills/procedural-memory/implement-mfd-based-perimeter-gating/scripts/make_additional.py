#!/usr/bin/env python3
"""
Build the per-run additional file:
  * an E3 (entry/exit) cordon detector around the CORE:
      detEntry on every gate edge (outside -> core), detExit on every
      core-outbound edge (core -> outside).  NOTE: trips that *end* inside the
      core never cross an exit point, so E3 vehicleSum over-counts occupancy;
      the TraCI edge-based accumulation is the primary instrument and the
      core edgeData below is the independent cross-check.
  * edgeData restricted to the core edges (fine interval)
  * edgeData over the whole network (coarse interval)
"""
import argparse
import json
import xml.etree.ElementTree as ET


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", required=True)
    ap.add_argument("--core-gate", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--interval", type=float, default=60.0)
    ap.add_argument("--light", action="store_true",
                    help="omit the network-wide edgeData (seed replications)")
    args = ap.parse_args()

    cg = json.load(open(args.core_gate))
    root = ET.parse(args.net).getroot()
    lanes_of = {}
    lane_len = {}
    for e in root.findall("edge"):
        if e.get("function") == "internal":
            continue
        ls = [l.get("id") for l in e.findall("lane")]
        lanes_of[e.get("id")] = ls
        for l in e.findall("lane"):
            lane_len[l.get("id")] = float(l.get("length"))

    with open(args.out, "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<additional>\n')
        f.write(f'  <e3Detector id="core_cordon" freq="{args.interval:.0f}" '
                f'file="{args.outdir}/e3_core.xml" openEntry="true">\n')
        for eid in cg["gate_edges"]:
            for l in lanes_of[eid]:
                f.write(f'    <detEntry lane="{l}" pos="{lane_len[l] - 2.0:.2f}"/>\n')
        for eid in cg["core_outbound_edges"]:
            for l in lanes_of[eid]:
                f.write(f'    <detExit lane="{l}" pos="2.0"/>\n')
        f.write('  </e3Detector>\n')
        f.write(f'  <edgeData id="core" file="{args.outdir}/edgedata_core.xml" '
                f'period="{args.interval:.0f}" edges="{" ".join(cg["core_edges"])}" '
                f'excludeEmpty="false"/>\n')
        if not args.light:
            f.write(f'  <edgeData id="all" file="{args.outdir}/edgedata_all.xml" '
                    f'period="300" excludeEmpty="true"/>\n')
        f.write('</additional>\n')
    print("wrote", args.out)


if __name__ == "__main__":
    main()
