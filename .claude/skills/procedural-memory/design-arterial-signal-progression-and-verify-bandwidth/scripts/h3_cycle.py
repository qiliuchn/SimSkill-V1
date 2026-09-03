#!/usr/bin/env python3
"""H3 CYCLE LENGTH - the bandwidth-optimal cycle is not the delay-optimal cycle.

Sweeps the cycle length with the green-time SHARES held constant (so this is a
pure cycle experiment, not a covert split experiment), at two spacings:
  L = 400 m  (non-resonant at C=90; its own resonant cycles are 2L/(v n))
  L = 585 m  (resonant at C=90)

At each cycle: analytic MAXBAND two-way band b (absolute) and efficiency b/C,
plus simulated delay under that same MAXBAND plan, CRN over six seeds.
Also records SUMO's own Webster answer from tlsCycleAdaptation --unified-cycle
as an independent delay-oriented cycle reference.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arterial_lib as A     # noqa: E402
import expbase as B          # noqa: E402
import runner as R           # noqa: E402
import scenario as S         # noqa: E402

CYCLES_ANA = [float(c) for c in range(40, 161, 5)]
CYCLES_SIM = [40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0, 110.0, 120.0, 140.0, 160.0]
SPACINGS = [400.0, 585.0]


def ana(L, C):
    gX, gL = B.scaled_split(C)
    p = B.plan(C=C, gX=gX, gL=gL)
    xs = [i * L for i in range(B.N_INT)]
    o, bE, bW = A.maxband(p, xs, B.VPROG, objective="min", restarts=12, seed=5)
    return dict(L=L, C=C, gT=p.gT, gX=gX, gL=gL, b=min(bE, bW), b_in=bE,
                b_out=bW, eff=min(bE, bW) / C, attain=min(bE, bW) / p.gT,
                twoL_over_vC=2 * L / (B.VPROG * C), offs=[round(x, 3) for x in o])


def sim_one(L=None, C=None, seed=None, offs=None, tag="maxband"):
    sc = S.get(L=L, seed=seed, thru=B.THRU0, cross=B.CROSS0, side=B.SIDE0)
    gX, gL = B.scaled_split(C)
    p = B.plan(C=C, gX=gX, gL=gL, offs=offs)
    d = os.path.join(B.WORK, "h3", "L%d_C%d_%s_s%d" % (L, C, tag, seed))
    res = R.evaluate(sc, p, d, seed=seed, warm=B.WARM, fcd=True)
    st, m = res["stats"], res["meas"]
    return dict(L=L, C=C, seed=seed, tag=tag,
                total_tl=st["all"]["total_timeLoss"], mean_tl=st["all"]["timeLoss"],
                tl_thruE=st["thruE"]["timeLoss"], tl_thruW=st["thruW"]["timeLoss"],
                tl_cross=st["cross"]["timeLoss"],
                stops_all=st["all"]["stops"],
                zeroEB=m["EB"]["zero_frac"], zeroWB=m["WB"]["zero_frac"],
                bandEB=m["EB"]["band_meas"], bandWB=m["WB"]["band_meas"],
                loaded=res["loaded"], inserted=res["inserted"],
                arrived=res["arrived"], running=res["still_running"],
                teleports=res["n_teleport_events"], tele_share=st["all"]["tele"])


def main():
    rows_a = [ana(L, C) for L in SPACINGS for C in CYCLES_ANA]
    A.write_csv(os.path.join(B.DATA, "h3_analytic.csv"),
                [{k: v for k, v in r.items() if k != "offs"} for r in rows_a])
    json.dump(rows_a, open(os.path.join(B.DATA, "h3_analytic_full.json"), "w"),
              indent=1)
    lut = {(r["L"], r["C"]): r for r in rows_a}
    for L in SPACINGS:
        for C in CYCLES_SIM:
            if (L, C) not in lut:
                lut[(L, C)] = ana(L, C)
    jobs = []
    for L in SPACINGS:
        for seed in B.SEEDS:
            S.get(L=L, seed=seed, thru=B.THRU0, cross=B.CROSS0, side=B.SIDE0)
        for C in CYCLES_SIM:
            for seed in B.SEEDS:
                jobs.append(dict(L=L, C=C, seed=seed, offs=lut[(L, C)]["offs"]))
    print("running %d simulations" % len(jobs))
    rows = B.pmap(sim_one, jobs)
    bad = [r for r in rows if "error" in r]
    if bad:
        print(bad[0]["tb"][:3000])
        raise SystemExit(1)
    A.write_csv(os.path.join(B.DATA, "h3_sim_raw.csv"), rows)

    agg = []
    for L in SPACINGS:
        for C in CYCLES_SIM:
            g = sorted([r for r in rows if r["L"] == L and r["C"] == C],
                       key=lambda r: r["seed"])
            row = dict(L=L, C=C, n_rep=len(g), b=lut[(L, C)]["b"],
                       eff=lut[(L, C)]["eff"], attain=lut[(L, C)]["attain"])
            for f in ("total_tl", "mean_tl", "tl_thruE", "tl_thruW", "tl_cross",
                      "stops_all", "zeroEB", "zeroWB", "bandEB", "bandWB"):
                m, hw, sd, n = A.tconf([r[f] for r in g])
                row[f], row[f + "_hw"] = m, hw
            row["teleports"] = sum(r["teleports"] for r in g)
            row["tele_share_max"] = max(r["tele_share"] for r in g)
            row["completed_min"] = min(r["arrived"] / r["inserted"] for r in g)
            agg.append(row)
    A.write_csv(os.path.join(B.DATA, "h3_agg.csv"), agg)

    # SUMO's own Webster/unified-cycle answer as an independent reference
    ref = {}
    for L in SPACINGS:
        sc = S.get(L=L, seed=1, thru=B.THRU0, cross=B.CROSS0, side=B.SIDE0)
        cyc, off = S.tls_tools(sc, os.path.join(B.WORK, "h3", "webster_L%d" % L),
                               min_cycle=20, max_cycle=160, begin=B.WARM)
        pg = A.load_programs([sc["net"], cyc])
        cycles = sorted(set(round(sum(d for d, _ in pg["J%d" % i][1]), 2)
                            for i in range(B.N_INT)))
        ref["L%d" % L] = dict(unified_cycles_found=cycles,
                              unified=len(cycles) == 1,
                              webster_cycle=cycles[0] if len(cycles) == 1 else None,
                              cycles_add=cyc, offsets_add=off)
    json.dump(ref, open(os.path.join(B.DATA, "h3_webster_reference.json"), "w"),
              indent=1)
    print("H3 done", ref)


if __name__ == "__main__":
    main()
