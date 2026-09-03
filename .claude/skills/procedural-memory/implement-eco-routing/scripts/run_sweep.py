"""Market-penetration and alpha/beta sweeps for the online TraCI eco-router.

Every arm starts from the SAME per-seed travel-time user equilibrium route file
(duaIterate final iteration) and the same demand realisation -- Common Random
Numbers across arms -- so the only thing that varies is (i) which share of
main-OD vehicles is equipped with the eco-router and (ii) the alpha/beta
weighting of its generalized cost.

beta is parameterised as beta = lam * R, where
R = sum_e freeflow_traveltime_e / sum_e freeflow_fuelPerVeh_e = 1.238e-3 s/mg,
so lam = 1 makes the time term and the fuel term contribute equally at free
flow. lam = 0 is a pure travel-time online router (the control that separates
"rerouting at all" from "eco rerouting"); the PURE arm is alpha=0, beta=1.
"""
import json
import multiprocessing as mp
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import WORK, OUT  # noqa: E402

R_SCALE = 1.238073e-03      # s per mg fuel, from the free-flow probe
SEEDS = [0, 1, 2, 3, 4]
SWEEP_DIR = os.path.join(WORK, "sweep")
os.makedirs(SWEEP_DIR, exist_ok=True)


def job(args):
    tag, pen, alpha, beta, seed = args
    import traci_eco_router as ter
    prefix = os.path.join(SWEEP_DIR, "%s_p%03d_s%d" % (tag, round(pen * 100), seed))
    try:
        base = os.path.join(WORK, "baseline_ue_s%d.rou.xml" % seed)
        tagged = prefix + "_routes.rou.xml"
        n_eq, n_main = ter.tag_routes(base, tagged, pen, seed)
        res = ter.run(tagged, prefix, alpha, beta, seed=100 + seed, log_every=300)
        s = ter.summarise(res, pen, alpha, beta, seed, tag)
        s["n_equipped"], s["n_main"] = n_eq, n_main
        s["trace"] = res["trace"]
        with open(prefix + "_summary.json", "w") as f:
            json.dump(s, f, indent=1)
        # keep the disk footprint sane
        for suf in ("_vehroute.xml", "_tripinfo.xml", "_routes.rou.xml", "_edgeemis.xml"):
            p = prefix + suf
            if os.path.exists(p) and tag not in ("pen",):
                os.remove(p)
        return dict(ok=True, tag=tag, pen=pen, seed=seed, lam=beta / R_SCALE if alpha else -1,
                    file=prefix + "_summary.json")
    except Exception:
        return dict(ok=False, tag=tag, pen=pen, seed=seed, err=traceback.format_exc())


def build_jobs():
    jobs = []
    # (A) penetration sweep at the balanced eco weighting lam = 1
    for pen in (0.0, 0.25, 0.5, 0.75, 1.0):
        for s in SEEDS:
            jobs.append(("pen", pen, 1.0, 1.0 * R_SCALE, s))
    # (B) online travel-time-only control (lam = 0) -- isolates "rerouting at
    #     all" from "eco rerouting"
    for pen in (0.25, 0.5, 0.75, 1.0):
        for s in SEEDS:
            jobs.append(("tt", pen, 1.0, 0.0, s))
    # (C) alpha/beta sweep at full penetration
    for lam in (0.25, 0.5, 2.0, 4.0, 8.0):
        for s in SEEDS:
            jobs.append(("lam%g" % lam, 1.0, 1.0, lam * R_SCALE, s))
    for s in SEEDS:                                   # pure minimum-fuel
        jobs.append(("lampure", 1.0, 0.0, 1.0, s))
    return jobs


if __name__ == "__main__":
    jobs = build_jobs()
    print("%d runs" % len(jobs))
    with mp.Pool(6) as pool:
        for i, r in enumerate(pool.imap_unordered(job, jobs)):
            if not r["ok"]:
                print("FAIL", r["tag"], r["pen"], r["seed"], r["err"][-800:])
            elif i % 10 == 0:
                print("  %d/%d done" % (i + 1, len(jobs)))
    print("sweep complete ->", SWEEP_DIR)
