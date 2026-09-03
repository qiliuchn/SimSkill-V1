#!/usr/bin/env python3
"""Multimodal (car + bicycle) signalised arterial: geometry, plans, demand, runs.

Extends `arterial_lib.py` (carried verbatim from episodic-memory/2026-08-02_19-00-00,
skill `design-arterial-signal-progression-and-verify-bandwidth`) with:

  * build_net(variant)  -- ONE corridor, TWO geometry variants that differ only in
                           lane permissions/count on the arterial:
                             'dedicated' : lane 0 = bicycle-only, lanes 1..3 = cars
                             'mixed'     : lanes 0..1 shared car+bicycle, lane 2 = left bay
  * BikePlan            -- the arterial_lib SignalPlan phase structure with the
                           bicycle-lane through movement added as its own movement
                           (it gets exactly the same green as the car through), and
                           right turns held at 'g' (minor) so a right-turning car
                           must yield to a through bicycle.
  * write_demand()      -- ONE demand set (cars + bicycles) valid on BOTH variants.
  * progression_offsets / band re-used unchanged from arterial_lib (exact interval
    algebra modulo the cycle).

SUMO offset convention (verified in the source episode and re-verified here in
verify_offsets.py): program position at time t is (t - offset) mod C.
"""
import os
import random
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arterial_lib as A  # noqa: E402

NETCONVERT = A.NETCONVERT
DUAROUTER = A.DUAROUTER
SUMO = A.SUMO
YELLOW, ALLRED = A.YELLOW, A.ALLRED

# ---------------------------------------------------------------- geometry ---

# arterial car lanes: [through, through, left-bay]  (2 through lanes per direction)
NCAR = 3


def n_bike_lanes(variant):
    return 1 if variant == "dedicated" else 0


