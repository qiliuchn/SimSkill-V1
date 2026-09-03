#!/usr/bin/env python3
"""Collect analyze.py metrics for every run whose directory name starts with a prefix."""
import argparse
import csv
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from analyze import analyze  # noqa: E402


def fleet_for(rundir):
    meta = {r["key"]: r["value"] for r in csv.DictReader(open(os.path.join(rundir, "run_meta.csv")))}
    return meta["routes"].replace(".rou.xml", ".fleet.csv")


def one(rundir):
    try:
        return analyze(rundir, fleet_for(rundir))
    except Exception as e:                                  # noqa: BLE001
        return {"run": os.path.basename(rundir), "error": repr(e)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--nproc", type=int, default=8)
    a = ap.parse_args()
    runsdir = os.path.join(ROOT, "runs")
    dirs = sorted(os.path.join(runsdir, d) for d in os.listdir(runsdir)
                  if d.startswith(a.prefix) and os.path.isdir(os.path.join(runsdir, d)))
    with ProcessPoolExecutor(a.nproc) as ex:
        rows = list(ex.map(one, dirs))
    errs = [r for r in rows if "error" in r]
    for e in errs[:5]:
        print("ERR", e)
    rows = [r for r in rows if "error" not in r]
    keys = sorted({k for r in rows for k in r})
    out = os.path.join(ROOT, "analysis", f"metrics_{a.tag}.csv")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
                        for k, v in r.items()})
    print(f"{len(rows)} runs -> {out}  ({len(errs)} errors)")


if __name__ == "__main__":
    main()
