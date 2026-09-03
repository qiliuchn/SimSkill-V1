#!/usr/bin/env python3
"""Collect every run's analysis.json into CSV tables + figures."""
import csv
import json
import os
import sys

EP = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
RUNS = os.path.join(EP, "outputs", "runs")
OUT = os.path.join(EP, "outputs", "tables")
FIG = os.path.join(EP, "outputs", "figures")

ORDER = ["baseline_drive", "A_parkingAreas", "A_ptStops", "A_allJunctions",
         "D_cap200", "D_cap100", "D_cap50", "D_cap20",
         "E_cap100_rr", "E_cap50_rr", "E_cap20_rr",
         "S_suburban", "S_intermediate",
         "H_hw120", "H_hw600", "H_hw900", "P_pm_return"]


def load(name):
    p = os.path.join(RUNS, name, "analysis.json")
    if not os.path.exists(p):
        return None
    return json.load(open(p))


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(FIG, exist_ok=True)
    rows, decomp, links = [], [], []
    occ_series = {}
    for name in ORDER:
        d = load(name)
        if d is None:
            continue
        s = d["summary"]
        by = {r["mode"]: r for r in s["by_mode"]}
        pr = by.get("park_and_ride", {})
        da = by.get("drive_alone", {})
        n_ok = s["n_completed"]
        rows.append({
            "case": name,
            "n_persons": s["n_persons"],
            "completed": n_ok,
            "never_arrived": s["n_never_arrived"],
            "no_vehicle_ride": s["n_no_vehicle_ride"],
            "teleports": s.get("teleports", ""),
            "pr_n": pr.get("n", 0),
            "pr_share_of_completed": round(pr.get("n", 0) / n_ok, 4) if n_ok else 0,
            "pr_share_of_all": round(pr.get("n", 0) / s["n_persons"], 4),
            "drive_n": da.get("n", 0),
            "mean_total_all_s": round(s["mean_total_s"], 1),
            "mean_total_pr_s": round(pr.get("mean_total_s", 0), 1),
            "mean_total_drive_s": round(da.get("mean_total_s", 0), 1),
            "person_hours_completed": round(s["person_hours_completed"], 1),
            "person_hours_lower_bound": round(s["person_hours_total_lb"], 1),
            "peak_occ": json.dumps(s.get("peak_occupancy", {})),
        })
        for m, r in by.items():
            decomp.append({"case": name, "mode": m, "n": r["n"],
                           "total_s": round(r["mean_total_s"], 1),
                           "drive_s": round(r["mean_drive_s"], 1),
                           "walk_access_s": round(r["mean_access_s"], 1),
                           "wait_s": round(r["mean_wait_s"], 1),
                           "ride_s": round(r["mean_ride_s"], 1),
                           "egress_s": round(r["mean_egress_s"], 1)})
        for eid, v in sorted(s.get("arterial", {}).items()):
            links.append({"case": name, "edge": eid, "entered": int(v["entered"]),
                          "mean_traveltime_s": round(v["traveltime_mean"], 1),
                          "total_timeLoss_s": round(v["timeLoss"], 0)})
        for eid, v in sorted(s.get("cbd_gate", {}).items()):
            if eid not in [l["edge"] for l in links if l["case"] == name]:
                links.append({"case": name, "edge": eid, "entered": int(v["entered"]),
                              "mean_traveltime_s": round(v["traveltime_mean"], 1),
                              "total_timeLoss_s": round(v["timeLoss"], 0)})
        if "occupancy_series" in s:
            occ_series[name] = s["occupancy_series"]

    def dump(path, data):
        if not data:
            return
        with open(path, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(data[0].keys()))
            w.writeheader()
            w.writerows(data)
        print("wrote", path, len(data), "rows")

    dump(os.path.join(OUT, "summary_by_case.csv"), rows)
    dump(os.path.join(OUT, "traveltime_decomposition.csv"), decomp)
    dump(os.path.join(OUT, "corridor_links.csv"), links)
    with open(os.path.join(OUT, "lot_occupancy_series.json"), "w") as fh:
        json.dump(occ_series, fh)

    # ---- figures -----------------------------------------------------------
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib unavailable; skipping figures")
        return

    # fig 1: lot occupancy over time
    fig, ax = plt.subplots(figsize=(9, 4.5))
    for name in ["A_parkingAreas", "D_cap100", "D_cap50", "E_cap50_rr"]:
        s = occ_series.get(name)
        if not s:
            continue
        for lot, series in s["occ"].items():
            if max(series) == 0:
                continue
            ax.plot([t / 3600.0 for t in s["t"]], series, label="%s / %s" % (name, lot))
    ax.set_xlabel("simulation time (h)")
    ax.set_ylabel("vehicles parked in lot")
    ax.set_title("P+R lot accumulation (spaces held, no turnover in an AM-only peak)")
    ax.legend(fontsize=7)
    ax.grid(alpha=.3)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "lot_occupancy.png"), dpi=130)

    # fig 2: capacity sweep
    caps, share, strand, ph = [], [], [], []
    for name, c in [("A_parkingAreas", 400), ("D_cap200", 200), ("D_cap100", 100),
                    ("D_cap50", 50), ("D_cap20", 20)]:
        d = load(name)
        if not d:
            continue
        s = d["summary"]
        by = {r["mode"]: r for r in s["by_mode"]}
        caps.append(c)
        share.append(by.get("park_and_ride", {}).get("n", 0) / s["n_persons"] * 100)
        strand.append(s["n_never_arrived"])
        ph.append(s["person_hours_total_lb"])
    if caps:
        o = sorted(range(len(caps)), key=lambda i: caps[i])
        caps = [caps[i] for i in o]; share = [share[i] for i in o]
        strand = [strand[i] for i in o]; ph = [ph[i] for i in o]
        fig, axs = plt.subplots(1, 3, figsize=(12, 3.6))
        axs[0].plot(caps, share, "o-"); axs[0].set_ylabel("realised P+R share (%)")
        axs[1].plot(caps, strand, "o-", color="crimson"); axs[1].set_ylabel("persons never arriving")
        axs[2].plot(caps, ph, "o-", color="seagreen"); axs[2].set_ylabel("corridor person-hours (LB)")
        for a in axs:
            a.set_xlabel("PR_MID capacity (spaces)"); a.grid(alpha=.3)
        fig.suptitle("Undersized P+R lot: routing is capacity-blind, so surplus demand fails")
        fig.tight_layout()
        fig.savefig(os.path.join(FIG, "capacity_sweep.png"), dpi=130)

    # fig 3: door-to-door decomposition
    cases = [c for c in ["baseline_drive", "A_parkingAreas", "A_ptStops", "A_allJunctions"]
             if load(c)]
    fig, ax = plt.subplots(figsize=(9, 4.2))
    parts = ["drive_s", "walk_access_s", "wait_s", "ride_s", "egress_s"]
    labels, bottoms = [], []
    idx = 0
    for c in cases:
        for m in ["drive_alone", "park_and_ride"]:
            r = [x for x in decomp if x["case"] == c and x["mode"] == m]
            if not r:
                continue
            r = r[0]
            b = 0
            for p in parts:
                ax.bar(idx, r[p], bottom=b, color=dict(zip(parts, ["#4C6EF5", "#F59F00", "#E03131", "#2F9E44", "#9C36B5"]))[p],
                       label=p if idx == 0 else None)
                b += r[p]
            labels.append("%s\n%s (n=%d)" % (c.replace("A_", ""), m, r["n"]))
            idx += 1
    ax.set_xticks(range(idx)); ax.set_xticklabels(labels, fontsize=6.5)
    ax.set_ylabel("mean door-to-door time (s)")
    ax.set_title("Door-to-door time decomposition by option and car-walk transfer setting")
    ax.legend(fontsize=8); ax.grid(alpha=.3, axis="y")
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "traveltime_decomposition.png"), dpi=130)
    print("figures written to", FIG)


if __name__ == "__main__":
    main()
