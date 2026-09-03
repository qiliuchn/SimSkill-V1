"""
Two diagnostic add-ons that make claims (b) and (c) honest:

(b) MODERATE, UNDERSATURATED demand (1500 veh/h < snow capacity ~2034) for dry/wet/
    snow -> all free-flow, so completed-vehicle mean speed & travel time reflect the
    pure weather speed difference (not queue admission). In the oversaturated runs,
    per-vehicle travel time is confounded by throughput, so (b) can't be read cleanly
    there.

(c) SNOW-UNDER-ADAPTED: snow speed/accel/decel (reduced stopping capability) but DRY
    gaps (minGap 2.5, tau 1.0) -> models a driver who does NOT lengthen following
    distance on ice. Isolates the pure longer-stopping-distance danger that claim (c)
    expects, showing when low friction actually becomes UNSAFE in the model.
"""
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "outputs")
SEED = "42"

VT = {  # speedFactor, minGap, tau, accel, decel, sigma
    "dry":  (1.0,  2.5, 1.0, 2.6, 4.5, 0.5),
    "wet":  (0.85, 3.5, 1.4, 2.0, 3.5, 0.6),
    "snow": (0.65, 5.0, 2.0, 1.3, 2.5, 0.7),
    # snow motion params but DRY gaps -> under-adapted driver on ice
    "snow_underadapted": (0.65, 2.5, 1.0, 1.3, 2.5, 0.7),
}

def routes(vt, rate, end=1800):
    sf, mg, tau, ac, dc, sg = vt
    return f"""<routes>
    <vType id="car" vClass="passenger" carFollowModel="Krauss" length="5.0" maxSpeed="40"
           speedFactor="{sf}" minGap="{mg}" tau="{tau}" accel="{ac}" decel="{dc}" sigma="{sg}">
        <param key="has.ssm.device" value="true"/>
        <param key="device.ssm.measures" value="TTC DRAC PET BR"/>
        <param key="device.ssm.thresholds" value="3.0 3.0 2.0 0.0"/>
        <param key="device.ssm.range" value="50.0"/>
        <param key="device.ssm.extratime" value="5.0"/>
    </vType>
    <route id="r0" edges="e_in e_up e_bn"/>
    <flow id="f" type="car" route="r0" begin="0" end="{end}" vehsPerHour="{rate}"
          departLane="free" departSpeed="max"/>
</routes>
"""

DET = """<additional>
    <inductionLoop id="e1_bn_0" lane="e_bn_0" pos="250" period="60" file="{d}/e1.xml"/>
    <inductionLoop id="e1_bn_1" lane="e_bn_1" pos="250" period="60" file="{d}/e1.xml"/>
    <laneAreaDetector id="e2_up_0" lane="e_up_0" pos="0" endPos="490" period="60" file="{d}/e2.xml"/>
    <laneAreaDetector id="e2_up_1" lane="e_up_1" pos="0" endPos="490" period="60" file="{d}/e2.xml"/>
    <laneAreaDetector id="e2_up_2" lane="e_up_2" pos="0" endPos="490" period="60" file="{d}/e2.xml"/>
</additional>
"""

# (scenario name, net, vType key, demand rate)
RUNS = [
    ("dry_mod",  "net_dry.net.xml",  "dry",  1500),
    ("wet_mod",  "net_wet.net.xml",  "wet",  1500),
    ("snow_mod", "net_snow.net.xml", "snow", 1500),
    ("snow_underadapted", "net_dry.net.xml", "snow_underadapted", 6000),
]

def run(name, net, vtkey, rate):
    d = os.path.join(OUT, name)
    os.makedirs(d, exist_ok=True)
    rou = os.path.join(d, "routes.rou.xml")
    with open(rou, "w") as f:
        f.write(routes(VT[vtkey], rate))
    det = os.path.join(d, "detectors.add.xml")
    with open(det, "w") as f:
        f.write(DET.format(d=d))
    cmd = [
        "sumo", "-n", os.path.join(HERE, net), "-r", rou, "-a", det,
        "--begin", "0", "--end", "3600", "--seed", SEED, "--time-to-teleport", "-1",
        "--tripinfo-output", "tripinfo.xml", "--summary-output", "summary.xml",
        "--device.ssm.file", "ssm.xml", "--no-step-log", "true",
        "--duration-log.statistics", "true",
    ]
    r = subprocess.run(cmd, cwd=d, capture_output=True, text=True)
    print(f"=== {name} rc={r.returncode} ===")
    if r.stderr.strip():
        print("STDERR:", r.stderr.strip()[:800])
    for l in r.stdout.splitlines():
        if any(k in l for k in ("Inserted", "Speed:", "Duration:", "TimeLoss", "Collisions", "Teleports")):
            print("  ", l.strip())

def main():
    for args in RUNS:
        run(*args)

if __name__ == "__main__":
    main()
