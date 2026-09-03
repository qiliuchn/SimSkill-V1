"""
Tram Signal Priority runner -- adapts the implement-transit-signal-priority
skill's SignalTSP controller (offset-recovery, current-phase-duration-only
perturbation, conditional grant limit) to vClass="tram" rather than "bus".
The controller class itself (SignalTSP, collect_requests) is imported
UNCHANGED from the skill's own script -- only the driving `run()` loop is
rewritten here to handle this study's multi-route-file scenarios (cars +
trams + persons [+ an optional mid-block blockage file]) and to apply
priority across all 6 corridor signals (a tram serves the whole corridor,
unlike a single-route bus study).
"""
import json
import os
import sys

SKILL_DIR = "/Users/liuqi/Desktop/simskill/.claude/skills/procedural-memory/implement-transit-signal-priority/scripts"
sys.path.append(SKILL_DIR)
from tsp_controller import SignalTSP, collect_requests  # noqa: E402  (reused unchanged)

SUMO_HOME = os.environ.get(
    "SUMO_HOME",
    "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo")
sys.path.append(os.path.join(SUMO_HOME, "tools"))

DEFAULT_PARAMS = dict(min_green=8.0, max_green=44.0, ext_threshold=8.0,
                       clear_buffer=2.0, grant_limit=1, recovery_max=15.0,
                       agg_min_green=3.0, agg_max_green=55.0)


def run_tram_tsp(net, route_files, add_files, outdir, seed, end,
                  mode="conditional", detection_range=150.0,
                  cycle_length=70.0, params=None, use_libsumo=False,
                  extra_outputs=None):
    os.makedirs(outdir, exist_ok=True)
    params = dict(DEFAULT_PARAMS, **(params or {}))
    if use_libsumo:
        import libsumo as traci   # not available in this SUMO install; kept for portability
    else:
        import traci

    outputs = dict(
        **{
            "--tripinfo-output": os.path.join(outdir, "tripinfo.xml"),
            "--summary-output": os.path.join(outdir, "summary.xml"),
            "--stop-output": os.path.join(outdir, "stopout.xml"),
            "--lanechange-output": os.path.join(outdir, "lcout.xml"),
        }
    )
    if extra_outputs:
        outputs.update(extra_outputs)

    cmd = ["sumo", "-n", net, "-r", ",".join(route_files)]
    if add_files:
        cmd += ["-a", ",".join(add_files)]
    for k, v in outputs.items():
        cmd += [k, v]
    cmd += ["--duration-log.statistics", "true", "--no-step-log", "true",
            "--time-to-teleport", "300", "--seed", str(seed), "-e", str(end)]

    traci.start(cmd)
    log = []
    try:
        controlled = list(traci.trafficlight.getIDList())
        sigs = {t: SignalTSP(traci, t, mode, cycle_length, params, log) for t in controlled}
        while traci.simulation.getMinExpectedNumber() > 0:
            traci.simulationStep()
            now = traci.simulation.getTime()
            reqs = collect_requests(traci, controlled, detection_range, "tram")
            for t, sig in sigs.items():
                sig.step(now, reqs[t])
        grants = {t: sigs[t].total_grants for t in sigs}
        diag = {t: {"extensions": sigs[t].ext_count, "truncations": sigs[t].trunc_count,
                    "blocked_by_limit": sigs[t].blocked_by_limit,
                    "final_debt": round(sigs[t].debt, 2)} for t in sigs}
    finally:
        traci.close()

    grants_path = os.path.join(outdir, "grants_log.json")
    with open(grants_path, "w") as f:
        json.dump({"mode": mode, "grants_per_signal": grants,
                   "total_grants": sum(grants.values()), "diagnostics": diag}, f, indent=2)
    return dict(outdir=outdir, grants=grants, total_grants=sum(grants.values()),
                diag=diag, **outputs)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", required=True)
    ap.add_argument("--routes", required=True, help="comma-separated route files")
    ap.add_argument("--add", default="")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--end", type=int, default=5000)
    ap.add_argument("--cycle-length", type=float, default=70.0)
    ap.add_argument("--mode", default="conditional")
    args = ap.parse_args()
    r = run_tram_tsp(args.net, args.routes.split(","),
                      args.add.split(",") if args.add else [],
                      args.outdir, args.seed, args.end,
                      mode=args.mode, cycle_length=args.cycle_length)
    print(json.dumps({"grants": r["grants"], "total_grants": r["total_grants"]}, indent=2))
