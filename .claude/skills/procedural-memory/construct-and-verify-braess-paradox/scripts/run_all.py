#!/usr/bin/env python3
"""Driver: run duaIterate DUE for every (variant, demand) cell of the sweep, in parallel."""
import argparse
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))


def one(args):
    net, work, demand, last_step, logit, seed, conv_iters, conv_dev = args
    if os.path.exists(os.path.join(work, "convergence.json")):
        return f"skip {work}"
    cmd = [sys.executable, os.path.join(HERE, "run_due.py"), "--net", net, "--work", work,
           "--demand", str(demand), "--last-step", str(last_step), "--seed", str(seed),
           "--conv-iters", str(conv_iters), "--conv-dev", str(conv_dev)]
    if logit:
        cmd.append("--logit")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return f"FAIL {work}: {r.stderr[-1500:]}"
    return f"ok   {os.path.basename(work)}  {r.stdout.strip()}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--netdir", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--demands", type=int, nargs="*", default=[900, 1200, 1500, 1800, 2400, 3000, 3600])
    ap.add_argument("--last-step", type=int, default=120)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--logit-demands", type=int, nargs="*", default=[1800])
    ap.add_argument("--conv-iters", type=int, default=5)
    ap.add_argument("--conv-dev", type=float, default=0.002)
    a = ap.parse_args()

    jobs = []
    for v in ("nolink", "link"):
        net = os.path.join(a.netdir, f"braess_{v}.net.xml")
        for d in a.demands:
            jobs.append((net, os.path.join(a.work, f"gawron_{v}_{d}"), d, a.last_step, False, a.seed,
                         a.conv_iters, a.conv_dev))
        for d in a.logit_demands:
            jobs.append((net, os.path.join(a.work, f"logit_{v}_{d}"), d, a.last_step, True, a.seed,
                         a.conv_iters, a.conv_dev))
    with ThreadPoolExecutor(max_workers=a.jobs) as ex:
        for res in ex.map(one, jobs):
            print(res, flush=True)


if __name__ == "__main__":
    main()
