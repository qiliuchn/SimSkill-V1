#!/usr/bin/env python3
"""Run tlsCoordinator.py on each variant with identical settings.

Cycle-length prerequisite: netconvert already gives EVERY traffic light in all
three variants a uniform 90 s static cycle (verified programmatically), so the
`tlsCycleAdaptation --unified-cycle` pre-step is unnecessary here.  We
deliberately do NOT run tlsCycleAdaptation: it sizes cycles from demand and
would hand the two variants DIFFERENT cycle lengths, breaking the "same fixed
cycle length in both networks" control this experiment requires.

--speed-factor is held identical across variants so the offset optimiser assumes
the same progression speed in each.
"""
import argparse
import os
import subprocess
import sys

TOOL = os.path.join(os.environ["SUMO_HOME"], "tools", "tlsCoordinator.py")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--nets", required=True)
    p.add_argument("--cell", required=True, help="dir holding <variant>.rou.xml")
    p.add_argument("-o", "--outdir", required=True)
    p.add_argument("--speed-factor", type=float, default=0.8)
    p.add_argument("--variants", nargs="+",
                   default=["twoway", "oneway_fair", "oneway_naive"])
    a = p.parse_args()
    os.makedirs(a.outdir, exist_ok=True)

    for v in a.variants:
        net = os.path.join(a.nets, v, "%s.net.xml" % v)
        rou = os.path.join(a.cell, "%s.rou.xml" % v)
        out = os.path.join(a.outdir, "%s.offsets.add.xml" % v)
        cmd = [sys.executable, TOOL, "-n", net, "-r", rou, "-o", out,
               "--speed-factor", str(a.speed_factor)]
        r = subprocess.run(cmd, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True)
        print("[%s] rc=%d" % (v, r.returncode))
        print("   " + r.stdout.strip().replace("\n", "\n   ")[:800])
        if r.returncode != 0:
            sys.exit(1)


if __name__ == "__main__":
    main()
