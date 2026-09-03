#!/usr/bin/env python3
"""
Walk a batch output tree (analysis/run_factorial_batch.py's --out-root) and
collect every run's result.json into one tidy JSON list, computing the
headline response metrics used throughout sub-goals 5-7:

  - TSTT_veh_h: total system time (mean_duration summed across ALL groups,
    weighted by n, converted to vehicle-hours) PLUS origin_delay_veh_s
    converted to vehicle-hours -- the "charge metering for every delay it
    creates, including demand that never got inserted" discipline from
    coordinated-ramp-metering-delay-transfer-and-ramp-storage.md.
  - per-group mean duration/timeLoss/departDelay
  - D/M/S/V audit summaries
  - teleports/collisions/safety proxy

Usage: python collect_results.py --root outputs/factorial --out results.json
"""
import argparse
import glob
import json
import os


def load_run(result_path):
    with open(result_path) as f:
        r = json.load(f)
    groups = r.get("groups", {})
    total_n = sum(g["n"] for g in groups.values())
    total_person_s = sum(g["duration"] for g in groups.values())
    origin_delay_s = r.get("origin_delay_veh_s", 0.0)
    tstt_veh_h = (total_person_s + origin_delay_s) / 3600.0

    args = r.get("args", {})
    row = dict(
        run_dir=os.path.dirname(result_path),
        seed=args.get("seed"),
        D=int(args.get("D", 0)), M=int(args.get("M", 0)),
        S=int(args.get("S", 0)), V=int(args.get("V", 0)),
        response_lag=args.get("response_lag"),
        no_incident=bool(args.get("no_incident", False)),
        incident_duration=args.get("incident_duration"),
        lanes_blocked=args.get("lanes_blocked"),
        total_n=total_n,
        tstt_veh_h=tstt_veh_h,
        origin_delay_veh_h=origin_delay_s / 3600.0,
        teleports_total=int(r.get("teleports", {}).get("total", 0)),
        collisions=int(r.get("safety", {}).get("collisions", 0)),
        loaded=int(r.get("vehicles", {}).get("loaded", 0)),
        inserted=int(r.get("vehicles", {}).get("inserted", 0)),
        waiting=int(r.get("vehicles", {}).get("waiting", 0)),
        hard_braking_events=r.get("safety_proxy", {}).get("hard_braking_events", 0),
    )
    for g in ("fwy_through", "diverted", "arterial_through", "cross_street_local"):
        gd = groups.get(g)
        row[f"{g}_n"] = gd["n"] if gd else 0
        row[f"{g}_mean_duration"] = gd["mean_duration"] if gd else None
        row[f"{g}_mean_departDelay"] = gd["mean_departDelay"] if gd else None
        row[f"{g}_mean_timeLoss"] = gd["mean_timeLoss"] if gd else None
    row["D_realized_share"] = r.get("D_audit", {}).get("realized_share")
    row["D_offered"] = r.get("D_audit", {}).get("offered")
    row["D_diverted"] = r.get("D_audit", {}).get("diverted")
    m2 = r.get("M_audit", {}).get("2", {})
    m3 = r.get("M_audit", {}).get("3", {})
    row["M2_mean_rate_vph"] = m2.get("mean_rate_vph")
    row["M3_mean_rate_vph"] = m3.get("mean_rate_vph")
    row["M2_max_ramp_jam_m"] = m2.get("max_ramp_jam_m")
    row["M3_max_ramp_jam_m"] = m3.get("max_ramp_jam_m")
    row["S_switched_at"] = r.get("S_audit", {}).get("switched_at")
    row["V_realized_compliance"] = r.get("V_audit", {}).get("realized_compliance")
    row["V_zone_vehicles_seen"] = r.get("V_audit", {}).get("zone_vehicles_seen")
    sb = r.get("spillback_audit", {})
    row["off_eb_2_max_jam_frac"] = sb.get("off_eb_2_max_jam_frac")
    row["off_eb_2_spillback_onto_mainline"] = sb.get("off_eb_2_spillback_onto_mainline")
    row["on_eb_3a_max_jam_frac"] = sb.get("on_eb_3a_max_jam_frac")
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    paths = sorted(glob.glob(os.path.join(args.root, "**", "result.json"), recursive=True))
    rows = []
    errors = []
    for p in paths:
        try:
            rows.append(load_run(p))
        except Exception as e:
            errors.append(dict(path=p, error=str(e)))
    with open(args.out, "w") as f:
        json.dump(dict(rows=rows, errors=errors), f, indent=2)
    print(f"collected {len(rows)} runs, {len(errors)} errors -> {args.out}")


if __name__ == "__main__":
    main()
