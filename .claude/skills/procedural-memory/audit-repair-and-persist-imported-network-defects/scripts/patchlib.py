#!/usr/bin/env python3
"""
patchlib -- the reusable core of the QA / repair / patch-persistence workflow.

A REPAIR PATCH is a small JSON spec keyed entirely on SUMO element IDs
(edge ids, node ids, tlLogic ids, lane indices).  Because the ids that netconvert
gives an OSM import are derived from OSM way/node ids, the same spec can be
re-applied to a *different build* of the same OSM data -- that is what makes the
repair persistent across upstream map edits.  Anything expressed by absolute
coordinates or by netconvert-invented ids (cluster_*, *-AddedOnRampEdge) will NOT
survive re-import; the applier reports that explicitly instead of failing silently.

VERIFIED netconvert patch-layering rules (measured on SUMO 1.27.1, see notes.md):
  * `--node-files a.nod.xml,b.nod.xml` : b patches a.  `<node id=.. type=..>` works
    but x/y must be repeated.  `<join nodes="a b c"/>` is SPACE-separated and every
    listed node must exist or netconvert aborts with "Unknown junction ... in
    join-cluster" AND "No edges loaded".
  * `<delete>` in a *later* .con.xml CANNOT delete a connection that an *earlier*
    .con.xml already declared -- netconvert reports "Connection ... not found".
    Plain-XML patch layering is effectively ADDITIVE ONLY for connections.
  * Any change to a TL-controlled connection's lane assignment REQUIRES a matching
    rewrite of the `.tll.xml` `<connection ... tl=.. linkIndex=..>` binding, or
    netconvert aborts.  `--ignore-errors.connections` does NOT suppress it.
  * Deleting edges therefore has to go through `--remove-edges.explicit` +
    `--ignore-errors` (the plain files still reference them), not `<delete id=..>`.
"""
import os, sys, json, subprocess, collections, re
import xml.etree.ElementTree as ET


# --------------------------------------------------------------------------- net IO
def load_net(net):
    r = ET.parse(net).getroot()
    edges = {e.get("id"): e for e in r.findall("edge") if e.get("function") != "internal"}
    junc = {j.get("id"): j for j in r.findall("junction") if j.get("type") != "internal"}
    conns = [c for c in r.findall("connection") if not c.get("from", "").startswith(":")]
    tls = {t.get("id"): t for t in r.findall("tlLogic")}
    return r, edges, junc, conns, tls


def edge_graph(edges, conns):
    succ = collections.defaultdict(set)
    pred = collections.defaultdict(set)
    for c in conns:
        f, t = c.get("from"), c.get("to")
        if f in edges and t in edges:
            succ[f].add(t); pred[t].add(f)
    return succ, pred


def bfs(seeds, adj):
    st = list(seeds); v = set(seeds)
    while st:
        x = st.pop()
        for y in adj[x]:
            if y not in v:
                v.add(y); st.append(y)
    return v


def connectivity(net):
    """Directed connectivity audit. Validated against $SUMO_HOME/tools/net/netcheck.py
    -s / -d (exact agreement on edge counts). NOTE: netcheck.py's DEFAULT component
    mode is undirected and massively understates the problem."""
    r, edges, junc, conns, tls = load_net(net)
    succ, pred = edge_graph(edges, conns)
    rem = set(edges); comps = []
    while rem:
        s = next(iter(rem))
        c = bfs([s], succ) & bfs([s], pred)
        comps.append(c); rem -= c
    comps.sort(key=len, reverse=True)
    main = comps[0] if comps else set()
    fwd = bfs(main, succ); bwd = bfs(main, pred)
    out = set(edges) - main
    L = {k: float(v.findall("lane")[0].get("length")) * len(v.findall("lane"))
         for k, v in edges.items()}
    return dict(
        n_edges=len(edges), n_scc=len(comps), main_scc=len(main),
        outside=len(out),
        trap=sorted(fwd - main),          # enterable, no way back
        unreachable=sorted(bwd - main),   # can exit, cannot be entered
        severed=sorted(out - fwd - bwd),  # neither
        main_edges=sorted(main),
        lane_km_total=sum(L.values()) / 1000.0,
        lane_km_outside=sum(L[e] for e in out) / 1000.0,
        dead_end_edges=sum(1 for e in edges if not succ[e]),
    )


