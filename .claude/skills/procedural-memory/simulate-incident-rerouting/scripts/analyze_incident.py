"""
Post-process a baseline (no rerouting device) vs dynamic-rerouting incident scenario:
comparison table, diversion analysis, and plots.

Usage:
    python analyze_incident.py \
        --baseline-dir outputs/baseline --dynamic-dir outputs/dynamic \
        --incident-begin 600 --incident-end 1500 \
        --incident-edge AC --detour-edge AP \
        --out-dir analysis/ --plots-dir plots/

Expects each run directory to contain tripinfo.xml, summary.xml, edgedata.xml, vehroutes.xml
(with --vehroute-output.exit-times true), queue.xml, and stats.xml (--statistic-output) --
see simulate-incident-rerouting's SKILL.md for the exact sumo flags that produce these.
"""

import argparse
import csv
import os
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def parse_args():
    p = argparse.ArgumentParser(description="Compare baseline vs dynamic-rerouting incident scenarios.")
    p.add_argument("--baseline-dir", required=True)
    p.add_argument("--dynamic-dir", required=True)
    p.add_argument("--incident-begin", type=float, required=True)
    p.add_argument("--incident-end", type=float, required=True)
    p.add_argument("--incident-edge", required=True, help="A main-route edge whose speed/queue reflects the closure (for the time-series plot)")
    p.add_argument("--detour-edge", required=True, help="A detour-exclusive edge id, used both for the plot and to classify a vehicle's route as main vs detour")
    p.add_argument("--out-dir", default="analysis")
    p.add_argument("--plots-dir", default="plots")
    return p.parse_args()


def trip_stats(run_dir):
    f = os.path.join(run_dir, "tripinfo.xml")
    n = 0
    dur = wait = tloss = ddelay = rlen = 0.0
    for _, el in ET.iterparse(f, events=("end",)):
        if el.tag == "tripinfo":
            n += 1
            dur += float(el.get("duration"))
            wait += float(el.get("waitingTime"))
            tloss += float(el.get("timeLoss"))
            ddelay += float(el.get("departDelay"))
            rlen += float(el.get("routeLength"))
            el.clear()
    if n == 0:
        raise SystemExit(f"{f}: no <tripinfo> elements -- check the run for gridlock/config errors.")
    return {
        "arrived": n, "mean_dur": dur / n, "total_dur": dur, "mean_wait": wait / n,
        "mean_tloss": tloss / n, "total_tloss": tloss, "mean_ddelay": ddelay / n,
        "total_ddelay": ddelay, "mean_rlen": rlen / n, "total_system_time": dur + ddelay,
    }


def teleports(run_dir):
    p = os.path.join(run_dir, "stats.xml")
    if not os.path.isfile(p):
        return 0
    s = ET.parse(p).getroot().find("teleports")
    return int(s.get("total")) if s is not None else 0


def edge_series(run_dir):
    """{edge_id: [(t_begin, meanSpeed, meanVehCount)]} from edgeData."""
    root = ET.parse(os.path.join(run_dir, "edgedata.xml")).getroot()
    series = {}
    for iv in root.findall("interval"):
        b, e_ = float(iv.get("begin")), float(iv.get("end"))
        dt = e_ - b
        for e in iv.findall("edge"):
            spd = e.get("speed")
            samp = e.get("sampledSeconds")
            spd = float(spd) if spd not in (None, "") else float("nan")
            veh = (float(samp) / dt) if samp not in (None, "") else 0.0
            series.setdefault(e.get("id"), []).append((b, spd, veh))
    return series


def detour_timeseries(run_dir, detour_edge):
    root = ET.parse(os.path.join(run_dir, "edgedata.xml")).getroot()
    times, cum = [], []
    c = 0
    for iv in root.findall("interval"):
        b = float(iv.get("begin"))
        n = 0
        for e in iv.findall("edge"):
            if e.get("id") == detour_edge:
                n = int(e.get("entered") or 0)
        c += n
        times.append(b)
        cum.append(c)
    return times, cum


