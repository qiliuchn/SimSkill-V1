"""
Build one standalone SUMO network + demand + signal program per inventory site.

Networks are written as plain XML (nodes / edges / connections) and compiled by
netconvert -- the technique from the `create-single-intersection` skill, extended
with EXPLICIT connections so that a dedicated left-turn bay is a genuinely
separate controlled link (the requirement flagged by
`compare-left-turn-signal-treatments`).

Signal programs are generated PROGRAMMATICALLY from the compiled net's own
linkIndex/dir mapping -- never hand-typed -- again per
`compare-left-turn-signal-treatments`, and an annotated verification table is
written to <site>/phases.txt for every signalized site.

Outputs, per site, under <root>/<site>/:
    <site>.net.xml   <site>.rou.xml   <site>.add.xml   phases.txt   webster.json
"""
import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from inventory import (SITES, ARM_ANGLE, MPH, approach_volumes, arms)

MAJOR_ARM_LEN = 320.0
MINOR_ARM_LEN = 260.0
SAT_FLOW = 1900.0          # veh/h/lane, protected saturation flow (HCM-style default)
SAT_FLOW_PERM_LEFT = 400.0  # veh/h effective for a permissive left against opposing flow
LOST_TIME_PER_PHASE = 4.0   # s
YELLOW = 3.0
ALLRED = 1.0

NODE_TYPE = {"4SG": "traffic_light", "4ST": "priority_stop", "3ST": "priority_stop"}


def find_bin(name):
    p = shutil.which(name)
    if p:
        return p
    s = shutil.which("sumo")
    if s:
        c = os.path.join(os.path.dirname(s), name)
        if os.path.isfile(c):
            return c
    sh = os.environ.get("SUMO_HOME")
    if sh:
        c = os.path.join(sh, "bin", name)
        if os.path.isfile(c):
            return c
    sys.exit("cannot find %s" % name)


def pos(angle_deg, length):
    r = math.radians(angle_deg)
    return round(length * math.sin(r), 2), round(length * math.cos(r), 2)


def turn_type(from_arm, to_arm):
    """Turn classification for an approach arriving from `from_arm`."""
    heading = (ARM_ANGLE[from_arm] + 180.0) % 360.0
    rel = (ARM_ANGLE[to_arm] - heading) % 360.0
    if rel > 180.0:
        rel -= 360.0
    if abs(rel) <= 10.0:
        return "T"
    if abs(rel) >= 170.0:
        return "U"
    return "L" if rel < 0 else "R"


def site_geometry(site):
    """in-lane / out-lane counts and left-bay flags per arm."""
    geo = {}
    major_bay = site["control"] == "4SG"       # signalized sites get a major-road left bay
    for a in arms(site):
        is_major = a in ("N", "S")
        lanes = site["lanes_major"] if is_major else site["lanes_minor"]
        bay = 1 if (is_major and major_bay) else 0
        geo[a] = dict(
            is_major=is_major,
            through=lanes,
            bay=bay,
            lanes_in=lanes + bay,
            lanes_out=lanes,
            length=MAJOR_ARM_LEN if is_major else MINOR_ARM_LEN,
            speed=site["speed_mph"] * MPH,
        )
    return geo


def write_plain_xml(site, geo, d):
    nodes = ['<?xml version="1.0" encoding="UTF-8"?>', "<nodes>"]
    nodes.append('    <node id="center" x="0" y="0" type="%s"/>' % NODE_TYPE[site["control"]])
    for a in arms(site):
        x, y = pos(ARM_ANGLE[a], geo[a]["length"])
        nodes.append('    <node id="%s" x="%s" y="%s" type="priority"/>' % (a, x, y))
    nodes.append("</nodes>")

    edges = ['<?xml version="1.0" encoding="UTF-8"?>', "<edges>"]
    for a in arms(site):
        g = geo[a]
        prio = 10 if g["is_major"] else 1     # edge priority => major road has right of way
        edges.append('    <edge id="in_%s" from="%s" to="center" numLanes="%d" speed="%.2f" priority="%d"/>'
                     % (a, a, g["lanes_in"], g["speed"], prio))
        edges.append('    <edge id="out_%s" from="center" to="%s" numLanes="%d" speed="%.2f" priority="%d"/>'
                     % (a, a, g["lanes_out"], g["speed"], prio))
    edges.append("</edges>")

    cons = ['<?xml version="1.0" encoding="UTF-8"?>', "<connections>"]
    for a in arms(site):
        g = geo[a]
        for b in arms(site):
            tt = turn_type(a, b)
            if tt in ("U",):
                continue
            og = geo[b]
            if tt == "L":
                # leftmost in-lane (highest index) -> leftmost out-lane
                fl = g["lanes_in"] - 1
                cons.append('    <connection from="in_%s" to="out_%s" fromLane="%d" toLane="%d"/>'
                            % (a, b, fl, og["lanes_out"] - 1))
            elif tt == "R":
                cons.append('    <connection from="in_%s" to="out_%s" fromLane="0" toLane="0"/>' % (a, b))
            else:  # through
                n_thru_from = g["through"]
                for i in range(n_thru_from):
                    cons.append('    <connection from="in_%s" to="out_%s" fromLane="%d" toLane="%d"/>'
                                % (a, b, i, min(i, og["lanes_out"] - 1)))
    cons.append("</connections>")

    paths = {}
    for key, lines in (("nod", nodes), ("edg", edges), ("con", cons)):
        p = os.path.join(d, "%s.%s.xml" % (site["site"], key))
        with open(p, "w") as f:
            f.write("\n".join(lines) + "\n")
        paths[key] = p
    return paths


