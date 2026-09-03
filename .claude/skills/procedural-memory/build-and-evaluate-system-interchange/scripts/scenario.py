#!/usr/bin/env python3
"""
Demand + instrumentation for the three system-interchange variants.

Demand
------
A 12-movement freeway OD (4 legs x 3 destinations), through-dominant, containing:
  * one clearly heaviest LEFT/loop movement   A-West -> B-North  (1300 veh/h)
  * a heavy WEAVING PAIR on the EB-A carriageway: that same 1300 veh/h loop-OFF
    together with 1000 veh/h of B-North -> A-East loop-ON traffic.  Those two
    streams must cross each other inside EB-A's 182 m auxiliary lane.
The other three carriageways are loaded moderately, so that the binding constraint
is unambiguously EB-A's weaving section rather than the network at large.

Instrumentation
---------------
E1 induction loops in a dense chain along the EB-A and NB-B mainlines (every lane,
60 s aggregation) -> discharge flow vs demand, and speed/occupancy time-space maps.
E2 lane-area detectors spanning the full weaving section (every lane), the loop-on
and loop-off ramps (queue + spillback), and the mainline lane immediately upstream
of the weave (to detect the queue escaping the weaving section onto the mainline).
"""
import json
import math
import os
import subprocess
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
EPISODE = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
NETDIR = os.path.join(EPISODE, "outputs", "networks")
DEMDIR = os.path.join(EPISODE, "outputs", "demand")

VARIANTS = ["clover", "cd", "flyover"]

# ------------------------------------------------------------------ the 12-movement OD
# origin leg -> destination leg -> veh/h at scale 1.0
OD = {
    "A-West": {"A-East": 2800, "B-North": 1300, "B-South": 500},
    "B-North": {"B-South": 2000, "A-East": 1000, "A-West": 450},
    "A-East": {"A-West": 2600, "B-South": 500, "B-North": 550},
    "B-South": {"B-North": 2000, "A-West": 450, "A-East": 550},
}
MOVEMENT_KIND = {   # for reporting
    ("A-West", "A-East"): "through", ("A-West", "B-North"): "left-loop(HEAVY)",
    ("A-West", "B-South"): "right-outer",
    ("B-North", "B-South"): "through", ("B-North", "A-East"): "left-loop(weave pair)",
    ("B-North", "A-West"): "right-outer",
    ("A-East", "A-West"): "through", ("A-East", "B-South"): "left-loop",
    ("A-East", "B-North"): "right-outer",
    ("B-South", "B-North"): "through", ("B-South", "A-West"): "left-loop",
    ("B-South", "A-East"): "right-outer",
}
ORIGIN_CW = {"A-West": "EB", "B-South": "NB", "A-East": "WB", "B-North": "SB"}
DEST_CW = {"A-East": "EB", "B-North": "NB", "A-West": "WB", "B-South": "SB"}

SCALES = [0.50, 0.60, 0.70, 0.80, 0.90, 0.95, 1.00, 1.05, 1.10, 1.20, 1.35,
          1.50, 1.70, 1.90]
SEEDS = [11, 23, 37, 53, 71]

T_WARM = 600          # discard
T_END_FLOW = 2400     # flows stop here
T_END = 3600          # simulation stops here (drain)
AGG = 60              # detector aggregation period

# E1 chain stations (metres from the crossing point, along direction of travel)
E1_STATIONS = [-3000, -2600, -2200, -1800, -1500, -1250, -1050, -900, -780, -660,
               -560, -480, -400, -330, -270, -220, -170, -130, -90, -55, -20,
               20, 55, 90, 130, 170, 220, 270, 330, 400, 480, 560, 660, 780,
               900, 1050, 1250, 1500, 1800, 2200, 2600, 3000]


# ------------------------------------------------------------------ net introspection
def load_net(variant):
    root = ET.parse(os.path.join(NETDIR, variant, "%s.net.xml" % variant)).getroot()
    edges = {}
    for e in root.iter("edge"):
        if e.get("function") == "internal":
            continue
        ls = []
        for l in e.findall("lane"):
            pts = [tuple(float(v) for v in p.split(",")) for p in l.get("shape").split()]
            pts = [p if len(p) == 3 else (p[0], p[1], 0.0) for p in pts]
            ls.append(dict(id=l.get("id"), index=int(l.get("index")),
                           length=float(l.get("length")), shape=pts))
        edges[e.get("id")] = dict(id=e.get("id"), lanes=ls, n=len(ls),
                                  length=ls[0]["length"] if ls else 0.0)
    conns = [dict(f=c.get("from"), t=c.get("to"), fl=int(c.get("fromLane")),
                  tl=int(c.get("toLane")))
             for c in root.iter("connection") if not c.get("from", "").startswith(":")]
    return edges, conns


def locate(lane, axis, target, sign):
    """arclength position along `lane` where its coordinate on `axis` (0=x,1=y) crosses
    `target` while travelling in direction `sign`.  Returns None if it never does."""
    sh = lane["shape"]
    acc = 0.0
    for i in range(len(sh) - 1):
        a, b = sh[i], sh[i + 1]
        seg = math.dist(a[:2], b[:2])
        va, vb = a[axis] * sign, b[axis] * sign
        t = target * sign
        if (va - t) * (vb - t) <= 0 and abs(vb - va) > 1e-9:
            f = (t - va) / (vb - va)
            return acc + f * seg
        acc += seg
    return None


