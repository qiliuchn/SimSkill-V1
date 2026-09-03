#!/usr/bin/env python3
"""Parallel driver: expands a JSON job list and runs each through runner.py."""
import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
ENV = dict(os.environ)
ENV.setdefault("SUMO_HOME", "/Library/Frameworks/EclipseSUMO.framework/"
                            "Versions/1.27.1/EclipseSUMO/share/sumo")


def one(job):
    out = job["outdir"]
    if os.path.exists(os.path.join(out, "stats.json")) and not job.get("force"):
        return (out, "cached")
    cmd = [sys.executable, os.path.join(HERE, "runner.py")]
    for k, v in job.items():
        if k in ("force", "tag"):
            continue
        cmd += ["--" + k.replace("_", "-"), str(v)]
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True, env=ENV)
    if p.returncode != 0:
        return (out, "FAIL rc=%d %s" % (p.returncode, p.stderr[-1500:]))
    return (out, "ok %.0fs" % (time.time() - t0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", required=True)
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    jobs = json.load(open(a.jobs))
    print("running %d jobs on %d workers" % (len(jobs), a.workers), flush=True)
    ok = fail = 0
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        for i, (out, msg) in enumerate(ex.map(one, jobs)):
            if msg.startswith("FAIL"):
                fail += 1
                print("[%d/%d] %s -> %s" % (i + 1, len(jobs), out, msg), flush=True)
            else:
                ok += 1
                if (i + 1) % 10 == 0 or i == 0:
                    print("[%d/%d] %s %s" % (i + 1, len(jobs), out, msg), flush=True)
    print("DONE ok=%d fail=%d" % (ok, fail), flush=True)


if __name__ == "__main__":
    main()
