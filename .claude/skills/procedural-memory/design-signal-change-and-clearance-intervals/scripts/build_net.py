"""Build the parameterized isolated 4-approach signalized intersection.

Parameters that can be swept:
  --speed   approach free-flow speed (m/s)
  --grade   approach grade (%, negative = downgrade toward the intersection)
  --lanes   lanes per direction per arm (sets the intersection WIDTH W)
  --arm     approach length (m)

Built with plain-XML nodes/edges/connections + netconvert, per `create-single-intersection`.
Through movements only (no turns) so that the change/clearance interval study is not
confounded by permissive-left gap acceptance.

Grade is authored via node z-coordinates per `model-road-gradient-effects-on-energy`
and the REALIZED grade is read back from the compiled net's lane shapes.
"""
import argparse
import json
import os
import xml.etree.ElementTree as ET

from common import NETCONVERT, NET_DIR, run, net_lane_grade_pct, net_tls_links, net_internal_lengths

ARMS = ["N", "E", "S", "W"]
OPPOSITE = {"N": "S", "S": "N", "E": "W", "W": "E"}
# unit vector from center toward the fringe node of each arm
DIRV = {"N": (0.0, 1.0), "E": (1.0, 0.0), "S": (0.0, -1.0), "W": (-1.0, 0.0)}


def build(name, speed=13.89, grade_pct=0.0, lanes=2, arm=400.0, graded_arms=("N", "E", "S", "W"),
          out_dir=NET_DIR):
    """Two-pass build: netconvert trims the approach edge at the junction boundary but pins
    z=0 there, so the realized grade over the (shorter) lane is steeper than authored.
    Pass 1 measures that ratio, pass 2 pre-compensates so the REALIZED grade matches the
    requested one. The realized value is always re-read from the compiled net and asserted."""
    if grade_pct != 0.0:
        _, m0 = _build_once(name + "__pass1", speed, grade_pct, lanes, arm, graded_arms,
                            out_dir, verify_grade=False)
        realized0 = m0["realized_grade_pct"][graded_arms[0]]
        corr = grade_pct / realized0 if realized0 != 0 else 1.0
        for suf in (".nod.xml", ".edg.xml", ".con.xml", ".net.xml", ".meta.json"):
            p = os.path.join(out_dir, name + "__pass1" + suf)
            if os.path.exists(p):
                os.remove(p)
        return _build_once(name, speed, grade_pct, lanes, arm, graded_arms, out_dir,
                           z_scale=corr)
    return _build_once(name, speed, grade_pct, lanes, arm, graded_arms, out_dir)


def _build_once(name, speed, grade_pct, lanes, arm, graded_arms, out_dir,
                z_scale=1.0, verify_grade=True):
    os.makedirs(out_dir, exist_ok=True)
    nod = os.path.join(out_dir, name + ".nod.xml")
    edg = os.path.join(out_dir, name + ".edg.xml")
    con = os.path.join(out_dir, name + ".con.xml")
    net = os.path.join(out_dir, name + ".net.xml")

    # --- nodes ---
    # Center at z=0. A vehicle travelling INBOUND on arm A descends by grade_pct over `arm`
    # metres, so the fringe node sits at z = -grade_pct/100 * arm  (negative grade -> z>0).
    lines = ['<nodes>']
    lines.append('    <node id="C" x="0.0" y="0.0" z="0.0" type="traffic_light" tl="C"/>')
    for a in ARMS:
        dx, dy = DIRV[a]
        g = grade_pct if a in graded_arms else 0.0
        z = -(g / 100.0) * arm * z_scale
        lines.append('    <node id="%s" x="%.4f" y="%.4f" z="%.6f" type="priority"/>'
                     % (a, dx * arm, dy * arm, z))
    lines.append('</nodes>')
    open(nod, "w").write("\n".join(lines) + "\n")

    # --- edges ---
    lines = ['<edges>']
    for a in ARMS:
        lines.append('    <edge id="in_%s"  from="%s" to="C" numLanes="%d" speed="%.4f" priority="10"/>'
                     % (a, a, lanes, speed))
        lines.append('    <edge id="out_%s" from="C" to="%s" numLanes="%d" speed="%.4f" priority="10"/>'
                     % (a, a, lanes, speed))
    lines.append('</edges>')
    open(edg, "w").write("\n".join(lines) + "\n")

    # --- connections: THROUGH ONLY, lane i -> lane i ---
    lines = ['<connections>']
    for a in ARMS:
        o = OPPOSITE[a]
        for i in range(lanes):
            lines.append('    <connection from="in_%s" to="out_%s" fromLane="%d" toLane="%d"/>'
                         % (a, o, i, i))
    lines.append('</connections>')
    open(con, "w").write("\n".join(lines) + "\n")

    run([NETCONVERT,
         "-n", nod, "-e", edg, "-x", con,
         "-o", net,
         "--no-turnarounds", "true",
         "--tls.default-type", "static",
         "--no-internal-links", "false",
         "--junctions.corner-detail", "5",
         "--offset.disable-normalization", "true",
         "--no-warnings", "true"])

    # VERIFIED CONSTRAINT (not assumed): the auto-generated program CANNOT be overridden by
    # an additional file using the same programID -- SUMO hard-errors with
    #   "Another logic with id 'C' and programID '0' exists".
    # And it cannot simply be deleted from the .net.xml either -- the connections carry
    # tl="C"/linkIndex and SUMO then hard-errors with "The tls 'C' is not known."
    # Both failure modes were reproduced directly. The hand-authored plan is therefore
    # loaded under programID="custom" and activated at t=0 via TraCI setProgram, and the
    # ACTIVE program is read back out of SUMO (getAllProgramLogics) for verification.
    root_chk = ET.parse(net).getroot()
    gen = [tl.get("programID") for tl in root_chk.findall("tlLogic")]
    assert gen, "expected an auto-generated tlLogic in the compiled net"

    meta = verify(net, name, speed, grade_pct, lanes, arm, graded_arms, verify_grade)
    meta["generated_programIDs"] = gen
    meta_p = os.path.join(out_dir, name + ".meta.json")
    json.dump(meta, open(meta_p, "w"), indent=2)
    return net, meta


