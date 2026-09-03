#!/usr/bin/env python3
"""Applied network: transit-station / venue egress.

    V(-200,0) --EPLAZA(w=12m,140m)--> P(-60,0) --EBOT(w=Wb,60m)--> J(0,0) --EFAR(w=4m,80m)--> F(80,0)
                                                                     |
                                            N(0,150) <--ENS/ESN--> J <--> S(0,-150)     two-way vehicle street

The E-W pedestrian corridor is ONE-WAY for vehicles so it carries exactly one
sidewalk (south side); pedestrians walking V->F must therefore use the marked
crossing over the N-S vehicle street at the signalised node J.

The signal program is REPLACED in the compiled net by an explicit hand-built
4-phase program, so no TraCI/programID juggling is needed; every link index used to
write it is re-derived from that compile's own <connection> entries, never hardcoded.
--offset.disable-normalization keeps the compiled coordinates equal to the authored
ones, so FCD x is directly interpretable as distance along the egress path.
"""
import argparse
import os
import subprocess
import sys
import xml.etree.ElementTree as ET


def build(outdir, w_bottleneck, ped_green=20, veh_green=40, yellow=4, allred=2,
          w_plaza=12.0, w_far=4.0, verbose=False):
    os.makedirs(outdir, exist_ok=True)
    nod = os.path.join(outdir, "eg.nod.xml")
    edg = os.path.join(outdir, "eg.edg.xml")
    net = os.path.join(outdir, "egress.net.xml")

    with open(nod, "w") as f:
        f.write("<nodes>\n")
        f.write('  <node id="V" x="-200" y="0" type="priority"/>\n')
        f.write('  <node id="P" x="-60" y="0" type="priority"/>\n')
        f.write('  <node id="J" x="0" y="0" type="traffic_light"/>\n')
        f.write('  <node id="F" x="80" y="0" type="priority"/>\n')
        f.write('  <node id="S" x="0" y="-150" type="priority"/>\n')
        f.write('  <node id="N" x="0" y="150" type="priority"/>\n')
        f.write("</nodes>\n")

    with open(edg, "w") as f:
        f.write("<edges>\n")
        f.write('  <edge id="EPLAZA" from="V" to="P" numLanes="1" speed="13.89" sidewalkWidth="%.4f"/>\n' % w_plaza)
        f.write('  <edge id="EBOT"   from="P" to="J" numLanes="1" speed="13.89" sidewalkWidth="%.4f"/>\n' % w_bottleneck)
        f.write('  <edge id="EFAR"   from="J" to="F" numLanes="1" speed="13.89" sidewalkWidth="%.4f"/>\n' % w_far)
        f.write('  <edge id="SJ" from="S" to="J" numLanes="1" speed="13.89" sidewalkWidth="2.0"/>\n')
        f.write('  <edge id="JS" from="J" to="S" numLanes="1" speed="13.89" sidewalkWidth="2.0"/>\n')
        f.write('  <edge id="NJ" from="N" to="J" numLanes="1" speed="13.89" sidewalkWidth="2.0"/>\n')
        f.write('  <edge id="JN" from="J" to="N" numLanes="1" speed="13.89" sidewalkWidth="2.0"/>\n')
        f.write("</edges>\n")

    cmd = ["netconvert", "-n", nod, "-e", edg,
           "--sidewalks.guess", "--crossings.guess", "--walkingareas",
           "--offset.disable-normalization",
           "--no-turnarounds", "--tls.default-type", "static", "-o", net]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stdout + r.stderr)
        raise SystemExit("netconvert failed")

    info = inspect(net)
    set_program(net, info, ped_green, veh_green, yellow, allred)
    info = inspect(net)
    info["ped_green_requested"] = ped_green
    info["veh_green_requested"] = veh_green
    info["cycle"] = veh_green + yellow + ped_green + allred
    info["verification"] = verify_program(info)
    if verbose:
        print(_fmt(info))
    return info


