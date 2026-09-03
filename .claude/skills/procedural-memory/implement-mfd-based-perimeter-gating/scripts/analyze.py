#!/usr/bin/env python3
"""
Analyse the perimeter-gating experiment:
  * per-run metrics from tripinfo / summary / statistics / the accumulation CSV
  * per-trip-class split (CORE-destined / THROUGH / OUTSIDE)
  * baseline MFD binning -> n_crit
  * route-fidelity check (driven route == duarouter route  =>  no rerouting)
  * MFD overlay plot + n(t) time-series plot
  * comparison table CSV + Markdown
"""
import argparse
import csv
import glob
import json
import os
import xml.etree.ElementTree as ET
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt   # noqa: E402


def read_tripinfo(path, cls):
    per = []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag != "tripinfo":
            continue
        per.append({
            "id": el.get("id"),
            "cls": cls.get(el.get("id"), "?"),
            "depart": float(el.get("depart")),
            "arrival": float(el.get("arrival")),
            "duration": float(el.get("duration")),
            "timeLoss": float(el.get("timeLoss")),
            "waitingTime": float(el.get("waitingTime")),
            "departDelay": float(el.get("departDelay")),
            "routeLength": float(el.get("routeLength")),
        })
        el.clear()
    return per


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def read_statistics(path):
    r = ET.parse(path).getroot()
    out = {}
    for tag in ("vehicles", "teleports", "safety", "vehicleTripStatistics"):
        el = r.find(tag)
        if el is not None:
            for k, v in el.attrib.items():
                out[f"{tag}.{k}"] = v
    return out


def route_fidelity(vehroutes, planned):
    """Fraction of vehicles whose DRIVEN edge sequence equals the planned one."""
    same = diff = 0
    examples = []
    for _, el in ET.iterparse(vehroutes, events=("end",)):
        if el.tag != "vehicle":
            continue
        vid = el.get("id")
        r = el.find("route")
        if r is not None and vid in planned:
            driven = r.get("edges")
            if driven == planned[vid]:
                same += 1
            else:
                diff += 1
                if len(examples) < 3:
                    examples.append((vid, planned[vid], driven))
        el.clear()
    return same, diff, examples


