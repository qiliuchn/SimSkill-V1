#!/usr/bin/env python3
"""STEP 5 -- IDENTIFIABILITY: which target is each parameter recoverable from?

  A  lcKeepRight x lcSpeedGain grid -> are there distinct pairs that give
     per-lane flow distributions indistinguishable at the measured seed-noise
     floor?  (equifinality on the AGGREGATE observable)
  B  lcStrategic sweep -> is it identifiable at all from aggregate lane flows,
     or only from the spatial mandatory-LC profile?  Checked from BOTH sides:
     the aggregate response must be inside the noise band AND the spatial
     response must be outside it.
  C  known-answer recovery: perturb the calibrated vector, regenerate synthetic
     targets from ITS OWN raw output, and see whether the optimiser recovers it.

Usage: identifiability.py [a|b|c|all]
"""
import os, sys, json, math, random, statistics as st
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lc_common as L
from lc_eval import evaluate_runs
import calibrate as CAL

OUTP = os.path.join(L.TBL, "identifiability.json")
NOISE = {r["metric"]: r for r in json.load(
    open(os.path.join(L.TBL, "noise_floor.json")))["rows"]}


def share_dist(a, b):
    """L2 distance between two per-lane share vectors."""
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def noise_share_dist(nrep):
    """Expected L2 distance between two independent nrep-seed share estimates."""
    v = sum(2.0 * (NOISE["share_lane%d" % i]["sd"] ** 2) / nrep for i in range(3))
    return math.sqrt(v)


