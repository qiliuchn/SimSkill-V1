#!/usr/bin/env python3
"""H4 LEAD-LAG left-turn phasing recovers two-way band at non-resonant spacing.

Construction (see SignalPlan): lead-lead and lead-lag consume EXACTLY the same
arterial green time, give EXACTLY the same through-window width gT and EXACTLY
the same protected-left green gL per direction. The only difference is that
lead-lag displaces the two directions' through windows relative to each other
by delta = gL + yellow + all-red. That makes the per-signal phasing mode a
genuine extra degree of freedom for the two-way band problem, at zero green-time
cost -- so any band recovered is attributable to phase ORDER alone.

The cost shows up elsewhere: in lead-lag a left-turn movement runs adjacent to
its own through, so the left-turn queue's effective red is redistributed, and
the two directions' left turns no longer discharge concurrently.

Search: coordinate ascent over per-signal mode in {lead-lead, lead-lag,
lag-lead} with the offsets re-optimised (MAXBAND) inside each mode evaluation.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arterial_lib as A     # noqa: E402
import expbase as B          # noqa: E402
import runner as R           # noqa: E402
import scenario as S         # noqa: E402

MODES = ["lead-lead", "lead-lag", "lag-lead"]
SPACINGS = [200.0, 300.0, 400.0, 450.0, 500.0, 585.0, 700.0]
SIDE = 120.0             # raised left-turn demand: 60 veh/h per approach per int.


def best_offsets(modes, xs, restarts=10, seed=3):
    p = B.plan(modes=modes)
    o, bE, bW = A.maxband(p, xs, B.VPROG, objective="min", restarts=restarts,
                          seed=seed)
    return o, min(bE, bW), bE, bW


def search_modes(L, sweeps=3):
    xs = [i * L for i in range(B.N_INT)]
    modes = ["lead-lead"] * B.N_INT
    o, best, bE, bW = best_offsets(modes, xs)
    trace = [dict(step=0, modes=list(modes), b=best)]
    for sw in range(sweeps):
        improved = False
        for i in range(B.N_INT):
            cur_m = modes[i]
            for m in MODES:
                if m == cur_m:
                    continue
                trial = list(modes)
                trial[i] = m
                oo, b, e, w = best_offsets(trial, xs, restarts=6, seed=3)
                if b > best + 1e-6:
                    best, modes, o, bE, bW = b, trial, oo, e, w
                    improved = True
                    cur_m = m
            trace.append(dict(step=len(trace), sig=i, modes=list(modes), b=best))
        if not improved:
            break
    return modes, o, best, bE, bW, trace


def sim_one(L=None, seed=None, modes=None, offs=None, tag=None):
    sc = S.get(L=L, seed=seed, thru=B.THRU0, cross=B.CROSS0, side=SIDE)
    p = B.plan(modes=modes, offs=offs)
    d = os.path.join(B.WORK, "h4", "L%d_%s_s%d" % (L, tag, seed))
    res = R.evaluate(sc, p, d, seed=seed, warm=B.WARM, fcd=True)
    st, m = res["stats"], res["meas"]
    return dict(L=L, seed=seed, tag=tag,
                zeroEB=m["EB"]["zero_frac"], zeroWB=m["WB"]["zero_frac"],
                bandEB=m["EB"]["band_meas"], bandWB=m["WB"]["band_meas"],
                tl_thruE=st["thruE"]["timeLoss"], tl_thruW=st["thruW"]["timeLoss"],
                tl_artleft=st["artleft"]["timeLoss"],
                stops_artleft=st["artleft"]["stops"],
                n_artleft=st["artleft"]["n"],
                tl_artright=st["artright"]["timeLoss"],
                tl_cross=st["cross"]["timeLoss"],
                total_tl=st["all"]["total_timeLoss"], mean_tl=st["all"]["timeLoss"],
                loaded=res["loaded"], inserted=res["inserted"],
                arrived=res["arrived"], running=res["still_running"],
                teleports=res["n_teleport_events"], tele_share=st["all"]["tele"])


def main():
    ana, plans, traces = [], {}, {}
    for L in SPACINGS:
        xs = [i * L for i in range(B.N_INT)]
        o_ll, b_ll, e_ll, w_ll = best_offsets(["lead-lead"] * B.N_INT, xs,
                                              restarts=14, seed=3)
        modes, o_lx, b_lx, e_lx, w_lx, trace = search_modes(L)
        p = B.plan()
        ana.append(dict(L=L, gT=p.gT, delta_shift=p.delta,
                        b_leadlead=b_ll, b_in_leadlead=e_ll, b_out_leadlead=w_ll,
                        b_best=b_lx, b_in_best=e_lx, b_out_best=w_lx,
                        gain_s=b_lx - b_ll,
                        gain_pct=100.0 * (b_lx - b_ll) / max(b_ll, 1e-9),
                        attain_leadlead=b_ll / p.gT, attain_best=b_lx / p.gT,
                        modes_best=",".join(modes),
                        n_nonleadlead=sum(1 for m in modes if m != "lead-lead")))
        traces[str(L)] = trace
        plans[L] = dict(leadlead=dict(modes=["lead-lead"] * B.N_INT, offs=o_ll),
                        best=dict(modes=modes, offs=o_lx))
        print("L=%3.0f  lead-lead b=%5.2f -> best b=%5.2f  modes=%s"
              % (L, b_ll, b_lx, modes))
    A.write_csv(os.path.join(B.DATA, "h4_analytic.csv"), ana)
    json.dump(traces, open(os.path.join(B.DATA, "h4_mode_search_trace.json"),
                           "w"), indent=1)
    json.dump({str(k): v for k, v in plans.items()},
              open(os.path.join(B.DATA, "h4_plans.json"), "w"), indent=1)

    jobs = []
    for L in SPACINGS:
        for seed in B.SEEDS:
            S.get(L=L, seed=seed, thru=B.THRU0, cross=B.CROSS0, side=SIDE)
            for tag in ("leadlead", "best"):
                jobs.append(dict(L=L, seed=seed, tag=tag,
                                 modes=plans[L][tag]["modes"],
                                 offs=plans[L][tag]["offs"]))
    print("running %d simulations" % len(jobs))
    rows = B.pmap(sim_one, jobs)
    bad = [r for r in rows if "error" in r]
    if bad:
        print(bad[0]["tb"][:3000])
        raise SystemExit(1)
    A.write_csv(os.path.join(B.DATA, "h4_sim_raw.csv"), rows)

    agg = []
    for L in SPACINGS:
        arms = {}
        for tag in ("leadlead", "best"):
            g = sorted([r for r in rows if r["L"] == L and r["tag"] == tag],
                       key=lambda r: r["seed"])
            arms[tag] = g
            row = dict(L=L, tag=tag, n_rep=len(g))
            for f in ("zeroEB", "zeroWB", "bandEB", "bandWB", "tl_thruE",
                      "tl_thruW", "tl_artleft", "stops_artleft", "tl_artright",
                      "tl_cross", "mean_tl", "total_tl"):
                m, hw, sd, n = A.tconf([r[f] for r in g])
                row[f], row[f + "_hw"] = m, hw
            row["teleports"] = sum(r["teleports"] for r in g)
            row["completed_min"] = min(r["arrived"] / r["inserted"] for r in g)
            agg.append(row)
        for f in ("zeroEB", "zeroWB", "tl_thruE", "tl_thruW", "tl_artleft",
                  "tl_cross", "total_tl", "mean_tl"):
            d = A.paired([r[f] for r in arms["leadlead"]],
                         [r[f] for r in arms["best"]])
            agg.append(dict(L=L, tag="DIFF best-minus-leadlead:" + f,
                            n_rep=d["n"], zeroEB=d["mean"], zeroEB_hw=d["hw"],
                            zeroWB=d["p"], bandEB=d["corr"]))
    A.write_csv(os.path.join(B.DATA, "h4_agg.csv"), agg)
    print("H4 done")


if __name__ == "__main__":
    main()
