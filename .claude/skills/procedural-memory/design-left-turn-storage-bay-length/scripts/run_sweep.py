#!/usr/bin/env python3
"""
Drive the full bay-length sweep:

    bay length L  x  left-turn share  x  signal condition  x  replication seed

Each cell is a separate `run_cell.py` process (so every replication gets its
own output directory -- per `quantify-sumo-run-to-run-variability`, sharing an
output path across parallel replications silently overwrites results).

Writes one row per (cell, seed) to raw_cells.csv.
"""
import argparse
import csv
import itertools
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gen_network            # noqa: E402
import gen_programs           # noqa: E402
import gen_demand            # noqa: E402

BAYS = [10, 20, 30, 50, 75, 100, 150, "full"]
SHARES = [0.10, 0.25, 0.40]
SIGS = ["split08", "split16", "split24", "actuated"]


def prepare(work):
    nets, tls, rous = {}, {}, {}
    for b in BAYS:
        nets[b] = gen_network.build(str(b) if b != "full" else "full",
                                    os.path.join(work, "nets"))
        w, _, _ = gen_programs.build_programs(nets[b], os.path.join(work, "tls", str(b)))
        tls[b] = w
    for s in SHARES:
        for full in (False, True):
            p = os.path.join(work, f"rou_s{int(s*100)}{'_full' if full else ''}.rou.xml")
            gen_demand.write(p, s, full)
            rous[(s, full)] = p
    return nets, tls, rous


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--ttt", type=int, default=300)
    a = ap.parse_args()

    os.makedirs(a.work, exist_ok=True)
    nets, tls, rous = prepare(a.work)
    print(f"prepared {len(nets)} networks, {len(rous)} demand files")

    cells = list(itertools.product(BAYS, SHARES, SIGS, range(1, a.seeds + 1)))
    print(f"{len(cells)} runs")

    def one(args):
        b, s, sig, seed = args
        tag = f"bay{b}_s{int(s*100)}_{sig}_seed{seed}"
        od = os.path.join(a.work, "runs", tag)
        cmd = [sys.executable, os.path.join(HERE, "run_cell.py"),
               "--net", nets[b], "--rou", rous[(s, b == "full")],
               "--tls", tls[b][sig], "--program", sig,
               "--outdir", od, "--seed", str(seed), "--ttt", str(a.ttt),
               "--label", tag]
        if seed != 1:
            cmd.append("--no-keep-raw")
        r = subprocess.run(cmd, capture_output=True, text=True)
        f = os.path.join(od, "events.json")
        if not os.path.exists(f):
            return dict(bay=b, share=s, sig=sig, seed=seed, ok=0,
                        err=(r.stderr or "")[-400:])
        d = json.load(open(f))
        if seed != 1:
            try:
                os.remove(os.path.join(od, "lane_usage_trace.csv"))
            except OSError:
                pass
        for _k in ("bay_q_samples", "left_q_m_samples", "left_q_n_samples", "bayonly_q_m_samples", "bayonly_q_left_samples", "thru_q_m_samples"):
            d.pop(_k, None)
        d.pop("viol_examples", None)
        d.update(bay=b, share=s, sig=sig, seed=seed, ok=1, err="")
        return d

    rows = []
    with ThreadPoolExecutor(max_workers=a.jobs) as ex:
        for i, r in enumerate(ex.map(one, cells)):
            rows.append(r)
            if (i + 1) % 20 == 0:
                print(f"  {i+1}/{len(cells)}", flush=True)

    bad = [r for r in rows if not r["ok"]]
    if bad:
        print(f"WARNING: {len(bad)} failed runs; first error:\n{bad[0].get('err')}")
    allk = {k for r in rows for k in r}
    keys = ["bay", "share", "sig", "seed", "ok"] + \
           sorted(k for k in allk if k not in ("bay", "share", "sig", "seed", "ok", "err"))
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print("wrote", a.out, len(rows), "rows")


if __name__ == "__main__":
    main()
