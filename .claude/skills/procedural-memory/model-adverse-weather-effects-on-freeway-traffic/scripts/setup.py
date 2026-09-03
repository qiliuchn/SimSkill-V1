"""
Weather-vs-freeway-capacity study: generate plain-XML network inputs, detector
additional-file, per-weather vType/route files, and compile one net per lane-
friction level with netconvert.

Geometry: straight 1-directional freeway, ~3 km, 3 lanes with a downstream
3->2 lane-drop bottleneck (n2). E1 loops on each downstream (2) lane just past
the merge; E2 lane-area detectors on the 3 upstream lanes to see the queue.

Nets differ ONLY in the per-lane `friction` attribute (1.0 dry, 0.7 wet, 0.4
snow). vType param sets differ in car-following weather params. This lets us
isolate lane-friction effect vs. vType-param effect (the mechanism deliverable).
"""
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))

NODES = """<nodes>
    <node id="n0" x="0"    y="0" type="priority"/>
    <node id="n1" x="2000" y="0" type="priority"/>
    <node id="n2" x="2500" y="0" type="priority"/>
    <node id="n3" x="3000" y="0" type="priority"/>
</nodes>
"""

def edges_xml(fric):
    def lanes(n):
        return "\n".join(f'        <lane index="{i}" friction="{fric}"/>' for i in range(n))
    return f"""<edges>
    <edge id="e_in" from="n0" to="n1" priority="1" numLanes="3" speed="33.33">
{lanes(3)}
    </edge>
    <edge id="e_up" from="n1" to="n2" priority="1" numLanes="3" speed="33.33">
{lanes(3)}
    </edge>
    <edge id="e_bn" from="n2" to="n3" priority="1" numLanes="2" speed="33.33">
{lanes(2)}
    </edge>
</edges>
"""

# 3->2 lane drop: lane 2 of the upstream edge merges into lane 1 of the bottleneck.
CONNECTIONS = """<connections>
    <connection from="e_in" to="e_up" fromLane="0" toLane="0"/>
    <connection from="e_in" to="e_up" fromLane="1" toLane="1"/>
    <connection from="e_in" to="e_up" fromLane="2" toLane="2"/>
    <connection from="e_up" to="e_bn" fromLane="0" toLane="0"/>
    <connection from="e_up" to="e_bn" fromLane="1" toLane="1"/>
    <connection from="e_up" to="e_bn" fromLane="2" toLane="1"/>
</connections>
"""

# E1 loops just downstream of the bottleneck merge (each of the 2 lanes);
# E2 lane-area detectors on the 3 upstream lanes to measure occupancy/queue.
DETECTORS = """<additional>
    <inductionLoop id="e1_bn_0" lane="e_bn_0" pos="250" period="60" file="e1.xml"/>
    <inductionLoop id="e1_bn_1" lane="e_bn_1" pos="250" period="60" file="e1.xml"/>
    <laneAreaDetector id="e2_up_0" lane="e_up_0" pos="0" endPos="490" period="60" file="e2.xml"/>
    <laneAreaDetector id="e2_up_1" lane="e_up_1" pos="0" endPos="490" period="60" file="e2.xml"/>
    <laneAreaDetector id="e2_up_2" lane="e_up_2" pos="0" endPos="490" period="60" file="e2.xml"/>
</additional>
"""

# Progressive weather car-following param sets (dry -> wet -> snow).
VTYPES = {
    "dry":  dict(speedFactor=1.0,  minGap=2.5, tau=1.0, accel=2.6, decel=4.5, sigma=0.5),
    "wet":  dict(speedFactor=0.85, minGap=3.5, tau=1.4, accel=2.0, decel=3.5, sigma=0.6),
    "snow": dict(speedFactor=0.65, minGap=5.0, tau=2.0, accel=1.3, decel=2.5, sigma=0.7),
}

def routes_xml(p):
    return f"""<routes>
    <vType id="car" vClass="passenger" carFollowModel="Krauss" length="5.0" maxSpeed="40"
           speedFactor="{p['speedFactor']}" minGap="{p['minGap']}" tau="{p['tau']}"
           accel="{p['accel']}" decel="{p['decel']}" sigma="{p['sigma']}">
        <param key="has.ssm.device" value="true"/>
        <param key="device.ssm.measures" value="TTC DRAC PET BR"/>
        <param key="device.ssm.thresholds" value="3.0 3.0 2.0 0.0"/>
        <param key="device.ssm.range" value="50.0"/>
        <param key="device.ssm.extratime" value="5.0"/>
    </vType>
    <route id="r0" edges="e_in e_up e_bn"/>
    <flow id="f" type="car" route="r0" begin="0" end="1800" vehsPerHour="6000"
          departLane="free" departSpeed="max"/>
</routes>
"""

def write(name, content):
    path = os.path.join(HERE, name)
    with open(path, "w") as f:
        f.write(content)
    return path

def main():
    write("nodes.nod.xml", NODES)
    write("connections.con.xml", CONNECTIONS)
    write("detectors.add.xml", DETECTORS)

    fric = {"dry": 1.0, "wet": 0.7, "snow": 0.4}
    for w, fr in fric.items():
        write(f"edges_{w}.edg.xml", edges_xml(fr))
    for w, p in VTYPES.items():
        write(f"routes_{w}.rou.xml", routes_xml(p))

    # Compile one net per friction level (identical geometry, only lane friction differs).
    for w in fric:
        net = os.path.join(HERE, f"net_{w}.net.xml")
        cmd = [
            "netconvert",
            "-n", os.path.join(HERE, "nodes.nod.xml"),
            "-e", os.path.join(HERE, f"edges_{w}.edg.xml"),
            "-x", os.path.join(HERE, "connections.con.xml"),
            "-o", net,
            "--no-turnarounds", "true",
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        print(f"[netconvert {w}] rc={r.returncode}")
        if r.returncode != 0:
            print(r.stdout); print(r.stderr)
            raise SystemExit(f"netconvert failed for {w}")
    print("Setup complete.")

if __name__ == "__main__":
    main()
