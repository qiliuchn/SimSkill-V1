"""
Compare a microscopic baseline against one or more mesoscopic (or other) SUMO
run variants: exact per-run metrics from tripinfo + summary, honest wall-clock
speedup from a `time` (or /usr/bin/time) capture, and per-vehicle divergence
between any two runs (useful for confirming a meso parameter had -- or didn't
have -- any real effect).

Expects, per run, an output directory containing tripinfo.xml, summary.xml,
and a time.txt containing the captured `time`/`/usr/bin/time -p` output (must
include a line matching "real <seconds>" or "Duration: <seconds>s" -- adjust
WALLCLOCK_RE/COMPUTE_RE if your capture format differs).

Usage:
    python compare_micro_meso.py \
        --baseline micro=outputs/micro \
        --run meso_default=outputs/meso_default \
        --run meso_jc=outputs/meso_jc \
        --diff-pair meso_jc,meso_jc_multiqueue \
        --out-csv outputs/comparison.csv
"""

import argparse
import csv
import os
import re
import xml.etree.ElementTree as ET


def parse_args():
    p = argparse.ArgumentParser(description="Compare a microscopic baseline against mesoscopic run variants.")
    p.add_argument("--baseline", required=True, help="label=outdir for the microscopic baseline run")
    p.add_argument("--run", action="append", required=True, help="label=outdir, repeatable, one per meso variant")
    p.add_argument("--diff-pair", action="append", default=[], help="labelA,labelB -- report per-vehicle duration divergence between these two runs (repeatable)")
    p.add_argument("--out-csv", default="comparison.csv")
    return p.parse_args()


def parse_tripinfo(path):
    dur = wait = loss = rl = 0.0
    n = 0
    for _, e in ET.iterparse(path):
        if e.tag == "tripinfo":
            dur += float(e.get("duration"))
            wait += float(e.get("waitingTime"))
            loss += float(e.get("timeLoss"))
            rl += float(e.get("routeLength"))
            n += 1
            e.clear()
    if n == 0:
        raise SystemExit(f"{path}: no <tripinfo> elements found.")
    return {"n": n, "mean_dur": dur / n, "mean_wait": wait / n, "mean_loss": loss / n,
            "tot_loss": loss, "tot_wait": wait, "mean_speed": rl / dur, "mean_rl": rl / n}


def last_teleports(path):
    tp = 0
    for _, e in ET.iterparse(path):
        if e.tag == "step":
            tp = int(e.get("teleports"))
            e.clear()
    return tp


def wallclock_seconds(path):
    text = open(path).read()
    m = re.search(r"^real\s+([\d.]+)", text, re.M)
    if m:
        return float(m.group(1))
    m = re.search(r"real\s+(\d+)m([\d.]+)s", text)
    return float(m.group(1)) * 60 + float(m.group(2)) if m else None


def compute_seconds(path):
    m = re.search(r"Duration:\s+([\d.]+)s", open(path).read())
    return float(m.group(1)) if m else None


def dur_map(path):
    m = {}
    for _, e in ET.iterparse(path):
        if e.tag == "tripinfo":
            m[e.get("id")] = float(e.get("duration"))
            e.clear()
    return m


def main():
    args = parse_args()
    baseline_label, baseline_dir = args.baseline.split("=", 1)
    run_specs = [args.baseline] + args.run

    rows = []
    for spec in run_specs:
        label, outdir = spec.split("=", 1)
        ti = parse_tripinfo(os.path.join(outdir, "tripinfo.xml"))
        tp = last_teleports(os.path.join(outdir, "summary.xml"))
        time_path = os.path.join(outdir, "time.txt")
        wc = wallclock_seconds(time_path) if os.path.isfile(time_path) else None
        cd = compute_seconds(time_path) if os.path.isfile(time_path) else None
        rows.append({
            "run": label, "arrived": ti["n"], "teleports": tp,
            "wall_s": wc, "compute_s": cd,
            "mean_dur_s": round(ti["mean_dur"], 2), "mean_speed_ms": round(ti["mean_speed"], 3),
            "mean_wait_s": round(ti["mean_wait"], 2), "mean_loss_s": round(ti["mean_loss"], 2),
            "tot_loss_s": round(ti["tot_loss"], 1), "tot_wait_s": round(ti["tot_wait"], 1),
            "mean_routelen_m": round(ti["mean_rl"], 1),
        })

    baseline = next(r for r in rows if r["run"] == baseline_label)
    for r in rows:
        r["wall_speedup_x"] = round(baseline["wall_s"] / r["wall_s"], 2) if (r["wall_s"] and baseline["wall_s"]) else ""
        r["compute_speedup_x"] = round(baseline["compute_s"] / r["compute_s"], 2) if (r["compute_s"] and baseline["compute_s"]) else ""

    cols = ["run", "arrived", "teleports", "wall_s", "wall_speedup_x", "compute_s", "compute_speedup_x",
            "mean_dur_s", "mean_speed_ms", "mean_wait_s", "mean_loss_s", "tot_loss_s", "tot_wait_s", "mean_routelen_m"]
    with open(args.out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in cols})
    print(f"Wrote {args.out_csv}")

    print("\n| " + " | ".join(cols) + " |")
    print("|" + "|".join(["---"] * len(cols)) + "|")
    for r in rows:
        print("| " + " | ".join(str(r[k]) for k in cols) + " |")

    print("\n=== Divergence from baseline (signed %, + = higher than baseline) ===")
    for r in rows:
        if r["run"] == baseline_label:
            continue
        d_dur = 100 * (r["mean_dur_s"] - baseline["mean_dur_s"]) / baseline["mean_dur_s"]
        d_spd = 100 * (r["mean_speed_ms"] - baseline["mean_speed_ms"]) / baseline["mean_speed_ms"]
        d_wait = 100 * (r["mean_wait_s"] - baseline["mean_wait_s"]) / baseline["mean_wait_s"]
        d_loss = 100 * (r["mean_loss_s"] - baseline["mean_loss_s"]) / baseline["mean_loss_s"]
        print(f"{r['run']:20s} dur {d_dur:+6.1f}%  speed {d_spd:+6.1f}%  wait {d_wait:+6.1f}%  timeloss {d_loss:+6.1f}%")

    run_dirs = {spec.split("=", 1)[0]: spec.split("=", 1)[1] for spec in run_specs}
    for pair in args.diff_pair:
        a_label, b_label = pair.split(",")
        a = dur_map(os.path.join(run_dirs[a_label], "tripinfo.xml"))
        b = dur_map(os.path.join(run_dirs[b_label], "tripinfo.xml"))
        diffs = [abs(a[k] - b[k]) for k in a if k in b]
        ndiff = sum(1 for d in diffs if d > 0)
        print(f"\n=== {a_label} vs {b_label} per-vehicle duration ===")
        print(f"vehicles differing: {ndiff}/{len(diffs)}; max abs diff {max(diffs):.1f}s; mean abs diff {sum(diffs) / len(diffs):.3f}s")


if __name__ == "__main__":
    main()
