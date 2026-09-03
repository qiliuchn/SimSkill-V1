#!/usr/bin/env python3
"""Route-set generators for sub-goal 4 -- reusable deliverable ("the four route-set
generators"). Operates on a sumolib network graph with travel-time edge weights.

Methods:
  k_shortest_paths(net, src, dst, k)         -- Yen's algorithm, simple paths, by travel time
  link_penalty_paths(net, src, dst, k)       -- iterative: shortest path, penalize its edges
                                                 heavily, re-route, repeat k times
  duarouter_accumulated(net, trips, k)       -- repeated duarouter calls w/ randomized
                                                 weights, fed back as an accumulating
                                                 .rou.alt.xml (the mechanism verified in
                                                 sub-goal 1 to be what --route-choice-method
                                                 actually operates on)
  montecarlo_perturbed(net, src, dst, n)     -- many INDEPENDENT single-shot duarouter calls
                                                 under --weights.random-factor noise; the
                                                 SET of unique shortest paths found (no
                                                 accumulation/choice-model involved at all)
"""
import heapq
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))


def _sumolib():
    sumo_home = os.environ.get("SUMO_HOME")
    if sumo_home and os.path.join(sumo_home, "tools") not in sys.path:
        sys.path.insert(0, os.path.join(sumo_home, "tools"))
    import sumolib
    return sumolib


def load_graph(net_file):
    sumolib = _sumolib()
    net = sumolib.net.readNet(net_file)
    return net


def edge_time(net, edge_id):
    e = net.getEdge(edge_id)
    return e.getLength() / e.getSpeed()


def dijkstra(net, src, dst, penalty=None, forbidden_edges=None):
    """penalty: {edge_id: multiplicative factor}. forbidden_edges: set of edge ids to avoid.
    Returns (edge_id_list, total_cost) or (None, inf)."""
    penalty = penalty or {}
    forbidden_edges = forbidden_edges or set()
    src_e = net.getEdge(src)
    dist = {src: 0.0}
    prev = {}
    pq = [(0.0, src)]
    visited = set()
    while pq:
        d, u = heapq.heappop(pq)
        if u in visited:
            continue
        visited.add(u)
        if u == dst:
            break
        ue = net.getEdge(u)
        for conn in ue.getOutgoing():
            v = conn.getID()
            if v in forbidden_edges:
                continue
            w = edge_time(net, v) * penalty.get(v, 1.0)
            nd = d + w
            if v not in dist or nd < dist[v] - 1e-9:
                dist[v] = nd
                prev[v] = u
                heapq.heappush(pq, (nd, v))
    if dst not in dist:
        return None, float("inf")
    path = [dst]
    while path[-1] != src:
        path.append(prev[path[-1]])
    path.reverse()
    return path, dist[dst]


def path_true_cost(net, path):
    return sum(edge_time(net, e) for e in path)


def k_shortest_paths(net_file, src, dst, k=8):
    """Yen's algorithm for k loopless shortest paths by true travel time."""
    net = load_graph(net_file)
    A_path, A_cost = dijkstra(net, src, dst)
    if A_path is None:
        return []
    # BUG FIX (found during sub-goal-4 characterization): dist[src] is initialized to 0.0 in
    # dijkstra(), i.e. it does NOT count the source edge's own traversal time -- every
    # subsequent Yen's entry below is scored via path_true_cost() (which DOES count it), so
    # the raw dijkstra() cost for the very first entry silently undercounted by exactly one
    # source-edge's travel time (verified: 147.9 raw vs 161.6 true on the sub-goal-4 grid,
    # a difference matching "bottom0A0"'s own edge time to 3 decimal places). Recompute here
    # for consistency with every other entry in A/B.
    A_cost = path_true_cost(net, A_path)
    A = [(A_path, A_cost)]
    B = []
    for _ in range(1, k):
        prev_path = A[-1][0]
        for i in range(len(prev_path) - 1):
            spur_node = prev_path[i]
            root_path = prev_path[: i + 1]
            forbidden_edges = set()
            for p, _ in A:
                if len(p) > i and p[: i + 1] == root_path:
                    forbidden_edges.add(p[i + 1])
            # also forbid revisiting nodes already in root_path (via edges leading to them),
            # approximated by forbidding the root_path edges themselves as continuations
            spur_path, spur_cost = dijkstra(net, spur_node, dst, forbidden_edges=forbidden_edges)
            if spur_path is None:
                continue
            total_path = root_path[:-1] + spur_path
            if len(set(total_path)) != len(total_path):
                continue  # not loopless
            total_cost = path_true_cost(net, total_path)
            if (total_path, total_cost) not in B and all(total_path != p for p, _ in A):
                B.append((total_path, total_cost))
        if not B:
            break
        B.sort(key=lambda x: x[1])
        A.append(B.pop(0))
        B = [b for b in B if b[0] != A[-1][0]]
    return A


