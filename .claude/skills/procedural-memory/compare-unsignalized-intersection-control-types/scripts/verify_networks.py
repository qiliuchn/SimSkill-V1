#!/usr/bin/env python3
"""
Verify from the COMPILED .net.xml (not the inputs):
  (i)  each variant's center junction `type` is exactly the intended SUMO type.
  (ii) for the TWSC (priority) variant, that the N-S minor approaches YIELD to
       the E-W major approaches, decoded from connection link-states ('M' major /
       'm' minor) and the center junction's request/response (foe) matrix.

For right_before_left / allway_stop / traffic_light we just report the center
type + the link-state summary for context.
"""
import os
import sys
import xml.etree.ElementTree as ET

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NET = os.path.join(BASE, "outputs", "network")

VARIANTS = {
    "A_right_before_left": "right_before_left",
    "B_priority":          "priority",
    "C_allway_stop":       "allway_stop",
    "D_traffic_light":     "traffic_light",
}
MAJOR_IN = {"in_E", "in_W"}
MINOR_IN = {"in_N", "in_S"}


def center_type(root):
    for j in root.findall("junction"):
        if j.get("id") == "center":
            return j.get("type")
    return None


def edge_of_lane(lane):
    return lane.rsplit("_", 1)[0]


def verify_variant(vname, expected_type):
    path = os.path.join(NET, f"{vname}.net.xml")
    root = ET.parse(path).getroot()
    ctype = center_type(root)
    ok = (ctype == expected_type)
    print(f"\n=== {vname} ===")
    print(f"  center junction type = {ctype!r}  expected {expected_type!r}  -> {'OK' if ok else 'FAIL'}")

    # connections crossing the center: from in_* to out_*
    conns = [c for c in root.findall("connection")
             if c.get("from", "").startswith("in_") and c.get("to", "").startswith("out_")]
    major_states = sorted({c.get("state") for c in conns if c.get("from") in MAJOR_IN})
    minor_states = sorted({c.get("state") for c in conns if c.get("from") in MINOR_IN})
    print(f"  major (E-W) approach link states: {major_states}")
    print(f"  minor (N-S) approach link states: {minor_states}")

    if expected_type == "priority":
        # For genuine TWSC: minor through/left movements must carry give-way 'm';
        # major movements must carry priority 'M'. Right turns can be 'm' on both.
        # Decode the request/response foe matrix on the center junction.
        cj = next(j for j in root.findall("junction") if j.get("id") == "center")
        reqs = cj.findall("request")
        # Top-level <connection> elements carry no linkIndex on a non-TLS
        # junction; SUMO indexes links deterministically by incLanes order
        # (here N,E,S,W) and, within each incoming lane, right->straight->left.
        # Reconstruct idx->connection from that order, which matches the
        # in_->out connection list exactly.
        order = ["in_N", "in_E", "in_S", "in_W"]
        dir_rank = {"r": 0, "s": 1, "l": 2}
        conn_by_from = {}
        for c in conns:
            conn_by_from.setdefault(c.get("from"), []).append(c)
        idx2conn = {}
        idx = 0
        for frm in order:
            for c in sorted(conn_by_from.get(frm, []), key=lambda x: dir_rank.get(x.get("dir"), 9)):
                idx2conn[idx] = c
                idx += 1
        n = idx
        # SUMO response/foes bitstrings are written HIGHEST index first
        # (leftmost char = link n-1), so char position p from left = index n-1-p.
        def bits_set(s):
            return {n - 1 - p for p, ch in enumerate(s) if ch == "1"}

        minor_yields_major = True
        minor_defers = False
        details = []
        for r in reqs:
            i = int(r.get("index"))
            resp = r.get("response", "")
            c = idx2conn.get(i)
            if c is None:
                continue
            frm, direc, state = c.get("from"), c.get("dir"), c.get("state")
            yset = bits_set(resp)
            ynames = [f"{idx2conn[k].get('from')}:{idx2conn[k].get('dir')}" for k in sorted(yset) if k in idx2conn]
            details.append((i, frm, direc, state, resp, ynames))
            if frm in MAJOR_IN and direc == "s":
                if any(idx2conn.get(k) is not None and idx2conn[k].get("from") in MINOR_IN for k in yset):
                    minor_yields_major = False
            if frm in MINOR_IN:
                if any(idx2conn.get(k) is not None and idx2conn[k].get("from") in MAJOR_IN for k in yset):
                    minor_defers = True
        print("  --- TWSC foe-matrix decode (idx, from, dir, state, response, yields-to) ---")
        for i, frm, direc, state, resp, ynames in sorted(details):
            print(f"    idx={i:2d} {frm:5s} dir={direc} state={state} resp={resp} yields_to={ynames}")
        print(f"  minor (N-S) movements defer to major (E-W): {minor_defers} -> {'OK' if minor_defers else 'FAIL'}")
        print(f"  no major-through yields to a minor movement: {minor_yields_major} -> {'OK' if minor_yields_major else 'FAIL'}")
        ok = ok and minor_defers and minor_yields_major

    # tlLogic presence
    tls = root.findall("tlLogic")
    print(f"  tlLogic programs in net: {len(tls)}  (expected {'>=1' if expected_type=='traffic_light' else '0'})")
    if expected_type == "traffic_light":
        ok = ok and len(tls) >= 1
    else:
        ok = ok and len(tls) == 0
    return ok


def main():
    allok = True
    for v, t in VARIANTS.items():
        allok &= verify_variant(v, t)
    print("\n==== OVERALL:", "ALL VARIANTS VERIFIED" if allok else "VERIFICATION FAILED", "====")
    sys.exit(0 if allok else 1)


if __name__ == "__main__":
    main()
