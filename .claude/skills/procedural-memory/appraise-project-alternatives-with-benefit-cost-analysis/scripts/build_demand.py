#!/usr/bin/env python3
"""
AM peak-hour demand for the appraisal corridor.

Demand is specified as an explicit turning-movement / OD table (entry edge ->
exit edge with a share), NOT randomTrips, so that:
  * the arterial through movement genuinely dominates (AM peak, inbound = EB),
  * left-turn demand is deliberately concentrated at J2 and J3 (the intersections
    that alternative C rebuilds),
  * the same table can be scaled by a demand-growth factor for the horizon year.

Vehicle mix: 88% passenger cars (3 HBEFA3 sub-classes), 12% heavy vehicles
(7% HDV truck + 5% diesel LDV van).

Output: a .trips.xml valid for BOTH network variants (entry/exit edge ids are
identical across variants), so a given (seed, year) uses literally the same
departure times and OD pairs in every alternative -> Common Random Numbers.
"""
import argparse
import os
import random

N_INT = 5

# --- base AM peak-hour entry volumes (veh/h) --------------------------------
V_EB = 1200.0     # arterial eastbound (inbound / peak direction)
V_WB = 800.0      # arterial westbound (contra-peak)
V_CROSS = 200.0   # each of the 10 cross-street entries

# --- destination shares per entry -------------------------------------------
# Arterial eastbound entry (edge W_J1). Lefts concentrated at J2/J3.
EB_DEST = {
    'J5_E': 0.62,     # through the whole corridor
    'J2_N2': 0.10,    # EB LEFT at J2
    'J3_N3': 0.10,    # EB LEFT at J3
    'J1_S1': 0.04,    # EB right
    'J2_S2': 0.04,
    'J3_S3': 0.04,
    'J4_N4': 0.03,    # EB left at J4
    'J5_S5': 0.03,
}
# Arterial westbound entry (edge E_J5).
WB_DEST = {
    'J1_W': 0.66,
    'J3_S3': 0.09,    # WB LEFT at J3
    'J2_S2': 0.08,    # WB LEFT at J2
    'J3_N3': 0.06,    # WB right
    'J4_N4': 0.05,
    'J5_N5': 0.06,
}
# Cross-street entries: through / onto arterial eastbound / onto arterial westbound
CROSS_THROUGH = 0.40
CROSS_TO_EAST = 0.32
CROSS_TO_WEST = 0.28

VTYPES = """<additional>
    <!-- AM-peak fleet: 88% passenger car, 12% heavy vehicle (7% HDV + 5% LDV van).
         emissionClass = HBEFA3 (see semantic-memory/vehicle-emissions-modeling.md);
         vClass is independent of emissionClass and is set explicitly on each type.
         SSM device is attached here so every vehicle carries it; the SSM OUTPUT FILE
         is deliberately NOT set as a vType param (duarouter mangles relative paths);
         it is passed per run via sumo's device.ssm.file option instead. -->
    <vTypeDistribution id="fleet">
        <vType id="car_eu6"  vClass="passenger" emissionClass="HBEFA3/PC_G_EU6" probability="0.46"
               length="4.5" minGap="2.5" maxSpeed="16.0" accel="2.6" decel="4.5" sigma="0.5" tau="1.0">
            {ssm}
        </vType>
        <vType id="car_eu4"  vClass="passenger" emissionClass="HBEFA3/PC_G_EU4" probability="0.28"
               length="4.5" minGap="2.5" maxSpeed="15.5" accel="2.4" decel="4.5" sigma="0.5" tau="1.0">
            {ssm}
        </vType>
        <vType id="car_dsl"  vClass="passenger" emissionClass="HBEFA3/PC_D_EU6" probability="0.14"
               length="4.6" minGap="2.5" maxSpeed="15.5" accel="2.4" decel="4.5" sigma="0.5" tau="1.0">
            {ssm}
        </vType>
        <vType id="van_ldv"  vClass="delivery"  emissionClass="HBEFA3/LDV_D_EU6" probability="0.05"
               length="6.5" minGap="2.8" maxSpeed="14.0" accel="1.8" decel="4.0" sigma="0.5" tau="1.1">
            {ssm}
        </vType>
        <vType id="truck_hdv" vClass="truck"   emissionClass="HBEFA3/HDV_D_EU6" probability="0.07"
               length="12.0" minGap="3.0" maxSpeed="13.0" accel="1.1" decel="3.5" sigma="0.5" tau="1.2">
            {ssm}
        </vType>
    </vTypeDistribution>
</additional>
"""
SSM_PARAMS = """<param key="has.ssm.device" value="true"/>
            <param key="device.ssm.measures" value="TTC DRAC PET BR"/>
            <param key="device.ssm.thresholds" value="3.0 3.0 2.0 0.0"/>
            <param key="device.ssm.range" value="50.0"/>
            <param key="device.ssm.extratime" value="5.0"/>"""


def od_table(growth):
    """Return [(from_edge, to_edge, veh_per_hour)] scaled by `growth`."""
    rows = []
    for dest, share in EB_DEST.items():
        rows.append(('W_J1', dest, V_EB * share * growth))
    for dest, share in WB_DEST.items():
        rows.append(('E_J5', dest, V_WB * share * growth))
    for i in range(1, N_INT + 1):
        for entry, opp in ((f'N{i}_J{i}', f'J{i}_S{i}'), (f'S{i}_J{i}', f'J{i}_N{i}')):
            rows.append((entry, opp, V_CROSS * CROSS_THROUGH * growth))
            rows.append((entry, 'J5_E', V_CROSS * CROSS_TO_EAST * growth))
            rows.append((entry, 'J1_W', V_CROSS * CROSS_TO_WEST * growth))
    # drop degenerate pairs (from == to) that can arise at the corridor ends
    return [(f, t, v) for f, t, v in rows if f != t and v > 0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seed', type=int, required=True)
    ap.add_argument('--growth', type=float, default=1.0,
                    help='demand multiplier vs the opening-year AM peak')
    ap.add_argument('--duration', type=float, default=5400.0,
                    help='seconds of peak-rate demand generated (warm-up + analysis)')
    ap.add_argument('--out', required=True)
    ap.add_argument('--vtypes-out', default=None)
    args = ap.parse_args()

    if args.vtypes_out:
        with open(args.vtypes_out, 'w') as f:
            f.write(VTYPES.format(ssm=SSM_PARAMS))

    rng = random.Random(args.seed)
    trips = []
    for frm, to, vph in od_table(args.growth):
        n = vph * args.duration / 3600.0
        k = int(n) + (1 if rng.random() < (n - int(n)) else 0)
        for _ in range(k):
            trips.append((rng.uniform(0.0, args.duration), frm, to))
    trips.sort()

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, 'w') as f:
        f.write('<routes>\n')
        for j, (t, frm, to) in enumerate(trips):
            f.write(f'    <trip id="v{j}" type="fleet" depart="{t:.2f}" '
                    f'from="{frm}" to="{to}" departLane="best" departSpeed="max"/>\n')
        f.write('</routes>\n')
    print(f'{args.out}: {len(trips)} trips, growth={args.growth:.4f}, '
          f'span={args.duration:.0f}s '
          f'({len(trips)/(args.duration/3600.0):.0f} veh/h)')


if __name__ == '__main__':
    main()
