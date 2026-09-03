#!/usr/bin/env python3
"""
Parse SUMO tripinfo/summary(/edgeData) outputs from one or more simulation
runs into network-level performance metrics, write a comparison table, and
save a bar chart + time-series chart comparing the runs.

Usage
-----
Explicit files per run (tripinfo and summary required, edgeData optional):

    python analyze_outputs.py \
        --run baseline=tripinfo_baseline.xml,summary_baseline.xml \
        --run optimized=tripinfo_optimized.xml,summary_optimized.xml,edgedata_optimized.xml \
        --out-dir comparison/

A directory per run, using conventional filenames (any file matching
tripinfo*.xml / summary*.xml / edgedata*.xml inside it):

    python analyze_outputs.py \
        --run-dir baseline=runs/baseline \
        --run-dir optimized=runs/optimized \
        --out-dir comparison/

Any number of --run/--run-dir can be given (mix and match), for 2+ runs.
With exactly 2 runs the comparison table includes a % change column; with
3+ runs it reports raw values per run (a % change column would need a
chosen reference run, which this script does not assume).

Also converts each XML output to CSV via $SUMO_HOME/tools/xml/xml2csv.py
when --xml2csv is passed, alongside the direct ElementTree parsing used
for the metrics themselves (xml2csv.py is for human/spreadsheet inspection,
not required for the metrics or plots).
"""

import argparse
import glob
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

METRIC_ORDER = [
    "Completed trips (throughput)",
    "Mean travel time (s)",
    "Total travel time (s)",
    "Mean waiting time (s)",
    "Mean time loss (s)",
    "Mean trip speed (m/s)",
    "Total teleports",
]
HIGHER_IS_BETTER = {"Completed trips (throughput)", "Mean trip speed (m/s)"}
BAR_CHART_METRICS = ["Mean travel time (s)", "Mean waiting time (s)",
                      "Mean time loss (s)", "Mean trip speed (m/s)"]

# SUMO's summary output uses meanSpeed=-1 as a sentinel for "no vehicles are
# currently running" (division-by-zero avoided upstream), not a real speed.
# Plotting it as-is produces a misleading dip to -1 whenever the network
# drains empty at the start/tail of a run -- always filter these points out.
NO_VEHICLE_SENTINEL = -1.0


def find_sumo_tool(tool_relpath):
    """Locate a SUMO python tool under $SUMO_HOME/tools (same convention as
    the tlsCycleAdaptation/randomTrips wrapper skills)."""
    sumo_home = os.environ.get("SUMO_HOME")
    if not sumo_home:
        raise SystemExit("SUMO_HOME is not set -- cannot locate SUMO tools. "
                          "Run `echo $SUMO_HOME` to check.")
    path = os.path.join(sumo_home, "tools", tool_relpath)
    if not os.path.isfile(path):
        raise SystemExit(f"Expected SUMO tool not found at {path}")
    return path


def parse_run_arg(spec):
    name, _, rest = spec.partition("=")
    if not name or not rest:
        raise SystemExit(f"--run expects NAME=tripinfo.xml,summary.xml[,edgedata.xml], got: {spec}")
    parts = [p.strip() for p in rest.split(",") if p.strip()]
    if len(parts) < 2:
        raise SystemExit(f"--run {name}: need at least tripinfo,summary paths, got {parts}")
    files = {"tripinfo": parts[0], "summary": parts[1]}
    if len(parts) >= 3:
        files["edgedata"] = parts[2]
    return name, files


def parse_run_dir_arg(spec):
    name, _, directory = spec.partition("=")
    if not name or not directory:
        raise SystemExit(f"--run-dir expects NAME=directory, got: {spec}")

    def find_one(pattern, required=True):
        matches = sorted(glob.glob(os.path.join(directory, pattern)))
        if not matches and required:
            raise SystemExit(f"--run-dir {name}: no file matching {pattern} in {directory}")
        return matches[0] if matches else None

    files = {
        "tripinfo": find_one("tripinfo*.xml"),
        "summary": find_one("summary*.xml"),
    }
    edgedata = find_one("edgedata*.xml", required=False) or find_one("edgeData*.xml", required=False)
    if edgedata:
        files["edgedata"] = edgedata
    return name, files


