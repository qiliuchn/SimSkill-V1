"""H2 / H3: the five control arms (+ a negative control) on CRN demand and seeds.

arms
  donothing  default merge at the taper           (geom net, N4 priority)
  early      static EARLY merge                    (geom net, N4 priority, closing lane
                                                    prohibited from the START of the
                                                    advance-warning area)
  late       static LATE merge / zipper at taper   (geom net, N4 zipper + strategic
                                                    lane-change suppression upstream)
  dynamic    DYNAMIC LATE MERGE                     (geom net, N4 zipper; EARLY<->LATE on
                                                    smoothed upstream occupancy with
                                                    two-sided hysteresis + dwell time)
  vsl        upstream speed harmonisation          (geom net, N4 priority)
  negctrl    dynamic controller plumbing, actuation clamped off -- MUST reproduce
             `donothing` (catches controller-plumbing side effects)

CRN: for a given (peak, seed) every arm uses the identical route file and the identical
sumo --seed.  Differences are paired seed-wise.
"""
import os

import wz_common as W
import batch

OUTD = os.path.join(W.OUT, "control")
os.makedirs(OUTD, exist_ok=True)

DEMANDS = (2400, 2800, 3200, 3600, 4000, 4400)
SEEDS = (1, 2, 3, 4, 5)
ARMS = {
    "donothing": dict(merge="priority"),
    "early":     dict(merge="priority"),
    "late":      dict(merge="zipper"),
    "dynamic":   dict(merge="zipper"),
    "vsl":       dict(merge="priority"),
    "negctrl":   dict(merge="priority"),
}


def cells(lanes_closed=1, demands=DEMANDS, seeds=SEEDS, arms=None, ssm=False):
    arms = arms or ARMS
    cs = []
    for q in demands:
        for sd in seeds:
            for arm, spec in arms.items():
                cs.append(dict(label=f"lc{lanes_closed}_{arm}_q{q}_s{sd}",
                               outroot=OUTD, arm=arm, rep="geom",
                               merge=spec["merge"], peak=q, seed=sd,
                               demand_seed=300 + sd,
                               params=dict(lanes_closed=lanes_closed),
                               ssm=ssm, tagname=arm))
    return cs


if __name__ == "__main__":
    import sys
    lc = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    cs = cells(lanes_closed=lc)
    print(f"{len(cs)} control cells (lanes_closed={lc})")
    batch.run_cells(cs, os.path.join(OUTD, f"control_results_lc{lc}.json"))
