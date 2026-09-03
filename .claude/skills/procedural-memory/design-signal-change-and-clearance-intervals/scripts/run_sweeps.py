"""Parallel sweep driver with Common Random Numbers.

Every arm of every comparison uses the SAME seed list (CRN), so paired statistics can be
computed. Each cell writes a metrics.json; large raw outputs are pruned after parsing,
except for a designated AUDIT subset which is retained in full for independent re-checking.
"""
import argparse
import itertools
import json
import os
import shutil
import traceback
from multiprocessing import Pool

from common import ANA_DIR, RUN_DIR
from build_net import build
import analytic
import sim_rig

SEEDS = [11, 22, 33, 44, 55, 66]          # CRN seed list, identical across every arm
LOW, HIGH = 650, 1150                      # veh/h per approach per 2 lanes
CYCLE = 80.0
SIM_END = 1500.0
DEMAND_END = 1200.0
WARMUP = 240.0

DRIVERS = {
    # SUMO out of the box: full-decel braking, action step == simulation step, everyone complies
    "DEF": dict(car_over=dict(decel="4.5", actionStepLength="0.1"),
                noncomp_share=0.0, noncomp_jm=None),
    # ITE-consistent kinematics (a = 3.05 m/s^2) + a 1.0 s perception-reaction proxy via
    # actionStepLength, plus a 10% non-compliant share modelled ONLY through jmDriveAfterRedTime
    "ITE": dict(car_over=dict(decel="3.05", actionStepLength="1.0"),
                noncomp_share=0.10, noncomp_jm=dict(jmDriveAfterRedTime="1.0")),
    "ITE_NC00": dict(car_over=dict(decel="3.05", actionStepLength="1.0"),
                     noncomp_share=0.0, noncomp_jm=None),
    "ITE_NC05": dict(car_over=dict(decel="3.05", actionStepLength="1.0"),
                     noncomp_share=0.05, noncomp_jm=dict(jmDriveAfterRedTime="1.0")),
    "ITE_NC20": dict(car_over=dict(decel="3.05", actionStepLength="1.0"),
                     noncomp_share=0.20, noncomp_jm=dict(jmDriveAfterRedTime="1.0")),
    # perception-reaction only (no decel change) and decel only (no PRT) -- decomposition
    "PRT_ONLY": dict(car_over=dict(decel="4.5", actionStepLength="1.0"),
                     noncomp_share=0.10, noncomp_jm=dict(jmDriveAfterRedTime="1.0")),
    "DECEL_ONLY": dict(car_over=dict(decel="3.05", actionStepLength="0.1"),
                       noncomp_share=0.10, noncomp_jm=dict(jmDriveAfterRedTime="1.0")),
}

NET_CACHE = {}


def get_net(speed, grade, lanes, arm=400.0):
    key = (round(speed, 3), round(grade, 3), lanes, arm)
    if key not in NET_CACHE:
        nm = "n_v%.0f_g%+.0f_l%d" % (speed * 100, grade, lanes)
        NET_CACHE[key] = build(nm, speed=speed, grade_pct=grade, lanes=lanes, arm=arm)[1]
    return NET_CACHE[key]


def cell_id(c):
    return "_".join("%s%s" % (k, c[k]) for k in sorted(c) if k not in ("net", "meta"))