def xml_to_csv(xml_path, xml2csv_tool):
    subprocess.run([sys.executable, xml2csv_tool, xml_path],
                    check=True, capture_output=True, text=True)
    return os.path.splitext(xml_path)[0] + ".csv"


def parse_metrics(files):
    """Network-level metrics for one run, from its tripinfo + summary XML."""
    durations, waits, timelosses, speeds = [], [], [], []
    for _, elem in ET.iterparse(files["tripinfo"], events=("end",)):
        if elem.tag == "tripinfo":
            dur = float(elem.get("duration"))
            rlen = float(elem.get("routeLength"))
            durations.append(dur)
            waits.append(float(elem.get("waitingTime")))
            timelosses.append(float(elem.get("timeLoss")))
            speeds.append(rlen / dur if dur > 0 else 0.0)
            elem.clear()

    n = len(durations)
    if n == 0:
        raise SystemExit(f"{files['tripinfo']}: no <tripinfo> elements found -- "
                          "empty output usually means no vehicle completed its trip; "
                          "check the run for gridlock/config errors before comparing it.")

    # summary.xml's "teleports" attribute is a CUMULATIVE running count, not a
    # per-step delta -- take the last step's value, don't sum across steps
    # (summing would wildly over-count; verified against raw output).
    teleports = 0
    for _, elem in ET.iterparse(files["summary"], events=("end",)):
        if elem.tag == "step":
            teleports = int(elem.get("teleports"))
            elem.clear()

    return {
        "Completed trips (throughput)": n,
        "Mean travel time (s)": sum(durations) / n,
        "Total travel time (s)": sum(durations),
        "Mean waiting time (s)": sum(waits) / n,
        "Mean time loss (s)": sum(timelosses) / n,
        "Mean trip speed (m/s)": sum(speeds) / n,
        "Total teleports": teleports,
    }


def read_summary_series(summary_xml):
    """Time series of (time, running vehicles, mean speed) from summary XML,
    with the -1 "no vehicles running" sentinel dropped from the speed series."""
    t, running, t_speed, meanspeed = [], [], [], []
    for _, elem in ET.iterparse(summary_xml, events=("end",)):
        if elem.tag == "step":
            time = float(elem.get("time"))
            t.append(time)
            running.append(int(elem.get("running")))
            speed = float(elem.get("meanSpeed"))
            if speed != NO_VEHICLE_SENTINEL:
                t_speed.append(time)
                meanspeed.append(speed)
            elem.clear()
    return t, running, t_speed, meanspeed


def write_comparison_table(metrics_by_run, out_dir):
    run_names = list(metrics_by_run.keys())
    table_csv = os.path.join(out_dir, "comparison_table.csv")
    lines_md = []

    if len(run_names) == 2:
        base, other = run_names
        lines_md.append(f"| Metric | {base} | {other} | % change | Improved? |")
        lines_md.append("| --- | ---: | ---: | ---: | :---: |")
        with open(table_csv, "w") as f:
            f.write(f"metric,{base},{other},pct_change,improved\n")
            for m in METRIC_ORDER:
                b, o = metrics_by_run[base][m], metrics_by_run[other][m]
                pct = (o - b) / b * 100 if b != 0 else float("nan")
                better = o > b if m in HIGHER_IS_BETTER else o < b
                improved = "yes" if better else ("same" if o == b else "no")
                f.write(f"{m},{b:.4f},{o:.4f},{pct:.2f},{improved}\n")
                lines_md.append(f"| {m} | {b:,.2f} | {o:,.2f} | {pct:+.2f}% | {improved} |")
    else:
        lines_md.append("| Metric | " + " | ".join(run_names) + " |")
        lines_md.append("| --- | " + " | ".join(["---:"] * len(run_names)) + " |")
        with open(table_csv, "w") as f:
            f.write("metric," + ",".join(run_names) + "\n")
            for m in METRIC_ORDER:
                vals = [metrics_by_run[r][m] for r in run_names]
                f.write(f"{m}," + ",".join(f"{v:.4f}" for v in vals) + "\n")
                lines_md.append(f"| {m} | " + " | ".join(f"{v:,.2f}" for v in vals) + " |")

    print("\n".join(lines_md))
    print(f"\nComparison table written to: {table_csv}")
    return table_csv


