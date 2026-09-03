#!/usr/bin/env python3
"""H2 BANDWIDTH != DELAY.

Three offset sets on an IDENTICAL plan skeleton (same cycle, same phase
sequence, same green splits, same left-turn phasing -- only the seven offsets
differ, so the search spaces are exactly comparable):

  MAXBAND : analytic max-two-way-bandwidth offsets (equal-band objective),
            computed from geometry alone, zero simulation.
  TLSCOORD: SUMO's own tlsCoordinator.py, run with -a on the same plan and with
            --speed-factor set to the SAME calibrated progression speed the
            analytic search uses (fairness requirement).
  SILDELAY: simulation-in-the-loop offsets, coordinate-ascent directly on
            measured TOTAL time loss (with an incomplete-vehicle penalty),
            searched over the identical offset domain [0, C).

Swept over rising cross-street demand / saturation. Evaluated with CRN (the
same six demand+sim seed pairs for every arm). The SIL optimiser is trained on
seed 1 ONLY and then evaluated on all six seeds, so its reported advantage is
an out-of-sample number, not the value it optimised.
"""
import json
import multiprocessing as mp
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arterial_lib as A     # noqa: E402
import expbase as B          # noqa: E402
import runner as R           # noqa: E402
import scenario as S         # noqa: E402

L = 400.0                      # non-resonant base spacing
PENALTY = 200.0                # s of pseudo-delay per vehicle that never arrived

# (thru veh/h/dir, cross veh/h/approach, side veh/h/dir/intersection)
LEVELS = [("low",  800.0, 250.0, 60.0),
          ("base", 800.0, 350.0, 60.0),
          ("high", 900.0, 500.0, 60.0),
          ("sat",  1000.0, 650.0, 60.0)]


def obj_one(offs=None, seed=None, lvl=None, tag=None, cand=None):
    _, thru, cross, side = lvl
    sc = S.get(L=L, seed=seed, thru=thru, cross=cross, side=side)
    p = B.plan(offs=offs)
    d = os.path.join(B.WORK, "h2", "%s_%s_s%d" % (lvl[0], tag, seed))
    res = R.evaluate(sc, p, d, seed=seed, warm=B.WARM, fcd=True)
    st = res["stats"]
    incomplete = max(0.0, res["inserted"] - res["arrived"])
    return dict(lvl=lvl[0], tag=tag, seed=seed, cand=cand,
                obj=st["all"]["total_timeLoss"] + PENALTY * incomplete,
                total_tl=st["all"]["total_timeLoss"],
                mean_tl=st["all"]["timeLoss"], n_all=st["all"]["n"],
                tl_thruE=st["thruE"]["timeLoss"], tl_thruW=st["thruW"]["timeLoss"],
                tl_cross=st["cross"]["timeLoss"],
                tl_artleft=st.get("artleft", {}).get("timeLoss"),
                stops_thruE=st["thruE"]["stops"], stops_thruW=st["thruW"]["stops"],
                zeroEB=res["meas"]["EB"]["zero_frac"],
                zeroWB=res["meas"]["WB"]["zero_frac"],
                bandEB=res["meas"]["EB"]["band_meas"],
                bandWB=res["meas"]["WB"]["band_meas"],
                loaded=res["loaded"], inserted=res["inserted"],
                arrived=res["arrived"], running=res["still_running"],
                incomplete=incomplete, teleports=res["n_teleport_events"],
                tele_share=st["all"]["tele"])


def sil_optimise(lvl, start, grid_step=6.0, sweeps=3, train_seed=1, pool=None):
    """Coordinate ascent on measured total delay. Identical [0,C) offset domain."""
    C = B.C0
    cands = [k * grid_step for k in range(int(round(C / grid_step)))]
    o = [0.0] + [x % C for x in start[1:]]
    hist = []
    cur = obj_one(offs=o, seed=train_seed, lvl=lvl, tag="silp_start")["obj"]
    hist.append(dict(step=0, sig=-1, best=cur, offs=list(o)))
    for sw in range(sweeps):
        improved = False
        for i in range(1, B.N_INT):
            trials = []
            for c in cands:
                oo = list(o)
                oo[i] = c
                # UNIQUE outdir per trial: parallel workers must not share
                # tripinfo/summary/fcd paths.
                trials.append(dict(offs=oo, seed=train_seed, lvl=lvl,
                                   cand=c, tag="silp_i%d_c%03d" % (i, int(c))))
            res = pool.map(_wrap, trials)
            best = min(res, key=lambda r: r["obj"])
            if best["obj"] < cur - 1e-9:
                cur = best["obj"]
                o[i] = float(best["cand"])
                improved = True
            hist.append(dict(step=len(hist), sweep=sw, sig=i, best=cur,
                             offs=list(o)))
        if not improved:
            break
    return o, cur, hist


def _wrap(kw):
    return obj_one(**kw)


