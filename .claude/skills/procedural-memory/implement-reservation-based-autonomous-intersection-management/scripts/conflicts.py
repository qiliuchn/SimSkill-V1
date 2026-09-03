#!/usr/bin/env python3
"""
Extract the GENUINE conflict structure of a compiled SUMO junction from the
net.xml itself -- enumerate internal lanes and decode the <request response/foes>
bitstrings -- rather than assuming a conflict table from geometry.

Technique reused from the `compare-unsignalized-intersection-control-types` skill
("verify right-of-way from the compiled net, not from your intent").

Bitstring convention (verified empirically in this study, see verify() below):
    the RIGHTMOST character of a foes/response string is link index 0,
    i.e.  is_foe(i, j)  <=>  foes[i][len-1-j] == '1'

Usage:
    python conflicts.py --net inter_static.net.xml --json conflicts.json --verify
"""
import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from collections import OrderedDict


def load_junction(net_path, jid="center"):
    tree = ET.parse(net_path)
    root = tree.getroot()

    junction = None
    for j in root.findall("junction"):
        if j.get("id") == jid:
            junction = j
            break
    if junction is None:
        sys.exit("junction %s not found" % jid)

    int_lanes = junction.get("intLanes").split()
    inc_lanes = junction.get("incLanes").split()

    requests = {}
    for r in junction.findall("request"):
        idx = int(r.get("index"))
        requests[idx] = {
            "response": r.get("response"),
            "foes": r.get("foes"),
            "cont": r.get("cont") == "1",
        }
    n = len(requests)

    # connections at this junction, keyed by tl linkIndex
    links = {}
    for c in root.findall("connection"):
        if c.get("linkIndex") is None:
            continue
        li = int(c.get("linkIndex"))
        links[li] = {
            "from_edge": c.get("from"),
            "to_edge": c.get("to"),
            "from_lane": int(c.get("fromLane")),
            "to_lane": int(c.get("toLane")),
            "via": c.get("via"),
            "dir": c.get("dir"),
            "state": c.get("state"),
        }

    # internal lane geometry (length) + the continuation internal lanes of
    # cont=1 links (they live on a second internal edge after the internal junction)
    lane_len = {}
    lane_spd = {}
    int_edge_of = {}
    for e in root.findall("edge"):
        if e.get("function") != "internal":
            continue
        for ln in e.findall("lane"):
            lane_len[ln.get("id")] = float(ln.get("length"))
            lane_spd[ln.get("id")] = float(ln.get("speed"))
        int_edge_of[e.get("id")] = [ln.get("id") for ln in e.findall("lane")]

    # follow via-chains: an internal lane may itself have a <connection> to the
    # next internal lane (for cont=1 links)
    via_next = {}
    for c in root.findall("connection"):
        f = c.get("from")
        if f and f.startswith(":"):
            fl = "%s_%s" % (f, c.get("fromLane"))
            v = c.get("via")
            if v:
                via_next[fl] = v

    return {
        "junction": jid,
        "n_links": n,
        "int_lanes": int_lanes,
        "inc_lanes": inc_lanes,
        "requests": requests,
        "links": links,
        "lane_len": lane_len,
        "lane_spd": lane_spd,
        "via_next": via_next,
    }


def is_foe(foes_str, j):
    """Decode: rightmost char == index 0."""
    return foes_str[len(foes_str) - 1 - j] == "1"


def build(net_path, jid="center"):
    d = load_junction(net_path, jid)
    n = d["n_links"]

    foes = {}
    resp = {}
    for i in range(n):
        fs = d["requests"][i]["foes"]
        rs = d["requests"][i]["response"]
        foes[i] = sorted(j for j in range(n) if is_foe(fs, j))
        resp[i] = sorted(j for j in range(n) if is_foe(rs, j))

    # per-link full internal lane chain + total internal path length
    chain = {}
    ilen = {}
    ispd = {}
    for i in range(n):
        v = d["links"][i]["via"]
        ch = [v]
        cur = v
        while cur in d["via_next"]:
            cur = d["via_next"][cur]
            if cur in ch:
                break
            ch.append(cur)
        chain[i] = ch
        ilen[i] = sum(d["lane_len"].get(x, 0.0) for x in ch)
        ispd[i] = min(d["lane_spd"].get(x, 13.89) for x in ch)

    # internal lane id -> link index (covers continuation lanes too)
    ilane2link = {}
    for i in range(n):
        for ln in chain[i]:
            ilane2link.setdefault(ln, []).append(i)

    # movement key -> link index
    mov2link = {}
    for i, L in d["links"].items():
        mov2link["%s|%d|%s" % (L["from_edge"], L["from_lane"], L["to_edge"])] = i

    out = {
        "junction": jid,
        "n_links": n,
        "links": {str(i): d["links"][i] for i in range(n)},
        "foes": {str(i): foes[i] for i in range(n)},
        "response": {str(i): resp[i] for i in range(n)},
        "cont": {str(i): d["requests"][i]["cont"] for i in range(n)},
        "int_chain": {str(i): chain[i] for i in range(n)},
        "int_len": {str(i): ilen[i] for i in range(n)},
        "int_speed": {str(i): ispd[i] for i in range(n)},
        "ilane2link": {k: v for k, v in ilane2link.items()},
        "mov2link": mov2link,
        "int_lanes": d["int_lanes"],
    }
    return out