def save_bar_chart(metrics_by_run, out_dir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    run_names = list(metrics_by_run.keys())
    x = range(len(BAR_CHART_METRICS))
    n_runs = len(run_names)
    w = 0.8 / n_runs
    fig, ax = plt.subplots(figsize=(9, 5.5))
    for i, run in enumerate(run_names):
        offset = (i - (n_runs - 1) / 2) * w
        vals = [metrics_by_run[run][m] for m in BAR_CHART_METRICS]
        bars = ax.bar([xi + offset for xi in x], vals, w, label=run)
        ax.bar_label(bars, fmt="%.1f", padding=2, fontsize=8)
    ax.set_xticks(list(x))
    ax.set_xticklabels([m.replace(" (", "\n(") for m in BAR_CHART_METRICS])
    ax.set_ylabel("Value")
    ax.set_title("Key network metrics across runs")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    path = os.path.join(out_dir, "metrics_bar_comparison.png")
    fig.savefig(path, dpi=130)
    plt.close(fig)
    print(f"Bar chart saved to: {path}")


def save_timeseries_chart(files_by_run, out_dir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    for run, files in files_by_run.items():
        t, running, t_speed, speed = read_summary_series(files["summary"])
        ax1.plot(t, running, label=run, lw=1.2)
        ax2.plot(t_speed, speed, label=run, lw=1.2)
    ax1.set_ylabel("Running vehicles")
    ax1.set_title("Running vehicles over simulation time")
    ax1.legend()
    ax1.grid(alpha=0.3)
    ax2.set_ylabel("Mean network speed (m/s)")
    ax2.set_xlabel("Simulation time (s)")
    ax2.set_title("Mean network speed over simulation time (no-vehicle sentinel filtered out)")
    ax2.legend()
    ax2.grid(alpha=0.3)
    fig.tight_layout()
    path = os.path.join(out_dir, "timeseries_comparison.png")
    fig.savefig(path, dpi=130)
    plt.close(fig)
    print(f"Time-series chart saved to: {path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="append", default=[],
                     help="NAME=tripinfo.xml,summary.xml[,edgedata.xml] -- repeatable")
    ap.add_argument("--run-dir", action="append", default=[],
                     help="NAME=directory (looks for tripinfo*.xml, summary*.xml, edgedata*.xml inside) -- repeatable")
    ap.add_argument("--out-dir", default=".", help="where to write the comparison table and plots")
    ap.add_argument("--xml2csv", action="store_true",
                     help="also convert each XML output to CSV via $SUMO_HOME/tools/xml/xml2csv.py")
    ap.add_argument("--no-plots", action="store_true", help="skip generating PNG plots (table only)")
    args = ap.parse_args()

    files_by_run = {}
    for spec in args.run:
        name, files = parse_run_arg(spec)
        files_by_run[name] = files
    for spec in args.run_dir:
        name, files = parse_run_dir_arg(spec)
        files_by_run[name] = files

    if len(files_by_run) < 2:
        raise SystemExit("Need at least 2 runs (--run/--run-dir) to compare.")

    os.makedirs(args.out_dir, exist_ok=True)

    if args.xml2csv:
        xml2csv_tool = find_sumo_tool(os.path.join("xml", "xml2csv.py"))
        for run, files in files_by_run.items():
            for kind, path in files.items():
                csv_path = xml_to_csv(path, xml2csv_tool)
                print(f"  {run}/{kind} -> {csv_path}")

    metrics_by_run = {run: parse_metrics(files) for run, files in files_by_run.items()}
    write_comparison_table(metrics_by_run, args.out_dir)

    if not args.no_plots:
        try:
            import matplotlib  # noqa: F401
        except ImportError:
            raise SystemExit("matplotlib is required for plots (skip with --no-plots). "
                              "Install with: pip3 install matplotlib --break-system-packages")
        save_bar_chart(metrics_by_run, args.out_dir)
        save_timeseries_chart(files_by_run, args.out_dir)


if __name__ == "__main__":
    main()
