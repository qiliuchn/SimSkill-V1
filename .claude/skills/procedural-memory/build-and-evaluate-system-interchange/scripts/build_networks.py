#!/usr/bin/env python3
"""
Build three freeway-to-freeway SYSTEM INTERCHANGE variants in SUMO by hand-authoring
plain-XML node/edge/connection/type files and compiling them with netconvert.

Variants
--------
clover  : full four-leg cloverleaf.  Two freeways (3 lanes/dir, 120 km/h) cross
          grade-separated; 4 outer directional right-turn ramps + 4 inner loop
          ramps (270 deg arcs, R=65 m, 45 km/h, single lane); each carriageway has
          a 4th auxiliary lane between its loop-on gore and its loop-off gore ->
          a 154 m WEAVING SEGMENT on the mainline.
cd      : same cloverleaf, but all weaving is moved off the mainline onto a
          parallel 2-lane COLLECTOR-DISTRIBUTOR roadway joined to the mainline by a
          single 2-lane diverge/merge pair.  Mainline is a clean 3 lanes with no
          ramp terminals at all between the C-D gores.
flyover : partial cloverleaf / semi-directional.  The single heaviest left turn
          (A-West -> B-North, i.e. EB->NB) is served by a 2-lane directional
          FLYOVER instead of a loop ramp; the other three loops are unchanged.

Geometry conventions
--------------------
Global origin = the crossing point.  Four one-way carriageways, indexed k=0..3,
each a 90 deg CCW rotation of the previous:
    k=0 EB (freeway A, eastbound,  centerline y=-12, z=0)
    k=1 NB (freeway B, northbound, centerline x=+12, z=10 over the crossing)
    k=2 WB (freeway A, westbound,  centerline y=+12, z=0)
    k=3 SB (freeway B, southbound, centerline x=-12, z=10 over the crossing)
A point is addressed by (k, s, d): s = station along direction of travel measured
from the crossing point, d = lateral offset (positive = left of travel).

Right turn  from k goes to carriageway (k-1)%4 via an OUTER ramp  (R=428 m arc).
Left  turn  from k goes to carriageway (k+1)%4 via a LOOP  ramp   (R=65 m, 270 deg).
Through     from k stays on carriageway k.
-> 12 movements from 4 legs.

The outer-ramp radius (428 m) is NOT free: it is chosen so the outer ramp stays
geometrically OUTSIDE the loop ramp in the same quadrant.  See verify_networks.py,
which checks the actual minimum clearance between every pair of ramp polylines.
"""
import math
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
EPISODE = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
NETDIR = os.path.join(EPISODE, "outputs", "networks")

# ----------------------------------------------------------------------------- geometry constants
MED = 12.0            # carriageway centerline offset from the axis of its own freeway
R_LOOP = 65.0         # loop ramp radius  (270 deg)
R_OUTER = 428.0       # outer directional ramp radius (90 deg)
S_OUTER = MED + R_OUTER   # = 440 -> outer ramp gore station
S_LOOP = MED + R_LOOP     # = 77  -> loop ramp gore station
TERM = 3200.0         # external terminal station (identical in all variants so
                      # that OD travel distances are comparable across designs).
                      # Long enough that a broken-down interchange stores its queue
                      # INSIDE the network instead of having the source meter it.

SP_FWY = 33.33        # 120 km/h
SP_LOOP = 12.50       # 45 km/h  (R=65 m supports ~48 km/h at e+f=0.28)
SP_OUTER = 25.00      # 90 km/h
SP_CD = 22.22         # 80 km/h collector-distributor
SP_FLY = 22.22        # 80 km/h flyover (R=712 m supports far more; posted lower)

CW = ["EB", "NB", "WB", "SB"]
Z_HIGH = 10.0         # freeway B deck height over freeway A


def zprof(a):
    """z of a freeway-B carriageway at |station| = a."""
    a = abs(a)
    if a <= 700.0:
        return Z_HIGH
    if a >= 1050.0:
        return 0.0
    return Z_HIGH * (1050.0 - a) / 350.0


GORE_W = 5.0          # lateral gore offset of a ramp from the mainline centerline
GORE_TAPER = 40.0     # length over which that offset is taken up


