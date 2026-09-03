#!/usr/bin/env python3
"""Drive the one-way vs two-way demand sweep.

Design
------
* Common Random Numbers: replication r uses the same abstract OD realisation
  (demand seed r) AND the same sumo seed r in every variant, so variant is the
  only thing that changes within a replication.
* The abstract OD is resolved per variant and then RESTRICTED to the set of
  trips routable in *all three* variants, so every variant carries an
  identical trip population.
* Every replication gets its own additional-file copy and output directory --
  edgeData's `file` attribute resolves relative to the additional file's own
  directory, so sharing one additional file across parallel workers silently
  clobbers output.
"""
import argparse
import csv
import os
import shutil
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
VARIANTS = ["twoway", "oneway_fair", "oneway_naive"]

# Designated test arterial = the one-way PAIR {row 2, row 3}.
#   EB carriageway : EW_2_*_E   (row 2 is eastbound in the one-way pattern)
#   WB carriageway : EW_3_*_W   (row 3 is westbound)
# Both edge sets exist with IDENTICAL IDs in all three variants, so arterial
# demand, arterial routes and arterial measurement are literally the same edges
# in every variant.  The difference is that in the TWO-WAY net rows 2 and 3 also
# carry the opposing direction (EW_2_*_W / EW_3_*_E exist and are used by
# background demand), so one offset budget has to serve both directions on each
# street -- which is exactly the progression-bandwidth constraint under test.
ARTERIAL = {
    "EB": ["EW_2_%d_E" % i for i in range(4)],
    "WB": ["EW_3_%d_W" % i for i in range(4)],
}


def arterial_edges(variant):
    return ARTERIAL["EB"], ARTERIAL["WB"]


def sh(cmd, **kw):
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, **kw)
    if r.returncode != 0:
        raise RuntimeError("FAILED %s\n%s" % (" ".join(cmd), r.stdout[-4000:]))
    return r.stdout


def prepare_routes(work, nets, demand, seed, duration, through_share, art_vph=0.0):
    """Build the OD realisation and per-variant route files (CRN across variants)."""
    cell = os.path.join(work, "d%d_s%d" % (demand, seed))
    os.makedirs(cell, exist_ok=True)
    od = os.path.join(cell, "od.csv")
    done = os.path.join(cell, ".routes_ok")
    if os.path.exists(done):
        return cell
    sh([sys.executable, os.path.join(HERE, "gen_demand.py"), "-o", od,
        "--veh-per-hour", str(demand), "--seed", str(seed),
        "--duration", str(duration), "--through-share", str(through_share),
        "--arterial-vph", str(art_vph)])

    # pass 1: resolve per variant, collect commonly-routable trip ids
    common = None
    for v in VARIANTS:
        sh([sys.executable, os.path.join(HERE, "resolve_trips.py"),
            "-n", os.path.join(nets, v, "%s.net.xml" % v), "--od", od,
            "-o", os.path.join(cell, "%s.tmp.trips.xml" % v),
            "--dist-out", os.path.join(cell, "%s.dist.csv" % v)])
        ids = set(r["id"] for r in
                  csv.DictReader(open(os.path.join(cell, "%s.dist.csv" % v))))
        common = ids if common is None else (common & ids)

    # pass 2: rewrite the OD file to the common set, re-resolve, then route
    rows = [r for r in csv.DictReader(open(od)) if r["id"] in common]
    odc = os.path.join(cell, "od_common.csv")
    with open(odc, "w") as f:
        f.write("id,depart,origin,dest,kind\n")
        for r in rows:
            f.write("%s,%s,%s,%s,%s\n" % (r["id"], r["depart"], r["origin"],
                                          r["dest"], r["kind"]))
    for v in VARIANTS:
        net = os.path.join(nets, v, "%s.net.xml" % v)
        trips = os.path.join(cell, "%s.trips.xml" % v)
        sh([sys.executable, os.path.join(HERE, "resolve_trips.py"), "-n", net,
            "--od", odc, "-o", trips,
            "--dist-out", os.path.join(cell, "%s.dist.csv" % v)])
        sh(["duarouter", "-n", net, "-r", trips,
            "-o", os.path.join(cell, "%s.rou.xml" % v),
            "--no-step-log", "--no-warnings", "--ignore-errors",
            "--routing-algorithm", "dijkstra", "--seed", str(seed),
            "--alternatives-output", "NUL" if os.name == "nt" else "/dev/null"])
        tmp = os.path.join(cell, "%s.tmp.trips.xml" % v)
        if os.path.exists(tmp):
            os.remove(tmp)
    with open(os.path.join(cell, "n_common.txt"), "w") as f:
        f.write("%d/%d\n" % (len(rows), len(list(csv.DictReader(open(od))))))
    open(done, "w").close()
    return cell