def route_split(run_dir, detour_edge):
    """Classify each vehicle main vs detour from vehroutes; a rerouted vehicle carries a
    <routeDistribution> whose LAST <route> is the actually-driven one."""
    f = os.path.join(run_dir, "vehroutes.xml")
    main = detour = 0
    detour_departs = []
    for _, v in ET.iterparse(f, events=("end",)):
        if v.tag == "vehicle":
            routes = v.findall(".//route")
            edges = routes[-1].get("edges") if routes else ""
            dep = float(v.get("depart"))
            if detour_edge in edges.split():
                detour += 1
                detour_departs.append(dep)
            else:
                main += 1
            v.clear()
    return main, detour, sorted(detour_departs)


def max_queue(run_dir):
    f = os.path.join(run_dir, "queue.xml")
    if not os.path.isfile(f):
        return float("nan"), None
    mx, mx_t = 0.0, None
    for _, el in ET.iterparse(f, events=("end",)):
        if el.tag == "data":
            t = float(el.get("timestep"))
            lanes = el.find("lanes")
            tot = sum(float(ln.get("queueing_length") or 0.0) for ln in lanes.findall("lane")) if lanes is not None else 0.0
            if tot > mx:
                mx, mx_t = tot, t
            el.clear()
    return mx, mx_t


def pct(base, dyn):
    return float("nan") if base == 0 else 100.0 * (dyn - base) / base


