#!/usr/bin/env python3
"""Compute inter-bus headways and their coefficient of variation (CV) from the
raw SUMO --stop-output, for baseline vs control, and produce:
  - comparison_table.csv       (headway CV, pairing, dwell-load feedback, wait)
  - headways.png               (stringline + headway-over-time, baseline vs control)
  - console summary

A critic can rerun this on the raw stopinfo_*.xml to reproduce every number.
"""
import sys, argparse, statistics as st, csv, math
import xml.etree.ElementTree as ET
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

STOP_ORDER = ["bs0", "bs1", "bs2", "bs3", "bs4", "bs5"]
STOP_IDX = {s: i for i, s in enumerate(STOP_ORDER)}


def load_stops(path):
    """Return list of dicts per stopinfo, sorted by arrival (started)."""
    root = ET.parse(path).getroot()
    rows = []
    for s in root.findall("stopinfo"):
        started = float(s.get("started")); ended = float(s.get("ended"))
        rows.append(dict(
            bus=s.get("id"), stop=s.get("busStop"),
            started=started, ended=ended, dwell=ended - started,
            loaded=int(s.get("loadedPersons")), unloaded=int(s.get("unloadedPersons")),
            onboard=int(s.get("initialPersons")),
        ))
    rows.sort(key=lambda r: r["started"])
    return rows


def cv(xs):
    xs = [x for x in xs]
    if len(xs) < 2:
        return float("nan")
    m = st.mean(xs)
    if m == 0:
        return float("nan")
    return st.pstdev(xs) / m


def headways_at_stop(rows, stop):
    arr = sorted(r["started"] for r in rows if r["stop"] == stop)
    return arr, [arr[i] - arr[i - 1] for i in range(1, len(arr))]


def pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return float("nan")
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return float("nan")
    return sxy / math.sqrt(sxx * syy)


def person_wait(tripinfo_path):
    """Mean & total passenger wait time (time spent waiting for the bus)."""
    root = ET.parse(tripinfo_path).getroot()
    waits = []
    for pi in root.findall("personinfo"):
        for ride in pi.findall("ride"):
            w = ride.get("waitingTime")
            if w is not None:
                waits.append(float(w))
    return waits


def analyze(path_stop, path_trip, label):
    rows = load_stops(path_stop)
    res = {"label": label, "rows": rows}

    # pooled headways across all stops
    all_hw = []
    per_stop_hw = {}
    for s in STOP_ORDER:
        arr, hw = headways_at_stop(rows, s)
        per_stop_hw[s] = (arr, hw)
        all_hw.extend(hw)
    res["per_stop_hw"] = per_stop_hw
    res["all_hw"] = all_hw
    res["cv_pooled"] = cv(all_hw)
    res["mean_hw"] = st.mean(all_hw) if all_hw else float("nan")

    # CV growth over time at reference stop bs0: first half vs second half by time
    ref_arr, ref_hw = per_stop_hw["bs0"]
    # pair each headway with its arrival time (the later arrival)
    ref_pairs = list(zip(ref_arr[1:], ref_hw))
    if ref_pairs:
        tmid = (ref_pairs[0][0] + ref_pairs[-1][0]) / 2
        first = [h for (tt, h) in ref_pairs if tt <= tmid]
        second = [h for (tt, h) in ref_pairs if tt > tmid]
    else:
        first, second = [], []
    res["cv_ref_first"] = cv(first)
    res["cv_ref_second"] = cv(second)
    res["cv_ref_all"] = cv(ref_hw)
    res["ref_pairs"] = ref_pairs

    # pairing metric: fraction of pooled headways that are "near-zero" (< 0.25*mean)
    m = res["mean_hw"]
    near = [h for h in all_hw if h < 0.25 * m] if all_hw and m == m else []
    res["pair_frac"] = (len(near) / len(all_hw)) if all_hw else float("nan")
    res["min_hw"] = min(all_hw) if all_hw else float("nan")
    res["max_hw"] = max(all_hw) if all_hw else float("nan")

    # dwell vs load feedback (all stopinfo)
    load = [r["loaded"] + r["unloaded"] for r in rows]
    dwell = [r["dwell"] for r in rows]
    res["r_dwell_load"] = pearson(load, dwell)
    res["mean_dwell"] = st.mean(dwell) if dwell else float("nan")

    # bus round-trip time regularity: successive visits of same bus to bs0
    rtts = []
    by_bus = {}
    for r in rows:
        if r["stop"] == "bs0":
            by_bus.setdefault(r["bus"], []).append(r["started"])
    for b, times in by_bus.items():
        times.sort()
        rtts.extend(times[i] - times[i - 1] for i in range(1, len(times)))
    res["rtt_cv"] = cv(rtts)
    res["rtt_mean"] = st.mean(rtts) if rtts else float("nan")

    # passenger wait
    waits = person_wait(path_trip)
    res["waits"] = waits
    res["wait_mean"] = st.mean(waits) if waits else float("nan")
    res["wait_total"] = sum(waits) if waits else float("nan")
    res["n_riders"] = len(waits)
    return res


