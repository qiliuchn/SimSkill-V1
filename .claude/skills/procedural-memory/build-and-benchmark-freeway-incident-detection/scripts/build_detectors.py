"""Build the E1 induction-loop additional file: one station every 250 m, ALL lanes per station.

Coarser station spacings (500 m, 1000 m) are realised post hoc by sub-sampling stations,
so a single instrumented run serves the whole spacing sensitivity sweep.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import *
import xml.etree.ElementTree as ET

os.makedirs(DET_DIR, exist_ok=True)
NET = os.path.join(NET_DIR, "freeway.net.xml")


def lane_counts():
    t = ET.parse(NET)
    out = {}
    for e in t.getroot().findall("edge"):
        if e.get("function") == "internal":
            continue
        out[e.get("id")] = len(e.findall("lane"))
    return out


def build(det_out_path):
    """Return the additional-file XML text; `det_out_path` must be ABSOLUTE
    (edgeData/E1 `file` attributes resolve relative to the additional file's own dir)."""
    lc = lane_counts()
    x = ['<additional>']
    for k in range(N_SEG):
        eid = f"m{k:02d}"
        for li in range(lc[eid]):
            x.append(f'  <inductionLoop id="st{k:02d}_l{li}" lane="{eid}_{li}" pos="5" '
                     f'period="{DET_PERIOD:.0f}" file="{det_out_path}" friendlyPos="true"/>')
    x.append('</additional>')
    return "\n".join(x) + "\n"


if __name__ == "__main__":
    p = os.path.join(DET_DIR, "detectors_template.add.xml")
    with open(p, "w") as f:
        f.write(build(os.path.join(DET_DIR, "e1_out.xml")))
    print("wrote", p)
    print("stations:", N_SEG, "lane counts:", {k: v for k, v in lane_counts().items() if k.startswith('m0')})
    for sp in (250, 500, 1000):
        print(f"spacing {sp}m -> stations {stations_for_spacing(sp)}")