def noconflict_signals(net):
    """tlLogics whose controlled links are ALWAYS green together -> the program
    resolves no conflict at all and only injects an all-red interruption."""
    r, edges, junc, conns, tls = load_net(net)
    bad = []
    for tid, t in tls.items():
        ph = [p.get("state") for p in t.findall("phase")]
        durs = [float(p.get("duration")) for p in t.findall("phase")]
        gs = {frozenset(i for i, ch in enumerate(s) if ch in "Gg") for s in ph}
        gs.discard(frozenset())
        if len(gs) <= 1:
            lost = sum(d for d, s in zip(durs, ph) if not (set(s) & set("Gg")))
            bad.append(dict(id=tid, nlinks=len(ph[0]) if ph else 0, cycle=sum(durs),
                            nongreen=lost))
    return bad


# --------------------------------------------------------------------------- patch apply
def apply_patch(spec, plaindir, prefix, workdir, outnet, fixes):
    """Apply the subset `fixes` of `spec` on top of plaindir/<prefix>.*.xml and
    compile to outnet.  Returns (returncode, stderr, report) where report says, per
    fix, whether every id the fix references still exists in this build."""
    os.makedirs(workdir, exist_ok=True)
    nod = [os.path.join(plaindir, prefix + ".nod.xml")]
    edg = [os.path.join(plaindir, prefix + ".edg.xml")]
    con = [os.path.join(plaindir, prefix + ".con.xml")]
    tll = os.path.join(plaindir, prefix + ".tll.xml")
    opts = []
    report = {}

    # ids present in this build (for the persistence report)
    have_nodes = set(re.findall(r'<node id="([^"]+)"', open(nod[0]).read()))
    edg_txt = open(edg[0]).read()
    have_edges = set(re.findall(r'<edge id="([^"]+)"', edg_txt))
    tll_txt = open(tll).read()

    # ---- FIX-A : drop edges outside the largest strongly-connected component
    killed_edges, killed_nodes = set(), set()
    if "A" in fixes:
        want = spec["A"]["remove_edges"]
        present = [e for e in want if e in have_edges]
        report["A"] = dict(targeted=len(want), resolved=len(present),
                           missing=sorted(set(want) - set(present)))
        if present:
            opts += ["--remove-edges.explicit", ",".join(present), "--ignore-errors"]
            killed_edges = set(present)
            # nodes that only ever appear on removed edges will be gone too
            keep_nodes = set()
            for m in re.finditer(r'<edge id="([^"]+)"[^>]*?from="([^"]+)"[^>]*?to="([^"]+)"', edg_txt):
                if m.group(1) not in killed_edges:
                    keep_nodes.add(m.group(2)); keep_nodes.add(m.group(3))
            killed_nodes = have_nodes - keep_nodes
            have_edges = have_edges - killed_edges
            have_nodes = have_nodes - killed_nodes

    # ---- FIX-B : force a junction join netconvert's heuristic refused
    if "B" in fixes:
        want = spec["B"]["join_nodes"]
        present = [n for n in want if n in have_nodes]
        report["B"] = dict(targeted=len(want), resolved=len(present),
                           missing=sorted(set(want) - set(present)))
        # netconvert ABORTS if any listed node is unknown -> only list survivors
        if len(present) >= 2:
            p = os.path.join(workdir, "fixB.nod.xml")
            with open(p, "w") as f:
                f.write('<nodes>\n  <join nodes="%s" id="%s"/>\n</nodes>\n'
                        % (" ".join(present), spec["B"]["join_id"]))
            nod.append(p)

    # ---- FIX-C : add an exclusive left-turn lane + rebind the TL link
    #  spec["C"] = {edge, new_numLanes, connections:[[to,fromLane,toLane],...],
    #               tll_rebind:[[to, oldFromLane, toLane, newFromLane],...]}
    if "C" in fixes:
        c = spec["C"]
        ok = c["edge"] in have_edges
        dests_ok = all(t in have_edges for t, _, _ in c["connections"])
        rebinds = []
        for to, ofl, tl_, nfl in c["tll_rebind"]:
            b = ('<connection from="%s" to="%s" fromLane="%s" toLane="%s"'
                 % (c["edge"], to, ofl, tl_))
            nb = ('<connection from="%s" to="%s" fromLane="%s" toLane="%s"'
                  % (c["edge"], to, nfl, tl_))
            rebinds.append((b, nb, b in tll_txt))
        # PRE-STATE GUARD: a lane/connection patch is only meaningful if the build it
        # is applied to still has the state the patch assumed. Without this check the
        # patch either errors out (verified on an upstream lanes=4 map edit) or, worse,
        # silently produces a different network than intended.
        con_txt = open(con[0]).read()
        pre_ok = True
        for m in c.get("expect_connections", []):
            s = ('<connection from="%s" to="%s" fromLane="%s" toLane="%s"'
                 % (c["edge"], m[0], m[1], m[2]))
            if s not in con_txt:
                pre_ok = False
        m_nl = re.search(r'<edge id="%s"[^>]*numLanes="(\d+)"' % re.escape(c["edge"]), edg_txt)
        cur_nl = int(m_nl.group(1)) if m_nl else None
        if c.get("old_numLanes") is not None and cur_nl != c["old_numLanes"]:
            pre_ok = False
        report["C"] = dict(edge_present=ok, dests_present=dests_ok,
                           prestate_ok=pre_ok, observed_numLanes=cur_nl,
                           tll_bindings_found=[r[2] for r in rebinds],
                           applied=bool(ok and dests_ok and pre_ok))
        if ok and dests_ok and pre_ok:
            pe = os.path.join(workdir, "fixC.edg.xml")
            with open(pe, "w") as f:
                f.write('<edges>\n  <edge id="%s" numLanes="%d"/>\n</edges>\n'
                        % (c["edge"], c["new_numLanes"]))
            edg.append(pe)
            pc = os.path.join(workdir, "fixC.con.xml")
            with open(pc, "w") as f:
                f.write('<connections>\n')
                f.write('  <connection from="%s"/>\n' % c["edge"])  # clear, then re-declare
                for to, fl, tl_ in c["connections"]:
                    f.write('  <connection from="%s" to="%s" fromLane="%s" toLane="%s"/>\n'
                            % (c["edge"], to, fl, tl_))
                f.write('</connections>\n')
            con.append(pc)
            newtxt = tll_txt
            for b, nb, found in rebinds:
                if found:
                    newtxt = newtxt.replace(b, nb)
            if newtxt != tll_txt:
                pt = os.path.join(workdir, "fixC.tll.xml")
                with open(pt, "w") as f:
                    f.write(newtxt)
                tll = pt

    # ---- FIX-D : demote signals that resolve no conflict
    if "D" in fixes:
        want = spec["D"]["unset_junctions"]
        present = [n for n in want if n in have_nodes]
        report["D"] = dict(targeted=len(want), resolved=len(present),
                           missing=sorted(set(want) - set(present)))
        if present:
            opts += ["--tls.unset", ",".join(present)]

    cmd = ["netconvert",
           "--node-files", ",".join(nod),
           "--edge-files", ",".join(edg),
           "--connection-files", ",".join(con),
           "--tllogic-files", tll,
           "-o", outnet] + opts
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, p.stderr, report, cmd


