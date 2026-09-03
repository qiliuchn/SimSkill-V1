#!/usr/bin/env python3
"""Parallel batch driver for every corridor experiment (H1-H4).

Replication uses COMMON RANDOM NUMBERS: the same seed list {1..n} is reused across
every configuration of a sweep, so seed s always drives the same underlying random
stream in every arm.  Per the retrieved `sumo-stochastic-variability-and-replication-design`
guidance, CRN's benefit is checked per metric rather than assumed, and these sweeps
deliberately run straight through the capacity knee where the outcome distribution
can be bimodal -- so CI half-widths are reported per point, not assumed uniform.
"""
import argparse
import json
import os
import sys
import traceback
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_corridor  # noqa: E402

BASE = dict(end=1500.0, demand_end=1200.0, warmup=500.0, meas_end=1200.0,
            x1=60.0, x2=140.0, step=1.0)


def _job(spec):
    name, kw = spec
    try:
        m = run_corridor.run(**kw)
        return name, m, None
    except Exception:
        return name, None, traceback.format_exc()


def build_jobs(exp, root):
    jobs = []
    if exp == "h1_uniform":
        for rate in [0.1, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 3.5, 4.5, 6.0]:
            for seed in (1, 2, 3):
                n = "h1u_r%g_s%d" % (rate, seed)
                jobs.append((n, dict(outdir=os.path.join(root, n), w_mid=2.24,
                                     rate=rate, seed=seed, **BASE)))
    elif exp == "h1_gated":
        for gate in [0.32, 0.4, 0.5, 0.64, 0.8, 0.9, 1.12, 1.28, 1.6, 1.92]:
            for seed in (1, 2, 3):
                n = "h1g_w%g_s%d" % (gate, seed)
                jobs.append((n, dict(outdir=os.path.join(root, n), w_mid=2.24,
                                     rate=3.0, seed=seed, w_exit=gate, **BASE)))
    elif exp == "h1_gated_speed":
        # A narrow gate meters flow only in stripe-quantized jumps, so the congested
        # branch it produces has only a handful of attainable states.  Slowing the exit
        # edge instead (same stripe count as the measurement section) meters throughput
        # CONTINUOUSLY and fills in the branch.  Verified: pedestrians do honour the
        # sidewalk lane's speed limit.
        for sp in [1.30, 1.10, 0.95, 0.80, 0.70, 0.60, 0.50, 0.40, 0.30, 0.22]:
            for seed in (1, 2, 3):
                n = "h1gs_v%g_s%d" % (sp, seed)
                jobs.append((n, dict(outdir=os.path.join(root, n), w_mid=2.24, rate=3.0,
                                     seed=seed, w_exit=2.24, speed_exit=sp, **BASE)))
    elif exp in ("h2_default", "h2_sw040", "h2_sw080"):
        stripe = {"h2_default": None, "h2_sw040": 0.40, "h2_sw080": 0.80}[exp]
        seeds = (1, 2, 3) if stripe is None else (1, 2)
        widths = [round(0.64 + 0.16 * i, 2) for i in range(17)]   # 0.64 .. 3.20
        for w in widths:
            rate = round(max(1.0, 1.6 * w), 3)
            for seed in seeds:
                n = "%s_w%g_s%d" % (exp, w, seed)
                jobs.append((n, dict(outdir=os.path.join(root, n), w_mid=w, rate=rate,
                                     seed=seed, stripe_width=stripe, **BASE)))
    elif exp == "h2_plateau":
        # rate-insensitivity check: is the measured capacity on a plateau?
        for w in [1.28, 1.92, 2.56, 3.2]:
            for mult in [1.3, 1.6, 2.0, 2.6]:
                for seed in (1, 2):
                    n = "h2p_w%g_m%g_s%d" % (w, mult, seed)
                    jobs.append((n, dict(outdir=os.path.join(root, n), w_mid=w,
                                         rate=round(max(1.0, mult * w), 3),
                                         seed=seed, **BASE)))
    elif exp == "h3_counterflow":
        for frac in [1.0, 0.9, 0.75, 0.5]:
            for seed in (1, 2, 3, 4, 5):
                n = "h3_f%g_s%d" % (frac, seed)
                jobs.append((n, dict(outdir=os.path.join(root, n), w_mid=2.24, rate=3.0,
                                     seed=seed, frac_fwd=frac, lateral=True, **BASE)))
    elif exp == "h3_lowdens":
        # free-flow control: lane formation should be weak when nobody has to yield
        for frac in [1.0, 0.5]:
            for seed in (1, 2, 3, 4, 5):
                n = "h3lo_f%g_s%d" % (frac, seed)
                jobs.append((n, dict(outdir=os.path.join(root, n), w_mid=2.24, rate=0.5,
                                     seed=seed, frac_fwd=frac, lateral=True, **BASE)))
    elif exp == "h4_jamtime":
        # NOTE: SUMO 1.27.1's DEFAULT --pedestrian.striping.jamtime is 300 s (verified
        # from `sumo --save-template`), NOT 10 s.  jamtime.crossing defaults to 10 s and
        # jamtime.narrow to 1 s.  Every other sweep in this study left jamtime at its
        # default, so 300 is the reference arm here.
        for rate in [3.0, 6.0]:
            for jt in [-1, 10, 30, 100, 300, 1000]:
                for seed in (1, 2, 3):
                    n = "h4_r%g_jt%g_s%d" % (rate, jt, seed)
                    jobs.append((n, dict(outdir=os.path.join(root, n), w_mid=2.24,
                                         rate=rate, seed=seed, jamtime=jt, **BASE)))
    elif exp == "h3_reserve":
        # mechanism test for the counterflow collapse: --pedestrian.striping.reserve-oncoming
        # defaults to 0 on ordinary lanes (0.34 only on junctions/crossings), so nothing
        # holds stripes open for the minority direction.
        for frac in [0.75, 0.5]:
            for ro in [0.0, 0.2, 0.34, 0.5]:
                for seed in (1, 2, 3):
                    n = "h3r_f%g_ro%g_s%d" % (frac, ro, seed)
                    jobs.append((n, dict(outdir=os.path.join(root, n), w_mid=2.24, rate=3.0,
                                         seed=seed, frac_fwd=frac, lateral=True,
                                         extra_args=["--pedestrian.striping.reserve-oncoming",
                                                     str(ro)], **BASE)))
    else:
        raise SystemExit("unknown experiment %s" % exp)
    return jobs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", required=True)
    ap.add_argument("--root", required=True)
    ap.add_argument("--procs", type=int, default=7)
    ap.add_argument("--out-json", required=True)
    a = ap.parse_args()
    os.makedirs(a.root, exist_ok=True)
    jobs = build_jobs(a.exp, a.root)
    print("%s: %d runs" % (a.exp, len(jobs)), flush=True)
    res, errs = {}, {}
    with Pool(a.procs) as p:
        for i, (name, m, err) in enumerate(p.imap_unordered(_job, jobs)):
            if err:
                errs[name] = err
                print("  [%d/%d] FAIL %s" % (i + 1, len(jobs), name), flush=True)
            else:
                res[name] = m
                print("  [%d/%d] %-24s q=%.3f q/m=%.3f k=%.3f v=%.3f jamE/1ks=%.2f"
                      % (i + 1, len(jobs), name, m["flow_p_s"], m["flow_p_s_per_m"],
                         m["density_p_m2"], m["speed_ms"],
                         m["person_summary"]["jam_events_per_1000_person_seconds"]), flush=True)
    json.dump({"experiment": a.exp, "results": res, "errors": errs},
              open(a.out_json, "w"), indent=1)
    print("wrote %s  (%d ok, %d failed)" % (a.out_json, len(res), len(errs)))


if __name__ == "__main__":
    main()
