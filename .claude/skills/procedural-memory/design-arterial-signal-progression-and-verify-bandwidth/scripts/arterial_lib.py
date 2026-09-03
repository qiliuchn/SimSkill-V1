#!/usr/bin/env python3
"""Core library for the arterial-signal-progression study.

Everything parametric about the corridor lives here:

  * build_net()      - straight signalised arterial, n intersections, uniform
                       block spacing L, a cross street at every intersection.
  * SignalPlan       - cycle C, cross-street green, left-turn green, per-signal
                       left-turn phasing mode (lead-lead / lead-lag / lag-lead)
                       and per-signal offset -> a real SUMO tlLogic add-file.
  * band()           - EXACT analytic two-way through-band from the compiled
                       net + the tlLogic actually in force (interval algebra
                       modulo the cycle, no discretisation error).
  * maxband()        - MAXBAND-style search for the offset vector maximising
                       two-way band.
  * demand           - trips -> duarouter -> routed vehicles.
  * run_sumo()       - one simulation, with teleport / loaded-inserted-arrived
                       accounting.

SUMO offset convention used throughout (verified against TraCI in
`build-diamond-interchange-with-signal-offset-spillback` and re-verified here in
verify_offsets.py): the program position at simulation time t is
    (t - offset) mod C
so a phase occupying program positions [a,b) is green in absolute time at
    k*C + offset + [a, b).
"""
import csv
import math
import os
import random
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

SUMO_HOME = os.environ.get("SUMO_HOME") or \
    "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo"
os.environ["SUMO_HOME"] = SUMO_HOME
sys.path.append(os.path.join(SUMO_HOME, "tools"))
import sumolib  # noqa: E402

BIN = os.environ.get("SUMO_BIN") or os.path.join(
    os.path.dirname(os.path.dirname(SUMO_HOME.rstrip("/"))), "bin")
NETCONVERT = os.path.join(BIN, "netconvert")
DUAROUTER = os.path.join(BIN, "duarouter")
SUMO = os.path.join(BIN, "sumo")
for _p in (NETCONVERT, DUAROUTER, SUMO):
    if not os.path.exists(_p):
        raise SystemExit("SUMO binary not found: %s" % _p)

YELLOW = 3.0
ALLRED = 1.0

# ---------------------------------------------------------------- network ---


