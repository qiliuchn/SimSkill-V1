#!/usr/bin/env python3
"""Run the DDI and conventional-diamond scenarios under IDENTICAL demand and seed.
Each scenario: net = <design>.net.xml, additional = <design>.tll.xml + detectors.add.xml.
Outputs tripinfo, summary, and E1 detector file into runs/<design>/."""
import os, subprocess, shutil

BASE = "/Users/liuqi/Desktop/simskill/episodic-memory/2026-07-30_09-43-42/attempts/attempt-1"
OUT = os.path.join(BASE, "outputs")
SEED = "42"
END = "1200"

def run(design):
    rundir = os.path.join(BASE, "runs", design)
    os.makedirs(rundir, exist_ok=True)
    # SUMO writes a detector's `file` relative to the additional-file's own directory,
    # so write a per-scenario detector add-file with an ABSOLUTE output path into rundir.
    with open(os.path.join(OUT, "detectors.add.xml")) as f:
        det = f.read()
    e1_abs = os.path.join(rundir, "e1_out.xml")
    det = det.replace('file="e1_out.xml"', f'file="{e1_abs}"')
    det_path = os.path.join(rundir, "detectors.add.xml")
    with open(det_path, "w") as f:
        f.write(det)
    cmd = ["sumo",
           "-n", os.path.join(OUT, f"{design}.net.xml"),
           "-r", os.path.join(OUT, "demand.rou.xml"),
           "-a", f"{os.path.join(OUT, design + '.tll.xml')},{det_path}",
           "--tripinfo-output", os.path.join(rundir, "tripinfo.xml"),
           "--summary-output", os.path.join(rundir, "summary.xml"),
           "--seed", SEED,
           "--begin", "0", "--end", END,
           "--time-to-teleport", "120",
           "--duration-log.statistics", "true",
           "--no-step-log", "true",
           "--tripinfo-output.write-unfinished", "true"]
    print("=== running", design, "===")
    r = subprocess.run(cmd, cwd=rundir, capture_output=True, text=True)
    print(r.stdout[-2000:])
    if r.stderr:
        print("STDERR:", r.stderr[-3000:])
    # E1 file 'e1_out.xml' lands in rundir (relative file path)
    return r.returncode

if __name__ == "__main__":
    codes = {d: run(d) for d in ("ddi", "conv")}
    print("return codes:", codes)
