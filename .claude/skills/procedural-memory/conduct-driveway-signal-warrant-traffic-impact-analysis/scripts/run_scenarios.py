#!/usr/bin/env python3
"""
Execute every scenario x control x seed combination.

Run discipline
  * 3 seeds per (scenario, control) using a COMMON seed list across every
    control arm (Common Random Numbers -- quantify-sumo-run-to-run-variability).
  * --time-to-teleport 300 s: comfortably above the longest legitimate red
    (max cycle 105 s), and finite so a deadlocked driveway does not produce a
    survivorship-censored travel-time mean
    (validate-congested-scenario-results-against-teleport-artifacts).
  * No --max-depart-delay: vehicles that cannot be inserted stay in the
    insertion backlog and are counted, rather than being silently dropped --
    this backlog IS the demand-vs-served-volume measurement.
  * Demand ends at 43200 s (19:00); the simulation runs to 54000 s (22:00) so
    residual queues drain and their delay is not truncated out of tripinfo.
  * --tripinfo-output.write-unfinished so vehicles still running at the end
    still appear.
"""
import gzip
import multiprocessing as mp
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (RUNS, SCEN, DEMAND_END, DRAIN_END, STEP_LENGTH, find_bin, run, write)

NETD = os.path.join(SCEN, "net")
DEMD = os.path.join(SCEN, "demand")
DETD = os.path.join(SCEN, "detectors")
SIGD = os.path.join(SCEN, "signal")

SEEDS = [11, 23, 37]
SCENARIOS = ["nobuild", "build", "build_high"]
SWEEP = ["site015", "site025", "site040", "site050", "site075", "site150", "site300"]

# control -> (net variant, route/detector variant, extra additional files)
CONTROLS = {
    "twsc":      ("twsc",      "std",  []),
    "sig_fixed": ("signal",    "std",  ["@SCEN@_fixed.add.xml"]),
    "sig_act":   ("signal",    "std",  ["@SCEN@_act.add.xml"]),
    "twsc_rt":   ("twsc_rt",   "rt",   []),
    "twsc_riro": ("twsc_riro", "riro", []),
}
MITIGATION_SCENARIOS = ["build", "build_high"]
# NO-BUILD is also signalised, to test the other half of the 2x2:
# does a signal help when NO volume warrant is met at the 100% column?
NOBUILD_CONTROLS = ["sig_fixed", "sig_act"]


def build_jobs():
    jobs = []
    # ---- warrant phase: TWSC (the existing/no-mitigation condition) everywhere
    for scen in SCENARIOS:
        for seed in SEEDS:
            jobs.append(dict(name=f"{scen}__twsc__s{seed}", scen=scen, control="twsc",
                             seed=seed, scale=1.0))
    for ctrl in NOBUILD_CONTROLS:
        for seed in SEEDS:
            jobs.append(dict(name=f"nobuild__{ctrl}__s{seed}", scen="nobuild",
                             control=ctrl, seed=seed, scale=1.0))
    # ---- site-intensity sweep (TWSC, single seed): where does the detector-based
    #      warrant conclusion first diverge from the demand-based one?
    for scen in SWEEP:
        jobs.append(dict(name=f"{scen}__twsc__s11", scen=scen, control="twsc",
                         seed=11, scale=1.0))
    # ---- mitigation phase
    for scen in MITIGATION_SCENARIOS:
        for ctrl in CONTROLS:
            if ctrl == "twsc":
                continue
            for seed in SEEDS:
                jobs.append(dict(name=f"{scen}__{ctrl}__s{seed}", scen=scen, control=ctrl,
                                 seed=seed, scale=1.0))
    # ---- free-flow datum runs (control delay reference).  Two very light demand
    #      levels; the datum is the MINIMUM hourly mean segment time over both,
    #      never a geometric length/speed calculation.
    for ctrl, variant in (("twsc", "std"), ("twsc_rt", "rt"), ("twsc_riro", "riro")):
        for sc, tag in ((0.05, "a"), (0.25, "b")):
            jobs.append(dict(name=f"freeflow{tag}__{ctrl}", scen="build", control=ctrl,
                             seed=11, scale=sc))
    # ---- actuated detector-binding verification (detectors deliberately misplaced)
    for seed in SEEDS[:1]:
        jobs.append(dict(name=f"build_high__sig_act_MISPLACED__s{seed}", scen="build_high",
                         control="sig_act", seed=seed, scale=1.0, misplaced=True))
    # ---- teleport sensitivity: worst case with teleporting disabled
    for seed in SEEDS[:1]:
        jobs.append(dict(name=f"build_high__twsc_TTTOFF__s{seed}", scen="build_high",
                         control="twsc", seed=seed, scale=1.0, ttt="-1"))
    return jobs


