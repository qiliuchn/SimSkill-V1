"""
tspcore.py -- Transit Service Planning as a Design & Optimization Problem.

Core library:
  * network construction (6x6 grid + sidewalks/crossings; optional bus-lane variant)
  * zone system, documented zone-to-zone OD, person + background-car demand
  * ServicePlan (lines = stop sequence + integer bus allocation) and its
    compiler into a runnable SUMO scenario
  * runner (duarouter intermodal routing + sumo) with CRN seeds
  * personinfo stage decomposition and generalized-cost accounting
  * measured-cycle-time bus-hour budget module

Reuses conventions from procedural-memory skills:
  simulate-multimodal-transit, demonstrate-and-control-bus-bunching,
  evaluate-multimodal-accessibility-and-equity,
  optimize-under-simulation-noise-with-a-fixed-budget
and semantic-memory pages public-transport-and-intermodal-routing,
sumo-output-files, traci, sumo-command-line.
"""
import os, sys, math, random, subprocess, shutil, csv, json
import xml.etree.ElementTree as ET
from collections import defaultdict

# SUMO 1.27.1 framework layout: the data/ dir SUMO_HOME must point at lives in
# <framework>/EclipseSUMO/share/sumo, while the binaries live in
# <framework>/EclipseSUMO/bin.  Setting SUMO_HOME to the framework root makes
# every tool print "Environment variable SUMO_HOME is not set properly".
FRAMEWORK = "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO"
SUMO_HOME = os.path.join(FRAMEWORK, "share", "sumo")
os.environ["SUMO_HOME"] = SUMO_HOME
BIN = os.path.join(FRAMEWORK, "bin")
NETGENERATE = os.path.join(BIN, "netgenerate")
NETCONVERT = os.path.join(BIN, "netconvert")
DUAROUTER = os.path.join(BIN, "duarouter")
SUMO = os.path.join(BIN, "sumo")
TOOLS = os.path.join(SUMO_HOME, "tools")
RANDOMTRIPS = os.path.join(TOOLS, "randomTrips.py")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "work")
OUT = os.path.join(ROOT, "outputs")

# ----------------------------------------------------------------------------
# geometry / zones
# ----------------------------------------------------------------------------
COLS = "ABCDEF"
NC, NR = 6, 6
SPACING = 800.0          # m  -> city is 4.0 km across
CBD_ZONE = 4             # centre zone (cols C,D  rows 2,3)