def build_net(outdir, n_int=7, L=400.0, stub=350.0, cross_len=300.0,
              art_lanes=3, cross_lanes=2, art_speed=13.89, cross_speed=11.11):
    """Write .nod/.edg/.con XML and compile with netconvert. Returns net path."""
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

    def E(a, b, lanes, spd, prio):
        return ('<edge id="%sto%s" from="%s" to="%s" numLanes="%d" speed="%.3f" '
                'priority="%d"/>' % (a, b, a, b, lanes, spd, prio))

    edg = ['<edges>']
    seq = ["W"] + ["J%d" % i for i in range(n_int)] + ["E"]
    for a, b in zip(seq, seq[1:]):
        edg.append(E(a, b, art_lanes, art_speed, 10))
        edg.append(E(b, a, art_lanes, art_speed, 10))
    for i in range(n_int):
        edg.append(E("N%d" % i, "J%d" % i, cross_lanes, cross_speed, 3))
        edg.append(E("J%d" % i, "N%d" % i, cross_lanes, cross_speed, 3))
        edg.append(E("S%d" % i, "J%d" % i, cross_lanes, cross_speed, 3))
        edg.append(E("J%d" % i, "S%d" % i, cross_lanes, cross_speed, 3))
    edg.append('</edges>')

    # explicit lane assignment: arterial leftmost lane = exclusive left bay
    con = ['<connections>']

    def C(fr, to, fl, tl):
        con.append('<connection from="%s" to="%s" fromLane="%d" toLane="%d"/>'
                   % (fr, to, fl, tl))

    aL = art_lanes - 1          # arterial left bay (leftmost)
    for i in range(n_int):
        j = "J%d" % i
        up = "W" if i == 0 else "J%d" % (i - 1)
        dn = "E" if i == n_int - 1 else "J%d" % (i + 1)
        eb_in, wb_in = "%sto%s" % (up, j), "%sto%s" % (dn, j)
        eb_out, wb_out = "%sto%s" % (j, dn), "%sto%s" % (j, up)
        n_in, s_in = "N%dto%s" % (i, j), "S%dto%s" % (i, j)
        n_out, s_out = "%stoN%d" % (j, i), "%stoS%d" % (j, i)
        # EB approach: left->N, through, right->S
        C(eb_in, n_out, aL, cross_lanes - 1)
        for k in range(aL):
            C(eb_in, eb_out, k, k)
        C(eb_in, s_out, 0, 0)
        # WB approach: left->S, through, right->N
        C(wb_in, s_out, aL, cross_lanes - 1)
        for k in range(aL):
            C(wb_in, wb_out, k, k)
        C(wb_in, n_out, 0, 0)
        # NB approach (from S): left->W(wb_out), through->N, right->E(eb_out)
        C(s_in, wb_out, cross_lanes - 1, art_lanes - 1)
        C(s_in, n_out, 0, 0)
        if cross_lanes > 1:
            C(s_in, n_out, cross_lanes - 1, cross_lanes - 1)
        C(s_in, eb_out, 0, 0)
        # SB approach (from N): left->E, through->S, right->W
        C(n_in, eb_out, cross_lanes - 1, art_lanes - 1)
        C(n_in, s_out, 0, 0)
        if cross_lanes > 1:
            C(n_in, s_out, cross_lanes - 1, cross_lanes - 1)
        C(n_in, wb_out, 0, 0)
    con.append('</connections>')

    for name, body in (("nodes.nod.xml", nod), ("edges.edg.xml", edg),
                       ("cons.con.xml", con)):
        with open(os.path.join(outdir, name), "w") as f:
            f.write("\n".join(body))

    net = os.path.join(outdir, "art.net.xml")
    subprocess.run([NETCONVERT,
                    "-n", os.path.join(outdir, "nodes.nod.xml"),
                    "-e", os.path.join(outdir, "edges.edg.xml"),
                    "-x", os.path.join(outdir, "cons.con.xml"),
                    "-o", net, "--no-turnarounds", "true",
                    "--tls.guess", "false", "--no-warnings", "true"],
                   check=True, capture_output=True)
    return net


# ------------------------------------------------------- movement mapping ---

MOVES = ["EBT", "EBL", "EBR", "WBT", "WBL", "WBR",
         "NBT", "NBL", "NBR", "SBT", "SBL", "SBR"]


def movement_index(net, n_int):
    """tls id -> {movement: [tl link indices]} classified from net geometry."""
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
        for conns in net.getNode(j).getConnections():
            li = conns.getTLLinkIndex()
            if li < 0:
                continue
            key = (conns.getFrom().getID(), conns.getTo().getID())
            if key in m:
                idx[m[key]].append(li)
        out[j] = {k: sorted(set(v)) for k, v in idx.items()}
    return out


def n_links(net, tlsid):
    return max(c.getTLLinkIndex()
               for c in net.getNode(tlsid).getConnections()) + 1


# ------------------------------------------------------------ signal plan ---

