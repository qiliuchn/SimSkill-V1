#!/usr/bin/env python3
"""H1 RESONANCE - two-way progression quality is PERIODIC in block spacing L.

Layer (a) ANALYTIC: at each spacing L, a MAXBAND-style search for the offset
vector maximising the equal two-way band, giving b_in / b_out, b/C efficiency
and attainability b / gT (fraction of the physically available through green).
Swept at three cycle lengths so that MULTIPLE resonant peaks fall inside the
mandated 150-800 m window:
      C = 45 s -> resonances at L = n*v*C/2 = 292.5, 585   m
      C = 60 s ->                              390,  780   m
      C = 90 s ->                              585          m

Layer (b) MEASURED: per-direction zero-stop fraction and empirical arrival-
phase window from FCD, under the analytic MAXBAND plan, with CRN replication.

Layer (c) DELAY: tripinfo time loss / stops.

Peak sharpness is quantified two ways: the analytic slope d b / d L near the
global peak (compared against the closed-form prediction -(n-1)/v s per m) and
the spacing error that costs half the band.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arterial_lib as A     # noqa: E402
import expbase as B          # noqa: E402
import runner as R           # noqa: E402
import scenario as S         # noqa: E402

CYCLES = [45.0, 60.0, 90.0]
SIM_L = [150, 200, 250, 300, 350, 400, 450, 500, 550, 560, 585, 610,
         650, 700, 750, 800]
SIM_L_C60 = [195, 390, 585, 780]          # trough, peak, trough, peak at C=60


def analytic_row(L, C=B.C0):
    gX, gL = B.scaled_split(C)
    p = B.plan(C=C, gX=gX, gL=gL)
    xs = [i * L for i in range(B.N_INT)]
    o_min, bE, bW = A.maxband(p, xs, B.VPROG, objective="min", restarts=14, seed=7)
    o_sum, sE, sW = A.maxband(p, xs, B.VPROG, objective="sum", restarts=14, seed=7)
    p.offs = [0.0] * B.N_INT
    uE, uW = A.two_way(p, xs, B.VPROG)
    T = L / B.VPROG
    delta = (2 * T) % C
    if delta > C / 2:
        delta -= C
    pred = max(0.0, p.gT - (B.N_INT - 1) * abs(delta) / 2.0)
    return dict(L=L, cycle=C, gT=round(p.gT, 3), v=B.VPROG,
                twoL_over_vC=2 * L / (B.VPROG * C),
                detuning_delta_s=round(delta, 4),
                b_two_way=min(bE, bW), b_in=bE, b_out=bW,
                b_two_way_closedform=round(pred, 3),
                eff_two_way=min(bE, bW) / C,
                attainability=min(bE, bW) / p.gT,
                b_sum_EB=sE, b_sum_WB=sW, b_sum_total=sE + sW,
                b_uncoord_EB=uE, b_uncoord_WB=uW,
                offs_min=[round(x, 3) for x in o_min],
                offs_sum=[round(x, 3) for x in o_sum])


def sim_one(L=None, seed=None, offs=None, tag=None, C=B.C0):
    sc = S.get(L=float(L), seed=seed, thru=B.THRU0, cross=B.CROSS0, side=B.SIDE0)
    gX, gL = B.scaled_split(C)
    p = B.plan(C=C, gX=gX, gL=gL, offs=offs)
    d = os.path.join(B.WORK, "h1", "C%d_L%d_%s_s%d" % (C, L, tag, seed))
    res = R.evaluate(sc, p, d, seed=seed, warm=B.WARM, fcd=True)
    st, m = res["stats"], res["meas"]
    return dict(L=L, C=C, seed=seed, tag=tag,
                zeroEB=m["EB"]["zero_frac"], zeroWB=m["WB"]["zero_frac"],
                bandEB=m["EB"]["band_meas"], bandWB=m["WB"]["band_meas"],
                nEB=m["EB"]["n"], nWB=m["WB"]["n"],
                ttEB=m["EB"]["tt"], ttWB=m["WB"]["tt"],
                stopsEB=m["EB"]["stops"], stopsWB=m["WB"]["stops"],
                tl_thruE=st.get("thruE", {}).get("timeLoss"),
                tl_thruW=st.get("thruW", {}).get("timeLoss"),
                tl_all=st["all"]["timeLoss"], tot_tl=st["all"]["total_timeLoss"],
                n_all=st["all"]["n"],
                loaded=res["loaded"], inserted=res["inserted"],
                arrived=res["arrived"], running=res["still_running"],
                teleports=res["n_teleport_events"],
                tele_share=st["all"]["tele"],
                fcd_missing=len(res["fcd_edges_missing"]))


def agg_block(rows, keys, tags, extra=None):
    out = []
    for k in keys:
        for tag in tags:
            g = sorted([r for r in rows if (r["L"], r["C"]) == k
                        and r["tag"] == tag], key=lambda r: r["seed"])
            if not g:
                continue
            row = dict(L=k[0], C=k[1], tag=tag, n_rep=len(g))
            for f in ("zeroEB", "zeroWB", "bandEB", "bandWB", "tl_thruE",
                      "tl_thruW", "tl_all", "ttEB", "ttWB", "stopsEB", "stopsWB"):
                m, hw, sd, n = A.tconf([r[f] for r in g])
                row[f], row[f + "_hw"] = m, hw
            d = A.paired([r["zeroWB"] for r in g], [r["zeroEB"] for r in g])
            row["zero_EBminusWB"] = d["mean"]
            row["zero_EBminusWB_hw"] = d["hw"]
            row["zero_EBminusWB_p"] = d["p"]
            row["teleports"] = sum(r["teleports"] for r in g)
            row["tele_share_max"] = max(r["tele_share"] for r in g)
            row["completed_min"] = min(r["arrived"] / r["inserted"] for r in g)
            row["running_max"] = max(r["running"] for r in g)
            row["fcd_missing_max"] = max(r["fcd_missing"] for r in g)
            if extra:
                row.update(extra.get(k, {}))
            out.append(row)
    return out


def main():
    # ---------------- layer (a): analytic sweeps -----------------------------
    ana = []
    for C in CYCLES:
        Ls = list(range(150, 801, 5))
        for L in Ls:
            ana.append(analytic_row(float(L), C))
        print("analytic C=%.0f done" % C)
    A.write_csv(os.path.join(B.DATA, "h1_analytic.csv"),
                [{k: v for k, v in r.items() if not k.startswith("offs")}
                 for r in ana])
    json.dump(ana, open(os.path.join(B.DATA, "h1_analytic_full.json"), "w"),
              indent=1)

    # ---------------- peak sharpness (1 m resolution around L=585, C=90) -----
    sharp = [analytic_row(float(L), 90.0) for L in range(555, 616)]
    A.write_csv(os.path.join(B.DATA, "h1_peak_sharpness.csv"),
                [{k: v for k, v in r.items() if not k.startswith("offs")}
                 for r in sharp])

    # ---------------- layers (b)+(c): simulation -----------------------------
    lookup = {(r["L"], r["cycle"]): r for r in ana}
    lookup.update({(r["L"], r["cycle"]): r for r in sharp})
    jobs, keys90, keys60 = [], [], []
    for L in SIM_L:
        if (float(L), 90.0) not in lookup:
            lookup[(float(L), 90.0)] = analytic_row(float(L), 90.0)
        keys90.append((L, 90.0))
    for L in SIM_L_C60:
        if (float(L), 60.0) not in lookup:
            lookup[(float(L), 60.0)] = analytic_row(float(L), 60.0)
        keys60.append((L, 60.0))
    for (L, C) in keys90 + keys60:
        for seed in B.SEEDS:
            S.get(L=float(L), seed=seed, thru=B.THRU0, cross=B.CROSS0,
                  side=B.SIDE0)            # pre-build serially, avoid races
            jobs.append(dict(L=L, C=C, seed=seed, tag="maxband",
                             offs=lookup[(float(L), C)]["offs_min"]))
            jobs.append(dict(L=L, C=C, seed=seed, tag="uncoord",
                             offs=[0.0] * B.N_INT))
    print("running %d simulations" % len(jobs))
    rows = B.pmap(sim_one, jobs)
    bad = [r for r in rows if "error" in r]
    if bad:
        print("FAILED", bad[0]["tb"][:3000])
        raise SystemExit(1)
    A.write_csv(os.path.join(B.DATA, "h1_sim_raw.csv"), rows)

    extra = {k: dict(b_two_way_analytic=lookup[(float(k[0]), k[1])]["b_two_way"],
                     attain_analytic=lookup[(float(k[0]), k[1])]["attainability"],
                     b_sum_analytic=lookup[(float(k[0]), k[1])]["b_sum_total"])
             for k in keys90 + keys60}
    A.write_csv(os.path.join(B.DATA, "h1_sim_agg.csv"),
                agg_block(rows, keys90 + keys60, ("maxband", "uncoord"), extra))

    ben = []
    for k in keys90 + keys60:
        gm = sorted([r for r in rows if (r["L"], r["C"]) == k
                     and r["tag"] == "maxband"], key=lambda r: r["seed"])
        gu = sorted([r for r in rows if (r["L"], r["C"]) == k
                     and r["tag"] == "uncoord"], key=lambda r: r["seed"])
        a = lookup[(float(k[0]), k[1])]
        row = dict(L=k[0], C=k[1], b_two_way=a["b_two_way"],
                   eff=a["eff_two_way"], attain=a["attainability"],
                   detuning=a["detuning_delta_s"])
        for f, lab in (("zeroEB", "dzeroEB"), ("zeroWB", "dzeroWB"),
                       ("tl_thruE", "dtlE"), ("tl_thruW", "dtlW"),
                       ("tl_all", "dtl_all")):
            d = A.paired([r[f] for r in gu], [r[f] for r in gm])
            row[lab], row[lab + "_hw"] = d["mean"], d["hw"]
            row[lab + "_p"], row[lab + "_corr"] = d["p"], d["corr"]
        ben.append(row)
    A.write_csv(os.path.join(B.DATA, "h1_benefit.csv"), ben)
    print("H1 done")


if __name__ == "__main__":
    main()