def rot(k, x, y):
    """rotate (x,y) by k*90 degrees CCW."""
    k %= 4
    if k == 0:
        return (x, y)
    if k == 1:
        return (-y, x)
    if k == 2:
        return (-x, -y)
    return (y, -x)


def gp(k, s, d=0.0):
    """global (x,y) of carriageway k at station s, lateral offset d (left positive)."""
    return rot(k, s, -MED + d)


def gz(k, s):
    """z of carriageway k at station s (freeway A flat at 0, freeway B elevated)."""
    return 0.0 if (k % 4) % 2 == 0 else zprof(s)


def gore_taper(pts3, w=GORE_W, ltap=GORE_TAPER):
    """Offset a ramp polyline to the RIGHT of its direction of travel by `w`, taking
    the offset up linearly over the first/last `ltap` metres.

    Without this, a ramp that leaves the mainline exactly tangentially separates from
    it so slowly that netconvert builds a 60 m-wide junction polygon, which then
    *moves the mainline edge endpoints* (the weaving edge came out 196 m instead of the
    designed 154 m) and leaves 8 m shape stubs carrying the whole z change (a spurious
    15.6% grade warning).  A 5 m / 40 m gore taper = 7 deg divergence angle at the node,
    which is both realistic gore geometry and small enough to keep junctions tight."""
    n = len(pts3)
    d = [0.0] * n
    for i in range(1, n):
        d[i] = d[i - 1] + math.dist(pts3[i - 1][:2], pts3[i][:2])
    L = d[-1]
    out = []
    for i, p in enumerate(pts3):
        f = min(1.0, d[i] / ltap, (L - d[i]) / ltap)
        if i == 0:
            dx, dy = pts3[1][0] - p[0], pts3[1][1] - p[1]
        elif i == n - 1:
            dx, dy = p[0] - pts3[i - 1][0], p[1] - pts3[i - 1][1]
        else:
            dx, dy = pts3[i + 1][0] - pts3[i - 1][0], pts3[i + 1][1] - pts3[i - 1][1]
        m = math.hypot(dx, dy) or 1.0
        out.append((p[0] + w * f * dy / m, p[1] - w * f * dx / m, p[2]))
    return out


def arcpts(cx, cy, r, th0, th1, n=24):
    """points on a circle, th in degrees; direction implied by sign of (th1-th0)."""
    out = []
    for i in range(n + 1):
        t = math.radians(th0 + (th1 - th0) * i / n)
        out.append((cx + r * math.cos(t), cy + r * math.sin(t)))
    return out


def polylen(pts):
    return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def with_z(pts, z0, z1, flat=35.0):
    """Attach a linearly-interpolated z (by arclength) to a 2-D polyline, holding z
    CONSTANT over the first/last `flat` metres.

    The flat end zones exist because netconvert trims a ramp's first/last shape
    segment back to the junction boundary but keeps the node's z; if z were changing
    over that stub, the whole end-to-end height change would be compressed into an
    8 m remnant and reported as a spurious ~14% grade."""
    L = polylen(pts)
    span = max(L - 2 * flat, 1e-6)
    out, acc = [], 0.0
    for i, p in enumerate(pts):
        if i:
            acc += math.dist(pts[i - 1], p)
        f = min(1.0, max(0.0, (acc - flat) / span))
        out.append((p[0], p[1], z0 + (z1 - z0) * f))
    return out


def with_zprofile(pts, ctrl):
    """attach z from piecewise-linear control points ctrl=[(arclen, z), ...]."""
    out, acc = [], 0.0
    for i, p in enumerate(pts):
        if i:
            acc += math.dist(pts[i - 1], p)
        z = ctrl[-1][1]
        for j in range(len(ctrl) - 1):
            a0, z0 = ctrl[j]
            a1, z1 = ctrl[j + 1]
            if a0 <= acc <= a1:
                z = z0 + (z1 - z0) * ((acc - a0) / (a1 - a0) if a1 > a0 else 0.0)
                break
        out.append((p[0], p[1], z))
    return out


def shapestr(pts):
    return " ".join("%.2f,%.2f,%.2f" % (p[0], p[1], p[2]) for p in pts)


