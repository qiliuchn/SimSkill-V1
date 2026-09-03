"""
Build the macroscopic fundamental diagram (flow-density-speed) from a demand
sweep's E1 induction-loop output at one multi-lane measurement station.

For each run, over a steady-state window [--warmup, --end]:
  q = sum of per-lane flow                              [veh/h]
  v = space-mean (count-weighted harmonic) speed         [km/h]
  k = density, two independent estimators:
        k_qv  = q / v                (fundamental relation q = k*v)
        k_occ = sum_lane 10*occ_lane/length_lane         (from E1 occupancy)
Per-lane density is computed as q_i / v_harm_i and summed, so cross-section
space-mean speed = q_total / k_total -- this correctly handles uneven lane
loading (free flow: vehicles favor one lane; congestion: spread across all).

Requires one run directory per demand level, each containing the station's E1
output (--e1-filename, default e1_mfd.xml) with one <interval id=...> per lane
per aggregation period.

Usage:
    python build_fundamental_diagram.py \
        --runs-dir outputs --rates 600,1200,1500,1800,2000,2200,2500,2600,2700,2800,2900,3000,3500,4000,5000,6000,7000 \
        --run-dir-template "q{rate}" --e1-filename e1_mfd.xml \
        --warmup 1800 --end 3600 --free-speed-threshold-kmh 60 \
        --single-lane-speed-ms 33.33 --veh-length-m 5.0 --min-gap-m 2.5 --tau-s 1.0 --n-downstream-lanes 1 \
        --out-csv mfd_points.csv --out-json fd_summary.json --plots-dir plots/
"""

import argparse
import csv
import json
import os
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def parse_args():
    p = argparse.ArgumentParser(description="Build a macroscopic fundamental diagram from an E1 demand sweep.")
    p.add_argument("--runs-dir", required=True)
    p.add_argument("--rates", required=True, help="Comma-separated demand levels (veh/h total), one run per level")
    p.add_argument("--run-dir-template", default="q{rate}", help="Per-rate subdirectory name template under --runs-dir")
    p.add_argument("--e1-filename", default="e1_mfd.xml")
    p.add_argument("--warmup", type=float, default=1800.0, help="Discard intervals before this time (s)")
    p.add_argument("--end", type=float, default=3600.0)
    p.add_argument("--free-speed-threshold-kmh", type=float, default=60.0, help="Below this space-mean speed, classify the run as congested")
    p.add_argument("--single-lane-speed-ms", type=float, default=33.33, help="Free-flow speed (m/s) for the theoretical single-lane capacity bound")
    p.add_argument("--veh-length-m", type=float, default=5.0)
    p.add_argument("--min-gap-m", type=float, default=2.5)
    p.add_argument("--tau-s", type=float, default=1.0, help="vType's desired time headway (tau)")
    p.add_argument("--n-downstream-lanes", type=int, default=1, help="Number of lanes at the bottleneck the station's flow must funnel through")
    p.add_argument("--out-csv", default="mfd_points.csv")
    p.add_argument("--out-json", default="fd_summary.json")
    p.add_argument("--plots-dir", default="plots")
    return p.parse_args()