def mainline_axis(cw):
    """(coordinate index, sign) such that station = sign * coord for carriageway cw."""
    return {"EB": (0, 1), "WB": (0, -1), "NB": (1, 1), "SB": (1, -1)}[cw]


def instrument_targets(variant, edges, conns):
    """Resolve, per variant and per carriageway, the semantically-important edges:
    where the loop-on merges, where the loop-off diverges, and (if those are the same
    edge) the shared-auxiliary-lane weaving section between them."""
    out = {}
    for cw in ("EB", "NB", "WB", "SB"):
        t = {}
        loop_on = [c for c in conns
                   if c["f"].startswith(("loop", "cdloop")) and c["f"].endswith("_" + cw)]
        loop_off = [c for c in conns
                    if c["t"].startswith(("loop", "cdloop")) and c["t"].split("_")[1] == cw]
        t["loop_on_edge"] = loop_on[0]["f"] if loop_on else None
        t["loop_off_edge"] = loop_off[0]["t"] if loop_off else None
        if loop_on and loop_off and loop_on[0]["t"] == loop_off[0]["f"]:
            t["weave_edge"] = loop_on[0]["t"]
            t["weave_kind"] = ("collector-distributor" if t["weave_edge"].startswith("CD")
                               else "mainline")
        else:
            t["weave_edge"] = loop_on[0]["t"] if loop_on else (
                loop_off[0]["f"] if loop_off else None)
            t["weave_kind"] = "none (weaving movement removed from this carriageway)"
        up = [c["f"] for c in conns if t["weave_edge"] and c["t"] == t["weave_edge"]
              and not c["f"].startswith(("loop", "cdloop"))]
        t["weave_upstream_edge"] = up[0] if up else None
        out[cw] = t
    out["_global"] = dict(fly_edge="fly_EB_NB" if "fly_EB_NB" in edges else None,
                          cd_entry_edge="cddiv_EB" if "cddiv_EB" in edges else None,
                          cd_exit_edge="cdmer_EB" if "cdmer_EB" in edges else None)
    return out


