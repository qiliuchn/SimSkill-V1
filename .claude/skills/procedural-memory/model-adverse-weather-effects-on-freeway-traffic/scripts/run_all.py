"""
Run all weather scenarios on identical geometry + identical demand + identical seed.

Main comparison (both mechanisms applied):
  dry  = net_dry (friction 1.0)  + dry  vType
  wet  = net_wet (friction 0.7)  + wet  vType
  snow = net_snow(friction 0.4)  + snow vType

Mechanism-isolation controls (vs. dry baseline):
  fric_only_snow  = net_snow(0.4) + dry  vType   -> does lane friction ALONE change behavior?
  vtype_only_snow = net_dry (1.0) + snow vType    -> do vType params ALONE change behavior?
"""
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "outputs")
SEED = "42"

SCENARIOS = {
    "dry":             ("net_dry.net.xml",  "routes_dry.rou.xml"),
    "wet":             ("net_wet.net.xml",  "routes_wet.rou.xml"),
    "snow":            ("net_snow.net.xml", "routes_snow.rou.xml"),
    "fric_only_snow":  ("net_snow.net.xml", "routes_dry.rou.xml"),
    "vtype_only_snow": ("net_dry.net.xml",  "routes_snow.rou.xml"),
}

DET_TEMPLATE = """<additional>
    <inductionLoop id="e1_bn_0" lane="e_bn_0" pos="250" period="60" file="{d}/e1.xml"/>
    <inductionLoop id="e1_bn_1" lane="e_bn_1" pos="250" period="60" file="{d}/e1.xml"/>
    <laneAreaDetector id="e2_up_0" lane="e_up_0" pos="0" endPos="490" period="60" file="{d}/e2.xml"/>
    <laneAreaDetector id="e2_up_1" lane="e_up_1" pos="0" endPos="490" period="60" file="{d}/e2.xml"/>
    <laneAreaDetector id="e2_up_2" lane="e_up_2" pos="0" endPos="490" period="60" file="{d}/e2.xml"/>
</additional>
"""

def run(name, net, routes):
    d = os.path.join(OUT, name)
    os.makedirs(d, exist_ok=True)
    # per-scenario detector add-file with ABSOLUTE output paths (detector `file` is
    # otherwise resolved relative to the add-file's own directory, not cwd, so a
    # shared add-file would make all scenarios overwrite one e1.xml).
    det = os.path.join(d, "detectors.add.xml")
    with open(det, "w") as f:
        f.write(DET_TEMPLATE.format(d=d))
    cmd = [
        "sumo",
        "-n", os.path.join(HERE, net),
        "-r", os.path.join(HERE, routes),
        "-a", det,
        "--begin", "0", "--end", "3600",
        "--seed", SEED,
        "--time-to-teleport", "-1",       # disable teleport so queued vehicles are not removed (clean discharge)
        "--tripinfo-output", "tripinfo.xml",
        "--summary-output", "summary.xml",
        "--device.ssm.file", "ssm.xml",
        "--no-step-log", "true",
        "--duration-log.statistics", "true",
    ]
    r = subprocess.run(cmd, cwd=d, capture_output=True, text=True)
    print(f"=== {name} rc={r.returncode} ===")
    if r.stderr.strip():
        print("STDERR:", r.stderr.strip()[:1500])
    # print SUMO's own statistics tail
    tail = [l for l in r.stdout.splitlines() if any(k in l for k in
            ("Statistics", "Inserted", "Loaded", "Running", "Teleports", "Collisions",
             "DepartDelay", "Duration", "TimeLoss", "Speed", "WaitingTime"))]
    for l in tail:
        print("  ", l.strip())
    return r.returncode

def main():
    rcs = {}
    for name, (net, routes) in SCENARIOS.items():
        rcs[name] = run(name, net, routes)
    print("\nreturn codes:", rcs)
    # verify each scenario wrote its own detector outputs
    for name in SCENARIOS:
        d = os.path.join(OUT, name)
        files = sorted(os.listdir(d))
        print(f"{name}: {files}")

if __name__ == "__main__":
    main()