def compile_net(paths, out_path, tll=None):
    cmd = [find_bin("netconvert"),
           "--node-files", paths["nod"], "--edge-files", paths["edg"],
           "--connection-files", paths["con"], "-o", out_path,
           "--no-turnarounds", "true", "--default.junctions.radius", "8",
           "--tls.yellow.time", str(int(YELLOW)), "--tls.allred.time", str(int(ALLRED)),
           "--no-warnings", "true"]
    if tll:
        cmd += ["--tllogic-files", tll]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("netconvert failed for %s:\n%s" % (out_path, r.stderr))
    return r


def write_tll(path, phases, program_id="0"):
    """Plain-XML TL program, fed BACK INTO netconvert via --tllogic-files.

    Two SUMO facts make this the right route:
      * an *additional* file cannot override the net's own program 0 -- SUMO
        errors with "Another logic with id 'center' and programID '0' exists";
      * simply deleting the net's <tlLogic> leaves the junction's tls reference
        dangling -- SUMO then errors with "The tls 'center' is not known".
    So the program has to be baked into the net.  Pass 1 of netconvert produces
    the linkIndex mapping we need to author the state strings; pass 2 re-compiles
    the same plain XML with this file supplied, replacing the default program.
    """
    L = ['<?xml version="1.0" encoding="UTF-8"?>', "<additional>",
         '    <tlLogic id="center" type="static" programID="%s" offset="0">' % program_id]
    for dur, st, lab in phases:
        L.append('        <phase duration="%d" state="%s"/>  <!-- %s -->' % (int(round(dur)), st, lab))
    L += ["    </tlLogic>", "</additional>"]
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")


def read_tl_links(net_path):
    """{(from_arm, dir): [linkIndex,...]} for connections controlled by 'center'."""
    root = ET.parse(net_path).getroot()
    m = {}
    for c in root.findall("connection"):
        if c.get("tl") != "center":
            continue
        frm = c.get("from")
        if not frm.startswith("in_"):
            continue
        arm = frm[3:]
        d = c.get("dir")          # 'l', 's', 'r', 't'
        m.setdefault((arm, d), []).append(int(c.get("linkIndex")))
    return m


