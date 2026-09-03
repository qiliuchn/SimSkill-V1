#!/usr/bin/env python3
"""Time-space trajectory diagram for the test arterial pair, with green bands.

Left panel  : EB carriageway (row 2, edges EW_2_*_E)
Right panel : WB carriageway (row 3, edges EW_3_*_W)

Green bands are computed from the ACTUAL tlLogic in force (network program,
optionally overridden by the tlsCoordinator offsets additional file), by looking
up the signal link index of the arterial THROUGH movement at each junction and
marking every phase whose state is 'g'/'G' on that index.
"""
import argparse
import os
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import sumolib  # noqa: E402

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SPACING = 200.0
N = 5


def through_links(net, row, direction):
    """junction_id -> [tl link indices of the arterial through movement]."""
    out = {}
    for i in range(N):
        jid = "J%d_%d" % (i, row)
        if direction == "E":
            inc = "EW_%d_%d_E" % (row, i - 1) if i > 0 else "in_W%d" % row
            outg = "EW_%d_%d_E" % (row, i) if i < N - 1 else "out_E%d" % row
        else:
            inc = "EW_%d_%d_W" % (row, i) if i < N - 1 else "in_E%d" % row
            outg = "EW_%d_%d_W" % (row, i - 1) if i > 0 else "out_W%d" % row
        if not (net.hasEdge(inc) and net.hasEdge(outg)):
            continue
        idxs = []
        for c in net.getEdge(inc).getOutgoing().get(net.getEdge(outg), []):
            if c.getTLLinkIndex() >= 0:
                idxs.append(c.getTLLinkIndex())
        if idxs:
            out[jid] = sorted(set(idxs))
    return out


def programs(netfile, addfiles):
    """tls id -> (offset, [(dur, state), ...]); later files override earlier."""
    progs = {}
    for f in [netfile] + list(addfiles):
        if not f or not os.path.exists(f):
            continue
        root = ET.parse(f).getroot()
        for tl in root.iter("tlLogic"):
            phases = [(float(p.get("duration")), p.get("state"))
                      for p in tl.findall("phase")]
            off = float(tl.get("offset", 0))
            if not phases and tl.get("id") in progs:
                # tlsCoordinator emits offset-ONLY tlLogic entries that override
                # the offset of the network's existing program -- merge, do not
                # replace, or the phase definitions would be lost.
                progs[tl.get("id")] = (off, progs[tl.get("id")][1])
            else:
                progs[tl.get("id")] = (off, phases)
    return progs


def green_windows(offset, phases, idxs, t0, t1):
    cyc = sum(d for d, _ in phases)
    offset = offset % cyc
    spans = []
    acc = 0.0
    for d, st in phases:
        g = all(st[i] in "gG" for i in idxs if i < len(st))
        spans.append((acc, acc + d, g))
        acc += d
    # SUMO semantics (verified against TraCI): program position at time t is
    # (t - offset) mod cycle, so a green span [a,b) of the program appears in
    # absolute time at k*cyc + offset + [a,b).
    wins = []
    k0 = int((t0 - offset) // cyc) - 1
    for k in range(k0, int((t1 - offset) // cyc) + 2):
        base = k * cyc + offset
        for a, b, g in spans:
            if g and base + b > t0 and base + a < t1:
                wins.append((max(t0, base + a), min(t1, base + b)))
    return wins


def load_traj(fcd, edges_order, t0, t1, xoff):
    """vehicle -> [(t, corridor_x)] using true network x, filtered to the arterial."""
    pos = defaultdict(list)
    keep = set(edges_order)
    for _, el in ET.iterparse(fcd, events=("end",)):
        if el.tag != "timestep":
            continue
        t = float(el.get("time"))
        if t0 <= t <= t1:
            for v in el:
                lane = v.get("lane", "")
                eid = lane.rsplit("_", 1)[0]
                if eid in keep:
                    pos[v.get("id")].append((t, float(v.get("x")) - xoff))
        el.clear()
        if t > t1:
            break
    return pos


def panel(ax, fcd, net, progs, row, direction, t0, t1, title):
    edges = (["EW_%d_%d_E" % (row, i) for i in range(N - 1)] if direction == "E"
             else ["EW_%d_%d_W" % (row, i) for i in range(N - 1)])
    tl = through_links(net, row, direction)
    # netconvert normalises coordinates (the 200 m access stubs shift the whole
    # grid), so the corridor origin is read from the network, never assumed.
    x0 = net.getNode("J0_%d" % row).getCoord()[0]
    xN = net.getNode("J%d_%d" % (N - 1, row)).getCoord()[0]
    for jid, idxs in tl.items():
        if jid not in progs:
            continue
        off, ph = progs[jid]
        x = net.getNode(jid).getCoord()[0] - x0
        for a, b in green_windows(off, ph, idxs, t0, t1):
            ax.plot([a, b], [x, x], color="#2e9e4f", lw=5, solid_capstyle="butt",
                    zorder=1, alpha=0.85)
        ax.axhline(x, color="#cccccc", lw=0.5, zorder=0)
    traj = load_traj(fcd, edges, t0, t1, x0)
    n = 0
    for vid, pts in traj.items():
        if len(pts) < 5:
            continue
        pts.sort()
        ax.plot([p[0] for p in pts], [p[1] for p in pts], lw=0.5,
                color="#1f4e9c", alpha=0.45, zorder=2)
        n += 1
    ax.set_xlim(t0, t1)
    ax.set_ylim(-30, xN - x0 + 30)
    ax.set_xlabel("time [s]")
    ax.set_ylabel("distance along corridor [m]")
    ax.set_title("%s  (n=%d trajectories)" % (title, n), fontsize=10)
    return n


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--net", required=True)
    p.add_argument("--fcd", required=True)
    p.add_argument("--add", nargs="*", default=[])
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--t0", type=float, default=1800)
    p.add_argument("--t1", type=float, default=2160)
    p.add_argument("--suptitle", default="")
    p.add_argument("--row-eb", type=int, default=2)
    p.add_argument("--row-wb", type=int, default=3)
    a = p.parse_args()

    net = sumolib.net.readNet(a.net)
    progs = programs(a.net, a.add)
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2), sharey=True)
    panel(axes[0], a.fcd, net, progs, a.row_eb, "E", a.t0, a.t1,
          "EB carriageway - row %d (EW_%d_*_E)" % (a.row_eb, a.row_eb))
    panel(axes[1], a.fcd, net, progs, a.row_wb, "W", a.t0, a.t1,
          "WB carriageway - row %d (EW_%d_*_W)" % (a.row_wb, a.row_wb))
    axes[1].set_ylabel("")
    fig.suptitle(a.suptitle, fontsize=12)
    fig.text(0.5, 0.005, "green bars = through-movement green at each signal; "
             "blue lines = individual vehicle trajectories",
             ha="center", fontsize=8, color="#555555")
    fig.tight_layout(rect=(0, 0.03, 1, 0.95))
    fig.savefig(a.out, dpi=150)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
