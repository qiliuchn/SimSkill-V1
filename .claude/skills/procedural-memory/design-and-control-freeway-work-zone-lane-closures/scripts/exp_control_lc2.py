"""Reduced control matrix at TWO lanes closed, so the merge-control decision rule can be
keyed to lanes-closed as well as demand.  Demands are scaled to the lc=2 capacity
(one open lane, measured 1108-1274 pc/h/ln), not reused from the lc=1 matrix."""
import os
import wz_common as W
import batch
import exp_control

DEMANDS = (900, 1200, 1500, 1800, 2100)
SEEDS = (1, 2, 3, 4, 5)

if __name__ == "__main__":
    cs = exp_control.cells(lanes_closed=2, demands=DEMANDS, seeds=SEEDS)
    print(f"{len(cs)} control cells (lanes_closed=2)")
    batch.run_cells(cs, os.path.join(W.OUT, "control", "control_results_lc2.json"))