def build_net(outdir, variant, n_int=6, L=400.0, stub=350.0, cross_len=300.0,
              cross_lanes=2, art_speed=13.89, cross_speed=11.11,
              bike_lane_width=2.0):
    """Compile one geometry variant. Returns net path.

    Physical lane indexing on every arterial edge (index 0 = rightmost):
        dedicated : 0 = bicycle-only, 1,2 = car through, 3 = car left bay
        mixed     : 0,1 = car+bicycle through, 2 = car left bay
    """
    assert variant in ("dedicated", "mixed")
    nb = n_bike_lanes(variant)
    nlanes = nb + NCAR
    os.makedirs(outdir, exist_ok=True)
    xs = [i * L for i in range(n_int)]

    nod = ['<nodes>']
    nod.append('<node id="W" x="%.2f" y="0" type="priority"/>' % (-stub))
    nod.append('<node id="E" x="%.2f" y="0" type="priority"/>' % (xs[-1] + stub))
    for i, x in enumerate(xs):
        nod.append('<node id="J%d" x="%.2f" y="0" type="traffic_light" '
                   'tlType="static"/>' % (i, x))
        nod.append('<node id="N%d" x="%.2f" y="%.2f" type="priority"/>'
                   % (i, x, cross_len))
        nod.append('<node id="S%d" x="%.2f" y="%.2f" type="priority"/>'
                   % (i, x, -cross_len))
    nod.append('</nodes>')

    def art_edge(a, b):
        s = ('<edge id="%sto%s" from="%s" to="%s" numLanes="%d" speed="%.3f" '
             'priority="10">' % (a, b, a, b, nlanes, art_speed))
        lanes = []
        if nb:
            lanes.append('  <lane index="0" allow="bicycle" width="%.2f"/>'
                         % bike_lane_width)
            for k in range(1, nlanes):
                lanes.append('  <lane index="%d" disallow="bicycle"/>' % k)
        else:
            # mixed: bicycles share the two through lanes; the left bay excludes them
            for k in range(nlanes - 1):
                lanes.append('  <lane index="%d" allow="passenger bicycle '
                             'truck bus"/>' % k)
            lanes.append('  <lane index="%d" disallow="bicycle"/>' % (nlanes - 1))
        return s + "\n" + "\n".join(lanes) + "\n</edge>"

    def cross_edge(a, b):
        # cross streets carry no bicycle demand in this study -> car-only, both variants
        s = ('<edge id="%sto%s" from="%s" to="%s" numLanes="%d" speed="%.3f" '
             'priority="3">' % (a, b, a, b, cross_lanes, cross_speed))
        lanes = ['  <lane index="%d" disallow="bicycle"/>' % k
                 for k in range(cross_lanes)]
        return s + "\n" + "\n".join(lanes) + "\n</edge>"

    edg = ['<edges>']
    seq = ["W"] + ["J%d" % i for i in range(n_int)] + ["E"]
    for a, b in zip(seq, seq[1:]):
        edg.append(art_edge(a, b))
        edg.append(art_edge(b, a))
    for i in range(n_int):
        edg.append(cross_edge("N%d" % i, "J%d" % i))
        edg.append(cross_edge("J%d" % i, "N%d" % i))
        edg.append(cross_edge("S%d" % i, "J%d" % i))
        edg.append(cross_edge("J%d" % i, "S%d" % i))
    edg.append('</edges>')

    con = ['<connections>']

    def C_(fr, to, fl, tl):
        con.append('<connection from="%s" to="%s" fromLane="%d" toLane="%d"/>'
                   % (fr, to, fl, tl))

    car0 = nb                 # rightmost CAR lane
    carL = nb + NCAR - 1      # arterial left-turn bay (leftmost)
    thru_car = list(range(nb, nb + NCAR - 1))   # car through lanes
    for i in range(n_int):
        j = "J%d" % i
        up = "W" if i == 0 else "J%d" % (i - 1)
        dn = "E" if i == n_int - 1 else "J%d" % (i + 1)
        eb_in, wb_in = "%sto%s" % (up, j), "%sto%s" % (dn, j)
        eb_out, wb_out = "%sto%s" % (j, dn), "%sto%s" % (j, up)
        n_in, s_in = "N%dto%s" % (i, j), "S%dto%s" % (i, j)
        n_out, s_out = "%stoN%d" % (j, i), "%stoS%d" % (j, i)
        for a_in, a_out, left_out, right_out in ((eb_in, eb_out, n_out, s_out),
                                                 (wb_in, wb_out, s_out, n_out)):
            if nb:
                C_(a_in, a_out, 0, 0)                      # bicycle through
            for k in thru_car:
                C_(a_in, a_out, k, k)                      # car through
            C_(a_in, left_out, carL, cross_lanes - 1)      # protected left
            C_(a_in, right_out, car0, 0)                   # right turn
        # cross-street approaches: never terminate in the bicycle lane
        C_(s_in, wb_out, cross_lanes - 1, carL)
        C_(s_in, n_out, 0, 0)
        if cross_lanes > 1:
            C_(s_in, n_out, cross_lanes - 1, cross_lanes - 1)
        C_(s_in, eb_out, 0, car0)
        C_(n_in, eb_out, cross_lanes - 1, carL)
        C_(n_in, s_out, 0, 0)
        if cross_lanes > 1:
            C_(n_in, s_out, cross_lanes - 1, cross_lanes - 1)
        C_(n_in, wb_out, 0, car0)
    con.append('</connections>')

    for name, body in (("nodes.nod.xml", nod), ("edges.edg.xml", edg),
                       ("cons.con.xml", con)):
        with open(os.path.join(outdir, name), "w") as f:
            f.write("\n".join(body))

    net = os.path.join(outdir, "art_%s.net.xml" % variant)
    p = subprocess.run([NETCONVERT,
                        "-n", os.path.join(outdir, "nodes.nod.xml"),
                        "-e", os.path.join(outdir, "edges.edg.xml"),
                        "-x", os.path.join(outdir, "cons.con.xml"),
                        "-o", net, "--no-turnarounds", "true",
                        "--tls.guess", "false", "--no-warnings", "false"],
                       capture_output=True, text=True)
    with open(os.path.join(outdir, "netconvert_%s.log" % variant), "w") as f:
        f.write(p.stdout + "\n" + p.stderr)
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-4000:])
    return net


# ------------------------------------------------------- movement mapping ---

# car movements as in arterial_lib, plus the bicycle-lane through movements
MOVES = A.MOVES + ["EBB", "WBB"]


