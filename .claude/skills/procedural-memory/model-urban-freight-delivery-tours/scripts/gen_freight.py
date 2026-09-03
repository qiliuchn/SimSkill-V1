#!/usr/bin/env python3
"""
Tour-based urban-freight demand generator (parameterised + seeded).

Produces, for a given (network variant, fleet mix, seed, freight scale, night
fraction, bay supply):
  * `.add.xml` with a containerStop at every delivery address and at both depots
  * `.rou.xml` with
      - one <container> per parcel  (waiting stage at the depot + <transport> stage
        to the delivery containerStop, addressed to a named vehicle)
      - one freight <vehicle> per TOUR, with an explicit edge route built by
        concatenating vClass-aware shortest paths, and an ordered <stop> chain
  * a JSON ledger with the full per-tour plan, unroutable legs and unservable
    addresses (raw material for deliverable (c) and for H7)

Demand paradigms
  tour  -- multi-stop tours (nearest-neighbour construction + 2-opt), capacity- AND
           time-budget limited
  trip  -- the standard shortcut: one independent depot->stop->depot truck trip per
           delivery, SAME total parcel count, same vTypes, same depot assignment

OPERATOR ADAPTATION.  Tours are planned against the arm's OWN network.  An address is
assigned the heaviest vClass that can actually complete a ROUND TRIP
depot->address->depot at one and the same depot -- so an address whose street bans
`truck`, AND an address whose street nominally permits `truck` but whose truck
sub-network is fragmented, are BOTH re-assigned to a van tour (what a real carrier
would do).  Only an address that no permitted freight vClass can round-trip is
unservable -- that is H7's reachability failure, and it is recorded, never silently
dropped.  [Fixed in attempt 2: the first version chose the vClass from the edge
permission alone and never retried the exempt class, which manufactured service
failures under partial `hgv` bans.  See scripts/diag_vclass_fallback.py.]

VERIFIED SUMO CONTAINER SEMANTICS (see outputs/probe/PROBE_FINDINGS.md):
  * `<transport from="edge" .../>` alone NEVER gets picked up -- silently.  A
    container needs an explicit `<stop containerStop=.../>` waiting stage.
  * route files MUST be sorted by depart time or SUMO silently ignores elements.
  * loading/unloading BLOCKS the vehicle: effective dwell = max(authored duration,
    loadingDuration * nContainers).  loadingDuration is set to 1 s here so the
    authored, parcel-count-dependent dwell governs.
  * containerCapacity is enforced SILENTLY.
"""
import os, sys, json, math, random, argparse
from common import *   # noqa
import sumolib

DEPOT_EDGES = ["J03_J04", "J63_J62"]
N_ADDRESSES = 120
STOP_LEN = 25.0
MAX_STOPS_PER_TOUR = 8            # time-budget feasible inside a 1 h window
BASE_NET = os.path.join(NET, "d_strict_0.net.xml")

_NET_CACHE = {}


def getnet(f):
    if f not in _NET_CACHE:
        _NET_CACHE[f] = sumolib.net.readNet(f)
    return _NET_CACHE[f]


# --------------------------------------------------------------- addresses --
def choose_addresses(seed=20260803):
    import build_network as bn
    net = getnet(BASE_NET)
    locs = list(bn.local_edges())
    rng = random.Random(seed)
    rng.shuffle(locs)
    addrs, per_edge, idx = [], {}, 0
    while len(addrs) < N_ADDRESSES:
        e = locs[idx % len(locs)]
        k = per_edge.get(e, 0)
        L = net.getEdge(e).getLength()
        if k >= 2 or L < 2 * STOP_LEN + 40:
            idx += 1
            continue
        start = 25.0 + k * (L - 70.0) / 2.0
        start = max(10.0, min(start, L - STOP_LEN - 10.0))
        addrs.append(dict(id="addr%03d" % len(addrs), edge=e, lane=e + "_0",
                          startPos=round(start, 1), endPos=round(start + STOP_LEN, 1),
                          parcels=rng.randint(1, 8)))
        per_edge[e] = k + 1
        idx += 1
    return addrs