def analyze_run(e1_path, warmup, end):
    root = ET.parse(e1_path).getroot()
    lanes = {}
    for iv in root.findall("interval"):
        if float(iv.get("begin")) < warmup:
            continue
        lid = iv.get("id")
        d = lanes.setdefault(lid, {"n": 0, "sum_inv_v": 0.0, "occ": [], "len": []})
        n = int(iv.get("nVehContrib"))
        v = float(iv.get("harmonicMeanSpeed"))
        occ = float(iv.get("occupancy"))
        length = float(iv.get("length"))
        d["n"] += n
        if n > 0 and v > 0:
            d["sum_inv_v"] += n / v
        d["occ"].append(occ)
        if length > 0:
            d["len"].append(length)

    dur = end - warmup
    q_total = k_qv_total = k_occ_total = inv_v_all = 0.0
    n_all = 0
    for d in lanes.values():
        q_i = d["n"] / dur * 3600.0
        q_total += q_i
        if d["n"] > 0 and d["sum_inv_v"] > 0:
            v_i = d["n"] / d["sum_inv_v"]
            k_qv_total += q_i / (v_i * 3.6)
            n_all += d["n"]
            inv_v_all += d["sum_inv_v"]
        mean_len = np.mean(d["len"]) if d["len"] else 5.0
        occ_mean = np.mean(d["occ"]) if d["occ"] else 0.0
        k_occ_total += 10.0 * occ_mean / mean_len
    v_space = (n_all / inv_v_all) * 3.6 if inv_v_all > 0 else float("nan")
    return q_total, v_space, k_qv_total, k_occ_total


