#!/usr/bin/env python3
"""
Prove the geometry from the COMPILED net (net.net.xml), never from the input files.

Checks, per variant:
  1. every banned movement has NO connection at junction J (and therefore no linkIndex)
  2. every intended movement HAS a connection at J with a tls linkIndex
  3. each median crossover carries a genuine U-turn connection with dir="t"
  4. the U-turn's right-of-way: its <request> response bit must point at the
     conflicting arterial through movement (yield), and the through movement must
     NOT yield to the U-turn.
Writes a JSON report and prints a human-readable summary.
"""
import json
import sys
import xml.etree.ElementTree as ET

# (from-edge, to-edge) -> movement label, at junction J
J_MOVES = {
    ("E_XW_J", "E_J_XE"): "AR_EB_THRU",
    ("E_XW_J", "M_J_N"): "AR_EB_LEFT",
    ("E_XW_J", "M_J_S"): "AR_EB_RIGHT",
    ("W_XE_J", "W_J_XW"): "AR_WB_THRU",
    ("W_XE_J", "M_J_S"): "AR_WB_LEFT",
    ("W_XE_J", "M_J_N"): "AR_WB_RIGHT",
    ("M_N_J", "M_J_S"): "MI_SB_THRU",
    ("M_N_J", "E_J_XE"): "MI_SB_LEFT",
    ("M_N_J", "W_J_XW"): "MI_SB_RIGHT",
    ("M_S_J", "M_J_N"): "MI_NB_THRU",
    ("M_S_J", "E_J_XE"): "MI_NB_RIGHT",
    ("M_S_J", "W_J_XW"): "MI_NB_LEFT",
}
ALL_MOVES = set(J_MOVES.values())
BANNED = {
    "conv": set(),
    "rcut": {"MI_SB_THRU", "MI_SB_LEFT", "MI_NB_THRU", "MI_NB_LEFT"},
    "mut":  {"AR_EB_LEFT", "AR_WB_LEFT"},
}


def load(netfile):
    return ET.parse(netfile).getroot()


