#!/usr/bin/env python3
"""Extract per-run metrics, aggregate per cell with CIs, and do paired (CRN) tests."""
import argparse
import csv
import math
import os
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

VARIANTS = ["twoway", "oneway_fair", "oneway_naive"]
T975 = {2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776, 6: 2.571, 7: 2.447, 8: 2.365,
        9: 2.306, 10: 2.262, 11: 2.228, 12: 2.201, 13: 2.179, 14: 2.160,
        15: 2.145, 16: 2.131, 17: 2.120, 18: 2.110, 19: 2.101, 20: 2.093,
        24: 2.064, 29: 2.045, 30: 2.042, 39: 2.023, 49: 2.010, 59: 2.001}


def tcrit(df):
    if df <= 0:
        return float("nan")
    if df in T975:
        return T975[df]
    ks = sorted(T975)
    for k in ks:
        if df < k:
            return T975[k]
    return 1.96


def mean_ci(xs):
    n = len(xs)
    if n == 0:
        return float("nan"), float("nan"), float("nan"), 0
    m = sum(xs) / n
    if n == 1:
        return m, 0.0, 0.0, 1
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    hw = tcrit(n - 1) * sd / math.sqrt(n)
    return m, sd, hw, n


def mser5(series):
    """MSER-5 truncation point (index into the batched series). White (1997)."""
    b = [sum(series[i:i + 5]) / 5.0 for i in range(0, len(series) - 4, 5)]
    n = len(b)
    best, bestd = None, float("inf")
    for d in range(0, max(1, n - 5)):
        rest = b[d:]
        m = len(rest)
        if m < 5:
            break
        mu = sum(rest) / m
        ss = sum((x - mu) ** 2 for x in rest)
        z = ss / (m * m)
        if z < bestd:
            bestd, best = z, d
    return (best or 0) * 5, bestd


def read_summary(path):
    t, run = [], []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "step":
            t.append(float(el.get("time")))
            run.append(float(el.get("running")))
            el.clear()
    return t, run


def read_tripinfo(path, kinds, warmup, load_end):
    """Return aggregate metrics; `kinds` maps vehicle id -> trip kind."""
    agg = dict(n_arr=0, n_unfin=0, vmt=0.0, vht=0.0, stops=0.0, timeloss=0.0,
               waiting=0.0, dur=0.0, depdelay=0.0, rl=0.0)
    win = dict(n=0, dur=0.0, stops=0.0, timeloss=0.0, rl=0.0)
    bykind = defaultdict(lambda: dict(n=0, dur=0.0, stops=0.0, timeloss=0.0,
                                      waiting=0.0, rl=0.0))
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag != "tripinfo":
            el.clear()
            continue
        arr = float(el.get("arrival", -1))
        dep = float(el.get("depart"))
        dur = float(el.get("duration"))
        rl = float(el.get("routeLength", 0))
        tl = float(el.get("timeLoss", 0))
        wc = float(el.get("waitingCount", 0))
        wt = float(el.get("waitingTime", 0))
        dd = float(el.get("departDelay", 0))
        if arr >= 0:
            agg["n_arr"] += 1
            agg["vmt"] += rl
            agg["vht"] += dur
            agg["stops"] += wc
            agg["timeloss"] += tl
            agg["waiting"] += wt
            agg["dur"] += dur
            agg["depdelay"] += dd
            agg["rl"] += rl
            if warmup <= dep <= load_end:
                win["n"] += 1
                win["dur"] += dur
                win["stops"] += wc
                win["timeloss"] += tl
                win["rl"] += rl
            k = kinds.get(el.get("id"))
            if k:
                b = bykind[k]
                b["n"] += 1
                b["dur"] += dur
                b["stops"] += wc
                b["timeloss"] += tl
                b["waiting"] += wt
                b["rl"] += rl
        else:
            agg["n_unfin"] += 1
        el.clear()
    return agg, win, bykind


