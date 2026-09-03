#!/usr/bin/env python3
"""
Heterogeneous managed-lane corridor demand.

Every vehicle gets an EXPLICIT occupancy and an EXPLICIT value of time (VOT, $/person-hour,
lognormal).  Vehicle ids encode the class so the class survives a TraCI
setVehicleClass() call (which replaces the vType with a singular copy).

Emits:
  <stem>.rou.xml   SUMO route file (explicit <vehicle> elements, sorted by depart)
  <stem>.fleet.csv id,cls,vclass,occ,vot,route,depart

CRN: for a given (seed, carpool_share, demand_scale) the fleet is byte-identical, and the
SAME file is fed to every policy arm.
"""
import argparse
import csv
import math
import os
import random

# ---- corridor route definitions (edge ids from build_networks.py) -------------
MAIN = [f"m{i}" for i in range(1, 15)]
ROUTES = {
    "main_end":  MAIN,                       # 0 -> 7000  (full corridor)
    "main_off1": MAIN[:6] + ["off1"],        # 0 -> off-ramp 1 (x=3000)
    "main_off2": MAIN[:12] + ["off2"],       # 0 -> off-ramp 2 (x=6000)
    "on1_end":   ["on1"] + MAIN[3:],         # on-ramp 1 -> 7000
    "on1_off2":  ["on1"] + MAIN[3:12] + ["off2"],
    "on2_end":   ["on2"] + MAIN[9:],         # on-ramp 2 -> 7000
}
# entry-flow split at 1.0 demand scale (veh/h at the peak plateau)
BASE_FLOWS = {
    "main_end":  3050.0,
    "main_off1":  850.0,
    "main_off2":  900.0,
    "on1_end":    550.0,
    "on1_off2":   300.0,
    "on2_end":    750.0,
}
# -> mainline load on the busiest section (m10..m12, after on-ramp 2, before off-ramp 2)
#    = main_end + main_off2 + on1_end + on1_off2 + on2_end = 5550 veh/h at scale 1.0

VTYPES = """    <vType id="t_sov"     vClass="passenger" length="4.8" minGap="2.5" accel="2.6" decel="4.5" sigma="0.5" maxSpeed="36.0" speedFactor="normc(1.0,0.10,0.75,1.25)" tau="1.1" lcKeepRight="1.0" lcSpeedGain="1.5" lcCooperative="1.0"/>
    <vType id="t_hov"     vClass="hov"       length="4.8" minGap="2.5" accel="2.6" decel="4.5" sigma="0.5" maxSpeed="36.0" speedFactor="normc(1.0,0.10,0.75,1.25)" tau="1.1" lcKeepRight="1.0" lcSpeedGain="1.5" lcCooperative="1.0"/>
    <vType id="t_bus"     vClass="bus"       length="12.0" minGap="3.0" accel="1.2" decel="3.5" sigma="0.5" maxSpeed="28.0" speedFactor="normc(0.95,0.05,0.8,1.1)" tau="1.4" lcKeepRight="1.0" lcSpeedGain="1.0" lcCooperative="1.0"/>
"""


def demand_profile(t, t_ramp_up, t_peak_end, t_end):
    """Multiplier on the peak plateau flow at time t (s)."""
    if t < t_ramp_up:
        return 0.35 + 0.65 * (t / t_ramp_up)
    if t < t_peak_end:
        return 1.0
    if t < t_end:
        return max(0.0, 1.0 - 0.85 * (t - t_peak_end) / (t_end - t_peak_end))
    return 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--carpool-share", type=float, default=0.15,
                    help="share of NON-BUS vehicles that are carpools (hov)")
    ap.add_argument("--demand-scale", type=float, default=1.0)
    ap.add_argument("--bus-veh-per-hour", type=float, default=25.0,
                    help="buses/h on main_end at scale 1.0 (they are ADDED, not carved out)")
    ap.add_argument("--vot-median", type=float, default=25.0, help="$/person-hour")
    ap.add_argument("--vot-sigma", type=float, default=0.70, help="lognormal sigma")
    ap.add_argument("--horizon", type=float, default=3600.0, help="loading horizon (s)")
    ap.add_argument("--out-stem", required=True)
    a = ap.parse_args()

    rng = random.Random(a.seed)
    t_ramp_up, t_peak_end, t_end = 600.0, 3000.0, a.horizon
    mu = math.log(a.vot_median)

    veh = []
    # --- cars (SOV + carpool), thinned Poisson per route -----------------------
    for rname, base in BASE_FLOWS.items():
        rate = base * a.demand_scale / 3600.0     # veh/s at plateau
        t = 0.0
        while True:
            t += rng.expovariate(rate * 1.0)
            if t >= t_end:
                break
            if rng.random() > demand_profile(t, t_ramp_up, t_peak_end, t_end):
                continue                            # thinning -> time-varying profile
            if rng.random() < a.carpool_share:
                cls, vc, vt = "hov", "hov", "t_hov"
                occ = 2 if rng.random() < 0.72 else 3
            else:
                cls, vc, vt = "sov", "passenger", "t_sov"
                occ = 1
            veh.append([t, cls, vc, vt, occ, rng.lognormvariate(mu, a.vot_sigma), rname])
    # --- buses on the two long routes ----------------------------------------
    for rname, frac in (("main_end", 0.7), ("on1_end", 0.3)):
        rate = a.bus_veh_per_hour * frac * a.demand_scale / 3600.0
        t = 0.0
        while True:
            t += rng.expovariate(rate)
            if t >= t_end:
                break
            if rng.random() > demand_profile(t, t_ramp_up, t_peak_end, t_end):
                continue
            occ = max(8, int(round(rng.gauss(40.0, 9.0))))
            veh.append([t, "bus", "bus", "t_bus", occ, rng.lognormvariate(mu, a.vot_sigma), rname])

    veh.sort(key=lambda r: r[0])

    rou = a.out_stem + ".rou.xml"
    csvf = a.out_stem + ".fleet.csv"
    os.makedirs(os.path.dirname(os.path.abspath(rou)), exist_ok=True)
    counts = {"sov": 0, "hov": 0, "bus": 0}
    with open(rou, "w") as f, open(csvf, "w", newline="") as g:
        w = csv.writer(g)
        w.writerow(["id", "cls", "vclass", "occ", "vot", "route", "depart"])
        f.write("<routes>\n")
        f.write(VTYPES)
        for rname, edges in ROUTES.items():
            f.write(f'    <route id="r_{rname}" edges="{" ".join(edges)}"/>\n')
        for i, (t, cls, vc, vt, occ, vot, rname) in enumerate(veh):
            counts[cls] += 1
            vid = f"{cls}.{i}"
            f.write(f'    <vehicle id="{vid}" type="{vt}" route="r_{rname}" depart="{t:.2f}" '
                    f'departLane="best" departSpeed="max"/>\n')
            w.writerow([vid, cls, vc, occ, f"{vot:.4f}", rname, f"{t:.2f}"])
        f.write("</routes>\n")

    tot_people = 0
    with open(csvf) as g:
        for r in csv.DictReader(g):
            tot_people += int(r["occ"])
    print(f"{os.path.basename(a.out_stem)}: {len(veh)} veh "
          f"(sov={counts['sov']} hov={counts['hov']} bus={counts['bus']}), {tot_people} people")


if __name__ == "__main__":
    main()