# ----------------------------------------------------------------------------- net container
class Net:
    def __init__(self, name):
        self.name = name
        self.nodes = []
        self.edges = []
        self.conns = []
        # bookkeeping used by the detector/route builders
        self.chain = {}        # (k, 'main'|'cd') -> [(edge_id, s0, s1, nlanes), ...]
        self.roles = {}        # semantic role -> edge id

    def node(self, nid, x, y, z, ntype="priority"):
        self.nodes.append((nid, x, y, z, ntype))
        return nid

    def edge(self, eid, frm, to, nlanes, speed, etype, shape=None, priority=None):
        self.edges.append(dict(id=eid, frm=frm, to=to, n=nlanes, speed=speed,
                               type=etype, shape=shape, priority=priority))
        return eid

    def con(self, f, t, fl, tl):
        self.conns.append((f, t, fl, tl))

    def straight_chain(self, k, stations, lanes, names, prefix=None, d=0.0,
                       speed=SP_FWY, etype="fwy"):
        """create nodes + edges along carriageway k; returns (node_ids, edge_ids)."""
        pre = prefix if prefix is not None else CW[k]
        nids, eids = [], []
        for i, s in enumerate(stations):
            x, y = gp(k, s, d)
            nids.append(self.node("%s_n%d" % (pre, i), x, y, gz(k, s)))
        for i in range(len(stations) - 1):
            eid = "%s_%s" % (pre, names[i])
            self.edge(eid, nids[i], nids[i + 1], lanes[i], speed, etype)
            eids.append(eid)
        return nids, eids

    def write(self, outdir):
        os.makedirs(outdir, exist_ok=True)
        p = lambda f: os.path.join(outdir, f)

        with open(p("%s.nod.xml" % self.name), "w") as fh:
            fh.write("<nodes>\n")
            for nid, x, y, z, t in self.nodes:
                fh.write('  <node id="%s" x="%.2f" y="%.2f" z="%.2f" type="%s"/>\n'
                         % (nid, x, y, z, t))
            fh.write("</nodes>\n")

        with open(p("%s.typ.xml" % self.name), "w") as fh:
            fh.write("<types>\n")
            fh.write('  <type id="fwy"   numLanes="3" speed="%.2f" priority="13" width="3.20" disallow="pedestrian bicycle moped tram rail rail_urban rail_electric ship"/>\n' % SP_FWY)
            fh.write('  <type id="loop"  numLanes="1" speed="%.2f" priority="4"  width="4.00" disallow="pedestrian bicycle moped tram rail rail_urban rail_electric ship"/>\n' % SP_LOOP)
            fh.write('  <type id="outer" numLanes="1" speed="%.2f" priority="6"  width="3.75" disallow="pedestrian bicycle moped tram rail rail_urban rail_electric ship"/>\n' % SP_OUTER)
            fh.write('  <type id="cd"    numLanes="2" speed="%.2f" priority="8"  width="3.50" disallow="pedestrian bicycle moped tram rail rail_urban rail_electric ship"/>\n' % SP_CD)
            fh.write('  <type id="fly"   numLanes="2" speed="%.2f" priority="9"  width="3.50" disallow="pedestrian bicycle moped tram rail rail_urban rail_electric ship"/>\n' % SP_FLY)
            fh.write("</types>\n")

        with open(p("%s.edg.xml" % self.name), "w") as fh:
            fh.write("<edges>\n")
            for e in self.edges:
                a = ('  <edge id="%s" from="%s" to="%s" type="%s" numLanes="%d" speed="%.2f" spreadType="center"'
                     % (e["id"], e["frm"], e["to"], e["type"], e["n"], e["speed"]))
                if e["priority"] is not None:
                    a += ' priority="%d"' % e["priority"]
                if e["shape"]:
                    a += ' shape="%s"' % shapestr(e["shape"])
                fh.write(a + "/>\n")
            fh.write("</edges>\n")

        with open(p("%s.con.xml" % self.name), "w") as fh:
            fh.write("<connections>\n")
            for f, t, fl, tl in self.conns:
                fh.write('  <connection from="%s" to="%s" fromLane="%d" toLane="%d"/>\n'
                         % (f, t, fl, tl))
            fh.write("</connections>\n")


