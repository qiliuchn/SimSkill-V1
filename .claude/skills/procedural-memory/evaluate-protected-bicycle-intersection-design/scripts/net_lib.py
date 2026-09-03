"""
Shared plain-XML network builder for the bicycle-intersection-design study.
4-leg signalized intersection, arms N,E,S,W, node "center".
Turn mapping (clockwise arm order N,E,S,W):
  through(A) = opposite(A);  right(A) = prev(A);  left(A) = next(A)
"""
import os, subprocess, shutil, math, xml.etree.ElementTree as ET

ARMS = ["N", "E", "S", "W"]
ANGLE = {"N": 90, "E": 0, "S": 270, "W": 180}  # degrees, standard math convention, for node placement

def idx(a): return ARMS.index(a)
def opposite(a): return ARMS[(idx(a) + 2) % 4]
def right_of(a):  return ARMS[(idx(a) - 1) % 4]   # right turn destination
def left_of(a):   return ARMS[(idx(a) + 1) % 4]   # left turn destination

def arm_xy(a, dist):
    ang = math.radians(ANGLE[a])
    return round(dist * math.cos(ang), 3), round(dist * math.sin(ang), 3)

def find_binary(name):
    p = shutil.which(name)
    if p:
        return p
    # SUMO_HOME/bin
    sh = os.environ.get("SUMO_HOME")
    if sh:
        cand = os.path.join(sh, "bin", name)
        if os.path.exists(cand):
            return cand
    # macOS framework fallback next to `sumo`
    sumo_p = shutil.which("sumo")
    if sumo_p:
        cand = os.path.join(os.path.dirname(sumo_p), name)
        if os.path.exists(cand):
            return cand
    raise FileNotFoundError(name)

NETCONVERT = find_binary("netconvert")
SUMO_BIN = find_binary("sumo")


def perp_offset(p0, p1, frac, dist):
    """Point at fraction `frac` along p0->p1, offset perpendicular by `dist` (m, +left of travel dir)."""
    x0, y0 = p0; x1, y1 = p1
    x = x0 + (x1 - x0) * frac
    y = y0 + (y1 - y0) * frac
    dx, dy = x1 - x0, y1 - y0
    L = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / L, dx / L  # left-hand normal
    return (round(x + nx * dist, 3), round(y + ny * dist, 3))


class VariantSpec:
    """Config for one network variant."""
    def __init__(self, name, bike_mode, radius, setback_m=0.0, arm_length=150.0,
                 veh_speed=13.89, bike_speed=13.89, lanes_w=3.2):
        self.name = name
        self.bike_mode = bike_mode        # "mixed" | "dedicated"
        self.radius = radius              # junction corner radius (m)
        self.setback_m = setback_m        # lateral push applied to bike-through internal shape (m); 0 = none
        self.arm_length = arm_length
        self.veh_speed = veh_speed
        self.bike_speed = bike_speed
        self.lanes_w = lanes_w


def write_nod_xml(path, spec, extra_center_attrs=""):
    lines = ['<nodes>']
    lines.append(f'  <node id="center" x="0" y="0" type="traffic_light" tl="center" radius="{spec.radius}"{extra_center_attrs}/>')
    for a in ARMS:
        x, y = arm_xy(a, spec.arm_length)
        lines.append(f'  <node id="far_{a}" x="{x}" y="{y}" type="priority"/>')
    lines.append('</nodes>')
    with open(path, "w") as f:
        f.write("\n".join(lines))


