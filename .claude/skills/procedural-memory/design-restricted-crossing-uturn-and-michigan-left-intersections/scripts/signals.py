#!/usr/bin/env python3
"""
Size each variant's signal INDEPENDENTLY by Webster, from that variant's OWN
movement volumes at J (counted from its own duarouter routes -- so rerouted
traffic that passes J twice is counted twice, as it physically does).

Phase count is therefore a CONSEQUENCE of the geometry:
  conv -> 4 phases (art thru/right, art protected left, minor thru/right, minor left)
  rcut -> 2 phases (each arterial direction served whole, with the opposing minor
                    right turn; no movement at J conflicts across directions)
  mut  -> 3 phases (art thru/right, minor thru/right, minor protected left;
                    the arterial protected-left phase is SHED)

Saturation flows / startup lost times come from calib/sat_flow.json (measured on
this very geometry by measure_saturation.py), never from a textbook default.
"""
import itertools
import json
import os
import sys
import xml.etree.ElementTree as ET

sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import sumolib  # noqa: E402


def _open_maybe_gz(p):
    """Open an XML file that may have been gzipped by prune_runs/archival."""
    import gzip as _gz, os as _os
    if not _os.path.exists(p) and _os.path.exists(p + ".gz"):
        return _gz.open(p + ".gz", "rb")
    if p.endswith(".gz"):
        return _gz.open(p, "rb")
    return open(p, "rb")



YELLOW = 3.0
ALLRED = 2.0
CMIN, CMAX = 50.0, 160.0
GMIN = 7.0

J_MOVES = {
    ("E_XW_J", "E_J_XE"): "AR_EB_THRU", ("E_XW_J", "M_J_N"): "AR_EB_LEFT",
    ("E_XW_J", "M_J_S"): "AR_EB_RIGHT",
    ("W_XE_J", "W_J_XW"): "AR_WB_THRU", ("W_XE_J", "M_J_S"): "AR_WB_LEFT",
    ("W_XE_J", "M_J_N"): "AR_WB_RIGHT",
    ("M_N_J", "M_J_S"): "MI_SB_THRU", ("M_N_J", "E_J_XE"): "MI_SB_LEFT",
    ("M_N_J", "W_J_XW"): "MI_SB_RIGHT",
    ("M_S_J", "M_J_N"): "MI_NB_THRU", ("M_S_J", "W_J_XW"): "MI_NB_LEFT",
    ("M_S_J", "E_J_XE"): "MI_NB_RIGHT",
}
PHASES = {
    "conv": [[["AR_EB_THRU", "AR_EB_RIGHT"], ["AR_WB_THRU", "AR_WB_RIGHT"]],
             [["AR_EB_LEFT"], ["AR_WB_LEFT"]],
             [["MI_SB_THRU", "MI_SB_RIGHT"], ["MI_NB_THRU", "MI_NB_RIGHT"]],
             [["MI_SB_LEFT"], ["MI_NB_LEFT"]]],
    "rcut": [[["AR_EB_THRU", "AR_EB_RIGHT", "AR_EB_LEFT"], ["MI_SB_RIGHT"]],
             [["AR_WB_THRU", "AR_WB_RIGHT", "AR_WB_LEFT"], ["MI_NB_RIGHT"]]],
    "mut":  [[["AR_EB_THRU", "AR_EB_RIGHT"], ["AR_WB_THRU", "AR_WB_RIGHT"]],
             [["MI_SB_THRU", "MI_SB_RIGHT"], ["MI_NB_THRU", "MI_NB_RIGHT"]],
             [["MI_SB_LEFT"], ["MI_NB_LEFT"]]],
}


def sat_key(move, lane_index, variant):
    fam, _, mv = move.split("_")
    if fam == "AR":
        return {"THRU": "AR_THRU", "LEFT": "AR_LEFT", "RIGHT": "AR_RIGHT"}[mv]
    if mv == "THRU":
        return "MI_THRU"
    if mv == "LEFT":
        return "MI_LEFT"
    return "MI_RIGHT2" if (variant == "rcut" and lane_index == 1) else "MI_RIGHT"


def movement_volumes(routefile, period_h=1.0):
    """Count how many routed vehicles traverse each J movement (double-counted if
    the route passes J twice, which is exactly what the signal must serve)."""
    vol = {m: 0 for m in J_MOVES.values()}
    for _, veh in ET.iterparse(_open_maybe_gz(routefile), events=("end",)):
        if veh.tag != "vehicle":
            continue
        r = veh.find("route")
        if r is None:
            continue
        e = r.get("edges").split()
        for a, b in zip(e, e[1:]):
            m = J_MOVES.get((a, b))
            if m:
                vol[m] += 1
        veh.clear()
    return {m: v / period_h for m, v in vol.items()}


