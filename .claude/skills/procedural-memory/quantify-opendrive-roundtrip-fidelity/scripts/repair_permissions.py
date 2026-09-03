#!/usr/bin/env python3
"""
repair_permissions.py -- REPAIR RECIPE for the #2 OpenDRIVE-round-trip defect:
per-lane vClass permissions are not carried through OpenDRIVE.  With
--opendrive.import-all-lanes, sidewalks / bike lanes / restricted lanes come back
as ORDINARY lanes that passenger cars may use (or, for some types, as
disallow="all" lanes usable by nobody).  Either way the carriageway/sidewalk
distinction is destroyed and the car-usable network silently changes size.

Fix: map every round-trip edge back to its original counterpart geometrically and
re-apply the original per-lane allow/disallow through a netconvert edge PATCH:

    netconvert --sumo-net-file RT.net.xml --edge-files perm_patch.edg.xml -o REPAIRED.net.xml

Unmapped round-trip edges are listed in the report and left untouched (they are
new artefacts of the conversion, not recoverable from the original).

Usage:
  python repair_permissions.py --orig A.net.xml --rt B.net.xml \
      --patch perm_patch.edg.xml --out B_repaired.net.xml [--report r.json]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import netdiff  # noqa: E402
import mapdemand  # noqa: E402


def find_netconvert():
    f = shutil.which("netconvert")
    if f:
        return f
    s = shutil.which("sumo")
    if s and os.path.isfile(os.path.join(os.path.dirname(s), "netconvert")):
        return os.path.join(os.path.dirname(s), "netconvert")
    return os.path.join(os.environ.get("SUMO_HOME", ""), "bin", "netconvert")


def lane_perm_attrs(netfile):
    """{edgeId: [(allow, disallow) per lane]}"""
    r = ET.parse(netfile).getroot()
    out = {}
    for e in r.findall("edge"):
        if e.get("function") == "internal":
            continue
        out[e.get("id")] = [(l.get("allow"), l.get("disallow")) for l in e.findall("lane")]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--orig", required=True)
    ap.add_argument("--rt", required=True)
    ap.add_argument("--patch", required=True)
    ap.add_argument("--out")
    ap.add_argument("--report")
    a = ap.parse_args()

    emap, info = mapdemand.build_map(a.orig, a.rt)
    inv = {v: k for k, v in emap.items()}
    po, pr = lane_perm_attrs(a.orig), lane_perm_attrs(a.rt)

    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<edges>"]
    patched = unmapped = lanecount_mismatch = 0
    for rid, rlanes in pr.items():
        oid = inv.get(rid)
        if oid is None:
            unmapped += 1
            continue
        olanes = po[oid]
        if len(olanes) == len(rlanes):
            body = []
            for i, (al, dis) in enumerate(olanes):
                at = ""
                if al is not None:
                    at += f' allow="{al}"'
                if dis is not None:
                    at += f' disallow="{dis}"'
                if not at:
                    at = ' allow="all"'
                body.append(f'        <lane index="{i}"{at}/>')
            lines.append(f'    <edge id="{rid}">')
            lines += body
            lines.append("    </edge>")
        else:
            lanecount_mismatch += 1
            al, dis = olanes[0]
            at = f' allow="{al}"' if al else (f' disallow="{dis}"' if dis else ' allow="all"')
            lines.append(f'    <edge id="{rid}"{at}/>')
        patched += 1
    lines.append("</edges>")
    open(a.patch, "w").write("\n".join(lines) + "\n")

    rep = {"edge_map": info, "edges_patched": patched, "edges_unmapped": unmapped,
           "lanecount_mismatch": lanecount_mismatch, "patch": a.patch}
    if a.out:
        nc = find_netconvert()
        p = subprocess.run([nc, "--sumo-net-file", a.rt, "--edge-files", a.patch,
                            "-o", a.out], capture_output=True, text=True)
        rep["netconvert_rc"] = p.returncode
        rep["netconvert_tail"] = ((p.stdout or "") + (p.stderr or ""))[-1200:]
    if a.report:
        json.dump(rep, open(a.report, "w"), indent=1)
    print(json.dumps({k: v for k, v in rep.items() if k != "netconvert_tail"}))


if __name__ == "__main__":
    main()