def verify(net, name, speed, grade_pct, lanes, arm, graded_arms, verify_grade=True):
    """Read geometry and TLS link map back OUT of the compiled net. Never trust the source XML."""
    links = net_tls_links(net, "C")
    internal = net_internal_lengths(net)

    # group link indices by approach arm
    by_arm = {}
    for li, d in links.items():
        a = d["from_edge"].split("_")[1]
        by_arm.setdefault(a, []).append(li)
    for a in by_arm:
        by_arm[a].sort()

    # crossing distance W per movement = length of the internal (via) lane
    widths = {}
    for li, d in links.items():
        via = d["via"]
        if via in internal:
            widths[li] = internal[via]

    # realized grade per approach, read from the compiled lane shapes
    grades = {a: net_lane_grade_pct(net, "in_" + a, 0) for a in ARMS}

    # approach lane lengths (netconvert trims for junction geometry)
    root = ET.parse(net).getroot()
    lane_len = {}
    lane_speed = {}
    for e in root.findall("edge"):
        for ln in e.findall("lane"):
            lane_len[ln.get("id")] = float(ln.get("length"))
            lane_speed[ln.get("id")] = float(ln.get("speed"))

    meta = dict(name=name, net=net, nominal_speed=speed, nominal_grade_pct=grade_pct,
                lanes=lanes, arm=arm, graded_arms=list(graded_arms),
                n_tls_links=len(links), links={str(k): v for k, v in links.items()},
                links_by_arm=by_arm,
                internal_lane_lengths=internal,
                W_per_link={str(k): v for k, v in widths.items()},
                W_mean=sum(widths.values()) / len(widths) if widths else None,
                W_max=max(widths.values()) if widths else None,
                realized_grade_pct=grades,
                approach_lane_length={k: v for k, v in lane_len.items() if k.startswith("in_")},
                approach_lane_speed={k: v for k, v in lane_speed.items() if k.startswith("in_")})

    # --- assertions ---
    assert len(links) == 4 * lanes, "expected %d controlled links, got %d" % (4 * lanes, len(links))
    for a in ARMS:
        assert len(by_arm.get(a, [])) == lanes, "arm %s has %s links" % (a, by_arm.get(a))
        for li in by_arm[a]:
            assert links[li]["to_edge"] == "out_" + OPPOSITE[a], \
                "link %d on arm %s goes to %s (not the opposite arm)" % (li, a, links[li]["to_edge"])
    if verify_grade:
        for a in graded_arms:
            got = grades[a]
            assert abs(got - grade_pct) < 0.02, \
                "realized grade on in_%s is %.4f%%, wanted %.4f%%" % (a, got, grade_pct)
        for a in set(ARMS) - set(graded_arms):
            assert abs(grades[a]) < 0.02, "arm %s should be flat, got %.4f%%" % (a, grades[a])
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--speed", type=float, default=13.89)
    ap.add_argument("--grade", type=float, default=0.0, help="percent, negative = downgrade")
    ap.add_argument("--lanes", type=int, default=2)
    ap.add_argument("--arm", type=float, default=400.0)
    ap.add_argument("--graded-arms", default="N,E,S,W")
    a = ap.parse_args()
    net, meta = build(a.name, a.speed, a.grade, a.lanes, a.arm,
                      tuple(x for x in a.graded_arms.split(",") if x))
    print(json.dumps({k: meta[k] for k in
                      ("name", "n_tls_links", "W_mean", "W_max", "realized_grade_pct",
                       "links_by_arm")}, indent=2))


if __name__ == "__main__":
    main()