# ----------------------------------------------------------------------------- connection helpers
def widen(net, a, b, na, nb):
    """a (na lanes) -> b (nb lanes), nb>na, extra lanes added on the RIGHT.
    Source lane 0 feeds all the new right-hand lanes plus its own; this is exactly
    the pattern netconvert generates itself for a lane addition."""
    extra = nb - na
    for j in range(extra + 1):
        net.con(a, b, 0, j)
    for i in range(1, na):
        net.con(a, b, i, i + extra)


def narrow(net, a, b, na, nb, drop_right=True):
    """a (na lanes) -> b (nb lanes), nb<na, lanes dropped from the RIGHT (taper)."""
    drop = na - nb
    for j in range(drop + 1):
        net.con(a, b, j, 0)
    for i in range(drop + 1, na):
        net.con(a, b, i, i - drop)


def straight(net, a, b, n):
    for i in range(n):
        net.con(a, b, i, i)


# ----------------------------------------------------------------------------- ramp shapes
def loop_shape(k):
    """270 deg CW loop from carriageway k station +S_LOOP to carriageway k+1 station -S_LOOP."""
    cx, cy = rot(k, S_LOOP, -S_LOOP)
    pts = arcpts(cx, cy, R_LOOP, 90.0 + 90.0 * k, -180.0 + 90.0 * k, n=30)
    return gore_taper(with_z(pts, gz(k, S_LOOP), gz(k + 1, -S_LOOP)))


def outer_shape(k):
    """90 deg CW outer ramp from carriageway k station -S_OUTER to carriageway k-1 station +S_OUTER."""
    cx, cy = rot(k, -S_OUTER, -S_OUTER)
    pts = arcpts(cx, cy, R_OUTER, 90.0 + 90.0 * k, 0.0 + 90.0 * k, n=24)
    # the 428 m outer ramp separates from the mainline far more slowly than the
    # 65 m loop, so it needs a wider gore taper to keep its junction compact
    return gore_taper(with_z(pts, gz(k, -S_OUTER), gz(k - 1, S_OUTER)), w=9.0, ltap=45.0)


# flyover: EB station -800 -> NB station +800, 90 deg CCW arc, R = 812
S_FLY_OUT = -800.0
S_FLY_IN = 800.0
R_FLY = MED - S_FLY_OUT          # 812


def flyover_shape():
    cx, cy = (S_FLY_OUT, -MED + R_FLY)          # (-800, 800)
    pts = arcpts(cx, cy, R_FLY, -90.0, 0.0, n=36)
    L = polylen(pts)
    # z control points chosen from the two places the flyover actually crosses another
    # roadway: over WB-A (z=0) at ~198 m, over SB-B (z=10) at ~1077 m, then down onto
    # NB-B.  Verified by verify_networks.py, which recomputes both crossings.
    ctrl = [(0.0, 0.0), (35.0, 0.0), (198.0, 6.0), (1077.0, 16.0),
            (L - 35.0, zprof(S_FLY_IN)), (L, zprof(S_FLY_IN))]
    return gore_taper(with_zprofile(pts, ctrl), w=9.0, ltap=45.0)


# ----------------------------------------------------------------------------- variant: cloverleaf
CLOVER_ST = [-TERM, -640.0, -S_OUTER, -S_LOOP, S_LOOP, S_OUTER, 640.0, TERM]
CLOVER_LN = [3, 4, 3, 4, 3, 4, 3]
CLOVER_NM = ["in", "dec", "s2", "wv", "s4", "acc", "out"]


