#!/usr/bin/env python3
"""
Generate SUMO route files for a bicycle-mode-share sweep on a single-edge
corridor (edge id "E0"). One route file per mode-share LEVEL; the SAME route
file is run against BOTH infrastructure variants (mixed vs dedicated), which
guarantees identical demand + identical vehicle-order/seed across A and B at
each level (only the network permissions differ between the compared runs).

Design decisions:
- Fixed TOTAL number of trips N and a fixed departure schedule (identical
  across all levels), so the only thing that changes across levels is which
  trips are bicycles. This isolates the mode-share effect.
- Bicycle assignment is drawn from a single seeded RNG (seed=42) so the run is
  reproducible; the chosen bike indices are a deterministic function of the seed
  and the fraction.
- vTypes: car (vClass=passenger, maxSpeed 13.9 m/s ~ 50 km/h) and
  bike (vClass=bicycle, maxSpeed 5.5 m/s ~ 20 km/h, small length/width).
- Route is simply "E0" (the whole 2 km corridor) for every trip; SUMO auto-
  selects a legal lane per vClass, so the same route file works on both nets.
"""
import argparse
import random

VTYPES = """    <vType id="car"  vClass="passenger" maxSpeed="13.9" length="4.5"  minGap="2.5" accel="2.6" decel="4.5" sigma="0.5"/>
    <vType id="bike" vClass="bicycle"   maxSpeed="5.5"  length="1.8" width="0.65" minGap="0.5" accel="1.2" decel="3.0" sigma="0.5"/>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--total", type=int, default=200, help="total trips (cars+bikes)")
    ap.add_argument("--headway", type=float, default=5.0, help="seconds between successive departures")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--fraction", type=float, required=True, help="bicycle mode share, e.g. 0.05")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    N = args.total
    # Fixed departure schedule, identical across every level.
    departs = [round(i * args.headway, 1) for i in range(N)]

    # Seeded, deterministic bike assignment.
    rng = random.Random(args.seed)
    n_bikes = int(round(args.fraction * N))
    bike_idx = set(rng.sample(range(N), n_bikes))

    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<routes>", VTYPES, ""]
    for i in range(N):
        vt = "bike" if i in bike_idx else "car"
        lines.append(
            f'    <vehicle id="{vt}_{i}" type="{vt}" depart="{departs[i]:.1f}" '
            f'departLane="first" departSpeed="max"><route edges="E0"/></vehicle>'
        )
    lines.append("</routes>")
    with open(args.out, "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"{args.out}: N={N} total, bikes={n_bikes} ({args.fraction:.0%}), cars={N - n_bikes}, "
          f"last depart={departs[-1]:.1f}s, seed={args.seed}")


if __name__ == "__main__":
    main()
