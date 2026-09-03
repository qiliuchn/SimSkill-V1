#!/usr/bin/env python3
"""Poisson-arrival directional demand generator for the climbing-lane facility.
Trucks get id prefix 'hv_' (matched by GradeAwareController.truck_prefix);
cars get 'pc_'. Route is the 5-edge EB or WB chain from build_facility.py."""
import random

EB_EDGES = "approach taper_in grade taper_out departure"
WB_EDGES = "wb_departure wb_taper_out wb_grade wb_taper_in wb_approach"


def write_route_file(path, direction, volume_vph, truck_pct, seed, sim_end,
                      ratio=120.0, car_max_speed=33.33, truck_max_speed=30.0):
    rng = random.Random(seed)
    edges = EB_EDGES if direction == "EB" else WB_EDGES
    rate_per_s = volume_vph / 3600.0
    vehicles = []
    t = 0.0
    idx = 0
    while t < sim_end:
        iat = rng.expovariate(rate_per_s) if rate_per_s > 0 else 1e9
        t += iat
        if t >= sim_end:
            break
        is_truck = rng.random() < (truck_pct / 100.0)
        vehicles.append((t, is_truck, idx))
        idx += 1
    with open(path, "w") as f:
        f.write('<routes>\n')
        f.write('  <vType id="pc" vClass="passenger" carFollowModel="Krauss" sigma="0.5" '
                'speedFactor="normc(1.0,0.1,0.7,1.3)" maxSpeed="%.2f" accel="2.6" decel="4.5" '
                'length="4.5" tau="1.0"/>\n' % car_max_speed)
        f.write('  <vType id="hvt" vClass="truck" carFollowModel="Krauss" sigma="0.5" '
                'speedFactor="normc(0.95,0.05,0.8,1.05)" maxSpeed="%.2f" accel="1.3" decel="4.0" '
                'length="16.5" tau="1.2" mass="36287"/>\n' % truck_max_speed)
        f.write('  <route id="rt_%s" edges="%s"/>\n' % (direction, edges))
        for (dep, is_truck, i) in vehicles:
            if is_truck:
                f.write('  <vehicle id="hv_%d" type="hvt" route="rt_%s" depart="%.2f" '
                        'departSpeed="max" departLane="free"/>\n' % (i, direction, dep))
            else:
                f.write('  <vehicle id="pc_%d" type="pc" route="rt_%s" depart="%.2f" '
                        'departSpeed="max" departLane="free"/>\n' % (i, direction, dep))
        f.write('</routes>\n')
    n_truck = sum(1 for (_, tk, _) in vehicles if tk)
    return {"n_vehicles": len(vehicles), "n_truck": n_truck,
            "realized_truck_pct": 100.0 * n_truck / len(vehicles) if vehicles else 0.0}
