#!/usr/bin/env python3
"""Analyze the opposite-direction overtaking sweep.

Per run:
  - COMPLETED OVERTAKES: from FCD, count maneuvers where a primary fast car
    occupies the opposing lane B_A_0 and then returns to a primary lane
    (A_B_0 / B_E_0). Cross-checked that the car passes >=1 truck.
  - FAST-CAR delay: from tripinfo, mean travel time & total/mean time loss over
    type=="car" vehicles.
  - HEAD-ON SAFETY: from SSM, count of ONCOMING conflicts (encounter type 20),
    the minimum oncoming TTC, plus actual frontal collisions on opposing lanes.
"""
import os
import sys
import glob
import xml.etree.ElementTree as ET
from count_passes import count as count_passes

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "outputs")
ANA = os.path.join(ROOT, "analysis")
RATES = [0, 200, 400, 800]

PRIMARY_LANES = {"A_B_0", "B_E_0", "W_A_0"}   # forward lanes W->E
OPP_LANE = "B_A_0"                            # the oncoming lane used to overtake
ONCOMING_TYPE = "20"


def overtakes_from_fcd(path):
    """Return (completed_overtakes, distinct_cars_using_opp_lane, leader_pass_ok).
    Streams FCD; builds per-car lane timeline + truck positions per timestep."""
    car_lane_seq = {}      # car id -> list of (t, lane, x)
    # track completed maneuvers incrementally to bound memory
    car_state = {}         # car id -> current 'phase': 'primary'/'opp', last lane
    completed = 0
    cars_on_opp = set()
    car_maneuver_open = {}  # car -> True if currently on opp lane having come from primary

    # We also want leader-pass cross check: record, per car, min and max x while
    # doing an opp maneuver, and truck x at those times. Simpler robust proxy:
    # a completed opp-lane maneuver IS the overtake (car cannot be on the oncoming
    # lane except to pass). We still tally distinct cars.
    for ev, el in ET.iterparse(path, events=("end",)):
        if el.tag != "vehicle":
            continue
        vid = el.get("id")
        if vid is None or not vid.startswith("car"):
            el.clear()
            continue
        lane = el.get("lane")
        prev = car_state.get(vid)
        if lane == OPP_LANE:
            cars_on_opp.add(vid)
            if prev != "opp":
                # entered opp lane
                car_maneuver_open[vid] = True
            car_state[vid] = "opp"
        elif lane in PRIMARY_LANES:
            if prev == "opp" and car_maneuver_open.get(vid):
                # returned to a forward lane after being on the oncoming lane => completed
                completed += 1
                car_maneuver_open[vid] = False
            car_state[vid] = "primary"
        # ignore internal/junction lanes (keep state)
        el.clear()
    return completed, len(cars_on_opp)


def fastcar_metrics(path):
    durations = []
    timelosses = []
    n_truck = 0
    for ev, el in ET.iterparse(path, events=("end",)):
        if el.tag != "tripinfo":
            continue
        vtype = el.get("vType")
        if vtype == "car":
            durations.append(float(el.get("duration")))
            timelosses.append(float(el.get("timeLoss")))
        elif vtype == "truck":
            n_truck += 1
        el.clear()
    n = len(durations)
    return {
        "n_fastcars": n,
        "mean_traveltime_s": sum(durations) / n if n else float("nan"),
        "mean_timeloss_s": sum(timelosses) / n if n else float("nan"),
        "total_timeloss_s": sum(timelosses),
        "n_trucks_completed": n_truck,
    }


def ssm_metrics(path):
    oncoming_conflicts = 0
    oncoming_ttcs = []
    all_min_ttc = []
    collisions = 0
    for ev, el in ET.iterparse(path, events=("end",)):
        if el.tag == "minTTC":
            v = el.get("value")
            ty = el.get("type")
            if v not in ("NA", None):
                fv = float(v)
                all_min_ttc.append(fv)
                if ty == ONCOMING_TYPE:
                    oncoming_conflicts += 1
                    oncoming_ttcs.append(fv)
            elif ty == ONCOMING_TYPE:
                oncoming_conflicts += 1
        el.clear()
    return {
        "oncoming_conflicts": oncoming_conflicts,
        "min_oncoming_ttc_s": min(oncoming_ttcs) if oncoming_ttcs else None,
        "min_ttc_overall_s": min(all_min_ttc) if all_min_ttc else None,
    }


def headon_collisions(rate):
    """Count genuine head-on (frontal) collisions on the opposing lanes from the
    collision-output XML: collider must be a primary 'car', victim an 'opp_car'."""
    p = os.path.join(OUT, f"collisions_{rate}.xml")
    if not os.path.exists(p):
        return None
    n = 0
    for ev, el in ET.iterparse(p, events=("end",)):
        if el.tag == "collision":
            if (el.get("type") == "frontal"
                    and el.get("lane") in ("B_A_0", "A_W_0")
                    and el.get("colliderType") == "car"
                    and el.get("victimType") == "opp_car"):
                n += 1
        el.clear()
    return n


def main():
    rows = []
    for rate in RATES:
        fcd = os.path.join(OUT, f"fcd_{rate}.xml")
        trip = os.path.join(OUT, f"tripinfo_{rate}.xml")
        ssm = os.path.join(OUT, f"ssm_{rate}.xml")
        truck_passes, confirmed_overtakes, cars_opp = count_passes(fcd)
        fm = fastcar_metrics(trip)
        sm = ssm_metrics(ssm)
        coll = headon_collisions(rate)
        rows.append(dict(rate=rate, completed_overtakes=confirmed_overtakes,
                         truck_pass_events=truck_passes,
                         cars_using_opp_lane=cars_opp, **fm, **sm,
                         headon_collisions=coll))

    # write CSV + markdown
    os.makedirs(ANA, exist_ok=True)
    cols = ["rate", "completed_overtakes", "truck_pass_events",
            "cars_using_opp_lane", "n_fastcars",
            "mean_traveltime_s", "mean_timeloss_s", "total_timeloss_s",
            "oncoming_conflicts", "min_oncoming_ttc_s", "min_ttc_overall_s",
            "headon_collisions"]
    csvp = os.path.join(ANA, "summary_table.csv")
    with open(csvp, "w") as f:
        f.write(",".join(cols) + "\n")
        for r in rows:
            f.write(",".join(str(r.get(c)) for c in cols) + "\n")

    # pretty print
    hdr = ["oncoming(veh/h)", "overtakes", "cars_via_opp", "fastcar_TT(s)",
           "fastcar_timeloss(s)", "total_timeloss(s)", "oncoming_conflicts",
           "minTTC_oncoming(s)", "headon_collisions"]
    print("\n" + " | ".join(hdr))
    for r in rows:
        print(" | ".join([
            f"{r['rate']}", f"{r['completed_overtakes']}", f"{r['cars_using_opp_lane']}",
            f"{r['mean_traveltime_s']:.1f}", f"{r['mean_timeloss_s']:.1f}",
            f"{r['total_timeloss_s']:.0f}", f"{r['oncoming_conflicts']}",
            f"{r['min_oncoming_ttc_s']}", f"{r['headon_collisions']}"]))
    print(f"\nwrote {csvp}")
    return rows


if __name__ == "__main__":
    main()