def _fmt(info):
    L = ["net: %s" % info["net"]]
    for lid, v in sorted(info["ped_lanes"].items()):
        L.append("  ped lane %-16s edge=%-12s func=%-12s width=%s allow=%s"
                 % (lid, v["edge"], v["function"], v["width"], v["allow"]))
    L.append("  crossings: %s" % info["crossings"])
    L.append("  crossing links: %s ; NS vehicle links: %s ; EW vehicle links: %s"
             % (info["crossing_links"], info["ns_vehicle_links"], info["ew_vehicle_links"]))
    L.append("  pedestrian route uses crossing %s (link %s)"
             % (info.get("used_crossing"), info.get("used_crossing_link")))
    for i, p in enumerate(info["phases"]):
        L.append("  phase %d dur=%s state=%s  pedGreen=%s nsVehGreen=%s"
                 % (i, p["duration"], p["state"], p["ped_green"], p["ns_veh_green"]))
    L.append("  verification: %s" % info.get("verification"))
    return "\n".join(L)


def inspect(net):
    root = ET.parse(net).getroot()
    info = {"net": net, "ped_lanes": {}, "crossings": {}, "walkingareas": []}
    for e in root.findall("edge"):
        eid, fn = e.get("id"), e.get("function")
        if fn == "crossing":
            info["crossings"][eid] = e.get("crossingEdges")
        if fn == "walkingarea":
            info["walkingareas"].append(eid)
        for ln in e.findall("lane"):
            if "pedestrian" in (ln.get("allow") or "").split():
                info["ped_lanes"][ln.get("id")] = {
                    "edge": eid, "function": fn,
                    "width": float(ln.get("width")) if ln.get("width") else None,
                    "allow": ln.get("allow"), "length": float(ln.get("length"))}
    # crossing vs vehicle link indices, derived from the compiled net's connections
    cross_links, veh_links, cross_link_edge = [], [], {}
    for c in root.findall("connection"):
        if c.get("tl") is None:
            continue
        idx = int(c.get("linkIndex"))
        to = c.get("to")
        if to in info["crossings"]:
            cross_links.append(idx)
            cross_link_edge[idx] = to
        else:
            veh_links.append(idx)
    info["crossing_links"] = sorted(set(cross_links))
    info["vehicle_links"] = sorted(set(veh_links))
    info["crossing_link_edge"] = cross_link_edge
    # Which crossing does a pedestrian walking EBOT_0 -> EFAR_0 actually use?
    # Derived from the COMPILED net's geometry (never hardcoded by arm name): the
    # sidewalk of a one-way W->E street sits on its right/south side, so the
    # relevant crossing is the one whose shape midpoint lies nearest the midpoint
    # between EBOT_0's end and EFAR_0's start.
    def _shape(lane_id):
        for e in root.findall("edge"):
            for ln in e.findall("lane"):
                if ln.get("id") == lane_id:
                    return [tuple(float(v) for v in p.split(",")[:2])
                            for p in ln.get("shape").split()]
        return None
    sb, sf = _shape("EBOT_0"), _shape("EFAR_0")
    if sb and sf:
        tx = (sb[-1][0] + sf[0][0]) / 2.0
        ty = (sb[-1][1] + sf[0][1]) / 2.0
        best, bestd = None, 1e18
        for cid in info["crossings"]:
            sc = _shape(cid + "_0")
            if not sc:
                continue
            mx = sum(p[0] for p in sc) / len(sc)
            my = sum(p[1] for p in sc) / len(sc)
            d = (mx - tx) ** 2 + (my - ty) ** 2
            if d < bestd:
                best, bestd = cid, d
        info["used_crossing"] = best
        info["used_crossing_link"] = next((i for i, ed in cross_link_edge.items() if ed == best), None)
    # Vehicle movements on the crossed (N-S) street, from the compiled connections
    ns_veh = []
    ew_veh = []
    for c in root.findall("connection"):
        if c.get("tl") is None:
            continue
        idx = int(c.get("linkIndex"))
        if c.get("to") in info["crossings"]:
            continue
        (ns_veh if c.get("from") in ("SJ", "NJ") else ew_veh).append(idx)
        if c.get("from") in ("SJ", "NJ") and c.get("dir") == "s":
            info.setdefault("ns_through_links", []).append(idx)
    info["ns_vehicle_links"] = sorted(set(ns_veh))
    info["ns_through_links"] = sorted(set(info.get("ns_through_links", [])))
    info["ew_vehicle_links"] = sorted(set(ew_veh))
    ns_cross = [cid for cid, ce in info["crossings"].items()
                if ce and set(ce.split()) & {"SJ", "JS", "NJ", "JN"}]
    info["ns_crossings"] = ns_cross
    info["ns_crossing_links"] = sorted(i for i, ed in cross_link_edge.items() if ed in ns_cross)
    tl = root.find("tlLogic")
    info["tls_id"] = tl.get("id") if tl is not None else None
    info["program_id"] = tl.get("programID") if tl is not None else None
    phases = []
    uc = info.get("used_crossing_link")
    if tl is not None:
        for p in tl.findall("phase"):
            st = p.get("state")
            pg = (uc is not None and st[uc] in "gG")
            vg = any(st[i] in "gG" for i in info["ns_vehicle_links"])
            phases.append({"duration": float(p.get("duration")), "state": st,
                           "ped_green": pg, "ns_veh_green": vg})
    info["phases"] = phases
    info["state_len"] = len(phases[0]["state"]) if phases else 0
    info["n_links_total"] = len(info["crossing_links"]) + len(info["vehicle_links"])
    return info


