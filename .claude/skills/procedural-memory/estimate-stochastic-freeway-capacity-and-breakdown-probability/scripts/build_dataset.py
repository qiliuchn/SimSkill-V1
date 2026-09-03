#!/usr/bin/env python3
"""Turn every simulated day into a set of classified capacity observations.

For one breakdown DEFINITION (station, speed threshold, persistence, aggregation
interval) and one day:

  1. 1-min series at `station`; congested-minute flag = (v < v_thresh).
  2. t_bd = start of the first run of >= persist_min consecutive congested minutes
     after warm-up (NaN speed inherits the previous minute's flag).
  3. non-overlapping T-minute intervals from warm-up.
     * interval entirely before t_bd AND the NEXT interval contains t_bd -> UNCENSORED
       capacity observation (event=1), c = q of THIS interval.
     * interval entirely before t_bd and next interval also fluid -> CENSORED (event=0).
     * intervals at/after t_bd -> excluded (already congested; that flow is queue
       discharge, not capacity).
     * no breakdown in the day -> every interval censored.

Every row carries its full definition metadata so the CSV is self-describing.
"""
import argparse
import csv
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import detio     # noqa: E402
import scenario  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
WARMUP = 600.0
# the CONSTRAINED cross-section is ml_d (2 lanes); the mrg station sits on ml_c (3 lanes,
# incl. the acceleration lane), so per-lane capacity must be divided by 2, not by 3.
N_BOTTLENECK_LANES = 2

FIELDS = ["arm", "day", "sim_seed", "station", "v_thresh_kmh", "persist_min",
          "interval_min", "interval_begin_s", "q_vph", "q_vph_per_station_lane",
          "q_vph_per_bottleneck_lane", "v_kmh", "occ_pct",
          "n_veh", "event", "t_breakdown_s", "day_broke_down", "demand_vph",
          "het_scale", "ramp_share", "truck_share", "tau_mu", "sf_sd", "sigma_mu"]


def demand_at(t):
    for b, e, q in scenario.demand_schedule():
        if b <= t < e:
            return q
    return scenario.demand_schedule()[-1][2]


def day_rows(rundir, meta, station, v_thresh, persist_min, interval_min):
    s60 = detio.read_e1(os.path.join(rundir, "det60.xml"))
    if station not in s60:
        return []
    ser = s60[station]
    t_bd = detio.find_breakdown(ser, v_thresh, persist_min, warmup_s=WARMUP)
    agg = detio.aggregate({b: v for b, v in ser.items() if b >= WARMUP}, interval_min)
    bs = sorted(agg)
    T = interval_min * 60.0
    nlanes = ser[bs[0]]["nlanes"] if bs else 1
    rows = []
    for i, b in enumerate(bs):
        end = b + T
        if t_bd is not None and end > t_bd:
            break                       # this interval already contains/follows breakdown
        nxt_end = end + T
        event = 1 if (t_bd is not None and end <= t_bd < nxt_end) else 0
        a = agg[b]
        rows.append(dict(
            arm=meta["arm"], day=meta["day"], sim_seed=meta["sim_seed"],
            station=station, v_thresh_kmh=v_thresh, persist_min=persist_min,
            interval_min=interval_min, interval_begin_s=b,
            q_vph=round(a["q_vph"], 2),
            q_vph_per_station_lane=round(a["q_vph"] / nlanes, 2),
            q_vph_per_bottleneck_lane=round(a["q_vph"] / N_BOTTLENECK_LANES, 2),
            v_kmh=round(a["v_kmh"], 3) if a["v_kmh"] == a["v_kmh"] else "",
            occ_pct=round(a["occ_pct"], 3), n_veh=a["n"], event=event,
            t_breakdown_s=(round(t_bd, 1) if t_bd is not None else ""),
            day_broke_down=int(t_bd is not None),
            demand_vph=round(demand_at(b + T / 2), 1),
            het_scale=meta.get("het_scale", 1.0), ramp_share=meta.get("ramp_share", 0.2),
            truck_share=round(meta.get("truck_share", float("nan")), 5),
            tau_mu=round(meta.get("tau_mu", float("nan")), 4),
            sf_sd=round(meta.get("sf_sd", float("nan")), 4),
            sigma_mu=round(meta.get("sigma_mu", float("nan")), 4)))
    return rows


def arm_rows(arm, station, v_thresh, persist_min, interval_min, runroot=None):
    runroot = runroot or os.path.join(ROOT, "runs")
    idx = os.path.join(runroot, arm, "index.json")
    metas = {m["day"]: m for m in json.load(open(idx))}
    out = []
    for d in sorted(glob.glob(os.path.join(runroot, arm, "day*"))):
        day = int(os.path.basename(d)[3:])
        m = dict(metas.get(day, {}))
        m.setdefault("arm", arm); m.setdefault("day", day)
        m.setdefault("sim_seed", 90000 + day)
        if "truck_share" not in m:      # cached run -> regenerate the deterministic draws
            p = scenario.day_params(day, het_scale=m.get("het_scale", 1.0),
                                    ramp_share=m.get("ramp_share"))
            m.update(truck_share=p["truck_share"], tau_mu=p["tau_mu"],
                     sf_sd=p["sf_sd"], sigma_mu=p["sigma_mu"], ramp_share=p["ramp_share"])
        out += day_rows(d, m, station, v_thresh, persist_min, interval_min)
    return out


def write_csv(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default="main,het_low,het_high,phi10,phi30")
    ap.add_argument("--station", default="mrg")
    ap.add_argument("--v-thresh", type=float, default=80.0)
    ap.add_argument("--persist", type=int, default=5)
    ap.add_argument("--interval", type=int, default=5)
    ap.add_argument("--out", default=os.path.join(ROOT, "analysis", "breakdown_observations_base.csv"))
    ap.add_argument("--runroot", default=None)
    a = ap.parse_args()
    rows = []
    for arm in a.arms.split(","):
        rows += arm_rows(arm, a.station, a.v_thresh, a.persist, a.interval, a.runroot)
    write_csv(a.out, rows)
    nu = sum(r["event"] for r in rows)
    print(f"{len(rows)} rows ({nu} uncensored, {len(rows)-nu} censored) -> {a.out}")


if __name__ == "__main__":
    main()