def verify(c):
    """Structural sanity checks on the decoded conflict matrix."""
    n = c["n_links"]
    foes = {int(k): set(v) for k, v in c["foes"].items()}
    links = {int(k): v for k, v in c["links"].items()}
    problems = []

    # 1. symmetry
    for i in range(n):
        for j in foes[i]:
            if i not in foes[j]:
                problems.append("asymmetric foe %d<->%d" % (i, j))

    # 2. no self-conflict
    for i in range(n):
        if i in foes[i]:
            problems.append("self-foe %d" % i)

    # 3. movements from the SAME incoming lane must never be foes (they diverge)
    for i in range(n):
        for j in range(n):
            if i >= j:
                continue
            a, b = links[i], links[j]
            if a["from_edge"] == b["from_edge"] and a["from_lane"] == b["from_lane"]:
                if j in foes[i]:
                    problems.append("same-source-lane pair %d,%d marked foes" % (i, j))

    # 4. movements INTO the same outgoing lane MUST be foes (they merge)
    for i in range(n):
        for j in range(n):
            if i >= j:
                continue
            a, b = links[i], links[j]
            if a["to_edge"] == b["to_edge"] and a["to_lane"] == b["to_lane"]:
                if j not in foes[i]:
                    problems.append("same-target-lane pair %d,%d NOT foes" % (i, j))

    # 5. opposing-through pairs must NOT be foes (parallel movements)
    OPP = {"in_N": "in_S", "in_S": "in_N", "in_E": "in_W", "in_W": "in_E"}
    for i in range(n):
        for j in range(n):
            if i >= j:
                continue
            a, b = links[i], links[j]
            if a["dir"] == "s" and b["dir"] == "s" and OPP.get(a["from_edge"]) == b["from_edge"]:
                if j in foes[i]:
                    problems.append("opposing-through %d,%d wrongly foes" % (i, j))

    # 6. crossing-through pairs (perpendicular approaches, both through) MUST be foes
    for i in range(n):
        for j in range(n):
            if i >= j:
                continue
            a, b = links[i], links[j]
            if a["dir"] == "s" and b["dir"] == "s" and a["from_edge"] != b["from_edge"] \
               and OPP.get(a["from_edge"]) != b["from_edge"]:
                if j not in foes[i]:
                    problems.append("perpendicular-through %d,%d NOT foes" % (i, j))
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", required=True)
    ap.add_argument("--junction", default="center")
    ap.add_argument("--json", required=True)
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()

    c = build(a.net, a.junction)
    with open(a.json, "w") as f:
        json.dump(c, f, indent=1, sort_keys=True)

    n = c["n_links"]
    print("junction %s: %d controlled links, %d internal lanes"
          % (c["junction"], n, len(c["int_lanes"])))
    print("\n%-4s %-24s %-4s %-5s %-16s %-7s %s" %
          ("idx", "movement", "dir", "cont", "internal chain", "L_int", "foes"))
    for i in range(n):
        L = c["links"][str(i)]
        print("%-4d %-24s %-4s %-5s %-16s %-7.2f %s" % (
            i, "%s_%d -> %s_%d" % (L["from_edge"], L["from_lane"], L["to_edge"], L["to_lane"]),
            L["dir"], c["cont"][str(i)], ",".join(c["int_chain"][str(i)]),
            c["int_len"][str(i)], c["foes"][str(i)]))

    nf = sum(len(v) for v in c["foes"].values()) // 2
    print("\nconflicting movement PAIRS: %d  (out of %d unordered pairs)"
          % (nf, n * (n - 1) // 2))

    if a.verify:
        p = verify(c)
        if p:
            print("\nVERIFY FAILED (%d problems):" % len(p))
            for x in p[:40]:
                print("  ", x)
            sys.exit(1)
        print("\nVERIFY OK: foe matrix symmetric, no self-foes, same-source-lane "
              "pairs non-conflicting, same-target-lane pairs conflicting, "
              "opposing-through non-conflicting, perpendicular-through conflicting.")


if __name__ == "__main__":
    main()
