#!/usr/bin/env python3
"""
Build the three at-grade alternative-intersection variants on ONE shared geometry.

Geometry (identical for all three variants -- nodes, edges, lanes, speeds, shapes):

    NEnd (0,+600)
        |  minor street (2 lanes/dir, 50 km/h)
        |
  WEnd --- XW --- J --- XE --- EEnd     divided arterial (3 lanes/dir, 60 km/h)
 (-1600)  (-D)  (0)   (+D)   (+1600)    EB carriageway offset y=-5, WB y=+5
        |
    SEnd (0,-600)

XW / XE are median U-turn crossovers.  XW carries the WB->EB U-turn,
XE carries the EB->WB U-turn.  Both crossovers exist physically in ALL THREE
variants; only the CONNECTION LIST AT J differs between variants:

  conv : full movements (arterial thru/left/right, minor thru/left/right)
  rcut : minor through AND left banned  -> minor approach is dual-right-turn only
  mut  : arterial left turns banned     -> arterial left bay lane becomes a thru lane

Usage:  gen_network.py <outdir> <variant: conv|rcut|mut> <spacing_m>
"""
import os
import subprocess
import sys

ART_LANES = 3
MIN_LANES = 2
ART_SPEED = 16.67   # 60 km/h
MIN_SPEED = 13.89   # 50 km/h
OFFSET = 5.0        # median half-offset of each carriageway centreline
TAPER = 25.0
XEND = 1600.0
YEND = 600.0
ART_PRIO = 3
MIN_PRIO = 1


def art_shape(xa, xb, y):
    """Bowed shape: starts/ends on the node (y=0), offset to +-y in between."""
    if xb > xa:
        return f"{xa:.2f},0.00 {xa+TAPER:.2f},{y:.2f} {xb-TAPER:.2f},{y:.2f} {xb:.2f},0.00"
    return f"{xa:.2f},0.00 {xa-TAPER:.2f},{y:.2f} {xb+TAPER:.2f},{y:.2f} {xb:.2f},0.00"


