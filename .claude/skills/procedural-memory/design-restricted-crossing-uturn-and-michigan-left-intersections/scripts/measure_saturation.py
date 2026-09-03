#!/usr/bin/env python3
"""
Measure saturation flow rate s (veh/h/lane) and startup lost time l1 (s) for every
movement class used at junction J, on the REAL compiled geometry (not a generic
test bed), using the green-duration-regression estimator:

      N(g) = (s/3600) * (g + Y_eff - l1)      ->   s = 3600*slope,  l1 = Y_eff - intercept/slope

We hold a standing queue on the measured lane, give that lane green for g seconds
(followed by 3 s yellow), and count the vehicles that cross the stop line during
[green_start, green_end + yellow].  Sweeping g and regressing N on g removes the
need to pick a headway window (skill: measure-saturation-flow-and-validate-webster-method).

Output: sat_flow.json
"""
import json
import os
import subprocess
import sys

sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import sumolib  # noqa: E402
import traci  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORK = os.path.join(ROOT, "calib")
GREENS = [12, 20, 30, 40, 55]
YELLOW = 3
RED = 45
NCYC = 14
WARM_CYC = 2
STEP = 0.1

VTYPE = ('<vType id="car" vClass="passenger" length="4.5" minGap="2.5" accel="2.6" '
         'decel="4.5" sigma="0.5" maxSpeed="20.0" tau="1.0" speedFactor="normc(1.0,0.10,0.7,1.3)"/>')

# name -> (net variant, route edge list, departLane, measured lane id, links to be green)
CASES = {
    "AR_THRU":   ("conv", ["E_W_XW", "E_XW_J", "E_J_XE", "E_XE_E"], 1, "E_XW_J_1"),
    "AR_LEFT":   ("conv", ["E_W_XW", "E_XW_J", "M_J_N"],            2, "E_XW_J_2"),
    "AR_RIGHT":  ("conv", ["E_W_XW", "E_XW_J", "M_J_S"],            0, "E_XW_J_0"),
    "MI_THRU":   ("conv", ["M_N_J", "M_J_S"],                       0, "M_N_J_0"),
    "MI_LEFT":   ("conv", ["M_N_J", "E_J_XE", "E_XE_E"],            1, "M_N_J_1"),
    "MI_RIGHT":  ("conv", ["M_N_J", "W_J_XW", "W_XW_W"],            0, "M_N_J_0"),
    "MI_RIGHT2": ("rcut", ["M_N_J", "W_J_XW", "W_XW_W"],            1, "M_N_J_1"),
}


def run_case(name, variant, route, dlane, mlane, g, seed=7):
    netf = os.path.join(ROOT, "nets", f"{variant}_D400", "net.net.xml")
    net = sumolib.net.readNet(netf)
    d = os.path.join(WORK, f"{name}_g{g}")
    os.makedirs(d, exist_ok=True)
    lane = net.getLane(mlane)
    pos = max(lane.getLength() - 1.0, 5.0)
    with open(f"{d}/add.xml", "w") as f:
        f.write('<additional>\n' + VTYPE + '\n'
                f'  <inductionLoop id="det" lane="{mlane}" pos="{pos:.2f}" '
                f'period="100000" file="det.xml"/>\n</additional>\n')
    cyc = g + YELLOW + RED
    horizon = cyc * NCYC + 60
    with open(f"{d}/rou.xml", "w") as f:
        f.write('<routes>\n')
        f.write(f'  <route id="r" edges="{" ".join(route)}"/>\n')
        f.write(f'  <flow id="f" route="r" type="car" begin="0" end="{horizon}" '
                f'vehsPerHour="2400" departLane="{dlane}" departSpeed="max" '
                f'departPos="last"/>\n')
        f.write('</routes>\n')

    # target links = every tls link whose from-lane is the measured lane
    tls = net.getTLS("J")
    conns = tls.getConnections()   # (inLane, outLane, linkIndex)
    n = max(c[2] for c in conns) + 1
    tgt = [c[2] for c in conns if c[0].getID() == mlane]
    if name == "MI_THRU":
        tgt = [c[2] for c in conns if c[0].getID() == mlane and c[1].getEdge().getID() == "M_J_S"]
    if name == "MI_RIGHT":
        tgt = [c[2] for c in conns if c[0].getID() == mlane and c[1].getEdge().getID() == "W_J_XW"]
    if not tgt:
        raise RuntimeError(f"no tls link for {mlane} in {variant}")
    G = "".join("G" if i in tgt else "r" for i in range(n))
    Y = "".join("y" if i in tgt else "r" for i in range(n))
    R = "r" * n

    cmd = ["sumo", "-n", netf, "-r", f"{d}/rou.xml", "-a", f"{d}/add.xml",
           "--step-length", str(STEP), "--begin", "0", "--end", str(horizon),
           "--seed", str(seed), "--no-step-log", "true", "--no-warnings", "true",
           "--time-to-teleport", "-1", "--default.speeddev", "0"]
    traci.start(cmd, label=f"{name}{g}")
    c = traci.getConnection(f"{name}{g}")
    c.trafficlight.setProgramLogic if False else None
    counts = []
    t = 0.0
    for k in range(NCYC):
        # red
        c.trafficlight.setRedYellowGreenState("J", R)
        for _ in range(int(RED / STEP)):
            c.simulationStep()
        seen = set()
        c.trafficlight.setRedYellowGreenState("J", G)
        for _ in range(int(g / STEP)):
            c.simulationStep()
            seen.update(c.inductionloop.getLastStepVehicleIDs("det"))
        c.trafficlight.setRedYellowGreenState("J", Y)
        for _ in range(int(YELLOW / STEP)):
            c.simulationStep()
            seen.update(c.inductionloop.getLastStepVehicleIDs("det"))
        counts.append(len(seen))
    c.close()
    return counts[WARM_CYC:]


def linreg(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    b = sxy / sxx
    a = my - b * mx
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return a, b, r2


def main():
    os.makedirs(WORK, exist_ok=True)
    out = {}
    for name, (variant, route, dlane, mlane) in CASES.items():
        xs, ys, raw = [], [], {}
        for g in GREENS:
            cs = run_case(name, variant, route, dlane, mlane, g)
            raw[g] = cs
            for v in cs:
                xs.append(float(g))
                ys.append(float(v))
            print(f"  {name} g={g}: {cs} mean={sum(cs)/len(cs):.2f}", flush=True)
        a, b, r2 = linreg(xs, ys)
        s = 3600.0 * b
        l1 = YELLOW - a / b           # effective lost time at the start of green
        out[name] = {"lane": mlane, "variant": variant, "counts": raw,
                     "intercept": a, "slope": b, "r2": r2,
                     "sat_flow_vph_per_lane": s, "startup_lost_time_s": l1,
                     "sat_headway_s": 3600.0 / s}
        print(f"{name}: s={s:.0f} veh/h/lane  l1={l1:.2f}s  h={3600/s:.3f}s  R2={r2:.3f}",
              flush=True)
    with open(os.path.join(ROOT, "calib", "sat_flow.json"), "w") as f:
        json.dump(out, f, indent=1)


if __name__ == "__main__":
    main()