class SignalPlan(object):
    """Fixed-time coordinated arterial plan.

    C      cycle length (s)
    gX     cross-street green (s, excludes its 4 s clearance)
    gL     arterial protected-left green per direction (s)
    modes  per-signal: 'lead-lead' | 'lead-lag' | 'lag-lead'
    offs   per-signal offset (s)

    Green-time budget is IDENTICAL across the three modes by construction:
        C = gL + gT + gX + 12          (12 s = 3 clearance intervals)
        gT = C - 12 - gL - gX          (through window width, both directions)
        gB = gT - gL - YELLOW - ALLRED (the both-through overlap in lead-lag)
    lead-lag consumes one extra clearance interval, but it sits INSIDE the
    still-green through movement, so the through window width, the arterial
    time share and the per-direction left-turn green are all unchanged; only
    the RELATIVE position of the two directions' windows moves, by
        delta = gL + YELLOW + ALLRED
    """

    def __init__(self, C=90.0, gX=22.0, gL=10.0, n_int=7, modes=None, offs=None):
        self.C, self.gX, self.gL, self.n = float(C), float(gX), float(gL), n_int
        self.gT = C - 12.0 - gL - gX
        self.gB = self.gT - gL - YELLOW - ALLRED
        if self.gT < 5 or self.gB < 3:
            raise ValueError("infeasible split C=%s gX=%s gL=%s -> gT=%.1f gB=%.1f"
                             % (C, gX, gL, self.gT, self.gB))
        self.modes = list(modes) if modes else ["lead-lead"] * n_int
        self.offs = list(offs) if offs else [0.0] * n_int
        self.delta = gL + YELLOW + ALLRED   # window shift used by lead-lag
        self._wcache = {}
        self._gcache = {}

    # ---- phase table: list of (duration, {movement: char}) -----------------
    def phases(self, i):
        gL, gT, gB, gX = self.gL, self.gT, self.gB, self.gX
        A = "G"

        def cross(ch_t, ch_l):
            return {"NBT": ch_t, "SBT": ch_t, "NBR": ch_t, "SBR": ch_t,
                    "NBL": ch_l, "SBL": ch_l}
        ph = []
        mode = self.modes[i]
        if mode == "lead-lead":
            ph.append((gL, {"EBL": A, "WBL": A}))
            ph.append((YELLOW, {"EBL": "y", "WBL": "y"}))
            ph.append((ALLRED, {}))
            ph.append((gT, {"EBT": A, "WBT": A, "EBR": A, "WBR": A}))
            ph.append((YELLOW, {"EBT": "y", "WBT": "y", "EBR": "y", "WBR": "y"}))
            ph.append((ALLRED, {}))
        else:
            # lead-lag: EB approach leads; lag-lead: WB approach leads
            f, s = ("EB", "WB") if mode == "lead-lag" else ("WB", "EB")
            ph.append((gL, {f + "L": A, f + "T": A, f + "R": A}))
            ph.append((YELLOW, {f + "L": "y", f + "T": A, f + "R": A}))
            ph.append((ALLRED, {f + "T": A, f + "R": A}))
            ph.append((gB, {"EBT": A, "WBT": A, "EBR": A, "WBR": A}))
            ph.append((YELLOW, {f + "T": "y", f + "R": "y", s + "T": A, s + "R": A}))
            ph.append((ALLRED, {s + "T": A, s + "R": A}))
            ph.append((gL, {s + "T": A, s + "R": A, s + "L": A}))
            ph.append((YELLOW, {s + "T": "y", s + "R": "y", s + "L": "y"}))
            ph.append((ALLRED, {}))
        ph.append((gX, cross(A, "g")))
        ph.append((YELLOW, cross("y", "y")))
        ph.append((ALLRED, {}))
        assert abs(sum(d for d, _ in ph) - self.C) < 1e-6, \
            (mode, sum(d for d, _ in ph), self.C)
        return ph

    def through_window(self, i, direction):
        """(start, width) of the through green in PROGRAM coordinates."""
        ck = (self.modes[i], direction)
        if ck in self._wcache:
            return self._wcache[ck]
        mv = "EBT" if direction == "EB" else "WBT"
        acc, spans = 0.0, []
        for d, st in self.phases(i):
            if st.get(mv) in ("G", "g"):
                spans.append((acc, acc + d))
            acc += d
        # merge contiguous
        spans.sort()
        merged = []
        for a, b in spans:
            if merged and abs(merged[-1][1] - a) < 1e-9:
                merged[-1] = (merged[-1][0], b)
            else:
                merged.append((a, b))
        assert len(merged) == 1, merged
        self._wcache[ck] = (merged[0][0], merged[0][1] - merged[0][0])
        return self._wcache[ck]

    def write_add(self, net, path, program="prog"):
        mi = movement_index(net, self.n)
        root = ['<additional>']
        for i in range(self.n):
            j = "J%d" % i
            nl = n_links(net, j)
            root.append('<tlLogic id="%s" type="static" programID="%s" '
                        'offset="%.3f">' % (j, program, self.offs[i] % self.C))
            for d, st in self.phases(i):
                s = ["r"] * nl
                for mv, ch in st.items():
                    for li in mi[j][mv]:
                        s[li] = ch
                root.append('  <phase duration="%.2f" state="%s"/>'
                            % (d, "".join(s)))
            root.append('</tlLogic>')
        root.append('</additional>')
        with open(path, "w") as f:
            f.write("\n".join(root))
        return path