# ------------------------------------------------------------------ routes
def build_routes(variant):
    """One duarouter run per variant produces the 12 canonical movement routes."""
    net = os.path.join(NETDIR, variant, "%s.net.xml" % variant)
    d = os.path.join(DEMDIR, variant)
    os.makedirs(d, exist_ok=True)
    trips = os.path.join(d, "movements.trips.xml")
    with open(trips, "w") as fh:
        fh.write("<routes>\n")
        i = 0
        for o, row in OD.items():
            for dst in row:
                fh.write('  <trip id="%s__%s" depart="%d" from="%s_in" to="%s_out"/>\n'
                         % (o, dst, i, ORIGIN_CW[o], DEST_CW[dst]))
                i += 1
        fh.write("</routes>\n")
    rou = os.path.join(d, "movements.rou.xml")
    r = subprocess.run(["duarouter", "-n", net, "-r", trips, "-o", rou,
                        "--no-step-log", "true", "--ignore-errors", "false"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("duarouter failed for %s:\n%s" % (variant, r.stderr))
    routes = {}
    for v in ET.parse(rou).getroot().iter("vehicle"):
        routes[v.get("id").replace("__", "|", 1)] = v.find("route").get("edges")
    if len(routes) != 12:
        raise RuntimeError("%s: only %d/12 movements routed" % (variant, len(routes)))
    return routes


def write_demand(variant, routes, edges):
    d = os.path.join(DEMDIR, variant)
    lens = {}
    for mid, seq in routes.items():
        lens[mid] = round(sum(edges[e]["length"] for e in seq.split() if e in edges), 1)
    for sc in SCALES:
        path = os.path.join(d, "demand_%s_%.2f.rou.xml" % (variant, sc))
        with open(path, "w") as fh:
            fh.write("<routes>\n")
            fh.write('  <vType id="car" vClass="passenger" length="5.0" minGap="2.5"\n'
                     '         accel="2.6" decel="4.5" sigma="0.5" tau="1.1" maxSpeed="45"\n'
                     '         speedFactor="normc(1.0,0.10,0.75,1.25)" carFollowModel="Krauss"\n'
                     '         laneChangeModel="LC2013"/>\n')
            for mid, seq in sorted(routes.items()):
                fh.write('  <route id="r_%s" edges="%s"/>\n' % (mid.replace("|", "__"), seq))
            for o, row in sorted(OD.items()):
                for dst, vph in sorted(row.items()):
                    mid = "%s|%s" % (o, dst)
                    fh.write('  <flow id="f_%s" type="car" route="r_%s" begin="0" end="%d"\n'
                             '        vehsPerHour="%.1f" departLane="free" departSpeed="desired"/>\n'
                             % (mid.replace("|", "__"), mid.replace("|", "__"),
                                T_END_FLOW, vph * sc))
            fh.write("</routes>\n")
    return lens


# ------------------------------------------------------------------ detectors
def write_detectors(variant, edges, conns, targets):
    """Template additional file; %(out)s is substituted with a per-run output prefix."""
    lines = ['<additional>']
    placed = []
    for cw in ("EB", "NB"):
        axis, sign = mainline_axis(cw)
        chain = [e for e in edges.values() if e["id"].startswith(cw + "_")]
        for st in E1_STATIONS:
            hits = []
            for e in chain:
                pos = locate(e["lanes"][0], axis, st, sign)
                if pos is not None and 1.0 < pos < e["length"] - 1.0:
                    hits.append((e, pos))
            if len(hits) != 1:
                continue                      # station falls inside a junction: skip
            e, pos = hits[0]
            for l in e["lanes"]:
                did = "e1_%s_%+05d_l%d" % (cw, st, l["index"])
                lines.append('  <inductionLoop id="%s" lane="%s" pos="%.2f" period="%d" '
                             'file="%%(out)s_e1.xml"/>' % (did, l["id"], min(pos, l["length"] - 0.5), AGG))
            placed.append((cw, st, e["id"], round(pos, 1), e["n"]))

    e2_meta = {}

    def e2_all_lanes(tag, eid):
        if not eid or eid not in edges:
            return
        for l in edges[eid]["lanes"]:
            lines.append('  <laneAreaDetector id="e2_%s_l%d" lane="%s" pos="0" '
                         'length="%.2f" period="%d" file="%%(out)s_e2.xml"/>'
                         % (tag, l["index"], l["id"], l["length"] - 0.2, AGG))
        # detector length is needed to turn a jam length into a SPILLBACK test
        e2_meta["e2_" + tag] = dict(edge=eid, length_m=round(edges[eid]["length"] - 0.2, 1),
                                    lanes=edges[eid]["n"])

    for cw in ("EB", "NB", "WB", "SB"):
        t = targets[cw]
        e2_all_lanes("weave" + cw, t["weave_edge"])
        e2_all_lanes("loopon" + cw, t["loop_on_edge"])
        e2_all_lanes("loopoff" + cw, t["loop_off_edge"])
        e2_all_lanes("upstr" + cw, t["weave_upstream_edge"])
    g = targets["_global"]
    e2_all_lanes("flyEB", g["fly_edge"])
    e2_all_lanes("cdentryEB", g["cd_entry_edge"])
    e2_all_lanes("cdexitEB", g["cd_exit_edge"])

    # network-level edge data for the congestion heatmap
    lines.append('  <edgeData id="ed" period="%d" file="%%(out)s_edge.xml" excludeEmpty="true"/>'
                 % (T_END_FLOW - T_WARM))
    lines.append('</additional>')
    path = os.path.join(DEMDIR, variant, "detectors.add.template.xml")
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    with open(os.path.join(DEMDIR, variant, "e2_meta.json"), "w") as fh:
        json.dump(e2_meta, fh, indent=1)
    return placed, e2_meta


def main():
    os.makedirs(DEMDIR, exist_ok=True)
    summary = {"od": {o: dict(r) for o, r in OD.items()},
               "od_total_vph": sum(sum(r.values()) for r in OD.values()),
               "scales": SCALES, "seeds": SEEDS,
               "warmup_s": T_WARM, "flow_end_s": T_END_FLOW, "sim_end_s": T_END,
               "variants": {}}
    for v in VARIANTS:
        edges, conns = load_net(v)
        targets = instrument_targets(v, edges, conns)
        routes = build_routes(v)
        lens = write_demand(v, routes, edges)
        placed, e2_meta = write_detectors(v, edges, conns, targets)
        summary["variants"][v] = dict(targets=targets, route_lengths_m=lens,
                                      n_e1_stations=len(placed), e1_stations=placed,
                                      e2_meta=e2_meta)
        for cw in ("EB", "NB", "WB", "SB"):
            t = targets[cw]
            print("%-8s %s weave=%-12s (%-22s) loop_on=%-14s loop_off=%-14s"
                  % (v, cw, t["weave_edge"], t["weave_kind"][:22], t["loop_on_edge"],
                     t["loop_off_edge"]))
        print("%-8s    E1 stations=%d  E2 groups=%d" % (v, len(placed), len(e2_meta)))
    with open(os.path.join(EPISODE, "outputs", "tables", "scenario_setup.json"), "w") as fh:
        json.dump(summary, fh, indent=1)

    print("\nOD (veh/h at scale 1.0), total %d veh/h:" % summary["od_total_vph"])
    for (o, dst), kind in MOVEMENT_KIND.items():
        print("  %-8s -> %-8s  %5d   %s" % (o, dst, OD[o][dst], kind))
    print("\nroute length by movement (m):")
    for mid in sorted(summary["variants"]["clover"]["route_lengths_m"]):
        row = "  %-20s" % mid
        for v in VARIANTS:
            row += "  %-8s %7.0f" % (v, summary["variants"][v]["route_lengths_m"][mid])
        print(row)


if __name__ == "__main__":
    main()
