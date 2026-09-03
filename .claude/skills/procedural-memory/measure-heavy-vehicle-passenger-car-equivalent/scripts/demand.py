"""Explicit-vehicle demand generation with an EXACT heavy-vehicle share.

Why explicit <vehicle> entries instead of <flow>+<vTypeDistribution>:
  * the realised heavy-vehicle fraction is exact, not merely expected;
  * the vehicle id encodes its class (`..._c` / `..._t`), so a stop-line
    instantInductionLoop record can be attributed to car vs. heavy vehicle
    without needing the detector to emit a type attribute;
  * TOTAL vehicle demand (veh/h) is held constant across every truck-share arm
    by construction -- only the composition changes;
  * the replication seed drives ONLY the heavy-vehicle placement in the arrival
    sequence, which is exactly the variance source the CIs are meant to describe.
Common Random Numbers: for a given seed, the arrival TIMES are identical in
every arm, and the heavy-vehicle positions are drawn from the same shuffled
permutation, so the p=5% arm's trucks are a subset of the p=10% arm's.
"""
import random


def compose(n, p, seed):
    """-> list of 'c'/'t' of length n with EXACTLY round(p*n) heavy vehicles.

    Nested/CRN construction: one seeded permutation of positions per (n, seed);
    the first round(p*n) entries of that permutation become heavy vehicles.  So
    increasing p only ADDS heavy vehicles, never rearranges existing ones.
    """
    rng = random.Random(seed)
    order = list(range(n))
    rng.shuffle(order)
    k = int(round(p * n))
    heavy = set(order[:k])
    return ["t" if i in heavy else "c" for i in range(n)], k


def write_signal_routes(path, approaches, veh_per_hour, t_end, p, seed,
                        car_type, hv_type):
    """Uniform headway arrivals per approach, departSpeed=max (departSpeed=0
    silently caps insertion at ~1500 veh/h/lane and prevents real spillback)."""
    hw = 3600.0 / veh_per_hour
    n = int(t_end / hw)
    lines = []
    total_t = 0
    for ai, app in enumerate(approaches):
        cls, k = compose(n, p, seed * 1000 + ai)
        total_t += k
        for i in range(n):
            lines.append((i * hw, '  <vehicle id="%s_%05d_%s" type="%s" route="r_%s" '
                                  'depart="%.2f" departLane="0" departSpeed="max" '
                                  'departPos="base"/>\n'
                          % (app, i, cls[i], car_type if cls[i] == "c" else hv_type,
                             app, i * hw)))
    lines.sort(key=lambda x: x[0])
    with open(path, "a") as f:
        for _, s in lines:
            f.write(s)
    return n * len(approaches), total_t


def write_freeway_routes(path, veh_per_hour, t_end, p, seed, car_type, hv_type,
                         n_lanes):
    """Uniform arrivals distributed round-robin over the 3 upstream lanes."""
    hw = 3600.0 / veh_per_hour
    n = int(t_end / hw)
    cls, k = compose(n, p, seed)
    with open(path, "a") as f:
        for i in range(n):
            f.write('  <vehicle id="v%05d_%s" type="%s" route="r0" depart="%.3f" '
                    'departLane="%d" departSpeed="max" departPos="base"/>\n'
                    % (i, cls[i], car_type if cls[i] == "c" else hv_type,
                       i * hw, i % n_lanes))
    return n, k