def movement_index(net, n_int, variant):
    """tls id -> {movement: [tl link indices]}.

    A connection originating on a bicycle-only lane is classified EBB/WBB even
    though its (from-edge, to-edge) pair is the same as EBT/WBT.
    """
    nb = n_bike_lanes(variant)
    out = {}
    for i in range(n_int):
        j = "J%d" % i
        up = "W" if i == 0 else "J%d" % (i - 1)
        dn = "E" if i == n_int - 1 else "J%d" % (i + 1)
        m = {
            ("%sto%s" % (up, j), "%sto%s" % (j, dn)): "EBT",
            ("%sto%s" % (up, j), "%stoN%d" % (j, i)): "EBL",
            ("%sto%s" % (up, j), "%stoS%d" % (j, i)): "EBR",
            ("%sto%s" % (dn, j), "%sto%s" % (j, up)): "WBT",
            ("%sto%s" % (dn, j), "%stoS%d" % (j, i)): "WBL",
            ("%sto%s" % (dn, j), "%stoN%d" % (j, i)): "WBR",
            ("S%dto%s" % (i, j), "%stoN%d" % (j, i)): "NBT",
            ("S%dto%s" % (i, j), "%sto%s" % (j, up)): "NBL",
            ("S%dto%s" % (i, j), "%sto%s" % (j, dn)): "NBR",
            ("N%dto%s" % (i, j), "%stoS%d" % (j, i)): "SBT",
            ("N%dto%s" % (i, j), "%sto%s" % (j, dn)): "SBL",
            ("N%dto%s" % (i, j), "%sto%s" % (j, up)): "SBR",
        }
        idx = {k: [] for k in MOVES}
        for conn in net.getNode(j).getConnections():
            li = conn.getTLLinkIndex()
            if li < 0:
                continue
            key = (conn.getFrom().getID(), conn.getTo().getID())
            mv = m.get(key)
            if mv is None:
                continue
            if nb and mv in ("EBT", "WBT") and conn.getFromLane().getIndex() < nb:
                mv = "EBB" if mv == "EBT" else "WBB"
            idx[mv].append(li)
        out[j] = {k: sorted(set(v)) for k, v in idx.items()}
    return out


# ------------------------------------------------------------ signal plan ---

class BikePlan(A.SignalPlan):
    """arterial_lib.SignalPlan + bicycle-lane through movement + minor right turns.

    Phase structure, green-time budget and the through-window width are exactly
    the parent class's: the bicycle through movement is simply given the same
    green interval as the car through movement in the same direction (a bicycle
    lane at a signalised junction is not separately signalised here), and right
    turns are 'g' (permissive) rather than 'G' so a right-turning car has to
    yield to a through bicycle on its right.
    """

    def __init__(self, *a, **kw):
        self.variant = kw.pop("variant", "dedicated")
        A.SignalPlan.__init__(self, *a, **kw)

    def phases(self, i):
        ph = A.SignalPlan.phases(self, i)
        out = []
        for d, st in ph:
            st = dict(st)
            for dr in ("EB", "WB"):
                if st.get(dr + "T") in ("G", "g"):
                    st[dr + "B"] = st[dr + "T"]
                elif st.get(dr + "T") == "y":
                    st[dr + "B"] = "y"
                # right turns become permissive so they yield to through bikes
                if st.get(dr + "R") == "G":
                    st[dr + "R"] = "g"
            out.append((d, st))
        return out

    def bike_window(self, i, direction):
        """(start, width) of the bicycle through green in PROGRAM coordinates."""
        mv = ("EB" if direction == "EB" else "WB") + "B"
        acc, spans = 0.0, []
        for d, st in self.phases(i):
            if st.get(mv) in ("G", "g"):
                spans.append((acc, acc + d))
            acc += d
        spans.sort()
        merged = []
        for a, b in spans:
            if merged and abs(merged[-1][1] - a) < 1e-9:
                merged[-1] = (merged[-1][0], b)
            else:
                merged.append((a, b))
        assert len(merged) == 1, merged
        return merged[0][0], merged[0][1] - merged[0][0]

    def write_add(self, net, path, program="prog"):
        mi = movement_index(net, self.n, self.variant)
        root = ['<additional>']
        for i in range(self.n):
            j = "J%d" % i
            nl = A.n_links(net, j)
            root.append('<tlLogic id="%s" type="static" programID="%s" '
                        'offset="%.3f">' % (j, program, self.offs[i] % self.C))
            for d, st in self.phases(i):
                s = ["r"] * nl
                for mv, ch in st.items():
                    for li in mi[j].get(mv, []):
                        s[li] = ch
                root.append('  <phase duration="%.2f" state="%s"/>' % (d, "".join(s)))
            root.append('</tlLogic>')
        root.append('</additional>')
        with open(path, "w") as f:
            f.write("\n".join(root))
        return path