def dwell_seconds(parcels, rng):
    mu = 55.0 + 28.0 * parcels
    return int(max(60, min(300, round(rng.gauss(mu, 0.18 * mu)))))


# ------------------------------------------------------------- sequencing ---
def nn_2opt(depot_edge, stop_edges, D, rng, n_restarts=3):
    def cost(order):
        c = D[(depot_edge, order[0])]
        for a, b in zip(order, order[1:]):
            c += D[(a, b)]
        return c + D[(order[-1], depot_edge)]

    best, bestc = None, float("inf")
    for r in range(n_restarts):
        remaining, cur, order = list(stop_edges), depot_edge, []
        while remaining:
            if r == 0:
                nxt = min(remaining, key=lambda e: D[(cur, e)])
            else:
                nxt = rng.choice(sorted(remaining, key=lambda e: D[(cur, e)])[:2])
            order.append(nxt); remaining.remove(nxt); cur = nxt
        improved = True
        while improved:
            improved = False
            base = cost(order)
            for i in range(len(order) - 1):
                for k in range(i + 1, len(order)):
                    new = order[:i] + order[i:k + 1][::-1] + order[k + 1:]
                    c = cost(new)
                    if c < base - 1e-6:
                        order, base, improved = new, c, True
        c = cost(order)
        if c < bestc:
            best, bestc = order, c
    return best, bestc


def _pairD(net, edges, vClass):
    D = {}
    for a in edges:
        ea = net.getEdge(a)
        for b in edges:
            if a == b:
                D[(a, b)] = 0.0
                continue
            p, c = net.getShortestPath(ea, net.getEdge(b), vClass=vClass)
            D[(a, b)] = float("inf") if p is None else c
    return D