# --------------------------------------- exact periodic interval algebra ---

def _clean(iv, C):
    iv = sorted((a, b) for a, b in iv if b - a > 1e-9)
    out = []
    for a, b in iv:
        if out and a <= out[-1][1] + 1e-9:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def shift(S, d, C):
    out = []
    for a, b in S:
        if b - a >= C - 1e-9:
            return [(0.0, C)]
        a2, b2 = (a + d) % C, (a + d) % C + (b - a)
        if b2 <= C + 1e-9:
            out.append((a2, min(b2, C)))
        else:
            out.append((a2, C))
            out.append((0.0, b2 - C))
    return _clean(out, C)


def inter(S1, S2):
    out, i, jx = [], 0, 0
    while i < len(S1) and jx < len(S2):
        a = max(S1[i][0], S2[jx][0])
        b = min(S1[i][1], S2[jx][1])
        if b - a > 1e-9:
            out.append((a, b))
        if S1[i][1] < S2[jx][1]:
            i += 1
        else:
            jx += 1
    return out


def measure(S):
    return sum(b - a for a, b in S)


def green_set(plan, i, direction):
    ck = (plan.modes[i], direction)
    g = plan._gcache.get(ck)
    if g is None:
        s, w = plan.through_window(i, direction)
        g = _clean([(s, s + w)] if s + w <= plan.C else
                   [(s, plan.C), (0.0, s + w - plan.C)], plan.C)
        plan._gcache[ck] = g
    return g


def band(plan, xs, v, direction, offs=None, _pre=None):
    """Exact through-band (s) for one direction. Returns (width, feasible set).

    xs   x-coordinate of each signal (m), ascending
    v    progression (design) speed (m/s)
    """
    C = plan.C
    offs = plan.offs if offs is None else offs
    n = len(xs)
    order = range(n) if direction == "EB" else range(n - 1, -1, -1)
    ref = xs[0] if direction == "EB" else xs[-1]
    S = [(0.0, C)]
    for i in order:
        T = abs(xs[i] - ref) / v
        S = inter(S, shift(green_set(plan, i, direction), offs[i] - T, C))
        if not S:
            return 0.0, []
    return measure(S), S


def two_way(plan, xs, v, offs=None):
    bE, sE = band(plan, xs, v, "EB", offs)
    bW, sW = band(plan, xs, v, "WB", offs)
    return bE, bW


# --------------------------------------------------------- MAXBAND search ---

