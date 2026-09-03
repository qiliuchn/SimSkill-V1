#!/usr/bin/env python3
"""Build a straight walkable corridor test section for pedestrian FD measurement.

Geometry (all along the x-axis, so FCD x = longitudinal, y = lateral):

    A(-60,0) --EA--> B(0,0) --EM--> C(200,0) --EO--> D(260,0)
      wide feed        measurement section        exit / optional gate

The road is one-way so that each edge carries EXACTLY ONE sidewalk lane -- this is
what makes counterflow (H3) possible: opposing pedestrians must share one lane
instead of being routed onto two separate sidewalks of a bidirectional street pair.

Sidewalk width is set per edge with the netconvert edge attribute `sidewalkWidth`,
then the compiled net is verified (width + allow="pedestrian") -- never trusted from
the input files.
"""
import argparse
import os
import subprocess
import sys
import xml.etree.ElementTree as ET


def build(out_net, w_feed, w_mid, w_exit, mid_len=200.0, feed_len=60.0, exit_len=60.0,
          stripe_width=None, verbose=False, speed_exit=13.89):
    d = os.path.dirname(os.path.abspath(out_net))
    os.makedirs(d, exist_ok=True)
    base = os.path.splitext(os.path.splitext(os.path.basename(out_net))[0])[0]
    nod = os.path.join(d, base + ".nod.xml")
    edg = os.path.join(d, base + ".edg.xml")

    with open(nod, "w") as f:
        f.write("<nodes>\n")
        for nid, x in [("A", -feed_len), ("B", 0.0), ("C", mid_len), ("D", mid_len + exit_len)]:
            f.write('  <node id="%s" x="%.2f" y="0.00" type="priority"/>\n' % (nid, x))
        f.write("</nodes>\n")

    with open(edg, "w") as f:
        f.write("<edges>\n")
        for eid, a, b, w, sp in [("EA", "A", "B", w_feed, 13.89), ("EM", "B", "C", w_mid, 13.89),
                                 ("EO", "C", "D", w_exit, speed_exit)]:
            f.write('  <edge id="%s" from="%s" to="%s" numLanes="1" speed="%.4f" sidewalkWidth="%.4f"/>\n'
                    % (eid, a, b, sp, w))
        f.write("</edges>\n")

    cmd = ["netconvert", "-n", nod, "-e", edg,
           "--sidewalks.guess", "--sidewalks.guess.min-speed", "0.05",
           "--crossings.guess", "--walkingareas",
           "--offset.disable-normalization",
           "--no-turnarounds", "--no-internal-links", "false",
           "-o", out_net]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stdout + r.stderr)
        raise SystemExit("netconvert failed for %s" % out_net)
    return verify(out_net, {"EA": w_feed, "EM": w_mid, "EO": w_exit}, verbose=verbose)


def verify(net, expect, verbose=False):
    """Verify sidewalk lane widths and pedestrian permission ON THE COMPILED NET."""
    root = ET.parse(net).getroot()
    info = {"net": net, "lanes": {}, "ok": True, "errors": []}
    for e in root.findall("edge"):
        eid = e.get("id")
        for ln in e.findall("lane"):
            allow = (ln.get("allow") or "")
            if "pedestrian" in allow.split():
                info["lanes"][ln.get("id")] = {
                    "edge": eid, "function": e.get("function"),
                    "width": float(ln.get("width")) if ln.get("width") else None,
                    "allow": allow, "length": float(ln.get("length")),
                }
    for eid, w in expect.items():
        lid = eid + "_0"
        if lid not in info["lanes"]:
            info["ok"] = False
            info["errors"].append("no pedestrian lane %s in compiled net" % lid)
            continue
        got = info["lanes"][lid]["width"]
        if got is None or abs(got - w) > 0.011:
            info["ok"] = False
            info["errors"].append("%s width %s != requested %.4f" % (lid, got, w))
    # y-centre of the measurement sidewalk lane, needed for lateral-position analysis
    for e in root.findall("edge"):
        if e.get("id") == "EM":
            ln = e.find("lane")
            shp = [p.split(",") for p in ln.get("shape").split()]
            info["EM_y_center"] = sum(float(p[1]) for p in shp) / len(shp)
            info["EM_length"] = float(ln.get("length"))
            xs = [float(p[0]) for p in shp]
            info["EM_x0"], info["EM_x1"] = min(xs), max(xs)
    if verbose:
        for lid, v in sorted(info["lanes"].items()):
            print("  %-14s edge=%-12s func=%-12s width=%s allow=%s len=%.2f"
                  % (lid, v["edge"], v["function"], v["width"], v["allow"], v["length"]))
    return info


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--w-feed", type=float, default=6.0)
    ap.add_argument("--w-mid", type=float, required=True)
    ap.add_argument("--w-exit", type=float, default=6.0)
    ap.add_argument("--mid-len", type=float, default=200.0)
    a = ap.parse_args()
    info = build(a.out, a.w_feed, a.w_mid, a.w_exit, mid_len=a.mid_len, verbose=True)
    print("OK" if info["ok"] else "FAIL " + "; ".join(info["errors"]))
    print("EM y-centre = %.3f  EM length = %.2f" % (info["EM_y_center"], info["EM_length"]))
