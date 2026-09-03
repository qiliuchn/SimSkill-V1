#!/usr/bin/env python3
"""Re-run one replication with FCD output restricted to the arterial edges,
so a time-space trajectory diagram can be drawn."""
import argparse
import os
import subprocess
import sys

N = 5
EB = ["EW_2_%d_E" % i for i in range(N - 1)]
WB = ["EW_3_%d_W" % i for i in range(N - 1)] + ["EW_2_%d_W" % i for i in range(N - 1)]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--net", required=True)
    p.add_argument("--routes", required=True)
    p.add_argument("--outdir", required=True)
    p.add_argument("--offsets", default=None)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--end", type=float, default=12000)
    p.add_argument("--fcd-begin", type=float, default=0)
    a = p.parse_args()
    os.makedirs(a.outdir, exist_ok=True)

    # GOTCHA: --fcd-output.filter-edges.input-file wants a netedit SELECTION
    # file ("edge:<ID>" per line).  Handing it an additional file with
    # <edgeData edges="..."/> is accepted without error but silently filters
    # almost everything away (verified: whole-run FCD came out empty, and in a
    # multi-edge attempt two of eight arterial edges vanished with no warning).
    filt = os.path.join(a.outdir, "fcdfilter.sel.txt")
    with open(filt, "w") as f:
        for e in EB + WB:
            f.write("edge:%s\n" % e)

    adds = [filt]
    if a.offsets:
        adds.append(a.offsets)
    cmd = ["sumo", "-n", a.net, "-r", a.routes,
           "--fcd-output", os.path.join(a.outdir, "fcd.xml"),
           "--fcd-output.filter-edges.input-file", filt,
           "--fcd-output.attributes", "x,y,speed,lane",
           "--tripinfo-output", os.path.join(a.outdir, "tripinfo.xml"),
           "--device.fcd.begin", str(a.fcd_begin),
           "--seed", str(a.seed), "--end", str(a.end),
           "--time-to-teleport", "300", "--no-step-log", "--no-warnings",
           "--tripinfo-output.write-unfinished", "true"]
    if a.offsets:
        cmd += ["-a", a.offsets]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True)
    print(r.returncode, r.stdout[-1500:])
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