def write_edg_xml(path, spec):
    lines = ['<edges>']
    if spec.bike_mode == "mixed":
        for a in ARMS:
            lines.append(f'  <edge id="in_{a}" from="far_{a}" to="center" numLanes="1" speed="{spec.veh_speed}">')
            lines.append(f'    <lane index="0" allow="passenger bicycle bus"/>')
            lines.append('  </edge>')
            lines.append(f'  <edge id="out_{a}" from="center" to="far_{a}" numLanes="1" speed="{spec.veh_speed}">')
            lines.append(f'    <lane index="0" allow="passenger bicycle bus"/>')
            lines.append('  </edge>')
    else:  # dedicated: lane0=bike-only (rightmost/curb), lane1=vehicle-only
        for a in ARMS:
            lines.append(f'  <edge id="in_{a}" from="far_{a}" to="center" numLanes="2" speed="{spec.veh_speed}">')
            lines.append(f'    <lane index="0" allow="bicycle" speed="{spec.bike_speed}"/>')
            lines.append(f'    <lane index="1" disallow="bicycle"/>')
            lines.append('  </edge>')
            lines.append(f'  <edge id="out_{a}" from="center" to="far_{a}" numLanes="2" speed="{spec.veh_speed}">')
            lines.append(f'    <lane index="0" allow="bicycle" speed="{spec.bike_speed}"/>')
            lines.append(f'    <lane index="1" disallow="bicycle"/>')
            lines.append('  </edge>')
    lines.append('</edges>')
    with open(path, "w") as f:
        f.write("\n".join(lines))


def write_con_xml(path, spec, bike_through_shapes=None):
    """bike_through_shapes: dict approach -> shape string override for the bike-through connection (2nd pass only)."""
    bike_through_shapes = bike_through_shapes or {}
    lines = ['<connections>']
    for a in ARMS:
        t, r, l = opposite(a), right_of(a), left_of(a)
        if spec.bike_mode == "mixed":
            lines.append(f'  <connection from="in_{a}" to="out_{t}" fromLane="0" toLane="0"/>')
            lines.append(f'  <connection from="in_{a}" to="out_{r}" fromLane="0" toLane="0"/>')
            lines.append(f'  <connection from="in_{a}" to="out_{l}" fromLane="0" toLane="0"/>')
        else:
            shp = bike_through_shapes.get(a)
            shp_attr = f' shape="{shp}"' if shp else ''
            lines.append(f'  <connection from="in_{a}" to="out_{t}" fromLane="0" toLane="0"{shp_attr}/>')  # bike through
            lines.append(f'  <connection from="in_{a}" to="out_{t}" fromLane="1" toLane="1"/>')  # veh through
            lines.append(f'  <connection from="in_{a}" to="out_{r}" fromLane="1" toLane="1"/>')  # veh right
            lines.append(f'  <connection from="in_{a}" to="out_{l}" fromLane="1" toLane="1"/>')  # veh left
    lines.append('</connections>')
    with open(path, "w") as f:
        f.write("\n".join(lines))


def run_netconvert(nod, edg, con, out_net, extra_args=None):
    cmd = [NETCONVERT, "-n", nod, "-e", edg, "-x", con,
           "--sidewalks.guess", "--crossings.guess", "--walkingareas",
           "--no-turnarounds", "true",
           "--tls.default-type", "static",
           "--junctions.corner-detail", "5",
           "--offset.disable-normalization", "true",
           "-o", out_net]
    if extra_args:
        cmd += extra_args
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r


def build_variant_net(workdir, tag, spec, extra_netconvert_args=None, bike_through_shapes=None):
    os.makedirs(workdir, exist_ok=True)
    nod = os.path.join(workdir, f"{tag}.nod.xml")
    edg = os.path.join(workdir, f"{tag}.edg.xml")
    con = os.path.join(workdir, f"{tag}.con.xml")
    net = os.path.join(workdir, f"{tag}.net.xml")
    write_nod_xml(nod, spec)
    write_edg_xml(edg, spec)
    write_con_xml(con, spec, bike_through_shapes=bike_through_shapes)
    r = run_netconvert(nod, edg, con, net, extra_args=extra_netconvert_args)
    return net, r


# ---------------- link-map extraction from compiled net ----------------

def approach_of_from_edge(edge_id):
    if edge_id.startswith("in_"):
        return edge_id.split("_", 1)[1]
    return None

def dest_of_to_edge(edge_id):
    if edge_id.startswith("out_"):
        return edge_id.split("_", 1)[1]
    return None

def classify_movement(approach, to_edge):
    dest = dest_of_to_edge(to_edge)
    if dest is None:
        return None
    if dest == opposite(approach):
        return "through"
    if dest == right_of(approach):
        return "right"
    if dest == left_of(approach):
        return "left"
    return None


