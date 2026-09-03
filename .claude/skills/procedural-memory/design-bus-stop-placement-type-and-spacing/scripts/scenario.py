"""
Parameterised signalized-arterial-with-bus-stops scenario builder.

Everything the study sweeps is a field of Cfg: number of signals, block spacing,
arterial/cross lane counts, cycle/split/offsets, bus-stop PLACEMENT (near-side /
far-side / mid-block), bus-stop TYPE (in-lane vs bay), bus-stop SPACING, bus
headway, passenger demand (which drives dwell ENDOGENOUSLY through
boardingDuration), and car demand.

Reuses conventions from:
  - simulate-multimodal-transit          (busStop + <access> + person plans)
  - design-arterial-signal-progression-... (coordinated fixed-time arterial,
                                            (t - offset) mod C convention)
  - model-curbside-delivery-...          (parking="false" lane-blocking stop)
  - demonstrate-and-control-bus-bunching (boardingDuration-driven endogenous dwell)
"""
import os
import math
import random
import subprocess
import sys
from dataclasses import dataclass, field, asdict

SUMO_HOME = os.environ.get("SUMO_HOME", "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo")
sys.path.append(os.path.join(SUMO_HOME, "tools"))
import sumolib  # noqa: E402

BIN = os.path.join(SUMO_HOME, "bin")
NETCONVERT = os.path.join(BIN, "netconvert")
SUMO = os.path.join(BIN, "sumo")


@dataclass
class Cfg:
    # --- geometry ---
    n_signals: int = 6
    block_len: float = 400.0
    approach_len: float = 300.0
    cross_len: float = 250.0
    lanes_art: int = 2
    lanes_cross: int = 1
    speed_art: float = 13.89        # 50 km/h
    speed_cross: float = 13.89
    # --- signals (coordinated fixed time) ---
    cycle: float = 80.0
    art_green: float = 46.0
    yellow: float = 4.0
    prog_speed: float = 12.5        # progression design speed (m/s), EB
    # --- bus stops ---
    stop_placement: str = "farside"   # farside | nearside | midblock
    stop_type: str = "inlane"         # inlane | bay | geobay
    stop_spacing: float = 0.0         # 0 -> one stop per signal (placement rule);
                                      # >0 -> uniform spacing sweep (H4)
    stop_len: float = 20.0
    n_stops_override: int = 0
    # --- transit ---
    headway: float = 240.0
    bus_capacity: int = 60
    boarding_duration: float = 1.5
    min_dwell: float = 5.0
    # bay pull-out (re-entry) penalty. SUMO imposes NONE natively (verified) --
    # this adds an explicit gap-acceptance wait as a second PARKED stop that runs
    # AFTER boarding finishes.  0 => no penalty (SUMO-native bay).
    bay_reentry_tau: float = 0.0     # critical gap (s) a bus needs to pull out
    bay_reentry_cap: float = 90.0
    bay_extra_penalty: float = 0.0   # fixed extra parked seconds per bay stop
                                     # (used to probe HOW BIG a pull-out penalty
                                     #  would have to be to create a "bay trap")
    # --- demand ---
    q_art: float = 900.0            # veh/h/direction on the arterial
    q_cross: float = 250.0          # veh/h/direction on each cross street
    pax_rate: float = 600.0         # boarding persons/h over the whole corridor
    car_occupancy: float = 1.2
    walk_speed: float = 1.2
    # --- run window ---
    warmup: float = 600.0
    demand_end: float = 3000.0
    sim_end: float = 5400.0

    def label(self):
        return (f"{self.stop_placement}-{self.stop_type}-sp{int(self.stop_spacing)}"
                f"-h{int(self.headway)}-qa{int(self.q_art)}-pax{int(self.pax_rate)}"
                f"-la{self.lanes_art}")


# --------------------------------------------------------------------------
# network
# --------------------------------------------------------------------------
def signal_x(cfg, j):
    """x of signal j, j = 1..n_signals (signal 1 at x=0)."""
    return (j - 1) * cfg.block_len


