#!/usr/bin/env python3
"""
Sub-goal 2(a): establish the CRN replication noise floor for every reported
metric, from the reference "no control, incident present" arm (DMSV=0000)
and the "no incident" control arm's seed-to-seed spread.

Usage: python noise_floor.py --collected results.json --out noise_floor.json
"""
import argparse
import json
import statistics as st

METRICS = ["tstt_veh_h", "origin_delay_veh_h", "fwy_through_mean_duration",
           "arterial_through_mean_duration", "cross_street_local_mean_duration",
           "hard_braking_events", "teleports_total"]


def summarize(rows, metrics):
    out = {}
    n = len(rows)
    for m in metrics:
        vals = [r[m] for r in rows if r.get(m) is not None]
        if len(vals) < 2:
            out[m] = dict(n=len(vals), mean=vals[0] if vals else None, sd=None, cv=None, note="insufficient seeds for SD")
            continue
        mean = st.mean(vals)
        sd = st.stdev(vals)
        out[m] = dict(n=len(vals), mean=mean, sd=sd,
                       cv=(sd / mean if mean else None),
                       sem=sd / (len(vals) ** 0.5),
                       noise_floor_2x_sem=2 * sd / (len(vals) ** 0.5))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--collected", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    with open(args.collected) as f:
        data = json.load(f)
    rows = data["rows"]

    ref_arm = [r for r in rows if r["D"] == 0 and r["M"] == 0 and r["S"] == 0 and r["V"] == 0
               and not r["no_incident"]]
    noincident_arm = [r for r in rows if r["no_incident"]]

    result = dict(
        reference_arm="DMSV=0000, incident present",
        n_seeds_reference=len(ref_arm),
        reference=summarize(ref_arm, METRICS),
        no_incident_arm=summarize(noincident_arm, METRICS),
    )
    with open(args.out, "w") as f:
        json.dump(result, f, indent=2)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