def build(outdir, variant, D):
    os.makedirs(outdir, exist_ok=True)
    D = float(D)

    nodes = [
        ("WEnd", -XEND, 0.0, "priority"),
        ("XW", -D, 0.0, "priority"),
        ("J", 0.0, 0.0, "traffic_light"),
        ("XE", D, 0.0, "priority"),
        ("EEnd", XEND, 0.0, "priority"),
        ("NEnd", 0.0, YEND, "priority"),
        ("SEnd", 0.0, -YEND, "priority"),
    ]
    with open(f"{outdir}/net.nod.xml", "w") as f:
        f.write("<nodes>\n")
        for nid, x, y, t in nodes:
            f.write(f'  <node id="{nid}" x="{x:.2f}" y="{y:.2f}" type="{t}"/>\n')
        f.write("</nodes>\n")

    # ---- edges -------------------------------------------------------------
    # eastbound carriageway (y = -OFFSET), westbound (y = +OFFSET)
    E = []  # (id, from, to, lanes, speed, prio, shape)
    seg = [("WEnd", -XEND, "XW", -D), ("XW", -D, "J", 0.0),
           ("J", 0.0, "XE", D), ("XE", D, "EEnd", XEND)]
    ebids = ["E_W_XW", "E_XW_J", "E_J_XE", "E_XE_E"]
    for (a, xa, b, xb), eid in zip(seg, ebids):
        E.append((eid, a, b, ART_LANES, ART_SPEED, ART_PRIO, art_shape(xa, xb, -OFFSET)))
    wbids = ["W_E_XE", "W_XE_J", "W_J_XW", "W_XW_W"]
    wseg = [("EEnd", XEND, "XE", D), ("XE", D, "J", 0.0),
            ("J", 0.0, "XW", -D), ("XW", -D, "WEnd", -XEND)]
    for (a, xa, b, xb), eid in zip(wseg, wbids):
        E.append((eid, a, b, ART_LANES, ART_SPEED, ART_PRIO, art_shape(xa, xb, OFFSET)))
    # minor street: plain one-way pairs, default (right) spread
    E.append(("M_N_J", "NEnd", "J", MIN_LANES, MIN_SPEED, MIN_PRIO, None))
    E.append(("M_J_S", "J", "SEnd", MIN_LANES, MIN_SPEED, MIN_PRIO, None))
    E.append(("M_S_J", "SEnd", "J", MIN_LANES, MIN_SPEED, MIN_PRIO, None))
    E.append(("M_J_N", "J", "NEnd", MIN_LANES, MIN_SPEED, MIN_PRIO, None))

    with open(f"{outdir}/net.edg.xml", "w") as f:
        f.write("<edges>\n")
        for eid, a, b, nl, sp, pr, sh in E:
            s = f'  <edge id="{eid}" from="{a}" to="{b}" numLanes="{nl}" speed="{sp}" priority="{pr}"'
            if sh:
                s += f' shape="{sh}" spreadType="center"'
            f.write(s + "/>\n")
        f.write("</edges>\n")

    # ---- connections -------------------------------------------------------
    C = []   # (from, to, fromLane, toLane)

    def c(a, b, fl, tl):
        C.append((a, b, fl, tl))

    # --- crossover XW : WB through, EB through, and the WB->EB U-turn
    for i in range(ART_LANES):
        c("E_W_XW", "E_XW_J", i, i)
        c("W_J_XW", "W_XW_W", i, i)
    c("W_J_XW", "E_XW_J", 2, 2)          # <== median U-turn (dir should compile to "t")
    # --- crossover XE : EB->WB U-turn
    for i in range(ART_LANES):
        c("W_E_XE", "W_XE_J", i, i)
        c("E_J_XE", "E_XE_E", i, i)
    c("E_J_XE", "W_XE_J", 2, 2)          # <== median U-turn

    # --- main junction J ----------------------------------------------------
    # arterial approaches: lane0 = right+thru, lane1 = thru, lane2 = left bay
    if variant in ("conv", "rcut"):
        c("E_XW_J", "M_J_S", 0, 0)       # EB right
        c("E_XW_J", "E_J_XE", 0, 0)      # EB thru
        c("E_XW_J", "E_J_XE", 1, 1)      # EB thru
        c("E_XW_J", "M_J_N", 2, 1)       # EB left
        c("W_XE_J", "M_J_N", 0, 0)       # WB right
        c("W_XE_J", "W_J_XW", 0, 0)
        c("W_XE_J", "W_J_XW", 1, 1)
        c("W_XE_J", "M_J_S", 2, 1)       # WB left
    else:  # mut -- arterial lefts BANNED, bay lane becomes a third through lane
        c("E_XW_J", "M_J_S", 0, 0)
        c("E_XW_J", "E_J_XE", 0, 0)
        c("E_XW_J", "E_J_XE", 1, 1)
        c("E_XW_J", "E_J_XE", 2, 2)
        c("W_XE_J", "M_J_N", 0, 0)
        c("W_XE_J", "W_J_XW", 0, 0)
        c("W_XE_J", "W_J_XW", 1, 1)
        c("W_XE_J", "W_J_XW", 2, 2)

    # minor approaches: lane0 = right+thru, lane1 = left
    if variant in ("conv", "mut"):
        c("M_N_J", "W_J_XW", 0, 0)       # minor SB right (to west)
        c("M_N_J", "M_J_S", 0, 0)        # minor SB thru
        c("M_N_J", "E_J_XE", 1, 2)       # minor SB left (to east)
        c("M_S_J", "E_J_XE", 0, 0)       # minor NB right (to east)
        c("M_S_J", "M_J_N", 0, 0)        # minor NB thru
        c("M_S_J", "W_J_XW", 1, 2)       # minor NB left (to west)
    else:  # rcut -- minor thru AND left BANNED: dual right turn only
        c("M_N_J", "W_J_XW", 0, 0)
        c("M_N_J", "W_J_XW", 1, 1)
        c("M_S_J", "E_J_XE", 0, 0)
        c("M_S_J", "E_J_XE", 1, 1)

    with open(f"{outdir}/net.con.xml", "w") as f:
        f.write("<connections>\n")
        for a, b, fl, tl in C:
            f.write(f'  <connection from="{a}" to="{b}" fromLane="{fl}" toLane="{tl}"/>\n')
        f.write("</connections>\n")

    netfile = f"{outdir}/net.net.xml"
    cmd = ["netconvert",
           "-n", f"{outdir}/net.nod.xml",
           "-e", f"{outdir}/net.edg.xml",
           "-x", f"{outdir}/net.con.xml",
           "-o", netfile,
           "--no-turnarounds", "true",
           "--default.junctions.keep-clear", "true",
           "--tls.default-type", "static",
           "--no-internal-links", "false",
           "--offset.disable-normalization", "true",
           "--check-lane-foes.all", "false"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stdout + r.stderr)
        raise SystemExit(f"netconvert failed for {variant} D={D}")
    warn = [l for l in r.stderr.splitlines() if l.strip()]
    if warn:
        with open(f"{outdir}/netconvert.warnings.txt", "w") as f:
            f.write("\n".join(warn))
    return netfile


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2], sys.argv[3])
    print("built", sys.argv[1])
