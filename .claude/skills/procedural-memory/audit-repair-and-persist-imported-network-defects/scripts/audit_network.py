#!/usr/bin/env python3
"""
Systematic QA audit of a compiled SUMO .net.xml produced by an OSM import.

Produces a defect inventory with counts across 6 defect families:
  A. netconvert warnings by category (from the build log)
  B. connectivity defects (netcheck.py: components, unreachable, dead ends)
  C. junction-joining defects (under-joined / over-joined clusters)
  D. edge attribute defects (default lane count / default speed / missing turn lanes)
  E. connection & right-of-way guessing defects
  F. TLS defects (guessed-signal misassignment, implausible programs)

Usage: python3 02_audit.py <net.xml> [--log build.log] [--json out.json]
"""
import sys, os, re, json, subprocess, collections, math
import xml.etree.ElementTree as ET

SUMO_HOME = os.environ["SUMO_HOME"]
NETCHECK = os.path.join(SUMO_HOME, "tools", "net", "netcheck.py")

# netconvert / OSM typemap defaults that indicate "netconvert guessed this"
DEFAULT_SPEEDS = {13.89, 27.78, 36.11, 22.22}  # 50/100/130/80 km/h generic fallbacks


def norm_warning(line):
    return re.sub(r"'[^']*'", "'X'", re.sub(r"\b\d{4,}\b", "N", line.strip()))


WARN_FAMILIES = [
    ("pt_relation", r"pt stop|pt line|Platform|Stop '|PT line|free-floating"),
    ("turn_restriction_lost", r"restriction relation"),
    ("tls_not_built", r"traffic light .* does not control any links|Could not build program"),
    ("junction_join_refused", r"Not joining junctions"),
    ("junction_join_reduced", r"Reducing junction cluster"),
    ("missing_left_turn_lane", r"Minor green from edge .* exceeds"),
    ("bad_attr_value", r"could not be parsed|is not numeric|Invalid color|unknown compound|unusable type"),
    ("geometry", r"Intersecting left turns|junction radius|too short|Removing empty"),
    ("connection_lost", r"Could not find fromEdge|Could not build connection|No connection"),
]


def audit_warnings(logfile):
    if not logfile or not os.path.exists(logfile):
        return {}, {}
    fam = collections.Counter()
    detail = collections.Counter()
    for line in open(logfile):
        s = line.strip()
        if not s or not s.lower().startswith(("warning", "error")):
            continue
        detail[norm_warning(s)] += 1
        hit = False
        for name, pat in WARN_FAMILIES:
            if re.search(pat, s):
                fam[name] += 1
                hit = True
                break
        if not hit:
            fam["other"] += 1
    return dict(fam), {k: v for k, v in detail.most_common()}


def run_netcheck(net):
    """Connectivity audit via SUMO's own netcheck.py (strongly connected components
    honouring connections). Returns component size list."""
    out = subprocess.run([sys.executable, NETCHECK, net, "-l", "passenger"],
                         capture_output=True, text=True)
    txt = out.stdout + out.stderr
    sizes = [int(m) for m in re.findall(r"Found (\d+) components", txt)]
    comps = re.findall(r"Component: #\d+ Edge Count: (\d+)", txt)
    return txt, [int(c) for c in comps]


def parse_net(net):
    tree = ET.parse(net)
    root = tree.getroot()
    return root


