#!/usr/bin/env python3
"""Copy the small final deliverables into the episodic-memory outputs/ directory.

Large raw traces (full duaIterate iteration dumps, per-run SUMO outputs) stay in
attempts/attempt-1/work/.
"""
import os
import shutil
import sys

ATT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EP = os.path.dirname(os.path.dirname(ATT))
OUT = os.path.join(EP, "outputs")

COPY = [
    # networks + plain-XML sources
    ("work/net/braess_nolink.net.xml", "network/braess_nolink.net.xml"),
    ("work/net/braess_link.net.xml", "network/braess_link.net.xml"),
    ("work/net/braess_nolink.nod.xml", "network/braess_nolink.nod.xml"),
    ("work/net/braess_nolink.edg.xml", "network/braess_nolink.edg.xml"),
    ("work/net/braess_nolink.con.xml", "network/braess_nolink.con.xml"),
    ("work/net/braess_link.nod.xml", "network/braess_link.nod.xml"),
    ("work/net/braess_link.edg.xml", "network/braess_link.edg.xml"),
    ("work/net/braess_link.con.xml", "network/braess_link.con.xml"),
    # link performance functions
    ("work/lpf_measured.csv", "link_performance/lpf_measured.csv"),
    ("work/lpf_fits.json", "link_performance/lpf_fits.json"),
    ("work/fig_link_performance_functions.png", "link_performance/fig_link_performance_functions.png"),
    # results
    ("work/analysis/cases.csv", "results/cases.csv"),
    ("work/analysis/paradox_table.csv", "results/paradox_table.csv"),
    ("work/analysis/summary.json", "results/summary.json"),
    ("work/analysis/route_choice_model_robustness.csv", "results/route_choice_model_robustness.csv"),
    ("work/fig_braess_paradox.png", "results/fig_braess_paradox.png"),
    # price of anarchy
    ("work/poa/poa_sweep.csv", "price_of_anarchy/poa_sweep.csv"),
    ("work/poa/poa_summary.json", "price_of_anarchy/poa_summary.json"),
]


def main():
    os.makedirs(OUT, exist_ok=True)
    for src, dst in COPY:
        s = os.path.join(ATT, src)
        d = os.path.join(OUT, dst)
        if not os.path.exists(s):
            print("MISSING", s, file=sys.stderr)
            continue
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copy(s, d)
        print("->", os.path.relpath(d, EP))
    # convergence traces (one small csv per duaIterate run)
    cdir = os.path.join(OUT, "convergence_traces")
    os.makedirs(cdir, exist_ok=True)
    n = 0
    for f in sorted(os.listdir(os.path.join(ATT, "work/analysis"))):
        if f.startswith("convergence_") and f.endswith(".csv"):
            shutil.copy(os.path.join(ATT, "work/analysis", f), os.path.join(cdir, f))
            n += 1
    print(f"-> outputs/convergence_traces/  ({n} files)")
    # demand definition + duaIterate configuration, one representative copy
    ddir = os.path.join(OUT, "demand_and_config")
    os.makedirs(ddir, exist_ok=True)
    for case in ("gawron_link_2400", "gawron_nolink_2400"):
        src = os.path.join(ATT, "work/due", case)
        for f, dst in (("demand.flows.xml", f"{case}.demand.flows.xml"),
                       ("dua/duaIterate.cmd", f"{case}.duaIterate.cmd"),
                       ("converged.rou.xml", f"{case}.converged.rou.xml")):
            if os.path.exists(os.path.join(src, f)):
                shutil.copy(os.path.join(src, f), os.path.join(ddir, dst))
                print("-> outputs/demand_and_config/" + dst)
    # scripts
    sdir = os.path.join(OUT, "scripts")
    os.makedirs(sdir, exist_ok=True)
    for f in sorted(os.listdir(os.path.join(ATT, "scripts"))):
        if f.endswith(".py"):
            shutil.copy(os.path.join(ATT, "scripts", f), os.path.join(sdir, f))
    print("-> outputs/scripts/")


if __name__ == "__main__":
    main()