# --------------------------------------------------------------- planning ---
def plan_tours(net_file, addrs, fleet_mix, seed, rep=0, stop_caps=None):
    """Plan tours against THIS arm's network (operator adaptation)."""
    net = getnet(net_file)
    rng = random.Random(seed * 1000003 + rep * 97 + 11)

    reach = {}
    for a in addrs:
        e = net.getEdge(a["edge"])
        reach[a["id"]] = {vc: e.allows(vc) for vc in ("truck", "delivery")}

    # OPERATOR ADAPTATION, done properly (fixed in attempt 2).
    #
    # An address is assigned the HEAVIEST vClass that can actually complete a ROUND
    # TRIP depot -> address -> depot at the SAME depot.  Edge-level permission is
    # only the first screen: a `truck`-permitted address can still sit behind a
    # fragmented truck sub-network, and a real carrier would then simply send a van.
    # The previous version picked the vClass from the edge permission alone and
    # declared the address unservable the moment THAT class failed to route -- which
    # under a partial `hgv` ban (trucks banned, vans exempt everywhere) invented
    # service failures for addresses a van reaches without difficulty.
    #
    # THREE distinct reachability failure modes are separated here (H7), and are
    # only recorded once EVERY permitted vClass has been tried:
    #   banned   -- the address edge itself disallows every freight vClass
    #   no-path  -- edge legal but no legal inbound route from either depot, for any
    #               permitted vClass
    #   trap     -- a legal route IN exists for some permitted vClass but NO legal
    #               route back out to that same depot, for any permitted vClass
    #               (U-turns are disabled with --no-turnarounds, so a ban can leave a
    #               stub a vehicle can enter and never leave)
    def _roundtrip(e, vc):
        """Cheapest depot with BOTH a legal inbound and a legal outbound leg.
        Returns (depot_index_or_None, saw_any_inbound_path)."""
        best, bestc, any_in = None, float("inf"), False
        for k, de in enumerate(DEPOT_EDGES):
            p1, c1 = net.getShortestPath(net.getEdge(de), e, vClass=vc)
            if p1 is None:
                continue
            any_in = True
            p2, c2 = net.getShortestPath(e, net.getEdge(de), vClass=vc)
            if p2 is None:
                continue                      # can get in at this depot, not back out
            if c1 < bestc:
                best, bestc = k, c1
        return best, any_in

    assign = {0: [], 1: []}
    unservable = []
    feasible_vc = {}          # addr id -> vClass that actually completes a round trip
    for a in addrs:
        e = net.getEdge(a["edge"])
        cands = [vc for vc in ("truck", "delivery") if reach[a["id"]][vc]]
        if not cands:
            a = dict(a); a["fail"] = "banned"
            unservable.append(a)
            continue
        chosen, depot_k, any_in = None, None, False
        for vc in cands:                      # truck first, then fall back to the van
            k, ai = _roundtrip(e, vc)
            any_in = any_in or ai
            if k is not None:
                chosen, depot_k = vc, k
                break
        if chosen is None:
            a = dict(a)
            a["fail"] = "trap" if any_in else "no-path"
            a["tried_vclasses"] = cands
            unservable.append(a)
            continue
        feasible_vc[a["id"]] = chosen
        assign[depot_k].append(a)

    heavy_types = [t for t in fleet_mix if VTYPES[t]["vClass"] == "truck"]
    light_types = [t for t in fleet_mix if VTYPES[t]["vClass"] == "delivery"]

    tours = []
    for k, alist in assign.items():
        alist = sorted(alist, key=lambda a: a["id"])
        rng.shuffle(alist)
        # pool by the vClass that was proven round-trip feasible, NOT by the raw edge
        # permission -- an address whose street permits trucks but whose truck network
        # is fragmented must ride a van, or its tour cannot be built.
        vanonly = [a for a in alist if feasible_vc[a["id"]] != "truck"]
        anyv = [a for a in alist if feasible_vc[a["id"]] == "truck"]

        def pack(pool, types):
            i, ci = 0, 0
            while i < len(pool):
                vt = types[ci % len(types)]; ci += 1
                cap = VTYPES[vt]["containerCapacity"]
                batch, load = [], 0
                maxstops = (stop_caps or {}).get(vt, MAX_STOPS_PER_TOUR)
                while (i < len(pool) and len(batch) < maxstops
                       and load + pool[i]["parcels"] <= cap):
                    batch.append(pool[i]); load += pool[i]["parcels"]; i += 1
                if not batch:
                    batch = [pool[i]]; load = pool[i]["parcels"]; i += 1
                tours.append(dict(depot=k, vtype=vt, addrs=batch, parcels=load))

        if vanonly:
            pack(vanonly, light_types if light_types else fleet_mix)
        if anyv:
            pack(anyv, fleet_mix)

    out = []
    for t_i, t in enumerate(tours):
        vc = VTYPES[t["vtype"]]["vClass"]
        uniq = sorted({a["edge"] for a in t["addrs"]})
        D = _pairD(net, [DEPOT_EDGES[t["depot"]]] + uniq, vc)
        if any(not math.isfinite(v) for v in D.values()):
            out.append(dict(id="r%d_t%03d" % (rep, t_i), depot=t["depot"], vtype=t["vtype"],
                            seq=t["addrs"], parcels=t["parcels"], planned_cost=float("inf"),
                            infeasible=True))
            continue
        order, cost = nn_2opt(DEPOT_EDGES[t["depot"]], uniq, D, rng)
        seq = []
        for e in order:
            for a in sorted([x for x in t["addrs"] if x["edge"] == e],
                            key=lambda x: x["startPos"]):
                seq.append(a)
        out.append(dict(id="r%d_t%03d" % (rep, t_i), depot=t["depot"], vtype=t["vtype"],
                        seq=seq, parcels=t["parcels"], planned_cost=cost, infeasible=False))
    return out, unservable


