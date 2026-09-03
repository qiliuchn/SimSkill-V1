#!/usr/bin/env python3
"""
Generate a time-varying trip file (ramp-up / sustained peak / ramp-down) for the
signalized grid, deliberately concentrating demand on the CORE so that core
accumulation grows past its critical value during the peak.

Trip mix (all origins are the network's dead-end entry stubs):
  * "core"      -> destination is a CORE edge          (trip ends inside the core)
  * "through"   -> destination is an exit stub on the OPPOSITE side
  * "outside"   -> destination is an exit stub on the SAME or ADJACENT side

The realised class of each vehicle is re-derived AFTER routing from the actual
route edges (see classify_trips.py), so these labels are only a generator hint.

Departure times are drawn from a piecewise-linear rate profile lambda(t).
Everything is driven by one fixed RNG seed so the demand is byte-identical
across every run of the experiment.
"""
import argparse
import json
import random


OPPOSITE = {"left": "right", "right": "left", "top": "bottom", "bottom": "top"}


def rate_profile(t, peak_vph, t_ramp_up, t_peak_end, t_end, base_frac=0.20):
    """Piecewise-linear veh/h loading profile."""
    if t < 0:
        return 0.0
    if t < t_ramp_up:
        f = base_frac + (1.0 - base_frac) * (t / t_ramp_up)
    elif t < t_peak_end:
        f = 1.0
    elif t < t_end:
        f = 1.0 - (1.0 - base_frac) * ((t - t_peak_end) / (t_end - t_peak_end))
    else:
        f = 0.0
    return peak_vph * f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--core-gate", required=True)
    ap.add_argument("--out-trips", required=True)
    ap.add_argument("--out-meta", required=True)
    ap.add_argument("--peak-vph", type=float, default=5400.0)
    ap.add_argument("--t-ramp-up", type=float, default=600.0)
    ap.add_argument("--t-peak-end", type=float, default=2400.0)
    ap.add_argument("--t-end", type=float, default=3000.0)
    ap.add_argument("--p-core", type=float, default=0.45)
    ap.add_argument("--p-through", type=float, default=0.35)
    ap.add_argument("--seed", type=int, default=20260731)
    args = ap.parse_args()

    cg = json.load(open(args.core_gate))
    entry_edges = cg["entry_edges"]
    exit_edges = cg["exit_edges"]
    entry_side = cg["entry_side"]
    exit_side = cg["exit_side"]
    core_edges = cg["core_edges"]

    exits_by_side = {}
    for e in exit_edges:
        exits_by_side.setdefault(exit_side[e], []).append(e)
    for v in exits_by_side.values():
        v.sort()

    rng = random.Random(args.seed)

    # --- sample departure times from the rate profile (thinning-free, 1 s bins)
    departs = []
    t = 0.0
    dt = 1.0
    while t < args.t_end:
        lam = rate_profile(t, args.peak_vph, args.t_ramp_up,
                           args.t_peak_end, args.t_end) / 3600.0  # veh/s
        # expected number in this 1 s bin
        k = lam * dt
        # Poisson-ish: integer part + Bernoulli remainder
        n = int(k) + (1 if rng.random() < (k - int(k)) else 0)
        for _ in range(n):
            departs.append(t + rng.random() * dt)
        t += dt
    departs.sort()

    trips = []
    counts = {"core": 0, "through": 0, "outside": 0}
    for i, dep in enumerate(departs):
        o = rng.choice(entry_edges)
        oside = entry_side[o]
        u = rng.random()
        if u < args.p_core:
            kind = "core"
            d = rng.choice(core_edges)
        elif u < args.p_core + args.p_through:
            kind = "through"
            d = rng.choice(exits_by_side[OPPOSITE[oside]])
        else:
            kind = "outside"
            cand_sides = [s for s in exits_by_side if s != OPPOSITE[oside]]
            s = rng.choice(cand_sides)
            cands = [e for e in exits_by_side[s] if e != o]
            d = rng.choice(cands)
        counts[kind] += 1
        trips.append((f"v{i}", dep, o, d, kind))

    with open(args.out_trips, "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<routes>\n')
        f.write('  <vType id="car" accel="2.6" decel="4.5" sigma="0.5" '
                'length="5.0" minGap="2.5" maxSpeed="13.89" tau="1.0"/>\n')
        for vid, dep, o, d, kind in trips:
            f.write(f'  <trip id="{vid}" type="car" depart="{dep:.2f}" '
                    f'from="{o}" to="{d}"/>\n')
        f.write('</routes>\n')

    meta = {
        "n_trips": len(trips),
        "generator_counts": counts,
        "peak_vph": args.peak_vph,
        "t_ramp_up": args.t_ramp_up,
        "t_peak_end": args.t_peak_end,
        "t_end": args.t_end,
        "seed": args.seed,
        "generator_kind": {vid: kind for vid, _, _, _, kind in trips},
    }
    json.dump(meta, open(args.out_meta, "w"), indent=2)
    print(f"{len(trips)} trips  {counts}")


if __name__ == "__main__":
    main()
