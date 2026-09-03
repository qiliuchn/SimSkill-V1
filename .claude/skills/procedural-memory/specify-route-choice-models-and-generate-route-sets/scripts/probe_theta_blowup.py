#!/usr/bin/env python3
"""Hypothesis probe for sub-goal 5: does duarouter's DEFAULT auto-estimated logit.theta
blow up (imply extreme, near-deterministic discrimination) as the cost SPREAD across
alternative routes shrinks -- i.e., exactly the situation duaIterate approaches near
convergence, when competing routes' costs become nearly equal by definition of equilibrium?
If so, that is a structural, mechanistic explanation for logit's documented oscillating
near-all-or-nothing non-convergence in braess-paradox-in-sumo.md.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from netbuild import build_independent               # noqa: E402
from duahelpers import write_hand_alt, run_duarouter  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sg1_formulas"))
from run_sg1 import mnl_fit_theta                     # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
outdir = os.path.join(HERE, "work_probe")
os.makedirs(outdir, exist_ok=True)

edges = ["S_in r1 T_out", "S_in r2 T_out"]

# Fix a base cost level (~150s, comparable to Braess-scale link costs) and shrink the
# SPREAD between the two routes progressively, holding the mean fixed.
mean_cost = 150.0
spreads = [40.0, 20.0, 10.0, 4.0, 2.0, 1.0, 0.5, 0.2, 0.1, 0.05, 0.02]
for spread in spreads:
    c1 = mean_cost - spread / 2
    c2 = mean_cost + spread / 2
    L1 = (c1 - 200 / 30 - 200 / 30) * 10
    L2 = (c2 - 200 / 30 - 200 / 30) * 10
    net = build_independent([L1, L2], os.path.join(outdir, f"net_{spread}"), speed=10.0)
    hand = os.path.join(outdir, f"hand_{spread}.rou.alt.xml")
    write_hand_alt(hand, "veh0", [(edges[0], c1, 0.5), (edges[1], c2, 0.5)])
    parsed, _ = run_duarouter(net, hand, os.path.join(outdir, f"out_{spread}"), method="logit")
    routes = parsed["veh0"]
    costs = [r[1] for r in routes]
    probs = [r[2] for r in routes]
    _, theta, _ = mnl_fit_theta(costs, probs)
    print(f"spread={spread:6.2f}s  costs={['%.3f' % c for c in costs]}  "
          f"probs={['%.4f' % p for p in probs]}  auto_theta={theta:.5f}  "
          f"theta*spread={theta*spread:.4f}")
