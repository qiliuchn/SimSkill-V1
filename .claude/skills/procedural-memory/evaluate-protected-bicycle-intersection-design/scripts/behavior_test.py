"""
Sub-goal 1 behavioral confirmation: for each of the 4 corners of the rig network,
saturate that one approach with a through-bike flow + a permitted right-turn car flow
under a permanent green (bike-through=G, right-turn=g), and measure whether the
right-turning car actually decelerates/yields for the bike (vs sailing through),
and whether any collisions occur. This behaviorally validates (or refutes) the
foes/response bitstring reading from build_rig.py.
"""
import sys, os, re, json, subprocess, xml.etree.ElementTree as ET, statistics as st
sys.path.insert(0, "/private/tmp/claude-501/-Users-liuqi-Desktop-simskill/07cb182d-88df-492d-b918-d753d888c5e5/scratchpad/bikeint/lib")
import net_lib as nl

WORK = "/private/tmp/claude-501/-Users-liuqi-Desktop-simskill/07cb182d-88df-492d-b918-d753d888c5e5/scratchpad/bikeint/goal1"
NET = os.path.join(WORK, "rig.net.xml")

lm = nl.parse_linkmap(NET)
n_links = lm["n_links"]
linkmap = lm["linkmap"]
print("n_links", n_links)

# Build a permanent single-phase state string: bike-through=G, veh-through=G, veh-left=g, veh-right=g, all crossings=r
state = ["r"] * n_links
for (approach, mv, vtag), li in linkmap.items():
    if vtag == "bike" and mv == "through":
        state[li] = "G"
    elif vtag == "veh" and mv == "through":
        state[li] = "G"
    elif vtag == "veh" and mv in ("left", "right"):
        state[li] = "g"
state = "".join(state)
print("state string:", state, "len", len(state))

new_tllogic = f'''  <tlLogic id="center" type="static" programID="0" offset="0">
    <phase duration="100000" state="{state}"/>
  </tlLogic>
'''

# Rewrite tlLogic block in net.xml
with open(NET) as f:
    txt = f.read()
new_txt = re.sub(r'  <tlLogic id="center".*?</tlLogic>\n', new_tllogic, txt, flags=re.S)
assert new_txt != txt, "tlLogic replacement failed"
TEST_NET = os.path.join(WORK, "rig_allgreen.net.xml")
with open(TEST_NET, "w") as f:
    f.write(new_txt)
print("wrote", TEST_NET)

# vType additional file with SSM
ADD = os.path.join(WORK, "vtypes.add.xml")
with open(ADD, "w") as f:
    f.write('''<additional>
  <vType id="car" vClass="passenger" length="4.5" minGap="2.5" accel="2.6" decel="4.5" sigma="0.5" maxSpeed="16.0" speedFactor="1.0" speedDev="0">
      <param key="has.ssm.device" value="true"/>
      <param key="device.ssm.measures" value="TTC DRAC PET BR MDRAC"/>
      <param key="device.ssm.thresholds" value="3.0 3.0 2.0 0.0 3.4"/>
      <param key="device.ssm.range" value="50.0"/>
      <param key="device.ssm.extratime" value="5.0"/>
  </vType>
  <vType id="bike" vClass="bicycle" length="1.8" minGap="1.0" accel="1.2" decel="3.0" sigma="0.5" maxSpeed="5.56" speedFactor="1.0" speedDev="0">
      <param key="has.ssm.device" value="true"/>
      <param key="device.ssm.measures" value="TTC DRAC PET BR MDRAC"/>
      <param key="device.ssm.thresholds" value="3.0 3.0 2.0 0.0 3.4"/>
      <param key="device.ssm.range" value="50.0"/>
      <param key="device.ssm.extratime" value="5.0"/>
  </vType>
</additional>''')