def main():
    args = parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    os.makedirs(args.plots_dir, exist_ok=True)

    dirs = {"baseline": args.baseline_dir, "dynamic": args.dynamic_dir}
    stats = {}
    for name, d in dirs.items():
        s = trip_stats(d)
        s["teleports"] = teleports(d)
        m, det, deps = route_split(d, args.detour_edge)
        s["route_main"], s["route_detour"], s["detour_departs"] = m, det, deps
        s["max_queue_m"], s["max_queue_t"] = max_queue(d)
        stats[name] = s

    b, d = stats["baseline"], stats["dynamic"]
    rows = [
        ("Arrived vehicles (throughput)", b["arrived"], d["arrived"], pct(b["arrived"], d["arrived"])),
        ("Mean travel time (in-network) [s]", b["mean_dur"], d["mean_dur"], pct(b["mean_dur"], d["mean_dur"])),
        ("Total travel time (in-network) [s]", b["total_dur"], d["total_dur"], pct(b["total_dur"], d["total_dur"])),
        ("Mean time loss [s]", b["mean_tloss"], d["mean_tloss"], pct(b["mean_tloss"], d["mean_tloss"])),
        ("Mean waiting time [s]", b["mean_wait"], d["mean_wait"], pct(b["mean_wait"], d["mean_wait"])),
        ("Mean depart delay [s]", b["mean_ddelay"], d["mean_ddelay"], pct(b["mean_ddelay"], d["mean_ddelay"])),
        ("Total system time (net+depart) [s]", b["total_system_time"], d["total_system_time"], pct(b["total_system_time"], d["total_system_time"])),
        ("Max network queue length [m]", b["max_queue_m"], d["max_queue_m"], pct(b["max_queue_m"], d["max_queue_m"])),
        ("Teleports", b["teleports"], d["teleports"], pct(b["teleports"], d["teleports"])),
        ("Vehicles via MAIN route", b["route_main"], d["route_main"], pct(b["route_main"], d["route_main"])),
        ("Vehicles via DETOUR", b["route_detour"], d["route_detour"], float("nan")),
    ]

    csv_path = os.path.join(args.out_dir, "comparison_table.csv")
    with open(csv_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["metric", "baseline", "dynamic_rerouting", "pct_change"])
        for name, bv, dv, p in rows:
            w.writerow([name, f"{bv:.2f}" if isinstance(bv, float) else bv,
                        f"{dv:.2f}" if isinstance(dv, float) else dv,
                        "" if p != p else f"{p:+.1f}%"])

    print(f"{'METRIC':<40}{'BASELINE':>15}{'DYNAMIC':>15}{'% CHANGE':>15}")
    for name, bv, dv, p in rows:
        bs = f"{bv:.2f}" if isinstance(bv, float) else str(bv)
        ds = f"{dv:.2f}" if isinstance(dv, float) else str(dv)
        ps = "" if p != p else f"{p:+.1f}%"
        print(f"{name:<40}{bs:>15}{ds:>15}{ps:>15}")

    with open(os.path.join(args.out_dir, "diversion_summary.txt"), "w") as fh:
        for name in dirs:
            deps = stats[name]["detour_departs"]
            tot = stats[name]["route_main"] + stats[name]["route_detour"]
            frac = 100.0 * stats[name]["route_detour"] / tot if tot else 0.0
            first = min(deps) if deps else None
            line = f"[{name}] detour={stats[name]['route_detour']}/{tot} ({frac:.1f}%); first_detour_depart={first if first is not None else 'NA'}"
            print(line)
            fh.write(line + "\n")

    # Plot 1: incident-edge and detour speed + vehicle-count time series
    es = {name: edge_series(d) for name, d in dirs.items()}
    colors = {"baseline": "#d62728", "dynamic": "#1f77b4"}
    fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=True)
    for ax, idx, ylabel, title in [
        (axes[0], 1, "mean speed [m/s]", f"Incident-edge ({args.incident_edge}) vs detour ({args.detour_edge}) mean speed"),
        (axes[1], 2, "mean vehicles on edge", "Mean vehicle count — flow shifts onto the detour only when rerouting is enabled"),
    ]:
        for name in dirs:
            ser = es[name].get(args.incident_edge, [])
            ax.plot([x[0] for x in ser], [x[idx] for x in ser], color=colors[name], lw=2, label=f"{name} — {args.incident_edge} (main)")
            serd = es[name].get(args.detour_edge, [])
            ax.plot([x[0] for x in serd], [x[idx] for x in serd], color=colors[name], lw=1.5, ls="--", label=f"{name} — {args.detour_edge} (detour)")
        ax.axvspan(args.incident_begin, args.incident_end, color="grey", alpha=0.15)
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.legend(fontsize=8, ncol=2)
        ax.grid(alpha=0.3)
    axes[1].set_xlabel("simulation time [s]")
    fig.tight_layout()
    p1 = os.path.join(args.plots_dir, "incident_edge_and_detour_timeseries.png")
    fig.savefig(p1, dpi=130)
    plt.close(fig)

    # Plot 2: cumulative detour uptake (diversion timing)
    fig, ax = plt.subplots(figsize=(11, 4.5))
    for name, d_ in dirs.items():
        t, cum = detour_timeseries(d_, args.detour_edge)
        ax.plot(t, cum, color=colors[name], lw=2, marker="o", ms=3, label=f"{name} cumulative detour entries")
    ax.axvspan(args.incident_begin, args.incident_end, color="grey", alpha=0.15, label="incident window")
    ax.set_xlabel("simulation time [s]")
    ax.set_ylabel("cumulative vehicles entering detour")
    ax.set_title("How quickly vehicles rerouted onto the detour after the incident began")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    p2 = os.path.join(args.plots_dir, "detour_uptake_over_time.png")
    fig.savefig(p2, dpi=130)
    plt.close(fig)

    # Plot 3: bar chart of key metrics
    metrics = [
        ("Mean travel\ntime [s]", b["mean_dur"], d["mean_dur"]),
        ("Mean time\nloss [s]", b["mean_tloss"], d["mean_tloss"]),
        ("Mean depart\ndelay [s]", b["mean_ddelay"], d["mean_ddelay"]),
        ("Mean waiting\ntime [s]", b["mean_wait"], d["mean_wait"]),
    ]
    labels = [m[0] for m in metrics]
    x = range(len(labels))
    w = 0.38
    fig, ax = plt.subplots(figsize=(9, 5.5))
    bars1 = ax.bar([i - w / 2 for i in x], [m[1] for m in metrics], w, color="#d62728", label="baseline (no rerouting)")
    bars2 = ax.bar([i + w / 2 for i in x], [m[2] for m in metrics], w, color="#1f77b4", label="dynamic rerouting")
    for bars in (bars1, bars2):
        for bar in bars:
            ax.annotate(f"{bar.get_height():.0f}", (bar.get_x() + bar.get_width() / 2, bar.get_height()), ha="center", va="bottom", fontsize=8)
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels)
    ax.set_title("Key network metrics: baseline vs dynamic rerouting (lower is better)")
    ax.legend()
    ax.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    p3 = os.path.join(args.plots_dir, "metrics_bar_baseline_vs_dynamic.png")
    fig.savefig(p3, dpi=130)
    plt.close(fig)

    print(f"\nSaved plots: {p1}, {p2}, {p3}")
    print(f"Saved table: {csv_path}")


if __name__ == "__main__":
    main()
