#!/usr/bin/env python3
"""Three-measurement-layer reconciliation + the annotated time-space diagrams.

Layers, on the SAME runs:
  (a) ANALYTIC  b_in / b_out / b/C / attainability, from offsets+splits+cycle+
      geometry alone (exact interval algebra modulo the cycle -- no simulation).
  (b) MEASURED  from FCD: per-direction zero-stop fraction of corridor-through
      vehicles and the empirical arrival-phase window that actually gets
      through.
  (c) DELAY     tripinfo time loss / stops / travel time, per cohort.

Cases: the analytic BEST (resonant L=585 m) and WORST (L=500 m) two-way spacings
at the design cycle, each coordinated (MAXBAND) and uncoordinated, plus the
one-way-favouring sum-optimal plan at the base spacing to show the
per-direction asymmetry a bandwidth-sum objective produces.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arterial_lib as A     # noqa: E402
import expbase as B          # noqa: E402
import plot_timespace as PT  # noqa: E402
import runner as R           # noqa: E402
import scenario as S         # noqa: E402

CASES = [
    ("best_resonant_coord", 585.0, "maxband"),
    ("best_resonant_uncoord", 585.0, "uncoord"),
    ("worst_detuned_coord", 500.0, "maxband"),
    ("worst_detuned_uncoord", 500.0, "uncoord"),
    ("base_oneway_sumopt", 400.0, "sumopt"),
    ("base_twoway_maxband", 400.0, "maxband"),
]


def offsets_for(L, kind):
    xs = [i * L for i in range(B.N_INT)]
    p = B.plan()
    if kind == "uncoord":
        return [0.0] * B.N_INT
    obj = "sum" if kind == "sumopt" else "min"
    o, bE, bW = A.maxband(p, xs, B.VPROG, objective=obj, restarts=20, seed=13)
    return o


def one(name, L, kind, seeds=B.SEEDS, make_plot=False):
    xs = [i * L for i in range(B.N_INT)]
    offs = offsets_for(L, kind)
    p = B.plan(offs=offs)
    bE, sE = A.band(p, xs, B.VPROG, "EB")
    bW, sW = A.band(p, xs, B.VPROG, "WB")
    out = dict(case=name, L=L, kind=kind, cycle=p.C, gT=p.gT,
               offsets=[round(x, 3) for x in offs],
               a_b_in=bE, a_b_out=bW, a_b_in_over_C=bE / p.C,
               a_b_out_over_C=bW / p.C,
               a_attain_in=bE / p.gT, a_attain_out=bW / p.gT,
               a_two_way=min(bE, bW), a_signed_in_minus_out=bE - bW)
    per = []
    for seed in seeds:
        sc = S.get(L=L, seed=seed, thru=B.THRU0, cross=B.CROSS0, side=B.SIDE0)
        d = os.path.join(B.WORK, "recon", "%s_s%d" % (name, seed))
        res = R.evaluate(sc, p, d, seed=seed, warm=B.WARM, fcd=True,
                         keep_fcd=(make_plot and seed == seeds[0]))
        st, m = res["stats"], res["meas"]
        per.append(dict(seed=seed, zeroEB=m["EB"]["zero_frac"],
                        zeroWB=m["WB"]["zero_frac"],
                        bandEB=m["EB"]["band_meas"], bandWB=m["WB"]["band_meas"],
                        band_cov_EB=m["EB"]["band_meas_coverage_adj"],
                        band_cov_WB=m["WB"]["band_meas_coverage_adj"],
                        nEB=m["EB"]["n"], nWB=m["WB"]["n"],
                        ttEB=m["EB"]["tt"], ttWB=m["WB"]["tt"],
                        stopsEB=m["EB"]["stops"], stopsWB=m["WB"]["stops"],
                        tri_zeroE=st["thruE"]["zero_stop"],
                        tri_zeroW=st["thruW"]["zero_stop"],
                        tri_stopsE=st["thruE"]["stops"],
                        tri_stopsW=st["thruW"]["stops"],
                        tl_thruE=st["thruE"]["timeLoss"],
                        tl_thruW=st["thruW"]["timeLoss"],
                        tl_cross=st["cross"]["timeLoss"],
                        tl_artleft=st.get("artleft", {}).get("timeLoss"),
                        mean_tl=st["all"]["timeLoss"],
                        total_tl=st["all"]["total_timeLoss"],
                        wait_thruE=st["thruE"]["waitingTime"],
                        wait_thruW=st["thruW"]["waitingTime"],
                        loaded=res["loaded"], inserted=res["inserted"],
                        arrived=res["arrived"], running=res["still_running"],
                        teleports=res["n_teleport_events"],
                        tele_share=st["all"]["tele"],
                        fcd_missing=len(res["fcd_edges_missing"]),
                        fcd=res.get("fcd")))
    for f in ("zeroEB", "zeroWB", "bandEB", "bandWB", "ttEB", "ttWB",
              "stopsEB", "stopsWB", "tri_zeroE", "tri_zeroW", "tri_stopsE",
              "tri_stopsW", "tl_thruE", "tl_thruW", "tl_cross",
              "mean_tl", "total_tl", "wait_thruE", "wait_thruW"):
        m, hw, sd, n = A.tconf([r[f] for r in per])
        out["m_" + f], out["m_" + f + "_hw"] = m, hw
    d = A.paired([r["zeroWB"] for r in per], [r["zeroEB"] for r in per])
    out["m_zero_signed_EBminusWB"] = d["mean"]
    out["m_zero_signed_hw"] = d["hw"]
    out["m_zero_signed_p"] = d["p"]
    out["teleports_total"] = sum(r["teleports"] for r in per)
    out["tele_share_max"] = max(r["tele_share"] for r in per)
    out["completed_share_min"] = min(r["arrived"] / r["inserted"] for r in per)
    out["still_running_max"] = max(r["running"] for r in per)
    out["fcd_missing_max"] = max(r["fcd_missing"] for r in per)
    out["n_thru_EB"] = per[0]["nEB"]
    out["n_thru_WB"] = per[0]["nWB"]
    return out, per, (sE, sW), p, xs


def main():
    rows, details = [], {}
    for name, L, kind in CASES:
        for seed in B.SEEDS:
            S.get(L=L, seed=seed, thru=B.THRU0, cross=B.CROSS0, side=B.SIDE0)
        out, per, bands, plan, xs = one(name, L, kind, make_plot=True)
        rows.append(out)
        details[name] = per
        fcd = per[0].get("fcd")
        ttl = ("%s   L=%.0f m, C=%.0f s, v=%.1f m/s   |   analytic band "
               "in=%.1f s out=%.1f s (b/C = %.2f / %.2f)   |   measured "
               "zero-stop EB=%.2f WB=%.2f"
               % (name, L, plan.C, B.VPROG, out["a_b_in"], out["a_b_out"],
                  out["a_b_in_over_C"], out["a_b_out_over_C"],
                  out["m_zeroEB"], out["m_zeroWB"]))
        PT.figure(plan, xs, fcd, os.path.join(B.FIG, "timespace_%s.png" % name),
                  ttl, B.VPROG, t0=1200.0, t1=1560.0, band=bands)
        if fcd and os.path.exists(fcd):
            os.remove(fcd)
        print("%-24s a_in=%5.1f a_out=%5.1f  meas zero %.3f/%.3f  band %.1f/%.1f"
              % (name, out["a_b_in"], out["a_b_out"], out["m_zeroEB"],
                 out["m_zeroWB"], out["m_bandEB"], out["m_bandWB"]))
    A.write_csv(os.path.join(B.DATA, "reconciliation.csv"), rows)
    json.dump(details, open(os.path.join(B.DATA, "reconciliation_perseed.json"),
                            "w"), indent=1, default=str)
    print("reconciliation done")


if __name__ == "__main__":
    main()
