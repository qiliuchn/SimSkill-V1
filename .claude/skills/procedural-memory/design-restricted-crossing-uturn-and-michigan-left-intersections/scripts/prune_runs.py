#!/usr/bin/env python3
"""
Shrink the raw run directories for archival WITHOUT destroying the evidence the
results tables rest on.

For every run directory:
  * summary.xml (one row per 0.5 s step, ~5 MB) is replaced by summary_sparse.xml
    holding every 60 s step plus the FINAL step -- enough to detect a
    running-count freeze (the survivorship-censoring check) and to read the final
    cumulative loaded/inserted/arrived/teleports, which is all any table uses.
  * tripinfo.xml and lanearea.xml are gzipped (per-vehicle and per-detector raw
    data are retained in full).
  * ssm.xml is gzipped for the runs listed in KEEP_SSM and deleted elsewhere
    (its aggregate is already in results/ssm_summary.json).
Run this ONLY after analyze.py / ssm_analyze.py have produced the result files.
"""
import gzip
import os
import shutil
import sys
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEEP_SSM_PREFIX = ("ssm_conv_D400_Q2400_m30_s1", "ssm_rcut_D400_Q2400_m30_s1",
                   "ssm_mut_D400_Q2400_m30_s1")


def sparsify(p, every=60.0):
    keep, last = [], None
    for _, s in ET.iterparse(p, events=("end",)):
        if s.tag != "step":
            continue
        t = float(s.get("time"))
        if abs(t % every) < 0.26:
            keep.append(dict(s.attrib))
        last = dict(s.attrib)
        s.clear()
    if last and (not keep or keep[-1] is not last):
        keep.append(last)
    out = p.replace("summary.xml", "summary_sparse.xml")
    with open(out, "w") as f:
        f.write("<summary>\n")
        for s in keep:
            f.write("  <step " + " ".join(f'{k}="{v}"' for k, v in s.items()) + "/>\n")
        f.write("</summary>\n")
    return out


def gz(p):
    with open(p, "rb") as fi, gzip.open(p + ".gz", "wb", compresslevel=9) as fo:
        shutil.copyfileobj(fi, fo)
    os.remove(p)


def main(roots):
    n = 0
    for root in roots:
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            d = os.path.join(root, name)
            if not os.path.exists(os.path.join(d, "DONE")):
                continue
            p = os.path.join(d, "summary.xml")
            if os.path.exists(p):
                sparsify(p)
                os.remove(p)
            for f in ("tripinfo.xml", "lanearea.xml", "vehroute.xml"):
                q = os.path.join(d, f)
                if os.path.exists(q):
                    gz(q)
            q = os.path.join(d, "ssm.xml")
            if os.path.exists(q):
                if name in KEEP_SSM_PREFIX:
                    gz(q)
                else:
                    os.remove(q)
            n += 1
    print("pruned", n, "run dirs")


if __name__ == "__main__":
    main(sys.argv[1:] or [os.path.join(ROOT, "runs")])
