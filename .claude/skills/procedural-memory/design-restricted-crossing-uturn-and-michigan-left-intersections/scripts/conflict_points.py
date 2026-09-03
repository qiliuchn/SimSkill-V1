#!/usr/bin/env python3
"""
Count MOVEMENT-LEVEL conflict points from the COMPILED net, the classic
crossing / merging / diverging taxonomy, for the main junction alone and for
the whole intersection SYSTEM (main junction + both median crossovers).

crossing  : pair of movements from different approaches to different exits that
            the compiled net flags as foes
merging   : per exit edge, (number of distinct approaches feeding it - 1)
diverging : per approach edge, (number of distinct exits served - 1)

This is the direct test of the textbook "32 conflict points -> 14" claim, and of
whether the removed points are eliminated or merely RELOCATED to the crossovers.
"""
import itertools
import json
import os
import sys
from collections import defaultdict

sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import sumolib  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def junction_points(net, jid):
    node = net.getNode(jid)
    conns = [c for c in node.getConnections() if not c.getFrom().getID().startswith(":")]
    idx = {}
    for c in conns:
        i = node.getLinkIndex(c)
        if i >= 0:
            idx.setdefault((c.getFrom().getID(), c.getTo().getID()), []).append(i)
    moves = sorted(idx)
    crossing = []
    for (a1, b1), (a2, b2) in itertools.combinations(moves, 2):
        if a1 == a2 or b1 == b2:
            continue
        if any(node.areFoes(i, j) for i in idx[(a1, b1)] for j in idx[(a2, b2)]):
            crossing.append((f"{a1}->{b1}", f"{a2}->{b2}"))
    byexit = defaultdict(set)
    byapp = defaultdict(set)
    for a, b in moves:
        byexit[b].add(a)
        byapp[a].add(b)
    merging = sum(max(len(v) - 1, 0) for v in byexit.values())
    diverging = sum(max(len(v) - 1, 0) for v in byapp.values())
    return {"junction": jid, "n_movements": len(moves),
            "movements": [f"{a}->{b}" for a, b in moves],
            "crossing": len(crossing), "crossing_pairs": crossing,
            "merging": merging, "diverging": diverging,
            "total": len(crossing) + merging + diverging}


def main(D=400):
    out = {}
    for v in ("conv", "rcut", "mut"):
        netf = os.path.join(ROOT, "nets", f"{v}_D{D}", "net.net.xml")
        net = sumolib.net.readNet(netf)
        per = {j: junction_points(net, j) for j in ("J", "XW", "XE")}
        sysm = {k: sum(per[j][k] for j in per) for k in ("crossing", "merging", "diverging", "total")}
        out[v] = {"per_junction": per, "system_total": sysm,
                  "main_junction_total": per["J"]["total"]}
    with open(os.path.join(ROOT, "results", "conflict_points.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(f"{'variant':6s} {'J:cross':>8s} {'J:merge':>8s} {'J:div':>6s} {'J:TOT':>6s} "
          f"{'SYS:cross':>10s} {'SYS:merge':>10s} {'SYS:div':>8s} {'SYS:TOT':>8s}")
    for v, r in out.items():
        j = r["per_junction"]["J"]
        s = r["system_total"]
        print(f"{v:6s} {j['crossing']:8d} {j['merging']:8d} {j['diverging']:6d} {j['total']:6d} "
              f"{s['crossing']:10d} {s['merging']:10d} {s['diverging']:8d} {s['total']:8d}")
    return out


if __name__ == "__main__":
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    main()
