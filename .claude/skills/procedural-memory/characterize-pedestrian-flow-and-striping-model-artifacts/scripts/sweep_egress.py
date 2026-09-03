#!/usr/bin/env python3
"""Parallel driver for the egress application (widen-vs-retime grid), H5 (model
choice) and the vehicle-side reverse-coupling baseline.

The retiming arm is ZERO-SUM at a fixed 90 s cycle: every second of extra
pedestrian green is taken away from the crossed street's vehicle green, so the
"re-time the signal" option is priced honestly instead of being free green time.
"""
import argparse
import json
import os
import sys
import traceback
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_egress  # noqa: E402

CYCLE = 90
YEL, ALLRED = 4, 2
WIDTHS = [2.0, 3.0, 4.0, 6.0]
GREENS = [10, 20, 30, 40]
SEEDS = (1, 2, 3)
N_PED = 1500


def veh_green_for(pg):
    return CYCLE - YEL - ALLRED - pg


def _job(spec):
    name, kw = spec
    try:
        return name, run_egress.run(**kw), None
    except Exception:
        return name, None, traceback.format_exc()


def build_jobs(exp, root):
    jobs = []
    if exp == "app_grid":
        for w in WIDTHS:
            for pg in GREENS:
                for s in SEEDS:
                    n = "app_w%g_g%d_s%d" % (w, pg, s)
                    jobs.append((n, dict(outdir=os.path.join(root, n), w_bottleneck=w,
                                         ped_green=pg, veh_green=veh_green_for(pg),
                                         n_ped=N_PED, seed=s, traj=(s == 1))))
    elif exp == "h5_model":
        for w, pg in [(3.0, 20), (2.0, 20), (6.0, 40)]:
            for model in ["striping", "nonInteracting", "jupedsim"]:
                for s in SEEDS:
                    n = "h5_%s_w%g_g%d_s%d" % (model, w, pg, s)
                    jobs.append((n, dict(outdir=os.path.join(root, n), w_bottleneck=w,
                                         ped_green=pg, veh_green=veh_green_for(pg),
                                         n_ped=N_PED, seed=s, model=model)))
    elif exp == "h5_reduced":
        # jupedsim is ~50x slower than striping, so the 3-way model comparison runs at a
        # reduced but IDENTICAL scale in all three arms rather than being dropped.
        for model in ["striping", "nonInteracting", "jupedsim"]:
            for s in SEEDS:
                n = "h5r_%s_s%d" % (model, s)
                jobs.append((n, dict(outdir=os.path.join(root, n), w_bottleneck=3.0,
                                     ped_green=20, veh_green=veh_green_for(20),
                                     n_ped=400, release_end=150.0, end=2400.0,
                                     seed=s, model=model)))
    elif exp == "h5_striping_vs_noninteracting":
        for w, pg in [(3.0, 20), (2.0, 20), (6.0, 40)]:
            for model in ["striping", "nonInteracting"]:
                for s in SEEDS:
                    n = "h5_%s_w%g_g%d_s%d" % (model, w, pg, s)
                    jobs.append((n, dict(outdir=os.path.join(root, n), w_bottleneck=w,
                                         ped_green=pg, veh_green=veh_green_for(pg),
                                         n_ped=N_PED, seed=s, model=model)))
    elif exp == "h4_jamtime_crossing":
        # jamtime.crossing only bites where there IS a crossing -> the egress scenario
        for jtc in [-1, 5, 10, 30, 100]:
            for s in SEEDS:
                n = "h4c_jtc%g_s%d" % (jtc, s)
                jobs.append((n, dict(outdir=os.path.join(root, n), w_bottleneck=2.0,
                                     ped_green=20, veh_green=veh_green_for(20),
                                     n_ped=N_PED, seed=s,
                                     extra=["--pedestrian.striping.jamtime.crossing", str(jtc)])))
    elif exp == "veh_baseline":
        # vehicle performance with NO pedestrian surge -> the reverse-coupling datum
        for pg in GREENS:
            for s in SEEDS:
                n = "vb_g%d_s%d" % (pg, s)
                jobs.append((n, dict(outdir=os.path.join(root, n), w_bottleneck=3.0,
                                     ped_green=pg, veh_green=veh_green_for(pg),
                                     n_ped=1, seed=s)))
    else:
        raise SystemExit("unknown %s" % exp)
    return jobs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", required=True)
    ap.add_argument("--root", required=True)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--procs", type=int, default=7)
    a = ap.parse_args()
    os.makedirs(a.root, exist_ok=True)
    jobs = build_jobs(a.exp, a.root)
    print("%s: %d runs" % (a.exp, len(jobs)), flush=True)
    res, errs = {}, {}
    with Pool(a.procs) as p:
        for i, (name, r, err) in enumerate(p.imap_unordered(_job, jobs)):
            if err:
                errs[name] = err
                print("  [%d/%d] FAIL %s\n%s" % (i + 1, len(jobs), name, err[-600:]), flush=True)
            else:
                res[name] = r
                c = r["clearance"]
                print("  [%d/%d] %-26s p95=%.0f p100=%.0f meanDur=%.0f v_tl=%.1f done=%d/%d"
                      % (i + 1, len(jobs), name, c.get("clearance_p95", -1),
                         c.get("clearance_p100", -1), c.get("mean_egress_duration_s", -1),
                         r["vehicles"].get("mean_veh_timeloss_s", -1),
                         r["accounting"]["completed"], r["accounting"]["n_ped_demanded"]),
                      flush=True)
    json.dump({"experiment": a.exp, "results": res, "errors": errs},
              open(a.out_json, "w"), indent=1)
    print("wrote %s (%d ok, %d fail)" % (a.out_json, len(res), len(errs)))


if __name__ == "__main__":
    main()
