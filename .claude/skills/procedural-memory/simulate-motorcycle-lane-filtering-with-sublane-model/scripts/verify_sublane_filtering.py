"""
Compare a baseline (default lane model) run against a sublane-model
(--lateral-resolution) run for a mixed-vClass lane-filtering scenario:
tripinfo metrics by vehicle class, plus FCD-based physical verification of
genuine sublane filtering (lateral position + net overtakes on a queuing
approach), for a filtering-capable class (e.g. motorcycles) vs. a
full-lane-width class (e.g. cars).

Usage:
    python verify_sublane_filtering.py \
        --baseline-tripinfo outputs/baseline/tripinfo.xml --baseline-fcd outputs/baseline/fcd.xml \
        --sublane-tripinfo outputs/sublane/tripinfo.xml --sublane-fcd outputs/sublane/fcd.xml \
        --filtering-vtype-prefix moto_ --other-vtype-prefix car_ \
        --approach-lane-prefix WC_ \
        --out-csv comparison_table.csv --out-json filtering_summary.json
"""

import argparse
import json
import xml.etree.ElementTree as ET
from collections import defaultdict


def parse_args():
    p = argparse.ArgumentParser(description="Verify sublane-model lane-filtering against a baseline run.")
    p.add_argument("--baseline-tripinfo", required=True)
    p.add_argument("--baseline-fcd", required=True)
    p.add_argument("--sublane-tripinfo", required=True)
    p.add_argument("--sublane-fcd", required=True)
    p.add_argument("--filtering-vtype-prefix", required=True, help="Vehicle id prefix for the filtering-capable class (e.g. 'moto_')")
    p.add_argument("--other-vtype-prefix", required=True, help="Vehicle id prefix for the full-lane-width class (e.g. 'car_')")
    p.add_argument("--approach-lane-prefix", required=True, help="Lane id prefix identifying the queuing approach in FCD (e.g. 'WC_')")
    p.add_argument("--out-csv", default="comparison_table.csv")
    p.add_argument("--out-json", default="filtering_summary.json")
    return p.parse_args()


def cls_of(vid, filt_prefix, other_prefix):
    if vid.startswith(filt_prefix):
        return "filtering"
    if vid.startswith(other_prefix):
        return "other"
    return None


def parse_tripinfo(path, filt_prefix, other_prefix):
    metrics = defaultdict(lambda: defaultdict(list))
    for _, el in ET.iterparse(path):
        if el.tag != "tripinfo":
            continue
        c = cls_of(el.get("id"), filt_prefix, other_prefix)
        if c is None:
            el.clear()
            continue
        metrics[c]["duration"].append(float(el.get("duration")))
        metrics[c]["waitingTime"].append(float(el.get("waitingTime")))
        metrics[c]["timeLoss"].append(float(el.get("timeLoss")))
        el.clear()
    return metrics


def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def parse_approach_fcd(path, lane_prefix):
    """{veh_id: [(time, pos, posLat), ...]} restricted to frames on the approach."""
    series = defaultdict(list)
    time = None
    for ev, el in ET.iterparse(path, events=("start", "end")):
        if el.tag == "timestep":
            if ev == "start":
                time = float(el.get("time"))
            else:
                el.clear()
        elif el.tag == "vehicle" and ev == "end":
            lane = el.get("lane") or ""
            if lane.startswith(lane_prefix):
                series[el.get("id")].append((time, float(el.get("pos")), float(el.get("posLat"))))
            el.clear()
    return series


def pos_at(frames, t):
    best = None
    for f in frames:
        if abs(f[0] - t) <= 0.5 and (best is None or abs(f[0] - t) < abs(best[0] - t)):
            best = f
    return best[1] if best else None


def filtering_stats(series, filt_prefix):
    """For each filtering-class vehicle, count others that were ahead of it on
    entry to the approach and behind it on exit -- a net overtake."""
    entry = {v: s[0] for v, s in series.items()}
    exitf = {v: s[-1] for v, s in series.items()}
    result = {}
    for v, s in series.items():
        if not v.startswith(filt_prefix):
            continue
        t_in, pos_in = entry[v][0], entry[v][1]
        t_out, pos_out = exitf[v][0], exitf[v][1]
        overtaken = 0
        for u, su in series.items():
            if u == v:
                continue
            pu_in, pu_out = pos_at(su, t_in), pos_at(su, t_out)
            if pu_in is None or pu_out is None:
                continue
            if pu_in > pos_in and pu_out < pos_out:
                overtaken += 1
        result[v] = {"overtaken": overtaken, "t_in": t_in, "t_out": t_out,
                     "pos_in": pos_in, "pos_out": pos_out, "travel": t_out - t_in}
    return result


