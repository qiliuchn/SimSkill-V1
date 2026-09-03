#!/usr/bin/env python3
"""
Build a freeway toll plaza network from hand-authored plain XML
(.typ / .nod / .edg / .con) and compile it with netconvert.

Topology (left to right, +x direction, right-hand traffic so lane index 0 = rightmost
= most negative y):

    app (2 lanes, 1200 m mainline storage)
      -> fan  (c lanes, 200 m, free lane changing: the fan-out taper)
      -> lock (c lanes,  40 m, changeLeft/changeRight = "none": booth choice is
               committed here, no weaving inside the plaza)
      -> chin_i  (1 lane, ~50 m diagonal, one per booth channel)
      -> booth_i (1 lane,   30 m STRAIGHT booth island segment)   <-- the server
      -> chout_i (1 lane, ~100 m diagonal)
      -> post (c lanes, 300 m, fan-in)
      -> exit (2 lanes, 700 m)

Every booth-channel choice is expressed with explicit <connection> elements
(lock lane i -> chin_i, chout_i -> post lane i); nothing is left to netconvert's
connection guessing.

Usage:
  python3 build_plaza_network.py --booths 6 --out-dir <dir> [--etc-booths 2]
"""
import argparse
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

LANE_Y_SPACING = 4.0  # m between booth channel centrelines (wide -> room for islands)

# x coordinates of the longitudinal control points
X_ORG, X_FAN_S, X_LOCK_S, X_LOCK_E = 0.0, 1200.0, 1340.0, 1440.0
X_BOOTH_S, X_BOOTH_E, X_POST_S, X_DROP, X_END = 1560.0, 1590.0, 1700.0, 2000.0, 2700.0


def find_bin(name):
    p = shutil.which(name)
    if p:
        return p
    sumo = shutil.which("sumo")
    if sumo:
        cand = os.path.join(os.path.dirname(sumo), name)
        if os.path.exists(cand):
            return cand
    home = os.environ.get("SUMO_HOME")
    if home:
        cand = os.path.join(home, "bin", name)
        if os.path.exists(cand):
            return cand
    raise RuntimeError("cannot locate %s" % name)


def booth_y(i, c):
    return (i - (c - 1) / 2.0) * LANE_Y_SPACING


def write_typ(path):
    with open(path, "w") as f:
        f.write("""<?xml version="1.0" encoding="UTF-8"?>
<types>
    <!-- 100 km/h mainline -->
    <type id="mainline"    priority="12" numLanes="2" speed="27.78"/>
    <!-- 50 km/h plaza fan-out / fan-in -->
    <type id="plaza_taper" priority="10" numLanes="2" speed="13.89"/>
    <!-- 30 km/h channelised approach to the booth islands -->
    <type id="plaza_lock"  priority="10" numLanes="1" speed="8.33"/>
    <!-- booth island: 20 km/h, this is where the service stop happens -->
    <type id="booth"       priority="10" numLanes="1" speed="5.56"/>
</types>
""")


def write_nod(path, c):
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<nodes>"]
    lines.append('    <node id="n_org"    x="%g" y="0" type="priority"/>' % X_ORG)
    lines.append('    <node id="n_fan_s"  x="%g" y="0" type="priority"/>' % X_FAN_S)
    lines.append('    <node id="n_lock_s" x="%g" y="0" type="priority"/>' % X_LOCK_S)
    lines.append('    <node id="n_lock_e" x="%g" y="0" type="priority"/>' % X_LOCK_E)
    for i in range(c):
        y = booth_y(i, c)
        lines.append('    <node id="n_b%d_s"  x="%g" y="%g" type="priority"/>' % (i, X_BOOTH_S, y))
        lines.append('    <node id="n_b%d_e"  x="%g" y="%g" type="priority"/>' % (i, X_BOOTH_E, y))
    lines.append('    <node id="n_post"   x="%g" y="0" type="priority"/>' % X_POST_S)
    lines.append('    <node id="n_drop"   x="%g" y="0" type="zipper"/>' % X_DROP)
    lines.append('    <node id="n_end"    x="%g" y="0" type="priority"/>' % X_END)
    lines.append("</nodes>")
    open(path, "w").write("\n".join(lines) + "\n")


