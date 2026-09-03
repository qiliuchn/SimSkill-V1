#!/usr/bin/env python3
"""
One experiment cell = (variant, spacing D, total demand Q, minor share m, seed).

Pipeline per cell (OD-fair, CRN):
  shared trips file for (Q,m)  ->  duarouter on THIS variant's net  ->
  Webster plan from THIS variant's own J movement volumes  ->  sumo
The trips file (vehicle ids, departure times, OD pairs) is byte-identical across
variants, and the sumo --seed is fixed per replication, so variants are compared
under common random numbers.
"""
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import sumolib  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import demand as dm  # noqa: E402
import gen_network as gn  # noqa: E402
import signals as sg  # noqa: E402

DEMAND_END = 3600
SIM_END = 9000
VTYPE = ('  <vType id="DEFAULT_VEHTYPE" vClass="passenger" length="4.5" minGap="2.5" '
         'accel="2.6" decel="4.5" sigma="0.5" tau="1.0" maxSpeed="20.0" '
         'speedFactor="normc(1.0,0.10,0.7,1.3)"/>\n')
# crossover approach edges: the U-turn storage is the median lane of these edges
XOVER_EDGES = {"W_J_XW": "XW", "E_J_XE": "XE"}


def net_dir(variant, D):
    return os.path.join(ROOT, "nets", f"{variant}_D{int(D)}")


def ensure_net(variant, D):
    d = net_dir(variant, D)
    if not os.path.exists(os.path.join(d, "net.net.xml")):
        gn.build(d, variant, D)
    return os.path.join(d, "net.net.xml")


def trips_dir(Q, m):
    return os.path.join(ROOT, "demand", f"Q{int(Q)}_m{int(round(m*100))}")


def ensure_trips(Q, m, seed=42):
    d = trips_dir(Q, m)
    if not os.path.exists(os.path.join(d, "trips.xml")):
        dm.make_trips(d, Q, m, seed)
    return os.path.join(d, "trips.xml"), os.path.join(d, "taz.xml")


def ensure_routes(variant, D, Q, m):
    netf = ensure_net(variant, D)
    trips, taz = ensure_trips(Q, m)
    d = os.path.join(ROOT, "routes", f"{variant}_D{int(D)}_Q{int(Q)}_m{int(round(m*100))}")
    os.makedirs(d, exist_ok=True)
    rou = os.path.join(d, "rou.xml")
    if not os.path.exists(rou):
        r = subprocess.run(["duarouter", "-n", netf, "--additional-files", taz,
                            "-r", trips, "-o", rou, "--with-taz",
                            "--no-step-log", "true", "--ignore-errors",
                            "--routing-threads", "1"],
                           capture_output=True, text=True)
        log = r.stdout + r.stderr
        with open(os.path.join(d, "duarouter.log"), "w") as f:
            f.write(log)
        if not os.path.exists(rou):
            raise SystemExit(f"duarouter failed: {variant} D{D} Q{Q} m{m}\n{log}")
    return netf, rou, d


def ensure_plan(variant, D, Q, m):
    netf, rou, d = ensure_routes(variant, D, Q, m)
    pj = os.path.join(d, "plan.json")
    if not os.path.exists(pj):
        plan = sg.design(netf, rou, variant)
        with open(pj, "w") as f:
            json.dump(plan, f, indent=1)
    else:
        plan = json.load(open(pj))
    return netf, rou, d, plan


def write_additional(path, netfile, plan, run_dir):
    net = sumolib.net.readNet(netfile)
    s = ["<additional>\n", VTYPE]
    for eid in XOVER_EDGES:
        e = net.getEdge(eid)
        for ln in e.getLanes():
            L = ln.getLength()
            s.append(f'  <laneAreaDetector id="la_{ln.getID()}" lane="{ln.getID()}" '
                     f'pos="0" endPos="{L:.2f}" period="60" file="lanearea.xml" '
                     f'friendlyPos="true"/>\n')
    s.append(f'  <edgeData id="ed" file="edgedata.xml" begin="0" end="{SIM_END}" '
             f'excludeEmpty="true"/>\n')
    # signal plan (programID 0 replaces the netconvert-generated program)
    n = plan["n_tls_links"]
    s.append('  <tlLogic id="J" type="static" programID="webster" offset="0">\n')
    for g, lk in zip(plan["green_s"], plan["phase_link_indices"]):
        G = "".join("G" if i in lk else "r" for i in range(n))
        Y = "".join("y" if i in lk else "r" for i in range(n))
        s.append(f'    <phase duration="{g:.1f}" state="{G}"/>\n')
        s.append(f'    <phase duration="{plan["yellow_s"]:.1f}" state="{Y}"/>\n')
        s.append(f'    <phase duration="{plan["allred_s"]:.1f}" state="{"r"*n}"/>\n')
    s.append("  </tlLogic>\n</additional>\n")
    with open(path, "w") as f:
        f.write("".join(s))


def run_cell(variant, D, Q, m, seed, tag="base", ttt=300, ssm=False, xover_signal=False,
             outroot=None, keep=True):
    netf, rou, rd, plan = ensure_plan(variant, D, Q, m)
    outroot = outroot or os.path.join(ROOT, "runs")
    name = f"{tag}_{variant}_D{int(D)}_Q{int(Q)}_m{int(round(m*100))}_s{seed}"
    d = os.path.join(outroot, name)
    os.makedirs(d, exist_ok=True)
    if os.path.exists(os.path.join(d, "DONE")):
        return d
    add = os.path.join(d, "add.xml")
    write_additional(add, netf, plan, d)
    cmd = ["sumo", "-n", netf, "-r", rou, "-a", add,
           "--begin", "0", "--end", str(SIM_END), "--step-length", "0.5",
           "--seed", str(seed), "--no-step-log", "true",
           "--time-to-teleport", str(ttt),
           "--tripinfo-output", os.path.join(d, "tripinfo.xml"),
           "--tripinfo-output.write-unfinished", "true",
           "--summary-output", os.path.join(d, "summary.xml"),
           "--statistic-output", os.path.join(d, "stats.xml"),
           "--duration-log.statistics", "true"]
    if ssm:
        cmd += ["--device.ssm.probability", "1", "--device.ssm.deterministic",
                "--device.ssm.measures", "TTC DRAC PET",
                "--device.ssm.thresholds", "3.0 3.0 2.0",
                "--device.ssm.range", "50", "--device.ssm.extratime", "5",
                "--device.ssm.file", os.path.join(d, "ssm.xml")]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=d)
    with open(os.path.join(d, "sumo.log"), "w") as f:
        f.write(r.stdout + "\n----STDERR----\n" + r.stderr)
    if r.returncode != 0:
        raise SystemExit(f"sumo failed for {name}:\n{r.stderr[-3000:]}")
    with open(os.path.join(d, "meta.json"), "w") as f:
        json.dump({"variant": variant, "D": D, "Q": Q, "m": m, "seed": seed,
                   "tag": tag, "ttt": ttt, "ssm": ssm, "route_file": rou,
                   "net": netf, "plan": plan}, f, indent=1)
    open(os.path.join(d, "DONE"), "w").close()
    return d


if __name__ == "__main__":
    v, D, Q, m, s = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]), int(sys.argv[5])
    print(run_cell(v, D, Q, m, s))