def write_additional(rundir, variant, coord_src):
    """Per-run additional file: arterial edgeData + optional coordinated offsets."""
    eb, wb = arterial_edges(variant)
    path = os.path.join(rundir, "meas.add.xml")
    with open(path, "w") as f:
        f.write("<additional>\n")
        f.write('    <edgeData id="art_EB" file="edge_EB.xml" begin="0" end="99999"'
                ' excludeEmpty="true" edges="%s"/>\n' % " ".join(eb))
        f.write('    <edgeData id="art_WB" file="edge_WB.xml" begin="0" end="99999"'
                ' excludeEmpty="true" edges="%s"/>\n' % " ".join(wb))
        f.write('    <edgeData id="net_all" file="edge_all.xml" begin="0" end="99999"'
                ' excludeEmpty="true"/>\n')
        f.write("</additional>\n")
    adds = [path]
    if coord_src:
        dst = os.path.join(rundir, "offsets.add.xml")
        shutil.copy(coord_src, dst)
        adds.append(dst)
    return adds


def run_one(job):
    (work, nets, variant, demand, seed, duration, end, coord, coord_dir) = job
    cell = os.path.join(work, "d%d_s%d" % (demand, seed))
    tag = "%s_%s" % (variant, "coord" if coord else "base")
    rundir = os.path.join(cell, tag)
    os.makedirs(rundir, exist_ok=True)
    net = os.path.join(nets, variant, "%s.net.xml" % variant)
    rou = os.path.join(cell, "%s.rou.xml" % variant)
    coord_src = os.path.join(coord_dir, "%s.offsets.add.xml" % variant) if coord else None
    adds = write_additional(rundir, variant, coord_src)
    cmd = ["sumo", "-n", net, "-r", rou, "-a", ",".join(adds),
           "--tripinfo-output", os.path.join(rundir, "tripinfo.xml"),
           "--summary-output", os.path.join(rundir, "summary.xml"),
           "--statistic-output", os.path.join(rundir, "stats.xml"),
           "--seed", str(seed), "--end", str(end),
           "--time-to-teleport", "300", "--no-step-log", "--no-warnings",
           "--duration-log.statistics", "true",
           "--tripinfo-output.write-unfinished", "true"]
    try:
        sh(cmd)
        return (variant, demand, seed, coord, "ok", rundir)
    except Exception as e:
        return (variant, demand, seed, coord, "FAIL:%s" % str(e)[:300], rundir)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--work", required=True)
    p.add_argument("--nets", required=True)
    p.add_argument("--coord-dir", default=None)
    p.add_argument("--demands", type=int, nargs="+", required=True)
    p.add_argument("--seeds", type=int, nargs="+", required=True)
    p.add_argument("--duration", type=float, default=3600.0)
    p.add_argument("--end", type=float, default=9000.0)
    p.add_argument("--through-share", type=float, default=0.5)
    p.add_argument("--arterial-vph", type=float, default=0.0)
    p.add_argument("--coord", action="store_true")
    p.add_argument("--variants", nargs="+", default=VARIANTS)
    p.add_argument("--jobs", type=int, default=8)
    p.add_argument("--routes-only", action="store_true")
    a = p.parse_args()

    os.makedirs(a.work, exist_ok=True)
    for d in a.demands:
        for s in a.seeds:
            prepare_routes(a.work, a.nets, d, s, a.duration, a.through_share,
                           a.arterial_vph)
            print("routes ready d=%d s=%d" % (d, s), flush=True)
    if a.routes_only:
        return

    jobs = [(a.work, a.nets, v, d, s, a.duration, a.end, a.coord, a.coord_dir)
            for d in a.demands for s in a.seeds for v in a.variants]
    nfail = 0
    with ProcessPoolExecutor(max_workers=a.jobs) as ex:
        for i, r in enumerate(ex.map(run_one, jobs), 1):
            if not r[4].startswith("ok"):
                nfail += 1
                print("  !! %s" % (r,), flush=True)
            if i % 10 == 0 or i == len(jobs):
                print("  %d/%d done (%d failed)" % (i, len(jobs), nfail), flush=True)


if __name__ == "__main__":
    main()