def stringline(ax, rows, title):
    """Trajectory per bus: cumulative stops visited vs arrival time."""
    by_bus = {}
    for r in sorted(rows, key=lambda r: r["started"]):
        by_bus.setdefault(r["bus"], []).append(r)
    for b in sorted(by_bus):
        seq = by_bus[b]
        xs = [r["started"] for r in seq]
        # cumulative distance = running count of stop visits (each = 1/6 loop)
        ys = list(range(1, len(seq) + 1))
        ax.plot(xs, ys, marker="o", ms=2, lw=1.0, label=b)
    ax.set_title(title); ax.set_xlabel("sim time (s)")
    ax.set_ylabel("cumulative stops visited")
    ax.legend(fontsize=6, ncol=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline-stop", required=True)
    ap.add_argument("--baseline-trip", required=True)
    ap.add_argument("--control-stop", required=True)
    ap.add_argument("--control-trip", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    B = analyze(args.baseline_stop, args.baseline_trip, "baseline")
    C = analyze(args.control_stop, args.control_trip, "control")

    # ---- comparison table ----
    metrics = [
        ("headway CV (pooled, all stops)", "cv_pooled"),
        ("headway CV @bs0 (all)", "cv_ref_all"),
        ("headway CV @bs0 (first half)", "cv_ref_first"),
        ("headway CV @bs0 (second half)", "cv_ref_second"),
        ("mean headway (s)", "mean_hw"),
        ("min headway (s)", "min_hw"),
        ("max headway (s)", "max_hw"),
        ("pairing frac (hw < 0.25*mean)", "pair_frac"),
        ("dwell~load Pearson r", "r_dwell_load"),
        ("mean dwell (s)", "mean_dwell"),
        ("bus round-trip-time CV", "rtt_cv"),
        ("mean round-trip time (s)", "rtt_mean"),
        ("mean passenger wait (s)", "wait_mean"),
        ("total passenger wait (s)", "wait_total"),
        ("riders counted", "n_riders"),
    ]
    tbl = os.path.join(args.out_dir, "comparison_table.csv")
    with open(tbl, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["metric", "baseline", "control"])
        for name, key in metrics:
            w.writerow([name, f"{B[key]:.4f}" if isinstance(B[key], float) else B[key],
                        f"{C[key]:.4f}" if isinstance(C[key], float) else C[key]])
    print(f"wrote {tbl}")

    # ---- plot ----
    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    stringline(axes[0][0], B["rows"], "BASELINE (no control): bus trajectories")
    stringline(axes[0][1], C["rows"], "CONTROL (holding): bus trajectories")
    # headway over time at bs0
    for ax, R, ttl in [(axes[1][0], B, "BASELINE"), (axes[1][1], C, "CONTROL")]:
        pairs = R["ref_pairs"]
        if pairs:
            xs = [p[0] for p in pairs]; ys = [p[1] for p in pairs]
            ax.plot(xs, ys, "-o", ms=3, color="#c0392b")
            ax.axhline(R["mean_hw"], ls="--", color="gray",
                       label=f"mean={R['mean_hw']:.0f}s")
        ax.set_title(f"{ttl}: headway @bs0 over time  (CV all={R['cv_ref_all']:.2f})")
        ax.set_xlabel("arrival time (s)"); ax.set_ylabel("headway to prev bus (s)")
        ax.legend(fontsize=8)
    # share y-limits on headway panels for fair visual comparison
    ymax = max(axes[1][0].get_ylim()[1], axes[1][1].get_ylim()[1])
    axes[1][0].set_ylim(0, ymax); axes[1][1].set_ylim(0, ymax)
    fig.tight_layout()
    png = os.path.join(args.out_dir, "headways.png")
    fig.savefig(png, dpi=110)
    print(f"wrote {png}")

    # ---- console summary ----
    def line(name, key, fmt="{:.3f}"):
        bv = B[key]; cv_ = C[key]
        bs = fmt.format(bv) if isinstance(bv, float) else str(bv)
        cs = fmt.format(cv_) if isinstance(cv_, float) else str(cv_)
        print(f"  {name:38s} baseline={bs:>10s}   control={cs:>10s}")
    print("\n==== SUMMARY (recomputed from raw stop-output) ====")
    for name, key in metrics:
        line(name, key)


if __name__ == "__main__":
    import os
    main()