def build_clover(name="clover"):
    net = Net(name)
    nids, eids = {}, {}
    for k in range(4):
        nids[k], eids[k] = net.straight_chain(k, CLOVER_ST, CLOVER_LN, CLOVER_NM)
        net.chain[(k, "main")] = [(eids[k][i], CLOVER_ST[i], CLOVER_ST[i + 1], CLOVER_LN[i])
                                  for i in range(len(CLOVER_LN))]
    for k in range(4):
        e = eids[k]
        IN, DEC, S2, WV, S4, ACC, OUT = e
        loop_out = "loop_%s_%s" % (CW[k], CW[(k + 1) % 4])     # left turn, leaves at n4
        loop_in = "loop_%s_%s" % (CW[(k - 1) % 4], CW[k])      # left turn of k-1, arrives at n3
        out_out = "outer_%s_%s" % (CW[k], CW[(k - 1) % 4])     # right turn, leaves at n2
        out_in = "outer_%s_%s" % (CW[(k + 1) % 4], CW[k])      # right turn of k+1, arrives at n5

        widen(net, IN, DEC, 3, 4)                       # deceleration lane opens
        net.con(DEC, out_out, 0, 0)                     # outer right-turn diverge
        for i in range(3):
            net.con(DEC, S2, i + 1, i)
        for i in range(3):
            net.con(S2, WV, i, i + 1)                   # mainline into weave lanes 1..3
        net.con(loop_in, WV, 0, 0)                      # loop-on feeds the auxiliary lane
        net.con(WV, loop_out, 0, 0)                     # auxiliary lane drains to the loop-off
        for i in range(3):
            net.con(WV, S4, i + 1, i)
        for i in range(3):
            net.con(S4, ACC, i, i + 1)                  # acceleration lane opens
        net.con(out_in, ACC, 0, 0)
        narrow(net, ACC, OUT, 4, 3)

        net.roles["weave_%s" % CW[k]] = WV
        net.roles["main_up_%s" % CW[k]] = IN
        net.roles["main_dn_%s" % CW[k]] = OUT

    for k in range(4):
        net.edge("loop_%s_%s" % (CW[k], CW[(k + 1) % 4]),
                 nids[k][4], nids[(k + 1) % 4][3], 1, SP_LOOP, "loop", shape=loop_shape(k))
        net.edge("outer_%s_%s" % (CW[k], CW[(k - 1) % 4]),
                 nids[k][2], nids[(k - 1) % 4][5], 1, SP_OUTER, "outer", shape=outer_shape(k))
    return net


# ----------------------------------------------------------------------------- variant: C-D roads
CD_MAIN_ST = [-TERM, -1200.0, -800.0, 800.0, 1200.0, TERM]
CD_MAIN_LN = [3, 5, 3, 5, 3]
CD_MAIN_NM = ["in", "dec", "mid", "acc", "out"]

CD_LAT = -14.0        # C-D centerline offset (right of the mainline centerline)
CD_AXIS = MED - CD_LAT             # 26 = |offset of the C-D from its freeway's axis|
# C-D ramp terminals are tangential, exactly as on the mainline, but referenced to the
# C-D alignment (26 m off-axis) rather than the mainline alignment (12 m off-axis).
S_CD_ARC = CD_AXIS + R_LOOP        # 91 -> station where the loop arc meets the C-D
S_CD_OUTER = CD_AXIS + R_OUTER     # 454 -> outer right-turn gore station on the C-D
CD_ST = [-700.0, -S_CD_OUTER, -S_LOOP, S_LOOP, S_CD_OUTER, 700.0]
CD_LN = [2, 2, 3, 2, 3]
CD_NM = ["a1", "a2", "wv", "b1", "b2"]


def cd_loop_shape(k):
    """270 deg loop between C-D roadways.  Same 65 m radius as the cloverleaf; short
    tangent stubs at each end put the C-D gores at the same +/-77 stations as the
    cloverleaf's mainline gores, so the two designs' weaving sections are the same
    154 m long and only their LOCATION (mainline vs C-D) differs."""
    p0 = gp(k, S_LOOP, CD_LAT)
    cx, cy = rot(k, S_CD_ARC, -S_CD_ARC)
    arc = arcpts(cx, cy, R_LOOP, 90.0 + 90.0 * k, -180.0 + 90.0 * k, n=30)
    pb = gp(k + 1, -S_LOOP, CD_LAT)
    pts = [p0] + arc + [pb]
    return gore_taper(with_z(pts, gz(k, S_LOOP), gz(k + 1, -S_LOOP)))


def cd_outer_shape(k):
    """90 deg outer right-turn ramp between C-D roadways, tangential at both ends."""
    cx, cy = rot(k, -S_CD_OUTER, -S_CD_OUTER)
    pts = arcpts(cx, cy, R_OUTER, 90.0 + 90.0 * k, 0.0 + 90.0 * k, n=24)
    return gore_taper(with_z(pts, gz(k, -S_CD_OUTER), gz(k - 1, S_CD_OUTER)), w=9.0, ltap=45.0)


