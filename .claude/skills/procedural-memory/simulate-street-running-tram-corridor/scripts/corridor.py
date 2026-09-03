"""
Street-running tram corridor builder.

3 km urban arterial, 6 signalized cross streets at 480 m spacing (within the
requested 450-500 m band), coordinated fixed-time signals, base cross-section
2 general-traffic lanes/direction. A single tram line runs the whole corridor
both directions, 5 stops (~600-750 m spacing), 5-min headway, endogenous
per-passenger dwell (reused mechanism from design-bus-stop-placement-type-
and-spacing: boardingDuration + real person walk->ride->walk plans -- SUMO
extends the stop natively, no TraCI needed for dwell itself).

Lane layout (index 0 = curb/rightmost = general lane always; index 1 = inner/
median lane, whose permission is the only thing that changes between arms):

  V0   : lane0 allow=passenger        lane1 allow=passenger        (no tram)
  C    : lane0 allow=passenger        lane1 allow=passenger,tram   (shared)
  B    : lane0 allow=passenger        lane1 allow=tram             (exclusive)
  B+P  : same physical net as B, + TSP controller on tram
  C+P  : same physical net as C, + TSP controller on tram

Physical geometry (numLanes=2 on every arterial segment) is IDENTICAL across
all 5 arms -- only lane1's `allow` attribute and the presence of a TSP
controller differ -- so junction internal-lane geometry cannot confound the
car-performance comparison (the geometry confound flagged in
model-curbside-delivery-and-lane-blocking-externality / design-bus-stop-
placement-type-and-spacing).

Frontage/back streets (one block behind the arterial on each side, y=+200 and
y=-200, linking consecutive cross-street stub nodes) exist in every arm so
that a "left turns prohibited" treatment has a genuine alternate path to
reroute onto (sub-goal 4), not just a routing failure.
"""
import os
import random
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict

SUMO_HOME = os.environ.get(
    "SUMO_HOME",
    "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo")
sys.path.append(os.path.join(SUMO_HOME, "tools"))
import sumolib  # noqa: E402

BIN = os.path.join(SUMO_HOME, "bin")
NETCONVERT = os.path.join(BIN, "netconvert")
SUMO_BIN = os.path.join(BIN, "sumo")

N_SIGNALS = 6
BLOCK_LEN = 480.0          # signal spacing (within 450-500 m band)
APPROACH_LEN = 300.0       # end segments, so total corridor = 3000 m
CROSS_LEN = 220.0          # cross-street stub half-length
SPEED_ART = 13.89          # 50 km/h
SPEED_CROSS = 11.11        # 40 km/h
SPEED_FRONT = 8.33         # 30 km/h local frontage street

CYCLE = 70.0
ART_GREEN = 34.0
YELLOW = 3.0
LEFT_GREEN = 10.0          # protected-left phase length (when used)
PROG_SPEED = 11.5          # progression design speed (m/s)


def signal_x(j):
    return (j - 1) * BLOCK_LEN


ALL_SIGNAL_X = [signal_x(j) for j in range(1, N_SIGNALS + 1)]
CORRIDOR_X0 = -APPROACH_LEN
CORRIDOR_X1 = signal_x(N_SIGNALS) + APPROACH_LEN


# ---------------------------------------------------------------------------
# 5 tram stops, ~600-750 m spacing, mid-block, clear of junction boxes.
# Corridor x actually spans [CORRIDOR_X0, CORRIDOR_X1] = [-300, 2700] (W
# terminus at -300, J1 at 0, ..., J6 at 2400, E terminus at 2700) -- these
# positions are chosen in THAT coordinate system, each >=40 m clear of the
# nearest signal.
STOP_LEN = 45.0   # >= tram consist length + margin
STOP_X = [-150.0, 560.0, 1200.0, 1800.0, 2550.0]