def write_edg(path, c, etc_booths):
    """etc_booths: set of booth indices restricted to vClass custom1 (transponder-equipped)."""
    L = ['<?xml version="1.0" encoding="UTF-8"?>', "<edges>"]
    L.append('    <edge id="app"  from="n_org"    to="n_fan_s"  type="mainline"/>')
    # fan-out taper: c lanes, free lane changing (vehicles sort themselves here)
    L.append('    <edge id="fan"  from="n_fan_s"  to="n_lock_s" type="plaza_taper" numLanes="%d"/>' % c)
    # lock: c lanes, NO lane changing in either direction -> no weaving inside the plaza
    L.append('    <edge id="lock" from="n_lock_s" to="n_lock_e" type="plaza_taper" numLanes="%d" speed="8.33">' % c)
    for i in range(c):
        # NB: changeLeft="none" is a netconvert ERROR ("Unknown vehicle class 'none'"),
        # changeLeft="" is an error, and changeLeft="ignoring" compiles but is silently
        # dropped from the .net.xml (no-op).  "authority" is the working idiom: only the
        # authority vClass (never used in this scenario) may change lanes here.
        L.append('        <lane index="%d" changeLeft="authority" changeRight="authority"/>' % i)
    L.append("    </edge>")
    for i in range(c):
        perm = ' allow="custom1"' if i in etc_booths else ""
        L.append('    <edge id="chin_%d"  from="n_lock_e" to="n_b%d_s" type="plaza_lock"%s/>' % (i, i, perm))
        L.append('    <edge id="booth_%d" from="n_b%d_s"  to="n_b%d_e" type="booth"%s/>' % (i, i, i, perm))
        L.append('    <edge id="chout_%d" from="n_b%d_e"  to="n_post"  type="plaza_lock" speed="13.89"%s/>' % (i, i, perm))
    L.append('    <edge id="post" from="n_post"   to="n_drop"   type="plaza_taper" numLanes="%d" speed="22.22"/>' % c)
    L.append('    <edge id="exit" from="n_drop"   to="n_end"    type="mainline"/>')
    L.append("</edges>")
    open(path, "w").write("\n".join(L) + "\n")


