#!/usr/bin/env python3
"""
Drive the full factorial sweep:
    2 variants (A no facility / B loading bay)
  x 6 background volumes (600 .. 2400 veh/h)
  x 4 delivery cells (D0 control, D10, D30, D6L)
  x 20 simulation seeds
  = 960 SUMO runs.

Replication protocol (from `quantify-sumo-run-to-run-variability`):
  * 20 replications per cell, everywhere - the near/over-capacity cells are
    exactly the regime that skill flags as UNSAFE for single-seed comparison.
  * COMMON RANDOM NUMBERS: the identical seed list 1..20 is used in variant A
    and variant B, so the A-vs-B contrast is a paired design. The seed drives
    BOTH the flow's departure realisation and driver behaviour here, so the
    pairing is as tight as it can be made.
  * Warm-up: the first 600 s of departures are discarded (justified separately
    by warmup_check.py rather than assumed).

Bulk raw traces stay in the attempt work dir; only per-run metrics.json and the
compacted CSV are promoted to outputs/.

Usage:
    python3 run_sweep.py --net-dir NET --work-dir WORK --out CSV [--jobs 8]
"""
import argparse
import csv
import json
import os
import shutil
import sys
import traceback
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scenario as SC          # noqa: E402
import run_cell as RC          # noqa: E402

# raw traces that are big and safe to delete after the metrics are extracted
PURGE = ["lanechange.xml", "fcd.xml", "tripinfo.xml", "summary.xml",
         "lanedata_car.xml", "lanedata_van.xml", "edgedata.xml", "e2.xml"]

# one cell whose full raw output set is kept and promoted as the raw sample
ARCHIVE = {("A", 1800, "D30", 1), ("B", 1800, "D30", 1),
           ("A", 1800, "D0", 1), ("B", 1800, "D0", 1)}


def one(job):
    net_dir, work_dir, variant, volume, cell, seed = job
    tag = f"{variant}_{volume}_{cell}_s{seed}"
    rd = os.path.join(work_dir, "runs", tag)
    try:
        m = RC.run(net_dir, rd, variant, volume, cell, seed, fcd=False)
        if (variant, volume, cell, seed) not in ARCHIVE:
            for f in PURGE:
                p = os.path.join(rd, f)
                if os.path.exists(p):
                    os.remove(p)
        return m
    except Exception:
        return {"variant": variant, "volume": volume, "cell": cell,
                "seed": seed, "ERROR": traceback.format_exc()[-1500:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--net-dir", required=True)
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--jobs", type=int, default=8)
    a = ap.parse_args()
    net_dir = os.path.abspath(a.net_dir)
    work_dir = os.path.abspath(a.work_dir)
    os.makedirs(os.path.join(work_dir, "runs"), exist_ok=True)

    jobs = [(net_dir, work_dir, v, vol, c, s)
            for v in SC.VARIANTS
            for vol in SC.VOLUMES
            for c in SC.DELIVERY_CELLS
            for s in SC.SEEDS]
    print(f"{len(jobs)} runs on {a.jobs} workers", flush=True)

    rows, errs = [], []
    with Pool(a.jobs) as pool:
        for i, m in enumerate(pool.imap_unordered(one, jobs, chunksize=4), 1):
            if "ERROR" in m:
                errs.append(m)
            else:
                rows.append(m)
            if i % 50 == 0:
                print(f"  {i}/{len(jobs)} done ({len(errs)} errors)", flush=True)

    cols = ["variant", "volume", "cell", "stops_per_hour", "dwell_s", "seed",
            "car_n", "car_mean_duration_s", "car_mean_timeloss_s",
            "car_mean_departdelay_s", "car_mean_waiting_s", "car_mean_delay_s",
            "car_total_timeloss_vehh", "car_total_delay_vehh",
            "van_n", "van_mean_duration_s", "throughput_vph",
            "queue_mean_veh", "queue_max_veh", "lc_car_total",
            "lc_car_curbzone", "lc_car_forced_merge",
            "curb_block_s", "curb_block_vehh", "n_stops_in_window",
            "teleports", "collisions", "unfinished_trips",
            "car_lane_secs_right", "car_lane_secs_left",
            "van_lane_secs_bayORright"]
    for m in rows:
        cl = m.get("car_lane_seconds_ECURB", {})
        vl = m.get("van_lane_seconds_ECURB", {})
        if m["variant"] == "A":
            right, left, bay = "ECURB_0", "ECURB_1", "ECURB_0"
        else:
            right, left, bay = "ECURB_1", "ECURB_2", "ECURB_0"
        m["car_lane_secs_right"] = cl.get(right, 0.0)
        m["car_lane_secs_left"] = cl.get(left, 0.0)
        m["van_lane_secs_bayORright"] = vl.get(bay, 0.0)

    rows.sort(key=lambda r: (r["variant"], r["volume"], r["cell"], r["seed"]))
    with open(a.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows -> {a.out}")
    if errs:
        with open(a.out + ".errors.json", "w") as fh:
            json.dump(errs, fh, indent=1)
        print(f"!! {len(errs)} FAILED runs -> {a.out}.errors.json")


if __name__ == "__main__":
    main()
