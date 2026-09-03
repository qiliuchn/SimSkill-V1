#!/usr/bin/env python3
"""Generate a VARIANT-INDEPENDENT abstract OD file (CSV).

Tokens are physical places, not edge IDs, so exactly the same demand realisation
can be resolved onto each network variant:

  BND:<label>      one of the 20 perimeter access stubs (W0..N4)
  SEG:<kind>_<a>_<b>   a physical street segment ("block face"), e.g. SEG:EW_1_2
                       -- present in every variant, but reachable from both
                       directions only in the two-way net

Demand mix (default): 50 % through trips (perimeter -> perimeter) and 50 %
local-access trips (perimeter <-> interior block face).  The split matters: the
one-way circuity penalty lives almost entirely in the local-access half, because
Manhattan path length is invariant under an alternating one-way pattern for
trips that merely cross the grid.
"""
import argparse
import random

ENTRIES = ["W0", "W2", "W4", "E1", "E3", "S0", "S2", "S4", "N1", "N3"]
EXITS = ["W1", "W3", "E0", "E2", "E4", "S1", "S3", "N0", "N2", "N4"]
N = 5

SEGMENTS = ([("EW", j, i) for j in range(N) for i in range(N - 1)] +
            [("NS", i, j) for i in range(N) for j in range(N - 1)])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--veh-per-hour", type=float, required=True)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--duration", type=float, default=3600.0)
    p.add_argument("--through-share", type=float, default=0.5)
    p.add_argument("--arterial-vph", type=float, default=0.0,
                   help="extra corridor demand, per direction, on the test "
                        "arterial pair (row2 EB via W2->E2, row3 WB via E3->W3)")
    a = p.parse_args()

    rng = random.Random(a.seed)
    through = [(o, d) for o in ENTRIES for d in EXITS if o[0] != d[0]]
    n = int(round(a.veh_per_hour * a.duration / 3600.0))

    rows = []
    for k in range(n):
        t = rng.uniform(0.0, a.duration)
        u = rng.random()
        if u < a.through_share:                       # perimeter -> perimeter
            o, d = rng.choice(through)
            rows.append((t, "BND:" + o, "BND:" + d, "through"))
        elif u < a.through_share + (1 - a.through_share) / 2:   # inbound local
            o = rng.choice(ENTRIES)
            s = rng.choice(SEGMENTS)
            rows.append((t, "BND:" + o, "SEG:%s_%d_%d" % s, "local_in"))
        else:                                          # outbound local
            s = rng.choice(SEGMENTS)
            d = rng.choice(EXITS)
            rows.append((t, "SEG:%s_%d_%d" % s, "BND:" + d, "local_out"))

    # corridor platoon demand on the test arterial pair -- identical OD tokens
    # in every variant (W2->E2 runs row 2 eastbound, E3->W3 runs row 3 westbound)
    na = int(round(a.arterial_vph * a.duration / 3600.0))
    for k in range(na):
        rows.append((rng.uniform(0.0, a.duration), "BND:W2", "BND:E2", "art_EB"))
        rows.append((rng.uniform(0.0, a.duration), "BND:E3", "BND:W3", "art_WB"))
    rows.sort()

    with open(a.out, "w") as f:
        f.write("id,depart,origin,dest,kind\n")
        for k, (t, o, d, kd) in enumerate(rows):
            f.write("v%d,%.2f,%s,%s,%s\n" % (k, t, o, d, kd))
    print("%s: %d trips (%.0f veh/h, seed=%d, through_share=%.2f)"
          % (a.out, n, a.veh_per_hour, a.seed, a.through_share))


if __name__ == "__main__":
    main()
