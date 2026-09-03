"""
Run every site x seed replication of the jurisdiction, in parallel.

Follows `run-simulation` conventions.  Per the `analyze-intersection-safety-with-ssm`
gotcha, the SSM output path is passed PER RUN on the sumo command line
(--device.ssm.file), never as a vType param.

Each run writes into its own directory so nothing (including edgeData-style
relative outputs) can collide between parallel workers -- the batch-replication
hazard flagged by `quantify-sumo-run-to-run-variability`.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def find_sumo():
    p = shutil.which("sumo")
    if p:
        return p
    sh = os.environ.get("SUMO_HOME")
    if sh and os.path.isfile(os.path.join(sh, "bin", "sumo")):
        return os.path.join(sh, "bin", "sumo")
    sys.exit("cannot find sumo")


SUMO = find_sumo()


def one_run(job):
    site, site_dir, seed, out_dir, end, variant = job
    os.makedirs(out_dir, exist_ok=True)
    net = os.path.join(site_dir, "%s.net.xml" % site)
    rou = os.path.join(site_dir, "%s.rou.xml" % site)
    add = os.path.join(site_dir, variant + ".add.xml") if variant else os.path.join(site_dir, "%s.add.xml" % site)
    cmd = [SUMO, "-n", net, "-r", rou, "-a", add,
           "--begin", "0", "--end", str(end),
           "--seed", str(seed),
           "--device.ssm.file", os.path.join(out_dir, "ssm.xml"),
           "--tripinfo-output", os.path.join(out_dir, "tripinfo.xml"),
           "--summary-output", os.path.join(out_dir, "summary.xml"),
           "--collision-output", os.path.join(out_dir, "collisions.xml"),
           "--time-to-teleport", "300",
           "--no-step-log", "true", "--duration-log.statistics", "true",
           "--xml-validation", "never", "--no-warnings", "true"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    ok = r.returncode == 0
    with open(os.path.join(out_dir, "run.log"), "w") as f:
        f.write("CMD: %s\nRC: %s\n--- STDOUT ---\n%s\n--- STDERR ---\n%s\n"
                % (" ".join(cmd), r.returncode, r.stdout, r.stderr))
    return dict(site=site, seed=seed, variant=variant or "base", ok=ok,
                out_dir=out_dir, stderr=r.stderr[:800])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites-root", required=True)
    ap.add_argument("--out-root", required=True)
    ap.add_argument("--seeds", required=True, help="comma list or A:B range")
    ap.add_argument("--only", default="", help="comma list of site ids (default: all in manifest)")
    ap.add_argument("--variant", default="", help="alternate <variant>.add.xml basename inside the site dir")
    ap.add_argument("--end", type=int, default=4200)
    ap.add_argument("--workers", type=int, default=9)
    a = ap.parse_args()

    if ":" in a.seeds:
        lo, hi = a.seeds.split(":")
        seeds = list(range(int(lo), int(hi)))
    else:
        seeds = [int(s) for s in a.seeds.split(",")]

    manifest = json.load(open(os.path.join(a.sites_root, "manifest.json")))
    wanted = set(s for s in a.only.split(",") if s) or None

    jobs = []
    for m in manifest:
        if wanted and m["site"] not in wanted:
            continue
        for sd in seeds:
            od = os.path.join(a.out_root, m["site"], "seed%d" % sd)
            jobs.append((m["site"], m["dir"], sd, od, a.end, a.variant))

    print("running %d jobs on %d workers" % (len(jobs), a.workers))
    results, failed = [], 0
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(one_run, j): j for j in jobs}
        for i, f in enumerate(as_completed(futs), 1):
            r = f.result()
            results.append(r)
            if not r["ok"]:
                failed += 1
                print("FAIL %s seed%s: %s" % (r["site"], r["seed"], r["stderr"][:300]))
            if i % 20 == 0:
                print("  %d/%d done" % (i, len(jobs)))

    os.makedirs(a.out_root, exist_ok=True)
    with open(os.path.join(a.out_root, "run_index.json"), "w") as f:
        json.dump(results, f, indent=2)
    print("done: %d ok, %d failed" % (len(results) - failed, failed))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