def stop_x_positions(cfg):
    """Return list of (label, x_start) for each bus stop, EB direction."""
    out = []
    if cfg.stop_spacing and cfg.stop_spacing > 0:
        # uniform-spacing mode (H4): start half a spacing into the corridor
        corridor_end = signal_x(cfg, cfg.n_signals)
        x = cfg.stop_spacing / 2.0
        k = 0
        while x < corridor_end - 20:
            xs = x
            # keep the stop clear of the junction box: shift downstream if too close
            for j in range(1, cfg.n_signals + 1):
                sx = signal_x(cfg, j)
                if -55.0 < xs - sx < 35.0:
                    xs = sx + 35.0
            out.append((f"S{k}", xs))
            k += 1
            x += cfg.stop_spacing
    else:
        n = cfg.n_stops_override or (cfg.n_signals - 1)
        for j in range(1, n + 1):
            sx = signal_x(cfg, j)
            if cfg.stop_placement == "farside":
                xs = sx + 25.0
            elif cfg.stop_placement == "nearside":
                xs = sx - 45.0
            elif cfg.stop_placement == "midblock":
                xs = sx + cfg.block_len / 2.0 - 10.0
            else:
                raise ValueError(cfg.stop_placement)
            out.append((f"S{j}", xs))
    return out


