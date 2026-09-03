"""
Run a SUMO simulation entirely from the command line — no TraCI, no
Python-side loop. SUMO runs start-to-finish on its own and writes
whichever output files were requested, then exits.

Usage:
    python run_sumo_cli.py --config config.sumocfg --tripinfo-output tripinfo.xml --summary-output summary.xml
    python run_sumo_cli.py --net-file net.net.xml --route-file routes.rou.xml --duration-log-statistics
    python run_sumo_cli.py --config config.sumocfg --gui
    python run_sumo_cli.py --config config.sumocfg --begin 0 --end 3600 --step-length 0.5
    python run_sumo_cli.py --config config.sumocfg -a tlsAdaptation.add.xml,tlsOffsets.add.xml --tripinfo-output out.xml

Use this instead of run_traci_simulation.py whenever the task is fully
"run this and look at the output files" with no need to read or change
state mid-run. See SKILL.md for when each mode applies.
"""

import argparse
import os
import shutil
import subprocess
import sys


def find_sumo_binary(gui: bool) -> str:
    name = "sumo-gui" if gui else "sumo"

    found = shutil.which(name)
    if found:
        return found

    sumo_home = os.environ.get("SUMO_HOME")
    if sumo_home:
        candidate = os.path.join(sumo_home, "bin", name)
        if os.path.isfile(candidate):
            return candidate

    sys.exit(
        f"Could not locate {name}. Checked $PATH and $SUMO_HOME/bin. "
        "Pass its full path directly or add it to PATH."
    )


def parse_args():
    p = argparse.ArgumentParser(description="Run a SUMO simulation from the command line (no TraCI).")

    conn = p.add_mutually_exclusive_group(required=True)
    conn.add_argument("--config", "-c", help="Path to a .sumocfg")
    conn.add_argument("--net-file", "-n", help="Path to a .net.xml (use with --route-file instead of --config)")

    p.add_argument("--route-file", "-r", help="Path to a .rou.xml (required if using --net-file instead of --config)")
    p.add_argument(
        "--additional-files", "-a",
        help="Additional file(s), comma-separated (e.g. tlLogic overrides from optimize-signals-by-tlscycleadaptation/tlscoordinator)",
    )

    p.add_argument("--gui", action="store_true", help="Use sumo-gui instead of headless sumo")
    p.add_argument("--begin", "-b", type=float, help="Simulation start time (s)")
    p.add_argument("--end", "-e", type=float, help="Simulation end time (s) — respected in this mode, unlike under TraCI")
    p.add_argument("--step-length", type=float, help="Simulation step length (s), default 1")
    p.add_argument("--seed", type=int, help="Random seed")

    # Common output files
    p.add_argument("--tripinfo-output", help="Per-vehicle summary output file")
    p.add_argument("--summary-output", help="Per-timestep aggregate output file")
    p.add_argument("--duration-log-statistics", action="store_true", help="Print aggregate duration/waiting-time statistics to stdout")
    p.add_argument("--fcd-output", help="Floating Car Data output file (position every timestep, can be large)")
    p.add_argument("--netstate-output", help="Full network state dump output file")
    p.add_argument("--queue-output", help="Per-lane queue length output file")
    p.add_argument("--emission-output", help="Per-vehicle emissions output file")

    p.add_argument(
        "--extra",
        action="append",
        default=[],
        help="Extra raw sumo argument(s), can be repeated, e.g. --extra '--no-warnings'",
    )
    p.add_argument("--dry-run", action="store_true", help="Print the command without running it")
    return p.parse_args()


def build_command(sumo_bin: str, args: argparse.Namespace) -> list:
    cmd = [sumo_bin]

    if args.config:
        cmd += ["-c", args.config]
    else:
        if not args.route_file:
            sys.exit("--route-file is required when using --net-file instead of --config")
        cmd += ["-n", args.net_file, "-r", args.route_file]

    if args.additional_files:
        cmd += ["-a", args.additional_files]

    if args.begin is not None:
        cmd += ["-b", str(args.begin)]
    if args.end is not None:
        cmd += ["-e", str(args.end)]
    if args.step_length is not None:
        cmd += ["--step-length", str(args.step_length)]
    if args.seed is not None:
        cmd += ["--seed", str(args.seed)]

    if args.tripinfo_output:
        cmd += ["--tripinfo-output", args.tripinfo_output]
    if args.summary_output:
        cmd += ["--summary-output", args.summary_output]
    if args.duration_log_statistics:
        cmd += ["--duration-log.statistics"]
    if args.fcd_output:
        cmd += ["--fcd-output", args.fcd_output]
    if args.netstate_output:
        cmd += ["--netstate-dump", args.netstate_output]
    if args.queue_output:
        cmd += ["--queue-output", args.queue_output]
    if args.emission_output:
        cmd += ["--emission-output", args.emission_output]

    for extra in args.extra:
        cmd += extra.split()

    return cmd


def main():
    args = parse_args()
    if args.dry_run:
        sumo_bin = "sumo-gui" if args.gui else "sumo"
    else:
        sumo_bin = find_sumo_binary(args.gui)
    cmd = build_command(sumo_bin, args)

    print("Running:", " ".join(cmd))
    if args.dry_run:
        return

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        sys.exit(result.returncode)

    print("Simulation finished.")


if __name__ == "__main__":
    main()