def run_one(a, with_bikes, period_car, period_bike, dur, tag):
    t, r = nl.opposite(a), nl.right_of(a)
    rou = os.path.join(WORK, f"corner_{a}_{tag}.rou.xml")
    bike_flow = f'  <flow id="bikes" type="bike" route="bikeR" begin="0" end="{dur}" period="{period_bike}" departSpeed="max" departPos="base"/>\n' if with_bikes else ""
    with open(rou, "w") as f:
        f.write(f'''<routes>
  <route id="bikeR" edges="in_{a} out_{t}"/>
  <route id="carR" edges="in_{a} out_{r}"/>
{bike_flow}  <flow id="cars" type="car" route="carR" begin="0" end="{dur}" period="{period_car}" departSpeed="max" departPos="base"/>
</routes>''')
    outdir = os.path.join(WORK, f"out_corner_{a}_{tag}")
    os.makedirs(outdir, exist_ok=True)
    fcd = os.path.join(outdir, "fcd.xml")
    ssm = os.path.join(outdir, "ssm.xml")
    coll = os.path.join(outdir, "collisions.xml")
    trip = os.path.join(outdir, "tripinfo.xml")
    cmd = [nl.SUMO_BIN, "-n", TEST_NET, "-r", rou, "-a", ADD,
           "--fcd-output", fcd, "--fcd-output.attributes", "id,x,y,speed,lane,pos",
           "--device.ssm.file", ssm,
           "--collision-output", coll, "--collision.action", "warn",
           "--tripinfo-output", trip,
           "--time-to-teleport", "-1", "--no-step-log", "true",
           "--step-length", "0.1", "--begin", "0", "--end", str(dur + 30)]
    r_ = subprocess.run(cmd, capture_output=True, text=True)
    if r_.returncode != 0:
        print(f"CORNER {a} {tag} FAILED rc={r_.returncode}\n{r_.stderr[-2000:]}")
        return {"error": r_.stderr[-2000:]}
    ncoll = 0
    if os.path.exists(coll):
        try:
            ct = ET.parse(coll); ncoll = len(ct.getroot().findall("collision"))
        except ET.ParseError:
            ncoll = -1
    conns = lm["connections"]
    via_lane = None
    bike_via_lane = None
    for c in conns:
        if c["approach"] == a and c["movement"] == "right" and c["vtag"] == "veh":
            via_lane = c["via"]
        if c["approach"] == a and c["movement"] == "through" and c["vtag"] == "bike":
            bike_via_lane = c["via"]
    speeds_on_via = []
    bike_speeds_on_via = []
    if os.path.exists(fcd) and via_lane:
        for _, elem in ET.iterparse(fcd, events=("end",)):
            if elem.tag == "vehicle":
                if elem.get("lane") == via_lane:
                    speeds_on_via.append(float(elem.get("speed")))
                elif bike_via_lane is not None and elem.get("lane") == bike_via_lane:
                    bike_speeds_on_via.append(float(elem.get("speed")))
            elif elem.tag == "timestep":
                elem.clear()
    ssm_conflicts = 0
    car_bike_merge_conflicts = 0
    if os.path.exists(ssm):
        for _, elem in ET.iterparse(ssm, events=("end",)):
            if elem.tag == "conflict":
                ssm_conflicts += 1
                mn = elem.find("minTTC")
                typ = mn.get("type") if mn is not None else None
                ego, foe = elem.get("ego"), elem.get("foe")
                if ("car" in ego and "bike" in foe) or ("bike" in ego and "car" in foe):
                    car_bike_merge_conflicts += 1
                elem.clear()
    return dict(
        n_via_speed_samples=len(speeds_on_via),
        via_speed_mean=round(st.mean(speeds_on_via), 3) if speeds_on_via else None,
        via_speed_min=round(min(speeds_on_via), 3) if speeds_on_via else None,
        via_speed_p85=round(sorted(speeds_on_via)[int(0.85 * len(speeds_on_via))], 3) if speeds_on_via else None,
        bike_via_speed_mean=round(st.mean(bike_speeds_on_via), 3) if bike_speeds_on_via else None,
        bike_via_speed_min=round(min(bike_speeds_on_via), 3) if bike_speeds_on_via else None,
        collisions=ncoll,
        ssm_conflicts=ssm_conflicts,
        ssm_car_bike_conflicts=car_bike_merge_conflicts,
    )


results = {}
DUR = 500
for a in nl.ARMS:
    baseline = run_one(a, with_bikes=False, period_car=8.0, period_bike=None, dur=DUR, tag="carsonly")
    paired = run_one(a, with_bikes=True, period_car=8.0, period_bike=20.0, dur=DUR, tag="paired")
    results[a] = dict(baseline_car_only=baseline, paired_with_bikes=paired)
    print(a, "baseline via_speed_mean=", baseline.get("via_speed_mean"),
          " paired via_speed_mean=", paired.get("via_speed_mean"),
          " paired via_speed_p85=", paired.get("via_speed_p85"),
          " paired bike_via_speed_mean=", paired.get("bike_via_speed_mean"),
          " collisions(paired)=", paired.get("collisions"),
          " ssm_car_bike(paired)=", paired.get("ssm_car_bike_conflicts"))

with open(os.path.join(WORK, "behavior_test_results.json"), "w") as f:
    json.dump(results, f, indent=2)