# ---------------------------------------------------------------- emitting --
def build_route(net, edge_seq, vClass):
    route, bad = [edge_seq[0]], []
    for k in range(len(edge_seq) - 1):
        a, b = edge_seq[k], edge_seq[k + 1]
        if a == b:
            continue
        p, c = net.getShortestPath(net.getEdge(a), net.getEdge(b), vClass=vClass)
        if p is None:
            bad.append((k, a, b)); continue
        for e in [x.getID() for x in p if not x.getID().startswith(":")][1:]:
            if route[-1] != e:
                route.append(e)
    return route, bad


def write_containerstops(net_file, addrs, out_add, bay_addr_ids=()):
    net = getnet(net_file)
    add = ['<additional>']
    for k, de in enumerate(DEPOT_EDGES):
        L = net.getEdge(de).getLength()
        add.append('  <containerStop id="depot%d" lane="%s_0" startPos="%.1f" endPos="%.1f"/>'
                   % (k, de, L * 0.30, L * 0.30 + 40))
    for a in addrs:
        add.append('  <containerStop id="cs_%s" lane="%s" startPos="%.1f" endPos="%.1f"/>'
                   % (a["id"], a["lane"], a["startPos"], a["endPos"]))
    add.append('</additional>')
    open(out_add, "w").write("\n".join(add) + "\n")


