"""
CRN demand generator. For a given (bike_level, rt_level, rep) cell, produces ONE
route file (vehicles + persons, individually timed via seeded Poisson process) that
is used UNCHANGED across all network variants for that cell -- true Common Random
Numbers: only the network differs between variant runs of the same cell.

Vehicle/person IDs encode (mode, approach, movement, seq) for downstream SSM
movement-pair classification without needing to re-parse routes.
"""
import sys, random, math

sys.path.insert(0, "/private/tmp/claude-501/-Users-liuqi-Desktop-simskill/07cb182d-88df-492d-b918-d753d888c5e5/scratchpad/bikeint/lib")
import net_lib as nl

DUR = 3600.0

# fixed background demand (veh/h per approach unless noted)
CAR_THROUGH_MAJOR = 400.0   # N, S
CAR_LEFT_MAJOR = 50.0       # N, S
CAR_THROUGH_MINOR = 200.0   # E, W
CAR_RIGHT_MINOR = 50.0
CAR_LEFT_MINOR = 50.0
BIKE_MINOR_BG = 30.0        # small fixed bike background on E,W (not swept)
PED_PER_LEG = 150.0         # ped/h crossing each leg, split both directions


def poisson_arrivals(rate_per_h, duration_s, rng):
    """Return sorted list of arrival times (s) for a Poisson process at rate_per_h veh/h."""
    if rate_per_h <= 0:
        return []
    times = []
    t = 0.0
    rate_per_s = rate_per_h / 3600.0
    while True:
        t += rng.expovariate(rate_per_s)
        if t >= duration_s:
            break
        times.append(t)
    return times


def build_demand(bike_level_total, rt_level_per_approach, seed, out_path, duration=DUR):
    """bike_level_total: total bikes/h on the main (N+S) street, split evenly.
       rt_level_per_approach: right-turn veh/h on EACH of N,S."""
    rng = random.Random(seed)
    events = []  # (time, xml_line)

    def add_car_flow(approach, movement, rate, vtype="car"):
        dest = {"through": nl.opposite(approach), "left": nl.left_of(approach), "right": nl.right_of(approach)}[movement]
        times = poisson_arrivals(rate, duration, rng)
        for i, t in enumerate(times):
            vid = f"car_{approach}_{movement}_{i}"
            events.append((t, f'  <vehicle id="{vid}" type="{vtype}" depart="{t:.2f}" departSpeed="max" departLane="best">'
                              f'<route edges="in_{approach} out_{dest}"/></vehicle>'))

    def add_bike_flow(approach, rate):
        times = poisson_arrivals(rate, duration, rng)
        dest = nl.opposite(approach)
        for i, t in enumerate(times):
            vid = f"bike_{approach}_through_{i}"
            events.append((t, f'  <vehicle id="{vid}" type="bike" depart="{t:.2f}" departSpeed="max" departLane="best">'
                              f'<route edges="in_{approach} out_{dest}"/></vehicle>'))

    def add_ped_flow(leg, rate_each_dir):
        for direction, (frm, to) in enumerate([(f"in_{leg}", f"out_{leg}"), (f"out_{leg}", f"in_{leg}")]):
            times = poisson_arrivals(rate_each_dir, duration, rng)
            for i, t in enumerate(times):
                pid = f"ped_{leg}_{direction}_{i}"
                events.append((t, f'  <person id="{pid}" depart="{t:.2f}"><walk from="{frm}" to="{to}"/></person>'))

    bike_per_major_approach = bike_level_total / 2.0
    for a in ["N", "S"]:
        add_car_flow(a, "through", CAR_THROUGH_MAJOR)
        add_car_flow(a, "left", CAR_LEFT_MAJOR)
        add_car_flow(a, "right", rt_level_per_approach)
        add_bike_flow(a, bike_per_major_approach)
    for a in ["E", "W"]:
        add_car_flow(a, "through", CAR_THROUGH_MINOR)
        add_car_flow(a, "left", CAR_LEFT_MINOR)
        add_car_flow(a, "right", CAR_RIGHT_MINOR)
        add_bike_flow(a, BIKE_MINOR_BG)
    for leg in nl.ARMS:
        add_ped_flow(leg, PED_PER_LEG / 2.0)

    events.sort(key=lambda x: x[0])
    with open(out_path, "w") as f:
        f.write('<routes>\n')
        for t, line in events:
            f.write(line + "\n")
        f.write('</routes>\n')
    return len(events)


if __name__ == "__main__":
    import os
    n = build_demand(200.0, 100.0, seed=12345, out_path="/tmp/demo.rou.xml")
    print("wrote", n, "events")