def main():
    lookup = {}
    xs = [i * L for i in range(B.N_INT)]
    p0 = B.plan()
    o_max, bE, bW = A.maxband(p0, xs, B.VPROG, objective="min", restarts=20, seed=11)
    print("MAXBAND offsets", [round(x, 2) for x in o_max], "b=%.2f/%.2f" % (bE, bW))

    rows, offsets_used, sil_hist = [], {}, {}
    for lvl in LEVELS:
        name, thru, cross, side = lvl
        for seed in B.SEEDS:
            S.get(L=L, seed=seed, thru=thru, cross=cross, side=side)
        sc = S.get(L=L, seed=1, thru=thru, cross=cross, side=side)
        nt = R.net_of(sc)
        d = os.path.join(B.WORK, "h2", "plans_%s" % name)
        os.makedirs(d, exist_ok=True)
        base_add = B.plan().write_add(nt, os.path.join(d, "skeleton.add.xml"))
        _, o_coord = S.coordinate_plan(sc, base_add, d,
                                       speed_factor=B.VPROG / B.VLIMIT)
        print("%-5s tlsCoordinator offsets %s" % (name, [round(x, 2) for x in o_coord]))
        pc = B.plan(offs=o_coord)
        cE, _ = A.band(pc, xs, B.VPROG, "EB")
        cW, _ = A.band(pc, xs, B.VPROG, "WB")
        with mp.Pool(B.NPROC) as pool:
            o_sil, best, hist = sil_optimise(lvl, o_max, pool=pool)
        ps = B.plan(offs=o_sil)
        sE, _ = A.band(ps, xs, B.VPROG, "EB")
        sW, _ = A.band(ps, xs, B.VPROG, "WB")
        print("%-5s SIL offsets %s  train-obj %.0f" % (name, [round(x, 1) for x in o_sil], best))
        offsets_used[name] = dict(maxband=o_max, tlscoord=o_coord, sil=o_sil,
                                  band_maxband=[bE, bW], band_tlscoord=[cE, cW],
                                  band_sil=[sE, sW])
        sil_hist[name] = hist
        jobs = []
        for tag, offs in (("maxband", o_max), ("tlscoord", o_coord),
                          ("sil", o_sil), ("uncoord", [0.0] * B.N_INT)):
            for seed in B.SEEDS:
                jobs.append(dict(offs=offs, seed=seed, lvl=lvl, tag=tag))
        rows += B.pmap(obj_one, jobs)
        bad = [r for r in rows if "error" in r]
        if bad:
            print(bad[0]["tb"][:3000])
            raise SystemExit(1)
    A.write_csv(os.path.join(B.DATA, "h2_raw.csv"), rows)
    json.dump(offsets_used, open(os.path.join(B.DATA, "h2_offsets.json"), "w"),
              indent=1)
    json.dump(sil_hist, open(os.path.join(B.DATA, "h2_sil_history.json"), "w"),
              indent=1)

    agg = []
    for lvl in LEVELS:
        name = lvl[0]
        arms = {}
        for tag in ("maxband", "tlscoord", "sil", "uncoord"):
            g = sorted([r for r in rows if r["lvl"] == name and r["tag"] == tag],
                       key=lambda r: r["seed"])
            arms[tag] = g
            row = dict(lvl=name, tag=tag, n_rep=len(g),
                       band_EB=offsets_used[name]["band_" +
                                                  ("maxband" if tag == "maxband"
                                                   else "tlscoord" if tag == "tlscoord"
                                                   else "sil")][0]
                       if tag != "uncoord" else None,
                       band_WB=offsets_used[name]["band_" +
                                                  ("maxband" if tag == "maxband"
                                                   else "tlscoord" if tag == "tlscoord"
                                                   else "sil")][1]
                       if tag != "uncoord" else None)
            for f in ("total_tl", "mean_tl", "tl_thruE", "tl_thruW", "tl_cross",
                      "tl_artleft", "zeroEB", "zeroWB", "bandEB", "bandWB",
                      "stops_thruE", "stops_thruW"):
                m, hw, sd, n = A.tconf([r[f] for r in g])
                row[f], row[f + "_hw"] = m, hw
            row["teleports"] = sum(r["teleports"] for r in g)
            row["tele_share_max"] = max(r["tele_share"] for r in g)
            row["incomplete_max"] = max(r["incomplete"] for r in g)
            row["completed_min"] = min(r["arrived"] / r["inserted"] for r in g)
            agg.append(row)
        # paired MAXBAND-vs-SIL delay penalty (the headline H2 number)
        for a, b in (("sil", "maxband"), ("sil", "tlscoord"),
                     ("uncoord", "maxband"), ("uncoord", "sil")):
            d = A.paired([r["total_tl"] for r in arms[a]],
                         [r["total_tl"] for r in arms[b]])
            base = sum(r["total_tl"] for r in arms[a]) / len(arms[a])
            agg.append(dict(lvl=name, tag="DIFF %s-minus-%s" % (b, a),
                            total_tl=d["mean"], total_tl_hw=d["hw"],
                            mean_tl=100.0 * d["mean"] / base, n_rep=d["n"],
                            zeroEB=d["p"], zeroWB=d["corr"]))
    A.write_csv(os.path.join(B.DATA, "h2_agg.csv"), agg)
    print("H2 done")


if __name__ == "__main__":
    main()