def maxband(plan, xs, v, objective="sum", restarts=12, sweeps=8, seed=0,
            weights=(1.0, 1.0), coarse=1.5, fine=0.05, modes_fixed=True):
    """Search the offset vector maximising two-way band.

    objective 'sum'  -> maximise w_E*b_EB + w_W*b_WB (this is what a one-way
                        -favouring search does; it will happily sacrifice a
                        direction entirely)
              'min'  -> maximise min(b_EB, b_WB), the classic MAXBAND
                        equal-band two-way objective

    Two-stage coordinate ascent (coarse lattice, then local refinement) from
    structured + random starts. Offset of signal 0 is pinned to 0: only
    relative offsets matter.
    """
    C = plan.C
    n = len(xs)
    rng = random.Random(seed)

    def score(o):
        bE, bW = two_way(plan, xs, v, o)
        if objective == "min":
            return min(bE, bW) * 1000.0 + (bE + bW)
        return weights[0] * bE + weights[1] * bW

    def ascend(o, cands_fn, nsweep):
        cur = score(o)
        for _ in range(nsweep):
            improved = False
            for i in range(1, n):
                keep, bv = o[i], cur
                for c in cands_fn(i, o[i]):
                    o[i] = c % C
                    s = score(o)
                    if s > bv + 1e-9:
                        bv, keep, improved = s, c % C, True
                o[i], cur = keep, bv
            if not improved:
                break
        return cur

    grid = [k * coarse for k in range(int(round(C / coarse)))]

    def centred(u):
        u = u % C
        return u - C if u > C / 2 else u

    # Structured starts, including the CLOSED-FORM uniform-corridor solution.
    # With equal through windows the EB arc start at signal i is
    #   a_i^E = p0 + off_i - x_i/v      and   a_i^W = a_i^E + 2 x_i / v + const,
    # so putting a_i^E = -(2 x_i/v)/2 splits the detuning evenly between the two
    # directions and gives b = gT - (n-1)|delta|/2 with delta = (2L/v) mod C
    # centred on zero.  A pure coordinate ascent does not always find this, so
    # it is seeded explicitly (and with the +-C alias of delta).
    starts = [[0.0] * n,
              [(xs[i] - xs[0]) / v for i in range(n)],
              [-(xs[i] - xs[0]) / v for i in range(n)],
              [(xs[i] - xs[0]) / v + (C / 2 if i % 2 else 0) for i in range(n)],
              [-(xs[i] - xs[0]) / v + (C / 2 if i % 2 else 0) for i in range(n)]]
    for sgn in (1.0, -1.0):
        for alias in (0.0, C, -C):
            u1 = centred(2 * (xs[1] - xs[0]) / v) + alias
            starts.append([(xs[i] - xs[0]) / v - sgn * i * u1 / 2.0
                           for i in range(n)])
            starts.append([-(xs[i] - xs[0]) / v - sgn * i * u1 / 2.0
                           for i in range(n)])
    for _ in range(restarts):
        starts.append([rng.choice(grid) for _ in range(n)])

    best, bo = -1e18, None
    for st in starts:
        o = [0.0] + [x % C for x in st[1:]]
        cur = ascend(o, lambda i, cv: grid, sweeps)
        if cur > best:
            best, bo = cur, list(o)
    # local refinement on the winner
    o = list(bo)
    ascend(o, lambda i, cv: [cv + k * fine for k in range(-int(coarse / fine),
                                                          int(coarse / fine) + 1)],
           6)
    if score(o) >= best:
        bo = o
    bE, bW = two_way(plan, xs, v, bo)
    return bo, bE, bW


# ------------------- generic band, for ANY tlLogic (tool-produced plans) ---

def load_programs(files):
    """tls id -> (offset, [(dur,state),...]). Later files override earlier.

    tlsCoordinator emits offset-ONLY <tlLogic> entries; those must MERGE onto
    the phase list already known for that id, not replace it.
    """
    progs = {}
    for f in files:
        if not f or not os.path.exists(f):
            continue
        for tl in ET.parse(f).getroot().iter("tlLogic"):
            ph = [(float(p.get("duration")), p.get("state"))
                  for p in tl.findall("phase")]
            off = float(tl.get("offset", 0) or 0)
            tid = tl.get("id")
            if not ph and tid in progs:
                progs[tid] = (off, progs[tid][1])
            else:
                progs[tid] = (off, ph)
    return progs


def green_set_prog(prog, idxs):
    off, ph = prog
    C = sum(d for d, _ in ph)
    acc, sp = 0.0, []
    for d, st in ph:
        if idxs and all(st[k] in "gG" for k in idxs if k < len(st)):
            sp.append((acc, acc + d))
        acc += d
    # a window wrapping the cycle boundary is correctly represented as the two
    # disjoint pieces [0,a) and [b,C); shift()/inter() operate on sets, so no
    # special unwrapping is needed.
    return _clean(sp, C), C