def lanes_for_moves(net, variant):
    """movement -> {lane_index: [tls link indices]} on its approach edge."""
    out = {}
    tls = net.getTLS("J")
    for inl, outl, li in tls.getConnections():
        fe, te = inl.getEdge().getID(), outl.getEdge().getID()
        m = J_MOVES.get((fe, te))
        if m is None:
            continue
        out.setdefault(m, {}).setdefault(inl.getIndex(), []).append(li)
    return out


def group_flow_ratio(moves, vol, lanemap, sat, variant):
    """Exact critical flow ratio of one lane group, by Hall's condition over all
    movement subsets (continuous transportation feasibility)."""
    sup, lanes_of = {}, {}
    for m in moves:
        lm = lanemap.get(m, {})
        if not lm:
            continue
        # green-time supply needed, in hours, using each lane's own measured s
        s_eff = sum(sat[sat_key(m, li, variant)]["sat_flow_vph_per_lane"] for li in lm) / len(lm)
        sup[m] = vol.get(m, 0.0) / s_eff
        lanes_of[m] = set(lm)
    if not sup:
        return 0.0, None
    best, crit = 0.0, None
    for k in range(1, len(sup) + 1):
        for A in itertools.combinations(sup, k):
            u = set().union(*(lanes_of[m] for m in A))
            if not u:
                continue
            r = sum(sup[m] for m in A) / len(u)
            if r > best:
                best, crit = r, A
    return best, crit


def design(netfile, routefile, variant, period_h=1.0):
    net = sumolib.net.readNet(netfile)
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sat = json.load(open(os.path.join(here, "calib", "sat_flow.json")))
    vol = movement_volumes(routefile, period_h)
    lanemap = lanes_for_moves(net, variant)
    nlinks = max(li for _, _, li in net.getTLS("J").getConnections()) + 1

    ys, l1s, crits, links = [], [], [], []
    for ph in PHASES[variant]:
        y, crit_desc, l1 = 0.0, None, 0.0
        lk = []
        for grp in ph:
            r, crit = group_flow_ratio(grp, vol, lanemap, sat, variant)
            if r > y:
                y, crit_desc = r, (grp, crit)
                l1 = max(sat[sat_key(m, sorted(lanemap.get(m, {0: 0}))[0], variant)]
                         ["startup_lost_time_s"] for m in (crit or grp))
            for m in grp:
                for li, idxs in lanemap.get(m, {}).items():
                    lk += idxs
        ys.append(y)
        l1s.append(max(l1, 1.5))
        crits.append({"critical_movements": list(crit_desc[1]) if crit_desc and crit_desc[1] else [],
                      "y": y})
        links.append(sorted(set(lk)))

    Y = sum(ys)
    L = sum(l1s) + ALLRED * len(ys)
    if Y < 0.92:
        C = (1.5 * L + 5.0) / (1.0 - Y)
    else:
        C = CMAX
    C = max(CMIN, min(CMAX, C))
    total_int = sum(l1s) + (YELLOW + ALLRED) * len(ys)  # lost + change intervals
    avail = C - (YELLOW + ALLRED) * len(ys)
    geff_total = C - L
    greens = []
    for y, l1 in zip(ys, l1s):
        geff = geff_total * (y / Y) if Y > 0 else geff_total / len(ys)
        greens.append(max(GMIN, geff + l1 - YELLOW))
    # rescale so the cycle closes exactly
    scale = (C - (YELLOW + ALLRED) * len(ys)) / sum(greens)
    greens = [max(GMIN, g * scale) for g in greens]
    C = sum(greens) + (YELLOW + ALLRED) * len(ys)

    plan = {"variant": variant, "n_phases": len(ys), "Y": Y, "L": L, "cycle_s": C,
            "y_per_phase": ys, "l1_per_phase": l1s, "green_s": greens,
            "critical": crits, "movement_volumes_vph": vol,
            "phase_link_indices": links, "n_tls_links": nlinks,
            "yellow_s": YELLOW, "allred_s": ALLRED}
    return plan


def write_tls(plan, path, program="0"):
    n = plan["n_tls_links"]
    out = [f'  <tlLogic id="J" type="static" programID="{program}" offset="0">\n']
    for g, lk in zip(plan["green_s"], plan["phase_link_indices"]):
        G = "".join("G" if i in lk else "r" for i in range(n))
        Ys = "".join("y" if i in lk else "r" for i in range(n))
        R = "r" * n
        out.append(f'    <phase duration="{g:.1f}" state="{G}"/>\n')
        out.append(f'    <phase duration="{YELLOW:.1f}" state="{Ys}"/>\n')
        out.append(f'    <phase duration="{ALLRED:.1f}" state="{R}"/>\n')
    out.append("  </tlLogic>\n")
    with open(path, "w") as f:
        f.write("<additional>\n" + "".join(out) + "</additional>\n")
    return "".join(out)


if __name__ == "__main__":
    p = design(sys.argv[1], sys.argv[2], sys.argv[3])
    print(json.dumps({k: v for k, v in p.items() if k != "phase_link_indices"}, indent=1))
    print(write_tls(p, "/tmp/tls.add.xml"))