def build_network(cfg, outdir):
    """Write node/edge/connection files and compile with netconvert.

    Returns dict with net path, EB edge list (ordered), WB edge list, cross route
    edge lists, and an x->(edge,pos) mapper for the EB direction.
    """
    os.makedirs(outdir, exist_ok=True)
    n = cfg.n_signals
    x0 = -cfg.approach_len
    xN = signal_x(cfg, n) + cfg.approach_len

    # EB break points: terminus W, signals 1..n, terminus E, plus (for geobay)
    # extra nodes bracketing every bus stop.
    breaks = [("W", x0, "priority")]
    for j in range(1, n + 1):
        breaks.append((f"J{j}", signal_x(cfg, j), "traffic_light"))
    breaks.append(("E", xN, "priority"))

    bay_zones = []
    if cfg.stop_type == "geobay":
        for lab, xs in stop_x_positions(cfg):
            a, b = xs - 25.0, xs + cfg.stop_len + 25.0
            bay_zones.append((lab, a, b))
            breaks.append((f"BA_{lab}", a, "priority"))
            breaks.append((f"BB_{lab}", b, "priority"))
    breaks.sort(key=lambda t: t[1])

    nodes = list(breaks)
    for j in range(1, n + 1):
        nodes.append((f"N{j}", signal_x(cfg, j), "priority"))
        nodes.append((f"Q{j}", signal_x(cfg, j), "priority"))

    nlines = ["<nodes>"]
    for nid, x, typ in breaks:
        nlines.append(f'  <node id="{nid}" x="{x:.2f}" y="0.00" type="{typ}"/>')
    for j in range(1, n + 1):
        sx = signal_x(cfg, j)
        nlines.append(f'  <node id="N{j}" x="{sx:.2f}" y="{cfg.cross_len:.2f}" type="priority"/>')
        nlines.append(f'  <node id="Q{j}" x="{sx:.2f}" y="{-cfg.cross_len:.2f}" type="priority"/>')
    nlines.append("</nodes>")

    def in_bay(a, b):
        for lab, za, zb in bay_zones:
            if abs(a - za) < 1e-6 and abs(b - zb) < 1e-6:
                return lab
        return None

    eb, wb = [], []
    elines = ["<edges>"]
    for i in range(len(breaks) - 1):
        (ia, xa, _), (ib, xb, _) = breaks[i], breaks[i + 1]
        eid = f"AE_{ia}_{ib}"
        wid = f"AW_{ib}_{ia}"
        lab = in_bay(xa, xb)
        if lab is not None:
            # bay section: one extra rightmost lane, bus-only -> a genuine
            # geometric pull-out bay (cars keep lanes_art through lanes)
            elines.append(f'  <edge id="{eid}" from="{ia}" to="{ib}" numLanes="{cfg.lanes_art+1}" '
                          f'speed="{cfg.speed_art}" spreadType="right">')
            elines.append('    <lane index="0" allow="bus"/>')
            elines.append('  </edge>')
        else:
            elines.append(f'  <edge id="{eid}" from="{ia}" to="{ib}" numLanes="{cfg.lanes_art}" '
                          f'speed="{cfg.speed_art}" spreadType="right"/>')
        elines.append(f'  <edge id="{wid}" from="{ib}" to="{ia}" numLanes="{cfg.lanes_art}" '
                      f'speed="{cfg.speed_art}" spreadType="right"/>')
        eb.append((eid, xa, xb, lab))
        wb.append(wid)
    for j in range(1, n + 1):
        elines.append(f'  <edge id="CN{j}_in" from="N{j}" to="J{j}" numLanes="{cfg.lanes_cross}" speed="{cfg.speed_cross}" spreadType="right"/>')
        elines.append(f'  <edge id="CN{j}_out" from="J{j}" to="N{j}" numLanes="{cfg.lanes_cross}" speed="{cfg.speed_cross}" spreadType="right"/>')
        elines.append(f'  <edge id="CS{j}_in" from="Q{j}" to="J{j}" numLanes="{cfg.lanes_cross}" speed="{cfg.speed_cross}" spreadType="right"/>')
        elines.append(f'  <edge id="CS{j}_out" from="J{j}" to="Q{j}" numLanes="{cfg.lanes_cross}" speed="{cfg.speed_cross}" spreadType="right"/>')
    elines.append("</edges>")

    nod = os.path.join(outdir, "net.nod.xml")
    edg = os.path.join(outdir, "net.edg.xml")
    open(nod, "w").write("\n".join(nlines))
    open(edg, "w").write("\n".join(elines))

    net = os.path.join(outdir, "corridor.net.xml")
    cmd = [NETCONVERT, "-n", nod, "-e", edg, "-o", net,
           "--no-turnarounds", "true",
           "--sidewalks.guess", "true", "--walkingareas", "true",
           "--crossings.guess", "true",
           "--tls.default-type", "static",
           "--default.junctions.keep-clear", "true",
           "--no-internal-links", "false",
           "--junctions.corner-detail", "0",
           "--offset.disable-normalization", "true"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("netconvert failed:\n" + r.stderr[-4000:])

    eb_edges = [e[0] for e in eb]
    wb_edges = list(reversed(wb))
    info = {
        "net": net,
        "eb_edges": eb_edges,
        "wb_edges": wb_edges,
        "eb_spans": [(e[0], e[1], e[2], e[3]) for e in eb],
        "cross_routes": {j: ([f"CN{j}_in", f"CS{j}_out"], [f"CS{j}_in", f"CN{j}_out"]) for j in range(1, n + 1)},
        "netconvert_stderr": r.stderr,
    }
    return info


def _edge_len(info, eid):
    for e, xa, xb, _ in info["eb_spans"]:
        if e == eid:
            return xb - xa
    return 100.0


def x_to_edgepos(info, x):
    """Map corridor x to (EB edge id, pos along edge)."""
    for eid, xa, xb, _lab in info["eb_spans"]:
        if xa - 1e-6 <= x <= xb + 1e-6:
            return eid, x - xa
    eid, xa, xb, _ = info["eb_spans"][-1]
    return eid, min(x - xa, xb - xa)


# --------------------------------------------------------------------------
# signals: coordinated fixed-time plan, built from the COMPILED net
# --------------------------------------------------------------------------
def build_tls(cfg, info, outdir):
    import xml.etree.ElementTree as ET
    net = sumolib.net.readNet(info["net"], withPrograms=True)
    root = ET.parse(info["net"]).getroot()
    # pedestrian crossings carry their own TLS link indices; classify each by the
    # street it crosses so it can be given green while that street is red.
    crossing_edges = {}
    for e in root.findall("edge"):
        if e.get("function") == "crossing":
            crossing_edges[e.get("id")] = e.get("crossingEdges", "").split()
    cross_links = {}
    for c in root.findall("connection"):
        tl = c.get("tl")
        to = c.get("to")
        if tl is None or to not in crossing_edges:
            continue
        crossed = crossing_edges[to]
        art = any(x.startswith("AE_") or x.startswith("AW_") for x in crossed)
        cross_links.setdefault(tl, {})[int(c.get("linkIndex"))] = "PA" if art else "PC"
    lines = ['<additional>']
    plan = {}
    for j in range(1, cfg.n_signals + 1):
        tid = f"J{j}"
        tls = net.getTLS(tid)
        conns = tls.getConnections()          # (inLane, outLane, linkIndex)
        nlinks = max(c[2] for c in conns) + 1
        nlinks = max(nlinks, max(cross_links.get(tid, {0: 0}).keys()) + 1)
        kind = ["?"] * nlinks
        for inl, outl, idx in conns:
            e = inl.getEdge().getID()
            if net.getEdge(e).getFunction() in ("walkingarea", "crossing"):
                continue
            art = e.startswith("AE_") or e.startswith("AW_")
            # direction of the movement
            d = "s"
            for c in inl.getOutgoing():
                if c.getToLane().getID() == outl.getID():
                    d = c.getDirection()
                    break
            kind[idx] = ("A" if art else "C") + d
        for idx, k in cross_links.get(tid, {}).items():
            kind[idx] = k

        def state(green_group):
            # green_group "A": arterial vehicle phase (+ crossings OVER the cross
            # street, tagged PC). "C": cross-street vehicle phase (+ crossings
            # over the arterial, tagged PA).
            ped_ok = "PC" if green_group == "A" else "PA"
            s = ""
            for k in kind:
                if k == "?":
                    s += "r"
                elif k == ped_ok:
                    s += "G"
                elif k in ("PA", "PC"):
                    s += "r"
                elif k[0] == green_group:
                    # through = protected G; turns = permissive g so they yield to
                    # the concurrent pedestrian crossing
                    s += "G" if k[1] == "s" else "g"
                else:
                    s += "r"
            return s

        def yel(green_group):
            ped_ok = "PC" if green_group == "A" else "PA"
            s = ""
            for k in kind:
                if k == "?":
                    s += "r"
                elif k in ("PA", "PC"):
                    s += "r"
                elif k[0] == green_group:
                    s += "y"
                else:
                    s += "r"
            return s
        cross_green = cfg.cycle - cfg.art_green - 2 * cfg.yellow
        assert cross_green > 4, "cross green too short"
        off = ((j - 1) * cfg.block_len / cfg.prog_speed) % cfg.cycle
        lines.append(f'  <tlLogic id="{tid}" type="static" programID="0" offset="{off:.2f}">')
        lines.append(f'    <phase duration="{cfg.art_green:.1f}" state="{state("A")}"/>')
        lines.append(f'    <phase duration="{cfg.yellow:.1f}" state="{yel("A")}"/>')
        lines.append(f'    <phase duration="{cross_green:.1f}" state="{state("C")}"/>')
        lines.append(f'    <phase duration="{cfg.yellow:.1f}" state="{yel("C")}"/>')
        lines.append('  </tlLogic>')
        plan[tid] = {"offset": off, "kind": kind,
                     "phases": [cfg.art_green, cfg.yellow, cross_green, cfg.yellow],
                     "art_state": state("A"), "cross_state": state("C")}
    lines.append('</additional>')
    p = os.path.join(outdir, "tls.add.xml")
    open(p, "w").write("\n".join(lines))
    return p, plan


# --------------------------------------------------------------------------
# bus stops
# --------------------------------------------------------------------------
def build_stops(cfg, info, outdir):
    net = sumolib.net.readNet(info["net"])
    lines = ['<additional>']
    stops = []
    for lab, xs in stop_x_positions(cfg):
        eid, pos = x_to_edgepos(info, xs)
        edge = net.getEdge(eid)
        lanes = edge.getLanes()
        # lane 0 is the guessed sidewalk; driving lanes are 1..
        side = lanes[0].getID()
        if cfg.stop_type == "geobay" and edge.getLaneNumber() == cfg.lanes_art + 2:
            stop_lane = lanes[1].getID()   # the bus-only bay lane
        else:
            stop_lane = lanes[1].getID()   # rightmost general travel lane
        L = edge.getLength()
        sp = max(1.0, min(pos, L - cfg.stop_len - 1.0))
        ep = sp + cfg.stop_len
        sid = f"BS_{lab}"
        lines.append(f'  <busStop id="{sid}" lane="{stop_lane}" startPos="{sp:.2f}" endPos="{ep:.2f}" '
                     f'lines="BUS" friendlyPos="false">')
        lines.append(f'    <access lane="{side}" pos="{(sp+ep)/2:.2f}" length="8.00"/>')
        lines.append('  </busStop>')
        stops.append({"id": sid, "label": lab, "x": xs, "edge": eid, "lane": stop_lane,
                      "startPos": sp, "endPos": ep, "access_lane": side})
    lines.append('</additional>')
    p = os.path.join(outdir, "busstops.add.xml")
    open(p, "w").write("\n".join(lines))
    return p, stops


# --------------------------------------------------------------------------
# demand
# --------------------------------------------------------------------------
VTYPES = """  <vType id="car" vClass="passenger" length="4.5" minGap="2.5" accel="2.6" decel="4.5"
         sigma="0.5" speedDev="0.10" tau="1.0" carFollowModel="Krauss"/>
  <vType id="bus" vClass="bus" length="12.0" minGap="3.0" accel="1.2" decel="3.0"
         sigma="0.5" speedDev="0.05" tau="1.2" personCapacity="{cap}"
         boardingDuration="{bd}" color="1,0.6,0">
    <param key="has.fcd.device" value="true"/>
  </vType>
"""


def build_cars(cfg, info, outdir, seed):
    rng = random.Random(20000 + seed)
    lines = ['<routes>', VTYPES.format(cap=cfg.bus_capacity, bd=cfg.boarding_duration)]
    lines.append(f'  <route id="rEB" edges="{" ".join(info["eb_edges"])}"/>')
    lines.append(f'  <route id="rWB" edges="{" ".join(info["wb_edges"])}"/>')
    for j, (ns, sn) in info["cross_routes"].items():
        lines.append(f'  <route id="rC{j}ns" edges="{" ".join(ns)}"/>')
        lines.append(f'  <route id="rC{j}sn" edges="{" ".join(sn)}"/>')
    vid = 0

    def poisson_stream(rate_per_h, route, tag):
        nonlocal vid
        if rate_per_h <= 0:
            return
        t = 0.0
        mean = 3600.0 / rate_per_h
        while True:
            t += rng.expovariate(1.0 / mean)
            if t >= cfg.demand_end:
                break
            lines.append(f'  <vehicle id="{tag}{vid}" type="car" route="{route}" depart="{t:.2f}" '
                         f'departLane="best" departSpeed="max"/>')
            vid += 1

    poisson_stream(cfg.q_art, "rEB", "eb")
    poisson_stream(cfg.q_art, "rWB", "wb")
    for j in info["cross_routes"]:
        poisson_stream(cfg.q_cross, f"rC{j}ns", f"c{j}n")
        poisson_stream(cfg.q_cross, f"rC{j}sn", f"c{j}s")
    lines.append('</routes>')
    # departure order must be sorted
    body = [l for l in lines if l.startswith('  <vehicle')]
    body.sort(key=lambda l: float(l.split('depart="')[1].split('"')[0]))
    head = [l for l in lines if not l.startswith('  <vehicle') and l != '</routes>']
    p = os.path.join(outdir, "cars.rou.xml")
    open(p, "w").write("\n".join(head + body + ['</routes>']))
    return p


def sample_reentry_wait(rng, q_per_lane_veh_s, tau, cap):
    """Classical gap-acceptance wait: reject exponential headways until one
    exceeds the critical gap tau. E[W] = (exp(q*tau)-1)/q - tau."""
    if tau <= 0 or q_per_lane_veh_s <= 0:
        return 0.0
    w = 0.0
    while w < cap:
        h = rng.expovariate(q_per_lane_veh_s)
        if h >= tau:
            return round(min(w, cap), 1)
        w += h
    return round(cap, 1)


def build_buses(cfg, info, stops, outdir, seed=0):
    rng = random.Random(40000 + seed)
    q_lane = (cfg.q_art / 3600.0) / max(cfg.lanes_art, 1)
    lines = ['<routes>']
    lines.append(f'  <route id="rBUS" edges="{" ".join(info["eb_edges"])}"/>')
    t = 0.0
    k = 0
    waits = []
    while t < cfg.demand_end:
        lines.append(f'  <vehicle id="bus{k}" type="bus" route="rBUS" line="BUS" depart="{t:.2f}" '
                     f'departLane="best" departSpeed="max">')
        for s in stops:
            park = "true" if cfg.stop_type in ("bay", "geobay") else "false"
            lines.append(f'    <stop busStop="{s["id"]}" duration="{cfg.min_dwell:.1f}" '
                         f'parking="{park}"/>')
            if park == "true" and (cfg.bay_reentry_tau > 0 or cfg.bay_extra_penalty > 0):
                w = cfg.bay_extra_penalty
                if cfg.bay_reentry_tau > 0:
                    w += sample_reentry_wait(rng, q_lane, cfg.bay_reentry_tau, cfg.bay_reentry_cap)
                waits.append(w)
                if w > 0:
                    lines.append(f'    <stop busStop="{s["id"]}" duration="{w:.1f}" parking="true"/>')
        lines.append('  </vehicle>')
        t += cfg.headway
        k += 1
    lines.append('</routes>')
    p = os.path.join(outdir, "buses.rou.xml")
    open(p, "w").write("\n".join(lines))
    return p, k, waits


def build_persons(cfg, info, stops, outdir, seed):
    """Explicit walk -> ride -> walk plans. Each person walks to the NEAREST stop
    to their origin and alights at the NEAREST stop to their destination, so the
    access-walk distribution is an exact, controllable function of stop spacing
    (this is a deliberate modelling choice, not intermodal duarouter mode choice
    -- documented as such in FINDINGS.md)."""
    rng = random.Random(30000 + seed)
    xs = [s["x"] + cfg.stop_len / 2.0 for s in stops]
    corridor_a = 0.0
    corridor_b = signal_x(cfg, cfg.n_signals)
    lines = ['<routes>']
    n = 0
    skipped = 0
    t = 0.0
    mean = 3600.0 / cfg.pax_rate if cfg.pax_rate > 0 else 1e9
    recs = []
    pax_end = cfg.demand_end - 600.0     # last bus must still be able to serve them
    while True:
        t += rng.expovariate(1.0 / mean)
        if t >= pax_end:
            break
        # OD draw is INDEPENDENT of stop layout (CRN across spacing/placement arms)
        xo = rng.uniform(corridor_a, corridor_b)
        trip = rng.uniform(500.0, 1600.0)
        xd = min(xo + trip, corridor_b)
        if xd - xo < 400.0:
            skipped += 1
            continue
        bi = min(range(len(xs)), key=lambda i: abs(xs[i] - xo))
        ai = min(range(len(xs)), key=lambda i: abs(xs[i] - xd))
        if ai <= bi:
            skipped += 1
            continue
        eo, po = x_to_edgepos(info, xo)
        ed, pd = x_to_edgepos(info, xd)
        po = min(max(5.0, po), _edge_len(info, eo) - 15.0)
        pd = min(max(5.0, pd), _edge_len(info, ed) - 15.0)
        pid = f"p{n}"
        lines.append(f'  <person id="{pid}" depart="{t:.2f}" departPos="{po:.2f}">')
        lines.append(f'    <walk from="{eo}" busStop="{stops[bi]["id"]}"/>')
        lines.append(f'    <ride busStop="{stops[ai]["id"]}" lines="BUS"/>')
        lines.append(f'    <walk to="{ed}" arrivalPos="{pd:.2f}"/>')
        lines.append('  </person>')
        recs.append({"id": pid, "depart": t, "xo": xo, "xd": xd,
                     "board": stops[bi]["id"], "alight": stops[ai]["id"],
                     "access_dx": abs(xs[bi] - xo), "egress_dx": abs(xs[ai] - xd)})
        n += 1
    lines.append('</routes>')
    body = [l for l in lines]
    p = os.path.join(outdir, "persons.rou.xml")
    open(p, "w").write("\n".join(body))
    return p, n, skipped, recs


def bake_tls_into_net(info, tls_path, outdir):
    """Second netconvert pass: bake the coordinated program into the compiled net
    (SUMO refuses a second tlLogic with programID 0 from an additional file)."""
    out = os.path.join(outdir, "corridor_tls.net.xml")
    r = subprocess.run([NETCONVERT, "-s", info["net"], "-i", tls_path, "-o", out],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("netconvert(tls) failed:\n" + r.stderr[-4000:])
    info["net_base"] = info["net"]
    info["net"] = out
    return out


def build_scenario(cfg, outdir, seed):
    os.makedirs(outdir, exist_ok=True)
    info = build_network(cfg, outdir)
    tls, plan = build_tls(cfg, info, outdir)
    bake_tls_into_net(info, tls, outdir)
    add_stops, stops = build_stops(cfg, info, outdir)
    cars = build_cars(cfg, info, outdir, seed)
    buses, nbus, waits = build_buses(cfg, info, stops, outdir, seed)
    persons, npers, nskip, precs = build_persons(cfg, info, stops, outdir, seed)
    return {"cfg": asdict(cfg), "info": info, "tls": tls, "plan": plan,
            "busstops": add_stops, "stops": stops, "cars": cars, "buses": buses,
            "reentry_waits": waits,
            "n_buses": nbus, "persons": persons, "n_persons": npers,
            "n_skipped": nskip, "person_recs": precs, "net": info["net"]}
