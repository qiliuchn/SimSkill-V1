#!/usr/bin/env python3
"""STEP 3 -- Morris elementary-effects GLOBAL SENSITIVITY SCREENING over the
LC2013 lane-changing parameter space + the --lanechange.duration setting.

The Morris SAMPLER ITSELF IS REUSED, not rebuilt: `trajectory()` is imported
from `calibrate-car-following-parameters-against-field-targets/scripts/morris.py`
(p=4 levels, Delta=2/3, one coordinate moved per step, reflection at the cube
boundary).  Only the response vector Y is LC-specific: as that skill insists,
mu*/sigma are computed for EVERY observable separately (each normalised by its
own target or its own default-parameter baseline) as well as for the aggregate
objective, so a parameter that is the sole control of one observable is not
fixed on the strength of a small aggregate mu*.

Usage: screen_morris.py [r_trajectories] [n_seeds]
"""
import os, sys, json, math
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lc_common as L
from lc_eval import evaluate_runs

# --- import the Morris trajectory sampler from the car-following skill -----
CF = ("/Users/liuqi/Desktop/simskill/.claude/skills/procedural-memory/"
      "calibrate-car-following-parameters-against-field-targets/scripts")
sys.path.insert(0, CF)
_argv = sys.argv
sys.argv = ["morris.py", "Krauss", "1"]        # module reads sys.argv at import
import morris as CFMORRIS                      # noqa: E402
sys.argv = _argv

R = int(sys.argv[1]) if len(sys.argv) > 1 else 10
NSEED = int(sys.argv[2]) if len(sys.argv) > 2 else 4
SEEDS = tuple(1000 + 7 * i for i in range(NSEED))

NAMES = L.LC_NAMES
K = len(NAMES)
CFMORRIS.K = K                                  # retarget the sampler
CFMORRIS.rng = np.random.default_rng(20260805)

# response quantities and the scale each is normalised by
BASE = json.load(open(os.path.join(L.TBL, "noise_floor.json")))
BASEMEAN = {r["metric"]: r["mean"] for r in BASE["rows"]}
BASESD = {r["metric"]: r["sd"] for r in BASE["rows"]}

SCALE = {
    "share_lane0": L.TARGET_LANE_SHARE[0],
    "share_lane1": L.TARGET_LANE_SHARE[1],
    "share_lane2": L.TARGET_LANE_SHARE[2],
    "dlc": L.TARGET_DLC,
    "p85": L.TARGET_P85,
    "p50": L.TARGET_P85,
    "strat_rate": BASEMEAN["strat_rate"],       # no field target -> default baseline
    "coop_rate": 0.05,                          # nominal scale (baseline is 0)
    "fail_frac": 0.05,                          # nominal scale (baseline is 0)
    "flow": BASEMEAN["flow"],
}
QUANTS = ["obj"] + list(SCALE.keys())


def Yvec(r):
    y = {"obj": r["obj"] if r.get("ok") else 3.0}
    if not r.get("ok"):
        for q in SCALE:
            y[q] = float("nan")
        return y
    for q in SCALE:
        if q.startswith("share_lane"):
            v = r["share"][int(q[-1])]
        else:
            v = r[q]
        y[q] = v / SCALE[q] if v == v else float("nan")
    return y


def main():
    trajs = [CFMORRIS.trajectory() for _ in range(R)]
    allpts = []
    for pts, order, steps in trajs:
        allpts.extend(list(pts))
    plist = [L.unit_to_params(u, NAMES) for u in allpts]
    print("[morris] k=%d params, r=%d trajectories, %d points x %d CRN seeds "
          "= %d runs" % (K, R, len(plist), NSEED, len(plist) * NSEED))
    res = evaluate_runs(plist, seeds=SEEDS)
    nfail = sum(1 for r in res if not r.get("ok"))
    print("[morris] failed evaluations: %d/%d" % (nfail, len(res)))

    Y = [Yvec(r) for r in res]
    ee = {q: {n: [] for n in NAMES} for q in QUANTS}
    ptr = 0
    for pts, order, steps in trajs:
        idx = list(range(ptr, ptr + K + 1)); ptr += K + 1
        for i in range(K):
            j = order[i]; d = steps[i]
            if abs(d) < 1e-9:
                continue
            for q in QUANTS:
                a, b = Y[idx[i]][q], Y[idx[i + 1]][q]
                if a == a and b == b:
                    ee[q][NAMES[j]].append((b - a) / d)

    # noise floor on an elementary effect: two independent CRN-mean evaluations
    # differ by ~sqrt(2)*sd/sqrt(nseed); divided by the Morris step Delta=2/3.
    ee_noise = {}
    for q in QUANTS:
        key = {"obj": "obj"}.get(q, q)
        sd = BASESD.get(key, float("nan"))
        sc = 1.0 if q == "obj" else SCALE[q]
        ee_noise[q] = (math.sqrt(2.0) * (sd / sc) / math.sqrt(NSEED) /
                       CFMORRIS.DELTA) if sd == sd else float("nan")

    table = {}
    for q in QUANTS:
        rows = []
        for n in NAMES:
            e = np.array(ee[q][n], dtype=float)
            if len(e) == 0:
                rows.append(dict(param=n, mu_star=float("nan"), mu=float("nan"),
                                 sigma=float("nan"), n=0, above_noise=False))
                continue
            mus = float(np.mean(np.abs(e)))
            rows.append(dict(param=n, mu_star=mus, mu=float(np.mean(e)),
                             sigma=float(np.std(e, ddof=1)) if len(e) > 1 else 0.0,
                             n=int(len(e)),
                             above_noise=bool(mus > 2.0 * ee_noise[q])))
        rows.sort(key=lambda r: -(r["mu_star"] if r["mu_star"] == r["mu_star"] else -1))
        table[q] = rows

    outp = os.path.join(L.TBL, "morris_lc2013.json")
    json.dump(dict(r=R, k=K, n_seeds=NSEED, seeds=list(SEEDS),
                   n_points=len(plist), n_failed=nfail,
                   delta=CFMORRIS.DELTA, levels=CFMORRIS.P_LEVELS,
                   ee_noise_floor=ee_noise, scale=SCALE, table=table,
                   param_ranges={n: L.PARAM_SPACE[n] for n in NAMES}),
              open(outp, "w"), indent=2)

    for q in QUANTS:
        print("\n--- %s   (EE noise floor = %.4f; mu* must exceed 2x that) ---"
              % (q, ee_noise[q]))
        print("  %-18s %10s %10s %10s %6s" % ("param", "mu*", "mu", "sigma", ">noise"))
        for r in table[q]:
            print("  %-18s %10.4f %10.4f %10.4f %6s"
                  % (r["param"], r["mu_star"], r["mu"], r["sigma"],
                     "YES" if r["above_noise"] else "-"))
    print("\nwrote", outp)


if __name__ == "__main__":
    main()