def main():
    args = parse_args()
    os.makedirs(args.plots_dir, exist_ok=True)
    rates = [int(r) for r in args.rates.split(",")]

    rows = []
    for rate in rates:
        e1_path = os.path.join(args.runs_dir, args.run_dir_template.format(rate=rate), args.e1_filename)
        q, v, k_qv, k_occ = analyze_run(e1_path, args.warmup, args.end)
        regime = "free" if (v == v and v >= args.free_speed_threshold_kmh) else "congested"
        rows.append(dict(demand=rate, q=q, v=v, k_qv=k_qv, k_occ=k_occ, regime=regime))

    with open(args.out_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["demand_vph", "flow_q_vph", "speed_v_kmh", "density_kqv_vpkm", "density_kocc_vpkm", "regime"])
        for r in rows:
            w.writerow([r["demand"], f"{r['q']:.1f}", f"{r['v']:.2f}", f"{r['k_qv']:.2f}", f"{r['k_occ']:.2f}", r["regime"]])
    print(f"wrote {args.out_csv}")
    for r in rows:
        print(f"  demand={r['demand']:>5}  q={r['q']:>6.0f}  v={r['v']:>6.1f}km/h  "
              f"k_qv={r['k_qv']:>6.1f}  k_occ={r['k_occ']:>6.1f}  {r['regime']}")

    free = [r for r in rows if r["regime"] == "free"]
    cong = [r for r in rows if r["regime"] == "congested"]
    capacity = max(r["q"] for r in rows)
    cap_row = max(rows, key=lambda r: r["q"])
    k_crit = cap_row["k_qv"]
    v_free = float(np.mean([r["v"] for r in free])) if free else float("nan")
    q_disch = float(np.mean([r["q"] for r in cong])) if cong else float("nan")
    kc = float(np.mean([r["k_qv"] for r in cong])) if cong else float("nan")
    k_occ_deep = max((r["k_occ"] for r in cong), default=float("nan"))

    # Jam density: a two-point extrapolation of the congested branch to q=0 is
    # ill-conditioned if that branch is a tight cluster rather than a real spread
    # reaching standstill -- report it only as an unreliable upper bound alongside
    # the physically-grounded standstill estimate.
    if cong and abs(kc - k_crit) > 1e-6:
        w_slope = (q_disch - capacity) / (kc - k_crit)
        k_jam_extrap = kc - q_disch / w_slope
    else:
        k_jam_extrap = float("nan")
    k_jam_theory = 1000.0 / (args.veh_length_m + args.min_gap_m) * args.n_downstream_lanes

    c_single_lane_theory = (args.single_lane_speed_ms / (args.single_lane_speed_ms * args.tau_s
                             + args.veh_length_m + args.min_gap_m) * 3600.0 * args.n_downstream_lanes)

    summary = dict(capacity_vph=round(capacity), k_crit_vpkm=round(k_crit, 1), v_free_kmh=round(v_free, 1),
                   q_discharge_vph=round(q_disch) if q_disch == q_disch else None,
                   cap_drop_pct=round(100 * (capacity - q_disch) / capacity, 1) if q_disch == q_disch else None,
                   k_cong_mean_vpkm=round(kc, 1) if kc == kc else None,
                   k_deepest_measured_vpkm=round(k_occ_deep, 1) if k_occ_deep == k_occ_deep else None,
                   k_jam_theory_standstill_vpkm=round(k_jam_theory, 1),
                   k_jam_extrap_UNRELIABLE_vpkm=round(k_jam_extrap, 1) if k_jam_extrap == k_jam_extrap else None,
                   single_lane_theory_capacity_vph=round(c_single_lane_theory),
                   capacity_within_single_lane_bound=bool(capacity <= c_single_lane_theory),
                   discharge_within_single_lane_bound=bool(q_disch <= c_single_lane_theory) if q_disch == q_disch else None)
    print("\nFD SUMMARY:", summary)
    with open(args.out_json, "w") as f:
        json.dump(summary, f, indent=2)

    free_k, free_q, free_v = [r["k_qv"] for r in free], [r["q"] for r in free], [r["v"] for r in free]
    cong_k, cong_q, cong_v = [r["k_qv"] for r in cong], [r["q"] for r in cong], [r["v"] for r in cong]

    plt.figure(figsize=(7, 5))
    plt.scatter(free_k, free_q, c="#1f77b4", s=60, label="free-flow", zorder=3)
    plt.scatter(cong_k, cong_q, c="#d62728", s=60, label="congested", zorder=3)
    plt.axhline(capacity, ls="--", c="gray", lw=1, label=f"capacity ≈ {round(capacity)} veh/h")
    if q_disch == q_disch:
        plt.axhline(q_disch, ls=":", c="orange", lw=1, label=f"queued discharge ≈ {round(q_disch)} veh/h")
    for r in rows:
        plt.annotate(str(r["demand"]), (r["k_qv"], r["q"]), fontsize=6, xytext=(3, 3), textcoords="offset points")
    plt.xlabel("density k [veh/km]"); plt.ylabel("flow q [veh/h]")
    plt.title("Fundamental diagram: flow vs density"); plt.legend(fontsize=8); plt.grid(alpha=.3)
    plt.tight_layout(); plt.savefig(os.path.join(args.plots_dir, "fd_flow_density.png"), dpi=130); plt.close()

    plt.figure(figsize=(7, 5))
    plt.scatter(free_k, free_v, c="#1f77b4", s=60, label="free-flow", zorder=3)
    plt.scatter(cong_k, cong_v, c="#d62728", s=60, label="congested", zorder=3)
    plt.axvline(k_crit, ls="--", c="gray", lw=1, label=f"critical k ≈ {round(k_crit, 1)} veh/km")
    plt.xlabel("density k [veh/km]"); plt.ylabel("space-mean speed v [km/h]")
    plt.title("Fundamental diagram: speed vs density"); plt.legend(fontsize=8); plt.grid(alpha=.3)
    plt.tight_layout(); plt.savefig(os.path.join(args.plots_dir, "fd_speed_density.png"), dpi=130); plt.close()

    plt.figure(figsize=(7, 5))
    plt.scatter(free_v, free_q, c="#1f77b4", s=60, label="free-flow", zorder=3)
    plt.scatter(cong_v, cong_q, c="#d62728", s=60, label="congested", zorder=3)
    plt.axhline(capacity, ls="--", c="gray", lw=1, label=f"capacity ≈ {round(capacity)} veh/h")
    plt.xlabel("space-mean speed v [km/h]"); plt.ylabel("flow q [veh/h]")
    plt.title("Fundamental diagram: flow vs speed"); plt.legend(fontsize=8); plt.grid(alpha=.3)
    plt.tight_layout(); plt.savefig(os.path.join(args.plots_dir, "fd_flow_speed.png"), dpi=130); plt.close()

    print(f"\nplots + {args.out_json} written to {args.plots_dir}")


if __name__ == "__main__":
    main()
