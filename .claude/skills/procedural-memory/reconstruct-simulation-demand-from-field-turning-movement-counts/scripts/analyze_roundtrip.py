#!/usr/bin/env python3
"""
The round-trip test, on three explicitly separate levels.

  (i)   COUNT FIT         reconstructed-run stop-bar counts vs the OBSERVED
                          stop-bar counts, per movement per 15-min bin  -> GEH
  (ii)  DEMAND RECOVERY   reconstructed INPUT flow vs the TRUE injected flow,
                          per movement per bin (only computable synthetically)
  (iii) PERFORMANCE       control delay, 95th-percentile back of queue, LOS,
                          residual queue at the end of the peak

plus the REALIZED PHF, measured from the rerun's detector output rather than
taken from the flow file.
"""
import json
import os
import statistics

from common import RUNS, OUT, SCEN, BIN, N_BINS, JUNCTIONS, geh
import demand as D
import metrics as M
from export_tmc import movement_counts
from counts_to_demand import peak_hour_factor

APPS = ("EB", "WB", "NB", "SB")
MOVES = ("L", "T", "R")
PEAK = M.PEAK_BINS


def series(counts, j, app, m):
    return [counts.get((j, app, m, b), (0, 0))[0] for b in range(N_BINS)]


def approach_series(counts, j, app):
    return [sum(counts.get((j, app, m, b), (0, 0))[0] for m in MOVES)
            for b in range(N_BINS)]


def count_fit(obs, sim):
    rows = []
    for j in JUNCTIONS:
        for app in APPS:
            for m in MOVES:
                for b in range(N_BINS):
                    c = obs.get((j, app, m, b), (0, 0))[0]
                    s = sim.get((j, app, m, b), (0, 0))[0]
                    rows.append(dict(j=j, app=app, m=m, b=b, obs=c, sim=s,
                                     geh=geh(s, c)))
    return rows


def demand_recovery(rec_report, truth):
    rec = rec_report["recovered_movement_volumes"]
    rows = []
    for key, tv in truth.items():
        j, app, m = key
        rv = rec.get("%s|%s|%s" % key, [0.0] * N_BINS)
        for b in range(N_BINS):
            rows.append(dict(j=j, app=app, m=m, b=b, true=tv[b], rec=rv[b],
                             geh=geh(rv[b], tv[b])))
    return rows


def summarise_geh(rows, key="geh", subset=None):
    v = [r[key] for r in rows if (subset is None or subset(r))]
    if not v:
        return dict(n=0)
    v_sorted = sorted(v)
    return dict(n=len(v), mean=statistics.mean(v), median=statistics.median(v),
                p85=v_sorted[int(0.85 * (len(v) - 1))],
                p95=v_sorted[int(0.95 * (len(v) - 1))], max=max(v),
                pct_lt5=100.0 * sum(1 for x in v if x < 5) / len(v),
                pct_lt10=100.0 * sum(1 for x in v if x < 10) / len(v))


def realized_phf(run_dir):
    c = movement_counts(run_dir)
    out = {}
    for j in JUNCTIONS:
        for app in APPS:
            out["%s %s" % (j, app)] = peak_hour_factor(approach_series(c, j, app))
        out[j] = peak_hour_factor([sum(approach_series(c, j, a)[b] for a in APPS)
                                   for b in range(N_BINS)])
    return out


def performance(run_dir):
    d = M.approach_delay(run_dir, PEAK)
    q = M.back_of_queue(run_dir, PEAK)
    out = {}
    for k in d:
        out["%s %s" % k] = dict(delay=d[k]["delay"], n=d[k]["n"], los=d[k]["los"],
                                q95_veh=q[k]["q95_veh"], qmax_veh=q[k]["qmax_veh"],
                                residual_end_peak=q[k]["residual_end_of_peak_veh"])
    return out


