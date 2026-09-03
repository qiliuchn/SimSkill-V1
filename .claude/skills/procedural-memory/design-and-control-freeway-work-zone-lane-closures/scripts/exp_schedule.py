"""SCHEDULING layer: partial lane closure under a daytime peak vs FULL closure with a
mandatory detour under an off-peak/night profile.

Road-user cost (RUC) of a closure strategy at a given demand level, relative to the
SAME demand with NO work zone at all:

    RUC = (TSTT_closure - TSTT_nowork) * VOT
        + (fuel_closure - fuel_nowork) * FUEL_PRICE
        + (CO2_closure  - CO2_nowork)  * CARBON_PRICE

TSTT includes the origin-insertion integral, so a closure that simply refuses to insert
vehicles is charged for it (the honesty requirement inherited from the ramp-metering
skill).  Fuel and CO2 come from HBEFA3 edgeData, not from tripinfo, so they cover every
vehicle-second in the network including internal edges.

Three strategies per demand level:
  nowork   lanes_closed=0, free posted speed, phi=0          (reference)
  partial  lanes_closed=1, wz speed 80, phi=0                (partial closure)
  full     mainline fully closed, phi=1.0 mandatory detour   (full closure)

The demand threshold is where RUC(full) crosses RUC(partial).
"""
import os

import wz_common as W
import batch

OUTD = os.path.join(W.OUT, "schedule")
os.makedirs(OUTD, exist_ok=True)

# Road-user cost coefficients (documented, not hidden in code):
VOT = 20.0          # currency units per vehicle-hour
FUEL_PRICE = 1.80   # per litre
CARBON_PRICE = 0.10  # per kg CO2

DEMANDS = (600, 1000, 1400, 1800, 2200, 2600, 3000, 3600)
SEEDS = (1, 2, 3)


def cells(demands=DEMANDS, seeds=SEEDS):
    cs = []
    for q in demands:
        for sd in seeds:
            cs.append(dict(label=f"sch_nowork_q{q}_s{sd}", outroot=OUTD,
                           arm="donothing", rep="geom", merge="priority",
                           peak=q, seed=sd, phi=0.0, demand_seed=500 + sd,
                           params=dict(lanes_closed=0, wz_speed_kmh=120),
                           tagname="nowork"))
            cs.append(dict(label=f"sch_partial_q{q}_s{sd}", outroot=OUTD,
                           arm="donothing", rep="geom", merge="priority",
                           peak=q, seed=sd, phi=0.0, demand_seed=500 + sd,
                           params=dict(lanes_closed=1, wz_speed_kmh=80),
                           tagname="partial"))
            cs.append(dict(label=f"sch_full_q{q}_s{sd}", outroot=OUTD,
                           arm="donothing", rep="geom", merge="priority",
                           peak=q, seed=sd, phi=1.0, demand_seed=500 + sd,
                           params=dict(lanes_closed=2, wz_speed_kmh=80),
                           tagname="full"))
    return cs


if __name__ == "__main__":
    cs = cells()
    print(f"{len(cs)} scheduling cells")
    batch.run_cells(cs, os.path.join(OUTD, "schedule_results.json"))