def webster(site, geo, vols):
    """Webster cycle + splits.  Returns dict with cycle, green times, y-ratios."""
    phasing = site["phasing"]
    protected_left = phasing in ("prot", "protperm")

    # critical flow ratio for the major through phase (worst of N / S)
    y_major = 0.0
    for a in ("N", "S"):
        thru_r = vols[a]["T"] + vols[a]["R"]
        cap = geo[a]["through"] * SAT_FLOW
        if protected_left:
            y = thru_r / cap
        else:
            # permissive: lefts served from the bay during the same phase
            y = max(thru_r / cap, vols[a]["L"] / SAT_FLOW_PERM_LEFT)
        y_major = max(y_major, y)

    y_left = 0.0
    if protected_left:
        y_left = max(vols[a]["L"] / SAT_FLOW for a in ("N", "S"))

    y_minor = 0.0
    minor_arms = [a for a in arms(site) if a in ("E", "W")]
    for a in minor_arms:
        y_minor = max(y_minor, vols[a]["total"] / (geo[a]["through"] * SAT_FLOW))

    n_green = 3 if protected_left else 2
    L = n_green * LOST_TIME_PER_PHASE + n_green * (YELLOW + ALLRED - LOST_TIME_PER_PHASE)
    L = n_green * LOST_TIME_PER_PHASE
    Y = y_major + y_left + y_minor
    Y = min(Y, 0.92)
    C = (1.5 * L + 5.0) / (1.0 - Y)
    # clamp to practical agency range: Webster's raw optimum is often below the
    # shortest cycle an agency would field at a multi-phase signal.
    C = max(60.0, min(140.0, C))

    forced = {"long140": 140.0, "long100": 100.0, "short35": 35.0}
    if site["cycle_mode"] in forced:
        C = forced[site["cycle_mode"]]

    inter = n_green * (YELLOW + ALLRED)
    g_total = max(C - inter, 6.0 * n_green)
    ys = {"major": y_major, "left": y_left, "minor": y_minor}
    ysum = y_major + y_left + y_minor
    greens = {k: max(6.0, g_total * v / ysum) for k, v in ys.items() if (k != "left" or protected_left)}
    # rescale so greens + intergreen == C
    s = sum(greens.values())
    greens = {k: v * g_total / s for k, v in greens.items()}
    return dict(cycle=round(C, 1), greens={k: round(v, 1) for k, v in greens.items()},
                y=dict((k, round(v, 4)) for k, v in ys.items()), Y=round(Y, 4),
                n_green=n_green, protected_left=protected_left)


def build_program(site, links, web, n_links):
    """Generate tlLogic phases from the compiled net's own link map."""
    phasing = site["phasing"]
    major, minor = ("N", "S"), tuple(a for a in arms(site) if a in ("E", "W"))

    def idx(armset, dirs):
        out = []
        for a in armset:
            for d in dirs:
                out.extend(links.get((a, d), []))
        return out

    maj_L = idx(major, "l")
    maj_TR = idx(major, "sr")
    min_L = idx(minor, "l")
    min_TR = idx(minor, "sr")

    def state(assign):
        s = ["r"] * n_links
        for group, ch in assign:
            for i in group:
                s[i] = ch
        return "".join(s)

    phases = []          # (duration, state, label)
    g = web["greens"]
    if phasing == "perm":
        phases.append((g["major"], state([(maj_TR, "G"), (maj_L, "g")]), "major thru G + perm left g"))
        phases.append((YELLOW, state([(maj_TR, "y"), (maj_L, "y")]), "major yellow"))
        phases.append((ALLRED, state([]), "all red"))
        phases.append((g["minor"], state([(min_TR, "G"), (min_L, "g")]), "minor thru G + perm left g"))
        phases.append((YELLOW, state([(min_TR, "y"), (min_L, "y")]), "minor yellow"))
        phases.append((ALLRED, state([]), "all red"))
    else:
        phases.append((g["left"], state([(maj_L, "G")]), "major PROTECTED left G"))
        phases.append((YELLOW, state([(maj_L, "y")]), "left yellow"))
        phases.append((ALLRED, state([]), "all red"))
        if phasing == "protperm":
            phases.append((g["major"], state([(maj_TR, "G"), (maj_L, "g")]), "major thru G + perm fill-in g"))
            phases.append((YELLOW, state([(maj_TR, "y"), (maj_L, "y")]), "major yellow"))
        else:
            phases.append((g["major"], state([(maj_TR, "G")]), "major thru G, left r (protected only)"))
            phases.append((YELLOW, state([(maj_TR, "y")]), "major yellow"))
        phases.append((ALLRED, state([]), "all red"))
        phases.append((g["minor"], state([(min_TR, "G"), (min_L, "g")]), "minor thru G + perm left g"))
        phases.append((YELLOW, state([(min_TR, "y"), (min_L, "y")]), "minor yellow"))
        phases.append((ALLRED, state([]), "all red"))

    table = ["site=%s phasing=%s cycle_mode=%s cycle=%.1f Y=%.3f" %
             (site["site"], phasing, site["cycle_mode"], sum(p[0] for p in phases), web["Y"]),
             "majorL idx=%s  majorTR idx=%s  minorL idx=%s  minorTR idx=%s" %
             (maj_L, maj_TR, min_L, min_TR),
             "%-5s %-7s %-28s %s" % ("ph", "dur", "state", "label")]
    for i, (dur, st, lab) in enumerate(phases):
        table.append("%-5d %-7.1f %-28s %s | majL=%s" %
                     (i, dur, st, lab, "".join(st[j] for j in maj_L)))
    return phases, "\n".join(table)