@dataclass
class ArmCfg:
    arm: str                 # V0 | C | B | BP | CP
    left_turn: str = "prohibited"   # prohibited | protected  (only matters for B/BP)
    q_art: float = 700.0     # veh/h/direction arterial car demand
    q_cross: float = 180.0   # veh/h/direction per cross street
    q_left: float = 60.0     # veh/h/signal/direction: arterial LEFT turn onto cross street
    q_right: float = 60.0    # veh/h/signal/direction: arterial RIGHT turn onto cross street
    pax_rate: float = 30.0   # boarding persons/h PER STOP PER DIRECTION (endogenous dwell driver)
    headway: float = 300.0   # tram headway (s) = 5 min
    tram_capacity: int = 220
    boarding_duration: float = 2.2
    min_dwell: float = 8.0
    warmup: float = 0.0
    demand_end: float = 3600.0
    sim_end: float = 5400.0
    block_mid: bool = False   # inject mid-block blockage (sub-goal 5)
    block_edge_dir: str = "EB"

    def has_tram(self):
        return self.arm != "V0"

    def tram_shared_lane1(self):
        return self.arm in ("C", "CP")

    def has_priority(self):
        return self.arm in ("BP", "CP")

    def label(self):
        return f"{self.arm}-{self.left_turn}-qa{int(self.q_art)}-pax{int(self.pax_rate)}"


