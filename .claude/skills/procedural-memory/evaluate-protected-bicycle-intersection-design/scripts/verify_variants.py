import sys, os, json, math, subprocess, xml.etree.ElementTree as ET, statistics as st
sys.path.insert(0, "/private/tmp/claude-501/-Users-liuqi-Desktop-simskill/07cb182d-88df-492d-b918-d753d888c5e5/scratchpad/bikeint/lib")
import net_lib as nl

WORK = "/private/tmp/claude-501/-Users-liuqi-Desktop-simskill/07cb182d-88df-492d-b918-d753d888c5e5/scratchpad/bikeint/net"
manifest = json.load(open(os.path.join(WORK, "manifest.json")))

ADD = os.path.join(WORK, "vtypes.add.xml")
with open(ADD, "w") as f:
    f.write('''<additional>
  <vType id="car" vClass="passenger" length="4.5" minGap="2.5" accel="2.6" decel="4.5" sigma="0.5" maxSpeed="16.0" speedFactor="1.0" speedDev="0"/>
  <vType id="bike" vClass="bicycle" length="1.8" minGap="1.0" accel="1.2" decel="3.0" sigma="0.5" maxSpeed="5.56" speedFactor="1.0" speedDev="0.1"/>
</additional>''')


def parse_pts(s):
    return [tuple(map(float, p.split(","))) for p in s.split()]


def polyline_len(pts):
    return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def point_seg_dist(p, a, b):
    ax, ay = a; bx, by = b; px, py = p
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return math.dist(p, a), 0.0
    t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L2))
    proj = (ax + t * dx, ay + t * dy)
    return math.dist(p, proj), t


def min_dist_and_station(polyA, polyB):
    """Return (min_dist, arc_len_along_A_at_closest_point)."""
    best = (float("inf"), 0.0)
    acc = 0.0
    for i in range(len(polyA) - 1):
        a0, a1 = polyA[i], polyA[i + 1]
        seg_len = math.dist(a0, a1)
        # sample along this segment finely and check dist to polyB
        n = max(2, int(seg_len))
        for k in range(n + 1):
            t = k / n
            p = (a0[0] + t * (a1[0] - a0[0]), a0[1] + t * (a1[1] - a0[1]))
            dmin = min(point_seg_dist(p, polyB[j], polyB[j + 1])[0] for j in range(len(polyB) - 1))
            station = acc + t * seg_len
            if dmin < best[0]:
                best = (dmin, station)
        acc += seg_len
    return best