def parse_linkmap(net_path):
    """Return dict: (approach, movement, vclass_tag) -> linkIndex, plus raw connection list,
    plus crossing info: list of dict(approach, linkIndex, crossingEdges)."""
    tree = ET.parse(net_path)
    root = tree.getroot()
    # need lane->allow info to distinguish bike vs vehicle connections
    lane_allow = {}
    for edge in root.findall("edge"):
        for lane in edge.findall("lane"):
            lane_allow[lane.get("id")] = lane.get("allow"), lane.get("disallow")

    conns = []
    linkmap = {}
    crossings = []
    for c in root.findall("connection"):
        tl = c.get("tl")
        li = c.get("linkIndex")
        frm = c.get("from")
        to = c.get("to")
        if tl != "center" or li is None:
            continue
        li = int(li)
        if frm.startswith("in_"):
            approach = approach_of_from_edge(frm)
            mv = classify_movement(approach, to)
            from_lane_id = f'{frm}_{c.get("fromLane")}'
            allow, disallow = lane_allow.get(from_lane_id, (None, None))
            if allow == "bicycle":
                vtag = "bike"
            elif disallow == "bicycle" or allow is None:
                vtag = "veh"
            else:
                vtag = "mixed"
            linkmap[(approach, mv, vtag)] = li
            conns.append(dict(approach=approach, movement=mv, vtag=vtag, linkIndex=li,
                               fromLane=c.get("fromLane"), toLane=c.get("toLane"),
                               frm=frm, to=to, via=c.get("via"), shape=c.get("shape")))
        elif frm.startswith(":"):
            # crossing / walkingarea internal connection; identify via edge function
            pass
    # crossings: edges with function=crossing carry crossingEdges; find their connection's linkIndex
    crossing_edges = {}
    for edge in root.findall("edge"):
        if edge.get("function") == "crossing":
            crossing_edges[edge.get("id")] = edge.get("crossingEdges", "").split()
    for c in root.findall("connection"):
        tl = c.get("tl")
        li = c.get("linkIndex")
        to = c.get("to")
        if tl != "center" or li is None:
            continue
        if to in crossing_edges:
            crossings.append(dict(linkIndex=int(li), to=to, crossingEdges=crossing_edges[to],
                                   frm=c.get("from")))
    return dict(linkmap=linkmap, connections=conns, crossings=crossings,
                n_links=max([c["linkIndex"] for c in conns] + [c["linkIndex"] for c in crossings], default=-1) + 1)


def get_internal_lane_shape(net_path, via_id):
    tree = ET.parse(net_path)
    root = tree.getroot()
    for edge in root.findall("edge"):
        if edge.get("id") == via_id.rsplit("_", 1)[0] if False else False:
            pass
    # via_id like ":center_3_0" refers to a lane on internal edge ":center_3"
    internal_edge_id = via_id.rsplit("_", 1)[0]
    for edge in root.findall("edge"):
        if edge.get("id") == internal_edge_id:
            for lane in edge.findall("lane"):
                if lane.get("id") == via_id:
                    return lane.get("shape")
    return None


def make_setback_shape(base_shape_str, setback_m, side=-1.0):
    """Bow a 2-point straight internal-lane shape outward to approximate a recessed
    (setback) bike crossing. base_shape_str: 'x0,y0 x1,y1' (netconvert's auto shape).
    side: +-1, direction of the perpendicular push (chosen so it pushes AWAY from the
    adjoining vehicle lane, i.e. toward the outside/curb)."""
    pts = [tuple(map(float, p.split(","))) for p in base_shape_str.split()]
    p0, p1 = pts[0], pts[-1]
    q1 = perp_offset(p0, p1, 0.35, side * setback_m)
    q2 = perp_offset(p0, p1, 0.65, side * setback_m)
    return f"{p0[0]:.2f},{p0[1]:.2f} {q1[0]:.2f},{q1[1]:.2f} {q2[0]:.2f},{q2[1]:.2f} {p1[0]:.2f},{p1[1]:.2f}"


def get_request_foes(net_path):
    """Return dict linkIndex -> dict(response=str, foes=str) from the traffic_light junction's <request> children."""
    tree = ET.parse(net_path)
    root = tree.getroot()
    out = {}
    for junc in root.findall("junction"):
        if junc.get("id") == "center":
            for req in junc.findall("request"):
                out[int(req.get("index"))] = dict(response=req.get("response"), foes=req.get("foes"))
    return out