def run_metrics(rundir, cell, warmup, load_end):
    kinds = {}
    odc = os.path.join(cell, "od_common.csv")
    if os.path.exists(odc):
        for r in csv.DictReader(open(odc)):
            kinds[r["id"]] = r["kind"]
    agg, win, bykind = read_tripinfo(os.path.join(rundir, "tripinfo.xml"),
                                     kinds, warmup, load_end)
    n = max(agg["n_arr"], 1)
    m = dict(
        n_arrived=agg["n_arr"], n_unfinished=agg["n_unfin"],
        vmt_vehkm=agg["vmt"] / 1000.0, vht_vehh=agg["vht"] / 3600.0,
        mean_speed_ms=(agg["vmt"] / agg["vht"]) if agg["vht"] > 0 else 0.0,
        mean_duration_s=agg["dur"] / n, mean_stops=agg["stops"] / n,
        mean_timeloss_s=agg["timeloss"] / n, mean_waiting_s=agg["waiting"] / n,
        mean_departdelay_s=agg["depdelay"] / n,
        mean_routelen_m=agg["rl"] / n,
    )
    wn = max(win["n"], 1)
    m.update(win_n=win["n"], win_mean_duration_s=win["dur"] / wn,
             win_mean_stops=win["stops"] / wn,
             win_mean_timeloss_s=win["timeloss"] / wn,
             win_mean_routelen_m=win["rl"] / wn)
    for k, b in bykind.items():
        bn = max(b["n"], 1)
        m["k_%s_n" % k] = b["n"]
        m["k_%s_dur" % k] = b["dur"] / bn
        m["k_%s_stops" % k] = b["stops"] / bn
        m["k_%s_timeloss" % k] = b["timeloss"] / bn
        m["k_%s_rl" % k] = b["rl"] / bn
    return m


