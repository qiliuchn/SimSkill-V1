#!/usr/bin/env python3
"""
Calibrate the ALINEA setpoint from the network's OWN data, as the skill prescribes:
trace the flow-vs-occupancy relation of the leftmost lane using the 60-s E2 detector time
series from arm-A runs (where lane 3 is an ORDINARY general-purpose lane and therefore gets
loaded all the way through capacity), and read off the occupancy at which flow peaks.
"""
import glob
import gzip
import os
import statistics as st
import sys
import xml.etree.ElementTree as ET

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DETS = ("e2_ml_m7", "e2_ml_m10", "e2_ml_m12")


def samples(rundirs):
    pts = []
    for d in rundirs:
        f = os.path.join(d, "e2.xml")
        if os.path.exists(f):
            fh = open(f, "rb")
        elif os.path.exists(f + ".gz"):
            fh = gzip.open(f + ".gz", "rb")
        else:
            continue
        for _, iv in ET.iterparse(fh, events=("end",)):
            if iv.tag != "interval":
                iv.clear()
                continue
            if iv.get("id") in DETS:
                b, e = float(iv.get("begin")), float(iv.get("end"))
                occ = float(iv.get("meanOccupancy"))
                nleft = float(iv.get("nVehLeft"))
                flow = nleft * 3600.0 / max(1e-9, e - b)
                spd = float(iv.get("meanSpeed"))
                if b >= 600 and occ >= 0.5:       # skip loading transient and empty-detector samples
                    pts.append((occ, flow, spd))
            iv.clear()
    return pts


def main():
    dirs = sorted(glob.glob(os.path.join(ROOT, "runs", "H1dm_A_*")) +
                  glob.glob(os.path.join(ROOT, "runs", "H1cp_A_*")) +
                  glob.glob(os.path.join(ROOT, "runs", "CAP_A_*")))
    pts = samples(dirs)
    print(f"{len(pts)} 60-s lane-3 samples from {len(dirs)} arm-A runs")
    W = 1.0
    bins = {}
    for occ, flow, spd in pts:
        k = round(occ / W) * W
        bins.setdefault(k, []).append((flow, spd))
    lines = [f"{'occ%':>6} {'n':>5} {'flow veh/h':>11} {'speed m/s':>10} {'speed mph':>10}"]
    best = (None, -1)
    for k in sorted(bins):
        v = bins[k]
        if len(v) < 15:
            continue
        fl = st.mean(x[0] for x in v)
        sp = st.mean(x[1] for x in v)
        lines.append(f"{k:6.1f} {len(v):5d} {fl:11.0f} {sp:10.2f} {sp*2.23694:10.1f}")
        if fl > best[1]:
            best = (k, fl)
    lines.append("")
    lines.append(f"CRITICAL OCCUPANCY (peak of the flow-occupancy curve for the leftmost lane) "
                 f"= {best[0]:.1f}%  at {best[1]:.0f} veh/h")
    # occupancy at which speed drops below the 45 mph (20.12 m/s) managed-lane standard
    thr = None
    for k in sorted(bins):
        if len(bins[k]) < 15:
            continue
        if st.mean(x[1] for x in bins[k]) < 20.12:
            thr = k
            break
    lines.append(f"Occupancy at which lane speed first falls below the 45 mph standard = "
                 f"{thr if thr is not None else 'never in sampled range'}%")
    txt = "\n".join(lines)
    print(txt)
    open(os.path.join(ROOT, "analysis", "alinea_setpoint_calibration.txt"), "w").write(
        f"{len(pts)} 60-s lane-3 samples from {len(dirs)} arm-A runs\n" + txt + "\n")
    return best[0]


if __name__ == "__main__":
    sys.exit(0 if main() else 0)
