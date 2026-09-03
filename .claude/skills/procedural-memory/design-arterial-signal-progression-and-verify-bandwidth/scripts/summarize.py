#!/usr/bin/env python3
"""Print every headline number the FINDINGS report quotes, straight from the
CSV/JSON artefacts in data/, so nothing in the report is hand-transcribed."""
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import expbase as B     # noqa: E402


def rd(n):
    p = os.path.join(B.DATA, n)
    if not os.path.exists(p):
        print("MISSING", n)
        return []
    out = []
    for r in csv.DictReader(open(p)):
        d = {}
        for k, v in r.items():
            try:
                d[k] = float(v) if v not in ("", "None") else None
            except (ValueError, TypeError):
                d[k] = v
        out.append(d)
    return out


def js(n):
    p = os.path.join(B.DATA, n)
    return json.load(open(p)) if os.path.exists(p) else None


def hdr(t):
    print("\n" + "=" * 78 + "\n" + t + "\n" + "=" * 78)


def main():
    hdr("VERIFICATION")
    v = js("verify_offsets.json")
    if v:
        print("offset convention all_signals_pass:", v["all_signals_pass"])
        for j, d in v["signals"].items():
            print("  %s off=%7.2f err_minus=%.2f err_plus=%.2f discriminating=%s"
                  % (j, d["offset_written"], d["max_err_minus_s"],
                     d["max_err_plus_s"], d["discriminating"]))
    print("speed calibration:", js("speed_calibration.json"))
    w = js("h3_webster_reference.json")
    print("tlsCycleAdaptation --unified-cycle:", json.dumps(w, indent=1)
          if w else "n/a")

    hdr("RECONCILIATION (3 layers)")
    for r in rd("reconciliation.csv"):
        print("%-24s L=%4.0f  ANALYTIC in=%5.2f out=%5.2f b/C=%.3f/%.3f "
              "attain=%.3f/%.3f | MEASURED zero=%.3f/%.3f band=%.1f/%.1f | "
              "DELAY thruE=%.1f thruW=%.1f cross=%.1f all=%.1f | tele=%d "
              "compl=%.4f"
              % (r["case"], r["L"], r["a_b_in"], r["a_b_out"],
                 r["a_b_in_over_C"], r["a_b_out_over_C"], r["a_attain_in"],
                 r["a_attain_out"], r["m_zeroEB"], r["m_zeroWB"],
                 r["m_bandEB"], r["m_bandWB"], r["m_tl_thruE"],
                 r["m_tl_thruW"], r["m_tl_cross"], r["m_mean_tl"],
                 r["teleports_total"], r["completed_share_min"]))
        print("      FCD-based (J0->J6 interior) zero-stop %.3f/%.3f vs "
              "tripinfo-whole-trip zero-stop %.3f/%.3f ; FCD stops %.2f/%.2f "
              "vs tripinfo waitingCount %.2f/%.2f"
              % (r["m_zeroEB"], r["m_zeroWB"], r["m_tri_zeroE"],
                 r["m_tri_zeroW"], r["m_stopsEB"], r["m_stopsWB"],
                 r["m_tri_stopsE"], r["m_tri_stopsW"]))
        print("      signed EB-WB zero-stop diff %+.4f +/- %.4f (p=%.4g); "
              "analytic signed in-out %+.2f s"
              % (r["m_zero_signed_EBminusWB"], r["m_zero_signed_hw"],
                 r["m_zero_signed_p"], r["a_signed_in_minus_out"]))

    hdr("H1 RESONANCE")
    a = rd("h1_analytic.csv")
    for C in (45.0, 60.0, 90.0):
        g = sorted([r for r in a if r["cycle"] == C], key=lambda r: -r["b_two_way"])
        pk = [(r["L"], round(r["b_two_way"], 2), round(r["attainability"], 3))
              for r in g[:4]]
        print("C=%3.0f gT=%.1f  predicted resonances L=n*v*C/2:" % (C, g[0]["gT"]),
              [round(n * B.VPROG * C / 2, 1) for n in (1, 2)],
              " top analytic spacings:", pk)
    sh = sorted(rd("h1_peak_sharpness.csv"), key=lambda r: r["L"])
    if sh:
        pk = max(sh, key=lambda r: r["b_two_way"])
        sl = [(r["L"], r["b_two_way"]) for r in sh]
        lo = [x for x in sl if x[0] == pk["L"] - 25][0]
        print("peak L=%.0f b=%.2f ; at L=%.0f b=%.2f -> slope %.4f s band per m"
              % (pk["L"], pk["b_two_way"], lo[0], lo[1],
                 (pk["b_two_way"] - lo[1]) / 25.0))
        print("closed-form slope prediction (n-1)/v = %.4f" % (6.0 / B.VPROG))
        half = [x for x in sl if x[1] <= pk["b_two_way"] / 2 and x[0] > pk["L"]]
        print("spacing error that halves the band:",
              (half[0][0] - pk["L"]) if half else ">30 m (not reached in window)")
    for r in sorted(rd("h1_benefit.csv"), key=lambda r: (r["C"], r["L"])):
        print("C=%3.0f L=%4.0f b=%5.2f attain=%.3f | benefit dzeroEB=%+.3f+/-%.3f "
              "(p=%.3g,r=%.2f) dzeroWB=%+.3f+/-%.3f | dtlE=%+.2f+/-%.2f "
              "dtlW=%+.2f+/-%.2f dtl_all=%+.2f+/-%.2f"
              % (r["C"], r["L"], r["b_two_way"], r["attain"], r["dzeroEB"],
                 r["dzeroEB_hw"], r["dzeroEB_p"], r["dzeroEB_corr"],
                 r["dzeroWB"], r["dzeroWB_hw"], r["dtlE"], r["dtlE_hw"],
                 r["dtlW"], r["dtlW_hw"], r["dtl_all"], r["dtl_all_hw"]))
    # correlation between analytic band and measured zero-stop
    s = [r for r in rd("h1_sim_agg.csv") if r["tag"] == "maxband"]
    if s:
        try:
            from scipy import stats as sps
            x = [r["b_two_way_analytic"] for r in s]
            y = [(r["zeroEB"] + r["zeroWB"]) / 2 for r in s]
            print("corr(analytic two-way band, measured mean zero-stop) = %.3f "
                  "(n=%d, p=%.3g)" % (sps.pearsonr(x, y).statistic, len(x),
                                      sps.pearsonr(x, y).pvalue))
        except Exception as e:
            print("corr failed", e)

    hdr("H2 BANDWIDTH != DELAY")
    off = js("h2_offsets.json")
    if off:
        for k, v2 in off.items():
            print("%-5s maxband=%s\n      tlscoord=%s\n      sil=%s\n"
                  "      analytic band  maxband=%s tlscoord=%s sil=%s"
                  % (k, [round(x, 1) for x in v2["maxband"]],
                     [round(x, 1) for x in v2["tlscoord"]],
                     [round(x, 1) for x in v2["sil"]],
                     [round(x, 2) for x in v2["band_maxband"]],
                     [round(x, 2) for x in v2["band_tlscoord"]],
                     [round(x, 2) for x in v2["band_sil"]]))
    for r in rd("h2_agg.csv"):
        if isinstance(r["tag"], str) and r["tag"].startswith("DIFF"):
            print("%-5s %-28s  d_total_tl=%+9.1f +/- %8.1f s  (%+.2f%%) "
                  "p=%.3g r=%.2f"
                  % (r["lvl"], r["tag"], r["total_tl"], r["total_tl_hw"],
                     r["mean_tl"], r["zeroEB"], r["zeroWB"]))
        else:
            print("%-5s %-9s total_tl=%9.1f+/-%7.1f mean_tl=%5.2f zeroEB=%.3f "
                  "zeroWB=%.3f tl_cross=%5.2f tl_left=%s tele=%d compl=%.4f"
                  % (r["lvl"], r["tag"], r["total_tl"], r["total_tl_hw"],
                     r["mean_tl"], r["zeroEB"], r["zeroWB"], r["tl_cross"],
                     ("%.2f" % r["tl_artleft"]) if r["tl_artleft"] else "na",
                     r["teleports"] or 0, r["completed_min"]))

    hdr("H3 CYCLE LENGTH")
    ag = rd("h3_agg.csv")
    for L in sorted(set(r["L"] for r in ag)):
        g = sorted([r for r in ag if r["L"] == L], key=lambda r: r["C"])
        bo = max(g, key=lambda r: r["b"])
        eo = max(g, key=lambda r: r["eff"])
        do = min(g, key=lambda r: r["mean_tl"])
        zo = max(g, key=lambda r: (r["zeroEB"] + r["zeroWB"]) / 2)
        print("L=%.0f: band-optimal C=%.0f (b=%.1f) | eff-optimal C=%.0f "
              "(b/C=%.3f) | delay-optimal C=%.0f (%.2f s/veh) | zero-stop-"
              "optimal C=%.0f" % (L, bo["C"], bo["b"], eo["C"], eo["eff"],
                                  do["C"], do["mean_tl"], zo["C"]))
        for r in g:
            print("   C=%3.0f b=%5.1f b/C=%.3f attain=%.3f mean_tl=%6.2f+/-%.2f "
                  "zeroEB=%.3f zeroWB=%.3f tl_cross=%5.2f tele=%d"
                  % (r["C"], r["b"], r["eff"], r["attain"], r["mean_tl"],
                     r["mean_tl_hw"], r["zeroEB"], r["zeroWB"], r["tl_cross"],
                     r["teleports"] or 0))

    hdr("H4 LEAD-LAG")
    for r in rd("h4_analytic.csv"):
        print("L=%4.0f  gT=%.0f delta=%.0f  b(lead-lead)=%5.2f -> b(best)=%5.2f "
              "(+%.2f s, %+.1f%%)  attain %.3f->%.3f  modes=%s"
              % (r["L"], r["gT"], r["delta_shift"], r["b_leadlead"],
                 r["b_best"], r["gain_s"], r["gain_pct"],
                 r["attain_leadlead"], r["attain_best"], r["modes_best"]))
    for r in rd("h4_agg.csv"):
        if isinstance(r["tag"], str) and r["tag"].startswith("DIFF"):
            print("L=%4.0f %-42s %+8.3f +/- %7.3f  p=%.3g r=%.2f"
                  % (r["L"], r["tag"], r["zeroEB"], r["zeroEB_hw"],
                     r["zeroWB"], r["bandEB"]))
        else:
            print("L=%4.0f %-9s zeroEB=%.3f zeroWB=%.3f tl_left=%6.2f+/-%.2f "
                  "stops_left=%.2f tl_cross=%5.2f mean_tl=%5.2f"
                  % (r["L"], r["tag"], r["zeroEB"], r["zeroWB"],
                     r["tl_artleft"], r["tl_artleft_hw"], r["stops_artleft"],
                     r["tl_cross"], r["mean_tl"]))

    hdr("H5 DISPERSION")
    print(json.dumps(js("h5_robertson_fit.json"), indent=1))
    for r in rd("h5_dispersion.csv"):
        print("  d=%4.0f T=%5.1f sd=%5.2f var=%6.2f F=%.4f 1/F-1=%.3f "
              "conc10s=%.3f n=%d" % (r["d_m"], r["cruise_T"], r["sd_tau"],
                                     r["var_tau"], r["F"], r["inv_F_minus1"],
                                     r["conc10s"], r["n"]))
    cv = rd("h5_spread_vs_band.csv")
    bad = [r for r in cv if r["band_exceeds_spread"] in (False, "False")]
    print("first L where 2*sigma exceeds the two-way band:",
          bad[0]["L"] if bad else None)

    hdr("H6 SPILLBACK")
    print("SIGN CONVENTION: BENEFIT rows are (uncoordinated - coordinated). "
          "For time-loss metrics POSITIVE = coordination helped; for zero-stop "
          "metrics POSITIVE = coordination HURT.")
    for r in rd("h6_agg.csv"):
        if isinstance(r["tag"], str) and r["tag"].startswith("BENEFIT"):
            print("L=%3.0f q=%4.0f %-46s %+8.3f +/- %7.3f p=%.3g"
                  % (r["L"], r["thru"], r["tag"], r["jam_max_EB"],
                     r["jam_max_EB_hw"], r["jam_mean_EB"]))
        else:
            print("L=%3.0f q=%4.0f %-9s jamEB=%6.1f/%6.1f (link %.1f, ratio "
                  "%.2f) nearfull=%.3f zeroEB=%.3f tlE=%7.2f tl_all=%7.2f "
                  "compl=%.4f tele=%d run_max=%.0f"
                  % (r["L"], r["thru"], r["tag"], r["jam_max_EB"],
                     r["jam_mean_EB"], r["link_len"], r["storage_ratio_EB"],
                     r["nearfull_EB"], r["zeroEB"], r["tl_thruE"], r["tl_all"],
                     r["completed_share"], r["teleports"] or 0,
                     r["running_max"] or 0))


if __name__ == "__main__":
    main()