report = {}
for name, m in manifest.items():
    net = m["net"]
    lm = nl.parse_linkmap(net)
    linkmap = lm["linkmap"]
    n_links = lm["n_links"]
    has_bike_through = all((a, "through", "bike") in linkmap for a in nl.ARMS) if m["cfg"]["bike_mode"] == "dedicated" else "n/a (mixed)"
    has_veh_right = all(((a, "right", "veh") in linkmap or (a, "right", "mixed") in linkmap) for a in nl.ARMS)
    n_crossings = len(lm["crossings"])

    setback = {}
    if m["cfg"]["bike_mode"] == "dedicated":
        for a in ["N", "S"]:
            bike_c = [c for c in lm["connections"] if c["approach"] == a and c["movement"] == "through" and c["vtag"] == "bike"][0]
            veh_c = [c for c in lm["connections"] if c["approach"] == a and c["movement"] == "right" and c["vtag"] == "veh"][0]
            bshape = parse_pts(nl.get_internal_lane_shape(net, bike_c["via"]))
            vshape = parse_pts(nl.get_internal_lane_shape(net, veh_c["via"]))
            dmin, station_on_veh = min_dist_and_station(vshape, bshape)
            setback[a] = dict(min_gap_m=round(dmin, 3), station_along_veh_turn_m=round(station_on_veh, 3),
                               veh_via_len_m=round(polyline_len(vshape), 3), bike_via_len_m=round(polyline_len(bshape), 3))

    # quick free-flow run: 1 bike + 1 car through N, measure bike lane occupancy and via speed
    rou = net + ".verify.rou.xml"
    edges_bike_thru = "in_N out_S"
    with open(rou, "w") as f:
        if m["cfg"]["bike_mode"] == "dedicated":
            f.write(f'''<routes>
  <route id="bk" edges="{edges_bike_thru}"/>
  <flow id="b" type="bike" route="bk" begin="0" end="300" period="5" departSpeed="max"/>
</routes>''')
        else:
            f.write(f'''<routes>
  <route id="bk" edges="{edges_bike_thru}"/>
  <flow id="b" type="bike" route="bk" begin="0" end="300" period="5" departSpeed="max"/>
</routes>''')
    fcd = net + ".verify.fcd.xml"
    cmd = [nl.SUMO_BIN, "-n", net, "-r", rou, "-a", ADD,
           "--fcd-output", fcd, "--fcd-output.attributes", "id,speed,lane",
           "--time-to-teleport", "-1", "--no-step-log", "true", "--step-length", "0.2",
           "--begin", "0", "--end", "330"]
    r_ = subprocess.run(cmd, capture_output=True, text=True)
    bike_lane_frac = None
    if r_.returncode == 0 and os.path.exists(fcd):
        total = 0; on_bike_lane = 0
        expected_bike_lanes = set()
        if m["cfg"]["bike_mode"] == "dedicated":
            for edge in ET.parse(net).getroot().findall("edge"):
                for lane in edge.findall("lane"):
                    if lane.get("allow") == "bicycle":
                        expected_bike_lanes.add(lane.get("id"))
        else:
            for edge in ET.parse(net).getroot().findall("edge"):
                for lane in edge.findall("lane"):
                    if lane.get("allow") and "bicycle" in lane.get("allow"):
                        expected_bike_lanes.add(lane.get("id"))
        for _, elem in ET.iterparse(fcd, events=("end",)):
            if elem.tag == "vehicle":
                total += 1
                ln = elem.get("lane")
                if ln in expected_bike_lanes or ln.startswith(":"):
                    on_bike_lane += 1
            elif elem.tag == "timestep":
                elem.clear()
        bike_lane_frac = round(on_bike_lane / total, 4) if total else None
    else:
        bike_lane_frac = f"RUN FAILED: {r_.stderr[-500:]}"

    # 85th pct right-turn speed (car only) reusing goal1 methodology
    rou2 = net + ".verify_rt.rou.xml"
    with open(rou2, "w") as f:
        f.write(f'''<routes>
  <route id="cr" edges="in_N out_W"/>
  <flow id="c" type="car" route="cr" begin="0" end="300" period="8" departSpeed="max"/>
</routes>''')
    fcd2 = net + ".verify_rt.fcd.xml"
    cmd2 = [nl.SUMO_BIN, "-n", net, "-r", rou2, "-a", ADD,
            "--fcd-output", fcd2, "--fcd-output.attributes", "id,speed,lane",
            "--time-to-teleport", "-1", "--no-step-log", "true", "--step-length", "0.1",
            "--begin", "0", "--end", "330"]
    r2_ = subprocess.run(cmd2, capture_output=True, text=True)
    p85 = None
    if r2_.returncode == 0:
        via = [c for c in lm["connections"] if c["approach"] == "N" and c["movement"] == "right" and c["vtag"] in ("veh", "mixed")][0]["via"]
        speeds = []
        for _, elem in ET.iterparse(fcd2, events=("end",)):
            if elem.tag == "vehicle" and elem.get("lane") == via:
                speeds.append(float(elem.get("speed")))
            elif elem.tag == "timestep":
                elem.clear()
        if speeds:
            speeds.sort()
            p85 = round(speeds[int(0.85 * len(speeds))], 3)

    report[name] = dict(
        n_links=n_links, has_bike_through_all_approaches=has_bike_through,
        has_veh_right_all_approaches=has_veh_right, n_crossings=n_crossings,
        setback_geometry=setback, bike_lane_occupancy_fraction=bike_lane_frac,
        rightturn_N_p85_speed_mps=p85, cycle_len=m["cycle_len"], n_phases=m["n_phases"],
    )
    print(name, json.dumps(report[name], indent=None))

with open(os.path.join(WORK, "verification_report.json"), "w") as f:
    json.dump(report, f, indent=2)
print("wrote verification_report.json")