def generate(net_file, addrs, out_add, out_rou, seed, fleet_mix=("van", "van", "rigid"),
             paradigm="tour", freight_scale=1, night_fraction=0.0, night_offset=0,
             bay_ids=(), ledger_path=None, stop_caps=None):
    """bay_ids: set of address ids that HAVE a loading bay -> stop is emitted with
    parking='true' (vehicle leaves the traffic stream).  All other stops are
    parking='false' double-parks that block the single local travel lane."""
    net = getnet(net_file)
    write_containerstops(net_file, addrs, out_add)
    rng = random.Random(seed * 7919 + 13)
    elems = []
    ledger = dict(paradigm=paradigm, freight_scale=freight_scale, fleet_mix=list(fleet_mix),
                  stop_caps=stop_caps,
                  night_fraction=night_fraction, tours=[], unservable=[], unroutable_legs=[],
                  bay_ids=sorted(bay_ids))

    FREIGHT_WINDOW = 1500.0     # tours all dispatched inside the first 25 min so a
                                # full multi-stop tour can close before SIM_END
    def depart_time(i, n, rep):
        return 60.0 + rep * 20.0 + FREIGHT_WINDOW * (i / max(1, n - 1))

    for rep in range(freight_scale):
        tours, unserv = plan_tours(net_file, addrs, fleet_mix, seed, rep, stop_caps=stop_caps)
        for a in unserv:
            ledger["unservable"].append(dict(rep=rep, addr=a["id"], edge=a["edge"],
                                             parcels=a["parcels"],
                                             reason=a.get("fail", "unknown")))
        if paradigm == "trip":
            flat = []
            for t in tours:
                for a in t["seq"]:
                    flat.append((t["depot"], t["vtype"], a))
            tours = [dict(id="r%d_p%03d" % (rep, i), depot=d, vtype=v, seq=[a],
                          parcels=a["parcels"], infeasible=False)
                     for i, (d, v, a) in enumerate(flat)]

        n = len(tours)
        night_ids = set()
        if night_fraction > 0:
            ids = sorted(t["id"] for t in tours)
            rr = random.Random(4242 + seed + rep)
            rr.shuffle(ids)
            night_ids = set(ids[:int(round(night_fraction * n))])

        for ti, t in enumerate(tours):
            vt = t["vtype"]; vc = VTYPES[vt]["vClass"]
            depot_edge = DEPOT_EDGES[t["depot"]]
            if t.get("infeasible"):
                ledger["tours"].append(dict(id=t["id"], vtype=vt, emitted=False,
                                            reason="infeasible sequence",
                                            planned_parcels=t["parcels"],
                                            addrs=[a["id"] for a in t["seq"]]))
                continue
            seqe = [depot_edge] + [a["edge"] for a in t["seq"]] + [depot_edge]
            route, bad = build_route(net, seqe, vc)
            if bad:
                for (k, ea, eb) in bad:
                    ledger["unroutable_legs"].append(dict(tour=t["id"], leg=k, frm=ea, to=eb))
                ledger["tours"].append(dict(id=t["id"], vtype=vt, emitted=False,
                                            reason="unroutable leg",
                                            planned_parcels=t["parcels"],
                                            addrs=[a["id"] for a in t["seq"]]))
                continue
            vid = t["id"]
            dep = depart_time(ti, n, rep)
            if t["id"] in night_ids:
                dep += night_offset
            stops = ['    <stop containerStop="depot%d" duration="60" parking="true"/>' % t["depot"]]
            dwells = []
            for a in t["seq"]:
                d = dwell_seconds(a["parcels"], rng)
                dwells.append(d)
                park = "true" if a["id"] in bay_ids else "false"
                stops.append('    <stop containerStop="cs_%s" duration="%d" parking="%s"/>'
                             % (a["id"], d, park))
            veh = ('  <vehicle id="%s" type="%s" depart="%.1f" departLane="best" departSpeed="max">\n'
                   '    <route edges="%s"/>\n%s\n  </vehicle>'
                   % (vid, vt, dep, " ".join(route), "\n".join(stops)))
            elems.append((dep, 1, veh))
            npar = sum(a["parcels"] for a in t["seq"])
            for a in t["seq"]:
                for p in range(a["parcels"]):
                    cid = "p_%s_%s_%d" % (vid, a["id"], p)
                    cdep = max(0.0, dep - 30.0)
                    elems.append((cdep, 0,
                                  '  <container id="%s" depart="%.1f">\n'
                                  '    <stop containerStop="depot%d" duration="1"/>\n'
                                  '    <transport containerStop="cs_%s" lines="%s"/>\n'
                                  '  </container>' % (cid, cdep, t["depot"], a["id"], vid)))
            ledger["tours"].append(dict(id=vid, vtype=vt, depot=t["depot"], emitted=True,
                                        depart=dep, addrs=[a["id"] for a in t["seq"]],
                                        dwells=dwells, parcels=npar,
                                        planned_parcels=t["parcels"],
                                        n_bays=sum(1 for a in t["seq"] if a["id"] in bay_ids),
                                        night=(t["id"] in night_ids),
                                        route_len_planned=sum(
                                            net.getEdge(e).getLength() for e in route)))

    elems.sort(key=lambda x: (x[0], x[1]))
    # vTypes come from demand/vtypes.add.xml (loaded as an --additional-file);
    # emitting them here too would be a duplicate definition error.
    open(out_rou, "w").write('<routes>\n%s\n</routes>\n'
                             % "\n".join(x[2] for x in elems))
    ledger["n_containers_offered"] = sum(1 for e in elems if e[1] == 0)
    ledger["n_vehicles_emitted"] = sum(1 for e in elems if e[1] == 1)
    ledger["parcels_offered_by_design"] = freight_scale * sum(a["parcels"] for a in addrs)
    ledger["addresses_total"] = len(addrs) * freight_scale
    if ledger_path:
        json.dump(ledger, open(ledger_path, "w"), indent=1)
    return ledger


if __name__ == "__main__":
    addrs = choose_addresses()
    json.dump(addrs, open(os.path.join(DEMAND, "addresses.json"), "w"), indent=1)
    import build_network as bn
    streets = sorted({bn.edge_to_street(a["edge"]) for a in addrs})
    print("addresses=%d parcels=%d on %d/%d local streets"
          % (len(addrs), sum(a["parcels"] for a in addrs), len(streets), len(bn.local_streets())))
    lg = generate(BASE_NET, addrs, os.path.join(DEMAND, "stops_test.add.xml"),
                  os.path.join(DEMAND, "freight_test.rou.xml"), seed=1,
                  ledger_path=os.path.join(DEMAND, "ledger_test.json"))
    print("tours=%d containers=%d unservable=%d"
          % (lg["n_vehicles_emitted"], lg["n_containers_offered"], len(lg["unservable"])))