def band_generic(net, progs, xs, v, direction, n_int):
    """Exact band for tool-produced (or any) tlLogic programs."""
    mi = movement_index(net, n_int)
    mv = "EBT" if direction == "EB" else "WBT"
    Cs = set()
    for i in range(n_int):
        Cs.add(round(sum(d for d, _ in progs["J%d" % i][1]), 3))
    if len(Cs) != 1:
        return None, sorted(Cs)          # cycles not unified -> undefined band
    C = Cs.pop()
    order = range(n_int) if direction == "EB" else range(n_int - 1, -1, -1)
    ref = xs[0] if direction == "EB" else xs[-1]
    S = [(0.0, C)]
    for i in order:
        j = "J%d" % i
        G, _ = green_set_prog(progs[j], mi[j][mv])
        if not G:
            return 0.0, C
        T = abs(xs[i] - ref) / v
        S = inter(S, shift(G, progs[j][0] - T, C))
        if not S:
            return 0.0, C
    return measure(S), C


# ----------------------------------------------------------------- demand ---

def write_demand(path, n_int, seed, end=3000.0, thru=600.0, cross=250.0,
                 art_side=60.0, cross_thru_frac=0.6, speed_dev=0.05):
    """Trips file. IDs encode cohort:  thruE.k / thruW.k / side.* / cross.*"""
    rng = random.Random(seed)
    trips = []

    def add(prefix, fr, to, rate):
        if rate <= 0:
            return
        n = int(round(rate * end / 3600.0))
        for k in range(n):
            trips.append((rng.uniform(0, end), "%s.%d" % (prefix, k), fr, to))

    jw, je = "WtoJ0", "EtoJ%d" % (n_int - 1)
    add("thruE", jw, "J%dtoE" % (n_int - 1), thru)
    add("thruW", je, "J0toW", thru)
    for i in range(n_int):
        add("sideEL.%d" % i, jw, "J%dtoN%d" % (i, i), art_side / 2.0)
        add("sideER.%d" % i, jw, "J%dtoS%d" % (i, i), art_side / 2.0)
        add("sideWL.%d" % i, je, "J%dtoS%d" % (i, i), art_side / 2.0)
        add("sideWR.%d" % i, je, "J%dtoN%d" % (i, i), art_side / 2.0)
        # cross-street traffic: through, plus LOCAL turns that ride the
        # arterial for exactly one block and leave again (so cross-street
        # turning demand does not silently become long-haul arterial demand).
        e_s, e_n = "S%dtoJ%d" % (i, i), "N%dtoJ%d" % (i, i)
        turn = cross * (1 - cross_thru_frac) / 2.0
        add("crossT.S%d" % i, e_s, "J%dtoN%d" % (i, i), cross * cross_thru_frac)
        add("crossT.N%d" % i, e_n, "J%dtoS%d" % (i, i), cross * cross_thru_frac)
        w = "W" if i == 0 else None
        e_ = "E" if i == n_int - 1 else None
        # from S: left -> WB one block; right -> EB one block
        add("crossL.S%d" % i, e_s,
            "J0toW" if i == 0 else "J%dtoN%d" % (i - 1, i - 1), turn)
        add("crossR.S%d" % i, e_s,
            "J%dtoE" % (n_int - 1) if i == n_int - 1
            else "J%dtoS%d" % (i + 1, i + 1), turn)
        # from N: left -> EB one block; right -> WB one block
        add("crossL.N%d" % i, e_n,
            "J%dtoE" % (n_int - 1) if i == n_int - 1
            else "J%dtoS%d" % (i + 1, i + 1), turn)
        add("crossR.N%d" % i, e_n,
            "J0toW" if i == 0 else "J%dtoN%d" % (i - 1, i - 1), turn)
        del w, e_
    trips.sort()
    with open(path, "w") as f:
        f.write('<routes>\n')
        # two IDENTICAL vTypes; the only difference is that corridor-through
        # vehicles carry an FCD device, so --fcd-output records exactly the
        # population the measured-band layer is about (and stays small).
        f.write('  <vType id="car" speedDev="%.3f" speedFactor="1.0"/>\n'
                % speed_dev)
        f.write('  <vType id="carT" speedDev="%.3f" speedFactor="1.0">\n'
                '    <param key="has.fcd.device" value="true"/>\n'
                '  </vType>\n' % speed_dev)
        for t, vid, fr, to in trips:
            ty = "carT" if vid.startswith("thru") else "car"
            f.write('  <trip id="%s" type="%s" depart="%.2f" from="%s" to="%s"/>\n'
                    % (vid, ty, t, fr, to))
        f.write('</routes>\n')
    return path, len(trips)