def part_a(out, nseed=4):
    print("\n===== A: lcKeepRight x lcSpeedGain =====")
    seeds = tuple(1000 + 7 * i for i in range(nseed))
    KR = [0.0, 0.25, 0.5, 1.0, 2.0, 3.5, 6.0]
    SG = [0.05, 0.25, 0.5, 1.0, 2.0, 3.5, 6.0]
    pl, grid = [], []
    for kr in KR:
        for sg in SG:
            p = L.full_params(); p["lcKeepRight"] = kr; p["lcSpeedGain"] = sg
            pl.append(p); grid.append((kr, sg))
    res = evaluate_runs(pl, seeds=seeds)
    rows = []
    for (kr, sg), r in zip(grid, res):
        rows.append(dict(lcKeepRight=kr, lcSpeedGain=sg, share=r["share"],
                         rmsn_lane=r["rmsn_lane"], geh_max=r["geh_max"],
                         dlc=r["dlc"], p85=r["p85"], obj=r["obj"],
                         flow=r["flow"]))
    thr = 2.0 * noise_share_dist(nseed)
    print("  noise-floor L2 distance between two %d-seed share vectors = %.5f;"
          " 'indistinguishable' threshold = %.5f" % (nseed, thr / 2, thr))
    print("  %-12s %-12s %-26s %8s %8s" % ("lcKeepRight", "lcSpeedGain",
                                           "share(r/m/l)", "rmsn", "p85"))
    for r in rows:
        print("  %-12.2f %-12.2f %-26s %8.4f %8.0f"
              % (r["lcKeepRight"], r["lcSpeedGain"],
                 "/".join("%.4f" % x for x in r["share"]), r["rmsn_lane"],
                 r["p85"]))
    # equifinal pairs: distinct (kr,sg) whose SHARE vectors are within threshold
    pairs = []
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            d = share_dist(rows[i]["share"], rows[j]["share"])
            if d <= thr:
                du = math.hypot(
                    (rows[i]["lcKeepRight"] - rows[j]["lcKeepRight"]) / 6.0,
                    (rows[i]["lcSpeedGain"] - rows[j]["lcSpeedGain"]) / 5.95)
                pairs.append(dict(a=(rows[i]["lcKeepRight"], rows[i]["lcSpeedGain"]),
                                  b=(rows[j]["lcKeepRight"], rows[j]["lcSpeedGain"]),
                                  share_dist=d, unit_cube_dist=du,
                                  p85_a=rows[i]["p85"], p85_b=rows[j]["p85"],
                                  dlc_a=rows[i]["dlc"], dlc_b=rows[j]["dlc"]))
    pairs.sort(key=lambda x: -x["unit_cube_dist"])
    print("\n  %d indistinguishable (kr,sg) PAIRS out of %d; "
          "most separated ones:" % (len(pairs), len(rows) * (len(rows) - 1) // 2))
    for q in pairs[:8]:
        print("    %s vs %s   share-L2=%.5f  unit-cube sep=%.3f  "
              "dlc %.3f vs %.3f  p85 %.0f vs %.0f"
              % (q["a"], q["b"], q["share_dist"], q["unit_cube_dist"],
                 q["dlc_a"], q["dlc_b"], q["p85_a"], q["p85_b"]))
    out["A_keepright_speedgain"] = dict(rows=rows, threshold=thr, n_seed=nseed,
                                        seeds=list(seeds),
                                        n_indistinguishable_pairs=len(pairs),
                                        n_pairs_total=len(rows) * (len(rows) - 1) // 2,
                                        top_pairs=pairs[:25])


def part_b(out, nseed=6):
    print("\n===== B: is lcStrategic identifiable from aggregate lane flows? =====")
    seeds = tuple(1000 + 7 * i for i in range(nseed))
    VALS = [0.1, 0.25, 0.5, 1.0, 2.0, 3.0, 4.5, 6.0]
    pl = []
    for v in VALS:
        p = L.full_params(); p["lcStrategic"] = v; pl.append(p)
    res = evaluate_runs(pl, seeds=seeds, want_profiles=True, keep=False)
    rows = []
    for v, r in zip(VALS, res):
        rows.append(dict(lcStrategic=v, share=r["share"], rmsn_lane=r["rmsn_lane"],
                         geh_max=r["geh_max"], dlc=r["dlc"], p85=r["p85"],
                         p50=r["p50"], p15=r["p15"], fail_frac=r["fail_frac"],
                         strat_rate=r["strat_rate"], flow=r["flow"],
                         n_nochange=r["n_nochange"], n_cohort=r["n_cohort"]))
        print("  lcStrategic=%4.2f  share=%s  rmsn=%.4f  p85=%6.0f  p50=%6.0f  "
              "strat_rate=%.4f  fail=%.4f"
              % (v, "/".join("%.4f" % x for x in r["share"]), r["rmsn_lane"],
                 r["p85"], r["p50"], r["strat_rate"], r["fail_frac"]))
    # BOTH-SIDES check
    sh = [r["share"] for r in rows]
    rng_share = [max(s[i] for s in sh) - min(s[i] for s in sh) for i in range(3)]
    noise_share = [2.0 * 1.96 * NOISE["share_lane%d" % i]["sd"] / math.sqrt(nseed)
                   for i in range(3)]
    p85s = [r["p85"] for r in rows]
    rng_p85 = max(p85s) - min(p85s)
    noise_p85 = 2.0 * 1.96 * NOISE["p85"]["sd"] / math.sqrt(nseed)
    print("\n  per-lane share RANGE over the whole lcStrategic range: %s"
          % ["%.4f" % x for x in rng_share])
    print("  95%% noise band on a %d-seed share difference:            %s"
          % (nseed, ["%.4f" % x for x in noise_share]))
    print("  p85 RANGE %.0f m   vs 95%% noise band on a difference %.0f m"
          % (rng_p85, noise_p85))
    out["B_lcstrategic"] = dict(rows=rows, seeds=list(seeds), n_seed=nseed,
                                share_range=rng_share, share_noise_band=noise_share,
                                p85_range=rng_p85, p85_noise_band=noise_p85,
                                aggregate_identifiable=bool(
                                    any(rng_share[i] > noise_share[i] for i in range(3))),
                                spatial_identifiable=bool(rng_p85 > noise_p85))


def part_c(out, nseed=3):
    """Known-answer recovery against SYNTHETIC targets."""
    print("\n===== C: known-answer recovery =====")
    cal = json.load(open(os.path.join(L.TBL, "calibration.json")))
    free = cal["free"]
    theta = {k: float(v) for k, v in cal["best_params"].items()}
    rng = random.Random(20260805)
    u0 = L.params_to_unit(theta, free)
    ustar = [min(0.95, max(0.05, x + rng.uniform(-0.22, 0.22))) for x in u0]
    tstar = CAL.make_p(free, ustar, dict(L.LC_DEFAULTS))
    print("  ground-truth (perturbed) vector:",
          {k: round(tstar[k], 4) for k in free})

    # --- generate the synthetic targets from theta*'s OWN raw output --------
    big = tuple(3000 + 17 * i for i in range(8))
    rstar = evaluate_runs([tstar], seeds=big)[0]
    tgt_lane = {str(i): rstar["share"][i] for i in range(3)}
    tgt_dlc = rstar["dlc"]; tgt_p85 = rstar["p85"]
    print("  synthetic targets: share=%s dlc=%.4f p85=%.1f"
          % (["%.4f" % x for x in rstar["share"]], tgt_dlc, tgt_p85))

    ctx = dict(_target_lane=tgt_lane, _target_dlc=tgt_dlc, _target_p85=tgt_p85)
    saved = CAL.EVLOG
    CAL.EVLOG = os.path.join(L.TBL, "recovery_evals.jsonl")
    CAL.SEEDS = tuple(1000 + 7 * i for i in range(nseed))
    ps = CAL.run_ps(free, dict(L.LC_DEFAULTS), nstart=3, iters=10, seed=99, ctx=ctx)
    CAL.EVLOG = saved
    that = CAL.make_p(free, ps["best_u"], dict(L.LC_DEFAULTS))
    print("  recovered vector:", {k: round(that[k], 4) for k in free})

    uh = L.params_to_unit(that, free)
    per = {n: dict(true=tstar[n], recovered=that[n],
                   unit_err=uh[i] - ustar[i],
                   rel_err=(that[n] - tstar[n]) / tstar[n] if tstar[n] else float("nan"))
           for i, n in enumerate(free)}
    dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(uh, ustar)))
    # observable-space recovery
    rhat = evaluate_runs([that], seeds=big)[0]
    obs = dict(share_true=rstar["share"], share_rec=rhat["share"],
               dlc_true=rstar["dlc"], dlc_rec=rhat["dlc"],
               p85_true=rstar["p85"], p85_rec=rhat["p85"],
               share_rel_err=[(rhat["share"][i] - rstar["share"][i]) / rstar["share"][i]
                              for i in range(3)],
               dlc_rel_err=(rhat["dlc"] - rstar["dlc"]) / rstar["dlc"],
               p85_rel_err=(rhat["p85"] - rstar["p85"]) / rstar["p85"])
    print("\n  parameter recovery (unit-cube error per parameter):")
    for n in free:
        print("    %-18s true=%8.4f rec=%8.4f  unit err=%+.3f  rel=%+.1f%%"
              % (n, per[n]["true"], per[n]["recovered"], per[n]["unit_err"],
                 100 * per[n]["rel_err"]))
    print("  total unit-cube distance: %.4f (over %d free params)" % (dist, len(free)))
    print("  observable recovery: share rel err=%s  dlc %+.1f%%  p85 %+.1f%%"
          % (["%+.2f%%" % (100 * x) for x in obs["share_rel_err"]],
             100 * obs["dlc_rel_err"], 100 * obs["p85_rel_err"]))
    out["C_known_answer_recovery"] = dict(
        free=free, true=tstar, recovered=that, per_param=per,
        unit_cube_distance=dist, observables=obs,
        search_obj=ps["best_obj"], n_eval=ps["n_eval"], n_seed=nseed)