def mfd_bins(rows, width=20.0, warmup=120.0):
    b = defaultdict(list)
    for r in rows:
        if float(r["t_end"]) < warmup:
            continue
        n = float(r["n_mean"])
        if n <= 0:
            continue
        b[int(n // width)].append(float(r["production_vehkm_h"]))
    return {(k + 0.5) * width: (mean(v), len(v)) for k, v in sorted(b.items())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-dir", required=True)
    ap.add_argument("--labels", required=True, help="comma separated, baseline first")
    ap.add_argument("--trip-class", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--baseline-pool", default="",
                    help="glob of extra ungated accumulation CSVs pooled for n_crit")
    ap.add_argument("--overlay-labels", default="",
                    help="comma separated subset of labels to draw on the MFD overlay")
    ap.add_argument("--peak-start", type=float, default=600.0)
    ap.add_argument("--peak-end", type=float, default=2400.0)
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    tc = json.load(open(args.trip_class))
    cls = tc["class"]
    planned = tc["planned"]
    labels = args.labels.split(",")

    runs = {}
    for lab in labels:
        d = os.path.join(args.runs_dir, lab)
        rows = list(csv.DictReader(open(os.path.join(d, "accumulation_production.csv"))))
        trips = read_tripinfo(os.path.join(d, "tripinfo.xml"), cls)
        stats = read_statistics(os.path.join(d, "statistics.xml"))
        meta = json.load(open(os.path.join(d, "run_meta.json")))
        same, diffn, ex = route_fidelity(os.path.join(d, "vehroutes.xml"), planned)
        runs[lab] = {"rows": rows, "trips": trips, "stats": stats, "meta": meta,
                     "route_same": same, "route_diff": diffn, "route_ex": ex}

    base = runs[labels[0]]

    # ---------- n_crit from the pooled UNGATED baseline MFD ----------
    pool = list(base["rows"])
    n_pool_runs = 1
    if args.baseline_pool:
        for p in sorted(glob.glob(args.baseline_pool)):
            extra = list(csv.DictReader(open(p)))
            if extra == list(base["rows"]):
                continue          # same seed as the primary baseline: don't double count
            pool += extra
            n_pool_runs += 1
    bb = mfd_bins(pool)
    n_crit_bin = max(bb.items(), key=lambda kv: kv[1][0])
    n_crit = n_crit_bin[0]
    p_max = n_crit_bin[1][0]
    with open(os.path.join(args.outdir, "baseline_mfd_bins.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["n_bin_center_veh", "mean_production_vehkm_h", "n_intervals"])
        for k, (m, c) in bb.items():
            w.writerow([k, round(m, 2), c])

    # ---------- per-run metrics ----------
    horizons = [2400, 3000, 3600, 4914]
    table = []
    for lab in labels:
        R = runs[lab]
        trips, rows = R["trips"], R["rows"]
        rec = {"run": lab, "mode": R["meta"]["mode"], "n_set": R["meta"]["n_set"]}
        rec["arrived_total"] = len(trips)
        rec["sim_end_s"] = R["meta"]["sim_end"]
        for h in horizons:
            rec[f"arrived_by_{h}s"] = sum(1 for t in trips if t["arrival"] <= h)
        rec["mean_travel_time_s"] = round(mean(t["duration"] for t in trips), 2)
        rec["mean_time_loss_s"] = round(mean(t["timeLoss"] for t in trips), 2)
        rec["mean_waiting_s"] = round(mean(t["waitingTime"] for t in trips), 2)
        rec["mean_depart_delay_s"] = round(mean(t["departDelay"] for t in trips), 2)
        for k in ("core", "through", "outside"):
            sel = [t for t in trips if t["cls"] == k]
            rec[f"n_{k}"] = len(sel)
            rec[f"tt_{k}_s"] = round(mean(t["duration"] for t in sel), 2)
            rec[f"tl_{k}_s"] = round(mean(t["timeLoss"] for t in sel), 2)
        rec["teleports"] = int(R["stats"].get("teleports.total", 0))
        rec["collisions"] = int(R["stats"].get("safety.collisions", 0))

        n_series = [(float(r["t_end"]), float(r["n_mean"])) for r in rows]
        rec["n_peak_veh"] = round(max(n for _, n in n_series), 1)
        rec["n_at_peak_end_veh"] = round(
            min(n_series, key=lambda p: abs(p[0] - args.peak_end))[1], 1)
        peak_rows = [r for r in rows
                     if args.peak_start < float(r["t_end"]) <= args.peak_end]
        # production is veh*km/h over a 60 s interval -> veh*km = P * (60/3600)
        rec["core_production_peak_vehkm"] = round(
            sum(float(r["production_vehkm_h"]) for r in peak_rows) / 60.0, 2)
        rec["core_production_total_vehkm"] = round(
            sum(float(r["production_vehkm_h"]) for r in rows) / 60.0, 2)
        rec["core_outflow_peak_veh"] = sum(int(r["core_outflow_veh"]) for r in peak_rows)
        rec["gate_queue_mean_veh"] = round(mean(float(r["gate_queue_halting"]) for r in rows), 2)
        rec["gate_queue_max_veh"] = max(int(r["gate_queue_halting"]) for r in rows)
        rec["gate_wait_mean_s"] = round(mean(float(r["gate_queue_waiting_s"]) for r in rows), 1)
        rec["max_pending_insertion"] = max(int(r["pending_insertion"]) for r in rows)
        rec["binding_intervals"] = R["meta"]["binding_intervals"]
        rec["throttle_steps"] = R["meta"]["throttle_steps"]
        rec["route_match"] = R["route_same"]
        rec["route_mismatch"] = R["route_diff"]
        table.append(rec)

    keys = list(table[0].keys())
    with open(os.path.join(args.outdir, "comparison_table.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(table)

    # markdown (transposed: metrics as rows, runs as columns)
    with open(os.path.join(args.outdir, "comparison_table.md"), "w") as f:
        f.write("# Perimeter gating - run comparison\n\n")
        f.write("| metric | " + " | ".join(r["run"] for r in table) + " |\n")
        f.write("|---" * (len(table) + 1) + "|\n")
        for k in keys:
            if k == "run":
                continue
            f.write(f"| {k} | " + " | ".join(str(r[k]) for r in table) + " |\n")
        f.write(f"\n**n_crit (baseline, {20:.0f}-veh bins, argmax of mean production) "
                f"= {n_crit:.0f} veh, P_max = {p_max:.0f} veh-km/h**\n")

    # ---------- plots ----------
    ov = args.overlay_labels.split(",") if args.overlay_labels else labels
    colors = plt.cm.viridis([i / max(len(ov) - 1, 1) for i in range(len(ov))])
    fig, ax = plt.subplots(figsize=(9, 6.5))
    for lab, c in zip(ov, colors):
        rows = runs[lab]["rows"]
        n = [float(r["n_mean"]) for r in rows]
        p = [float(r["production_vehkm_h"]) for r in rows]
        if lab == ov[0]:
            ax.scatter(n, p, s=46, facecolors="none", edgecolors="#d1495b",
                       linewidths=1.4, label=lab, zorder=3)
        else:
            ax.scatter(n, p, s=20, color=c, alpha=0.75, label=lab)
    bx = list(bb.keys())
    by = [v[0] for v in bb.values()]
    ax.plot(bx, by, "k-", lw=2.4, alpha=0.85,
            label=f"pooled ungated baseline, binned mean ({n_pool_runs} seeds)")
    ax.axvline(n_crit, color="k", ls="--", lw=1.2)
    ax.annotate(f"n_crit ≈ {n_crit:.0f} veh", (n_crit, p_max * 1.02),
                ha="center", fontsize=10)
    ax.set_xlabel("core accumulation n(t)  [veh]")
    ax.set_ylabel("core production  [veh·km/h]")
    ax.set_title("Core MFD: production vs accumulation (60 s intervals)")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="lower left")
    fig.tight_layout()
    fig.savefig(os.path.join(args.outdir, "mfd_overlay.png"), dpi=150)
    plt.close(fig)

    # hysteresis view of the baseline alone (loading vs unloading)
    fig, ax = plt.subplots(figsize=(8, 6))
    rows = base["rows"]
    n = [float(r["n_mean"]) for r in rows]
    p = [float(r["production_vehkm_h"]) for r in rows]
    t = [float(r["t_end"]) for r in rows]
    ax.plot(n, p, "-", color="0.7", lw=1)
    sc = ax.scatter(n, p, c=t, cmap="plasma", s=45, zorder=3)
    plt.colorbar(sc, ax=ax, label="time [s]")
    ax.axvline(n_crit, color="k", ls="--", lw=1.2, label=f"n_crit ≈ {n_crit:.0f}")
    ax.set_xlabel("core accumulation n(t) [veh]")
    ax.set_ylabel("core production [veh·km/h]")
    ax.set_title("Ungated baseline core MFD - clockwise hysteresis loop")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(args.outdir, "baseline_mfd_hysteresis.png"), dpi=150)
    plt.close(fig)

    fig, axes = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
    tcolors = plt.cm.viridis([i / max(len(labels) - 1, 1) for i in range(len(labels))])
    for lab, c in zip(labels, tcolors):
        rows = runs[lab]["rows"]
        tt = [float(r["t_end"]) for r in rows]
        nn = [float(r["n_mean"]) for r in rows]
        qq = [float(r["gate_queue_halting"]) for r in rows]
        style = dict(lw=2.4, color="#d1495b") if lab == labels[0] else dict(lw=1.4, color=c)
        axes[0].plot(tt, nn, label=lab, **style)
        axes[1].plot(tt, qq, label=lab, **style)
    axes[0].axhline(n_crit, color="k", ls="--", lw=1.1)
    axes[0].text(20, n_crit + 4, f"n_crit ≈ {n_crit:.0f}", fontsize=9)
    axes[0].set_ylabel("core accumulation n(t) [veh]")
    axes[0].set_title("Core accumulation and perimeter gate queue")
    axes[0].grid(alpha=0.3)
    axes[0].legend(fontsize=8, ncol=2)
    axes[1].set_ylabel("halting veh on gate approaches")
    axes[1].set_xlabel("time [s]")
    axes[1].grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(args.outdir, "accumulation_timeseries.png"), dpi=150)
    plt.close(fig)

    json.dump({"n_crit_veh": n_crit, "p_max_vehkm_h": round(p_max, 2),
               "bin_width_veh": 20.0,
               "pooled_baseline_runs": n_pool_runs,
               "method": "60 s intervals of the ungated baseline runs, binned by mean "
                         "accumulation in 20-veh bins (warm-up <120 s dropped); "
                         "n_crit = centre of the bin with the highest mean production"},
              open(os.path.join(args.outdir, "n_crit.json"), "w"), indent=2)

    print(f"n_crit = {n_crit:.0f} veh   P_max = {p_max:.0f} veh-km/h")
    for r in table:
        print(f"{r['run']:>16}  TT={r['mean_travel_time_s']:8.1f}  TL={r['mean_time_loss_s']:8.1f}  "
              f"n_peak={r['n_peak_veh']:6.1f}  arr@3600={r['arrived_by_3600s']:5d}  "
              f"end={r['sim_end_s']:7.0f}  tele={r['teleports']:5d}  "
              f"routeMismatch={r['route_mismatch']}")


if __name__ == "__main__":
    main()
