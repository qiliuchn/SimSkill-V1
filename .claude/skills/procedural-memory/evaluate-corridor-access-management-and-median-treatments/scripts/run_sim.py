#!/usr/bin/env python3
"""One experiment cell = (variant, density, seed[, consolidate]).
Builds/reuses net + demand, routes per-variant, runs sumo with tripinfo +
summary + SSM output. CRN: trips.xml is identical across variants for a
given (density, seed, consolidate) -- only variant-specific routing and
network differ."""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gen_demand as dm  # noqa: E402

NETS = os.path.join(HERE, "nets")
DEMAND = os.path.join(HERE, "demand")
RUNS = os.path.join(HERE, "runs")


def net_dir(variant, density, consolidate=1):
    suffix = f"_consolidate{consolidate}" if consolidate > 1 else ""
    return os.path.join(NETS, f"{variant}_d{int(density)}{suffix}")


def ensure_demand(density, seed, consolidate=1):
    # canonical trips built from the UNDIVIDED net's meta (driveway
    # positions are variant-independent for a given density/consolidate)
    meta = os.path.join(net_dir("undivided", density, consolidate), "meta.json")
    d = os.path.join(DEMAND, f"d{int(density)}_c{consolidate}_s{seed}")
    os.makedirs(d, exist_ok=True)
    trips = os.path.join(d, "trips.xml")
    if not os.path.exists(trips):
        dm.gen_trips(meta, seed, trips)
    return trips, d


def ensure_route(variant, density, seed, consolidate=1):
    trips, d = ensure_demand(density, seed, consolidate)
    net = os.path.join(net_dir(variant, density, consolidate), "net.net.xml")
    rou = os.path.join(d, f"rou_{variant}.xml")
    log = os.path.join(d, f"duarouter_{variant}.log")
    if not os.path.exists(rou):
        rc, out = dm.route(net, trips, rou, log)
        if rc != 0 or not os.path.exists(rou):
            raise SystemExit(f"duarouter FAILED {variant} d{density} s{seed}: {out[-2000:]}")
    return net, rou


def run(variant, density, seed, consolidate=1, sim_end=None):
    net, rou = ensure_route(variant, density, seed, consolidate)
    nd = net_dir(variant, density, consolidate)
    sig = os.path.join(nd, "signals.add.xml")
    suffix = f"_c{consolidate}" if consolidate > 1 else ""
    outdir = os.path.join(RUNS, f"{variant}_d{int(density)}{suffix}_s{seed}")
    os.makedirs(outdir, exist_ok=True)
    tripinfo = os.path.join(outdir, "tripinfo.xml")
    summary = os.path.join(outdir, "summary.xml")
    ssm = os.path.join(outdir, "ssm.xml")
    statistics = os.path.join(outdir, "statistics.xml")
    end = sim_end or dm.SIM_END
    args = ["sumo", "-n", net, "-r", rou, "-a", sig,
            "--tripinfo-output", tripinfo,
            "--summary-output", summary,
            "--device.ssm.file", ssm,
            "--statistic-output", statistics,
            "--duration-log.statistics", "true",
            "--no-step-log", "true",
            "--no-warnings", "true",
            "--time-to-teleport", "300",
            "--collision.action", "warn",
            "--seed", str(seed),
            "--end", str(end)]
    r = subprocess.run(args, capture_output=True, text=True, cwd=outdir)
    with open(os.path.join(outdir, "sumo.log"), "w") as f:
        f.write(" ".join(args) + "\n\n" + r.stdout + "\n" + r.stderr)
    ok = os.path.exists(tripinfo)
    return ok, outdir, r.stdout + r.stderr


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("variant")
    ap.add_argument("density", type=float)
    ap.add_argument("seed", type=int)
    ap.add_argument("--consolidate", type=int, default=1)
    a = ap.parse_args()
    ok, outdir, log = run(a.variant, a.density, a.seed, a.consolidate)
    print(f"variant={a.variant} density={a.density} seed={a.seed} consolidate={a.consolidate} ok={ok} -> {outdir}")
    if not ok:
        print(log[-3000:])