def part_d(out):
    """Equifinality band, read off the optimiser's own evaluation log -- no new
    simulations.  The 'statistically tied' band is defined from the MEASURED
    seed-noise SD of the objective, not from an arbitrary tolerance."""
    print("\n===== D: equifinality band from the optimiser evaluation log =====")
    cal = json.load(open(os.path.join(L.TBL, "calibration.json")))
    free = cal["free"]
    nrep = int(os.environ.get("LC_CAL_SEEDS", "3"))
    sd = NOISE["obj"]["sd"] / math.sqrt(nrep)
    rows = []
    with open(os.path.join(L.TBL, "calib_evals.jsonl")) as f:
        for line in f:
            d = json.loads(line)
            if d.get("ok"):
                rows.append(d)
    if not rows:
        return
    best = min(r["obj"] for r in rows)
    band = best + 2.0 * sd
    tied = [r for r in rows if r["obj"] <= band]
    print("  %d evaluated candidates; best obj=%.5f; seed SD of a %d-seed mean "
          "= %.5f; tied band <= %.5f -> %d candidates"
          % (len(rows), best, nrep, sd, band, len(tied)))
    spread = {}
    for n in free:
        v = [r["params"][n] for r in tied]
        lo, hi, _ = L.PARAM_SPACE[n]
        spread[n] = dict(min=min(v), max=max(v), median=sorted(v)[len(v) // 2],
                         unit_range=(max(v) - min(v)) / (hi - lo))
        print("    %-18s tied range %.3f .. %.3f  (%.0f%% of its screened range)"
              % (n, min(v), max(v), 100 * spread[n]["unit_range"]))
    obsrange = {}
    for k in ("dlc", "p85", "p50"):
        v = [r[k] for r in tied if r.get(k) is not None]
        obsrange[k] = dict(min=min(v), max=max(v))
    sh0 = [r["share"][0] for r in tied]
    obsrange["share_lane0"] = dict(min=min(sh0), max=max(sh0))
    print("  observables across the tied set: %s" % json.dumps(
        {k: {kk: round(vv, 4) for kk, vv in v.items()} for k, v in obsrange.items()}))
    out["D_equifinality"] = dict(n_eval=len(rows), best=best, seed_sd=sd,
                                 band=band, n_tied=len(tied), spread=spread,
                                 observable_range=obsrange, n_rep=nrep)


def part_e(out, nseed=4):
    """lcKeepRight screens as the WEAKEST parameter here.  Check that from the
    other side before generalising: prior SimSkill work
    ([[mutcd-signal-warrants-and-the-demand-vs-served-volume-trap]],
    `conduct-driveway-signal-warrant-traffic-impact-analysis`) found SUMO's
    keep-right rule badly unbalancing a MODERATE-demand multi-lane approach.
    Sweep lcKeepRight at three demand levels and report where it bites."""
    print("\n===== E: is lcKeepRight weak in general, or only at this demand? =====")
    seeds = tuple(1000 + 7 * i for i in range(nseed))
    rows = []
    for per_lane in (400.0, 800.0, 1600.0):
        ctx = dict(mainline_per_lane=per_lane)
        pl = []
        vals = [0.0, 1.0, 6.0]
        for v in vals:
            p = L.full_params(); p["lcKeepRight"] = v; pl.append(p)
        res = evaluate_runs(pl, seeds=seeds, ctx=ctx)
        sh0 = [r["share"][0] for r in res]
        rows.append(dict(per_lane=per_lane, lcKeepRight=vals,
                         share=[r["share"] for r in res],
                         share0_range=max(sh0) - min(sh0),
                         max_lane_share=[max(r["share"]) for r in res],
                         flow=[r["flow"] for r in res],
                         p85=[r["p85"] for r in res], dlc=[r["dlc"] for r in res]))
        print("  %6.0f veh/h/ln : share_lane0 at lcKeepRight 0/1/6 = %s "
              "(range %.4f);  max-lane share = %s"
              % (per_lane, ["%.4f" % x for x in sh0], max(sh0) - min(sh0),
                 ["%.4f" % max(r["share"]) for r in res]))
    noise = 2.0 * 1.96 * NOISE["share_lane0"]["sd"] / math.sqrt(nseed)
    print("  95%% noise band on a %d-seed share difference: %.4f" % (nseed, noise))
    out["E_keepright_by_demand"] = dict(rows=rows, seeds=list(seeds),
                                        share0_noise_band=noise)


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    out = json.load(open(OUTP)) if os.path.exists(OUTP) else {}
    if which in ("a", "all"):
        part_a(out)
    if which in ("b", "all"):
        part_b(out)
    if which in ("c", "all"):
        part_c(out)
    if which in ("d", "all"):
        part_d(out)
    if which in ("e", "all"):
        part_e(out)
    json.dump(out, open(OUTP, "w"), indent=2, default=str)
    print("\nwrote", OUTP)


if __name__ == "__main__":
    main()