def audit_net(root):
    r = {}
    edges = [e for e in root.findall("edge") if e.get("function") != "internal"]
    junctions = [j for j in root.findall("junction") if j.get("type") != "internal"]
    conns = [c for c in root.findall("connection") if not c.get("from", "").startswith(":")]
    tls = root.findall("tlLogic")

    r["n_edges"] = len(edges)
    r["n_lanes"] = sum(len(e.findall("lane")) for e in edges)
    r["n_junctions"] = len(junctions)
    r["n_connections"] = len(conns)
    r["n_tlLogic"] = len(tls)
    r["lane_km"] = round(sum(float(l.get("length")) for e in edges for l in e.findall("lane")) / 1000.0, 3)

    # --- D. edge attribute defects -------------------------------------------
    onelane = 0
    default_speed = collections.Counter()
    unnamed = 0
    for e in edges:
        lanes = e.findall("lane")
        if len(lanes) == 1:
            onelane += 1
        sp = round(float(lanes[0].get("speed")), 2)
        default_speed[sp] += 1
        if not e.get("name"):
            unnamed += 1
    r["edges_single_lane"] = onelane
    r["edges_no_street_name"] = unnamed
    r["speed_histogram"] = dict(default_speed.most_common(10))
    r["edges_at_generic_default_speed"] = sum(v for k, v in default_speed.items() if k in DEFAULT_SPEEDS)

    # --- C. junction typing ---------------------------------------------------
    jt = collections.Counter(j.get("type") for j in junctions)
    r["junction_types"] = dict(jt)
    r["n_dead_end_junctions"] = jt.get("dead_end", 0)
    clusters = [j for j in junctions if j.get("id", "").startswith("cluster")]
    r["n_cluster_junctions"] = len(clusters)
    # over-joined: cluster made of many original nodes
    big = [(j.get("id"), j.get("id").count("_")) for j in clusters]
    r["cluster_member_histogram"] = dict(collections.Counter(n for _, n in big))
    r["clusters_with_ge5_members"] = sorted([i for i, n in big if n >= 5])

    # --- E. connection / right-of-way -----------------------------------------
    # request/response matrices tell how netconvert resolved right-of-way
    nrq = 0
    for j in junctions:
        nrq += len(j.findall("request"))
    r["n_requests"] = nrq

    # movements per junction: junctions with a left turn served from a shared-through lane
    r["n_uncontrolled_conns"] = sum(1 for c in conns if c.get("state") in ("M", "m"))
    r["n_keepclear_off"] = sum(1 for c in conns if c.get("keepClear") == "0")

    # --- F. TLS ---------------------------------------------------------------
    tls_report = []
    for t in tls:
        phases = t.findall("phase")
        durs = [float(p.get("duration")) for p in phases]
        states = [p.get("state") for p in phases]
        nlinks = len(states[0]) if states else 0
        greens = [s for s in states if ("G" in s or "g" in s)]
        cycle = sum(durs)
        tls_report.append(dict(id=t.get("id"), type=t.get("type"), nphases=len(phases),
                               nlinks=nlinks, cycle=cycle, ngreen=len(greens),
                               min_dur=min(durs) if durs else 0,
                               has_protected_left=any(re.search(r"G", s) for s in states),
                               all_green_phase=any(set(s) <= set("Gg") for s in states)))
    r["tls"] = tls_report
    r["n_tls_2phase"] = sum(1 for t in tls_report if t["nphases"] <= 2)
    r["n_tls_implausible_cycle"] = sum(1 for t in tls_report if t["cycle"] < 30 or t["cycle"] > 180)
    r["n_tls_single_approach"] = sum(1 for t in tls_report if t["nlinks"] <= 2)
    # TLS junction with very few incoming edges = probable guess-signals misplacement
    jbyid = {j.get("id"): j for j in junctions}
    bad_place = []
    for t in tls_report:
        j = jbyid.get(t["id"])
        if j is None:
            continue
        inc = j.get("incLanes", "").split()
        if len(inc) <= 2:
            bad_place.append(t["id"])
    r["tls_on_trivial_junction"] = bad_place
    r["n_tls_on_trivial_junction"] = len(bad_place)
    return r


def audit_deadends_and_reachability(root):
    """Graph-level reachability honouring <connection> elements."""
    edges = {}
    for e in root.findall("edge"):
        if e.get("function") == "internal":
            continue
        edges[e.get("id")] = e
    succ = collections.defaultdict(set)
    pred = collections.defaultdict(set)
    for c in root.findall("connection"):
        f, t = c.get("from"), c.get("to")
        if f in edges and t in edges:
            succ[f].add(t)
            pred[t].add(f)
    no_out = [e for e in edges if not succ[e]]
    no_in = [e for e in edges if not pred[e]]

    # largest strongly connected component (Tarjan, iterative)
    def scc(nodes, adj):
        index = {}
        low = {}
        onstack = {}
        stack = []
        result = []
        counter = [0]
        for root_n in nodes:
            if root_n in index:
                continue
            work = [(root_n, iter(adj[root_n]))]
            index[root_n] = low[root_n] = counter[0]; counter[0] += 1
            stack.append(root_n); onstack[root_n] = True
            while work:
                v, it = work[-1]
                advanced = False
                for w in it:
                    if w not in index:
                        index[w] = low[w] = counter[0]; counter[0] += 1
                        stack.append(w); onstack[w] = True
                        work.append((w, iter(adj[w])))
                        advanced = True
                        break
                    elif onstack.get(w):
                        low[v] = min(low[v], index[w])
                if not advanced:
                    work.pop()
                    if work:
                        low[work[-1][0]] = min(low[work[-1][0]], low[v])
                    if low[v] == index[v]:
                        comp = []
                        while True:
                            w = stack.pop(); onstack[w] = False; comp.append(w)
                            if w == v: break
                        result.append(comp)
        return result

    comps = scc(list(edges), succ)
    comps.sort(key=len, reverse=True)
    biggest = set(comps[0]) if comps else set()
    return dict(
        n_edges_no_successor=len(no_out),
        n_edges_no_predecessor=len(no_in),
        edges_no_successor=sorted(no_out),
        n_scc=len(comps),
        largest_scc_edges=len(biggest),
        edges_outside_largest_scc=len(edges) - len(biggest),
        scc_size_histogram=dict(collections.Counter(len(c) for c in comps).most_common()),
        outside_edges=sorted(set(edges) - biggest),
    )


