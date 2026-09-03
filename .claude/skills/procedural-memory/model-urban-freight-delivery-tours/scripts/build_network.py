#!/usr/bin/env python3
"""
Parameterised urban-district network builder + vClass-restriction variant builder.

Builds a 6x6-block grid (7x7 junctions, 200 m blocks) with
  * a perimeter arterial RING + one bisecting arterial  (2 lanes/dir, 50 km/h)
  * interior LOCAL streets                              (1 lane/dir, 30 km/h)
  * traffic lights on every arterial node with a conflicting approach
  * priority control on interior local-local nodes

and then emits `disallow="truck delivery"` restriction variants at a chosen
coverage of the local street set (seeded, symmetric per street so a ban is a real
street closure, not a one-way ban).

Two restriction families:
  strict  -- ban applies to every selected local street, including those carrying
             a delivery address (this is what generates H7's reachability failure)
  exempt  -- "access except loading": streets carrying a delivery address are
             never banned, so every address stays reachable

Usage:  python build_network.py            (builds everything)
"""
import os, sys, random, json, argparse
import xml.etree.ElementTree as ET
from common import *   # noqa

COVERAGES = [0, 25, 50, 75, 100]
FAMILIES = ["strict", "hgv"]
# strict : disallow="truck delivery"  -- ALL freight banned from the street (no access exemption)
# hgv    : disallow="truck"           -- heavy-goods ban with a delivery-van exemption
NET_SEED = 20260803    # seed for which streets get banned (held fixed across arms)


# ---------------------------------------------------------------- plain XML --
def write_plain_xml(banned_streets=(), tag="base", ban_classes="truck delivery"):
    """delivery_streets: set of undirected street keys carrying >=1 delivery stop"""
    nodes = ['<nodes>']
    for i in range(N):
        for j in range(N):
            t = "traffic_light" if is_signalized(i, j) else "priority"
            nodes.append('  <node id="%s" x="%.1f" y="%.1f" type="%s"/>'
                         % (nid(i, j), i * BLOCK, j * BLOCK, t))
    nodes.append('</nodes>')

    edges = ['<edges>']
    for (i1, j1, i2, j2) in grid_streets():
        art = is_arterial(i1, j1, i2, j2)
        lanes = ART_LANES if art else LOC_LANES
        speed = ART_SPEED if art else LOC_SPEED
        prio = 3 if art else 1
        etype = "arterial" if art else "local"
        skey = street_key(i1, j1, i2, j2)
        banned = (skey in banned_streets)
        a, b = nid(i1, j1), nid(i2, j2)
        for (f, t) in ((a, b), (b, a)):
            attrs = ('id="%s" from="%s" to="%s" numLanes="%d" speed="%.3f" '
                     'priority="%d" type="%s"' % (eid(f, t), f, t, lanes, speed, prio, etype))
            if banned:
                edges.append('  <edge %s disallow="%s"/>' % (attrs, ban_classes))
            else:
                edges.append('  <edge %s/>' % attrs)
    edges.append('</edges>')

    open(os.path.join(NET, "%s.nod.xml" % tag), "w").write("\n".join(nodes) + "\n")
    open(os.path.join(NET, "%s.edg.xml" % tag), "w").write("\n".join(edges) + "\n")


def street_key(i1, j1, i2, j2):
    return tuple(sorted([(i1, j1), (i2, j2)]))


def compile_net(tag):
    out = os.path.join(NET, "%s.net.xml" % tag)
    # NOTE (model-vclass-lane-permissions): do NOT pass .con.xml/.tll.xml alongside
    # permission-edited edges -- let netconvert regenerate connections + TLS logic.
    cmd = (f'"{NETCONVERT}" -n {NET}/{tag}.nod.xml -e {NET}/{tag}.edg.xml -o {out} '
           f'--no-turnarounds true --tls.default-type static '
           f'--tls.green.time 31 --tls.yellow.time 4 --tls.allred.time 2 '
           f'--default.junctions.keep-clear true --junctions.corner-detail 0 '
           f'--no-internal-links false --offset.disable-normalization true')
    r = sh(cmd)
    if r.returncode != 0:
        raise RuntimeError("netconvert failed for %s:\n%s" % (tag, r.stderr[-3000:]))
    return out


# ------------------------------------------------------------ street sets ----
def local_streets():
    out = []
    for (i1, j1, i2, j2) in grid_streets():
        if not is_arterial(i1, j1, i2, j2):
            out.append(street_key(i1, j1, i2, j2))
    return sorted(out)


def arterial_edges():
    out = []
    for (i1, j1, i2, j2) in grid_streets():
        if is_arterial(i1, j1, i2, j2):
            a, b = nid(i1, j1), nid(i2, j2)
            out += [eid(a, b), eid(b, a)]
    return sorted(out)


def local_edges():
    out = []
    for (i1, j1, i2, j2) in grid_streets():
        if not is_arterial(i1, j1, i2, j2):
            a, b = nid(i1, j1), nid(i2, j2)
            out += [eid(a, b), eid(b, a)]
    return sorted(out)


def edge_to_street(e):
    a, b = e.split("_")
    p = lambda s: (int(s[1]), int(s[2]))
    return street_key(*p(a), *p(b))


def choose_banned(coverage_pct, protect=()):
    """Seeded selection of local streets to ban, identical prefix-nesting across
    coverage levels (25% set is a subset of the 50% set, etc.) so the sweep is a
    genuine dose-response and not five unrelated random draws."""
    ls = local_streets()
    rng = random.Random(NET_SEED)
    order = ls[:]
    rng.shuffle(order)
    if protect:
        order = [s for s in order if s not in set(protect)]
    k = int(round(len(ls) * coverage_pct / 100.0))
    k = min(k, len(order))
    return set(order[:k])


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delivery-streets-json", default=os.path.join(DEMAND, "delivery_streets.json"))
    args = ap.parse_args()

    manifest = {}
    BANCLS = {"strict": "truck delivery", "hgv": "truck"}
    for fam in FAMILIES:
        for cov in COVERAGES:
            tag = "d_%s_%d" % (fam, cov)
            banned = choose_banned(cov)
            write_plain_xml(banned_streets=banned, tag=tag, ban_classes=BANCLS[fam])
            compile_net(tag)
            manifest[tag] = dict(family=fam, coverage=cov, ban_classes=BANCLS[fam],
                                 n_local_streets=len(local_streets()),
                                 n_banned_streets=len(banned),
                                 banned=[list(map(list, s)) for s in sorted(banned)])
            print("built %-16s coverage=%3d%% banned=%3d/%d streets"
                  % (tag, cov, len(banned), len(local_streets())))
    json.dump(manifest, open(os.path.join(NET, "net_manifest.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
