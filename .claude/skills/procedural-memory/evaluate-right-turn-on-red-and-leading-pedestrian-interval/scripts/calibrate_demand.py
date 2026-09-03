#!/usr/bin/env python3
"""Calibration sweep: right-turn movement CAPACITY vs pedestrian volume.

The 2x2 factorial is only informative if the No-Turn-on-Red baseline is not
already degenerate (v/c > 1).  This sweep loads the right turn to saturation
(1200 veh/h per approach) and measures the SERVED right-turn volume under NTOR
and RTOR at several pedestrian volumes, so the operational right-turn demand can
be set to a defensible fraction of the NTOR capacity.

Runs go through run_cell.py so the additional-file <tlLogic> is actually
ACTIVATED via traci.trafficlight.setProgram - an additional-file program with a
programID different from the net's own is NOT selected automatically.
"""
import json
import os
import subprocess
import sys
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gen_scenario                       # noqa: E402
from linkmap import LinkMap               # noqa: E402

BASE = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
OUT = os.path.join(BASE, "outputs")
CAL = os.path.join(OUT, "calibration")
WARM, ENDW = 600.0, 3600.0
WIN_H = (ENDW - WARM) / 3600.0


def routes(path, right_vph, ped_per_flow):
    out = ['<routes>', gen_scenario.VTYPE]
    for a, mv in gen_scenario.MOVES.items():
        for m in ("r", "s", "l"):
            out.append(f'    <route id="rt_{a}{m}" edges="in_{a} out_{mv[m]}"/>')
    for a in "NESW":
        for m, q in (("r", right_vph), ("s", 240.0), ("l", 80.0)):
            out.append(f'    <flow id="f_{a}{m}" type="car" route="rt_{a}{m}" begin="0" '
                       f'end="3600" period="exp({q/3600.0:.6f})" departLane="best" '
                       f'departSpeed="max"/>')
    if ped_per_flow > 0:
        for a in "NESW":
            for b in "NESW":
                if a != b:
                    out.append(f'    <personFlow id="p_{a}{b}" type="ped" begin="0" end="3600" '
                               f'perHour="{ped_per_flow}" departPos="250">')
                    out.append(f'        <walk from="in_{a}" to="out_{b}" arrivalPos="50"/>')
                    out.append('    </personFlow>')
    out.append('</routes>')
    open(path, "w").write("\n".join(out) + "\n")


def job(args):
    variant, cell, right_vph, ped = args
    tag = f"{variant}_{cell}_r{int(right_vph)}_p{int(ped)}"
    net = os.path.join(OUT, "net", f"{variant}.net.xml")
    lm = LinkMap(net)
    rv = {a: lm.veh[lm.right(a)]["via"] for a in "NESW"}
    rou = os.path.join(CAL, tag + ".rou.xml")
    det = os.path.join(CAL, tag + ".add.xml")
    routes(rou, right_vph, ped)
    gen_scenario.gen_detectors(det, variant, 300, os.path.join(CAL, tag), right_via=rv)
    cmd = [sys.executable, os.path.join(HERE, "run_cell.py"),
           "--net", net, "--routes", rou,
           "--program", os.path.join(OUT, "programs", f"{variant}.{cell}.tll.xml"),
           "--program-id", cell, "--detectors", det,
           "--outdir", CAL, "--tag", tag, "--seed", "1",
           "--demand-end", "3600", "--end", "4200", "--warmup", "600",
           "--freeflow", os.path.join(OUT, "freeflow", f"freeflow_{variant}.json")]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=HERE)
    if r.returncode != 0:
        return {"tag": tag, "error": r.stderr[-800:]}
    T = json.load(open(os.path.join(CAL, tag + "_traci.json")))
    te = [e for e in T["turn_events"] if WARM <= e["t"] < ENDW]
    red = sum(1 for e in te if e["char"] in "rs")
    grn = sum(1 for e in te if e["char"] in "gG")
    xe = sum(T["xing_entries"].values())
    return {"variant": variant, "cell": cell, "right_demand_vph_per_appr": right_vph,
            "ped_per_flow": ped,
            "ped_vph_per_crossing_measured": round(xe / 4.0 / (3600 / 3600.0), 1),
            "served_rt_vph_per_appr": round(len(te) / WIN_H / 4, 1),
            "onred_vph_per_appr": round(red / WIN_H / 4, 1),
            "ongreen_vph_per_appr": round(grn / WIN_H / 4, 1)}


if __name__ == "__main__":
    os.makedirs(CAL, exist_ok=True)
    jobs = [("A_excl", cell, 1200.0, ped)
            for ped in (0.0, 33.333, 66.667, 133.333)
            for cell in ("NTOR_noLPI", "RTOR_noLPI")]
    jobs += [("B_shared", cell, 1200.0, 66.667) for cell in ("NTOR_noLPI", "RTOR_noLPI")]
    with Pool(6) as p:
        res = p.map(job, jobs)
    json.dump(res, open(os.path.join(CAL, "capacity_vs_ped.json"), "w"), indent=2)
    for r in res:
        if "error" in r:
            print("ERR", r["tag"], r["error"][:200])
        else:
            print(f"{r['variant']:9s} {r['cell']:12s} ped/crossing="
                  f"{r['ped_vph_per_crossing_measured']:6.1f}  served="
                  f"{r['served_rt_vph_per_appr']:7.1f} veh/h/appr  "
                  f"(on-red {r['onred_vph_per_appr']:6.1f}, on-green "
                  f"{r['ongreen_vph_per_appr']:6.1f})")
