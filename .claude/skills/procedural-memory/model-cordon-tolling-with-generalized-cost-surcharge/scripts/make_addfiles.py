#!/usr/bin/env python3
"""Generate the E3 (entryExitDetector) + edgeData additional files for a run.

The E3 detector rings the central cordon zone: entry detectors sit at the
downstream end of every cordon-entry edge (the point of crossing INTO the priced
area) and exit detectors sit at the start of every edge leaving the zone, so the
detector measures vehicles that enter the priced zone and their mean in-zone
travel time. A separate edgeData collector aggregates all edges over the run.
"""
import os, sys, json
import sumolib

def main(net_file, info_file, outdir, end):
    os.makedirs(outdir, exist_ok=True)
    info = json.load(open(info_file))
    net = sumolib.net.readNet(net_file)
    e3_out = os.path.join(outdir, "e3_cordon.xml")
    ed_out = os.path.join(outdir, "edgedata.xml")

    lines = ['<additional>']
    lines.append(f'  <entryExitDetector id="cordon" pos="0" '
                 f'file="{e3_out}" period="{end}" openEntry="true">')
    # entry detectors: 5 m before the end of each cordon-entry edge (crossing in)
    for e in info["entry"]:
        L = net.getEdge(e).getLength()
        pos = max(1.0, L - 5.0)
        lines.append(f'    <detEntry lane="{e}_0" pos="{pos:.2f}"/>')
    # exit detectors: 5 m into each edge leaving the zone (crossing out)
    for e in info["exit"]:
        lines.append(f'    <detExit lane="{e}_0" pos="5.00"/>')
    lines.append('  </entryExitDetector>')
    lines.append('</additional>')
    with open(os.path.join(outdir, "e3.add.xml"), "w") as f:
        f.write("\n".join(lines) + "\n")

    with open(os.path.join(outdir, "edgedata.add.xml"), "w") as f:
        f.write('<additional>\n'
                f'  <edgeData id="all" file="{ed_out}" begin="0" end="{end}"/>\n'
                '</additional>\n')
    print("wrote add files to", outdir)

if __name__ == "__main__":
    net_file, info_file, outdir, end = sys.argv[1:5]
    main(net_file, info_file, outdir, int(end))