def set_program(net, info, ped_green, veh_green, yellow, allred):
    """Replace the compiled net's tlLogic with an explicit 4-phase program.

    netconvert's own guessed program interleaves an E-W vehicle green that carries
    no demand here, which would waste a large share of the cycle and corrupt the
    "how much green does the crossing get" experiment.  Following the
    build-pedestrian-crossings-and-phasing skill's advice not to trust generated
    phasing, the program is written out by hand from link indices re-derived from
    THIS compile's connections.

    Phase 0  N-S vehicles green, pedestrian crossing red   (veh_green s)
    Phase 1  N-S vehicles yellow                            (yellow s)
    Phase 2  all vehicles red, N-S crossings green          (ped_green s)
    Phase 3  all red clearance                              (allred s)
    """
    n = info["n_links_total"]
    ns_v = set(info["ns_vehicle_links"])
    ns_c = set(info["ns_crossing_links"])

    ns_thru = set(info.get("ns_through_links", []))

    def state(veh_char, cross_char):
        s = []
        for i in range(n):
            if i in ns_v:
                s.append(veh_char if (i in ns_thru or veh_char != "G") else "g")
            elif i in ns_c:
                s.append(cross_char)
            else:
                s.append("r")
        return "".join(s)

    phases = [(veh_green, state("G", "r")), (yellow, state("y", "r")),
              (ped_green, state("r", "G")), (allred, state("r", "r"))]
    tree = ET.parse(net)
    root = tree.getroot()
    tl = root.find("tlLogic")
    for p in list(tl.findall("phase")):
        tl.remove(p)
    for dur, st in phases:
        ET.SubElement(tl, "phase", {"duration": str(dur), "state": st})
    tl.set("offset", "0")
    tree.write(net, encoding="UTF-8", xml_declaration=True)


def verify_program(info):
    """Static verification on the COMPILED net: the pedestrian crossing is never
    green at the same time as any conflicting N-S vehicle movement, and it does
    get a green phase at all."""
    uc = info.get("used_crossing_link")
    v = {"used_crossing": info.get("used_crossing"), "used_crossing_link": uc,
         "has_ped_green_phase": False, "conflicting_green_phases": [],
         "ped_green_seconds": 0.0, "ns_veh_green_seconds": 0.0,
         "cycle_seconds": sum(p["duration"] for p in info["phases"])}
    for i, p in enumerate(info["phases"]):
        if p["ped_green"]:
            v["has_ped_green_phase"] = True
            v["ped_green_seconds"] += p["duration"]
            if p["ns_veh_green"]:
                v["conflicting_green_phases"].append(i)
        if p["ns_veh_green"]:
            v["ns_veh_green_seconds"] += p["duration"]
    v["ok"] = v["has_ped_green_phase"] and not v["conflicting_green_phases"]
    return v


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--w-bottleneck", type=float, required=True)
    ap.add_argument("--ped-green", type=int, default=20)
    ap.add_argument("--veh-green", type=int, default=40)
    a = ap.parse_args()
    build(a.outdir, a.w_bottleneck, a.ped_green, a.veh_green, verbose=True)
