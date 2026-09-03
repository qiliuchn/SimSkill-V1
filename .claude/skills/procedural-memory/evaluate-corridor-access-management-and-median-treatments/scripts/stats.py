#!/usr/bin/env python3
"""CRN aggregation: mean + 95% t-CI across the 5 seeds for every
(variant, density[, consolidate]) cell, for both per_run.csv and
conflicts.csv. Writes summary_by_cell.csv and summary_conflicts.csv."""
import csv
import math
import os
from collections import defaultdict

from scipy import stats as sstats

HERE = os.path.dirname(os.path.abspath(__file__))


def read_csv(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def to_float(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def ci95(vals):
    vals = [v for v in vals if not math.isnan(v)]
    n = len(vals)
    if n == 0:
        return float("nan"), float("nan"), float("nan"), 0
    mean = sum(vals) / n
    if n < 2:
        return mean, float("nan"), float("nan"), n
    sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / (n - 1))
    se = sd / math.sqrt(n)
    tcrit = sstats.t.ppf(0.975, df=n - 1)
    half = tcrit * se
    return mean, mean - half, mean + half, n


def aggregate(rows, group_keys, value_keys):
    groups = defaultdict(list)
    for r in rows:
        key = tuple(r[k] for k in group_keys)
        groups[key].append(r)
    out = []
    for key, rs in sorted(groups.items()):
        row = dict(zip(group_keys, key))
        row["n_seeds"] = len(rs)
        for vk in value_keys:
            vals = [to_float(r[vk]) for r in rs]
            m, lo, hi, n = ci95(vals)
            row[f"{vk}__mean"] = m
            row[f"{vk}__ci_lo"] = lo
            row[f"{vk}__ci_hi"] = hi
        out.append(row)
    return out


def write_csv(rows, path):
    if not rows:
        print("no rows for", path)
        return
    keys = list(rows[0].keys())
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    print("wrote", path, len(rows), "rows")


def main():
    per_run = read_csv(os.path.join(HERE, "per_run.csv"))
    conflicts = read_csv(os.path.join(HERE, "conflicts.csv"))

    value_keys_run = [
        "vmt_km", "vht_h", "mean_speed_mps_all",
        "through_mean_traveltime_s", "through_mean_speed_mps", "through_mean_timeloss_s",
        "through_mean_waitingtime_s", "through_mean_stops",
        "access_mean_traveltime_s", "access_mean_speed_mps", "access_mean_timeloss_s",
        "access_mean_waitingtime_s", "access_mean_stops",
        "access_mean_departdelay_s", "access_p95_departdelay_s",
        "access_in_left_mean_traveltime_s", "access_in_left_mean_departdelay_s",
        "access_in_left_p95_departdelay_s",
        "access_out_left_mean_traveltime_s", "access_out_left_mean_departdelay_s",
        "access_out_left_p95_departdelay_s",
        "access_in_right_mean_departdelay_s", "access_out_right_mean_departdelay_s",
    ]
    value_keys_conf = [
        "conflicts_per_Mvkm_total", "left_turn_in_per_Mvkm", "left_turn_out_per_Mvkm",
        "right_turn_in_per_Mvkm", "right_turn_out_per_Mvkm", "thru_thru_per_Mvkm",
        "median_related_per_Mvkm", "n_conflicts_total",
    ]

    # main sweep: group by variant, density (consolidate==1 only)
    main_run = [r for r in per_run if r["consolidate"] == "1"]
    main_conf = [r for r in conflicts if r["consolidate"] == "1"]
    summary_run = aggregate(main_run, ["variant", "density"], value_keys_run)
    summary_conf = aggregate(main_conf, ["variant", "density"], value_keys_conf)
    write_csv(summary_run, os.path.join(HERE, "summary_by_cell.csv"))
    write_csv(summary_conf, os.path.join(HERE, "summary_conflicts.csv"))

    # remedy arm: group by variant, density, consolidate (only consolidate>1 rows,
    # plus the matching consolidate==1 d45 baseline for direct comparison)
    remedy_run = [r for r in per_run if (r["consolidate"] != "1") or
                  (r["density"] == "45" and r["consolidate"] == "1")]
    remedy_conf = [r for r in conflicts if (r["consolidate"] != "1") or
                   (r["density"] == "45" and r["consolidate"] == "1")]
    summary_remedy_run = aggregate(remedy_run, ["variant", "density", "consolidate"], value_keys_run)
    summary_remedy_conf = aggregate(remedy_conf, ["variant", "density", "consolidate"], value_keys_conf)
    write_csv(summary_remedy_run, os.path.join(HERE, "summary_remedy.csv"))
    write_csv(summary_remedy_conf, os.path.join(HERE, "summary_remedy_conflicts.csv"))


if __name__ == "__main__":
    main()