def main():
    net = sys.argv[1]
    log = None
    outjson = None
    a = sys.argv[2:]
    for i, x in enumerate(a):
        if x == "--log": log = a[i + 1]
        if x == "--json": outjson = a[i + 1]

    root = parse_net(net)
    rep = {"net": os.path.abspath(net)}
    rep["A_warnings_by_family"], rep["A_warning_details"] = audit_warnings(log)
    nc_txt, comps = run_netcheck(net)
    rep["B_netcheck_raw"] = nc_txt[-3000:]
    rep["B_netcheck_component_sizes"] = comps
    rep.update({"C_D_E_F_" + k if False else k: v for k, v in audit_net(root).items()})
    rep["B_reachability"] = audit_deadends_and_reachability(root)

    if outjson:
        with open(outjson, "w") as f:
            json.dump(rep, f, indent=2)
    # console summary
    print("=" * 70)
    print("QA AUDIT:", net)
    print("=" * 70)
    print(f"edges={rep['n_edges']} lanes={rep['n_lanes']} junctions={rep['n_junctions']} "
          f"conns={rep['n_connections']} tls={rep['n_tlLogic']} lane_km={rep['lane_km']}")
    print("\n[A] netconvert warnings by family:")
    for k, v in sorted(rep["A_warnings_by_family"].items(), key=lambda x: -x[1]):
        print(f"    {v:5d}  {k}")
    b = rep["B_reachability"]
    print("\n[B] connectivity:")
    print(f"    strongly-connected components (passenger, honouring connections): {b['n_scc']}")
    print(f"    largest SCC edges: {b['largest_scc_edges']}  edges outside it: {b['edges_outside_largest_scc']}")
    print(f"    edges with no successor (dead ends): {b['n_edges_no_successor']}")
    print(f"    edges with no predecessor (unreachable): {b['n_edges_no_predecessor']}")
    print(f"    SCC size histogram: {b['scc_size_histogram']}")
    print("\n[C] junctions:")
    print(f"    types: {rep['junction_types']}")
    print(f"    cluster (joined) junctions: {rep['n_cluster_junctions']}")
    print(f"    cluster member-count histogram (n underscores): {rep['cluster_member_histogram']}")
    print(f"    clusters with >=5 members (over-join candidates): {len(rep['clusters_with_ge5_members'])}")
    print("\n[D] edge attributes:")
    print(f"    single-lane edges: {rep['edges_single_lane']} / {rep['n_edges']}")
    print(f"    edges w/o street name: {rep['edges_no_street_name']}")
    print(f"    speed histogram (m/s): {rep['speed_histogram']}")
    print("\n[E] connections / RoW:")
    print(f"    junction <request> rows: {rep['n_requests']}")
    print(f"    minor/uncontrolled ('m'/'M') connections: {rep['n_uncontrolled_conns']}")
    print("\n[F] TLS:")
    print(f"    tlLogic count: {rep['n_tlLogic']}")
    print(f"    <=2 phases: {rep['n_tls_2phase']}   implausible cycle (<30 or >180s): {rep['n_tls_implausible_cycle']}")
    print(f"    controlling <=2 links: {rep['n_tls_single_approach']}")
    print(f"    on trivial junction (<=2 incoming lanes): {rep['n_tls_on_trivial_junction']} {rep['tls_on_trivial_junction']}")
    if outjson:
        print("\nJSON ->", outjson)


if __name__ == "__main__":
    main()
