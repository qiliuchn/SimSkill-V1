#!/usr/bin/env python3
"""STEP 3 -- MORRIS ELEMENTARY-EFFECTS SCREENING of the 13-factor,
multi-subsystem space, run separately in the UNDERSATURATED and OVERSATURATED
demand regimes, with every mu* decision-gated against the measured seed-noise
floor from STEP 2.

THE SAMPLER IS REUSED, NOT REWRITTEN.  `trajectory()` is imported from
  .claude/skills/procedural-memory/calibrate-car-following-parameters-against-field-targets/scripts/morris.py
using exactly the import shim that
  .claude/skills/procedural-memory/calibrate-lane-changing-parameters-at-a-freeway-diverge/scripts/screen_morris.py
established (set sys.argv before import because that module reads it at import
time, then retarget CFMORRIS.K and CFMORRIS.rng).  p = 4 levels, Delta = 2/3,
one coordinate moved per step, reflection at the cube boundary.

NEW here: the factor space spans five SUMO subsystems (car-following,
lane-changing, junction/driver, fleet composition, demand, signal control);
mu* is normalised by the MEASURED seed-noise standard deviation of that MOE in
that regime, so "is this factor's effect real?" is a formal test rather than a
ranking convention; and the identical design is run in two demand regimes so
the ranking can be compared.

Usage: screen_morris.py [r_trajectories] [n_seeds]
"""
import os, sys, json, math
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gsa_common as G

# ---- REUSED Morris sampler ------------------------------------------------
CF = ("/Users/liuqi/Desktop/simskill/.claude/skills/procedural-memory/"
      "calibrate-car-following-parameters-against-field-targets/scripts")
sys.path.insert(0, CF)
_argv = sys.argv
sys.argv = ["morris.py", "Krauss", "1"]      # module reads sys.argv at import
import morris as CFMORRIS                    # noqa: E402
sys.argv = _argv

R = int(sys.argv[1]) if len(sys.argv) > 1 else 10
NSEED = int(sys.argv[2]) if len(sys.argv) > 2 else 3
SEEDS = tuple(1001 + 13 * i for i in range(NSEED))   # subset of the noise-floor seeds

NAMES = G.NAMES
K = len(NAMES)
CFMORRIS.K = K                                # retarget the reused sampler
CFMORRIS.rng = np.random.default_rng(20260806)
DELTA = CFMORRIS.DELTA

MOES = ["arrived", "timeloss_per_km", "queue_mean_m", "queue_max_m",
        "co2_kg", "teleports"]

NF = json.load(open(os.path.join(G.TBL, "noise_floor.json")))


def scales(regime):
    rows = {r["metric"]: r for r in NF["regimes"][regime]["rows"]}
    mean = {m: rows[m]["mean"] for m in MOES}
    sd = {m: rows[m]["sd"] for m in MOES}
    return mean, sd


