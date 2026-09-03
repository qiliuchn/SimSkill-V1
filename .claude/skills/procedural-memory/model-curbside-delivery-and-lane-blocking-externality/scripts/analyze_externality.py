#!/usr/bin/env python3
"""
Externality-rate analysis for the curbside-freight study.

Headline metric -- the MARGINAL EXTERNALITY RATE:

    R = ( car delay [veh-h] in cell  -  car delay [veh-h] in the SAME variant &
          volume's ZERO-DELIVERY CONTROL, SAME SEED )
        / curb blockage [veh-h] actually measured from stop-output

i.e. extra vehicle-hours of car delay per vehicle-hour of curb blockage. It is
formed SEED-BY-SEED (Common Random Numbers pairing against the control), so its
across-seed standard deviation is the dispersion of a paired difference, not of
two independent means -- which is what makes the "is this bigger than noise"
claim honest.

Car delay per vehicle = timeLoss + departDelay. departDelay must be included:
once the corridor backs up to the origin, vehicles wait to be inserted, and
that waiting is real delay that timeLoss alone never sees.

Outputs: results table (txt + csv), paired-test summary, and two plots.
Usage: python3 analyze_externality.py --csv IN.csv --outdir OUT
"""
import argparse
import csv
import os
from collections import defaultdict

import numpy as np
from scipy import stats

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt   # noqa: E402

CELL_LABEL = {"D0": "0 stops/h (control)",
              "D10": "10 stops/h x 100 s",
              "D30": "30 stops/h x 100 s",
              "D6L": "6 stops/h x 500 s"}
NUM = None


def load(path):
    rows = []
    with open(path) as fh:
        for r in csv.DictReader(fh):
            for k, v in r.items():
                if k in ("variant", "cell"):
                    continue
                try:
                    r[k] = float(v)
                except (TypeError, ValueError):
                    pass
            rows.append(r)
    return rows


def index(rows):
    d = {}
    for r in rows:
        d[(r["variant"], int(r["volume"]), r["cell"], int(r["seed"]))] = r
    return d


def mci(x):
    """mean, sd, half-width of the 95% CI."""
    x = np.asarray(x, float)
    n = len(x)
    if n < 2:
        return (x.mean() if n else float("nan")), 0.0, float("nan")
    sd = x.std(ddof=1)
    return x.mean(), sd, stats.t.ppf(0.975, n - 1) * sd / np.sqrt(n)