def main():
    args = parse_args()

    base_ti = parse_tripinfo(args.baseline_tripinfo, args.filtering_vtype_prefix, args.other_vtype_prefix)
    sub_ti = parse_tripinfo(args.sublane_tripinfo, args.filtering_vtype_prefix, args.other_vtype_prefix)

    rows = []
    header = ["class", "metric", "baseline", "sublane", "abs_change", "pct_change"]
    for c in ("filtering", "other"):
        for m, label in (("waitingTime", "mean waiting time (s)"), ("duration", "mean travel time (s)"), ("timeLoss", "mean time loss (s)")):
            b, s = mean(base_ti[c][m]), mean(sub_ti[c][m])
            rows.append([c, label, f"{b:.2f}", f"{s:.2f}", f"{s - b:+.2f}", f"{(s - b) / b * 100:+.1f}%" if b else "n/a"])
        rows.append([c, "vehicle count", str(len(base_ti[c]["duration"])), str(len(sub_ti[c]["duration"])), "", ""])

    with open(args.out_csv, "w") as f:
        f.write(",".join(header) + "\n")
        for r in rows:
            f.write(",".join(r) + "\n")
    print("=== TRIPINFO COMPARISON ===")
    for r in rows:
        print(" | ".join(str(c) for c in r))

    base_s = parse_approach_fcd(args.baseline_fcd, args.approach_lane_prefix)
    sub_s = parse_approach_fcd(args.sublane_fcd, args.approach_lane_prefix)
    base_f = filtering_stats(base_s, args.filtering_vtype_prefix)
    sub_f = filtering_stats(sub_s, args.filtering_vtype_prefix)

    b_over = [d["overtaken"] for d in base_f.values()]
    s_over = [d["overtaken"] for d in sub_f.values()]
    b_lat = [f[2] for v, s in base_s.items() if v.startswith(args.filtering_vtype_prefix) for f in s]
    s_lat = [f[2] for v, s in sub_s.items() if v.startswith(args.filtering_vtype_prefix) for f in s]

    print("\n=== FILTERING (net overtakes on the approach) ===")
    print(f"BASELINE: n={len(b_over)} mean={mean(b_over):.2f} filtered(>0)={sum(1 for x in b_over if x > 0)}")
    print(f"SUBLANE : n={len(s_over)} mean={mean(s_over):.2f} filtered(>0)={sum(1 for x in s_over if x > 0)}")

    print("\n=== posLat (m from lane centre) ===")
    print(f"BASELINE: n={len(b_lat)} mean|posLat|={mean([abs(x) for x in b_lat]):.3f} max={max([abs(x) for x in b_lat], default=0):.3f}")
    print(f"SUBLANE : n={len(s_lat)} mean|posLat|={mean([abs(x) for x in s_lat]):.3f} max={max([abs(x) for x in s_lat], default=0):.3f}")

    exemplar = max(sub_f, key=lambda v: sub_f[v]["overtaken"]) if sub_f else None
    summary = {
        "baseline": {"mean_overtakes": mean(b_over), "n_filtered": sum(1 for x in b_over if x > 0), "n": len(b_over),
                     "mean_abs_posLat": mean([abs(x) for x in b_lat]), "max_abs_posLat": max([abs(x) for x in b_lat], default=0)},
        "sublane": {"mean_overtakes": mean(s_over), "n_filtered": sum(1 for x in s_over if x > 0), "n": len(s_over),
                    "mean_abs_posLat": mean([abs(x) for x in s_lat]), "max_abs_posLat": max([abs(x) for x in s_lat], default=0)},
        "exemplar": exemplar,
    }
    with open(args.out_json, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nWrote {args.out_csv} and {args.out_json}")


if __name__ == "__main__":
    main()
