#!/usr/bin/env python3
"""Sub-goal 2: estimate degree of saturation (DoS) per approach from detector
occupancy/headway, and validate it against ground truth.

Ground truth (documented choice, see demand/rate_schedule.py's docstring):
DoS_true(cycle) = art_main_true_rate(direction, junction, t_mid) / capacity_hat
using the CLOSED-FORM Poisson generating rate this study's own demand
generator was built from -- never simulated vehicle/queue state -- divided by
the SAME realized-green/measured-saturation-flow capacity the estimator uses,
so the comparison isolates detector-side estimation error specifically.

Two competing detector-based estimators, both cycle-by-cycle, per (junction,
direction):
  DoS_hat_good : advance E1 count 90 m upstream (this study's real controller
                  detector) -> q_hat = count/cycle_dur*3600 -> /capacity_hat
  DoS_hat_bad  : same formula, but from the deliberately-too-short 15 m
                  advance detector (det/build_detectors_badsetback.py)
  occ_tail     : mean stop-bar E2 occupancy over the LAST 5 s of green
                  (ATSPM-style GOR5 proxy, build-atspm-pipeline-and-retime-arterial)
                  -- a spillback/split-failure flag, cross-checked against the
                  volume-based estimators rather than used as a third DoS
                  estimate in its own right.

Everything the controller itself would be allowed to see (E1/E2 detector
reads, its own realized green/cycle) is computed the same way the real
adaptive controller computes it; ground truth is computed in a completely
separate code path that never touches simulated vehicle state.
"""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "controller"))
sys.path.insert(0, os.path.join(ROOT, "demand"))

SUMO_HOME = os.environ.get("SUMO_HOME") or \
    "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo"
os.environ.setdefault("SUMO_HOME", SUMO_HOME)
sys.path.append(os.path.join(SUMO_HOME, "tools"))
import traci  # noqa: E402
from controller_core import JunctionPlant  # noqa: E402
from demand_gen import write_demand  # noqa: E402
from rate_schedule import art_main_true_rate  # noqa: E402
from live_detectors import E1EntryCounter  # noqa: E402
import build_rerouter  # noqa: E402

SUMO_BIN = os.path.join(os.path.dirname(os.path.dirname(SUMO_HOME.rstrip("/"))), "bin", "sumo")
NET = os.path.join(ROOT, "net", "arterial_static.net.xml")
S_MEAS = 1604.4    # veh/h/lane, from det/satflow_result.txt
N_INT = 5
REGIME_SEGS = [("ramp", 0, 300), ("stationary", 300, 1200), ("reversal", 1200, 2100),
               ("surge", 2100, 2700), ("incident", 2700, 3300), ("recovery", 3300, 3900)]


def regime_of(t):
    for name, a, b in REGIME_SEGS:
        if a <= t < b:
            return name
    return "post"


def run(seed, workdir):
    os.makedirs(workdir, exist_ok=True)
    trips_path = os.path.join(workdir, "trips.rou.xml")
    write_demand(trips_path, seed, "unpred")
    rr = build_rerouter.build(workdir)
    adds = [os.path.join(HERE, "detectors.add.xml"),
            os.path.join(HERE, "detectors_badsetback.add.xml"), rr]

    traci.start([SUMO_BIN, "-n", NET, "-r", trips_path, "-a", ",".join(adds),
                 "--device.rerouting.probability", "1", "--device.rerouting.period", "20",
                 "--no-step-log", "true", "--time-to-teleport", "300",
                 "--ignore-route-errors", "true", "--end", "3900"])
    plants = {}
    # cumulative[det_id] = {t: cumulative entry count up to and including t}
    cumulative = {}
    good_ids, bad_ids, sb_ids = [], [], []
    for i in range(N_INT):
        j = "J%d" % i
        for d in ("EB", "WB"):
            for li in (0, 1):
                good_ids.append("ADV_%s_%s_%d" % (j, d, li))
                bad_ids.append("ADVBAD_%s_%s_%d" % (j, d, li))
            for li in (0, 1, 2):
                sb_ids.append("SB_%s_%s_%d" % (j, d, li))
    counter = E1EntryCounter(good_ids + bad_ids)
    for d in good_ids + bad_ids:
        cumulative[d] = {0: 0}
    occ_series = {d: [] for d in sb_ids}
    try:
        for j in traci.trafficlight.getIDList():
            plants[j] = JunctionPlant(j, min_green=8.0)
            plants[j].start(0.0)
        t = 0.0
        run_total = {d: 0 for d in good_ids + bad_ids}
        while t < 3900.0:
            traci.simulationStep()
            t = traci.simulation.getTime()
            for p in plants.values():
                p.step(t)
            counter.step()
            for d in good_ids + bad_ids:
                run_total[d] += counter.pop(d)
                cumulative[d][t] = run_total[d]
            for d in sb_ids:
                occ_series[d].append((t, traci.lanearea.getLastStepOccupancy(d)))
    finally:
        traci.close()
    return plants, cumulative, occ_series