def fmt(m, h):
    return f"{m:8.2f} +/- {h:6.2f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--outdir", required=True)
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    rows = load(a.csv)
    ix = index(rows)
    variants = sorted({r["variant"] for r in rows})
    volumes = sorted({int(r["volume"]) for r in rows})
    cells = ["D0", "D10", "D30", "D6L"]
    seeds = sorted({int(r["seed"]) for r in rows})
    L = []
    P = L.append

    P("=" * 100)
    P("CURBSIDE FREIGHT DOUBLE-PARKING EXTERNALITY -- RESULTS")
    P(f"{len(variants)} variants x {len(volumes)} volumes x {len(cells)} "
      f"delivery cells x {len(seeds)} seeds = {len(rows)} SUMO runs")
    P("Variant A = no curb facility (van double-parks in right travel lane)")
    P("Variant B = dedicated off-line loading bay")
    P("Measurement window: car departures in [600, 4200) s (1 h). "
      "All +/- are 95% CI half-widths over 20 seeds.")
    P("=" * 100)

    # ------------------------------------------------------------------ 1 --
    P("")
    P("[1] PER-CELL MEANS  (mean +/- 95% CI over 20 seeds)")
    P("-" * 100)
    hdr = (f"{'var':>3} {'vol':>5} {'cell':>4} "
           f"{'car mean TT (s)':>22} {'car mean delay (s)':>22} "
           f"{'total car delay(vh)':>22} {'thru(vph)':>18} "
           f"{'q_max(veh)':>16} {'fmerge LC':>16} {'blk(vh)':>10} "
           f"{'tele':>5} {'coll':>5}")
    P(hdr)
    table_csv = [["variant", "volume", "cell", "stops_per_hour", "dwell_s",
                  "car_mean_tt_s", "car_mean_tt_ci", "car_mean_delay_s",
                  "car_mean_delay_ci", "car_total_delay_vehh",
                  "car_total_delay_vehh_ci", "throughput_vph",
                  "throughput_ci", "queue_max_veh", "queue_max_ci",
                  "queue_mean_veh", "forced_merge_lc", "forced_merge_lc_ci",
                  "curb_block_vehh", "curb_block_vehh_ci",
                  "teleports_mean", "collisions_mean", "n_seeds"]]
    agg = {}
    for v in variants:
        for vol in volumes:
            for c in cells:
                rr = [ix[(v, vol, c, s)] for s in seeds if (v, vol, c, s) in ix]
                g = lambda k: [x[k] for x in rr]
                tt = mci(g("car_mean_duration_s"))
                dl = mci(g("car_mean_delay_s"))
                td = mci(g("car_total_delay_vehh"))
                th = mci(g("throughput_vph"))
                qx = mci(g("queue_max_veh"))
                qm = mci(g("queue_mean_veh"))
                lc = mci(g("lc_car_forced_merge"))
                bk = mci(g("curb_block_vehh"))
                te = np.mean(g("teleports"))
                co = np.mean(g("collisions"))
                agg[(v, vol, c)] = dict(tt=tt, dl=dl, td=td, th=th, qx=qx,
                                        qm=qm, lc=lc, bk=bk, te=te, co=co,
                                        n=len(rr))
                P(f"{v:>3} {vol:5d} {c:>4} "
                  f"{fmt(tt[0], tt[2]):>22} {fmt(dl[0], dl[2]):>22} "
                  f"{fmt(td[0], td[2]):>22} {fmt(th[0], th[2]):>18} "
                  f"{fmt(qx[0], qx[2]):>16} {fmt(lc[0], lc[2]):>16} "
                  f"{bk[0]:10.3f} {te:5.2f} {co:5.2f}")
                table_csv.append([v, vol, c, int(rr[0]["stops_per_hour"]),
                                  int(rr[0]["dwell_s"]),
                                  round(tt[0], 3), round(tt[2], 3),
                                  round(dl[0], 3), round(dl[2], 3),
                                  round(td[0], 4), round(td[2], 4),
                                  round(th[0], 1), round(th[2], 1),
                                  round(qx[0], 2), round(qx[2], 2),
                                  round(qm[0], 3),
                                  round(lc[0], 1), round(lc[2], 1),
                                  round(bk[0], 4), round(bk[2], 4),
                                  round(te, 3), round(co, 3), len(rr)])
            P("")

    # ------------------------------------------------------------------ 2 --
    P("=" * 100)
    P("[2] ZERO-DELIVERY CONTROL EQUALITY  (A vs B at 0 stops/h, paired by seed)")
    P("    If the two networks are not equivalent absent deliveries, every")
    P("    A-vs-B claim downstream is contaminated. Paired t-test on the")
    P("    per-seed difference in mean car travel time.")
    P("-" * 100)
    P(f"{'vol':>6} {'A mean TT':>12} {'B mean TT':>12} {'B-A (s)':>18} "
      f"{'as % of A':>10} {'paired t':>9} {'p':>8}  verdict")
    ctl = {}
    for vol in volumes:
        dA = [ix[("A", vol, "D0", s)]["car_mean_duration_s"] for s in seeds]
        dB = [ix[("B", vol, "D0", s)]["car_mean_duration_s"] for s in seeds]
        diff = np.array(dB) - np.array(dA)
        m, sd, h = mci(diff)
        t, p = stats.ttest_rel(dB, dA)
        ctl[vol] = (m, h, p)
        verdict = ("equivalent (|diff| < 1% of mean)"
                   if abs(m) < 0.01 * np.mean(dA) else "CHECK")
        P(f"{vol:6d} {np.mean(dA):12.3f} {np.mean(dB):12.3f} "
          f"{fmt(m, h):>18} {100*m/np.mean(dA):9.2f}% {t:9.3f} {p:8.4f}  "
          f"{verdict}")

    # ------------------------------------------------------------------ 3 --
    P("")
    P("=" * 100)
    P("[3] MARGINAL EXTERNALITY RATE  R = d(car delay veh-h) / (curb blockage veh-h)")
    P("    Formed per seed against the SAME-SEED zero-delivery control (CRN).")
    P("-" * 100)
    P(f"{'var':>3} {'vol':>5} {'cell':>4} {'blk (vh/h)':>11} "
      f"{'delta delay (vh)':>22} {'R = ext. rate':>22} {'p(delta=0)':>11} "
      f"{'signif?':>8}")
    rate = {}
    rate_csv = [["variant", "volume", "cell", "curb_block_vehh",
                 "delta_delay_vehh", "delta_delay_ci", "ext_rate",
                 "ext_rate_sd", "ext_rate_ci", "p_value", "significant"]]
    for v in variants:
        for vol in volumes:
            for c in ["D10", "D30", "D6L"]:
                dd, rr_ = [], []
                for s in seeds:
                    a_ = ix[(v, vol, c, s)]
                    b_ = ix[(v, vol, "D0", s)]
                    d = a_["car_total_delay_vehh"] - b_["car_total_delay_vehh"]
                    dd.append(d)
                    rr_.append(d / a_["curb_block_vehh"])
                md, sdd, hd = mci(dd)
                mr, sdr, hr = mci(rr_)
                t, p = stats.ttest_1samp(dd, 0.0)
                sig = "YES" if p < 0.05 else "no"
                rate[(v, vol, c)] = (mr, hr, sdr, md, hd, p)
                bk = agg[(v, vol, c)]["bk"][0]
                P(f"{v:>3} {vol:5d} {c:>4} {bk:11.3f} "
                  f"{fmt(md, hd):>22} {fmt(mr, hr):>22} {p:11.2e} {sig:>8}")
                rate_csv.append([v, vol, c, round(bk, 4), round(md, 4),
                                 round(hd, 4), round(mr, 4), round(sdr, 4),
                                 round(hr, 4), f"{p:.3e}", sig])
            P("")

    # ------------------------------------------------------------------ 4 --
    P("=" * 100)
    P("[4] NONLINEARITY OF THE EXTERNALITY RATE IN BACKGROUND VOLUME "
      "(variant A, D30)")
    P("    Linear-in-volume would mean a constant ratio between successive")
    P("    volume steps' rate increments. Reported as the rate itself and its")
    P("    step-to-step multiplier.")
    P("-" * 100)
    prev = None
    P("    v/c uses the MEASURED unblocked corridor capacity of 2511 veh/h")
    P("    (peak of the served-flow-vs-demand curve, see results_capacity.txt),")
    P("    not a hand-computed signal capacity.")
    P(f"{'vol':>6} {'measured v/c':>14} {'R (A,D30)':>22} "
      f"{'x prev':>9} {'R (B,D30)':>22}")
    for vol in volumes:
        rA = rate[("A", vol, "D30")]
        rB = rate[("B", vol, "D30")]
        mult = "" if prev is None else f"{rA[0]/prev:9.2f}"
        prev = rA[0] if rA[0] > 0 else prev
        P(f"{vol:6d} {vol/2511:14.2f} {fmt(rA[0], rA[1]):>22} {mult:>9} "
          f"{fmt(rB[0], rB[1]):>22}")

    # ------------------------------------------------------------------ 5 --
    P("")
    P("=" * 100)
    P("[5] EQUAL-CURB-OCCUPANCY CONTRAST: 30 x 100 s vs 6 x 500 s")
    P("    Both are 3000 s/h = 0.833 veh-h/h of designed curb occupancy.")
    P("    Difference therefore isolates FREQUENCY (number of merge events)")
    P("    from OCCUPANCY TIME. Paired by seed.")
    P("-" * 100)
    P(f"{'var':>3} {'vol':>5} {'blk D30':>9} {'blk D6L':>9} "
      f"{'delay D30 (s)':>16} {'delay D6L (s)':>16} "
      f"{'D30-D6L (s)':>20} {'p':>9} {'LC D30':>9} {'LC D6L':>9}")
    eq_csv = [["variant", "volume", "blk_D30_vehh", "blk_D6L_vehh",
               "car_mean_delay_D30", "car_mean_delay_D6L", "diff", "diff_ci",
               "p_value", "lc_D30", "lc_D6L"]]
    for v in variants:
        for vol in volumes:
            x = [ix[(v, vol, "D30", s)]["car_mean_delay_s"] for s in seeds]
            y = [ix[(v, vol, "D6L", s)]["car_mean_delay_s"] for s in seeds]
            d = np.array(x) - np.array(y)
            m, sd, h = mci(d)
            t, p = stats.ttest_rel(x, y)
            lc1 = agg[(v, vol, "D30")]["lc"][0]
            lc2 = agg[(v, vol, "D6L")]["lc"][0]
            b1 = agg[(v, vol, "D30")]["bk"][0]
            b2 = agg[(v, vol, "D6L")]["bk"][0]
            P(f"{v:>3} {vol:5d} {b1:9.3f} {b2:9.3f} "
              f"{np.mean(x):16.2f} {np.mean(y):16.2f} {fmt(m, h):>20} "
              f"{p:9.2e} {lc1:9.0f} {lc2:9.0f}")
            eq_csv.append([v, vol, round(b1, 4), round(b2, 4),
                           round(np.mean(x), 3), round(np.mean(y), 3),
                           round(m, 3), round(h, 3), f"{p:.3e}",
                           round(lc1, 1), round(lc2, 1)])
        P("")

    # ------------------------------------------------------------------ 6 --
    P("=" * 100)
    P("[6] DOES THE LOADING BAY RESTORE THE BASELINE?")
    P("    (a) A-vs-B paired contrast at each delivery cell (CRN);")
    P("    (b) residual penalty inside variant B: B_delivery - B_control.")
    P("-" * 100)
    P(f"{'vol':>6} {'cell':>4} {'A delay(s)':>11} {'B delay(s)':>11} "
      f"{'A-B (s)':>20} {'p':>9} | {'B - Bctl (s)':>20} {'p':>9} "
      f"{'residual?':>10}")
    res_csv = [["volume", "cell", "A_delay_s", "B_delay_s", "A_minus_B",
                "A_minus_B_ci", "p_AB", "B_minus_Bcontrol", "resid_ci",
                "p_resid", "residual_significant"]]
    for vol in volumes:
        for c in ["D10", "D30", "D6L"]:
            xa = [ix[("A", vol, c, s)]["car_mean_delay_s"] for s in seeds]
            xb = [ix[("B", vol, c, s)]["car_mean_delay_s"] for s in seeds]
            xbc = [ix[("B", vol, "D0", s)]["car_mean_delay_s"] for s in seeds]
            d1 = np.array(xa) - np.array(xb)
            m1, _, h1 = mci(d1)
            _, p1 = stats.ttest_rel(xa, xb)
            d2 = np.array(xb) - np.array(xbc)
            m2, _, h2 = mci(d2)
            _, p2 = stats.ttest_rel(xb, xbc)
            flag = "YES" if p2 < 0.05 else "none"
            P(f"{vol:6d} {c:>4} {np.mean(xa):11.2f} {np.mean(xb):11.2f} "
              f"{fmt(m1, h1):>20} {p1:9.2e} | {fmt(m2, h2):>20} {p2:9.2e} "
              f"{flag:>10}")
            res_csv.append([vol, c, round(np.mean(xa), 3), round(np.mean(xb), 3),
                            round(m1, 3), round(h1, 3), f"{p1:.3e}",
                            round(m2, 3), round(h2, 3), f"{p2:.3e}", flag])
        P("")

    # ------------------------------------------------------------------ 7 --
    P("=" * 100)
    P("[7] REPLICATION DIAGNOSTICS")
    P("    Seed-to-seed CV per cell, minimum detectable difference at n=1 vs")
    P("    n=20, and the CRN variance-reduction factor for the A-vs-B contrast")
    P("    (VRF = Var(independent difference) / Var(paired difference);")
    P("     VRF > 1 => CRN helped, VRF < 1 => CRN hurt for that metric).")
    P("-" * 100)
    P(f"{'var':>3} {'vol':>5} {'cell':>4} {'mean delay':>11} {'sd':>9} "
      f"{'CV%':>7} {'MDD n=1':>9} {'MDD n=20':>9}")
    for v in variants:
        for vol in volumes:
            for c in cells:
                x = np.array([ix[(v, vol, c, s)]["car_mean_delay_s"]
                              for s in seeds])
                m, sd, h = mci(x)
                mdd1 = 1.96 * sd * np.sqrt(2)
                mdd20 = stats.t.ppf(0.975, 19) * sd * np.sqrt(2 / 20)
                P(f"{v:>3} {vol:5d} {c:>4} {m:11.2f} {sd:9.3f} "
                  f"{100*sd/m:7.2f} {mdd1:9.3f} {mdd20:9.3f}")
        P("")
    P(f"{'vol':>6} {'cell':>4} {'corr(A,B)':>10} {'Var paired':>12} "
      f"{'Var indep':>12} {'VRF':>8}  CRN verdict")
    for vol in volumes:
        for c in cells:
            xa = np.array([ix[("A", vol, c, s)]["car_mean_delay_s"]
                           for s in seeds])
            xb = np.array([ix[("B", vol, c, s)]["car_mean_delay_s"]
                           for s in seeds])
            r = np.corrcoef(xa, xb)[0, 1]
            vp = np.var(xa - xb, ddof=1)
            vi = np.var(xa, ddof=1) + np.var(xb, ddof=1)
            P(f"{vol:6d} {c:>4} {r:10.3f} {vp:12.4f} {vi:12.4f} "
              f"{vi/vp if vp > 0 else float('nan'):8.2f}  "
              f"{'CRN helped' if vi/vp > 1 else 'CRN HURT'}")
        P("")

    # ------------------------------------------------------------------ 8 --
    P("=" * 100)
    P("[8] SIMULATION ARTEFACT AUDIT (teleports / collisions / unfinished)")
    P("    --time-to-teleport 300 s. A fully blocked lane is a known SUMO")
    P("    teleport trigger, and a teleport TRUNCATES delay, biasing the")
    P("    externality DOWNWARD. Reported per cell rather than assumed absent.")
    P("-" * 100)
    tot_t = tot_c = tot_u = 0
    worst = []
    for v in variants:
        for vol in volumes:
            for c in cells:
                te = [ix[(v, vol, c, s)]["teleports"] for s in seeds]
                co = [ix[(v, vol, c, s)]["collisions"] for s in seeds]
                un = [ix[(v, vol, c, s)]["unfinished_trips"] for s in seeds]
                tot_t += sum(te)
                tot_c += sum(co)
                tot_u += sum(un)
                if sum(te) or sum(co) or sum(un):
                    worst.append((v, vol, c, sum(te), sum(co), sum(un),
                                  max(te)))
    P(f"    total over all {len(rows)} runs: teleports={tot_t:.0f}  "
      f"collisions={tot_c:.0f}  unfinished trips={tot_u:.0f}")
    if worst:
        P(f"    cells with any artefact ({len(worst)} of "
          f"{len(variants)*len(volumes)*len(cells)}):")
        P(f"      {'var':>3} {'vol':>5} {'cell':>4} {'tele(sum/20)':>13} "
          f"{'coll':>6} {'unfin':>6} {'max tele in a run':>18}")
        for w in sorted(worst, key=lambda z: -z[3]):
            P(f"      {w[0]:>3} {w[1]:5d} {w[2]:>4} {w[3]:13.0f} {w[4]:6.0f} "
              f"{w[5]:6.0f} {w[6]:18.0f}")
    else:
        P("    NO teleports, NO collisions, NO unfinished trips anywhere.")

    # ------------------------------------------------------------------ 9 --
    P("")
    P("=" * 100)
    P("[9] LANE-OCCUPANCY EVIDENCE THAT THE MECHANIC IS REAL "
      "(laneData, curb-zone edge)")
    P("    van seconds on the blocked/bay lane, and how car seconds split")
    P("    between the right and left through lane.")
    P("-" * 100)
    P(f"{'var':>3} {'vol':>5} {'cell':>4} {'van s on blk/bay lane':>22} "
      f"{'car s RIGHT thru':>18} {'car s LEFT thru':>18} {'right share':>12}")
    for v in variants:
        for vol in volumes:
            for c in cells:
                rr = [ix[(v, vol, c, s)] for s in seeds]
                vs = np.mean([x["van_lane_secs_bayORright"] for x in rr])
                cr = np.mean([x["car_lane_secs_right"] for x in rr])
                cl = np.mean([x["car_lane_secs_left"] for x in rr])
                P(f"{v:>3} {vol:5d} {c:>4} {vs:22.1f} {cr:18.1f} {cl:18.1f} "
                  f"{100*cr/max(cr+cl, 1e-9):11.1f}%")
        P("")

    txt = "\n".join(L)
    with open(os.path.join(a.outdir, "results_table.txt"), "w") as fh:
        fh.write(txt + "\n")
    for name, data in [("cell_summary.csv", table_csv),
                       ("externality_rates.csv", rate_csv),
                       ("equal_occupancy_contrast.csv", eq_csv),
                       ("variantAB_residual.csv", res_csv)]:
        with open(os.path.join(a.outdir, name), "w", newline="") as fh:
            csv.writer(fh).writerows(data)
    print(txt)
    make_plots(agg, rate, ix, variants, volumes, cells, seeds, a.outdir)


