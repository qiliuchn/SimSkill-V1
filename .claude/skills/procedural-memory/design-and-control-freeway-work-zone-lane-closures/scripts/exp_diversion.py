"""H4: the diversion layer.  Sweep the VMS/detour compliance share phi in [0,1] and
report corridor-wide TSTT decomposed across freeway / ramps / detour arterial /
origin-insertion delay.

The compliance assignment is NESTED (gen_demand.py): raising phi only adds diverters,
never re-shuffles them, so the sweep is itself a CRN design on top of the seed CRN.

The hypothesis (mirroring the ramp-metering delay-transfer finding in
[[coordinated-ramp-metering-delay-transfer-and-ramp-storage]]) is that TSTT vs phi is an
inverted U whose minimum sits strictly below phi=1, because the detour's three
fixed-time signals saturate and the delay is merely transferred.
"""
import os

import wz_common as W
import batch

OUTD = os.path.join(W.OUT, "diversion")
os.makedirs(OUTD, exist_ok=True)

PHIS = (0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.60, 0.80, 1.00)
DEMANDS = (3200, 4000)
SEEDS = (1, 2, 3, 4, 5)


def cells(arm="donothing", lanes_closed=1, demands=DEMANDS, phis=PHIS, seeds=SEEDS):
    cs = []
    for q in demands:
        for phi in phis:
            for sd in seeds:
                cs.append(dict(label=f"div_{arm}_q{q}_phi{int(phi*100):03d}_s{sd}",
                               outroot=OUTD, arm=arm, rep="geom", merge="priority",
                               peak=q, seed=sd, phi=phi, demand_seed=400 + sd,
                               params=dict(lanes_closed=lanes_closed),
                               tagname=f"q{q}_phi{phi}"))
    return cs


if __name__ == "__main__":
    cs = cells()
    print(f"{len(cs)} diversion cells")
    batch.run_cells(cs, os.path.join(OUTD, "diversion_results.json"))