def write_additional(site, path, phases):
    L = ['<?xml version="1.0" encoding="UTF-8"?>', "<additional>"]
    L.append('    <vType id="car" vClass="passenger" length="4.5" minGap="2.5" accel="2.6"'
             ' decel="4.5" sigma="0.5" tau="1.0" speedDev="0.1">')
    L.append('        <param key="has.ssm.device" value="true"/>')
    L.append('        <param key="device.ssm.measures" value="TTC DRAC PET"/>')
    L.append('        <param key="device.ssm.thresholds" value="3.0 3.0 2.0"/>')
    L.append('        <param key="device.ssm.range" value="60.0"/>')
    L.append('        <param key="device.ssm.extratime" value="5.0"/>')
    L.append('        <param key="device.ssm.trajectories" value="false"/>')
    L.append("    </vType>")
    if phases:
        L.append('    <tlLogic id="center" type="static" programID="0" offset="0">')
        for dur, st, lab in phases:
            L.append('        <phase duration="%.0f" state="%s"/>  <!-- %s -->' % (round(dur), st, lab))
        L.append("    </tlLogic>")
    L.append("</additional>")
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")


def write_routes(site, path, vols, begin, end):
    """Poisson arrivals via period="exp(rate)" so the sumo --seed drives arrival randomness."""
    L = ['<?xml version="1.0" encoding="UTF-8"?>', "<routes>"]
    flows = []
    for a in arms(site):
        for b in arms(site):
            tt = turn_type(a, b)
            if tt == "U":
                continue
            v = vols[a][tt]
            if v <= 0:
                continue
            rid = "r_%s_%s" % (a, b)
            L.append('    <route id="%s" edges="in_%s out_%s"/>' % (rid, a, b))
            flows.append((rid, v, a, tt))
    for rid, v, a, tt in flows:
        rate = v / 3600.0
        L.append('    <flow id="f_%s" route="%s" type="car" begin="%d" end="%d" '
                 'period="exp(%.6f)" departLane="best" departSpeed="max"/>'
                 % (rid, rid, begin, end, rate))
    L.append("</routes>")
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--begin", type=int, default=0)
    ap.add_argument("--end", type=int, default=4200)
    a = ap.parse_args()

    os.makedirs(a.root, exist_ok=True)
    manifest = []
    for site in SITES:
        d = os.path.join(a.root, site["site"])
        os.makedirs(d, exist_ok=True)
        geo = site_geometry(site)
        vols = approach_volumes(site)
        paths = write_plain_xml(site, geo, d)
        net = os.path.join(d, "%s.net.xml" % site["site"])
        compile_net(paths, net)

        phases, table, web = None, None, None
        if site["control"] == "4SG":
            links = read_tl_links(net)
            root = ET.parse(net).getroot()
            n_links = max(int(c.get("linkIndex")) for c in root.findall("connection")
                          if c.get("tl") == "center") + 1
            web = webster(site, geo, vols)
            phases, table = build_program(site, links, web, n_links)
            with open(os.path.join(d, "phases.txt"), "w") as f:
                f.write(table + "\n")
            with open(os.path.join(d, "webster.json"), "w") as f:
                json.dump(web, f, indent=2)
            tll = os.path.join(d, "%s.tll.xml" % site["site"])
            write_tll(tll, phases)
            compile_net(paths, net, tll=tll)      # pass 2: bake the program in

        write_additional(site, os.path.join(d, "%s.add.xml" % site["site"]), None)
        write_routes(site, os.path.join(d, "%s.rou.xml" % site["site"]), vols, a.begin, a.end)

        entering = sum(v["total"] for v in vols.values())
        manifest.append(dict(site=site["site"], control=site["control"],
                             aadt_major=site["aadt_major"], aadt_minor=site["aadt_minor"],
                             lanes_major=site["lanes_major"], lanes_minor=site["lanes_minor"],
                             phasing=site["phasing"], speed_mph=site["speed_mph"],
                             cycle_mode=site["cycle_mode"],
                             cycle_s=(web["cycle"] if web else None),
                             webster_Y=(web["Y"] if web else None),
                             peak_hour_entering_veh=round(entering, 1),
                             dir=d))
        print("built %s (%s) entering=%.0f veh/h cycle=%s"
              % (site["site"], site["control"], entering, web["cycle"] if web else "-"))

    with open(os.path.join(a.root, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print("\nmanifest -> %s" % os.path.join(a.root, "manifest.json"))


if __name__ == "__main__":
    main()
