"""Build route files (one per demand level) with stochastic (exponential-headway) flows."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import *

os.makedirs(DEMAND_DIR, exist_ok=True)

MAIN_ROUTE = "src " + " ".join(f"m{k:02d}" for k in range(N_SEG)) + " snk"
RAMP_ROUTE = "ramp " + " ".join(f"m{k:02d}" for k in range(RAMP_MERGE_SEG, N_SEG)) + " snk"


def write(level, main_vph, ramp_vph, end=SIM_END):
    p_main = main_vph / 3600.0
    p_ramp = ramp_vph / 3600.0
    x = ['<routes>']
    # speedFactor dispersion is REQUIRED for the sumo --seed to actually move outcomes
    # (see quantify-sumo-run-to-run-variability: sigma/speedDev off => seed has zero effect)
    x.append('  <vType id="car" vClass="passenger" accel="2.6" decel="4.5" sigma="0.5" '
             'length="5.0" minGap="2.5" maxSpeed="40" speedFactor="normc(1.0,0.10,0.7,1.3)" '
             'lcSpeedGain="1.0" lcCooperative="1.0" carFollowModel="Krauss"/>')
    x.append(f'  <route id="rmain" edges="{MAIN_ROUTE}"/>')
    x.append(f'  <route id="rramp" edges="{RAMP_ROUTE}"/>')
    x.append(f'  <flow id="fmain" type="car" route="rmain" begin="0" end="{end}" '
             f'period="exp({p_main:.6f})" departLane="best" departSpeed="max"/>')
    x.append(f'  <flow id="framp" type="car" route="rramp" begin="0" end="{end}" '
             f'period="exp({p_ramp:.6f})" departLane="free" departSpeed="max"/>')
    x.append('</routes>')
    path = os.path.join(DEMAND_DIR, f"demand_{level}.rou.xml")
    with open(path, "w") as f:
        f.write("\n".join(x) + "\n")
    print("wrote", path, main_vph, "+", ramp_vph, "veh/h")
    return path


if __name__ == "__main__":
    for lvl, (m, r) in DEMAND_LEVELS.items():
        write(lvl, m, r)
    # extra levels used only by the capacity sweep
    for vph in (3000, 3600, 4200, 4500, 5100, 5400, 6000):
        write(f"cap{vph}", vph, int(vph * 0.14))
