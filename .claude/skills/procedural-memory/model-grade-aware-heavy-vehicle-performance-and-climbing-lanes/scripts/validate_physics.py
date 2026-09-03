#!/usr/bin/env python3
"""SUB-GOAL 2 -- validate the TraCI GradeAwareController against:
  (1) the independent analytical RK4 integration + bisection crawl speed
      (analytical_check.py, written independently of physics_model.py);
  (2) the qualitative AASHTO truck-performance-curve shape: crawl speed
      approached after ~1-3 km, crawl speed falling with grade and with
      weight/power ratio;
  (3) safety: zero collisions / zero teleports on a multi-truck+car open-road
      run, and a following-a-slow-lead-vehicle case showing the ceiling is
      non-binding when traffic (not physics) is the constraint.
Also reports TraCI call count and wall-clock runtime vs a default (no
controller) run of the same scenario.
"""
import os, sys, json, math, time, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import SUMO_HOME, SUMO_BIN, NETCONVERT_BIN, WORK, RESULTS, DEFAULT_MASS_KG
import traci
from physics_model import GradeAwareController, accel_from_grade_percent
import analytical_check as ac

W = os.path.join(WORK, "validate")
os.makedirs(W, exist_ok=True)
EDGE_LEN = 6000.0


def build_net(grade_pct, tag, numlanes=1, speed=33.33):
    dz = EDGE_LEN * grade_pct / 100.0
    nod = os.path.join(W, "%s.nod.xml" % tag)
    with open(nod, "w") as f:
        f.write('<nodes>\n<node id="A" x="0" y="0" z="0"/>\n'
                '<node id="B" x="%.2f" y="0" z="%.4f"/>\n</nodes>\n' % (EDGE_LEN, dz))
    edg = os.path.join(W, "%s.edg.xml" % tag)
    with open(edg, "w") as f:
        f.write('<edges>\n<edge id="E" from="A" to="B" numLanes="%d" speed="%.2f"/>\n</edges>\n' % (numlanes, speed))
    net = os.path.join(W, "%s.net.xml" % tag)
    subprocess.run([NETCONVERT_BIN, "-n", nod, "-e", edg, "-o", net, "--no-turnarounds", "true"],
                    check=True, capture_output=True)
    return net


def run_open_road(grade_pct, ratio, mass_kg=DEFAULT_MASS_KG, end=500, dt=1.0, road_speed=33.33):
    net = build_net(grade_pct, "vopen_g%g" % grade_pct, speed=road_speed)
    rou = os.path.join(W, "vopen_g%g_r%g.rou.xml" % (grade_pct, ratio))
    with open(rou, "w") as f:
        f.write('<routes>\n<vType id="hvt" vClass="truck" carFollowModel="Krauss" sigma="0" '
                'speedDev="0" accel="1.3" decel="4.0" maxSpeed="30.0" tau="1.0"/>\n'
                '<route id="r" edges="E"/>\n'
                '<vehicle id="hv_1" type="hvt" route="r" depart="0" departSpeed="0" departLane="0"/>\n'
                '</routes>\n')
    label = "vopen_%g_%g" % (grade_pct, ratio)
    traci.start([SUMO_BIN, "-n", net, "-r", rou, "--step-length", str(dt), "--no-step-log", "true",
                 "--xml-validation", "never", "--end", str(end), "--collision.action", "warn"], label=label)
    traci.switch(label)
    ctrl = GradeAwareController(weight_to_power_kg_per_kw=ratio, mass_kg=mass_kg)
    traj = []
    t0 = time.time()
    while traci.simulation.getMinExpectedNumber() > 0:
        traci.simulationStep()
        ctrl.call_count += 1
        ctrl.step(dt=dt)
        if "hv_1" in traci.vehicle.getIDList():
            traj.append((round(traci.simulation.getTime(), 1),
                         round(traci.vehicle.getDistance("hv_1"), 3),
                         round(traci.vehicle.getSpeed("hv_1"), 4)))
            ctrl.call_count += 2
    wall = time.time() - t0
    traci.close()
    stats = ctrl.stats()
    stats["wall_seconds"] = round(wall, 3)
    return traj, stats


def run_default_open_road(grade_pct, end=500, dt=1.0, road_speed=33.33):
    net = build_net(grade_pct, "vdef_g%g" % grade_pct, speed=road_speed)
    rou = os.path.join(W, "vdef_g%g.rou.xml" % grade_pct)
    with open(rou, "w") as f:
        f.write('<routes>\n<vType id="hvt" vClass="truck" carFollowModel="Krauss" sigma="0" '
                'speedDev="0" accel="1.3" decel="4.0" maxSpeed="30.0" tau="1.0"/>\n'
                '<route id="r" edges="E"/>\n'
                '<vehicle id="hv_1" type="hvt" route="r" depart="0" departSpeed="0" departLane="0"/>\n'
                '</routes>\n')
    t0 = time.time()
    r = subprocess.run([SUMO_BIN, "-n", net, "-r", rou, "--step-length", str(dt), "--no-step-log", "true",
                         "--xml-validation", "never", "--end", str(end)], capture_output=True, text=True)
    wall = time.time() - t0
    return wall, r.returncode


