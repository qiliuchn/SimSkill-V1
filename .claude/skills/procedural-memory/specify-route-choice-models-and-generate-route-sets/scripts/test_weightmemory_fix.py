#!/usr/bin/env python3
"""Test whether --weight-memory (edge-weight smoothing across duaIterate iterations) --
which provides the same kind of iteration-to-iteration damping that Gawron's own update
rule has implicitly, and logit (confirmed memoryless in sub-goal 1) structurally lacks --
fixes logit's non-convergence at demand=2200, on top of a moderate FIXED theta (avoiding
the auto-theta 1/spread blow-up mechanism identified separately).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DUAITERATE = os.path.join(os.environ["SUMO_HOME"], "tools", "assign", "duaIterate.py")
NET = os.path.join(HERE, "netbuild", "braess_link.net.xml")


def write_demand(path, veh_per_hour, load_s):
    with open(path, "w") as f:
        f.write('<routes>\n')
        f.write(f'  <flow id="v" begin="0" end="{load_s}" vehsPerHour="{veh_per_hour}" '
                f'from="S_in" to="T_out" departLane="best" departSpeed="max"/>\n')
        f.write('</routes>\n')


def run(work, theta, weight_memory, demand=2200, last_step=20, seed=42):
    os.makedirs(work, exist_ok=True)
    demand_file = os.path.join(work, "demand.flows.xml")
    write_demand(demand_file, demand, 1800)
    cmd = [sys.executable, DUAITERATE, "-n", NET, "-F", demand_file,
           "-e", "7200", "-a", "7200", "-l", str(last_step),
           "--time-to-teleport=-1", "--disable-warnings",
           "--logit", "--logittheta", str(theta),
           "sumo--seed", str(seed)]
    if weight_memory:
        cmd.insert(-2, "--weight-memory")
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=work)
    with open(os.path.join(work, "stdout.txt"), "w") as f:
        f.write(r.stdout)
    with open(os.path.join(work, "stderr.txt"), "w") as f:
        f.write(r.stderr)
    if r.returncode != 0:
        print(f"FAILED {work}: {r.stderr[-2000:]}")
    return work


if __name__ == "__main__":
    demand = int(sys.argv[1]) if len(sys.argv) > 1 else 2200
    for theta, wm in [(0.05, True), (0.02, True), (0.05, False)]:
        tag = f"logit_theta{theta}_wm{wm}"
        work = os.path.join(HERE, "runs_fix", f"link_{demand}_{tag}")
        print("running", tag)
        run(work, theta, wm, demand=demand)
        print("done", tag)