# --------------------------------------------------------------------------- verify
def verify(net, spec, fixes):
    """Check IN THE COMPILED NET that each requested fix actually landed."""
    r, edges, junc, conns, tls = load_net(net)
    res = {}
    if "A" in fixes:
        still = [e for e in spec["A"]["remove_edges"] if e in edges]
        cn = connectivity(net)
        res["A"] = dict(ok=(len(still) == 0 and cn["outside"] == 0),
                        msg="%d/%d targeted edges still present; edges outside largest SCC now %d "
                            "(was %d)" % (len(still), len(spec["A"]["remove_edges"]),
                                          cn["outside"], spec["A"]["baseline_outside"]))
    if "B" in fixes:
        members = spec["B"]["join_nodes"]
        surv = [m for m in members if m in junc]
        joined = [j for j in junc if j.startswith(spec["B"]["join_id"])]
        res["B"] = dict(ok=(len(joined) == 1 and not surv),
                        msg="joined junction=%s ; member nodes still separate=%s" % (joined, surv))
    if "C" in fixes:
        c = spec["C"]
        e = edges.get(c["edge"])
        nl = len(e.findall("lane")) if e is not None else 0
        lt = sorted(int(x.get("fromLane")) for x in conns
                    if x.get("from") == c["edge"] and x.get("to") == c["left_to"])
        th = sorted(int(x.get("fromLane")) for x in conns
                    if x.get("from") == c["edge"] and x.get("to") != c["left_to"])
        excl = bool(lt) and not (set(lt) & set(th))
        res["C"] = dict(ok=(nl == c["new_numLanes"] and excl and lt == [int(c["new_fromLane"])]),
                        msg="numLanes=%d left-from-lanes=%s through-from-lanes=%s exclusive=%s"
                            % (nl, lt, th, excl))
    if "D" in fixes:
        nc = noconflict_signals(net)
        gone = [t for t in spec["D"]["unset_tls"] if t in tls]
        res["D"] = dict(ok=(not gone and not nc),
                        msg="targeted tlLogics still present=%s ; no-conflict signals remaining=%s"
                            % (gone, [x["id"] for x in nc]))
    return res