def analyse(arm, rec_name, rec_report_path, label):
    gt = os.path.join(RUNS, "gt_" + arm)
    rr = os.path.join(RUNS, rec_name)
    obs = movement_counts(gt)
    sim = movement_counts(rr)
    rep = json.load(open(rec_report_path))
    truth = D.true_movement_volumes(arm)

    cf = count_fit(obs, sim)
    dr = demand_recovery(rep, truth)
    perf_gt, perf_rr = performance(gt), performance(rr)

    sat = lambda r: (r["j"], r["app"], r["m"]) in (("J1", "EB", "T"), ("J1", "EB", "R"),
                                                   ("J1", "EB", "L"))
    peakonly = lambda r: r["b"] in PEAK
    out = dict(
        arm=arm, label=label, run=rec_name,
        count_fit_all=summarise_geh(cf),
        count_fit_peak=summarise_geh(cf, subset=peakonly),
        count_fit_J1EB=summarise_geh(cf, subset=sat),
        demand_recovery_all=summarise_geh(dr),
        demand_recovery_peak=summarise_geh(dr, subset=peakonly),
        demand_recovery_J1EB=summarise_geh(dr, subset=sat),
        realized_phf={k: v for k, v in realized_phf(rr).items()},
        gt_phf={k: v for k, v in realized_phf(gt).items()},
        performance_gt=perf_gt, performance_rerun=perf_rr,
        count_rows=cf, demand_rows=dr)
    # aggregate demand totals
    tot_true = {}
    tot_rec = {}
    for r in dr:
        k = "%s %s %s" % (r["j"], r["app"], r["m"])
        tot_true[k] = tot_true.get(k, 0.0) + r["true"]
        tot_rec[k] = tot_rec.get(k, 0.0) + r["rec"]
    out["demand_totals"] = {k: dict(true=tot_true[k], rec=tot_rec[k],
                                    err_pct=100.0 * (tot_rec[k] - tot_true[k]) / tot_true[k]
                                    if tot_true[k] else None)
                            for k in sorted(tot_true)}
    pk_true, pk_rec = {}, {}
    for r in dr:
        if r["b"] not in PEAK:
            continue
        k = "%s %s %s" % (r["j"], r["app"], r["m"])
        pk_true[k] = pk_true.get(k, 0.0) + r["true"]
        pk_rec[k] = pk_rec.get(k, 0.0) + r["rec"]
    out["demand_peak_hour"] = {k: dict(true=pk_true[k], rec=pk_rec[k],
                                       err_pct=100.0 * (pk_rec[k] - pk_true[k]) / pk_true[k]
                                       if pk_true[k] else None)
                               for k in sorted(pk_true)}
    return out


VARIANTS = [("rec", "field counts used directly"),
            ("recq", "queue-corrected, APPROACH-STORAGE metric"),
            ("recqt", "queue-corrected (storage) + trust-propagation"),
            ("recqj", "queue-corrected, E2 residual JAM-LENGTH metric")]


def main():
    all_out = {}
    for arm in ("under", "over"):
        for pref, label in VARIANTS:
            rp = os.path.join(SCEN, "%s_%s_report.json" % (pref, arm))
            rn = "%s_%s" % (pref, arm)
            if not (os.path.exists(rp) and os.path.isdir(os.path.join(RUNS, rn))):
                continue
            all_out["%s/%s" % (arm, pref)] = analyse(arm, rn, rp, label)
    with open(os.path.join(OUT, "roundtrip_results.json"), "w") as f:
        json.dump(all_out, f, indent=1)

    for k, v in all_out.items():
        print("=" * 78)
        print("%s   (%s)" % (k, v["label"]))
        for lvl in ("count_fit_all", "count_fit_peak", "count_fit_J1EB",
                    "demand_recovery_all", "demand_recovery_peak",
                    "demand_recovery_J1EB"):
            s = v[lvl]
            print("   %-22s n=%4d meanGEH=%5.2f p85=%5.2f max=%6.2f  %%GEH<5=%5.1f"
                  % (lvl, s["n"], s["mean"], s["p85"], s["max"], s["pct_lt5"]))
        print("   PHF J1 EB: gt=%.4f rerun=%.4f (true injected 0.87)"
              % (v["gt_phf"]["J1 EB"]["PHF"], v["realized_phf"]["J1 EB"]["PHF"]))
        for ap in ("J1 EB", "J2 EB", "J3 EB", "J1 WB"):
            g, r = v["performance_gt"].get(ap), v["performance_rerun"].get(ap)
            if not g:
                continue
            print("   %-6s delay %6.1f -> %6.1f s (%s->%s)  Q95 %5.1f -> %5.1f veh  "
                  "resid %5.1f -> %5.1f" % (ap, g["delay"], r["delay"], g["los"],
                                            r["los"], g["q95_veh"], r["q95_veh"],
                                            g["residual_end_peak"], r["residual_end_peak"]))
    print("\nwrote", os.path.join(OUT, "roundtrip_results.json"))


if __name__ == "__main__":
    main()