def build_cd(name="cd"):
    net = Net(name)
    mn, me, cn, ce = {}, {}, {}, {}
    for k in range(4):
        mn[k], me[k] = net.straight_chain(k, CD_MAIN_ST, CD_MAIN_LN, CD_MAIN_NM)
        net.chain[(k, "main")] = [(me[k][i], CD_MAIN_ST[i], CD_MAIN_ST[i + 1], CD_MAIN_LN[i])
                                  for i in range(len(CD_MAIN_LN))]
        cn[k], ce[k] = net.straight_chain(k, CD_ST, CD_LN, CD_NM,
                                          prefix="CD%s" % CW[k], d=CD_LAT,
                                          speed=SP_CD, etype="cd")
        net.chain[(k, "cd")] = [(ce[k][i], CD_ST[i], CD_ST[i + 1], CD_LN[i])
                                for i in range(len(CD_LN))]
    for k in range(4):
        IN, DEC, MID, ACC, OUT = me[k]
        A1, A2, WV, B1, B2 = ce[k]
        # transition edges mainline <-> C-D (single diverge / single merge pair)
        dv = "cddiv_%s" % CW[k]
        mg = "cdmer_%s" % CW[k]
        net.edge(dv, mn[k][2], cn[k][0], 2, SP_CD, "cd",
                 shape=[(gp(k, -800.0, 0.0) + (gz(k, -800.0),)),
                        (gp(k, -775.0, -6.0) + (gz(k, -790.0),)),
                        (gp(k, -740.0, CD_LAT) + (gz(k, -760.0),)),
                        (gp(k, -700.0, CD_LAT) + (gz(k, -700.0),))])
        net.edge(mg, cn[k][5], mn[k][3], 2, SP_CD, "cd",
                 shape=[(gp(k, 700.0, CD_LAT) + (gz(k, 700.0),)),
                        (gp(k, 740.0, CD_LAT) + (gz(k, 740.0),)),
                        (gp(k, 775.0, -6.0) + (gz(k, 775.0),)),
                        (gp(k, 800.0, 0.0) + (gz(k, 800.0),))])

        loop_out = "cdloop_%s_%s" % (CW[k], CW[(k + 1) % 4])
        loop_in = "cdloop_%s_%s" % (CW[(k - 1) % 4], CW[k])
        out_out = "cdouter_%s_%s" % (CW[k], CW[(k - 1) % 4])
        out_in = "cdouter_%s_%s" % (CW[(k + 1) % 4], CW[k])

        widen(net, IN, DEC, 3, 5)
        net.con(DEC, dv, 0, 0)                  # 2-lane exit to the C-D
        net.con(DEC, dv, 1, 1)
        for i in range(3):
            net.con(DEC, MID, i + 2, i)         # 3-lane mainline continues, ramp-free
        straight(net, dv, A1, 2)
        net.con(A1, out_out, 0, 0)              # outer right turn leaves the C-D
        straight(net, A1, A2, 2)
        for i in range(2):
            net.con(A2, WV, i, i + 1)           # C-D weaving section (3 lanes)
        net.con(loop_in, WV, 0, 0)
        net.con(WV, loop_out, 0, 0)
        for i in range(2):
            net.con(WV, B1, i + 1, i)
        for i in range(2):
            net.con(B1, B2, i, i + 1)
        net.con(out_in, B2, 0, 0)
        narrow(net, B2, mg, 3, 2)
        net.con(mg, ACC, 0, 0)
        net.con(mg, ACC, 1, 1)
        for i in range(3):
            net.con(MID, ACC, i, i + 2)
        narrow(net, ACC, OUT, 5, 3)

        net.roles["weave_%s" % CW[k]] = WV
        net.roles["main_up_%s" % CW[k]] = IN
        net.roles["main_dn_%s" % CW[k]] = OUT
        net.roles["cd_%s" % CW[k]] = A2

    for k in range(4):
        net.edge("cdloop_%s_%s" % (CW[k], CW[(k + 1) % 4]),
                 cn[k][3], cn[(k + 1) % 4][2], 1, SP_LOOP, "loop", shape=cd_loop_shape(k))
        net.edge("cdouter_%s_%s" % (CW[k], CW[(k - 1) % 4]),
                 cn[k][1], cn[(k - 1) % 4][4], 1, SP_OUTER, "outer", shape=cd_outer_shape(k))
    return net


