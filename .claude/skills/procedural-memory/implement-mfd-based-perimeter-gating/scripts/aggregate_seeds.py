#!/usr/bin/env python3
"""
Aggregate the multi-seed replication grid (seed x gating set-point).
Produces per-seed raw metrics, per-configuration means, and PAIRED
per-seed differences against that seed's own ungated baseline.
"""
import argparse
import csv
import re
import json
import os
import statistics as st
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt   # noqa: E402


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def metrics(d, cls):
    tp = os.path.join(d, "tripinfo.xml")
    dur, tl, wt, dd, arr = [], [], [], [], []
    per_cls = {"core": [], "through": [], "outside": []}
    for _, el in ET.iterparse(tp, events=("end",)):
        if el.tag != "tripinfo":
            continue
        vid = el.get("id")
        du = float(el.get("duration"))
        dur.append(du)
        tl.append(float(el.get("timeLoss")))
        wt.append(float(el.get("waitingTime")))
        dd.append(float(el.get("departDelay")))
        arr.append(float(el.get("arrival")))
        k = cls.get(vid)
        if k in per_cls:
            per_cls[k].append(du)
        el.clear()
    rows = list(csv.DictReader(open(os.path.join(d, "accumulation_production.csv"))))
    meta = json.load(open(os.path.join(d, "run_meta.json")))
    sroot = ET.parse(os.path.join(d, "statistics.xml")).getroot()
    tel = sroot.find("teleports")
    saf = sroot.find("safety")
    peak = [r for r in rows if 600 < float(r["t_end"]) <= 2400]
    return {
        "arrived_total": len(dur),
        "mean_tt_s": mean(dur),
        "mean_tl_s": mean(tl),
        "mean_wait_s": mean(wt),
        "mean_depart_delay_s": mean(dd),
        "tt_core_s": mean(per_cls["core"]),
        "tt_through_s": mean(per_cls["through"]),
        "tt_outside_s": mean(per_cls["outside"]),
        "arrived_by_3600s": sum(1 for a in arr if a <= 3600),
        "arrived_by_4914s": sum(1 for a in arr if a <= 4914),
        "clearance_s": meta["sim_end"],
        "teleports": int(tel.get("total")) if tel is not None else 0,
        "collisions": int(saf.get("collisions")) if saf is not None else 0,
        "n_peak_veh": max(float(r["n_mean"]) for r in rows),
        "n_at_2400_veh": float(min(rows, key=lambda r: abs(float(r["t_end"]) - 2400))["n_mean"]),
        "core_prod_peak_vehkm": sum(float(r["production_vehkm_h"]) for r in peak) / 60.0,
        "core_prod_total_vehkm": sum(float(r["production_vehkm_h"]) for r in rows) / 60.0,
        "core_outflow_peak_veh": sum(int(r["core_outflow_veh"]) for r in peak),
        "gate_queue_mean_veh": mean(float(r["gate_queue_halting"]) for r in rows),
        "gate_queue_peak_veh": mean(float(r["gate_queue_halting"]) for r in peak),
        "gate_queue_max_veh": max(int(r["gate_queue_halting"]) for r in rows),
        "gate_wait_mean_s": mean(float(r["gate_queue_waiting_s"]) for r in rows),
        "binding_intervals": meta["binding_intervals"],
        "throttle_steps": meta["throttle_steps"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rep-dir", required=True)
    ap.add_argument("--trip-class", required=True)
    ap.add_argument("--seeds", required=True)
    ap.add_argument("--cfgs", required=True)
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()

    cls = json.load(open(args.trip_class))["class"]
    seeds = args.seeds.split(",")
    cfgs = args.cfgs.split(",")
    os.makedirs(args.outdir, exist_ok=True)

    raw = {}
    for sd in seeds:
        for c in cfgs:
            d = os.path.join(args.rep_dir, f"s{sd}_{c}")
            if not os.path.exists(os.path.join(d, "run_meta.json")):
                print("MISSING", d)
                continue
            raw[(sd, c)] = metrics(d, cls)

    fields = list(next(iter(raw.values())).keys())
    with open(os.path.join(args.outdir, "seed_runs_raw.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["seed", "config"] + fields)
        for (sd, c), m in raw.items():
            w.writerow([sd, c] + [round(m[k], 3) if isinstance(m[k], float) else m[k]
                                  for k in fields])

    # ---- per-config mean +/- sd, and paired win counts vs. that seed's baseline
    summary = []
    for c in cfgs:
        rec = {"config": c, "n_seeds": sum(1 for sd in seeds if (sd, c) in raw)}
        for k in fields:
            vals = [raw[(sd, c)][k] for sd in seeds if (sd, c) in raw]
            rec[f"{k}_mean"] = round(mean(vals), 2)
            rec[f"{k}_sd"] = round(st.pstdev(vals), 2) if len(vals) > 1 else 0.0
        if c != "baseline":
            for k in ("mean_tt_s", "mean_tl_s", "arrived_by_3600s", "clearance_s",
                      "teleports", "core_prod_peak_vehkm"):
                dif = [raw[(sd, c)][k] - raw[(sd, "baseline")][k]
                       for sd in seeds if (sd, c) in raw and (sd, "baseline") in raw]
                rec[f"d_{k}_mean"] = round(mean(dif), 2)
                bmean = mean([raw[(sd, "baseline")][k] for sd in seeds
                              if (sd, "baseline") in raw])
                rec[f"d_{k}_pct"] = (round(100 * mean(dif) / bmean, 2)
                                     if bmean else float("nan"))
                if k in ("mean_tt_s", "mean_tl_s", "clearance_s", "teleports"):
                    rec[f"{k}_seeds_improved"] = sum(1 for x in dif if x < 0)
                else:
                    rec[f"{k}_seeds_improved"] = sum(1 for x in dif if x > 0)
        summary.append(rec)

    allk = []
    for r in summary:
        for k in r:
            if k not in allk:
                allk.append(k)
    with open(os.path.join(args.outdir, "seed_summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=allk)
        w.writeheader()
        for r in summary:
            w.writerow({k: r.get(k, "") for k in allk})

    # ---- markdown headline table
    show = [("mean_tt_s_mean", "mean travel time [s]"),
            ("mean_tl_s_mean", "mean time loss [s]"),
            ("tt_core_s_mean", "  CORE-destined TT [s]"),
            ("tt_through_s_mean", "  THROUGH TT [s]"),
            ("tt_outside_s_mean", "  OUTSIDE TT [s]"),
            ("arrived_by_3600s_mean", "completed trips by t=3600 s"),
            ("arrived_by_4914s_mean", "completed trips by t=4914 s"),
            ("clearance_s_mean", "network clearance time [s]"),
            ("n_peak_veh_mean", "peak core accumulation [veh]"),
            ("n_at_2400_veh_mean", "core accumulation at end of peak [veh]"),
            ("core_prod_peak_vehkm_mean", "core production over peak [veh-km]"),
            ("core_prod_total_vehkm_mean", "core production, whole run [veh-km]"),
            ("core_outflow_peak_veh_mean", "core exits over peak [veh]"),
            ("gate_queue_mean_veh_mean", "mean gate-approach queue [veh]"),
            ("gate_queue_peak_veh_mean", "mean gate-approach queue during peak [veh]"),
            ("gate_queue_max_veh_mean", "max gate-approach queue [veh]"),
            ("gate_wait_mean_s_mean", "mean gate-approach waiting [veh-s/60s]"),
            ("mean_depart_delay_s_mean", "mean depart delay [s]"),
            ("teleports_mean", "teleports"),
            ("collisions_mean", "collisions"),
            ("binding_intervals_mean", "intervals where gate bound"),
            ("throttle_steps_mean", "gate-throttled controller steps")]
    with open(os.path.join(args.outdir, "seed_summary.md"), "w") as f:
        f.write(f"# Multi-seed summary ({len(seeds)} seeds: {', '.join(seeds)})\n\n")
        f.write("Mean over seeds; identical network, demand, routes in every cell.\n\n")
        f.write("| metric | " + " | ".join(cfgs) + " |\n")
        f.write("|---" * (len(cfgs) + 1) + "|\n")
        bym = {r["config"]: r for r in summary}
        for k, lbl in show:
            f.write(f"| {lbl} | " + " | ".join(f"{bym[c].get(k, '')}" for c in cfgs) + " |\n")
        f.write("\n## Paired difference vs. the same seed's ungated baseline\n\n")
        f.write("| metric | " + " | ".join(c for c in cfgs if c != "baseline") + " |\n")
        f.write("|---" * (len([c for c in cfgs if c != 'baseline']) + 1) + "|\n")
        for k, lbl in [("mean_tt_s", "Δ mean travel time [s] (neg = better)"),
                       ("mean_tl_s", "Δ mean time loss [s]"),
                       ("arrived_by_3600s", "Δ completions by t=3600 s (pos = better)"),
                       ("clearance_s", "Δ clearance time [s]"),
                       ("teleports", "Δ teleports"),
                       ("core_prod_peak_vehkm", "Δ core production over peak [veh-km]")]:
            f.write(f"| {lbl} | " + " | ".join(
                f"{bym[c].get('d_'+k+'_mean','')} ({bym[c].get('d_'+k+'_pct','')}%) "
                f"[{bym[c].get(k+'_seeds_improved','')}/{len(seeds)} seeds]"
                for c in cfgs if c != "baseline") + " |\n")

    # ---- set-point response plot
    gcfgs = [c for c in cfgs if re.fullmatch(r"nset\d+", c)]
    xs = [float(c[4:]) for c in gcfgs]
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    xs = [xs[i] for i in order]
    gcfgs = [gcfgs[i] for i in order]
    bym = {r["config"]: r for r in summary}
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.8))
    for a, (k, lbl) in zip(ax, [("mean_tt_s", "mean travel time [s]"),
                                ("teleports", "teleports")]):
        m = [bym[c][f"{k}_mean"] for c in gcfgs]
        s = [bym[c][f"{k}_sd"] for c in gcfgs]
        a.errorbar(xs, m, yerr=s, marker="o", capsize=4, color="#2a6f97", label="gated")
        b = bym["baseline"][f"{k}_mean"]
        bs = bym["baseline"][f"{k}_sd"]
        a.axhline(b, color="#d1495b", ls="--", label="ungated baseline")
        a.fill_between([min(xs), max(xs)], b - bs, b + bs, color="#d1495b", alpha=0.12)
        a.set_xlabel("gating set-point n_set [veh]")
        a.set_ylabel(lbl)
        a.grid(alpha=0.3)
        a.legend(fontsize=8)
    fig.suptitle("Set-point response, mean ± sd over 8 seeds")
    fig.tight_layout()
    fig.savefig(os.path.join(args.outdir, "setpoint_response.png"), dpi=150)
    plt.close(fig)
    print("wrote", args.outdir)
    for r in summary:
        print(f"{r['config']:>12} TT={r['mean_tt_s_mean']:8.1f}±{r['mean_tt_s_sd']:6.1f} "
              f"TL={r['mean_tl_s_mean']:8.1f} arr3600={r['arrived_by_3600s_mean']:7.1f} "
              f"clr={r['clearance_s_mean']:7.0f} tel={r['teleports_mean']:6.1f} "
              f"nPeak={r['n_peak_veh_mean']:6.1f} prodPeak={r['core_prod_peak_vehkm_mean']:7.1f} "
              f"win={r.get('mean_tt_s_seeds_improved','-')}")


if __name__ == "__main__":
    main()
