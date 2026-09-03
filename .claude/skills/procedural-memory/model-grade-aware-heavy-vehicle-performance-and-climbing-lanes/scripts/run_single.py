#!/usr/bin/env python3
"""Run ONE sweep cell: a given facility variant/grade/length/direction under
a given directional volume + truck% + model (grade_blind default vs
grade_aware physics controller) + seed. Returns a metrics dict; also writes
tripinfo/edgeData/laneData outputs for later re-analysis if needed.
"""
import os, sys, json, subprocess, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import SUMO_BIN, WORK
from build_facility import build_variant
from demand import write_route_file

WARMUP = 300.0          # seconds excluded from measurement window (startup transient)
MEASURE_WINDOW = 900.0  # seconds of demand generated AFTER warmup (the measured period)
TAIL_BUFFER = 1200.0    # extra sim seconds after the last-generated vehicle's depart,
                         # so even a slow truck queued/crawling has time to finish its trip
                         # before tripinfo is written -- without this, essentially ALL
                         # trucks show up as "still in network at sim end" (vaporized/
                         # unfinished) and truck statistics are silently empty.


def _additional_xml(path, edgedata_all, edgedata_truck, lanedata_all, lanedata_truck, freq=60):
    with open(path, "w") as f:
        f.write('<additional>\n')
        f.write('  <edgeData id="ed_all" file="%s" freq="%d"/>\n' % (edgedata_all, freq))
        f.write('  <edgeData id="ed_truck" file="%s" freq="%d" vTypes="hvt"/>\n' % (edgedata_truck, freq))
        f.write('  <laneData id="ld_all" file="%s" freq="%d"/>\n' % (lanedata_all, freq))
        f.write('  <laneData id="ld_truck" file="%s" freq="%d" vTypes="hvt"/>\n' % (lanedata_truck, freq))
        f.write('</additional>\n')


def run_cell(grade_pct, grade_len_km, variant, direction, volume_vph, truck_pct,
             seed, model, ratio=120.0, sim_end=None, run_dir=None, step_length=1.0,
             governor_speed=None, measure_window=MEASURE_WINDOW, tail_buffer=TAIL_BUFFER):
    assert model in ("grade_blind", "grade_aware")
    tag = "c_g%g_L%g_%s_%s_v%g_t%g_%s_s%d" % (grade_pct, grade_len_km, variant, direction,
                                               volume_vph, truck_pct, model, seed)
    run_dir = run_dir or os.path.join(WORK, "cells", tag)
    os.makedirs(run_dir, exist_ok=True)

    info = build_variant(grade_pct, grade_len_km, variant, out_dir=run_dir)
    net_path = info["net_path"]
    rou_path = os.path.join(run_dir, "demand.rou.xml")
    demand_end = WARMUP + measure_window
    if sim_end is None:
        sim_end = demand_end + tail_buffer
    dstats = write_route_file(rou_path, direction, volume_vph, truck_pct, seed, demand_end, ratio=ratio)

    trip_path = os.path.join(run_dir, "tripinfo.xml")
    coll_path = os.path.join(run_dir, "collisions.xml")
    ed_all = os.path.join(run_dir, "edgedata_all.xml")
    ed_truck = os.path.join(run_dir, "edgedata_truck.xml")
    ld_all = os.path.join(run_dir, "lanedata_all.xml")
    ld_truck = os.path.join(run_dir, "lanedata_truck.xml")
    stat_path = os.path.join(run_dir, "stats.xml")
    add_path = os.path.join(run_dir, "additional.xml")
    _additional_xml(add_path, ed_all, ed_truck, ld_all, ld_truck)

    base_args = [SUMO_BIN, "-n", net_path, "-r", rou_path, "-a", add_path,
                 "--step-length", str(step_length), "--no-step-log", "true",
                 "--xml-validation", "never", "--end", str(sim_end),
                 "--tripinfo-output", trip_path, "--collision.action", "warn",
                 "--collision-output", coll_path, "--tripinfo-output.write-unfinished", "true",
                 "--time-to-teleport", "300", "--statistic-output", stat_path,
                 "--seed", str(seed)]

    t0 = time.time()
    profile_bins = None
    traci_call_count = 0
    n_steps = 0
    if model == "grade_blind":
        r = subprocess.run(base_args, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("sumo failed (%s):\n%s" % (tag, r.stderr[-2000:]))
    else:
        import traci
        from physics_model import GradeAwareController
        label = "cell_" + tag
        traci.start(base_args, label=label)
        traci.switch(label)
        ctrl = GradeAwareController(weight_to_power_kg_per_kw=ratio, truck_prefix="hv_",
                                     governor_speed=governor_speed)
        bin_w = 100.0
        n_bins = 90  # 9000m > 8000m corridor, safety margin
        bin_sum = [0.0] * n_bins
        bin_cnt = [0] * n_bins
        route_edges = ["approach", "taper_in", "grade", "taper_out", "departure"] if direction == "EB" else \
            ["wb_departure", "wb_taper_out", "wb_grade", "wb_taper_in", "wb_approach"]
        while traci.simulation.getMinExpectedNumber() > 0:
            traci.simulationStep()
            n_steps += 1
            ctrl.step(dt=step_length)
            for vid in ctrl.known:
                try:
                    d = traci.vehicle.getDistance(vid)
                except Exception:
                    continue
                if d is None or d < 0:
                    continue
                b = int(d // bin_w)
                if 0 <= b < n_bins:
                    sp = traci.vehicle.getSpeed(vid)
                    bin_sum[b] += sp
                    bin_cnt[b] += 1
            if n_steps > int(sim_end / step_length) + 5:
                break
        traci_call_count = ctrl.call_count
        traci.close()
        profile_bins = {"bin_width_m": bin_w,
                         "mean_speed_by_bin": [round(bin_sum[i] / bin_cnt[i], 3) if bin_cnt[i] else None
                                                for i in range(n_bins)],
                         "count_by_bin": bin_cnt}
    wall = time.time() - t0

    result = {
        "tag": tag, "grade_pct": grade_pct, "grade_len_km": grade_len_km, "variant": variant,
        "direction": direction, "volume_vph": volume_vph, "truck_pct_nominal": truck_pct,
        "truck_pct_realized": dstats["realized_truck_pct"], "n_vehicles_generated": dstats["n_vehicles"],
        "seed": seed, "model": model, "ratio": ratio, "wall_seconds": round(wall, 3),
        "traci_call_count": traci_call_count, "n_steps": n_steps,
        "run_dir": run_dir, "tripinfo_path": trip_path, "collisions_path": coll_path,
        "edgedata_all_path": ed_all, "edgedata_truck_path": ed_truck, "lanedata_path": ld_all,
        "lanedata_truck_path": ld_truck, "stats_path": stat_path,
        "profile_bins": profile_bins, "facility_edges": info["eb_edge_id_list"],
    }
    with open(os.path.join(run_dir, "meta.json"), "w") as f:
        json.dump(result, f, indent=2)
    return result


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--grade", type=float, default=4.0)
    p.add_argument("--length", type=float, default=2.0)
    p.add_argument("--variant", default="climbing_gp")
    p.add_argument("--direction", default="EB")
    p.add_argument("--volume", type=float, default=1400.0)
    p.add_argument("--truckpct", type=float, default=15.0)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--model", default="grade_aware")
    p.add_argument("--end", type=float, default=None)
    a = p.parse_args()
    res = run_cell(a.grade, a.length, a.variant, a.direction, a.volume, a.truckpct, a.seed, a.model,
                    sim_end=a.end)
    print(json.dumps({k: v for k, v in res.items() if k != "profile_bins"}, indent=2))