def circuity(cell):
    """Planned free-flow path distance per variant, on the common trip set."""
    out = {}
    for v in VARIANTS:
        p = os.path.join(cell, "%s.dist.csv" % v)
        if not os.path.exists(p):
            continue
        byk = defaultdict(list)
        for r in csv.DictReader(open(p)):
            byk[r["kind"]].append(float(r["ff_path_dist_m"]))
            byk["ALL"].append(float(r["ff_path_dist_m"]))
        out[v] = {k: sum(x) / len(x) for k, x in byk.items()}
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--work", required=True)
    p.add_argument("--demands", type=int, nargs="+", required=True)
    p.add_argument("--seeds", type=int, nargs="+", required=True)
    p.add_argument("--tag", default="base")
    p.add_argument("--load-end", type=float, default=3600.0)
    p.add_argument("--out-runs", required=True)
    p.add_argument("--out-cells", required=True)
    p.add_argument("--out-paired", required=True)
    p.add_argument("--out-circuity", default=None)
    p.add_argument("--warmup-report", default=None)
    a = p.parse_args()

    # ---- empirical warm-up detection -------------------------------------
    warm_rows, warmup_by_demand = [], {}
    for d in a.demands:
        vals = []
        for v in VARIANTS:
            for s in a.seeds[:5]:
                sp = os.path.join(a.work, "d%d_s%d" % (d, s),
                                  "%s_%s" % (v, a.tag), "summary.xml")
                if not os.path.exists(sp):
                    continue
                t, run = read_summary(sp)
                load = [r for tt, r in zip(t, run) if tt <= a.load_end]
                w, _ = mser5(load)
                vals.append(w)
                warm_rows.append(dict(demand=d, variant=v, seed=s, mser5_s=w,
                                      peak_running=max(run) if run else 0,
                                      running_at_load_end=load[-1] if load else 0))
        warmup_by_demand[d] = max(vals) if vals else 0.0
    if a.warmup_report:
        with open(a.warmup_report, "w") as f:
            w = csv.DictWriter(f, ["demand", "variant", "seed", "mser5_s",
                                   "peak_running", "running_at_load_end"])
            w.writeheader()
            for r in warm_rows:
                w.writerow(r)

    # ---- per-run metrics --------------------------------------------------
    runs = []
    for d in a.demands:
        wu = warmup_by_demand.get(d, 0.0)
        for s in a.seeds:
            cell = os.path.join(a.work, "d%d_s%d" % (d, s))
            for v in VARIANTS:
                rd = os.path.join(cell, "%s_%s" % (v, a.tag))
                if not os.path.exists(os.path.join(rd, "tripinfo.xml")):
                    continue
                m = run_metrics(rd, cell, wu, a.load_end)
                m.update(demand=d, seed=s, variant=v, tag=a.tag, warmup_s=wu)
                runs.append(m)
    cols = sorted(set().union(*[set(r) for r in runs]))
    cols = ["demand", "variant", "seed", "tag", "warmup_s"] + \
           [c for c in cols if c not in ("demand", "variant", "seed", "tag", "warmup_s")]
    with open(a.out_runs, "w") as f:
        w = csv.DictWriter(f, cols)
        w.writeheader()
        for r in runs:
            w.writerow({c: r.get(c, "") for c in cols})

    metrics = [c for c in cols if c not in ("demand", "variant", "seed", "tag")]

    # ---- per-cell aggregation with CIs -----------------------------------
    by = defaultdict(list)
    for r in runs:
        by[(r["demand"], r["variant"])].append(r)
    with open(a.out_cells, "w") as f:
        w = csv.writer(f)
        w.writerow(["demand", "variant", "metric", "n", "mean", "sd", "ci95_halfwidth",
                    "ci95_lo", "ci95_hi", "cv"])
        for (d, v), rs in sorted(by.items()):
            for mt in metrics:
                xs = [r[mt] for r in rs if isinstance(r.get(mt), (int, float))]
                m, sd, hw, n = mean_ci(xs)
                if n == 0:
                    continue
                w.writerow([d, v, mt, n, "%.6g" % m, "%.6g" % sd, "%.6g" % hw,
                            "%.6g" % (m - hw), "%.6g" % (m + hw),
                            "%.6g" % (sd / m) if m else ""])

    # ---- paired (CRN) differences ----------------------------------------
    idx = {(r["demand"], r["variant"], r["seed"]): r for r in runs}
    pairs = [("oneway_fair", "twoway"), ("oneway_naive", "twoway"),
             ("oneway_naive", "oneway_fair")]
    with open(a.out_paired, "w") as f:
        w = csv.writer(f)
        w.writerow(["demand", "treat", "base", "metric", "n", "mean_base",
                    "mean_treat", "mean_diff", "sd_diff", "ci95_lo", "ci95_hi",
                    "pct_diff", "significant", "paired_corr", "vrf_vs_unpaired"])
        for d in a.demands:
            for tr, ba in pairs:
                for mt in metrics:
                    ds, bs, ts = [], [], []
                    for s in a.seeds:
                        rb = idx.get((d, ba, s))
                        rt = idx.get((d, tr, s))
                        if rb is None or rt is None:
                            continue
                        xb, xt = rb.get(mt), rt.get(mt)
                        if not isinstance(xb, (int, float)) or \
                           not isinstance(xt, (int, float)):
                            continue
                        bs.append(xb)
                        ts.append(xt)
                        ds.append(xt - xb)
                    if len(ds) < 3:
                        continue
                    m, sd, hw, n = mean_ci(ds)
                    mb = sum(bs) / len(bs)
                    mt_ = sum(ts) / len(ts)
                    # paired correlation + variance-reduction factor of CRN
                    nb = len(bs)
                    mub, mut = mb, mt_
                    sb = math.sqrt(sum((x - mub) ** 2 for x in bs) / (nb - 1))
                    st = math.sqrt(sum((x - mut) ** 2 for x in ts) / (nb - 1))
                    cov = sum((bs[i] - mub) * (ts[i] - mut)
                              for i in range(nb)) / (nb - 1)
                    rho = cov / (sb * st) if sb > 0 and st > 0 else float("nan")
                    var_unp = sb ** 2 + st ** 2
                    var_pair = sd ** 2
                    vrf = (var_unp / var_pair) if var_pair > 0 else float("inf")
                    sig = "yes" if (m - hw) * (m + hw) > 0 else "no"
                    w.writerow([d, tr, ba, mt, n, "%.6g" % mb, "%.6g" % mt_,
                                "%.6g" % m, "%.6g" % sd, "%.6g" % (m - hw),
                                "%.6g" % (m + hw),
                                "%.4g" % (100 * m / mb) if mb else "", sig,
                                "%.4g" % rho, "%.4g" % vrf])

    # ---- circuity ---------------------------------------------------------
    if a.out_circuity:
        with open(a.out_circuity, "w") as f:
            w = csv.writer(f)
            w.writerow(["demand", "seed", "kind", "dist_twoway_m",
                        "dist_oneway_fair_m", "dist_oneway_naive_m",
                        "circuity_fair", "circuity_naive"])
            for d in a.demands:
                for s in a.seeds:
                    c = circuity(os.path.join(a.work, "d%d_s%d" % (d, s)))
                    if len(c) < 3:
                        continue
                    for k in sorted(c["twoway"]):
                        A = c["twoway"][k]
                        B = c["oneway_fair"][k]
                        C = c["oneway_naive"][k]
                        w.writerow([d, s, k, "%.2f" % A, "%.2f" % B, "%.2f" % C,
                                    "%.5f" % (B / A), "%.5f" % (C / A)])
    print("wrote %s (%d runs), %s, %s" % (a.out_runs, len(runs), a.out_cells,
                                          a.out_paired))


if __name__ == "__main__":
    main()
