"""Verify that the TraCI-injected incident produces a MEASURABLE disturbance in the
detector time series (not assumed) -- CRN-paired incident vs control on the same seed."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import *
import numpy as np
from run_day import run

os.makedirs(RESULTS_DIR, exist_ok=True)


def probe(level, seed, tag):
    dirs = {}
    for arm in ("incident", "control"):
        d = os.path.join(RUNS_DIR, f"_verify_{tag}_{arm}")
        m = run(d, level, seed, arm, label=f"{tag}_{arm}")
        dirs[arm] = (d, m)
    di, mi = dirs["incident"]
    dc, mc = dirs["control"]
    zi = np.load(os.path.join(di, "det.npz"))
    zc = np.load(os.path.join(dc, "det.npz"))
    inc = mi["incident"]
    k = inc["seg"]
    j0 = int(mi["injected_t"] // DET_PERIOD)
    j1 = int((mi["injected_t"] + inc["dur"]) // DET_PERIOD)
    up, dn = max(k - 1, 0), min(k + 1, N_SEG - 1)
    out = {"level": level, "seed": seed, "seg": k, "n_block": inc["n_block"],
           "t_start": mi["injected_t"], "dur": inc["dur"],
           "teleports_inc": mi["teleports"], "teleports_ctl": mc["teleports"],
           "collisions_inc": mi["collisions"], "collisions_ctl": mc["collisions"],
           "inserted_inc": mi["inserted"], "inserted_ctl": mc["inserted"],
           "running_tail_unique_inc": mi["running_tail_unique"]}
    for name, st in (("upstream", up), ("at", k), ("downstream", dn)):
        out[f"occ_{name}_inc"] = float(np.nanmean(zi["occ"][st, j0:j1]))
        out[f"occ_{name}_ctl"] = float(np.nanmean(zc["occ"][st, j0:j1]))
        out[f"spd_{name}_inc"] = float(np.nanmean(zi["spd"][st, j0:j1]))
        out[f"spd_{name}_ctl"] = float(np.nanmean(zc["spd"][st, j0:j1]))
        out[f"vol_{name}_inc"] = float(np.nansum(zi["vol"][st, j0:j1]))
        out[f"vol_{name}_ctl"] = float(np.nansum(zc["vol"][st, j0:j1]))
    # CRN check: pre-incident detector series must be IDENTICAL between the two arms
    pre = slice(0, j0)
    out["crn_pre_identical"] = bool(np.array_equal(zi["vol"][:, pre], zc["vol"][:, pre]))
    out["gt_speed_at_edge_inc"] = float(np.nanmean(zi["gt_speed"][j0:j1]))
    out["gt_speed_at_edge_ctl"] = float(np.nanmean(zc["gt_speed"][j0:j1]))
    return out


if __name__ == "__main__":
    rows = []
    for level in ("low", "moderate", "high"):
        for seed in (1, 2, 3, 4, 5, 6):
            r = probe(level, seed, f"{level}{seed}")
            rows.append(r)
            print(f"{level:8s} s{seed} seg{r['seg']:2d} block{r['n_block']} "
                  f"CRNpre={str(r['crn_pre_identical']):5s} tele={r['teleports_inc']} "
                  f"coll={r['collisions_inc']} | "
                  f"UP occ {r['occ_upstream_ctl']:5.1f}->{r['occ_upstream_inc']:5.1f} "
                  f"spd {r['spd_upstream_ctl']:5.1f}->{r['spd_upstream_inc']:5.1f} | "
                  f"AT occ {r['occ_at_ctl']:5.1f}->{r['occ_at_inc']:5.1f} | "
                  f"DN vol {r['vol_downstream_ctl']:5.0f}->{r['vol_downstream_inc']:5.0f} "
                  f"spd {r['spd_downstream_ctl']:5.1f}->{r['spd_downstream_inc']:5.1f}")
    with open(os.path.join(RESULTS_DIR, "incident_verification.json"), "w") as f:
        json.dump(rows, f, indent=1)
    print("\nwrote", os.path.join(RESULTS_DIR, "incident_verification.json"))