def check(netfile, variant):
    root = load(netfile)
    rep = {"variant": variant, "net": netfile}

    # ---- junction J movements --------------------------------------------
    present, idx = {}, {}
    for cn in root.findall("connection"):
        f, t = cn.get("from"), cn.get("to")
        if f.startswith(":"):
            continue
        key = (f, t)
        if key in J_MOVES:
            m = J_MOVES[key]
            present.setdefault(m, []).append(
                {"fromLane": cn.get("fromLane"), "toLane": cn.get("toLane"),
                 "dir": cn.get("dir"), "state": cn.get("state"),
                 "linkIndex": cn.get("linkIndex")})
    rep["J_movements_present"] = {k: v for k, v in sorted(present.items())}
    exp_banned = BANNED[variant]
    exp_present = ALL_MOVES - exp_banned
    rep["banned_expected"] = sorted(exp_banned)
    rep["banned_actually_absent"] = sorted(m for m in exp_banned if m not in present)
    rep["banned_LEAKED"] = sorted(m for m in exp_banned if m in present)
    rep["allowed_missing"] = sorted(m for m in exp_present if m not in present)
    rep["ok_bans"] = (not rep["banned_LEAKED"]) and (not rep["allowed_missing"])
    # every present J movement must be signal-controlled
    rep["uncontrolled_J_movements"] = sorted(
        m for m, v in present.items() if any(c["linkIndex"] is None for c in v))

    # ---- U-turn crossovers ------------------------------------------------
    uturns = {}
    for cn in root.findall("connection"):
        f, t = cn.get("from"), cn.get("to")
        if f.startswith(":"):
            continue
        if (f, t) == ("W_J_XW", "E_XW_J"):
            uturns["XW"] = cn
        if (f, t) == ("E_J_XE", "W_XE_J"):
            uturns["XE"] = cn
    rep["uturns"] = {}
    for node, cn in uturns.items():
        rep["uturns"][node] = {"from": cn.get("from"), "to": cn.get("to"),
                               "fromLane": cn.get("fromLane"), "toLane": cn.get("toLane"),
                               "dir": cn.get("dir"), "state": cn.get("state"),
                               "via": cn.get("via"), "linkIndex": cn.get("linkIndex")}
    rep["uturn_dir_is_t"] = all(v["dir"] == "t" for v in rep["uturns"].values()) and len(rep["uturns"]) == 2
    rep["uturn_nodes_found"] = sorted(rep["uturns"].keys())

    # ---- right-of-way at the crossovers, from the junction request matrix --
    # build linkIndex -> (from,to) map per junction
    junc_links = {}
    for cn in root.findall("connection"):
        f = cn.get("from")
        if f.startswith(":"):
            continue
        li = cn.get("linkIndex")
        if li is None:
            continue
        # find which junction: the "to" node of the from-edge
        junc_links.setdefault(f, []).append(cn)

    edge_to = {e.get("id"): e.get("to") for e in root.findall("edge") if e.get("function") is None}
    per_junc = {}
    for cn in root.findall("connection"):
        f = cn.get("from")
        if f.startswith(":") or cn.get("linkIndex") is None:
            continue
        j = edge_to.get(f)
        per_junc.setdefault(j, {})[int(cn.get("linkIndex"))] = (f, cn.get("to"),
                                                                cn.get("fromLane"), cn.get("dir"))

    # use sumolib for the junction link-index / response / foe matrices
    import os
    sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
    import sumolib
    snet = sumolib.net.readNet(netfile)
    rep["crossover_row"] = {}
    for j in ("XW", "XE"):
        node = snet.getNode(j)
        conns = [c for c in node.getConnections()
                 if not c.getFrom().getID().startswith(":")]
        idx = {}
        for c_ in conns:
            i = node.getLinkIndex(c_)
            if i >= 0:
                idx[i] = c_
        def lbl(c_):
            return (f"{c_.getFrom().getID()}_{c_.getFromLane().getIndex()}"
                    f"->{c_.getTo().getID()}_{c_.getToLane().getIndex()}"
                    f"(dir={c_.getDirection()})")
        row = {"n_links": len(idx),
               "links": {i: lbl(c_) for i, c_ in sorted(idx.items())}}
        ut = [(i, c_) for i, c_ in idx.items() if c_.getDirection() == "t"]
        details = []
        for ui, uc in ut:
            yields_to = sorted(i for i, c_ in idx.items()
                               if i != ui and node.forbids(c_, uc))
            yielded_by = sorted(i for i, c_ in idx.items()
                                if i != ui and node.forbids(uc, c_))
            foes = sorted(i for i, c_ in idx.items()
                          if i != ui and node.areFoes(ui, i))
            details.append({"uturn_index": ui, "uturn_link": lbl(uc),
                            "uturn_yields_to_links": yields_to,
                            "uturn_yields_to_moves": [row["links"][i] for i in yields_to],
                            "uturn_foes": foes,
                            "uturn_foe_moves": [row["links"][i] for i in foes],
                            "links_that_yield_to_uturn": yielded_by})
        row["uturn_link_indices"] = [i for i, _ in ut]
        row["uturn_row_analysis"] = details
        rep["crossover_row"][j] = row

    # summary flags for the yield relationship
    flags = {}
    for j, row in rep["crossover_row"].items():
        d = row["uturn_row_analysis"]
        if not d:
            flags[j] = "NO_UTURN_LINK"
            continue
        d0 = d[0]
        yields = len(d0["uturn_yields_to_links"]) > 0
        not_yielded_to = len(d0["links_that_yield_to_uturn"]) == 0
        flags[j] = {"uturn_yields": yields, "nobody_yields_to_uturn": not_yielded_to,
                    "verdict": "UNSIGNALIZED_YIELD_UTURN" if (yields and not_yielded_to) else "CHECK"}
    rep["crossover_verdict"] = flags
    rep["crossover_junction_type"] = {j: root.find(f"junction[@id='{j}']").get("type")
                                      for j in ("XW", "XE")}
    rep["J_junction_type"] = root.find("junction[@id='J']").get("type")
    return rep


if __name__ == "__main__":
    out = []
    for variant, netfile in zip(sys.argv[2::2], sys.argv[3::2]):
        out.append(check(netfile, variant))
    with open(sys.argv[1], "w") as f:
        json.dump(out, f, indent=1)
    for r in out:
        print(f"\n===== {r['variant']}  ({r['net']}) =====")
        print(f"  J type={r['J_junction_type']}  crossover types={r['crossover_junction_type']}")
        print(f"  banned expected : {r['banned_expected']}")
        print(f"  banned absent   : {r['banned_actually_absent']}")
        print(f"  banned LEAKED   : {r['banned_LEAKED']}   allowed missing: {r['allowed_missing']}")
        print(f"  ok_bans={r['ok_bans']}  uncontrolled J movements={r['uncontrolled_J_movements']}")
        print(f"  U-turns found at {r['uturn_nodes_found']}  all dir=='t': {r['uturn_dir_is_t']}")
        for j, v in r["uturns"].items():
            print(f"    {j}: {v['from']}_{v['fromLane']} -> {v['to']}_{v['toLane']} dir={v['dir']} state={v['state']}")
        for j, v in r["crossover_verdict"].items():
            print(f"    {j} verdict: {v}")
        for j, row in r["crossover_row"].items():
            for d in row["uturn_row_analysis"]:
                print(f"    {j} U-turn link {d['uturn_index']} yields to: {d['uturn_yields_to_moves']}")
                print(f"       links that yield to the U-turn: {d['links_that_yield_to_uturn']}")
