#!/usr/bin/env python3
"""Sweep driver: advance preemption time x through-demand level, plus the
short-train-headway stability test.  Each cell is an independent SUMO process
(own TraCI port); results land in outputs/runs/<cell>/."""
import concurrent.futures as cf
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
RUNS = os.path.join(ROOT, "outputs", "runs")
os.makedirs(RUNS, exist_ok=True)

EB_LEVELS = [450, 600, 750]
APTS = [0, 5, 10, 15, 20, 25, 30]
SEED = 42
END = 3600
TCG = 25.0


def cells():
    out = []
    for eb in EB_LEVELS:                       # baselines, normal headway
        out.append(dict(eb=eb, headway=290, preempt=0, apt=0,
                        name=f"base_eb{eb}_h290"))
    for eb in EB_LEVELS:                       # APT sweep
        for apt in APTS:
            out.append(dict(eb=eb, headway=290, preempt=1, apt=apt,
                            name=f"pre_eb{eb}_h290_apt{apt}"))
    for eb in (600, 750):                      # short-headway stability test
        out.append(dict(eb=eb, headway=120, preempt=0, apt=0,
                        name=f"base_eb{eb}_h120"))
        out.append(dict(eb=eb, headway=120, preempt=1, apt=25,
                        name=f"pre_eb{eb}_h120_apt25"))
    return out


def run_cell(c):
    od = os.path.join(RUNS, c["name"])
    cmd = [sys.executable, os.path.join(HERE, "preempt_sim.py"),
           "--eb", str(c["eb"]), "--headway", str(c["headway"]),
           "--apt", str(c["apt"]), "--preempt", str(c["preempt"]),
           "--tcg", str(TCG), "--seed", str(SEED), "--end", str(END),
           "--outdir", od, "--label", c["name"]]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=HERE)
    ok = os.path.exists(os.path.join(od, "events.json"))
    return {"name": c["name"], "ok": ok, "rc": r.returncode,
            "stdout": r.stdout.strip()[-400:], "stderr": r.stderr.strip()[-400:]}


if __name__ == "__main__":
    cs = cells()
    print(f"{len(cs)} cells")
    with cf.ThreadPoolExecutor(max_workers=7) as ex:
        res = list(ex.map(run_cell, cs))
    bad = [r for r in res if not r["ok"]]
    with open(os.path.join(RUNS, "sweep_status.json"), "w") as f:
        json.dump(res, f, indent=2)
    for r in res:
        print(r["name"], "OK" if r["ok"] else "FAIL", r["stdout"][:200])
    print("FAILED:", [r["name"] for r in bad])
