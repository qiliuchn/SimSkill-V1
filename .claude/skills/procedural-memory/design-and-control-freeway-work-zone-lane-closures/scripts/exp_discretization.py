"""Step 0: choose and JUSTIFY the time discretization, per
`choose-time-discretization-and-integration-method` / [[sumo-time-discretization]].

Two parts, both actually executed (not cited):

(A) INTEGRATOR PROBE -- a single deterministic vehicle (sigma=0, speedDev=0)
    accelerating from rest on a free lane has the closed form x(t)=0.5*a*t^2.
    Diff SUMO's reported position against it to confirm, on THIS SUMO build, that
    Euler runs ahead by a*dt*t/2 (settling to v*dt/2) and ballistic is exact.

(B) CONVERGENCE SWEEP on the ACTUAL work-zone testbed, dt in {1.0, 0.5, 0.25} s,
    two families: actionStepLength TIED to dt, and PINNED at 1.0 s.  CRN throughout
    (identical explicit-departure route file, identical sumo --seed).  Reference cell
    is dt=0.25 s, ballistic, actionStepLength=1.0 s.

    NOTE on reachable cells: a vType actionStepLength strictly greater than
    --step-length force-enables ballistic.  So the (Euler, pinned) cell does not exist
    at dt<1.0 and is not reported as measured.
"""
import json
import os
import re
import subprocess
import time
import xml.etree.ElementTree as ET

import numpy as np

import wz_common as W
import gen_demand
import gen_additional as GA
import analyze
import run_wz

OUTD = os.path.join(W.OUT, "discretization")
os.makedirs(OUTD, exist_ok=True)


# ------------------------------------------------------------------ (A) probe
def integrator_probe():
    d = os.path.join(OUTD, "probe")
    os.makedirs(d, exist_ok=True)
    with open(f"{d}/p.nod.xml", "w") as f:
        f.write('<nodes><node id="a" x="0" y="0"/><node id="b" x="3000" y="0"/></nodes>')
    with open(f"{d}/p.edg.xml", "w") as f:
        f.write('<edges><edge id="e" from="a" to="b" numLanes="1" speed="13.89"/></edges>')
    subprocess.run([W.NETCONVERT, "--node-files", f"{d}/p.nod.xml", "--edge-files",
                    f"{d}/p.edg.xml", "-o", f"{d}/p.net.xml"], check=True,
                   capture_output=True)
    A = 2.6
    rows = []
    for step in (1.0, 0.5, 0.25, 0.1):
        for method in ("euler", "ballistic"):
            with open(f"{d}/p.rou.xml", "w") as f:
                f.write(f'<routes><vType id="t" accel="{A}" decel="4.5" sigma="0" '
                        f'speedDev="0" length="5" minGap="2.5" maxSpeed="13.89" '
                        f'speedFactor="1.0" actionStepLength="{step}"/>'
                        f'<route id="r" edges="e"/>'
                        f'<vehicle id="v" type="t" route="r" depart="0" '
                        f'departSpeed="0" departPos="0"/></routes>')
            cmd = [W.SUMO, "-n", f"{d}/p.net.xml", "-r", f"{d}/p.rou.xml",
                   "--step-length", str(step), "--end", "60",
                   "--fcd-output", f"{d}/fcd.xml", "--no-step-log", "true",
                   "--no-warnings", "true"]
            if method == "ballistic":
                cmd.append("--step-method.ballistic")
            subprocess.run(cmd, check=True, capture_output=True)
            root = ET.parse(f"{d}/fcd.xml").getroot()
            err1 = None
            settled = []
            for ts in root.findall("timestep"):
                t = float(ts.get("time"))
                v = ts.find("vehicle")
                if v is None:
                    continue
                x = float(v.get("x"))
                sp = float(v.get("speed"))
                if abs(t - 1.0) < 1e-9:
                    err1 = x - 0.5 * A * t * t
                if sp >= 13.88 and t > 8:
                    settled.append(x - (13.89 * t - 13.89 ** 2 / (2 * A)))
            rows.append(dict(step=step, method=method,
                             err_at_1s=err1,
                             settled_offset=float(np.mean(settled)) if settled else None,
                             predicted_euler_offset=13.89 * step / 2))
    return rows


# ------------------------------------------------------------------ (B) sweep
def rou_with_asl(src, dst, asl):
    txt = open(src).read()
    txt = re.sub(r'actionStepLength="[^"]*"', f'actionStepLength="{asl}"', txt)
    with open(dst, "w") as f:
        f.write(txt)
    return dst


def convergence(peak=3600, seeds=(1, 2, 3)):
    p = W.params()
    net = W.build_net(p, "geom", merge="priority")
    base_rou, _ = gen_demand.gen(peak, 101, 0.0)
    cells = []
    for step in (1.0, 0.5, 0.25):
        for fam in ("tied", "pinned"):
            for method in ("ballistic", "euler"):
                if fam == "pinned" and method == "euler" and step < 1.0:
                    continue  # unreachable: asl>dt force-enables ballistic
                cells.append((step, fam, method))
    rows = []
    for step, fam, method in cells:
        asl = step if fam == "tied" else 1.0
        rou = rou_with_asl(base_rou, os.path.join(OUTD, f"rou_asl{asl}.rou.xml"), asl)
        for seed in seeds:
            lab = f"dt{step}_{fam}_{method}_s{seed}"
            od = os.path.join(OUTD, lab)
            add = GA.build(net, od, lab, e2=True)
            t0 = time.time()
            m = run_wz.run(net, rou, add, od, "donothing", p, seed=seed, step=step,
                           ballistic=(method == "ballistic"))
            wall = time.time() - t0
            s = analyze.summarize(od, 2)
            rows.append(dict(step=step, family=fam, method=method, asl=asl, seed=seed,
                             wall=wall, cap=s["cap"], mean_duration=s["mean_duration"],
                             mean_timeloss=s["mean_timeloss"],
                             hard_brakes=m["hard_brakes"],
                             hard_brakes_taper=m["hard_brakes_taper"],
                             completed=s["n"], still_running=s.get("running"),
                             teleports=s.get("teleports"),
                             collisions=s["n_collisions"],
                             CO2_kg=s["CO2_kg"], TSTT_vh=s["TSTT_vh"]))
            print(f"  {lab}: cap={s['cap']:.0f} dur={s['mean_duration']:.0f} "
                  f"hb={m['hard_brakes']} wall={wall:.0f}s", flush=True)
    return rows


if __name__ == "__main__":
    print("=== (A) integrator probe ===", flush=True)
    probe = integrator_probe()
    for r in probe:
        print(f"  dt={r['step']:<5} {r['method']:<10} err@1s={r['err_at_1s']:+.4f} m  "
              f"settled={r['settled_offset'] if r['settled_offset'] is None else round(r['settled_offset'],4)}  "
              f"pred_euler_offset={r['predicted_euler_offset']:.3f}")
    print("\n=== (B) convergence sweep on the work-zone testbed ===", flush=True)
    conv = convergence()
    json.dump(dict(probe=probe, convergence=conv),
              open(os.path.join(OUTD, "discretization_results.json"), "w"), indent=1)
    print("\nwrote", os.path.join(OUTD, "discretization_results.json"))