# ----------------------------------------------------------------------------- variant: flyover
FLY_EB_ST = [-TERM, -1050.0, S_FLY_OUT, -600.0, -S_OUTER, -S_LOOP, S_LOOP, S_OUTER, 640.0, TERM]
FLY_EB_LN = [3, 5, 3, 4, 3, 4, 3, 4, 3]
FLY_EB_NM = ["in", "decF", "s1", "dec", "s2", "wv", "s4", "acc", "out"]

FLY_NB_ST = [-TERM, -640.0, -S_OUTER, -S_LOOP, S_LOOP, S_OUTER, 640.0, S_FLY_IN, 1000.0, TERM]
FLY_NB_LN = [3, 4, 3, 4, 3, 4, 3, 5, 3]
FLY_NB_NM = ["in", "dec", "s2", "wv", "s4", "acc", "out1", "accF", "out"]


def build_flyover(name="flyover"):
    net = Net(name)
    nids, eids = {}, {}
    st = {0: FLY_EB_ST, 1: FLY_NB_ST, 2: CLOVER_ST, 3: CLOVER_ST}
    ln = {0: FLY_EB_LN, 1: FLY_NB_LN, 2: CLOVER_LN, 3: CLOVER_LN}
    nm = {0: FLY_EB_NM, 1: FLY_NB_NM, 2: CLOVER_NM, 3: CLOVER_NM}
    for k in range(4):
        nids[k], eids[k] = net.straight_chain(k, st[k], ln[k], nm[k])
        net.chain[(k, "main")] = [(eids[k][i], st[k][i], st[k][i + 1], ln[k][i])
                                  for i in range(len(ln[k]))]
    E = {k: dict(zip(nm[k], eids[k])) for k in range(4)}

    # ---- EB (k=0): flyover diverge, outer diverge, loop-on merge, no loop-off
    e = E[0]
    widen(net, e["in"], e["decF"], 3, 5)
    net.con(e["decF"], "fly_EB_NB", 0, 0)
    net.con(e["decF"], "fly_EB_NB", 1, 1)
    for i in range(3):
        net.con(e["decF"], e["s1"], i + 2, i)
    widen(net, e["s1"], e["dec"], 3, 4)
    net.con(e["dec"], "outer_EB_SB", 0, 0)
    for i in range(3):
        net.con(e["dec"], e["s2"], i + 1, i)
    for i in range(3):
        net.con(e["s2"], e["wv"], i, i + 1)
    net.con("loop_SB_EB", e["wv"], 0, 0)
    narrow(net, e["wv"], e["s4"], 4, 3)          # auxiliary lane now just tapers out
    for i in range(3):
        net.con(e["s4"], e["acc"], i, i + 1)
    net.con("outer_NB_EB", e["acc"], 0, 0)
    narrow(net, e["acc"], e["out"], 4, 3)

    # ---- NB (k=1): no loop-on, loop-off kept, flyover merge downstream
    e = E[1]
    widen(net, e["in"], e["dec"], 3, 4)
    net.con(e["dec"], "outer_NB_EB", 0, 0)
    for i in range(3):
        net.con(e["dec"], e["s2"], i + 1, i)
    widen(net, e["s2"], e["wv"], 3, 4)           # deceleration lane for the loop-off
    net.con(e["wv"], "loop_NB_WB", 0, 0)
    for i in range(3):
        net.con(e["wv"], e["s4"], i + 1, i)
    for i in range(3):
        net.con(e["s4"], e["acc"], i, i + 1)
    net.con("outer_WB_NB", e["acc"], 0, 0)
    narrow(net, e["acc"], e["out1"], 4, 3)
    net.con("fly_EB_NB", e["accF"], 0, 0)
    net.con("fly_EB_NB", e["accF"], 1, 1)
    for i in range(3):
        net.con(e["out1"], e["accF"], i, i + 2)
    narrow(net, e["accF"], e["out"], 5, 3)

    # ---- WB (k=2), SB (k=3): unchanged cloverleaf carriageways
    for k in (2, 3):
        IN, DEC, S2, WV, S4, ACC, OUT = eids[k]
        loop_out = "loop_%s_%s" % (CW[k], CW[(k + 1) % 4])
        loop_in = "loop_%s_%s" % (CW[(k - 1) % 4], CW[k])
        out_out = "outer_%s_%s" % (CW[k], CW[(k - 1) % 4])
        out_in = "outer_%s_%s" % (CW[(k + 1) % 4], CW[k])
        widen(net, IN, DEC, 3, 4)
        net.con(DEC, out_out, 0, 0)
        for i in range(3):
            net.con(DEC, S2, i + 1, i)
        for i in range(3):
            net.con(S2, WV, i, i + 1)
        net.con(loop_in, WV, 0, 0)
        net.con(WV, loop_out, 0, 0)
        for i in range(3):
            net.con(WV, S4, i + 1, i)
        for i in range(3):
            net.con(S4, ACC, i, i + 1)
        net.con(out_in, ACC, 0, 0)
        narrow(net, ACC, OUT, 4, 3)

    # ---- ramp edges
    idx_loop_from = {0: None, 1: 4, 2: 4, 3: 4}     # node index of the loop-off gore
    idx_loop_to = {0: 5, 1: None, 2: 3, 3: 3}       # node index of the loop-on gore
    for k in range(4):
        kk = (k + 1) % 4
        if idx_loop_from[k] is None or idx_loop_to[kk] is None:
            continue
        net.edge("loop_%s_%s" % (CW[k], CW[kk]), nids[k][idx_loop_from[k]],
                 nids[kk][idx_loop_to[kk]], 1, SP_LOOP, "loop", shape=loop_shape(k))
    idx_outer_from = {0: 4, 1: 2, 2: 2, 3: 2}
    idx_outer_to = {0: 7, 1: 5, 2: 5, 3: 5}
    for k in range(4):
        kk = (k - 1) % 4
        net.edge("outer_%s_%s" % (CW[k], CW[kk]), nids[k][idx_outer_from[k]],
                 nids[kk][idx_outer_to[kk]], 1, SP_OUTER, "outer", shape=outer_shape(k))
    net.edge("fly_EB_NB", nids[0][2], nids[1][7], 2, SP_FLY, "fly", shape=flyover_shape())

    for k in range(4):
        net.roles["weave_%s" % CW[k]] = E[k].get("wv")
        net.roles["main_up_%s" % CW[k]] = E[k]["in"]
        net.roles["main_dn_%s" % CW[k]] = E[k]["out"]
    return net