def work(job):
    name, meta, cfg, audit = job
    rd = os.path.join(RUN_DIR, name)
    if os.path.exists(os.path.join(rd, "metrics.json")):
        return name, "cached"
    if os.path.exists(rd):
        shutil.rmtree(rd)
    try:
        log_p, recs = sim_rig.run_cell(rd, meta, cfg)
        m = sim_rig.read_metrics(rd)
        s = sim_rig.read_ssm(rd, warmup=cfg.get("warmup", WARMUP))
        pets = s.pop("pets")
        rttc = s.pop("rear_ttcs")
        jp = json.load(open(os.path.join(rd, "jpet.json")))
        out = dict(name=name, cfg={k: v for k, v in cfg.items() if k != "meta"},
                   metrics=m, ssm=s, n_decision=len(recs),
                   jpet_n=len(jp["jpet"]), jpet_overlap=jp["n_overlap"],
                   jpet_passages=jp["n_junction_passages"],
                   jpet_lt_1=sum(1 for x in jp["jpet"] if x < 1.0),
                   jpet_lt_2=sum(1 for x in jp["jpet"] if x < 2.0),
                   jpet_min=min(jp["jpet"]) if jp["jpet"] else None,
                   jpet_min_pos=min([x for x in jp["jpet"] if x > 0], default=None),
                   ssm_pet_n=len(pets), ssm_pet_min=min(pets) if pets else None,
                   rear_ttc_n=len(rttc))
        json.dump(out, open(os.path.join(rd, "metrics.json"), "w"), indent=2)
        if not audit:
            sim_rig.prune_run(rd, keep=("decision_log.csv", "metrics.json", "jpet.json",
                                        "tls_verify.json", "plan.json", "extra.add.xml",
                                        "demand.rou.xml", "collisions.xml", "stats.xml",
                                        "summary.xml", "sumo.err"))
        return name, "ok"
    except Exception:
        return name, "FAIL\n" + traceback.format_exc()


def submit(jobs, procs=9):
    print("submitting %d jobs" % len(jobs), flush=True)
    fails = []
    with Pool(procs) as p:
        for i, (n, st) in enumerate(p.imap_unordered(work, jobs)):
            if st.startswith("FAIL"):
                fails.append((n, st))
                print("FAIL", n, st[:600], flush=True)
            if (i + 1) % 25 == 0:
                print("  %d/%d" % (i + 1, len(jobs)), flush=True)
    print("done, %d failures" % len(fails), flush=True)
    return fails


def base_cfg(**kw):
    c = dict(cycle=CYCLE, demand_end=DEMAND_END, sim_end=SIM_END, warmup=WARMUP,
             step_length=0.1, ssm=True, detectors=False, ttt=300, resp_window=6.0)
    c.update(kw)
    return c


# --------------------------------------------------------------------- sweeps

def sweep_A():
    """Main yellow sweep: y x speed x demand x driver-model, CRN replicated. H1/H2/H6."""
    jobs = []
    for drv, y, v, dem in itertools.product(("DEF", "ITE"), (2.0, 3.0, 4.0, 5.0, 6.0),
                                            (13.89, 19.44, 25.0), ("low", "high")):
        meta = get_net(v, 0.0, 2)
        for k, sd in enumerate(SEEDS):
            cfg = base_cfg(yellow=y, allred=1.0, vph=LOW if dem == "low" else HIGH,
                           seed=sd, **DRIVERS[drv])
            cfg["_sweep"] = "A"
            cfg["_driver"] = drv
            cfg["_v"] = v
            cfg["_dem"] = dem
            name = "A_%s_y%.1f_v%.2f_%s_s%d" % (drv, y, v, dem, sd)
            jobs.append((name, meta, cfg, k == 0 and y in (3.0, 5.0) and v == 19.44))
    return jobs


def sweep_A2():
    """Non-compliance share decomposition at fixed speed/demand. H1/H2."""
    jobs = []
    for drv, y in itertools.product(("ITE_NC00", "ITE_NC20", "PRT_ONLY", "DECEL_ONLY"),
                                    (2.0, 3.0, 5.0)):
        meta = get_net(19.44, 0.0, 2)
        for sd in SEEDS:
            cfg = base_cfg(yellow=y, allred=1.0, vph=LOW, seed=sd, **DRIVERS[drv])
            cfg["_sweep"] = "A2"
            cfg["_driver"] = drv
            cfg["_v"] = 19.44
            cfg["_dem"] = "low"
            jobs.append(("A2_%s_y%.1f_s%d" % (drv, y, sd), meta, cfg, False))
    return jobs


