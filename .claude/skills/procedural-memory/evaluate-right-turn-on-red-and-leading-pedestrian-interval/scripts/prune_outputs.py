#!/usr/bin/env python3
"""Prune the raw per-run outputs to a size that can live in the repository.

The 120 main runs plus 18 supplementary runs produce ~1 GB of XML. Kept:

  * every `*_traci.json` (the primary instrument record), gzipped
  * seed 1 of every cell/regime COMPLETE (gzipped) - full raw traceability for
    spot-checking any headline number end to end
  * `*_summary.xml` and `*_collisions.xml` for every run (small; the teleport /
    collision health evidence)
  * everything under net/, programs/, demand/, freeflow/, calibration/, sprobe/

Deleted for seeds 2..10: `*_instant.xml`, `*_instantvia.xml`, `*_ssm.xml`,
`*_tripinfo.xml`, `*_e1.xml`.

Every per-run DERIVED number for all seeds survives in
`outputs/per_run_metrics.json`, and every per-cell aggregate in
`outputs/per_cell_metrics.json`; both are written by `analyze.py` before this
script runs.  Re-running `analyze.py` after pruning would only reproduce the
seed-1 rows, so run it first.
"""
import glob
import gzip
import os
import shutil
import sys

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
OUT = os.path.join(BASE, "outputs")
BULK = ("_instant.xml", "_instantvia.xml", "_ssm.xml", "_tripinfo.xml", "_e1.xml")


def gz(p):
    with open(p, "rb") as f, gzip.open(p + ".gz", "wb", compresslevel=6) as g:
        shutil.copyfileobj(f, g)
    os.remove(p)


def keep_seed(name):
    return name.endswith("__s1") or name.endswith("__s101")


def main():
    freed = kept = 0
    for root in (os.path.join(OUT, "runs"), os.path.join(OUT, "runs_encroach")):
        for d, _, fs in os.walk(root):
            for f in fs:
                p = os.path.join(d, f)
                if f.endswith(".gz"):
                    continue
                tag = f.rsplit("_", 1)[0] if "_" in f else f
                for suf in BULK:
                    if f.endswith(suf):
                        tag = f[: -len(suf)]
                        break
                if any(f.endswith(s) for s in BULK):
                    if keep_seed(tag):
                        gz(p); kept += 1
                    else:
                        freed += os.path.getsize(p); os.remove(p)
                elif f.endswith("_traci.json"):
                    gz(p); kept += 1
                elif f.endswith(".add.xml"):
                    os.remove(p)
    print(f"gzipped/kept {kept} files, deleted {freed/1e6:.0f} MB of bulk XML")
    os.system(f"du -sh {OUT}")


if __name__ == "__main__":
    main()