# ----------------------------------------------------------------------------- compile
def compile_net(net, outdir):
    net.write(outdir)
    p = lambda f: os.path.join(outdir, f)
    cmd = ["netconvert",
           "-n", p("%s.nod.xml" % net.name),
           "-e", p("%s.edg.xml" % net.name),
           "-x", p("%s.con.xml" % net.name),
           "-t", p("%s.typ.xml" % net.name),
           "-o", p("%s.net.xml" % net.name),
           "--no-turnarounds", "true",
           "--geometry.max-grade", "12",
           "--offset.disable-normalization", "true",
           "--junctions.corner-detail", "8",
           "--check-lane-foes.all", "true"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    log = (r.stdout or "") + (r.stderr or "")
    with open(p("netconvert.log"), "w") as fh:
        fh.write(" ".join(cmd) + "\n\n" + log)
    return r.returncode, log


def main():
    builders = {"clover": build_clover, "cd": build_cd, "flyover": build_flyover}
    which = sys.argv[1:] or list(builders)
    ok = True
    for name in which:
        net = builders[name](name)
        outdir = os.path.join(NETDIR, name)
        rc, log = compile_net(net, outdir)
        warns = [l for l in log.splitlines() if l.startswith("Warning")]
        errs = [l for l in log.splitlines() if l.startswith("Error")]
        print("=== %-8s rc=%d  edges=%d nodes=%d conns=%d  warnings=%d errors=%d"
              % (name, rc, len(net.edges), len(net.nodes), len(net.conns), len(warns), len(errs)))
        for l in warns[:25]:
            print("    " + l)
        for l in errs[:25]:
            print("    " + l)
        ok = ok and rc == 0 and not errs
        # persist role/chain metadata for the detector + demand builders
        import json
        meta = dict(roles=net.roles,
                    chain={"%d|%s" % (k, w): v for (k, w), v in net.chain.items()})
        with open(os.path.join(outdir, "%s.meta.json" % name), "w") as fh:
            json.dump(meta, fh, indent=1)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
