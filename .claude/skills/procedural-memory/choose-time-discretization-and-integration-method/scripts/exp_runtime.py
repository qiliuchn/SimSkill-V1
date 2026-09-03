"""Runtime / cost layer.

  R1  wall-clock and real-time factor vs dt on a fixed scenario (is scaling ~1/dt?)
  R2  plain CLI  vs  TraCI stepping (no queries)  vs  TraCI stepping + per-vehicle queries
      vs  libsumo  -- libsumo availability is probed and reported, never silently skipped.
  R3  --threads scaling on the same scenario.
"""
import os
import sys
import time
import shutil
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dtcommon import (NET, RUNS, SUMO_HOME, DTS, run_sumo, BASE_ARGS, cell_args,
                      vtype_xml, DEFAULT_CAR, mean, sd, savejson, summary_totals)
sys.path.insert(0, os.path.join(SUMO_HOME, "tools"))
import traci                                          # noqa
import exp_c_merge as C                               # noqa

BASE = os.path.join(RUNS, "runtime")
os.makedirs(BASE, exist_ok=True)
MERGE = os.path.join(NET, "merge.net.xml")
END = 1800.0
REPS = 3

# ---------------------------------------------------------------- libsumo probe
LIBSUMO = dict(available=False, error=None, path=None)
try:
    import libsumo                                    # noqa
    LIBSUMO.update(available=True, path=getattr(libsumo, "__file__", "?"))
except Exception as e:                                # noqa
    LIBSUMO["error"] = "%s: %s" % (type(e).__name__, e)


def base_cmd(dt, ballistic=False, threads=None, out=None):
    add = os.path.join(BASE, "add.xml")
    if not os.path.exists(add):
        open(add, "w").write("<additional>%s</additional>"
                             % vtype_xml("car", DEFAULT_CAR, asl=None))
    a = ["-n", MERGE, "-r", C.DEMAND, "-a", add,
         "--begin", "0", "--end", str(END),
         "--time-to-teleport", "300", "--max-depart-delay", "900",
         "--collision.action", "warn", "--seed", "1001",
         "--step-length", str(dt)] + BASE_ARGS
    if ballistic:
        a += ["--step-method.ballistic", "true"]
    if threads:
        a += ["--threads", str(threads)]
    if out:
        a += ["--summary-output", out]
    return a


def r1_dt_scaling():
    rows = []
    for dt in DTS:
        for meth in (False, True):
            ws = []
            for _ in range(REPS):
                out = os.path.join(BASE, "s.xml")
                r = run_sumo(base_cmd(dt, ballistic=meth, out=out))
                assert r["rc"] == 0, r["err"][-300:]
                ws.append(r["wall"])
            rows.append(dict(dt=dt, method="ballistic" if meth else "euler",
                             wall=mean(ws), wall_sd=sd(ws), rtf=END / mean(ws),
                             n_steps=int(END / dt)))
            print("  dt=%-5g %-9s wall=%6.2fs (sd %.2f)  RTF=%8.1f  steps=%d"
                  % (dt, rows[-1]["method"], rows[-1]["wall"], rows[-1]["wall_sd"],
                     rows[-1]["rtf"], rows[-1]["n_steps"]))
    return rows


def _traci_run(dt, query):
    label = "rt_%g_%d_%f" % (dt, query, time.time())
    cmd = ["sumo"] + [str(x) for x in base_cmd(dt)]
    t0 = time.perf_counter()
    traci.start(cmd, label=label)
    conn = traci.getConnection(label)
    t = 0.0
    try:
        while t < END - dt / 2:
            conn.simulationStep()
            t = conn.simulation.getTime()
            if query:
                for v in conn.vehicle.getIDList():
                    conn.vehicle.getSpeed(v)
                    conn.vehicle.getPosition(v)
    finally:
        conn.close()
    return time.perf_counter() - t0


def r2_interface_overhead():
    rows = []
    for dt in (1.0, 0.5, 0.1):
        cli = mean([run_sumo(base_cmd(dt))["wall"] for _ in range(REPS)])
        tc_step = mean([_traci_run(dt, False) for _ in range(REPS)])
        tc_query = mean([_traci_run(dt, True) for _ in range(REPS)])
        rows.append(dict(dt=dt, cli_s=cli, traci_step_s=tc_step, traci_query_s=tc_query,
                         traci_step_overhead_x=tc_step / cli,
                         traci_query_overhead_x=tc_query / cli,
                         libsumo_s=None, libsumo_available=LIBSUMO["available"]))
        print("  dt=%-5g CLI=%6.2fs  TraCI(step)=%7.2fs (%.1fx)  TraCI(step+query)=%7.2fs (%.1fx)"
              % (dt, cli, tc_step, tc_step / cli, tc_query, tc_query / cli))
    return rows


def r3_threads():
    rows = []
    for th in (1, 2, 4, 8):
        ws = [run_sumo(base_cmd(0.1, threads=th))["wall"] for _ in range(REPS)]
        rows.append(dict(threads=th, wall=mean(ws), wall_sd=sd(ws)))
        print("  --threads %-2d wall=%6.2fs (sd %.2f)  speedup vs 1 thread=%.2fx"
              % (th, mean(ws), sd(ws), rows[0]["wall"] / mean(ws)))
    return rows


if __name__ == "__main__":
    print("libsumo:", "AVAILABLE at " + str(LIBSUMO["path"]) if LIBSUMO["available"]
          else "NOT INSTALLED -> " + str(LIBSUMO["error"]))
    print("\nR1 dt scaling (scenario = merge testbed, %g s of sim):" % END)
    r1 = r1_dt_scaling()
    print("\nR2 interface overhead:")
    r2 = r2_interface_overhead()
    print("\nR3 --threads scaling (dt=0.1):")
    r3 = r3_threads()
    e = [r for r in r1 if r["method"] == "euler"]
    base = [x for x in e if x["dt"] == 1.0][0]["wall"]
    print("\nlinearity check (wall/wall_dt1 vs 1/dt):")
    lin = []
    for x in e:
        lin.append(dict(dt=x["dt"], ratio_wall=x["wall"] / base, ratio_ideal=1.0 / x["dt"],
                        efficiency=(x["wall"] / base) / (1.0 / x["dt"])))
        print("  dt=%-5g wall ratio=%6.2f  ideal=%6.2f  observed/ideal=%.2f"
              % (x["dt"], lin[-1]["ratio_wall"], lin[-1]["ratio_ideal"], lin[-1]["efficiency"]))
    savejson("runtime.json", dict(libsumo=LIBSUMO, r1_dt=r1, r2_interface=r2,
                                  r3_threads=r3, linearity=lin, sim_seconds=END, reps=REPS))