def write_con(path, c):
    L = ['<?xml version="1.0" encoding="UTF-8"?>', "<connections>"]
    L.append("    <!-- 2-lane mainline fans out into c taper lanes; no crossing connections -->")
    half = c // 2
    for k in range(c):
        frm = 0 if k < half else 1
        L.append('    <connection from="app" to="fan" fromLane="%d" toLane="%d"/>' % (frm, k))
    L.append("    <!-- taper -> lock: straight through, one-to-one -->")
    for k in range(c):
        L.append('    <connection from="fan" to="lock" fromLane="%d" toLane="%d"/>' % (k, k))
    L.append("    <!-- lock lane i is the ONLY way into booth channel i -->")
    for i in range(c):
        L.append('    <connection from="lock" to="chin_%d" fromLane="%d" toLane="0"/>' % (i, i))
        L.append('    <connection from="chin_%d" to="booth_%d" fromLane="0" toLane="0"/>' % (i, i))
        L.append('    <connection from="booth_%d" to="chout_%d" fromLane="0" toLane="0"/>' % (i, i))
        L.append('    <connection from="chout_%d" to="post" fromLane="0" toLane="%d"/>' % (i, i))
    L.append("    <!-- fan-in: c post lanes back down to 2 exit lanes -->")
    for k in range(c):
        L.append('    <connection from="post" to="exit" fromLane="%d" toLane="%d"/>' % (k, 0 if k < half else 1))
    L.append("</connections>")
    open(path, "w").write("\n".join(L) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--booths", type=int, default=6)
    ap.add_argument("--etc-booths", type=int, default=0,
                    help="number of RIGHTMOST booths reserved for vClass custom1 (ETC)")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--name", default=None)
    args = ap.parse_args()

    c = args.booths
    name = args.name or ("plaza_c%d" % c + ("_etc%d" % args.etc_booths if args.etc_booths else ""))
    d = os.path.abspath(args.out_dir)
    os.makedirs(d, exist_ok=True)
    etc = set(range(args.etc_booths))

    typ = os.path.join(d, name + ".typ.xml")
    nod = os.path.join(d, name + ".nod.xml")
    edg = os.path.join(d, name + ".edg.xml")
    con = os.path.join(d, name + ".con.xml")
    net = os.path.join(d, name + ".net.xml")
    write_typ(typ)
    write_nod(nod, c)
    write_edg(edg, c, etc)
    write_con(con, c)

    cmd = [find_bin("netconvert"),
           "--type-files", typ, "--node-files", nod, "--edge-files", edg,
           "--connection-files", con, "-o", net,
           "--no-turnarounds", "true",
           "--offset.disable-normalization", "true",
           "--plain-output-prefix", os.path.join(d, name + "_dump")]
    r = subprocess.run(cmd, capture_output=True, text=True)
    sys.stderr.write(r.stderr)
    if r.returncode != 0:
        sys.exit("netconvert failed")
    print("NETCONVERT_STDERR_BYTES=%d" % len(r.stderr.strip()))
    print("net written:", net)

    # ---- verification straight off the compiled net ----
    root = ET.parse(net).getroot()
    edges = {e.get("id"): e for e in root.findall("edge") if e.get("function") != "internal"}
    print("\n--- compiled edges (id, numLanes, length_m, speed, allow) ---")
    for eid in ["app", "fan", "lock"] + sum([["chin_%d" % i, "booth_%d" % i, "chout_%d" % i] for i in range(c)], []) + ["post", "exit"]:
        e = edges[eid]
        lanes = e.findall("lane")
        allow = lanes[0].get("allow") or "(all)"
        print("  %-9s lanes=%d length=%7.2f speed=%5.2f allow=%s" %
              (eid, len(lanes), float(lanes[0].get("length")), float(lanes[0].get("speed")), allow))

    print("\n--- lock lane change permissions (must be changeLeft/changeRight = none) ---")
    for ln in edges["lock"].findall("lane"):
        print("  %s changeLeft=%r changeRight=%r" % (ln.get("id"), ln.get("changeLeft"), ln.get("changeRight")))

    print("\n--- connections into/out of every booth channel ---")
    conns = root.findall("connection")
    ok = True
    for i in range(c):
        into = [x for x in conns if x.get("to") == "chin_%d" % i]
        outof = [x for x in conns if x.get("from") == "chout_%d" % i]
        print("  chin_%d  <- %s ; chout_%d -> %s" %
              (i, [(x.get("from"), x.get("fromLane"), x.get("state")) for x in into],
               i, [(x.get("to"), x.get("toLane"), x.get("state")) for x in outof]))
        into = [x for x in into if not x.get("from").startswith(":")]
        if len(into) != 1 or into[0].get("from") != "lock" or int(into[0].get("fromLane")) != i:
            ok = False
    print("\nEXCLUSIVE_LOCK_LANE_TO_BOOTH_MAPPING_OK=%s" % ok)

    napp = [(x.get("fromLane"), x.get("toLane")) for x in conns if x.get("from") == "app" and x.get("to") == "fan"]
    print("app->fan connections (fromLane,toLane): %s" % sorted(napp))
    npe = [(x.get("fromLane"), x.get("toLane"), x.get("state")) for x in conns if x.get("from") == "post" and x.get("to") == "exit"]
    print("post->exit connections (fromLane,toLane,state): %s" % sorted(npe))


if __name__ == "__main__":
    main()
