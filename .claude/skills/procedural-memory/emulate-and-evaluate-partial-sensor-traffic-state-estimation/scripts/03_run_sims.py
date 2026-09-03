#!/usr/bin/env python3
"""
03_run_sims.py -- run the master (ground-truth) simulation and the sensing arms.

All arms share:  identical net, identical routes, identical fixed-time TLS,
identical --seed  (Common Random Numbers).  The ONLY thing that differs between
sensing arms is the FCD device configuration (--device.fcd.probability /
--device.fcd.period), i.e. the observation layer.

Arms
----
  master      : fcd.probability=1.0, fcd.period=1  -> ground truth trajectories
  p<pct>_<T>  : fcd.probability=pct/100, fcd.period=T  (real SUMO probe arms)
  ttt<X>      : teleport-sensitivity arms (--time-to-teleport swept)

Usage:  python3 03_run_sims.py [pilot|master|arms|teleport|all]
"""
import hashlib
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCEN = os.path.abspath(os.path.join(HERE, "..", "scenario"))
RUNS = os.path.abspath(os.path.join(HERE, "..", "..", "runs"))
os.makedirs(RUNS, exist_ok=True)

SEED = 42
SIM_END = 5400
TTT_DEFAULT = 300


def build_cmd(outdir, fcd=None, fcd_prob=None, fcd_period=None, ttt=TTT_DEFAULT,
              e1=True, edgedata=True, seed=SEED):
    os.makedirs(outdir, exist_ok=True)
    adds = []
    adds.append(os.path.join(SCEN, "tls.add.xml"))
    if e1:
        # per-run copy of the additional file so E1 output lands in THIS run's dir
        # (edgeData/E1 `file` resolves relative to the additional file's own dir)
        dst = os.path.join(outdir, "e1.add.xml")
        shutil.copy(os.path.join(SCEN, "e1.add.xml"), dst)
        adds.append(dst)
    if edgedata:
        dst = os.path.join(outdir, "edgedata.add.xml")
        shutil.copy(os.path.join(SCEN, "edgedata.add.xml"), dst)
        adds.append(dst)
    cmd = [
        "sumo",
        "-n", os.path.join(SCEN, "arterial.net.xml"),
        "-r", os.path.join(SCEN, "demand.rou.xml"),
        "-a", ",".join(adds),
        "--begin", "0", "--end", str(SIM_END),
        "--step-length", "1",
        "--seed", str(seed),
        "--time-to-teleport", str(ttt),
        "--tripinfo-output", os.path.join(outdir, "tripinfo.xml"),
        "--tripinfo-output.write-unfinished",
        "--summary-output", os.path.join(outdir, "summary.xml"),
        "--no-step-log", "true",
        "--duration-log.statistics", "true",
        "--xml-validation", "never",
    ]
    if fcd:
        cmd += ["--fcd-output", os.path.join(outdir, fcd),
                "--fcd-output.attributes", "id,speed,pos,lane",
                "--fcd-output.skip-empty"]
        if fcd_prob is not None:
            cmd += ["--device.fcd.probability", str(fcd_prob)]
        if fcd_period is not None:
            cmd += ["--device.fcd.period", str(fcd_period)]
    return cmd


def run(name, **kw):
    outdir = os.path.join(RUNS, name)
    cmd = build_cmd(outdir, **kw)
    with open(os.path.join(outdir, "cmd.txt"), "w") as f:
        f.write(" ".join(cmd) + "\n")
    r = subprocess.run(cmd, capture_output=True, text=True)
    open(os.path.join(outdir, "sumo_stdout.txt"), "w").write(r.stdout)
    open(os.path.join(outdir, "sumo_stderr.txt"), "w").write(r.stderr)
    status = "OK" if r.returncode == 0 else f"FAIL({r.returncode})"
    ntel = r.stderr.count("teleporting")
    print(f"[{status}] {name}   stderr_warnings={len(r.stderr.splitlines())} teleport_msgs={ntel}")
    if r.returncode != 0:
        print(r.stderr[-3000:])
    return r.returncode == 0


def sha(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


PROBE_ARMS = []
for pct in [0.5, 1, 2, 5, 10, 20, 50, 100]:
    for per in [1, 10, 30, 60]:
        PROBE_ARMS.append((pct, per))


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("pilot",):
        run("pilot", fcd=None, e1=True, edgedata=True)
    if what in ("master", "all"):
        run("master", fcd="fcd.xml.gz", fcd_prob=1.0, fcd_period=1)
    if what in ("arms", "all"):
        for pct, per in PROBE_ARMS:
            nm = f"p{pct}_T{per}"
            run(nm, fcd="fcd.xml.gz", fcd_prob=pct / 100.0, fcd_period=per,
                e1=False, edgedata=False)
    if what in ("teleport", "all"):
        for ttt in [-1, 120, 300, 600]:
            run(f"ttt{ttt}", fcd=None, ttt=ttt, e1=False, edgedata=False)


if __name__ == "__main__":
    main()
