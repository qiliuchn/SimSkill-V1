#!/usr/bin/env python3
"""
Produce the lane-blocking VERIFICATION evidence set: one variant-A and one
variant-B run at the same volume/cell/seed, with FCD output restricted to the
curb-zone edges (so the trace stays small enough to ship as a deliverable),
then run verify_blocking.py over the pair.

FCD is filtered with --fcd-output.filter-edges.input-file, whose format is a
netedit-style selection file with one "edge:<id>" line per edge.

Usage: python3 run_verification.py --net-dir NET --out-dir DIR \
           [--volume 1800] [--cell D30] [--seed 1]
"""
import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scenario as SC   # noqa: E402
import run_cell as RC   # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--net-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--volume", type=int, default=1800)
    ap.add_argument("--cell", default="D30")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    net_dir = os.path.abspath(a.net_dir)
    out = os.path.abspath(a.out_dir)
    os.makedirs(out, exist_ok=True)

    dirs = {}
    for variant in ["A", "B"]:
        rd = os.path.join(out, f"variant{variant}")
        os.makedirs(rd, exist_ok=True)
        SC.build_run_dir(rd, variant, a.volume, a.cell, a.seed)
        with open(os.path.join(rd, "fcd_edges.txt"), "w") as fh:
            fh.write("edge:E0\nedge:ECURB\nedge:E2\n")
        cmd = [
            "sumo", "-n", os.path.join(net_dir, f"variant{variant}.net.xml"),
            "-r", "routes.rou.xml", "-a", "extra.add.xml",
            "--begin", "0", "--end", str(SC.SIM_END), "--seed", str(a.seed),
            "--tripinfo-output", "tripinfo.xml",
            "--summary-output", "summary.xml",
            "--stop-output", "stops.xml",
            "--lanechange-output", "lanechange.xml",
            "--fcd-output", "fcd.xml",
            "--fcd-output.filter-edges.input-file", "fcd_edges.txt",
            "--fcd-output.skip-empty",
            "--time-to-teleport", "300",
            "--no-step-log", "--xml-validation", "never",
            "--duration-log.statistics", "true", "--no-warnings", "true",
        ]
        p = subprocess.run(cmd, cwd=rd, capture_output=True, text=True)
        if p.returncode != 0:
            raise SystemExit(f"sumo failed ({variant}):\n{p.stderr[-3000:]}")
        dirs[variant] = rd
        print(f"variant {variant}: fcd = "
              f"{os.path.getsize(os.path.join(rd, 'fcd.xml'))/1e6:.1f} MB")

    here = os.path.dirname(os.path.abspath(__file__))
    rep = subprocess.run(
        [sys.executable, os.path.join(here, "verify_blocking.py"),
         dirs["A"], dirs["B"]], capture_output=True, text=True)
    txt = (f"LANE-BLOCKING VERIFICATION\n"
           f"volume={a.volume} veh/h  cell={a.cell}  seed={a.seed} "
           f"(identical seed in both variants)\n\n" + rep.stdout + rep.stderr)
    with open(os.path.join(out, "verification.txt"), "w") as fh:
        fh.write(txt)
    print(txt)


if __name__ == "__main__":
    main()
