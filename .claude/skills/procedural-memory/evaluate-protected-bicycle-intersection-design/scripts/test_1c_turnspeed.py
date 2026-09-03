"""
Sub-goal 1c: does --junctions.limit-turn-speed / corner (node) radius actually change
the measured right-turn speed, and by how much?  Factorial: radius in {3,6,10,15} x
limit-turn-speed in {off(-1), 3.0 m/s^2 (tight AASHTO-like lateral accel)}.
Car-only (no bikes) free-flow demand (period=8s, well below capacity) so the measured
via-lane speed reflects pure geometry, not yielding.
"""
import sys, os, re, json, subprocess, xml.etree.ElementTree as ET, statistics as st
sys.path.insert(0, "/private/tmp/claude-501/-Users-liuqi-Desktop-simskill/07cb182d-88df-492d-b918-d753d888c5e5/scratchpad/bikeint/lib")
import net_lib as nl

WORK = "/private/tmp/claude-501/-Users-liuqi-Desktop-simskill/07cb182d-88df-492d-b918-d753d888c5e5/scratchpad/bikeint/goal1"
ADD = os.path.join(WORK, "vtypes.add.xml")

def build_net(tag, radius, limit_turn_speed):
    spec = nl.VariantSpec(tag, bike_mode="dedicated", radius=radius, arm_length=150.0)
    extra = []
    if limit_turn_speed is not None:
        extra += ["--junctions.limit-turn-speed", str(limit_turn_speed)]
    net, r = nl.build_variant_net(WORK, tag, spec, extra_netconvert_args=extra)
    return net, r

def make_allgreen(net_path, out_path):
    lm = nl.parse_linkmap(net_path)
    n_links = lm["n_links"]
    linkmap = lm["linkmap"]
    state = ["r"] * n_links
    for (approach, mv, vtag), li in linkmap.items():
        if vtag == "bike" and mv == "through":
            state[li] = "G"
        elif vtag == "veh" and mv == "through":
            state[li] = "G"
        elif vtag == "veh" and mv in ("left", "right"):
            state[li] = "g"
    state = "".join(state)
    new_tllogic = f'  <tlLogic id="center" type="static" programID="0" offset="0">\n    <phase duration="100000" state="{state}"/>\n  </tlLogic>\n'
    with open(net_path) as f:
        txt = f.read()
    new_txt = re.sub(r'  <tlLogic id="center".*?</tlLogic>\n', new_tllogic, txt, flags=re.S)
    assert new_txt != txt
    with open(out_path, "w") as f:
        f.write(new_txt)
    return lm

def measure_right_turn_speed(net_path, lm, dur=400):
    a = "N"
    t, r = nl.opposite(a), nl.right_of(a)
    rou = net_path + ".rou.xml"
    with open(rou, "w") as f:
        f.write(f'''<routes>
  <route id="carR" edges="in_{a} out_{r}"/>
  <flow id="cars" type="car" route="carR" begin="0" end="{dur}" period="8.0" departSpeed="max" departPos="base"/>
</routes>''')
    fcd = net_path + ".fcd.xml"
    cmd = [nl.SUMO_BIN, "-n", net_path, "-r", rou, "-a", ADD,
           "--fcd-output", fcd, "--fcd-output.attributes", "id,speed,lane",
           "--time-to-teleport", "-1", "--no-step-log", "true",
           "--step-length", "0.1", "--begin", "0", "--end", str(dur + 30)]
    r_ = subprocess.run(cmd, capture_output=True, text=True)
    if r_.returncode != 0:
        return None, r_.stderr[-1500:]
    via_lane = None
    for c in lm["connections"]:
        if c["approach"] == a and c["movement"] == "right" and c["vtag"] == "veh":
            via_lane = c["via"]
    speeds = []
    for _, elem in ET.iterparse(fcd, events=("end",)):
        if elem.tag == "vehicle" and elem.get("lane") == via_lane:
            speeds.append(float(elem.get("speed")))
        elif elem.tag == "timestep":
            elem.clear()
    if not speeds:
        return None, "no samples"
    speeds.sort()
    return dict(n=len(speeds), mean=round(st.mean(speeds), 3), max=round(max(speeds), 3),
                p85=round(speeds[int(0.85 * len(speeds))], 3),
                internal_lane_len=None), None

results = []
for radius in [3, 6, 10, 15]:
    for lts in [None, 3.0]:
        tag = f"r{radius}_lts{lts}"
        net, r = build_net(tag, radius, lts)
        if r.returncode != 0:
            print(tag, "NETCONVERT FAIL", r.stderr[-1000:]); continue
        allgreen = net.replace(".net.xml", "_ag.net.xml")
        lm = make_allgreen(net, allgreen)
        # get internal lane geometric length for the right-turn via lane
        via_lane = None
        for c in lm["connections"]:
            if c["approach"] == "N" and c["movement"] == "right" and c["vtag"] == "veh":
                via_lane = c["via"]
        tree = ET.parse(allgreen); root = tree.getroot()
        lane_len = None
        for edge in root.findall("edge"):
            for lane in edge.findall("lane"):
                if lane.get("id") == via_lane:
                    lane_len = float(lane.get("length"))
        res, err = measure_right_turn_speed(allgreen, lm)
        row = dict(radius=radius, limit_turn_speed=lts, via_lane_len=lane_len, result=res, err=err)
        results.append(row)
        print(row)

with open(os.path.join(WORK, "turnspeed_results.json"), "w") as f:
    json.dump(results, f, indent=2)