def prepare(job):
    net_variant, det_variant, extras = CONTROLS[job["control"]]
    d = os.path.join(RUNS, job["name"])
    if os.path.isdir(d):
        shutil.rmtree(d)
    os.makedirs(d)
    # detector additional file, with output paths rewritten to this run's own dir
    src = open(os.path.join(DETD, f"det_{det_variant}.add.xml")).read()
    write(os.path.join(d, "det.add.xml"), src.replace("@OUTDIR@/", ""))
    adds = ["det.add.xml"]
    for e in extras:
        fn = e.replace("@SCEN@", job["scen"])
        if job.get("misplaced"):
            fn = fn.replace(".add.xml", "_MISPLACED.add.xml")
        shutil.copy(os.path.join(SIGD, fn), os.path.join(d, "signal.add.xml"))
        adds.append("signal.add.xml")
        write(os.path.join(d, "tlslog.add.xml"),
              '<?xml version="1.0" encoding="UTF-8"?>\n<additional>\n'
              '  <timedEvent type="SaveTLSSwitchStates" source="C" dest="tls_switch.xml"/>\n'
              "</additional>\n")
        adds.append("tlslog.add.xml")
    return d, os.path.join(NETD, f"{net_variant}.net.xml"), \
        os.path.join(DEMD, f"{job['scen']}_{det_variant}.rou.xml"), adds


def execute(job):
    d, net, rou, adds = prepare(job)
    cmd = [find_bin("sumo"), "-n", net, "-r", rou, "-a", ",".join(adds),
           "--begin", "0", "--end", str(DRAIN_END),
           "--step-length", str(STEP_LENGTH), "--step-method.ballistic",
           "--seed", str(job["seed"]),
           "--time-to-teleport", str(job.get("ttt", 300)),
           "--tripinfo-output", "tripinfo.xml.gz",
           "--tripinfo-output.write-unfinished", "true",
           "--summary-output", "summary.xml",
           "--summary-output.period", "60",
           "--statistic-output", "statistics.xml",
           "--duration-log.statistics", "true",
           "--collision.action", "warn",
           "--collision-output", "collisions.xml",
           "--no-warnings", "true",
           "--no-step-log", "true", "--xml-validation", "never"]
    if abs(job["scale"] - 1.0) > 1e-9:
        cmd += ["--scale", str(job["scale"])]
    r = run(cmd, cwd=d)
    write(os.path.join(d, "cmd.txt"), " ".join(cmd) + f"\n(cwd={d})\n")
    ok = r.returncode == 0
    # teleports / collisions come from statistics.xml (authoritative cumulative
    # counters) rather than from grepping the log -- warnings are suppressed
    # because the shared-entry e3 detectors emit one "arrived inside" warning
    # per vehicle per non-matching movement, which dominates the log file.
    tel = col = -1
    sp = os.path.join(d, "statistics.xml")
    if os.path.isfile(sp):
        txt = open(sp, errors="replace").read()
        m = re.search(r'<teleports total="(\d+)"', txt)
        tel = int(m.group(1)) if m else -1
        m = re.search(r'<safety collisions="(\d+)"', txt)
        col = int(m.group(1)) if m else -1
    if not ok:
        write(os.path.join(d, "FAILED.txt"), r.stderr[-8000:])
    return job["name"], ok, tel, col, r.stderr[-400:] if not ok else ""


def main():
    jobs = build_jobs()
    only = sys.argv[1] if len(sys.argv) > 1 else None
    if only:
        jobs = [j for j in jobs if only in j["name"]]
    print(f"[run] {len(jobs)} runs, {mp.cpu_count()} cpus")
    with mp.Pool(min(8, mp.cpu_count())) as pool:
        for name, ok, tel, col, err in pool.imap_unordered(execute, jobs):
            print(f"[run] {'OK ' if ok else 'FAIL'} {name:42s} teleports={tel} "
                  f"collisions={col} {err}")


if __name__ == "__main__":
    main()
