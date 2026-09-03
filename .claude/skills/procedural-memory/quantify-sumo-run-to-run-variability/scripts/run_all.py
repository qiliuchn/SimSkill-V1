#!/usr/bin/env python3
"""Full experiment plan for the SUMO run-to-run variability study.

Three loading levels x four replication families, plus a CRN-vs-independent
treatment experiment. Every seed used is written to seeds.json so the whole
study is reproducible.

Loading levels (calibrated by probe_capacity.py + vc_from_routes.py against a
MEASURED interior-link capacity of 512.4 veh/h/edge):
    L050  insertion 2400 veh/h  -> demand v/c(p90 link) ~= 0.50
    L090  insertion 4250 veh/h  -> demand v/c(p90 link) ~= 0.89
    L110  insertion 5200 veh/h  -> demand v/c(p90 link) ~= 1.09

Replication families (variance-source decomposition):
    SIM    fixed route file, sumo --seed varies      -> simulation randomness
    DEM    randomTrips --seed varies, sumo seed fixed-> demand randomness
    BOTH   both vary  (this is the honest replication design)
    NODRV  fixed route file, sumo --seed varies, but sigma=0 and speedDev=0
           -> isolates how much of SIM's variance is driver-behaviour
              dispersion vs. everything else in the sumo RNG stream

Treatment experiment (at L050 and L090):
    BASE_A  baseline signal plan,        seed list A
    TRT_A   cycle length x0.8,           seed list A   (CRN / paired)
    TRT_B   cycle length x0.8,           seed list B   (independent)
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_replications as R  # noqa: E402
from gen_demand import gen    # noqa: E402

WORK = os.path.join(os.path.dirname(HERE), "attempts", "attempt-1", "work",
                    "study")

LEVELS = {"L050": 2400, "L090": 4250, "L110": 5200}

N_FAMILY = 30      # replications per variance-decomposition family
N_MAIN = 40        # replications for the main per-level replication study
N_TRT = 40         # replications per treatment arm

FIXED_DEMAND_SEED = 1000                       # for the fixed-route families
SIM_SEEDS = list(range(1, 1 + N_FAMILY))       # SIM / NODRV sumo seeds
DEM_SEEDS = list(range(2000, 2000 + N_FAMILY))  # DEM demand seeds
DEM_FIXED_SUMO_SEED = 42
BOTH_SEEDS = list(range(3000, 3000 + N_MAIN))  # BOTH: used for BOTH demand+sumo
TRT_SEEDS_A = list(range(5000, 5000 + N_TRT))
TRT_SEEDS_B = list(range(6000, 6000 + N_TRT))
CYCLE_SCALE = 0.8


def build_jobs():
    jobs = []
    fixed_routes = {}
    for lvl, rate in LEVELS.items():
        rd = os.path.join(WORK, lvl, "_fixed_demand")
        os.makedirs(rd, exist_ok=True)
        fixed_routes[lvl] = gen(rate, FIXED_DEMAND_SEED, rd, "fixed_" + lvl)

    for lvl, rate in LEVELS.items():
        base = dict(rate=rate, level=lvl)
        # --- SIM: fixed routes, varying sumo seed -------------------------
        for s in SIM_SEEDS:
            jobs.append(dict(base, family="SIM", id="%s_SIM_%04d" % (lvl, s),
                             out_dir=os.path.join(WORK, lvl, "SIM", "s%04d" % s),
                             route_file=fixed_routes[lvl],
                             demand_seed=FIXED_DEMAND_SEED, sumo_seed=s,
                             stochastic_driver=True))
        # --- NODRV: same, but driver dispersion switched off --------------
        for s in SIM_SEEDS:
            jobs.append(dict(base, family="NODRV",
                             id="%s_NODRV_%04d" % (lvl, s),
                             out_dir=os.path.join(WORK, lvl, "NODRV", "s%04d" % s),
                             route_file=fixed_routes[lvl],
                             demand_seed=FIXED_DEMAND_SEED, sumo_seed=s,
                             stochastic_driver=False))
        # --- DEM: varying demand seed, fixed sumo seed --------------------
        for s in DEM_SEEDS:
            jobs.append(dict(base, family="DEM", id="%s_DEM_%04d" % (lvl, s),
                             out_dir=os.path.join(WORK, lvl, "DEM", "s%04d" % s),
                             demand_seed=s, sumo_seed=DEM_FIXED_SUMO_SEED,
                             stochastic_driver=True))
        # --- BOTH: the main replication study -----------------------------
        for i, s in enumerate(BOTH_SEEDS):
            jobs.append(dict(base, family="BOTH", id="%s_BOTH_%04d" % (lvl, s),
                             out_dir=os.path.join(WORK, lvl, "BOTH", "s%04d" % s),
                             demand_seed=s, sumo_seed=s,
                             stochastic_driver=True,
                             keep_raw=(i == 0)))  # keep one full raw output set

    # --- treatment experiment --------------------------------------------
    for lvl in ("L050", "L090"):
        rate = LEVELS[lvl]
        for s in TRT_SEEDS_A:
            jobs.append(dict(rate=rate, level=lvl, family="TRT", arm="BASE_A",
                             id="%s_BASE_A_%04d" % (lvl, s),
                             out_dir=os.path.join(WORK, lvl, "TRT_BASE_A",
                                                  "s%04d" % s),
                             demand_seed=s, sumo_seed=s,
                             stochastic_driver=True))
            jobs.append(dict(rate=rate, level=lvl, family="TRT", arm="TRT_A",
                             id="%s_TRT_A_%04d" % (lvl, s),
                             out_dir=os.path.join(WORK, lvl, "TRT_TRT_A",
                                                  "s%04d" % s),
                             demand_seed=s, sumo_seed=s,
                             cycle_scale=CYCLE_SCALE,
                             stochastic_driver=True))
        for s in TRT_SEEDS_B:
            jobs.append(dict(rate=rate, level=lvl, family="TRT", arm="TRT_B",
                             id="%s_TRT_B_%04d" % (lvl, s),
                             out_dir=os.path.join(WORK, lvl, "TRT_TRT_B",
                                                  "s%04d" % s),
                             demand_seed=s, sumo_seed=s,
                             cycle_scale=CYCLE_SCALE,
                             stochastic_driver=True))
    return jobs


if __name__ == "__main__":
    os.makedirs(WORK, exist_ok=True)
    jobs = build_jobs()
    print("planned replications: %d" % len(jobs))
    with open(os.path.join(HERE, "seeds.json"), "w") as fh:
        json.dump({"levels": LEVELS,
                   "capacity_vph": R.CAPACITY_VPH,
                   "cycle_scale_treatment": CYCLE_SCALE,
                   "fixed_demand_seed": FIXED_DEMAND_SEED,
                   "sim_seeds": SIM_SEEDS,
                   "dem_seeds": DEM_SEEDS,
                   "dem_fixed_sumo_seed": DEM_FIXED_SUMO_SEED,
                   "both_seeds": BOTH_SEEDS,
                   "trt_seeds_A": TRT_SEEDS_A,
                   "trt_seeds_B": TRT_SEEDS_B,
                   "n_jobs": len(jobs),
                   "jobs": [{k: v for k, v in j.items() if k != "out_dir"}
                            for j in jobs]}, fh, indent=1)
    csv_out = os.path.join(HERE, "replication_metrics.csv")
    recs, errs = R.run_batch(jobs, csv_out, workers=8)
    print("ok=%d err=%d -> %s" % (len(recs), len(errs), csv_out))
    if errs:
        for e in errs[:5]:
            print("  ERR", e["id"], e["error"][:200])
