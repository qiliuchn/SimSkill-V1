#!/usr/bin/env python3
"""Generate a per-scenario detector additional-file with absolute output paths.

Detectors (for the REAL 2->1 merge lane-drop bottleneck at B):
  - E2 laneAreaDetector on the two through lanes (m_1, m_2) just upstream of the
    merge point B -> controller occupancy input.
  - E1 inductionLoop on the hard shoulder lane through the bottleneck (w_0) -> shoulder
    flow (used to verify zero / continuous / windowed shoulder usage across scenarios).
  - E1 inductionLoops on the two bottleneck exit lanes (w_0 shoulder, w_1 through) ->
    discharge / throughput.
  - edgeData mean-data over edges m,w -> aggregate speed / time-loss per edge.
"""
import argparse, os

TEMPLATE = """<additional>
    <!-- E2 lane-area detectors on the two through lanes just upstream of the merge
         point B (occupancy source for the controller) -->
    <laneAreaDetector id="e2_thru_1" lane="m_1" pos="1650" length="500" period="30" file="{det_e2}" friendlyPos="true"/>
    <laneAreaDetector id="e2_thru_2" lane="m_2" pos="1650" length="500" period="30" file="{det_e2}" friendlyPos="true"/>

    <!-- E1 induction loop on the hard shoulder lane within the bottleneck (shoulder flow) -->
    <inductionLoop id="e1_shoulder" lane="w_0" pos="500" period="60" file="{det_shoulder}" friendlyPos="true"/>

    <!-- E1 induction loops at the bottleneck exit, one per lane incl. shoulder (discharge / throughput) -->
    <inductionLoop id="e1_exit_s" lane="w_0" pos="1050" period="60" file="{det_exit}" friendlyPos="true"/>
    <inductionLoop id="e1_exit_0" lane="w_1" pos="1050" period="60" file="{det_exit}" friendlyPos="true"/>

    <!-- Aggregate edge data -->
    <edgeData id="ed" file="{edgedata}" period="300"/>
</additional>
"""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--out", required=True, help="path to write the .add.xml")
    a = ap.parse_args()
    od = os.path.abspath(a.outdir)
    os.makedirs(od, exist_ok=True)
    content = TEMPLATE.format(
        det_e2=os.path.join(od, "det_e2.xml"),
        det_shoulder=os.path.join(od, "det_shoulder.xml"),
        det_exit=os.path.join(od, "det_exit.xml"),
        edgedata=os.path.join(od, "edgedata.xml"),
    )
    with open(a.out, "w") as f:
        f.write(content)
    print("wrote", a.out)

if __name__ == "__main__":
    main()