def sweep_B():
    """All-red sweep at two speeds and two intersection widths. H4."""
    jobs = []
    for v, lanes, ar in itertools.product((13.89, 25.0), (2, 4), (0.0, 1.0, 2.0, 3.0)):
        meta = get_net(v, 0.0, lanes)
        y = round(analytic.ite_yellow(v) * 2) / 2.0     # ITE yellow, rounded to 0.5 s
        for sd in SEEDS:
            cfg = base_cfg(yellow=y, allred=ar, vph=325 * lanes, seed=sd, **DRIVERS["ITE"])
            cfg["_sweep"] = "B"
            cfg["_driver"] = "ITE"
            cfg["_v"] = v
            cfg["_lanes"] = lanes
            cfg["_W"] = meta["W_mean"]
            cfg["_dem"] = "low"
            jobs.append(("B_v%.2f_l%d_ar%.1f_s%d" % (v, lanes, ar, sd), meta, cfg, False))
    return jobs


def sweep_C():
    """Truck share x grade x yellow. H5."""
    jobs = []
    for ts, g, y in itertools.product((0.0, 0.30), (0.0, -4.0), (3.0, 5.0)):
        meta = get_net(19.44, g, 2)
        for sd in SEEDS:
            cfg = base_cfg(yellow=y, allred=1.0, vph=LOW, seed=sd, truck_share=ts,
                           **DRIVERS["ITE"])
            cfg["truck_over"] = dict(decel="2.5", actionStepLength="1.0")
            cfg["_sweep"] = "C"
            cfg["_driver"] = "ITE"
            cfg["_v"] = 19.44
            cfg["_truck"] = ts
            cfg["_grade"] = g
            cfg["_dem"] = "low"
            jobs.append(("C_t%.2f_g%+.0f_y%.1f_s%d" % (ts, g, y, sd), meta, cfg, False))
    return jobs


def sweep_F():
    """--time-to-teleport sensitivity + a hard-braking-threshold-free validity check."""
    jobs = []
    for ttt, dem, y in itertools.product((-1, 120, 300, 600), ("high",), (2.0, 5.0)):
        meta = get_net(19.44, 0.0, 2)
        for sd in SEEDS[:3]:
            cfg = base_cfg(yellow=y, allred=1.0, vph=LOW if dem == "low" else HIGH,
                           seed=sd, ttt=ttt, **DRIVERS["ITE"])
            cfg["_sweep"] = "F"
            cfg["_ttt"] = ttt
            cfg["_dem"] = dem
            cfg["_driver"] = "ITE"
            cfg["_v"] = 19.44
            jobs.append(("F_ttt%d_%s_y%.1f_s%d" % (ttt, dem, y, sd), meta, cfg, False))
    return jobs


def sweep_G():
    """Genuinely saturated / oversaturated demand, so the CAPACITY side of H6 has something
    to measure. At sweep A's 'high' level the approach still runs at v/c ~0.65 and throughput
    is demand-limited (identical at every yellow), which cannot expose a capacity optimum."""
    jobs = []
    for drv, vph, y in itertools.product(("ITE",), (1600, 1900),
                                         (2.0, 3.0, 4.0, 5.0, 6.0)):
        meta = get_net(19.44, 0.0, 2)
        for sd in SEEDS:
            cfg = base_cfg(yellow=y, allred=1.0, vph=vph, seed=sd, **DRIVERS[drv])
            cfg["_sweep"] = "G"
            cfg["_driver"] = drv
            cfg["_v"] = 19.44
            cfg["_dem"] = "sat%d" % vph
            cfg["extra_args"] = ["--max-depart-delay", "600"]
            jobs.append(("G_%s_q%d_y%.1f_s%d" % (drv, vph, y, sd), meta, cfg, False))
    return jobs


ALL = dict(A=sweep_A, A2=sweep_A2, B=sweep_B, C=sweep_C, F=sweep_F, G=sweep_G)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweeps", default="A,A2,B,C,F,G")
    ap.add_argument("--procs", type=int, default=9)
    a = ap.parse_args()
    jobs = []
    for s in a.sweeps.split(","):
        js = ALL[s.strip()]()
        print("%s: %d jobs" % (s, len(js)), flush=True)
        jobs += js
    fails = submit(jobs, a.procs)
    json.dump([f[0] for f in fails], open(os.path.join(ANA_DIR, "failures.json"), "w"), indent=2)


if __name__ == "__main__":
    main()