def nname(c, r):  return f"{COLS[c]}{r}"
def ncoord(c, r): return (c * SPACING, r * SPACING)
def zone_of(c, r): return (r // 2) * 3 + (c // 2)

ALL_NODES = [(c, r) for c in range(NC) for r in range(NR)]
NODE_CR = {nname(c, r): (c, r) for c, r in ALL_NODES}
ZONE_NODES = defaultdict(list)
for _c, _r in ALL_NODES:
    ZONE_NODES[zone_of(_c, _r)].append(nname(_c, _r))

ZONE_NAME = {0: "Z0_SW_periph", 1: "Z1_S", 2: "Z2_SE_periph", 3: "Z3_W",
             4: "Z4_CBD", 5: "Z5_E", 6: "Z6_NW_periph", 7: "Z7_N",
             8: "Z8_NE_periph"}

# Documented zone attributes.  P = peak-hour trip productions weight,
# J = attractions weight, CAR = car-availability rate of residents.
ZONE_P   = {0: 0.45, 1: 1.00, 2: 0.60, 3: 1.00, 4: 0.55, 5: 1.00, 6: 0.50, 7: 1.00, 8: 0.60}
ZONE_J   = {0: 0.25, 1: 0.55, 2: 0.35, 3: 0.60, 4: 4.00, 5: 0.60, 6: 0.25, 7: 0.70, 8: 0.35}
ZONE_CAR = {0: 0.85, 1: 0.60, 2: 0.80, 3: 0.55, 4: 0.35, 5: 0.55, 6: 0.85, 7: 0.50, 8: 0.80}
# residential population used for coverage / equity weighting (persons)
ZONE_POP = {z: int(round(4000 * ZONE_P[z])) for z in range(9)}

def zone_centroid(z):
    xs = [ncoord(*NODE_CR[n]) for n in ZONE_NODES[z]]
    return (sum(p[0] for p in xs) / len(xs), sum(p[1] for p in xs) / len(xs))

# ----------------------------------------------------------------------------
# demand / simulation timing constants
# ----------------------------------------------------------------------------
SERVICE_SPAN = 3600.0     # s of bus departures (0 .. SERVICE_SPAN)  -> bus-hours == buses
DEMAND_BEGIN = 600.0
DEMAND_END   = 3000.0     # 40 min peak person-demand window
SIM_END      = 5400.0

# generalized cost weights (minutes-equivalent multipliers on clock time)
W_ACCESS   = 2.0          # access + egress walk
W_WAIT     = 2.0          # initial wait at first stop
W_IVT      = 1.0          # in-vehicle
W_XWALK    = 2.0          # transfer walk
W_XWAIT    = 2.0          # transfer wait
P_TRANSFER = 300.0        # s of pure penalty per transfer (base value)
W_WALKONLY = 2.0          # all-walk trips

BUS_HOUR_SPAN_H = SERVICE_SPAN / 3600.0   # = 1.0 -> "N buses" == "N bus-hours"


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
def run(cmd, cwd=None, quiet=True):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write("FAILED: " + " ".join(str(c) for c in cmd) + "\n")
        sys.stderr.write(r.stdout[-4000:] + "\n" + r.stderr[-6000:] + "\n")
        raise RuntimeError("command failed")
    return r


def ensure(d):
    os.makedirs(d, exist_ok=True)
    return d


# ----------------------------------------------------------------------------
# network
# ----------------------------------------------------------------------------
def build_network(workdir, buslane_edges=None, tag="base"):
    """Build the 6x6 grid with sidewalks/crossings.  If buslane_edges is given,
    lane index 1 of those edges is restricted to vClass bus."""
    ensure(workdir)
    prefix = os.path.join(workdir, f"plain_{tag}")
    run([NETGENERATE, "--grid", "--grid.x-number", str(NC), "--grid.y-number", str(NR),
         "--grid.length", str(SPACING), "-j", "traffic_light", "-L", "2",
         "--default.speed", "13.89", "--tls.default-type", "static",
         "--plain-output-prefix", prefix, "-o", os.path.join(workdir, f"_tmp_{tag}.net.xml")])

    edg = prefix + ".edg.xml"
    if buslane_edges:
        t = ET.parse(edg); root = t.getroot()
        n = 0
        for e in root.findall("edge"):
            if e.get("id") in buslane_edges:
                for existing in list(e.findall("lane")):
                    e.remove(existing)
                ln = ET.SubElement(e, "lane")
                ln.set("index", "1")          # left lane -> bus only
                ln.set("allow", "bus")
                n += 1
        t.write(edg)
        print(f"  bus lane applied to {n} edges")

    net = os.path.join(workdir, f"{tag}.net.xml")
    run([NETCONVERT,
         "-n", prefix + ".nod.xml", "-e", edg, "-x", prefix + ".con.xml",
         "-i", prefix + ".tll.xml",
         "--sidewalks.guess", "--sidewalks.guess.max-speed", "25",
         "--crossings.guess", "--walkingareas",
         "--tls.default-type", "static",
         "-o", net])
    return net


class Net:
    def __init__(self, netfile):
        self.file = netfile
        r = ET.parse(netfile).getroot()
        self.edge_len = {}
        self.edge_lanes = {}
        self.ped_lane = {}
        self.drive_lane = {}
        for e in r.findall("edge"):
            if e.get("function") is not None:
                continue
            eid = e.get("id")
            lanes = e.findall("lane")
            self.edge_lanes[eid] = [l.get("id") for l in lanes]
            self.edge_len[eid] = float(lanes[0].get("length"))
            for l in lanes:
                allow = l.get("allow", "")
                disallow = l.get("disallow", "")
                if "pedestrian" in allow:
                    self.ped_lane[eid] = l.get("id")
                elif "pedestrian" not in disallow and allow == "":
                    self.drive_lane.setdefault(eid, l.get("id"))
                else:
                    self.drive_lane.setdefault(eid, l.get("id"))
            # prefer the rightmost non-pedestrian lane for bus stops
            nonped = [l.get("id") for l in lanes if "pedestrian" not in l.get("allow", "")]
            if nonped:
                self.drive_lane[eid] = nonped[0]
        self.out_edges = defaultdict(list)
        self.in_edges = defaultdict(list)
        for eid in self.edge_len:
            a, b = eid[:2], eid[2:]
            if a in NODE_CR and b in NODE_CR:
                self.out_edges[a].append(eid)
                self.in_edges[b].append(eid)

    def edge(self, a, b):
        return f"{a}{b}"


# ----------------------------------------------------------------------------
# demand
# ----------------------------------------------------------------------------
def build_od(seed=7):
    """Documented zone-to-zone OD shares.
       55% radial-in (any zone -> CBD), 10% radial-out (CBD -> any zone),
       35% crosstown (non-CBD -> non-CBD, gravity with 2 km decay)."""
    od = defaultdict(float)
    # radial in
    tot = sum(ZONE_P[z] for z in range(9) if z != CBD_ZONE)
    for z in range(9):
        if z == CBD_ZONE: continue
        od[(z, CBD_ZONE)] += 0.55 * ZONE_P[z] / tot
    # radial out
    totj = sum(ZONE_J[z] for z in range(9) if z != CBD_ZONE)
    for z in range(9):
        if z == CBD_ZONE: continue
        od[(CBD_ZONE, z)] += 0.10 * ZONE_J[z] / totj
    # crosstown, gravity
    w = {}
    for i in range(9):
        for j in range(9):
            if i == j or i == CBD_ZONE or j == CBD_ZONE: continue
            ci, cj = zone_centroid(i), zone_centroid(j)
            d = math.hypot(ci[0]-cj[0], ci[1]-cj[1])
            w[(i, j)] = ZONE_P[i] * ZONE_J[j] * math.exp(-d / 2000.0)
    s = sum(w.values())
    for k, v in w.items():
        od[k] += 0.35 * v / s
    return dict(od)


CAR_CHOICE_SHARE = 0.75   # of car-available travellers, share that drives (exogenous)
MIN_TRIP_M = 1200.0       # only OD pairs at least this far apart enter the market


def build_demand(net, workdir, n_trips=1200, seed=7):
    """Emit persons.trips.xml (transit-market persons, modes=public) and
       modechoice_cars.trips.xml (car-choosing travellers)."""
    rng = random.Random(seed)
    od = build_od()
    pairs = list(od.items())
    keys = [k for k, v in pairs]
    wts = [v for k, v in pairs]

    persons, cars, meta = [], [], []
    made = 0
    guard = 0
    while made < n_trips and guard < n_trips * 60:
        guard += 1
        zi, zj = rng.choices(keys, weights=wts, k=1)[0]
        no = rng.choice(ZONE_NODES[zi]); nd = rng.choice(ZONE_NODES[zj])
        if no == nd: continue
        po, pd = ncoord(*NODE_CR[no]), ncoord(*NODE_CR[nd])
        if math.hypot(po[0]-pd[0], po[1]-pd[1]) < MIN_TRIP_M: continue
        oe = rng.choice(net.out_edges[no]); de = rng.choice(net.in_edges[nd])
        opos = rng.uniform(30.0, 400.0)
        dpos = max(10.0, net.edge_len[de] - rng.uniform(30.0, 400.0))
        dep = rng.uniform(DEMAND_BEGIN, DEMAND_END)
        car_avail = rng.random() < ZONE_CAR[zi]
        pid = f"p{made}"
        if car_avail and rng.random() < CAR_CHOICE_SHARE:
            cars.append((dep, f'    <trip id="c{made}" type="car" depart="{dep:.1f}" '
                              f'from="{oe}" to="{de}" departPos="{opos:.1f}" '
                              f'arrivalPos="{dpos:.1f}" departLane="best"/>'))
        else:
            persons.append((dep, f'    <person id="{pid}" depart="{dep:.1f}" type="ped">\n'
                                 f'        <personTrip from="{oe}" to="{de}" modes="public" '
                                 f'departPos="{opos:.1f}" arrivalPos="{dpos:.1f}"/>\n'
                                 f'    </person>'))
            meta.append(dict(id=pid, ozone=zi, dzone=zj, onode=no, dnode=nd,
                             car_avail=int(car_avail), depart=round(dep, 1),
                             ox=po[0], oy=po[1], dx=pd[0], dy=pd[1],
                             oedge=oe, opos=round(opos, 1), dedge=de, dpos=round(dpos, 1)))
        made += 1

    persons.sort(key=lambda t: t[0]); cars.sort(key=lambda t: t[0])
    pf = os.path.join(workdir, "persons.trips.xml")
    with open(pf, "w") as f:
        f.write('<routes>\n    <vType id="ped" vClass="pedestrian" speedDev="0.1"/>\n')
        f.write("\n".join(x[1] for x in persons)); f.write("\n</routes>\n")
    cf = os.path.join(workdir, "modechoice_cars.trips.xml")
    with open(cf, "w") as f:
        f.write('<routes>\n    <vType id="car" vClass="passenger" sigma="0.5" speedDev="0.10"/>\n')
        f.write("\n".join(x[1] for x in cars)); f.write("\n</routes>\n")
    with open(os.path.join(workdir, "person_meta.json"), "w") as f:
        json.dump(meta, f)
    return pf, cf, meta


def build_background(net, workdir, n_veh=2600, seed=11):
    """Background car traffic (through/other trips) so buses are genuinely delayed."""
    trips = os.path.join(workdir, "bg.trips.xml")
    period = (DEMAND_END - DEMAND_BEGIN + 900.0) / n_veh
    run([sys.executable, RANDOMTRIPS, "-n", net.file, "-o", trips,
         "-b", str(DEMAND_BEGIN - 600), "-e", str(DEMAND_END + 300),
         "--period", f"{period:.4f}", "--seed", str(seed),
         "--fringe-factor", "4", "--min-distance", "1500",
         "--trip-attributes", 'departLane="best"',
         "--vehicle-class", "passenger", "--validate"])
    # normalise the vType randomTrips created to our "car" type
    t = ET.parse(trips); root = t.getroot()
    for vt in root.findall("vType"):
        root.remove(vt)
    for tr in root.findall("trip"):
        tr.set("type", "car")   # vType "car" is declared once, in modechoice_cars.trips.xml
    t.write(trips)
    return trips


def route_cars(net, workdir, trip_files, out_name):
    out = os.path.join(workdir, out_name)
    run([DUAROUTER, "-n", net.file, "-r", ",".join(trip_files), "-o", out,
         "--ignore-errors", "--no-step-log", "--routing-threads", "4",
         "--departlane", "best"])
    return out


# ----------------------------------------------------------------------------
# service plan
# ----------------------------------------------------------------------------
class Line:
    """A transit line: node sequence (one direction).  The vehicle runs out and
    back, so the round trip is nodes + reversed(nodes)."""
    def __init__(self, lid, nodes, buses=1, offset=0.0):
        self.id = lid
        self.nodes = list(nodes)
        self.buses = int(buses)
        self.offset = float(offset)

    def edges_fwd(self):
        return [f"{self.nodes[i]}{self.nodes[i+1]}" for i in range(len(self.nodes)-1)]

    def edges_round(self):
        f = self.edges_fwd()
        rev = [f"{self.nodes[i+1]}{self.nodes[i]}" for i in range(len(self.nodes)-1)][::-1]
        return f + rev

    def length_m(self, net):
        return sum(net.edge_len[e] for e in self.edges_round())


class ServicePlan:
    """A set of lines with an integer bus allocation.  Headways are DERIVED
    from measured cycle time:  h_l = C_l / N_l."""
    def __init__(self, name, lines, cycles=None):
        self.name = name
        self.lines = list(lines)
        self.cycles = dict(cycles or {})     # line id -> cycle+layover seconds

    def copy(self, buses=None):
        ls = [Line(l.id, l.nodes, buses[l.id] if buses else l.buses, l.offset) for l in self.lines]
        return ServicePlan(self.name, ls, self.cycles)

    def headway(self, lid):
        L = {l.id: l for l in self.lines}[lid]
        C = self.cycles.get(lid, 1200.0)
        return C / max(1, L.buses)

    def total_buses(self):
        return sum(l.buses for l in self.lines)

    def bus_hours(self):
        return self.total_buses() * BUS_HOUR_SPAN_H


# --- stop placement -----------------------------------------------------------
def stop_id(edge, end):
    return f"S_{edge}_{end}"          # end in {"lo","hi"}


def plan_stops(plan, net):
    """Every line serves a stop near the downstream end ('hi') of each edge it
    traverses, plus a stop near the upstream end ('lo') of its first edge so the
    origin terminal is served.  Stops are shared between lines that use the same
    edge -- that is what makes a transfer a short walk across the junction."""
    stops = {}          # sid -> dict(edge, lane, start, end, node, lines)
    for L in plan.lines:
        er = L.edges_round()
        seq = []
        first = er[0]
        seq.append((stop_id(first, "lo"), first, "lo"))
        for e in er:
            seq.append((stop_id(e, "hi"), e, "hi"))
        for sid, e, end in seq:
            if sid not in stops:
                ln = net.edge_len[e]
                if end == "hi":
                    sp, ep = max(5.0, ln - 45.0), max(20.0, ln - 25.0)
                    node = e[2:]
                else:
                    sp, ep = 15.0, 35.0
                    node = e[:2]
                stops[sid] = dict(edge=e, lane=net.drive_lane[e], start=sp, end=ep,
                                  node=node, lines=set(), ped=net.ped_lane[e])
            stops[sid]["lines"].add(L.id)
        L._stopseq = [s[0] for s in seq]
    return stops


def write_busstops(stops, path):
    with open(path, "w") as f:
        f.write("<additional>\n")
        for sid, s in sorted(stops.items()):
            f.write(f'    <busStop id="{sid}" lane="{s["lane"]}" startPos="{s["start"]:.1f}" '
                    f'endPos="{s["end"]:.1f}" lines="{" ".join(sorted(s["lines"]))}" '
                    f'friendlyPos="true">\n')
            f.write(f'        <access lane="{s["ped"]}" pos="{(s["start"]+s["end"])/2:.1f}" '
                    f'friendlyPos="true"/>\n')
            f.write("    </busStop>\n")
        f.write("</additional>\n")


BUS_VTYPE = ('    <vType id="bus" vClass="bus" length="12.0" accel="1.2" decel="2.5" '
             'sigma="0.5" speedDev="0.10" maxSpeed="16.7" personCapacity="60" '
             'boardingDuration="1.5" color="1,0.6,0"/>\n')

DWELL_MIN = 12.0          # s door time floor at every stop


def stop_distances(L, net):
    """Cumulative distance along the round trip of each stop in L._stopseq."""
    er = L.edges_round()
    d, cum = [], 0.0
    d.append(25.0)                       # the 'lo' stop on the first edge
    for e in er:
        d.append(cum + net.edge_len[e] - 35.0)
        cum += net.edge_len[e]
    return d, cum


def write_pt_vehicles(plan, net, stops, path, run_speed=None, dwell=None):
    """Emit one <vehicle> per round trip with an absolute until= timetable.

    The intermodal router only treats a line as usable when its stops carry an
    absolute until= (see [[public-transport-and-intermodal-routing]]).  The
    timetable is deliberately built from the *uncongested* running speed so that
    `until` is (almost) never binding: SUMO departs a stop at
    max(arrival + duration, until), so a generous timetable would silently turn
    every bus into a schedule-adherent vehicle and erase traffic delay from the
    measured cycle time entirely.
    """
    run_speed = run_speed or {}
    dwell = dwell if dwell is not None else DWELL_MIN
    lines_out, sched = [], {}
    for L in plan.lines:
        v = run_speed.get(L.id, 9.0)
        dists, total_len = stop_distances(L, net)
        offs = [dists[k] / v + (k + 1) * dwell for k in range(len(dists))]
        assert len(offs) == len(L._stopseq), (len(offs), len(L._stopseq))
        C = plan.cycles.get(L.id) or (offs[-1] * 1.10 + LAYOVER_MIN)
        h = C / max(1, L.buses)
        sched[L.id] = dict(headway=h, cycle_used=C, sched_runtime=offs[-1],
                           n_stops=len(L._stopseq), length_m=total_len,
                           run_speed=v, buses=L.buses)
        k = 0
        while True:
            dep = L.offset + k * h
            if dep >= SERVICE_SPAN:
                break
            body = [f'    <vehicle id="{L.id}.{k}" type="bus" line="{L.id}" '
                    f'depart="{dep:.1f}" departPos="0" departSpeed="max">',
                    f'        <route edges="{" ".join(L.edges_round())}"/>']
            for sid, off in zip(L._stopseq, offs):
                body.append(f'        <stop busStop="{sid}" duration="{dwell:.0f}" '
                            f'until="{dep + off:.1f}"/>')
            body.append("    </vehicle>")
            lines_out.append((dep, "\n".join(body)))
            k += 1
    lines_out.sort(key=lambda t: t[0])
    with open(path, "w") as f:
        f.write("<routes>\n"); f.write(BUS_VTYPE)
        f.write("\n".join(x[1] for x in lines_out)); f.write("\n</routes>\n")
    return sched


# ----------------------------------------------------------------------------
# compile + run
# ----------------------------------------------------------------------------
def compile_plan(plan, net, scen_dir, run_speed=None, write=True):
    ensure(scen_dir)
    stops = plan_stops(plan, net)           # also populates each Line._stopseq
    add = os.path.join(scen_dir, "busstops.add.xml")
    ptv = os.path.join(scen_dir, "pt_vehicles.rou.xml")
    if not write and os.path.exists(add) and os.path.exists(ptv):
        sched = json.load(open(os.path.join(scen_dir, "schedule.json")))
        return dict(add=add, ptv=ptv, stops=stops, sched=sched)
    write_busstops(stops, add)
    sched = write_pt_vehicles(plan, net, stops, ptv, run_speed)
    with open(os.path.join(scen_dir, "schedule.json"), "w") as f:
        json.dump(sched, f, indent=1)
    return dict(add=add, ptv=ptv, stops=stops, sched=sched)


def route_persons(net, comp, persons_trips, scen_dir, threads=4, extra=None,
                  reuse=False):
    out = os.path.join(scen_dir, "persons.routed.rou.xml")
    if reuse and os.path.exists(out) and os.path.getsize(out) > 0:
        return out
    cmd = [DUAROUTER, "-n", net.file, "--additional-files", comp["add"],
           "-r", f'{comp["ptv"]},{persons_trips}', "-o", out,
           "--ignore-errors", "--no-step-log", "--routing-threads", str(threads),
           "--persontrip.walkfactor", "0.9"]
    if extra: cmd += extra
    run(cmd)
    return out


def simulate(net, comp, routed_persons, car_routes, out_dir, seed=1,
             stop_output=True, extra=None):
    ensure(out_dir)
    tri = os.path.join(out_dir, "tripinfo.xml")
    sto = os.path.join(out_dir, "stopinfo.xml")
    summ = os.path.join(out_dir, "summary.xml")
    rfiles = [comp["ptv"]] + ([routed_persons] if routed_persons else []) + list(car_routes)
    cmd = [SUMO, "-n", net.file, "--additional-files", comp["add"],
           "-r", ",".join(rfiles),
           "--tripinfo-output", tri, "--tripinfo-output.write-unfinished", "true",
           "--summary-output", summ,
           "--begin", "0", "--end", str(int(SIM_END)),
           "--seed", str(seed), "--no-step-log", "true",
           "--time-to-teleport", "300",
           "--pedestrian.model", "striping",
           "--ignore-route-errors", "true",
           "--duration-log.statistics", "true",
           "--device.rerouting.probability", "0",
           "--xml-validation", "never"]
    if stop_output:
        cmd += ["--stop-output", sto, "--stop-output.write-unfinished", "true"]
    if extra: cmd += extra
    r = run(cmd)
    with open(os.path.join(out_dir, "sumo.log"), "w") as f:
        f.write(r.stdout + "\n=== STDERR ===\n" + r.stderr)
    return dict(tripinfo=tri, stopinfo=sto if stop_output else None,
                summary=summ, log=r.stdout + r.stderr)


# ----------------------------------------------------------------------------
# output parsing
# ----------------------------------------------------------------------------
def parse_personinfos(tripinfo):
    """Stage decomposition per person, from <personinfo>.

    Verified semantics (SUMO 1.27.1), see s3_mechanisms.py:
      * legs are <walk>, <access stop="..">, <ride>, in plan order;
      * <ride depart=..> is the BOARDING time, so ride@duration EXCLUDES the
        wait; ride@waitingTime is the wait that preceded boarding;
      * personinfo@duration == sum of all leg durations + sum of ride waits, and
        personinfo@traveltime == duration - sum(ride waitingTime);
      * a person who never completes still gets a <personinfo>, with
        duration="-1"; the leg they were stuck on has vehicle="NULL",
        depart="-1", duration="-1" and a REAL waitingTime (the censored wait).
    """
    out = []
    for ev, el in ET.iterparse(tripinfo, events=("end",)):
        if el.tag != "personinfo":
            continue
        legs = list(el)
        rides = [i for i, l in enumerate(legs) if l.tag == "ride"]
        complete = el.get("duration") not in (None, "-1", "-1.00")

        def dur(l):
            v = l.get("duration")
            try:
                v = float(v)
            except (TypeError, ValueError):
                return 0.0
            return v if v > 0 else 0.0

        def wt(l):
            try:
                return max(0.0, float(l.get("waitingTime", 0.0)))
            except (TypeError, ValueError):
                return 0.0

        stranded = any(l.tag == "ride" and l.get("vehicle") in (None, "NULL")
                       for l in legs)
        boarded = [i for i in rides if legs[i].get("vehicle") not in (None, "NULL")]
        d = dict(id=el.get("id"), depart=float(el.get("depart")),
                 n_rides=len(boarded), complete=complete, stranded=stranded,
                 n_ride_legs_planned=len(rides))
        if not boarded:
            w = sum(dur(l) for l in legs if l.tag in ("walk", "access"))
            cw = sum(wt(legs[i]) for i in rides)
            d.update(mode=("walk" if not rides else "stranded"), access=w, wait=cw,
                     ivt=0.0, xwalk=0.0, xwait=0.0, egress=0.0, n_transfers=0,
                     total=w + cw, lines=[])
        else:
            i0, i1 = boarded[0], boarded[-1]
            acc = sum(dur(l) for l in legs[:i0] if l.tag in ("walk", "access"))
            egr = sum(dur(l) for l in legs[i1 + 1:] if l.tag in ("walk", "access"))
            xw = sum(dur(l) for l in legs[i0 + 1:i1] if l.tag in ("walk", "access"))
            wait0 = wt(legs[i0])
            xwait = sum(wt(legs[j]) for j in rides[1:])
            ivt = sum(dur(legs[j]) for j in boarded)
            d.update(mode="transit", access=acc, wait=wait0, ivt=ivt, xwalk=xw,
                     xwait=xwait, egress=egr, n_transfers=len(boarded) - 1,
                     total=acc + egr + xw + wait0 + xwait + ivt,
                     lines=[legs[j].get("vehicle", "") for j in boarded])
        arr = None
        for l in reversed(legs):
            a = l.get("arrival")
            if a is not None and float(a) > 0:
                arr = float(a); break
        d["arrival"] = arr
        d["reported_duration"] = float(el.get("duration")) if complete else None
        out.append(d)
        el.clear()
    return out


def gen_cost(p, p_transfer=P_TRANSFER):
    if p["mode"] == "walk":
        return W_WALKONLY * p["access"]
    return (W_ACCESS * (p["access"] + p["egress"]) + W_WAIT * p["wait"]
            + W_IVT * p["ivt"] + W_XWALK * p["xwalk"] + W_XWAIT * p["xwait"]
            + p_transfer * p["n_transfers"])


def parse_bus_tripinfo(tripinfo):
    """Per-bus round-trip records from <tripinfo> for vehicles of type bus."""
    recs = []
    for ev, el in ET.iterparse(tripinfo, events=("end",)):
        if el.tag != "tripinfo":
            continue
        if el.get("vType") == "bus":
            arr = float(el.get("arrival"))
            recs.append(dict(id=el.get("id"), line=el.get("id").split(".")[0],
                             depart=float(el.get("depart")),
                             arrival=arr,
                             duration=float(el.get("duration")),
                             departDelay=float(el.get("departDelay", 0.0)),
                             complete=arr > 0))
        el.clear()
    return recs


def parse_car_stats(tripinfo):
    n, dur, delay = 0, 0.0, 0.0
    for ev, el in ET.iterparse(tripinfo, events=("end",)):
        if el.tag == "tripinfo" and el.get("vType") == "car":
            n += 1
            dur += float(el.get("duration"))
            delay += float(el.get("timeLoss"))
        if el.tag in ("tripinfo", "personinfo"):
            el.clear()
    return dict(n_cars=n, mean_car_dur=dur/n if n else 0.0,
                mean_car_timeloss=delay/n if n else 0.0)


def parse_stopinfo(stopinfo):
    rows = []
    if not stopinfo or not os.path.exists(stopinfo):
        return rows
    for ev, el in ET.iterparse(stopinfo, events=("end",)):
        if el.tag != "stopinfo":
            continue
        vid = el.get("id")
        rows.append(dict(vehicle=vid, line=vid.split(".")[0],
                         busStop=el.get("busStop"),
                         started=float(el.get("started", -1)),
                         ended=float(el.get("ended", -1)),
                         loaded=int(el.get("loadedPersons", 0)),
                         unloaded=int(el.get("unloadedPersons", 0)),
                         delay=float(el.get("delay", 0.0))))
        el.clear()
    return rows


def teleport_count(log):
    n = 0
    for ln in log.splitlines():
        if "teleporting" in ln.lower():
            n += 1
    return n


# ----------------------------------------------------------------------------
# budget accounting from measured quantities
# ----------------------------------------------------------------------------
LAYOVER_FRAC = 0.10
LAYOVER_MIN = 120.0
H_MAX_POLICY = 1200.0     # policy headway cap (20 min)
H_MIN_POLICY = 150.0


def measure_cycles(bus_recs, plan):
    """cycle_time = measured mean round-trip duration (includes dwell + traffic
    delay).

    Layover rule (stated once, applied everywhere):
        layover_l = max(0.10 * mean_cycle, 120 s, p90_cycle - mean_cycle)
    and the planning cycle is  C_l = mean_cycle + layover_l.

    The third term is not cosmetic.  With h = C/N, the number of buses actually
    in service at any instant is about (realised cycle)/h, so a layover sized
    only on the MEAN cycle lets cycle-time variance push the realised fleet
    above the budgeted one -- measured here as 25-27 concurrent buses against a
    24-bus budget before the p90 term was added.
    """
    by = defaultdict(list)
    for r in bus_recs:
        if r["complete"]:
            by[r["line"]].append(r["duration"])
    out = {}
    for L in plan.lines:
        v = sorted(by.get(L.id, []))
        if not v:
            out[L.id] = dict(n=0, cycle=None, layover=None, C=None)
            continue
        m = sum(v) / len(v)
        sd = (sum((x - m) ** 2 for x in v) / len(v)) ** 0.5 if len(v) > 1 else 0.0
        p90 = v[min(len(v) - 1, int(math.ceil(0.90 * len(v))) - 1)]
        lay = max(LAYOVER_FRAC * m, LAYOVER_MIN, p90 - m)
        out[L.id] = dict(n=len(v), cycle=m, cycle_sd=sd, cycle_p90=p90,
                         cycle_max=v[-1], layover=lay, C=m + lay)
    return out


def max_concurrent(bus_recs, line=None):
    ev = []
    for r in bus_recs:
        if line and r["line"] != line: continue
        a = r["arrival"] if r["complete"] else SIM_END
        ev.append((r["depart"], 1)); ev.append((a, -1))
    ev.sort()
    cur = mx = 0
    for t, d in ev:
        cur += d; mx = max(mx, cur)
    return mx


def audit_budget(plan, bus_recs):
    """Independent verification: required vehicles ceil(C/h) vs measured max
    concurrent distinct bus vehicles actually in service."""
    rows = []
    for L in plan.lines:
        C = plan.cycles.get(L.id)
        h = plan.headway(L.id)
        req = math.ceil(C / h) if C else None
        obs = max_concurrent(bus_recs, L.id)
        rows.append(dict(line=L.id, buses_allocated=L.buses, headway=h,
                         C_assumed=C, required_ceil=req, observed_max_concurrent=obs))
    return rows


# ----------------------------------------------------------------------------
# schedule calibration
# ----------------------------------------------------------------------------
def calibrate_run_speed(plan, net, workdir, seed=1):
    """Measure the UNCONGESTED round-trip running speed of each line by running
    the buses alone (no cars, no passengers) against a deliberately unattainable
    timetable, so `until` cannot bind.  The returned speeds are what the
    published timetable is then built from."""
    sd = ensure(os.path.join(workdir, f"_cal_{plan.name}"))
    stops = plan_stops(plan, net)
    add = os.path.join(sd, "busstops.add.xml"); write_busstops(stops, add)
    ptv = os.path.join(sd, "pt.rou.xml")
    fast = ServicePlan(plan.name, [Line(l.id, l.nodes, 1, 0.0) for l in plan.lines])
    plan_stops(fast, net)
    write_pt_vehicles(fast, net, stops, ptv, run_speed={l.id: 20.0 for l in fast.lines},
                      dwell=DWELL_MIN)
    comp = dict(add=add, ptv=ptv)
    res = simulate(net, comp, None, [], os.path.join(sd, "run"), seed=seed,
                   stop_output=True)
    recs = parse_bus_tripinfo(res["tripinfo"])
    by = defaultdict(list)
    for r in recs:
        if r["complete"]:
            by[r["line"]].append(r["duration"])
    speeds, info = {}, {}
    for L in plan.lines:
        v = by.get(L.id, [])
        dists, total_len = stop_distances(L, net)
        nstop = len(L._stopseq)
        if not v:
            speeds[L.id] = 7.5
            continue
        cyc = sum(v) / len(v)
        moving = max(60.0, cyc - nstop * DWELL_MIN)
        speeds[L.id] = total_len / moving
        info[L.id] = dict(free_cycle=cyc, length=total_len, n_stops=nstop,
                          run_speed=speeds[L.id])
    return speeds, info


def teleports_from_summary(summary):
    """summary@teleports is CUMULATIVE -- read the last step, never sum
    (see validate-congested-scenario-results-against-teleport-artifacts)."""
    last = 0
    if not summary or not os.path.exists(summary):
        return None
    for ev, el in ET.iterparse(summary, events=("end",)):
        if el.tag == "step":
            try:
                last = max(last, int(el.get("teleports", 0)))
            except (TypeError, ValueError):
                pass
            el.clear()
    return last