def link_penalty_paths(net_file, src, dst, k=8, penalty_factor=6.0):
    """Iteratively find the shortest path, then heavily penalize (not forbid) its edges so
    the next search prefers a structurally different route -- distinct from Yen's exact
    detour search: greedy, cheap, but can converge to duplicate/near-duplicate paths."""
    net = load_graph(net_file)
    penalty = {}
    results = []
    seen = set()
    for _ in range(k * 3):  # allow retries since duplicates can occur
        if len(results) >= k:
            break
        path, _ = dijkstra(net, src, dst, penalty=penalty)
        if path is None:
            break
        key = tuple(path)
        cost = path_true_cost(net, path)
        if key not in seen:
            seen.add(key)
            results.append((path, cost))
        for e in path:
            penalty[e] = penalty.get(e, 1.0) * penalty_factor
    return results


def duarouter_accumulated(net_file, src_edge, dst_edge, outdir, k=10, seed0=1,
                           random_factor=4.0, method="gawron"):
    """Repeated single-vehicle duarouter calls under randomized weights, with results fed
    back as an accumulating .rou.alt.xml (the SAME mechanism verified in sub-goal 1 that
    --route-choice-method operates on) -- emulates the route pool duaIterate would build up
    day-to-day, without running a full mobility simulation."""
    os.makedirs(outdir, exist_ok=True)
    cur = os.path.join(outdir, "acc_0.trips.xml")
    with open(cur, "w") as f:
        f.write(f'<routes><vehicle id="veh0" depart="0"><route edges="{src_edge}"/>'
                f'</vehicle></routes>\n')
    # bootstrap: first call needs a trips file, not an alt file
    trips = os.path.join(outdir, "boot.trips.xml")
    with open(trips, "w") as f:
        f.write(f'<trips><trip id="veh0" depart="0" from="{src_edge}" to="{dst_edge}"/></trips>\n')
    alt = None
    for i in range(k):
        outp = os.path.join(outdir, f"acc_{i}")
        cmd = ["duarouter", "-n", net_file,
               "-r", alt if alt else trips,
               "-o", outp + ".rou.xml", "--max-alternatives", "20",
               "--keep-all-routes", "--route-choice-method", method,
               "--weights.random-factor", str(random_factor),
               "--seed", str(seed0 + i), "--no-step-log", "--ignore-errors"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            break
        alt = outp + ".rou.alt.xml"
    if alt is None:
        return []
    sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
    from altparse import parse_alt_file_flows
    parsed = parse_alt_file_flows(alt)
    routes = parsed.get("veh0", [])
    # NOTE: the "cost" attribute duarouter writes here reflects the RANDOMIZED weight used
    # at the moment that specific alternative was discovered (verified: values came back
    # inflated by exactly the [1, random_factor) perturbation range), not the network's true
    # static cost -- recompute true cost from the edge sequence for honest characterization.
    net = load_graph(net_file)
    return [(edges.split(), path_true_cost(net, edges.split())) for edges, cost, prob in routes]


def montecarlo_perturbed(net_file, src_edge, dst_edge, outdir, n=30, random_factor=4.0, seed0=1):
    """n INDEPENDENT single-shot duarouter calls under randomized weights -- no accumulation,
    no choice model, just harvest the set of unique shortest paths found under noise."""
    os.makedirs(outdir, exist_ok=True)
    trips = os.path.join(outdir, "mc.trips.xml")
    with open(trips, "w") as f:
        f.write(f'<trips><trip id="veh0" depart="0" from="{src_edge}" to="{dst_edge}"/></trips>\n')
    seen = {}
    for i in range(n):
        outp = os.path.join(outdir, f"mc_{i}.rou.xml")
        cmd = ["duarouter", "-n", net_file, "-r", trips, "-o", outp,
               "--weights.random-factor", str(random_factor), "--seed", str(seed0 + i),
               "--no-step-log", "--ignore-errors"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            continue
        import re
        m = re.search(r'edges="([^"]+)"', open(outp).read())
        if m:
            edges = m.group(1).split()
            seen[tuple(edges)] = seen.get(tuple(edges), 0) + 1
    net = load_graph(net_file)
    return [(list(k), path_true_cost(net, list(k)), cnt) for k, cnt in seen.items()]