def cum_at(cum_dict, t):
    """Cumulative entry count at time t, from a {time: cumulative_count} dict
    recorded once per simulation step (nearest recorded step <= t)."""
    tt = int(round(t))
    while tt not in cum_dict and tt > 0:
        tt -= 1
    return cum_dict.get(tt, 0)


def sum_window(cum_dict, t0, t1):
    return cum_at(cum_dict, t1) - cum_at(cum_dict, t0)


def occ_tail(series_list, t0, t1, tail=5.0):
    win = [v for t, v in series_list if max(t0, t1 - tail) <= t < t1]
    return sum(win) / len(win) / 100.0 if win else 0.0   # E2 occupancy reported in %


def analyze(plants, series, occ_series, seed, regime="unpred"):
    rows = [("seed", "junction", "direction", "cycle_idx", "t_start", "t_end", "regime",
             "C_real", "g_real", "q_true_vph", "DoS_true",
             "q_hat_good_vph", "DoS_hat_good", "q_hat_bad_vph", "DoS_hat_bad",
             "occ_tail_frac")]
    for i in range(N_INT):
        j = "J%d" % i
        plant = plants[j]
        for cyc_idx, (gs, ge, plan, C) in enumerate(plant.cycle_log):
            if gs < 60:
                continue
            g_real = ge - gs
            cyc_end = gs + C            # FULL local cycle window for volume counting
            tmid = (gs + cyc_end) / 2.0
            reg = regime_of(tmid)
            cap_hat = (g_real / C) * S_MEAS * 2.0   # 2 through lanes
            for d in ("EB", "WB"):
                q_true = art_main_true_rate(d, i, tmid, regime)
                dos_true = q_true / cap_hat if cap_hat > 0 else float("nan")
                # volume must be counted over the FULL CYCLE (arrivals during red
                # queue up and are served next green -- they are still part of
                # this cycle's demand), not just the green sub-window, or the
                # estimate is biased high by roughly a factor of C/g.
                good = sum(sum_window(series["ADV_%s_%s_%d" % (j, d, li)], gs, cyc_end) for li in (0, 1))
                bad = sum(sum_window(series["ADVBAD_%s_%s_%d" % (j, d, li)], gs, cyc_end) for li in (0, 1))
                q_hat_good = good / C * 3600.0 if C > 0 else 0.0
                q_hat_bad = bad / C * 3600.0 if C > 0 else 0.0
                dos_hat_good = q_hat_good / cap_hat if cap_hat > 0 else float("nan")
                dos_hat_bad = q_hat_bad / cap_hat if cap_hat > 0 else float("nan")
                ot = max(occ_tail(occ_series["SB_%s_%s_%d" % (j, d, li)], gs, ge) for li in (0, 1))
                rows.append((seed, j, d, cyc_idx, "%.1f" % gs,
                            "%.1f" % ge, reg, "%.2f" % C, "%.2f" % g_real,
                            "%.1f" % q_true, "%.4f" % dos_true,
                            "%.1f" % q_hat_good, "%.4f" % dos_hat_good,
                            "%.1f" % q_hat_bad, "%.4f" % dos_hat_bad, "%.4f" % ot))
    return rows


def main():
    header = None
    data = []
    for seed in (1, 2):
        workdir = os.path.join(HERE, "dos_seed%d" % seed)
        plants, series, occ_series = run(seed, workdir)
        rows = analyze(plants, series, occ_series, seed)
        header = rows[0]
        data += rows[1:]
    out = os.path.join(HERE, "dos_validation.csv")
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(data)
    print("wrote", out, "rows=", len(data))


if __name__ == "__main__":
    main()