def main():
    # ONE common trajectory design, used in BOTH regimes, so the regime
    # comparison is paired (identical factor points).
    trajs = [CFMORRIS.trajectory() for _ in range(R)]
    allpts = []
    for pts, order, steps in trajs:
        allpts.extend(list(pts))
    plist = [G.unit_to_params(u) for u in allpts]
    print("[morris] k=%d factors, r=%d trajectories, %d points x %d CRN seeds "
          "x 2 regimes = %d SUMO runs"
          % (K, R, len(plist), NSEED, 2 * len(plist) * NSEED))

    result = {}
    raw = {}
    for regime in ("under", "over"):
        res = G.evaluate(plist, regime, seeds=SEEDS)
        nfail = sum(1 for r in res if not r["ok"])
        print("[morris/%s] failed evaluations: %d/%d" % (regime, nfail, len(res)))
        mean, sd = scales(regime)
        raw[regime] = [
            dict(unit=[float(x) for x in u],
                 params={k: v for k, v in p.items()},
                 ok=r["ok"], **{m: r.get(m) for m in MOES + ["not_inserted",
                                                             "collisions",
                                                             "veh_km"]})
            for u, p, r in zip(allpts, plist, res)]

        # normalised responses: Y = value / baseline mean of that MOE
        def Yvec(r):
            y = {}
            for m in MOES:
                if not r["ok"] or mean[m] == 0:
                    y[m] = float("nan")
                else:
                    y[m] = r[m] / mean[m]
            return y
        Y = [Yvec(r) for r in res]

        # elementary effects, and the SAME arithmetic on a nested r/2 subset
        def collect(traj_subset, index_offsets):
            ee = {m: {n: [] for n in NAMES} for m in MOES}
            for (pts, order, steps), off in zip(traj_subset, index_offsets):
                idx = list(range(off, off + K + 1))
                for i in range(K):
                    j = order[i]; d = steps[i]
                    if abs(d) < 1e-9:
                        continue
                    for m in MOES:
                        a, b = Y[idx[i]][m], Y[idx[i + 1]][m]
                        if a == a and b == b:
                            ee[m][NAMES[j]].append((b - a) / d)
            return ee

        offs = [t * (K + 1) for t in range(R)]
        ee_full = collect(trajs, offs)
        ee_half = collect(trajs[:R // 2], offs[:R // 2])

        # EE noise floor: two independent CRN-mean evaluations of the SAME point
        # differ by ~sqrt(2)*sd_mean; sd_mean = sd/sqrt(nseed); divide by Delta
        # because EE = dY/Delta.  Normalised by the same baseline mean as Y.
        ee_noise = {}
        for m in MOES:
            s = sd[m] / mean[m] if mean[m] else float("nan")
            ee_noise[m] = (math.sqrt(2.0) * s / math.sqrt(NSEED) / DELTA
                           if s == s else float("nan"))

        def table(ee):
            t = {}
            for m in MOES:
                rows = []
                for n in NAMES:
                    e = np.array(ee[m][n], dtype=float)
                    if len(e) == 0:
                        rows.append(dict(factor=n, subsystem=G.SUBSYS[n],
                                         mu_star=float("nan"), mu=float("nan"),
                                         sigma=float("nan"), n=0,
                                         mu_star_over_noise=float("nan"),
                                         above_noise=False))
                        continue
                    mus = float(np.mean(np.abs(e)))
                    nz = ee_noise[m]
                    rows.append(dict(
                        factor=n, subsystem=G.SUBSYS[n], mu_star=mus,
                        mu=float(np.mean(e)),
                        sigma=float(np.std(e, ddof=1)) if len(e) > 1 else 0.0,
                        n=int(len(e)),
                        mu_star_over_noise=(mus / nz if nz and nz == nz and nz > 0
                                            else float("nan")),
                        above_noise=bool(nz == nz and nz > 0 and mus > 2.0 * nz)))
                rows.sort(key=lambda r: -(r["mu_star"] if r["mu_star"] == r["mu_star"]
                                          else -1))
                t[m] = rows
            return t

        result[regime] = dict(ee_noise_floor=ee_noise,
                              baseline_mean=mean, baseline_sd=sd,
                              table=table(ee_full),
                              table_half_r=table(ee_half),
                              n_failed=nfail)

        for m in MOES:
            nz = ee_noise[m]
            print("\n--- %s / %s   (EE noise floor = %.4f, gate = 2x = %.4f) ---"
                  % (regime, m, nz, 2 * nz))
            print("  %-16s %-16s %10s %10s %10s %9s %7s"
                  % ("factor", "subsystem", "mu*", "mu", "sigma", "mu*/noise",
                     ">2xnoise"))
            for r in result[regime]["table"][m]:
                print("  %-16s %-16s %10.4f %10.4f %10.4f %9.2f %7s"
                      % (r["factor"], r["subsystem"], r["mu_star"], r["mu"],
                         r["sigma"], r["mu_star_over_noise"],
                         "YES" if r["above_noise"] else "-"))

    json.dump(dict(r=R, k=K, n_seeds=NSEED, seeds=list(SEEDS),
                   n_points=len(plist), delta=DELTA, levels=CFMORRIS.P_LEVELS,
                   sampler_source=os.path.join(CF, "morris.py"),
                   factor_ranges={n: list(G.SPACE[n]) for n in NAMES},
                   subsystem=G.SUBSYS, moes=MOES, regimes=result),
              open(os.path.join(G.TBL, "morris.json"), "w"), indent=2)
    json.dump(raw, open(os.path.join(G.TBL, "morris_raw_points.json"), "w"),
              indent=1)
    print("\nwrote", os.path.join(G.TBL, "morris.json"))
    print("wrote", os.path.join(G.TBL, "morris_raw_points.json"))


if __name__ == "__main__":
    main()