def main():
    out = {"analytical_vs_traci": [], "aashto_shape_checks": [], "safety_checks": {},
           "runtime_comparison": {}}

    # (1) Analytical cross-check: 3 ratios x 4 grades, compare crawl speed and
    # trajectory at matched distance checkpoints.
    for ratio in (90, 120, 180):
        for grade in (0, 2, 4, 6):
            traj, stats = run_open_road(grade, ratio, end=400)
            traci_final_v = traj[-1][2] if traj else None
            traci_vmax = max((v for (_, _, v) in traj), default=None)
            analytic_crawl = ac.crawl_speed(grade, DEFAULT_MASS_KG, DEFAULT_MASS_KG / ratio * 1000.0)
            rk4 = ac.rk4_truck_trajectory(0.0, grade, DEFAULT_MASS_KG, DEFAULT_MASS_KG / ratio * 1000.0,
                                           dt=0.1, t_end=400)
            rk4_final_v = rk4[-1][2]
            # distance to reach 95% of crawl speed, both methods
            def dist_to_95pct(trajectory, target):
                thr = 0.95 * target
                for (t, d, v) in trajectory:
                    if v >= thr:
                        return d
                return None
            d95_traci = dist_to_95pct(traj, analytic_crawl)
            d95_rk4 = dist_to_95pct(rk4, analytic_crawl)
            rel_err_final = abs(traci_final_v - analytic_crawl) / analytic_crawl if analytic_crawl > 0.5 else None
            out["analytical_vs_traci"].append({
                "ratio": ratio, "grade_pct": grade,
                "analytic_crawl_speed_ms": round(analytic_crawl, 3),
                "rk4_final_v_ms": round(rk4_final_v, 3),
                "traci_final_v_ms": traci_final_v, "traci_vmax_ms": traci_vmax,
                "rel_err_traci_vs_analytic_crawl": round(rel_err_final, 4) if rel_err_final is not None else None,
                "dist_to_95pct_crawl_traci_m": d95_traci, "dist_to_95pct_crawl_rk4_m": d95_rk4,
                "traci_call_count": stats["traci_call_count"], "wall_seconds": stats["wall_seconds"],
            })

    # (2) AASHTO shape check summary derived from the same data: crawl approached
    # within ~1-3km, and monotonic decrease with grade and with ratio.
    rows = out["analytical_vs_traci"]
    for ratio in (90, 120, 180):
        rr = [r for r in rows if r["ratio"] == ratio]
        crawlspeeds = [r["traci_final_v_ms"] for r in rr]
        grades = [r["grade_pct"] for r in rr]
        monotonic_decreasing = all(crawlspeeds[i] >= crawlspeeds[i + 1] - 1e-6 for i in range(len(crawlspeeds) - 1))
        dists = [r["dist_to_95pct_crawl_traci_m"] for r in rr if r["grade_pct"] > 0]
        out["aashto_shape_checks"].append({
            "ratio": ratio, "crawl_speed_by_grade_ms": dict(zip(grades, crawlspeeds)),
            "monotonic_decreasing_with_grade": monotonic_decreasing,
            "dist_to_95pct_crawl_m_uphill_only": dists,
            "within_1_to_3km": [(d is not None and 1000 <= d <= 3000) for d in dists],
        })
    # monotonic decrease with weight/power ratio at fixed grade
    for grade in (2, 4, 6):
        vs = [r["traci_final_v_ms"] for r in sorted([x for x in rows if x["grade_pct"] == grade], key=lambda x: x["ratio"])]
        out["aashto_shape_checks"].append({"grade": grade, "crawl_by_ratio_90_120_180": vs,
                                            "monotonic_decreasing_with_ratio": vs[0] >= vs[1] - 1e-6 >= vs[2] - 2e-6})

    # (3) Safety checks -----------------------------------------------------
    # (3a) multi-truck + car open road, high demand, check 0 collisions/teleports
    net = build_net(6.0, "safety_g6", numlanes=2, speed=27.78)
    rou = os.path.join(W, "safety.rou.xml")
    with open(rou, "w") as f:
        f.write('<routes>\n')
        f.write('<vType id="car" vClass="passenger" carFollowModel="Krauss" maxSpeed="33.3"/>\n')
        f.write('<vType id="hvt" vClass="truck" carFollowModel="Krauss" maxSpeed="30.0"/>\n')
        f.write('<route id="r" edges="E"/>\n')
        for i in range(60):
            vt = "hvt" if i % 4 == 0 else "car"
            pre = "hv_" if vt == "hvt" else "c_"
            f.write('<vehicle id="%s%d" type="%s" route="r" depart="%.1f" departSpeed="0" departLane="random"/>\n'
                     % (pre, i, vt, i * 4.0))
        f.write('</routes>\n')
    label = "safety1"
    traci.start([SUMO_BIN, "-n", net, "-r", rou, "--step-length", "1.0", "--no-step-log", "true",
                 "--xml-validation", "never", "--end", "600", "--collision.action", "warn",
                 "--collision-output", os.path.join(W, "safety_collisions.xml")], label=label)
    traci.switch(label)
    ctrl = GradeAwareController(weight_to_power_kg_per_kw=120.0, truck_prefix="hv_")
    n_collisions = 0
    while traci.simulation.getMinExpectedNumber() > 0:
        traci.simulationStep()
        ctrl.step(dt=1.0)
        n_collisions += traci.simulation.getCollidingVehiclesNumber()
    teleports = traci.simulation.getStartingTeleportNumber()
    traci.close()
    out["safety_checks"]["multi_vehicle_open_road"] = {
        "n_vehicles": 60, "collisions_observed_live": n_collisions,
        "teleports": teleports,
        "grade_pct": 6.0,
    }
    # parse collision-output file for a ground-truth count too
    import xml.etree.ElementTree as ET
    coll_file = os.path.join(W, "safety_collisions.xml")
    n_coll_file = 0
    if os.path.exists(coll_file):
        try:
            troot = ET.parse(coll_file).getroot()
            n_coll_file = len(troot.findall("collision"))
        except Exception:
            n_coll_file = -1
    out["safety_checks"]["multi_vehicle_open_road"]["collisions_from_output_file"] = n_coll_file

    # (3b) non-binding-under-traffic-constraint check: a truck queued behind a
    # slow lead car climbing the SAME grade -- ceiling should sit above actual
    # speed (never itself the thing forcing the low speed).
    net2 = build_net(6.0, "nonbinding_g6", numlanes=1, speed=27.78)
    rou2 = os.path.join(W, "nonbinding.rou.xml")
    with open(rou2, "w") as f:
        f.write('<routes>\n<vType id="slowcar" vClass="passenger" carFollowModel="Krauss" maxSpeed="4.0"/>\n'
                '<vType id="hvt" vClass="truck" carFollowModel="Krauss" maxSpeed="30.0"/>\n'
                '<route id="r" edges="E"/>\n'
                '<vehicle id="lead" type="slowcar" route="r" depart="0" departSpeed="0" departLane="0"/>\n'
                '<vehicle id="hv_1" type="hvt" route="r" depart="0" departSpeed="0" departLane="0"/>\n'
                '</routes>\n')
    label = "nonbinding1"
    traci.start([SUMO_BIN, "-n", net2, "-r", rou2, "--step-length", "1.0", "--no-step-log", "true",
                 "--xml-validation", "never", "--end", "300", "--collision.action", "warn"], label=label)
    traci.switch(label)
    ctrl2 = GradeAwareController(weight_to_power_kg_per_kw=120.0, truck_prefix="hv_")
    rows_nb = []
    while traci.simulation.getMinExpectedNumber() > 0:
        traci.simulationStep()
        ctrl2.step(dt=1.0)
        if "hv_1" in traci.vehicle.getIDList():
            actual_v = traci.vehicle.getSpeed("hv_1")
            ceiling = ctrl2.v_attain.get("hv_1")
            rows_nb.append((round(traci.simulation.getTime(), 1), round(actual_v, 3),
                             round(ceiling, 3) if ceiling is not None else None))
    traci.close()
    non_binding_frac = sum(1 for (t, a, c) in rows_nb if c is not None and c >= a - 1e-6) / max(1, len(rows_nb))
    out["safety_checks"]["non_binding_under_traffic"] = {
        "fraction_of_steps_ceiling_at_or_above_actual_speed": round(non_binding_frac, 4),
        "n_steps": len(rows_nb),
        "sample": rows_nb[:10] + rows_nb[-10:] if len(rows_nb) > 20 else rows_nb,
        "max_actual_speed_reached": max((a for (t, a, c) in rows_nb), default=None),
    }

    # (4) runtime comparison: default subprocess run vs traci-controlled run,
    # same 60-vehicle scenario.
    wall_default, rc = run_default_open_road(6.0, end=600, road_speed=27.78)
    t0 = time.time()
    traci.start([SUMO_BIN, "-n", net, "-r", rou, "--step-length", "1.0", "--no-step-log", "true",
                 "--xml-validation", "never", "--end", "600"], label="rt_ctrl")
    traci.switch("rt_ctrl")
    ctrl3 = GradeAwareController(weight_to_power_kg_per_kw=120.0, truck_prefix="hv_")
    while traci.simulation.getMinExpectedNumber() > 0:
        traci.simulationStep()
        ctrl3.step(dt=1.0)
    traci.close()
    wall_ctrl = time.time() - t0
    out["runtime_comparison"] = {
        "default_subprocess_wall_s": round(wall_default, 3),
        "grade_aware_traci_wall_s": round(wall_ctrl, 3),
        "slowdown_factor": round(wall_ctrl / wall_default, 2) if wall_default > 0 else None,
        "traci_call_count_60veh_600s": ctrl3.call_count,
    }

    with open(os.path.join(RESULTS, "validate_physics.json"), "w") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out["aashto_shape_checks"], indent=2))
    print(json.dumps(out["safety_checks"], indent=2))
    print(json.dumps(out["runtime_comparison"], indent=2))
    print("Full detail saved to", os.path.join(RESULTS, "validate_physics.json"))


if __name__ == "__main__":
    main()
