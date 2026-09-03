"""
Template for running a SUMO simulation step-by-step via TraCI.

Usage:
    python run_traci_simulation.py path/to/config.sumocfg
    python run_traci_simulation.py path/to/config.sumocfg --gui
    python run_traci_simulation.py path/to/config.sumocfg --libsumo --max-steps 3600

Adapt the body of `run()` to whatever the task actually needs — this just
wires up the boilerplate (SUMO_HOME path setup, connecting, the step loop,
and clean shutdown) so it doesn't have to be reinvented each time.
"""

import argparse
import os
import sys


def _ensure_traci_on_path():
    """traci/libsumo live inside SUMO's tools/ dir, not on PyPI as pip packages."""
    if "SUMO_HOME" not in os.environ:
        sys.exit(
            "SUMO_HOME is not set. Set it to your SUMO install directory, "
            "e.g. export SUMO_HOME=/usr/share/sumo"
        )
    tools = os.path.join(os.environ["SUMO_HOME"], "tools")
    if tools not in sys.path:
        sys.path.append(tools)


def parse_args():
    p = argparse.ArgumentParser(description="Run a SUMO simulation via TraCI.")
    p.add_argument("config", help="Path to a .sumocfg file")
    p.add_argument("--gui", action="store_true", help="Use sumo-gui instead of headless sumo")
    p.add_argument(
        "--libsumo",
        action="store_true",
        help="Use libsumo (in-process, faster, headless-only, single instance) instead of traci",
    )
    p.add_argument("--max-steps", type=int, default=None, help="Stop after this many steps regardless of vehicles remaining")
    p.add_argument("--step-length", type=float, default=None, help="Override step length in seconds (else use config default)")
    return p.parse_args()


def run(args):
    _ensure_traci_on_path()

    if args.libsumo:
        if args.gui:
            sys.exit("libsumo has no GUI support; drop --gui or drop --libsumo.")
        import libsumo as traci
    else:
        import traci

    binary = "sumo-gui" if args.gui else "sumo"
    sumo_cmd = [binary, "-c", args.config]
    if args.step_length:
        sumo_cmd += ["--step-length", str(args.step_length)]

    traci.start(sumo_cmd)

    try:
        step = 0
        while traci.simulation.getMinExpectedNumber() > 0:
            if args.max_steps is not None and step >= args.max_steps:
                break

            traci.simulationStep()

            # --- adapt this block to the actual task ---
            for veh_id in traci.vehicle.getIDList():
                speed = traci.vehicle.getSpeed(veh_id)
                # e.g. collect stats, apply a control policy, log to a dataframe, etc.
                _ = speed  # placeholder so linters don't complain

            step += 1
            # --------------------------------------------

        print(f"Finished after {step} steps.")
    finally:
        traci.close()


if __name__ == "__main__":
    run(parse_args())