# ------------------------------------------------------------- offsets ------

def progression_offsets(xs, v, direction="EB"):
    """Simple one-way progression offsets: o_i = +/- (x_i - x_ref)/v."""
    if direction == "EB":
        return [(x - xs[0]) / v for x in xs]
    return [-(x - xs[0]) / v for x in xs]


def twoway_offsets(plan, xs, v, seed=0):
    """MAXBAND-style equal-band two-way offsets at design speed v."""
    offs, bE, bW = A.maxband(plan, xs, v, objective="min", restarts=16,
                             sweeps=10, seed=seed)
    return offs, bE, bW


def asym_offsets(plan, xs, v_eb, v_wb, seed=0):
    """Directional-asymmetric offsets: EB band designed at v_eb, WB at v_wb.

    Coordinate ascent on min(b_EB(v_eb), b_WB(v_wb)) -- i.e. each direction's
    band is evaluated at ITS OWN design speed, which is the whole point of an
    asymmetric plan (e.g. progress bicycles one way and cars the other).
    """
    C, n = plan.C, len(xs)
    rng = random.Random(seed)
    grid = [k * 1.5 for k in range(int(round(C / 1.5)))]

    def score(o):
        bE, _ = A.band(plan, xs, v_eb, "EB", o)
        bW, _ = A.band(plan, xs, v_wb, "WB", o)
        return min(bE, bW) * 1000.0 + (bE + bW)

    starts = [[0.0] * n,
              progression_offsets(xs, v_eb, "EB"),
              progression_offsets(xs, v_wb, "WB"),
              [((x - xs[0]) / v_eb - (x - xs[0]) / v_wb) / 2.0 for x in xs]]
    for _ in range(16):
        starts.append([rng.choice(grid) for _ in range(n)])
    best, bo = -1e18, None
    for st in starts:
        o = [0.0] + [x % C for x in st[1:]]
        cur = score(o)
        for _ in range(10):
            improved = False
            for i in range(1, n):
                keep, bv = o[i], cur
                for c in grid:
                    o[i] = c % C
                    s = score(o)
                    if s > bv + 1e-9:
                        bv, keep, improved = s, c % C, True
                o[i], cur = keep, bv
            if not improved:
                break
        if cur > best:
            best, bo = cur, list(o)
    # fine refinement
    o = list(bo)
    cur = score(o)
    for _ in range(6):
        improved = False
        for i in range(1, n):
            keep, bv = o[i], cur
            for k in range(-30, 31):
                o[i] = (bo[i] + k * 0.05) % C
                s = score(o)
                if s > bv + 1e-9:
                    bv, keep, improved = s, o[i], True
            o[i], cur = keep, bv
        if not improved:
            break
    if score(o) >= best:
        bo = o
    bE, _ = A.band(plan, xs, v_eb, "EB", bo)
    bW, _ = A.band(plan, xs, v_wb, "WB", bo)
    return bo, bE, bW


# ----------------------------------------------------------------- demand ---

BIKE_VTYPE = ('  <vType id="bike" vClass="bicycle" length="1.80" minGap="0.60"\n'
              '         width="0.70" accel="1.20" decel="3.00" sigma="0.5"\n'
              '         maxSpeed="12.0" desiredMaxSpeed="%(dms).2f"\n'
              '         speedFactor="normc(1,%(sdev).3f,0.65,1.35)"\n'
              '         tau="1.2" jmDriveAfterRedTime="-1"\n'
              '         latAlignment="right" guiShape="bicycle">\n'
              '    <param key="has.fcd.device" value="true"/>\n'
              '  </vType>\n')