# ---------------------------------------------------------------------------
def build_network(outdir):
    """Build the ARM-INDEPENDENT node/edge geometry (numLanes=2 everywhere on
    the arterial in both directions; permissions are edited in a later pass).
    Returns info dict with edge id lists etc."""
    os.makedirs(outdir, exist_ok=True)
    nlines = ['<nodes>']
    nlines.append(f'  <node id="W" x="{CORRIDOR_X0:.2f}" y="0" type="priority"/>')
    nlines.append(f'  <node id="E" x="{CORRIDOR_X1:.2f}" y="0" type="priority"/>')
    for j in range(1, N_SIGNALS + 1):
        sx = signal_x(j)
        nlines.append(f'  <node id="J{j}" x="{sx:.2f}" y="0" type="traffic_light"/>')
        nlines.append(f'  <node id="N{j}" x="{sx:.2f}" y="{CROSS_LEN:.2f}" type="priority"/>')
        nlines.append(f'  <node id="S{j}" x="{sx:.2f}" y="{-CROSS_LEN:.2f}" type="priority"/>')
    nlines.append('</nodes>')

    breaks = [("W", CORRIDOR_X0)] + [(f"J{j}", signal_x(j)) for j in range(1, N_SIGNALS + 1)] + [("E", CORRIDOR_X1)]

    elines = ['<edges>']
    eb, wb = [], []
    for i in range(len(breaks) - 1):
        (ia, xa), (ib, xb) = breaks[i], breaks[i + 1]
        eid, wid = f"AE_{ia}_{ib}", f"AW_{ib}_{ia}"
        elines.append(f'  <edge id="{eid}" from="{ia}" to="{ib}" numLanes="2" speed="{SPEED_ART}" spreadType="center" priority="5"/>')
        elines.append(f'  <edge id="{wid}" from="{ib}" to="{ia}" numLanes="2" speed="{SPEED_ART}" spreadType="center" priority="5"/>')
        eb.append((eid, xa, xb))
        wb.append((wid, xa, xb))
    # cross streets
    for j in range(1, N_SIGNALS + 1):
        elines.append(f'  <edge id="CNin{j}" from="N{j}" to="J{j}" numLanes="1" speed="{SPEED_CROSS}" priority="2"/>')
        elines.append(f'  <edge id="CNout{j}" from="J{j}" to="N{j}" numLanes="1" speed="{SPEED_CROSS}" priority="2"/>')
        elines.append(f'  <edge id="CSin{j}" from="S{j}" to="J{j}" numLanes="1" speed="{SPEED_CROSS}" priority="2"/>')
        elines.append(f'  <edge id="CSout{j}" from="J{j}" to="S{j}" numLanes="1" speed="{SPEED_CROSS}" priority="2"/>')
    # frontage / back streets one block behind, both sides, linking consecutive
    # cross-street stubs -- the alternate path for rerouted left turns.
    for j in range(1, N_SIGNALS):
        elines.append(f'  <edge id="FNe{j}" from="N{j}" to="N{j+1}" numLanes="1" speed="{SPEED_FRONT}" priority="1"/>')
        elines.append(f'  <edge id="FNw{j}" from="N{j+1}" to="N{j}" numLanes="1" speed="{SPEED_FRONT}" priority="1"/>')
        elines.append(f'  <edge id="FSe{j}" from="S{j}" to="S{j+1}" numLanes="1" speed="{SPEED_FRONT}" priority="1"/>')
        elines.append(f'  <edge id="FSw{j}" from="S{j+1}" to="S{j}" numLanes="1" speed="{SPEED_FRONT}" priority="1"/>')
    elines.append('</edges>')

    nod = os.path.join(outdir, "base.nod.xml")
    edg = os.path.join(outdir, "base.edg.xml")
    open(nod, "w").write("\n".join(nlines))
    open(edg, "w").write("\n".join(elines))

    net = os.path.join(outdir, "base.net.xml")
    cmd = [NETCONVERT, "-n", nod, "-e", edg, "-o", net,
           "--tls.default-type", "static",
           "--default.junctions.keep-clear", "true",
           "--no-internal-links", "false",
           "--junctions.corner-detail", "5",
           "--offset.disable-normalization", "true",
           "--no-turnarounds", "true"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("netconvert (base) failed:\n" + r.stderr[-4000:])

    eb_edges = [e[0] for e in eb]
    wb_edges = [e[0] for e in reversed(wb)]
    info = dict(net=net, nod=nod, edg=edg, eb=eb, wb=wb,
                eb_edges=eb_edges, wb_edges=wb_edges,
                cross={j: dict(Nin=f"CNin{j}", Nout=f"CNout{j}", Sin=f"CSin{j}", Sout=f"CSout{j}")
                       for j in range(1, N_SIGNALS + 1)},
                stderr=r.stderr)
    return info


def x_to_edgepos_eb(info, x):
    for eid, xa, xb in info["eb"]:
        if xa - 1e-6 <= x <= xb + 1e-6:
            return eid, x - xa
    eid, xa, xb = info["eb"][-1]
    return eid, min(x - xa, xb - xa)


def x_to_edgepos_wb(info, x):
    # WB edge f"AW_{ib}_{ia}" runs from xb to xa (i.e., decreasing x); pos
    # along it = xb - x
    for eid, xa, xb in info["wb"]:
        if xa - 1e-6 <= x <= xb + 1e-6:
            return eid, xb - x
    eid, xa, xb = info["wb"][0]
    return eid, xb - max(x, xa)


# ---------------------------------------------------------------------------
# arm variant: edit lane1 permission on every AE_/AW_ edge, recompile
# ---------------------------------------------------------------------------
def lane1_allow_for(arm):
    if arm == "V0":
        return "passenger"
    if arm in ("C", "CP"):
        return "passenger tram"
    if arm in ("B", "BP"):
        return "tram"
    raise ValueError(arm)


def build_variant(info, cfg: ArmCfg, outdir):
    import re
    edg = open(info["edg"]).read()
    lane1_allow = lane1_allow_for(cfg.arm)

    def rewrite(m):
        tag = m.group(0)
        eid = re.search(r'id="([^"]+)"', tag).group(1)
        if eid.startswith("AE_") or eid.startswith("AW_"):
            attrs = tag.rstrip()
            assert attrs.endswith("/>")
            attrs = attrs[:-2].rstrip() + ">"
            return (attrs +
                    '\n    <lane index="0" allow="passenger pedestrian"/>'
                    f'\n    <lane index="1" allow="{lane1_allow}"/>\n  </edge>')
        return tag

    new_edg = re.sub(r"<edge [^>]*/>", rewrite, edg)
    edg_path = os.path.join(outdir, f"{cfg.arm}.edg.xml")
    open(edg_path, "w").write(new_edg)

    net_path = os.path.join(outdir, f"{cfg.arm}.net.xml")
    cmd = [NETCONVERT, "-n", info["nod"], "-e", edg_path, "-o", net_path,
           "--tls.default-type", "static",
           "--default.junctions.keep-clear", "true",
           "--no-internal-links", "false",
           "--junctions.corner-detail", "5",
           "--offset.disable-normalization", "true",
           "--no-turnarounds", "true"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"netconvert ({cfg.arm}) failed:\n" + r.stderr[-4000:])
    return net_path


# ---------------------------------------------------------------------------
# connection introspection -> per-signal "kind" classification
# ---------------------------------------------------------------------------
def classify_connections(net_path, arm):
    """Return {tls_id: {linkIndex: kind}} and {tls_id: nlinks} from the
    COMPILED net -- ground truth, not authoring intent.

    Note: the compiled net's top-level <connection> elements carry NO
    `allow` attribute of their own by default (verified directly) -- lane
    permission lives on the internal via-lane (":Jn_x_y") and on the
    approach lane itself. Since this builder always puts the general
    (passenger-legal) lane at index 0 and the arm-dependent lane at index 1
    (see build_variant), fromLane index is the robust, ground-truth
    discriminator for a TRAM-EXCLUSIVE lane1 (arms B/BP): fromLane==1 is a
    tram movement there. In arms C/CP, lane1 is SHARED (passenger legal
    too, verified: cars genuinely route and queue on it) -- tagging it "T"
    there mislabeled a real, usable car movement as spurious-and-permanently
    -red, which produced actual gridlock/teleports (found and fixed during
    build verification). So the T/A split only applies where lane1 is truly
    tram-exclusive; in every other arm all arterial connections (either
    lane) are ordinary car movements. kind in:
      As/Ar/Al  arterial car through/right/left
      Ts/Tr/Tl  tram through/right/left (only possible in arm B/BP, where
                lane1 truly excludes passenger)
      Cs/Cr/Cl  cross-street car through/right/left
    """
    tram_exclusive_lane1 = arm in ("B", "BP")
    root = ET.parse(net_path).getroot()
    out, nlinks = {}, {}
    for c in root.findall("connection"):
        tl = c.get("tl")
        if not tl:
            continue
        idx = int(c.get("linkIndex"))
        frm = c.get("from")
        from_lane = c.get("fromLane")
        d = c.get("dir", "s")
        if d not in ("s", "r", "l"):
            d = "s"
        if frm.startswith(("AE_", "AW_")):
            base = "T" if (from_lane == "1" and tram_exclusive_lane1) else "A"
        elif frm.startswith(("CNin", "CSin")):
            base = "C"
        else:
            base = "?"
        out.setdefault(tl, {})[idx] = base + d
        nlinks[tl] = max(nlinks.get(tl, 0), idx + 1)
    return out, nlinks


def prohibit_arterial_left(net_path, out_path):
    """Post-edit the COMPILED net: for every dir='l' connection FROM lane
    index 0 (the general car lane, per build_variant's fixed layout) on an
    arterial (AE_/AW_) approach, ADD an explicit disallow='passenger' onto
    that specific <connection> element.

    This is the answer to sub-goal 2's "lane permission vs connection
    permission" question, empirically: the compiled net's top-level
    <connection> elements carry NO allow/disallow by default (permission is
    inherited from the approach/via lanes) -- so prohibiting ONE turn
    movement while leaving the lane's OTHER movements (through, right)
    legal cannot be done by editing the mid-block LANE permission (that
    would block ALL car movements from the lane, not just left) and
    requires a CONNECTION-level override instead. Both mechanisms are real
    and distinct: the reservation itself is a lane permission; prohibiting
    one turn through it is a connection permission.

    Verified downstream via duarouter WITHOUT --ignore-errors: routing a
    left-turn-desiring car against the edited net fails loudly for the
    direct movement and succeeds only via the frontage-street detour.
    """
    txt = open(net_path).read()
    import re

    def sub_line(m):
        line = m.group(0)
        if (('from="AE_' in line or 'from="AW_' in line)
                and 'dir="l"' in line and 'fromLane="0"' in line
                and "disallow=" not in line):
            return line[:-2] + ' disallow="passenger"/>'
        return line

    new_txt = re.sub(r"<connection[^>]*/>", sub_line, txt)
    n_changed = new_txt.count('disallow="passenger"')
    open(out_path, "w").write(new_txt)
    return n_changed


# ---------------------------------------------------------------------------
# TLS: coordinated fixed-time program, baked into the net (2nd netconvert pass)
# ---------------------------------------------------------------------------
def build_tls_additional(cfg: ArmCfg, net_path, outdir):
    kinds, nlinks = classify_connections(net_path, cfg.arm)
    protected = cfg.arm in ("B", "BP") and cfg.left_turn == "protected"

    lines = ['<additional>']
    plan = {}
    for j in range(1, N_SIGNALS + 1):
        tid = f"J{j}"
        n = nlinks[tid]
        kind = {i: kinds[tid].get(i, "?") for i in range(n)}

        def state(active, permissive=()):
            # 'permissive' kinds get lowercase 'g' (yield) instead of 'G'
            # (protected). Needed for cross-street left turns: verified
            # directly that giving BOTH the cross-left (Cl, e.g. CNin->AE_*)
            # and the opposing cross-right (Cr, e.g. CSin->AE_* landing on
            # the SAME single-lane arterial output) a protected 'G'
            # triggered SUMO's "unsafe green phase... targeted by 2 G-links"
            # check -- the two movements merge (don't truly cross) but SUMO
            # still requires at most one protected 'G' per destination lane.
            # Demoting the left to 'g' (yields to the through/right stream)
            # is SUMO's own suggested fix and matches standard permissive-
            # left signal design.
            s = ""
            for i in range(n):
                k = kind[i]
                if k not in active:
                    s += "r"
                elif k in permissive:
                    s += "g"
                else:
                    s += "G"
            return s

        def state_yellow(active):
            s = ""
            for i in range(n):
                k = kind[i]
                s += "y" if k in active else "r"
            return s

        # NOTE: "Tr"/"Tl" are spurious tram right/left connections netconvert
        # auto-generates from the tram-permission lane purely because it is
        # geometrically able to (no tram route ever uses them -- the tram's
        # route only contains through movements). They are deliberately
        # EXCLUDED from every green set: giving them 'G' produced a real,
        # verified SUMO warning ("unsafe green phase... targeted by 2
        # G-links") because they land on the same 1-lane cross-street output
        # as the ordinary car right-turn from lane0 -- confirmed harmless
        # for actual traffic (never used) but left them 'r' throughout for a
        # clean, warning-free signal program.
        # Only arms B/BP give arterial left turns special (prohibited /
        # protected-phase) treatment -- that IS sub-goal 4's subject. In
        # every other arm (V0/C/CP, and B/BP with no reservation conflict to
        # speak of would not apply here since this function only special-
        # cases B/BP), "Al" is an ordinary PERMISSIVE left turn concurrent
        # with the arterial through phase, exactly like "Cl" is for the
        # cross street.
        # Right turns are ALWAYS permissive ('g'): with 2 lanes per approach
        # and only a single-lane cross-street/arterial output, a right turn
        # can be legally sourced from EITHER lane in arms where both permit
        # passenger (C/CP; and V0), which puts 2 independent 'G' links onto
        # the same 1-lane output -- verified to trip SUMO's "unsafe green
        # phase... targeted by 2 G-links" check. Making right (and,
        # symmetrically, permissive left) turns 'g' rather than 'G' is both
        # SUMO's own suggested fix and standard permissive-turn signal
        # design; only the THROUGH movement (and a left turn inside its own
        # dedicated protected phase) stays fully protected 'G'.
        separate_left_control = cfg.arm in ("B", "BP")
        art_active = {"As", "Ar", "Ts", "Tr"} | (set() if separate_left_control else {"Al"})
        art_permissive = {"Ar", "Tr"} | (set() if separate_left_control else {"Al"})
        cross_active = {"Cs", "Cr", "Cl"}
        cross_permissive = {"Cr", "Cl"}
        left_active = {"Al"}

        phases = []
        phases.append((ART_GREEN, state(art_active, permissive=art_permissive)))
        yellow_set = art_active
        phases.append((YELLOW, state_yellow(yellow_set)))
        if protected:
            phases.append((LEFT_GREEN, state(left_active)))
            phases.append((YELLOW, state_yellow(left_active)))
        cross_green = 26.0
        phases.append((cross_green, state(cross_active, permissive=cross_permissive)))
        phases.append((YELLOW, state_yellow(cross_active)))

        cyc = sum(d for d, _ in phases)
        off = ((j - 1) * BLOCK_LEN / PROG_SPEED) % cyc
        lines.append(f'  <tlLogic id="{tid}" type="static" programID="0" offset="{off:.2f}">')
        for d, s in phases:
            lines.append(f'    <phase duration="{d:.1f}" state="{s}"/>')
        lines.append('  </tlLogic>')
        plan[tid] = dict(cycle=cyc, offset=off, nlinks=n, kind=kind,
                          phases=[(d, s) for d, s in phases], protected=protected)
    lines.append('</additional>')
    p = os.path.join(outdir, f"{cfg.arm}_{cfg.left_turn}_tls.add.xml")
    open(p, "w").write("\n".join(lines))
    return p, plan


def bake_tls(net_path, tls_add_path, outdir, tag):
    out = os.path.join(outdir, f"{tag}_final.net.xml")
    r = subprocess.run([NETCONVERT, "-s", net_path, "-i", tls_add_path, "-o", out],
                        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("netconvert(tls bake) failed:\n" + r.stderr[-4000:])
    return out


# ---------------------------------------------------------------------------
# tram stops (busStop works unmodified for a non-rail vClass too -- it's a
# generic PT stop element; only the LANE's own permission determines who may
# stand on it and dwell there)
# ---------------------------------------------------------------------------
TRAM_CONSIST_LEN = 40.0   # m, within the requested 35-45 m band


def build_stops(info, net_path, outdir):
    net = sumolib.net.readNet(net_path)
    lines = ['<additional>']
    stops = []
    for i, xs in enumerate(STOP_X):
        for direction, mapper in (("EB", x_to_edgepos_eb), ("WB", x_to_edgepos_wb)):
            eid, pos = mapper(info, xs)
            edge = net.getEdge(eid)
            L = edge.getLength()
            sp = max(1.0, min(pos, L - STOP_LEN - 1.0))
            ep = sp + STOP_LEN
            lane1 = f"{eid}_1"
            lane0 = f"{eid}_0"
            sid = f"TS_{direction}_{i}"
            lines.append(f'  <busStop id="{sid}" lane="{lane1}" startPos="{sp:.2f}" endPos="{ep:.2f}" '
                         f'lines="TRAM" friendlyPos="false">')
            lines.append(f'    <access lane="{lane0}" pos="{(sp+ep)/2:.2f}" length="3.00"/>')
            lines.append('  </busStop>')
            stops.append(dict(id=sid, direction=direction, idx=i, x=xs, edge=eid,
                              startPos=sp, endPos=ep))
    lines.append('</additional>')
    p = os.path.join(outdir, "stops.add.xml")
    open(p, "w").write("\n".join(lines))
    return p, stops


# ---------------------------------------------------------------------------
# vTypes
# ---------------------------------------------------------------------------
VTYPES = """\
  <vType id="car" vClass="passenger" length="4.5" minGap="2.5" accel="2.6" decel="4.5"
         sigma="0.5" speedDev="0.10" tau="1.0" carFollowModel="Krauss" maxSpeed="16.7"/>
  <vType id="tram" vClass="tram" length="{tlen}" minGap="1.5" accel="0.9" decel="2.8"
         emergencyDecel="4.5" sigma="0.5" speedDev="0.0" tau="1.3" maxSpeed="16.7"
         personCapacity="{cap}" boardingDuration="{bd}" width="2.65" guiShape="rail/railcar"
         color="0.85,0.1,0.1">
    <param key="has.fcd.device" value="true"/>
  </vType>
  <vType id="blocker" vClass="passenger" length="6.5" minGap="2.5" accel="1.2"
         decel="3.5" sigma="0.5" speedDev="0.0" tau="1.2" maxSpeed="16.7" color="1,0.5,0"/>
"""


def vtypes_xml(cfg: ArmCfg):
    return VTYPES.format(tlen=TRAM_CONSIST_LEN, cap=cfg.tram_capacity, bd=cfg.boarding_duration)


# ---------------------------------------------------------------------------
# demand: cars (through + cross + turning), trams (scheduled), persons
# ---------------------------------------------------------------------------
def build_cars(cfg: ArmCfg, info, outdir, seed):
    rng = random.Random(10000 + seed)
    lines = ['<routes>', vtypes_xml(cfg)]
    vid = [0]

    def stream(rate, frm, to, tag, depart_lane="best"):
        if rate <= 0:
            return
        mean = 3600.0 / rate
        t = 0.0
        while True:
            t += rng.expovariate(1.0 / mean)
            if t >= cfg.demand_end:
                break
            lines.append(f'  <trip id="{tag}{vid[0]}" type="car" depart="{t:.2f}" '
                         f'from="{frm}" to="{to}" departLane="{depart_lane}" departSpeed="max"/>')
            vid[0] += 1

    eb0, eb1 = info["eb_edges"][0], info["eb_edges"][-1]
    wb0, wb1 = info["wb_edges"][0], info["wb_edges"][-1]
    stream(cfg.q_art, eb0, eb1, "eb")
    stream(cfg.q_art, wb0, wb1, "wb")

    for j in range(1, N_SIGNALS + 1):
        cx = info["cross"][j]
        stream(cfg.q_cross, cx["Nin"], cx["Sout"], f"cn{j}_")
        stream(cfg.q_cross, cx["Sin"], cx["Nout"], f"cs{j}_")
        # arterial turning demand: origin = the arterial edge feeding INTO Jj,
        # so a genuine EB/WB through-approach confronts the actual signal
        # (and, in arm B/BP, the actual left-turn treatment).
        eb_in = info["eb_edges"][j - 1]     # edge ending at Jj, EB direction
        wb_in = info["wb_edges"][N_SIGNALS - j]  # edge ending at Jj, WB direction
        # EB LEFT -> north cross street (the movement sub-goal 4 studies)
        stream(cfg.q_left, eb_in, cx["Nout"], f"ebL{j}_")
        # WB LEFT -> south cross street (mirror movement)
        stream(cfg.q_left, wb_in, cx["Sout"], f"wbL{j}_")
        # right turns (unaffected by the reservation, kept modest & constant)
        stream(cfg.q_right, eb_in, cx["Sout"], f"ebR{j}_")
        stream(cfg.q_right, wb_in, cx["Nout"], f"wbR{j}_")

    p = os.path.join(outdir, "cars.rou.xml")
    body = [l for l in lines[2:]]
    body.sort(key=lambda l: float(l.split('depart="')[1].split('"')[0]))
    open(p, "w").write("\n".join(lines[:2] + body + ['</routes>']))
    return p


def build_trams(cfg: ArmCfg, info, stops, outdir):
    lines = ['<routes>']
    lines.append(f'  <route id="rTRAM_EB" edges="{" ".join(info["eb_edges"])}"/>')
    lines.append(f'  <route id="rTRAM_WB" edges="{" ".join(info["wb_edges"])}"/>')
    eb_stops = sorted([s for s in stops if s["direction"] == "EB"], key=lambda s: s["x"])
    wb_stops = sorted([s for s in stops if s["direction"] == "WB"], key=lambda s: -s["x"])
    n = 0
    for direction, route, sset in (("EB", "rTRAM_EB", eb_stops), ("WB", "rTRAM_WB", wb_stops)):
        t = 5.0 if direction == "EB" else 5.0 + cfg.headway / 2.0  # offset the two directions
        k = 0
        while t < cfg.demand_end:
            vid = f"tram_{direction}_{k}"
            lines.append(f'  <vehicle id="{vid}" type="tram" route="{route}" line="TRAM" '
                         f'depart="{t:.2f}" departLane="1" departPos="0" departSpeed="max">')
            for s in sset:
                lines.append(f'    <stop busStop="{s["id"]}" duration="{cfg.min_dwell:.1f}" parking="false"/>')
            lines.append('  </vehicle>')
            t += cfg.headway
            k += 1
            n += 1
    lines.append('</routes>')
    p = os.path.join(outdir, "trams.rou.xml")
    open(p, "w").write("\n".join(lines))
    return p, n


def build_persons(cfg: ArmCfg, info, stops, outdir, seed):
    """Endogenous-dwell driver: persons board at each stop at rate
    cfg.pax_rate (persons/h/stop/direction) and alight at a uniformly-random
    LATER stop in the same direction. walk->ride->walk, reusing the
    design-bus-stop-placement-type-and-spacing dwell mechanism directly
    (boardingDuration x real ride demand -> SUMO extends the stop's duration
    natively, no TraCI needed)."""
    rng = random.Random(20000 + seed)
    lines = ['<routes>']
    n = 0
    pax_end = cfg.demand_end - 300.0
    for direction in ("EB", "WB"):
        sset = sorted([s for s in stops if s["direction"] == direction],
                      key=lambda s: s["x"] if direction == "EB" else -s["x"])
        for bi, sb in enumerate(sset[:-1]):
            mean = 3600.0 / cfg.pax_rate if cfg.pax_rate > 0 else 1e12
            t = 0.0
            while True:
                t += rng.expovariate(1.0 / mean)
                if t >= pax_end:
                    break
                ai = rng.randint(bi + 1, len(sset) - 1)
                sa = sset[ai]
                pid = f"p_{direction}_{bi}_{n}"
                edge = sb["edge"]
                pos = max(2.0, (sb["startPos"] + sb["endPos"]) / 2.0)
                lines.append(f'  <person id="{pid}" depart="{t:.2f}" departPos="{pos:.2f}">')
                lines.append(f'    <walk from="{edge}" busStop="{sb["id"]}"/>')
                lines.append(f'    <ride busStop="{sa["id"]}" lines="TRAM"/>')
                lines.append(f'    <walk to="{sa["edge"]}"/>')
                lines.append('  </person>')
                n += 1
    lines.append('</routes>')
    # CRITICAL: SUMO silently DROPS (not merely reorders) person entries that
    # appear out of departure-time order in the route file ("ignoring 'pX'"
    # warning is not cosmetic -- verified directly: an unsorted file here
    # dropped 14/21 persons). Sort the <person> blocks by depart= before
    # writing, exactly as build_cars already does for <trip>.
    header = [lines[0]]
    blocks, cur = [], []
    for l in lines[1:-1]:
        cur.append(l)
        if l.strip() == "</person>":
            blocks.append(cur)
            cur = []
    blocks.sort(key=lambda b: float(b[0].split('depart="')[1].split('"')[0]))
    out_lines = header + [l for b in blocks for l in b] + [lines[-1]]
    p = os.path.join(outdir, "persons.rou.xml")
    open(p, "w").write("\n".join(out_lines))
    return p, n


# ---------------------------------------------------------------------------
# mid-block blockage (sub-goal 5), reusing model-curbside-delivery-and-
# lane-blocking-externality's parking="false" mechanic
# ---------------------------------------------------------------------------
def build_blockage(cfg: ArmCfg, info, outdir, block_start=1650.0, block_dur=240.0, block_x=None):
    """A stopped (non-evasive) vehicle mid-block in the TRAM's own lane
    (lane1). In arm B/BP this ALSO blocks general car traffic (lane1 there
    is tram-exclusive, but the blocker vehicle itself must be able to use
    it -- we give the blocker vClass='tram' too, i.e. treat it as a
    double-parked/failed TRAM car for lane1 legality, matching 'a stopped
    vehicle in the tram's own running way'; for arm C, lane1 is shared so an
    ordinary passenger-class breakdown vehicle is used instead, which is the
    more realistic reading of "a stopped/double-parked vehicle" mid-block in
    mixed running)."""
    if block_x is None:
        # Solidly mid-block within the J3-J4 segment (960-1440): well clear
        # of both the J3/J4 signals and the TS_EB_2/TS_WB_2 busStop (which
        # sits at the START of this segment, ~960-1005 EB-side).
        block_x = 1300.0
    eid, pos = x_to_edgepos_eb(info, block_x)
    vclass_for_blocker = "tram" if cfg.arm in ("B", "BP") else "passenger"
    lines = ['<routes>']
    lines.append(f'  <vType id="blockveh" vClass="{vclass_for_blocker}" length="6.5" minGap="2.0" '
                 f'accel="1.2" decel="3.5" maxSpeed="16.7" color="1,0.4,0"/>')
    lines.append(f'  <route id="rBLOCK" edges="{eid}"/>')
    lines.append(f'  <vehicle id="blocker0" type="blockveh" route="rBLOCK" depart="{block_start:.1f}" '
                 f'departLane="1" departPos="{pos:.1f}" departSpeed="0">')
    lines.append(f'    <stop lane="{eid}_1" startPos="{pos:.1f}" endPos="{pos+6.5:.1f}" '
                 f'duration="{block_dur:.1f}" parking="false"/>')
    lines.append('  </vehicle>')
    lines.append('</routes>')
    p = os.path.join(outdir, "blockage.rou.xml")
    open(p, "w").write("\n".join(lines))
    return p, dict(edge=eid, pos=pos, start=block_start, dur=block_dur, vclass=vclass_for_blocker)


# ---------------------------------------------------------------------------
# top-level orchestration
# ---------------------------------------------------------------------------
def build_scenario(base_info, cfg: ArmCfg, outdir, seed, with_blockage=False):
    os.makedirs(outdir, exist_ok=True)
    net = build_variant(base_info, cfg, outdir)
    if cfg.arm in ("B", "BP") and cfg.left_turn == "prohibited":
        netp = os.path.join(outdir, f"{cfg.arm}_prohib.net.xml")
        prohibit_arterial_left(net, netp)
        net = netp
    tls_add, plan = build_tls_additional(cfg, net, outdir)
    final_net = bake_tls(net, tls_add, outdir, f"{cfg.arm}_{cfg.left_turn}")

    stops = []
    stops_add = None
    trams_path, n_tram = None, 0
    persons_path, n_pers = None, 0
    if cfg.has_tram():
        stops_add, stops = build_stops(base_info, final_net, outdir)
        trams_path, n_tram = build_trams(cfg, base_info, stops, outdir)
        persons_path, n_pers = build_persons(cfg, base_info, stops, outdir, seed)

    cars_path = build_cars(cfg, base_info, outdir, seed)

    block_path, block_info = (None, None)
    if with_blockage:
        block_path, block_info = build_blockage(cfg, base_info, outdir)

    return dict(net=final_net, plan=plan, stops_add=stops_add, stops=stops,
                trams=trams_path, n_tram=n_tram, persons=persons_path, n_persons=n_pers,
                cars=cars_path, block=block_path, block_info=block_info, cfg=asdict(cfg))