def route(net, trips, out):
    subprocess.run([DUAROUTER, "-n", net, "-r", trips, "-o", out,
                    "--ignore-errors", "true", "--no-warnings", "true",
                    "--routing-threads", "2"], check=True, capture_output=True)
    return out


# -------------------------------------------------------------- detectors ---

def arterial_edges(n_int, include_stubs=True):
    seq = (["W"] if include_stubs else []) + ["J%d" % i for i in range(n_int)] \
        + (["E"] if include_stubs else [])
    out = []
    for a, b in zip(seq, seq[1:]):
        out += ["%sto%s" % (a, b), "%sto%s" % (b, a)]
    return out


def write_edge_filter(path, edges):
    """netedit SELECTION file format -- 'edge:<ID>' per line.

    NOTE (verified gotcha, carried from
    compare-one-way-vs-two-way-street-grid-conversion): SUMO accepts a wrongly
    formatted filter file silently and drops output. verify_fcd_edges() below
    re-checks the produced FCD really contains every requested edge.
    """
    with open(path, "w") as f:
        for e in edges:
            f.write("edge:%s\n" % e)
    return path


def verify_fcd_edges(fcd, expect):
    seen = set()
    for _, el in ET.iterparse(fcd, events=("end",)):
        if el.tag == "vehicle":
            seen.add(el.get("lane", "").rsplit("_", 1)[0])
        el.clear()
    return sorted(seen), sorted(set(expect) - seen)


def write_e2(net, path, n_int, out_xml="e2.out.xml", period=60.0):
    root = ['<additional>']
    for i in range(n_int - 1):
        for a, b in (("J%d" % i, "J%d" % (i + 1)), ("J%d" % (i + 1), "J%d" % i)):
            eid = "%sto%s" % (a, b)
            e = net.getEdge(eid)
            for ln in e.getLanes():
                root.append('<laneAreaDetector id="e2_%s" lane="%s" pos="0" '
                            'endPos="%.2f" freq="%.0f" file="%s"/>'
                            % (ln.getID(), ln.getID(), ln.getLength() - 0.1,
                               period, out_xml))
    root.append('</additional>')
    with open(path, "w") as f:
        f.write("\n".join(root))
    return path


# ------------------------------------------------------------------- runs ---

TELE_RE = re.compile(r"Vehicle '([^']+)'.*teleport", re.I)


def run_sumo(net, routes, adds, outdir, seed=1, end=3000.0, begin=0.0,
             fcd=None, fcd_begin=None, extra=None, tripinfo=True, summary=True,
             ttt=300.0):
    outdir = os.path.abspath(outdir)
    os.makedirs(outdir, exist_ok=True)
    net, routes = os.path.abspath(net), os.path.abspath(routes)
    adds = [os.path.abspath(a) for a in (adds or [])]
    fcd = os.path.abspath(fcd) if fcd else None
    cmd = [SUMO, "-n", net, "-r", routes, "--begin", "%.1f" % begin,
           "--end", "%.1f" % end, "--seed", str(seed), "--no-step-log", "true",
           "--time-to-teleport", "%.1f" % ttt, "--duration-log.statistics", "true",
           "--xml-validation", "never"]
    if adds:
        cmd += ["-a", ",".join(adds)]
    tp = os.path.join(outdir, "tripinfo.xml")
    sm = os.path.join(outdir, "summary.xml")
    if tripinfo:
        cmd += ["--tripinfo-output", tp]
    if summary:
        cmd += ["--summary-output", sm]
    if fcd:
        cmd += ["--fcd-output", fcd, "--fcd-output.geo", "false"]
        if fcd_begin is not None:
            cmd += ["--begin", "%.1f" % begin]
    if extra:
        cmd += list(extra)
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=outdir)
    with open(os.path.join(outdir, "stderr.log"), "w") as f:
        f.write(p.stderr)
    with open(os.path.join(outdir, "stdout.log"), "w") as f:
        f.write(p.stdout)
    if p.returncode != 0:
        raise RuntimeError("sumo failed in %s:\n%s" % (outdir, p.stderr[-3000:]))
    return dict(tripinfo=tp if tripinfo else None,
                summary=sm if summary else None,
                stderr=p.stderr, stdout=p.stdout, dir=outdir)


