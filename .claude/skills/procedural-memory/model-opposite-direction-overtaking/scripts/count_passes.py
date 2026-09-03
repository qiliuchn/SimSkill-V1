#!/usr/bin/env python3
"""Rigorous completed-overtake counter.

A COMPLETED OVERTAKE = a primary fast car goes from BEHIND a specific truck to
AHEAD of that truck (in corridor distance), i.e. it actually passed its slow
leader. On this network (one lane per direction, NO passing lane) passing a
truck is only physically possible via the oncoming lane B_A_0, so each such
(car, truck) pass event is a completed opposite-direction overtake. We ALSO
require the car to have occupied the opposing lane B_A_0 at some point, as an
explicit, independent confirmation that the oncoming lane was used.

Corridor distance for W->E vehicles = x coordinate (corridor is along +x).
Only forward-direction lanes (W_A_0, A_B_0, B_E_0, opp lane B_A_0 during a pass)
are considered; both cars and trucks travel W->E on these.
"""
import sys
import xml.etree.ElementTree as ET

FORWARD_LANES = {"W_A_0", "A_B_0", "B_E_0", "B_A_0"}  # lanes a W->E vehicle occupies
OPP_LANE = "B_A_0"


def count(path):
    # stream FCD, per timestep gather forward-vehicle x positions
    # track per (car,truck) relative order transitions
    behind = {}          # (car,truck) -> True if car currently behind truck
    passes = set()       # (car,truck) that completed a pass (behind -> ahead)
    car_used_opp = set()

    cur_t = None
    trucks = {}  # id -> x   (this timestep)
    cars = {}    # id -> x

    def flush():
        for cid, cx in cars.items():
            for tid, tx in trucks.items():
                key = (cid, tid)
                car_ahead = cx > tx
                if key in behind:
                    if behind[key] and car_ahead:
                        # transitioned behind -> ahead => overtook this truck
                        passes.add(key)
                        behind[key] = False
                    elif not car_ahead:
                        behind[key] = True
                else:
                    behind[key] = (not car_ahead)

    for ev, el in ET.iterparse(path, events=("start", "end")):
        if ev == "start" and el.tag == "timestep":
            cur_t = el.get("time")
            trucks = {}
            cars = {}
        elif ev == "end" and el.tag == "vehicle":
            vid = el.get("id")
            lane = el.get("lane")
            if lane not in FORWARD_LANES:
                el.clear(); continue
            x = float(el.get("x"))
            if vid.startswith("truck"):
                trucks[vid] = x
            elif vid.startswith("car"):
                cars[vid] = x
                if lane == OPP_LANE:
                    car_used_opp.add(vid)
            el.clear()
        elif ev == "end" and el.tag == "timestep":
            flush()
            el.clear()

    # completed overtakes: pass events whose car also used the oncoming lane
    confirmed = [k for k in passes if k[0] in car_used_opp]
    return len(passes), len(confirmed), len(car_used_opp)


if __name__ == "__main__":
    for rate in [0, 200, 400, 800]:
        p = f"outputs/fcd_{rate}.xml"
        try:
            total, conf, opp = count(p)
        except FileNotFoundError:
            print(f"rate {rate}: (no fcd)"); continue
        print(f"rate {rate:4d}: truck-pass events={total:3d}  "
              f"confirmed-via-opp-lane={conf:3d}  cars-that-used-opp-lane={opp:3d}")
