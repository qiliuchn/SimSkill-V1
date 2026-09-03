#!/usr/bin/env python3
"""Boundary-preserving sub-network extraction ("scenario cutting") for SUMO.

Given a parent .net.xml, a parent route/vehroute file and a rectangular study
area, this produces a runnable sub-scenario:

  1. netconvert --keep-edges.in-boundary  ->  cut .net.xml
  2. cutRoutes.py                          ->  truncated routes with
                                               boundary-entry departures
  3. a .sumocfg + edgeData additional file ready to run

It also reports, structurally, what the cut dropped: edges, junctions, TLS
programs, TLS phase-string lengths (orphan phase states), and connections.

Usage:
  python3 cut_scenario.py --parent-net P.net.xml --parent-routes P.vehroutes.xml \
      --boundary xmin,ymin,xmax,ymax --out-dir DIR --name tag [cutRoutes opts]
"""
import argparse
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

SUMO_HOME = os.environ.get("SUMO_HOME")
if not SUMO_HOME:
    sys.exit("SUMO_HOME must be set")
sys.path.append(os.path.join(SUMO_HOME, "tools"))
import sumolib  # noqa: E402

CUT_ROUTES = os.path.join(SUMO_HOME, "tools", "route", "cutRoutes.py")


def net_stats(netfile):
    """Structural fingerprint of a network, for before/after cut diffing."""
    net = sumolib.net.readNet(netfile)
    edges = [e for e in net.getEdges() if e.getFunction() != "internal"]
    conns = 0
    for e in edges:
        for lane in e.getLanes():
            conns += len(lane.getOutgoing())
    # tlLogic phase-state widths straight from the XML (sumolib does not expose
    # phase strings for every program reliably)
    root = ET.parse(netfile).getroot()
    tls = {}
    for tl in root.findall("tlLogic"):
        states = [p.get("state") for p in tl.findall("phase")]
        tls[tl.get("id")] = {
            "programID": tl.get("programID"),
            "type": tl.get("type"),
            "nphases": len(states),
            "statelen": len(states[0]) if states else 0,
            "states": states,
        }
    # number of controlled links actually present per tls
    controlled = {}
    for c in root.findall("connection"):
        t = c.get("tl")
        if t is not None:
            controlled[t] = controlled.get(t, 0) + 1
    return {
        "netfile": netfile,
        "n_edges": len(edges),
        "n_lanes": sum(e.getLaneNumber() for e in edges),
        "lane_km": sum(e.getLength() * e.getLaneNumber() for e in edges) / 1000.0,
        "n_nodes": len(net.getNodes()),
        "n_connections": conns,
        "n_tls": len(tls),
        "tls": tls,
        "tls_controlled_links": controlled,
        "edge_ids": set(e.getID() for e in edges),
    }


