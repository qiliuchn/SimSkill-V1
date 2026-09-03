"""Demand generation for the work-zone corridor.

CRN discipline (from `quantify-sumo-run-to-run-variability` and the explicit warning in
`choose-time-discretization-and-integration-method`): departures are written as explicit
<vehicle depart="..."> entries, NEVER <flow>, because <flow> re-quantises departure times
whenever --step-length changes, which would destroy CRN across a dt sweep.

Diversion compliance is applied as a NESTED assignment: each vehicle carries a fixed
uniform draw u_i (fixed by the demand seed); it diverts iff u_i < phi.  So raising phi
only ever ADDS diverters and never re-shuffles who they are -- the diversion sweep is
itself a CRN design.
"""
import argparse
import os
import numpy as np

import wz_common as W

# time-varying peak: (begin, end, multiplier on the peak rate)
PROFILE = [(0, 600, 0.60), (600, 3600, 1.00), (3600, 4200, 0.50)]
SIM_END = 4800

ROUTE_MAIN = "fA fB fC fD fE fF fG fH"
ROUTE_DETOUR = "fA rOFF dA dB dC dD rON fH"

VTYPE = (
    '  <vType id="car" vClass="passenger" accel="2.6" decel="4.5" emergencyDecel="9.0"\n'
    '         sigma="0.5" length="5.0" minGap="2.5" maxSpeed="45" tau="1.4"\n'
    '         speedFactor="normc(1.00,0.10,0.75,1.25)" actionStepLength="1.0"\n'
    '         emissionClass="HBEFA3/PC_G_EU4" laneChangeModel="LC2013"\n'
    '         carFollowModel="Krauss"/>\n'
)


def gen(peak_vph, seed, phi=0.0, out=None, sim_end=SIM_END, profile=PROFILE,
        ramp_vph=0.0):
    """Write a route file.  peak_vph = mainline peak insertion rate (veh/h)."""
    rng = np.random.default_rng(seed)
    deps = []
    for b, e, m in profile:
        rate = peak_vph * m / 3600.0
        if rate <= 0:
            continue
        t = float(b)
        while True:
            t += rng.exponential(1.0 / rate)
            if t >= e:
                break
            deps.append(t)
    deps.sort()
    # per-vehicle nested compliance draw, fixed by the demand seed
    u = rng.random(len(deps))

    lines = ['<routes>', VTYPE,
             f'  <route id="main" edges="{ROUTE_MAIN}"/>',
             f'  <route id="detour" edges="{ROUTE_DETOUR}"/>']
    for i, (t, ui) in enumerate(zip(deps, u)):
        r = "detour" if ui < phi else "main"
        lines.append(f'  <vehicle id="v{i}" type="car" route="{r}" depart="{t:.2f}" '
                     f'departLane="free" departSpeed="max"/>')
    lines.append('</routes>')
    if out is None:
        out = os.path.join(W.RUNS, f"dem_q{peak_vph}_s{seed}_phi{int(phi*100)}.rou.xml")
    with open(out, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return out, len(deps)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--peak", type=float, required=True)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--phi", type=float, default=0.0)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    f, n = gen(a.peak, a.seed, a.phi, a.out)
    print(f, n)