def write_demand(path, n_int, seed, end=3600.0, thru=600.0, cross=250.0,
                 art_side=60.0, cross_thru_frac=0.6, car_speed_dev=0.10,
                 bike=250.0, bike_dms=5.0, bike_sdev=0.15):
    """ONE trips file, cars + bicycles, valid on BOTH geometry variants.

    id prefixes: thruE/thruW (car corridor-through, FCD), bikeE/bikeW (bicycle
    corridor-through, FCD), side*/cross* (car, no FCD).
    """
    rng = random.Random(seed)
    trips = []

    def add(prefix, fr, to, rate, kind):
        if rate <= 0:
            return
        n = int(round(rate * end / 3600.0))
        for k in range(n):
            trips.append((rng.uniform(0, end), "%s.%d" % (prefix, k), fr, to, kind))

    jw, je = "WtoJ0", "EtoJ%d" % (n_int - 1)
    eb_exit, wb_exit = "J%dtoE" % (n_int - 1), "J0toW"
    add("thruE", jw, eb_exit, thru, "carT")
    add("thruW", je, wb_exit, thru, "carT")
    add("bikeE", jw, eb_exit, bike, "bike")
    add("bikeW", je, wb_exit, bike, "bike")
    for i in range(n_int):
        add("sideEL.%d" % i, jw, "J%dtoN%d" % (i, i), art_side / 2.0, "car")
        add("sideER.%d" % i, jw, "J%dtoS%d" % (i, i), art_side / 2.0, "car")
        add("sideWL.%d" % i, je, "J%dtoS%d" % (i, i), art_side / 2.0, "car")
        add("sideWR.%d" % i, je, "J%dtoN%d" % (i, i), art_side / 2.0, "car")
        e_s, e_n = "S%dtoJ%d" % (i, i), "N%dtoJ%d" % (i, i)
        turn = cross * (1 - cross_thru_frac) / 2.0
        add("crossT.S%d" % i, e_s, "J%dtoN%d" % (i, i), cross * cross_thru_frac, "car")
        add("crossT.N%d" % i, e_n, "J%dtoS%d" % (i, i), cross * cross_thru_frac, "car")
        add("crossL.S%d" % i, e_s,
            wb_exit if i == 0 else "J%dtoN%d" % (i - 1, i - 1), turn, "car")
        add("crossR.S%d" % i, e_s,
            eb_exit if i == n_int - 1 else "J%dtoS%d" % (i + 1, i + 1), turn, "car")
        add("crossL.N%d" % i, e_n,
            eb_exit if i == n_int - 1 else "J%dtoS%d" % (i + 1, i + 1), turn, "car")
        add("crossR.N%d" % i, e_n,
            wb_exit if i == 0 else "J%dtoN%d" % (i - 1, i - 1), turn, "car")
    trips.sort()
    with open(path, "w") as f:
        f.write('<routes>\n')
        f.write('  <vType id="car" vClass="passenger" speedDev="%.3f" '
                'speedFactor="1.0"/>\n' % car_speed_dev)
        f.write('  <vType id="carT" vClass="passenger" speedDev="%.3f" '
                'speedFactor="1.0">\n'
                '    <param key="has.fcd.device" value="true"/>\n'
                '  </vType>\n' % car_speed_dev)
        f.write(BIKE_VTYPE % dict(dms=bike_dms, sdev=bike_sdev))
        for t, vid, fr, to, kind in trips:
            f.write('  <trip id="%s" type="%s" depart="%.2f" from="%s" to="%s"/>\n'
                    % (vid, kind, t, fr, to))
        f.write('</routes>\n')
    return path, len(trips)


def route(net, trips, out, strict=True):
    cmd = [DUAROUTER, "-n", net, "-r", trips, "-o", out,
           "--no-warnings", "true", "--routing-threads", "2"]
    if not strict:
        cmd += ["--ignore-errors", "true"]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("duarouter failed:\n" + p.stderr[-4000:])
    return out


def arterial_edges(n_int):
    return A.arterial_edges(n_int)


def run_sumo(*a, **kw):
    return A.run_sumo(*a, **kw)
