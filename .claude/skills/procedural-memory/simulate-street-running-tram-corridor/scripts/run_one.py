"""Build + run exactly one (ArmCfg, seed) scenario, return metrics.

Dispatch: arms without priority (V0, C, B) run via plain `sumo` command line
(fast, no TraCI needed -- dwell is native/endogenous via boardingDuration,
per design-bus-stop-placement-type-and-spacing). Arms WITH priority (BP, CP)
run via tram_tsp.py's TraCI controller (adapted implement-transit-signal-
priority).
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import corridor as C
import metrics as M
import tram_tsp

SUMO_HOME = os.environ.get(
    "SUMO_HOME",
    "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo")
SUMO_BIN = os.path.join(SUMO_HOME, "bin", "sumo")


def run_cli(net, routes, add_files, outdir, seed, end):
    os.makedirs(outdir, exist_ok=True)
    cmd = [SUMO_BIN, "-n", net, "-r", ",".join(routes)]
    if add_files:
        cmd += ["-a", ",".join(add_files)]
    cmd += ["--tripinfo-output", os.path.join(outdir, "tripinfo.xml"),
            "--stop-output", os.path.join(outdir, "stopout.xml"),
            "--lanechange-output", os.path.join(outdir, "lcout.xml"),
            "--duration-log.statistics", "true", "--no-step-log", "true",
            "--time-to-teleport", "300", "--seed", str(seed), "-e", str(end)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r


def run_scenario(base_info, cfg: C.ArmCfg, outdir, seed, with_blockage=False,
                  block_kwargs=None):
    """Build the scenario then run it (CLI or TSP-TraCI). Returns a dict of
    file paths + parsed metrics."""
    sc = C.build_scenario(base_info, cfg, outdir, seed, with_blockage=False)
    net = sc["net"]
    routes = [sc["cars"]]
    add_files = []
    if sc["stops_add"]:
        add_files.append(sc["stops_add"])
    if cfg.has_tram():
        routes += [sc["trams"], sc["persons"]]

    if with_blockage:
        block_path, block_info = C.build_blockage(cfg, base_info, outdir, **(block_kwargs or {}))
        routes.append(block_path)
        sc["block_info"] = block_info

    if cfg.has_priority():
        cyc = sc["plan"]["J1"]["cycle"]
        res = tram_tsp.run_tram_tsp(net, routes, add_files, outdir, seed, int(cfg.sim_end),
                                     cycle_length=cyc)
        tripinfo = res["--tripinfo-output"]
        stopout = res["--stop-output"]
        sc["tsp_grants"] = res["total_grants"]
        sc["tsp_diag"] = res["diag"]
    else:
        r = run_cli(net, routes, add_files, outdir, seed, int(cfg.sim_end))
        tripinfo = os.path.join(outdir, "tripinfo.xml")
        stopout = os.path.join(outdir, "stopout.xml")
        sc["stderr"] = r.stderr
        sc["returncode"] = r.returncode

    # EB travels stop idx 0->4 (idx4 = last/terminal). WB travels the SAME
    # x-positions in reverse (idx4->0), so WB's terminal (last stop reached)
    # is idx 0, NOT idx 4 -- verified: using idx4 for WB gave a suspiciously
    # near-zero headway CV because that stop is the FIRST one WB reaches
    # (right after departure, before any corridor-accumulated irregularity).
    terminal_eb = "TS_EB_4" if cfg.has_tram() else None
    terminal_wb = "TS_WB_0" if cfg.has_tram() else None
    m = M.summarize_run(tripinfo, stopout if cfg.has_tram() else None,
                         terminal_eb=terminal_eb, terminal_wb=terminal_wb)
    sc["metrics"] = m
    sc["tripinfo_path"] = tripinfo
    sc["stopout_path"] = stopout
    return sc
