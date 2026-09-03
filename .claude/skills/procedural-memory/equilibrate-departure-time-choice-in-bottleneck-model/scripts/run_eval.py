"""
Multi-seed (Common Random Numbers) evaluation of every converged equilibrium,
plus the marginal-traveller probe test and the capacity-invariance check.
"""
import os, sys, json, csv
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vickrey_lib import *
from evaluate import evaluate_condition, probe_unused_slots, EVAL_SEEDS, summarize

CONDS = ["no_toll", "tv_toll", "tv_toll2", "flat_toll", "zero_toll", "gamma4", "no_toll_alt"]


def main(conds):
    cap = json.load(open(os.path.join(WORK, "capacity", "capacity.json")))
    tf = cap["free_flow"]["tf_mean"]
    out = {}
    all_seed_rows = []
    for nm in conds:
        r = json.load(open(os.path.join(WORK, "eq_" + nm, "result.json")))
        counts = np.array(r["counts"], int)
        toll = np.array(r["toll"], float)
        gamma = r["gamma"]
        d = os.path.join(WORK, "eval_" + nm)
        per_seed, rows_by_seed = evaluate_condition(nm, counts, toll, tf, d,
                                                    seeds=EVAL_SEEDS, gamma=gamma)
        all_seed_rows += per_seed
        # per-vehicle detail for the first evaluation seed (kept as the full raw output set)
        v = rows_by_seed[EVAL_SEEDS[0]]
        with open(os.path.join(d, "per_vehicle_seed%d.csv" % EVAL_SEEDS[0]), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(v[0].keys())); w.writeheader(); w.writerows(v)
        out[nm] = dict(per_seed=per_seed, gamma=gamma)
        print("  %-10s meanCost=%.1f  meanQ=%.1f  disch=%.1f veh/h  dd=%.2f"
              % (nm, np.mean([p["mean_cost"] for p in per_seed]),
                 np.mean([p["mean_queue_delay"] for p in per_seed]),
                 np.nanmean([p["discharge_saturated_vph"] for p in per_seed]),
                 np.mean([p["mean_depart_delay"] for p in per_seed])), flush=True)
    with open(os.path.join(WORK, "eval_per_seed.json"), "w") as f:
        json.dump(out, f, indent=2)
    with open(os.path.join(WORK, "metrics_by_seed.csv"), "w", newline="") as f:
        fields = ["condition", "seed"] + [k for k in all_seed_rows[0] if k not in ("condition", "seed")]
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(all_seed_rows)
    return out


def probes(conds=("no_toll", "tv_toll")):
    cap = json.load(open(os.path.join(WORK, "capacity", "capacity.json")))
    tf = cap["free_flow"]["tf_mean"]
    res = {}
    for nm in conds:
        r = json.load(open(os.path.join(WORK, "eq_" + nm, "result.json")))
        rows, nb = probe_unused_slots(np.array(r["counts"], int), np.array(r["toll"], float),
                                      tf, os.path.join(WORK, "probe_" + nm),
                                      seed=1, gamma=r["gamma"])
        res[nm] = rows
        print("  probes %-8s: %d unused slots probed in %d batches" % (nm, len(rows), nb), flush=True)
    with open(os.path.join(WORK, "probe_results.json"), "w") as f:
        json.dump(res, f, indent=2)
    return res


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    cs = sys.argv[2].split(",") if len(sys.argv) > 2 else CONDS
    if what in ("all", "eval"):
        main(cs)
    if what in ("all", "probe"):
        probes()