def make_plots(agg, rate, ix, variants, volumes, cells, seeds, outdir):
    C = {"A": "#c0392b", "B": "#2471a3"}
    M = {"D10": "o", "D30": "s", "D6L": "^"}

    # --- plot 1: externality rate vs background volume
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.6))
    for v in variants:
        for c in ["D10", "D30", "D6L"]:
            y = [rate[(v, vol, c)][0] for vol in volumes]
            e = [rate[(v, vol, c)][1] for vol in volumes]
            ax[0].errorbar(volumes, y, yerr=e, marker=M[c], color=C[v],
                           ls="-" if c == "D30" else ("--" if c == "D10" else ":"),
                           capsize=3, ms=5,
                           label=f"{v}: {CELL_LABEL[c]}")
    ax[0].axhline(0, color="0.5", lw=0.8)
    ax[0].set_xlabel("background car volume (veh/h)")
    ax[0].set_ylabel("extra car veh-h delay per veh-h of curb blockage")
    ax[0].set_title("Marginal externality rate vs. background volume\n"
                    "(mean +/- 95% CI over 20 seeds)", fontsize=10)
    ax[0].legend(fontsize=7)
    ax[0].grid(alpha=0.3)

    # log panel: variant A only. Variant B's rate is at or below the noise
    # floor over most of the range, so clamping its near-zero / negative values
    # onto a log axis would draw spurious structure.
    for c in ["D10", "D30", "D6L"]:
        y = [rate[("A", vol, c)][0] for vol in volumes]
        ax[1].plot(volumes, y, marker=M[c], color=C["A"],
                   ls="-" if c == "D30" else ("--" if c == "D10" else ":"),
                   ms=5, label=f"A: {CELL_LABEL[c]}")
    yB = [rate[("B", vol, "D30")][0] for vol in volumes]
    ax[1].plot(volumes, yB, marker="s", color=C["B"], ls="-", ms=5,
               label="B: 30 stops/h x 100 s (loading bay)")
    ax[1].set_yscale("log")
    ax[1].set_ylim(0.05, 500)
    ax[1].axvspan(1800, 2100, color="0.85", zorder=0)
    ax[1].text(1950, 0.08, "knee\nv/c 0.72->0.84", ha="center", fontsize=7,
               color="0.35")
    ax[1].set_xlabel("background car volume (veh/h)")
    ax[1].set_ylabel("externality rate (log scale)")
    ax[1].set_title("Log scale: a straight line = exponential growth.\n"
                    "The 1800->2100 step is far steeper than that.",
                    fontsize=10)
    ax[1].grid(alpha=0.3, which="both")
    ax[1].legend(fontsize=7, loc="upper left")
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, "externality_rate_vs_volume.png"), dpi=150)
    plt.close(fig)

    # --- plot 2: variant A vs B delay, plus the equal-occupancy contrast
    fig, ax = plt.subplots(1, 3, figsize=(16, 4.6))
    w = 0.35
    x = np.arange(len(volumes))
    for c, axi in zip(["D30", "D6L"], ax[:2]):
        for i, v in enumerate(variants):
            m = [agg[(v, vol, c)]["dl"][0] for vol in volumes]
            e = [agg[(v, vol, c)]["dl"][2] for vol in volumes]
            axi.bar(x + (i - 0.5) * w, m, w, yerr=e, capsize=3, color=C[v],
                    label=f"variant {v}")
        ctl = [agg[("A", vol, "D0")]["dl"][0] for vol in volumes]
        axi.plot(x, ctl, "k--o", ms=4, lw=1.2, label="0-delivery control")
        axi.set_xticks(x)
        axi.set_xticklabels(volumes)
        axi.set_xlabel("background car volume (veh/h)")
        axi.set_ylabel("mean car delay: timeLoss + departDelay (s)")
        axi.set_title(f"{CELL_LABEL[c]}\nA (double-park) vs B (loading bay)",
                      fontsize=10)
        axi.legend(fontsize=8)
        axi.grid(alpha=0.3, axis="y")

    for i, c in enumerate(["D30", "D6L"]):
        m = [agg[("A", vol, c)]["dl"][0] - agg[("A", vol, "D0")]["dl"][0]
             for vol in volumes]
        ax[2].bar(x + (i - 0.5) * w, m, w,
                  color=["#e67e22", "#8e44ad"][i],
                  label=f"A: {CELL_LABEL[c]}")
    ax[2].set_xticks(x)
    ax[2].set_xticklabels(volumes)
    ax[2].set_xlabel("background car volume (veh/h)")
    ax[2].set_ylabel("excess mean car delay over control (s)")
    ax[2].set_title("EQUAL curb-occupancy contrast (both 3000 s/h):\n"
                    "many short stops vs. few long stops", fontsize=10)
    ax[2].legend(fontsize=8)
    ax[2].grid(alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, "variantA_vs_B_delay.png"), dpi=150)
    plt.close(fig)

    # --- plot 3: seed dispersion, to show effects exceed run-to-run noise
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.6))
    for j, vol in enumerate([1800, 2100]):
        axi = ax[j]
        data, labels, colors = [], [], []
        for v in variants:
            for c in cells:
                data.append([ix[(v, vol, c, s)]["car_mean_delay_s"]
                             for s in seeds])
                labels.append(f"{v}/{c}")
                colors.append(C[v])
        bp = axi.boxplot(data, tick_labels=labels, patch_artist=True,
                         widths=0.6)
        for patch, col in zip(bp["boxes"], colors):
            patch.set_facecolor(col)
            patch.set_alpha(0.55)
        for k, d in enumerate(data, 1):
            axi.plot(np.full(len(d), k) + np.random.uniform(-.12, .12, len(d)),
                     d, "k.", ms=3, alpha=0.6)
        axi.set_title(f"Seed-to-seed dispersion at {vol} veh/h "
                      f"(20 seeds, each dot = one run)", fontsize=10)
        axi.set_ylabel("mean car delay (s)")
        axi.tick_params(axis="x", rotation=45, labelsize=8)
        axi.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, "seed_dispersion.png"), dpi=150)
    plt.close(fig)
    print(f"\nplots -> {outdir}")


if __name__ == "__main__":
    main()