def teleport_ids(stderr):
    ids = set()
    for line in stderr.splitlines():
        if "teleport" in line.lower():
            m = re.search(r"Vehicle '([^']+)'", line)
            if m:
                ids.add(m.group(1))
    return ids


def parse_summary(path):
    last = None
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "step":
            last = dict(el.attrib)
        el.clear()
    if last is None:
        return {}
    return {k: float(v) for k, v in last.items()
            if k in ("loaded", "inserted", "running", "ended", "arrived",
                     "teleports", "time")}


def parse_tripinfo(path):
    rows = []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "tripinfo":
            rows.append(dict(id=el.get("id"),
                             depart=float(el.get("depart")),
                             arrival=float(el.get("arrival")),
                             duration=float(el.get("duration")),
                             routeLength=float(el.get("routeLength")),
                             waitingTime=float(el.get("waitingTime")),
                             waitingCount=float(el.get("waitingCount")),
                             timeLoss=float(el.get("timeLoss")),
                             departDelay=float(el.get("departDelay"))))
        el.clear()
    return rows


def cohort(vid):
    if vid.startswith("thruE"):
        return "thruE"
    if vid.startswith("thruW"):
        return "thruW"
    if vid.startswith("sideEL") or vid.startswith("sideWL"):
        return "artleft"        # arterial PROTECTED LEFT turners
    if vid.startswith("side"):
        return "artright"
    if vid.startswith("crossL") or vid.startswith("crossR"):
        return "crossturn"
    return "cross"


def stats(rows, t0=600.0, t1=1e9, teleported=frozenset()):
    """Aggregate, per cohort. Only vehicles DEPARTING in [t0,t1) are counted."""
    out = {}
    groups = {}
    for r in rows:
        if not (t0 <= r["depart"] < t1):
            continue
        groups.setdefault(cohort(r["id"]), []).append(r)
        groups.setdefault("all", []).append(r)
    for k, g in groups.items():
        n = len(g)
        out[k] = dict(
            n=n,
            dur=sum(r["duration"] for r in g) / n,
            timeLoss=sum(r["timeLoss"] for r in g) / n,
            waitingTime=sum(r["waitingTime"] for r in g) / n,
            stops=sum(r["waitingCount"] for r in g) / n,
            zero_stop=sum(1 for r in g if r["waitingCount"] == 0) / float(n),
            total_timeLoss=sum(r["timeLoss"] for r in g),
            tele=sum(1 for r in g if r["id"] in teleported) / float(n))
    return out


# ------------------------------------------------------------- statistics ---

def tconf(vals, alpha=0.05):
    """mean, half-width of the (1-alpha) t confidence interval, sd, n."""
    import statistics
    n = len(vals)
    m = sum(vals) / n
    if n < 2:
        return m, float("nan"), float("nan"), n
    s = statistics.stdev(vals)
    try:
        from scipy import stats as sps
        t = sps.t.ppf(1 - alpha / 2, n - 1)
    except Exception:
        t = 2.776
    return m, t * s / math.sqrt(n), s, n


def paired(a, b, alpha=0.05):
    """Paired (CRN) difference b-a: mean diff, CI half width, p, correlation."""
    import statistics
    d = [y - x for x, y in zip(a, b)]
    m, hw, s, n = tconf(d, alpha)
    p = float("nan")
    r = float("nan")
    try:
        from scipy import stats as sps
        if n > 1 and statistics.stdev(d) > 0:
            p = float(sps.ttest_rel(b, a).pvalue)
        if n > 2 and statistics.stdev(a) > 0 and statistics.stdev(b) > 0:
            r = float(sps.pearsonr(a, b).statistic)
    except Exception:
        pass
    return dict(mean=m, hw=hw, sd=s, n=n, p=p, corr=r)


def write_csv(path, rows):
    if not rows:
        return
    keys = list(rows[0].keys())
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return path