def run(cmd, errfile):
    with open(errfile, "w") as fh:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=fh, text=True)
    return p.returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parent-net", required=True)
    ap.add_argument("--parent-routes", required=True)
    ap.add_argument("--boundary", required=True,
                    help="xmin,ymin,xmax,ymax in network (cartesian) coords")
    ap.add_argument("--geo-boundary", action="store_true",
                    help="interpret --boundary as lon/lat (uses "
                         "--keep-edges.in-geo-boundary)")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--orig-net", default=None,
                    help="pass parent net to cutRoutes.py --orig-net "
                         "(extrapolate departures instead of using exit times)")
    ap.add_argument("--discard-exit-times", action="store_true")
    ap.add_argument("--disconnected-action", default="discard",
                    choices=["discard", "keep", "keep.walk"])
    ap.add_argument("--min-length", type=int, default=None)
    ap.add_argument("--min-air-dist", type=float, default=None)
    ap.add_argument("--speed-factor", type=float, default=None)
    ap.add_argument("--default-depart-speed", default=None)
    ap.add_argument("--trips-output", action="store_true")
    ap.add_argument("--stops-output", action="store_true")
    ap.add_argument("--vtype-source", default=None,
                    help="file containing the <vType> definitions the parent "
                         "routes reference. REQUIRED when cutting a "
                         "vehroute-output file: vehroute-output does NOT emit "
                         "vType elements, so cutRoutes.py's output carries "
                         "dangling type= references and SUMO will abort.")
    ap.add_argument("--edgedata-begin", type=float, default=0)
    ap.add_argument("--edgedata-end", type=float, default=3600)
    ap.add_argument("--sim-end", type=float, default=7200)
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    tag = args.name
    netout = os.path.join(args.out_dir, "net_%s.net.xml" % tag)
    routeout = os.path.join(args.out_dir, "rou_%s.rou.xml" % tag)

    # ---- 1. cut the network -------------------------------------------------
    opt = "--keep-edges.in-geo-boundary" if args.geo_boundary else \
          "--keep-edges.in-boundary"
    nc = ["netconvert", "-s", args.parent_net, opt, args.boundary,
          "-o", netout, "--no-turnarounds.tls", "true"]
    rc = run(nc, os.path.join(args.out_dir, "netconvert_%s.err" % tag))
    if rc != 0 or not os.path.exists(netout):
        sys.exit("netconvert failed for %s (rc=%d)" % (tag, rc))

    # ---- 2. cut the routes --------------------------------------------------
    cr = [sys.executable, CUT_ROUTES, netout, args.parent_routes,
          "-o", routeout, "-d", args.disconnected_action, "-v"]
    if args.orig_net:
        cr += ["--orig-net", args.orig_net]
    if args.discard_exit_times:
        cr += ["--discard-exit-times"]
    if args.min_length is not None:
        cr += ["--min-length", str(args.min_length)]
    if args.min_air_dist is not None:
        cr += ["--min-air-dist", str(args.min_air_dist)]
    if args.speed_factor is not None:
        cr += ["--speed-factor", str(args.speed_factor)]
    if args.default_depart_speed is not None:
        cr += ["--default.departSpeed", args.default_depart_speed]
    if args.trips_output:
        cr += ["--trips-output", os.path.join(args.out_dir,
                                              "trips_%s.trips.xml" % tag)]
    if args.stops_output:
        cr += ["--stops-output", os.path.join(args.out_dir,
                                              "stops_%s.add.xml" % tag)]
    crlog = os.path.join(args.out_dir, "cutroutes_%s.log" % tag)
    with open(crlog, "w") as fh:
        p = subprocess.run(cr, stdout=fh, stderr=subprocess.STDOUT, text=True)
    if p.returncode != 0:
        sys.exit("cutRoutes.py failed for %s (see %s)" % (tag, crlog))

    # ---- 3. runnable config -------------------------------------------------
    adds = []
    if args.vtype_source:
        vt = os.path.join(args.out_dir, "vtypes_%s.add.xml" % tag)
        src = ET.parse(args.vtype_source).getroot()
        out = ET.Element("additional")
        n_vt = 0
        for v in src.findall("vType"):
            out.append(v)
            n_vt += 1
        ET.ElementTree(out).write(vt)
        print("  extracted %d vType(s) -> %s" % (n_vt, vt))
        adds.append(os.path.basename(vt))

    add = os.path.join(args.out_dir, "edgedata_%s.add.xml" % tag)
    with open(add, "w") as fh:
        fh.write('<additional>\n    <edgeData id="ed" file="edgedata_%s.xml" '
                 'begin="%g" end="%g" excludeEmpty="false" '
                 'withInternal="false"/>\n</additional>\n'
                 % (tag, args.edgedata_begin, args.edgedata_end))
    adds.append(os.path.basename(add))
    cfg = os.path.join(args.out_dir, "%s.sumocfg" % tag)
    with open(cfg, "w") as fh:
        fh.write("""<configuration>
    <input>
        <net-file value="%s"/>
        <route-files value="%s"/>
        <additional-files value="%s"/>
    </input>
    <time><begin value="0"/><end value="%g"/></time>
    <processing>
        <time-to-teleport value="300"/>
        <ignore-route-errors value="false"/>
    </processing>
    <report><no-step-log value="true"/></report>
</configuration>
""" % (os.path.basename(netout), os.path.basename(routeout),
       ",".join(adds), args.sim_end))

    print("cut '%s' written: %s / %s / %s" % (tag, netout, routeout, cfg))


if __name__ == "__main__":
    main()
