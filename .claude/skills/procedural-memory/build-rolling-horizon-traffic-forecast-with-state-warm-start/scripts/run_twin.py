"""PARTS 2-6 - ground truth, sensor emulation, rolling-horizon twin, oracles, meso.

Arms (all forecast 1800 s ahead from every 300 s cycle):
  twin          assimilated state (twin's own chained sim, driven by observed
                entry counts, INCIDENT-BLIND) + persistence demand forecast
  oracle_demand assimilated state            + TRUE future demand profile
  oracle_state  ground-truth state (warm-started from the GT run's own saved
                state, i.e. perfect initial condition INCLUDING the incident)
                + persistence demand forecast
  oracle_both   ground-truth state + true future demand  (irreducible floor)
  twin_meso     assimilated MESO state + persistence demand, --mesosim

usage:  python3 run_twin.py gt|hist|twin|forecast|all
"""
import gzip
import json
import multiprocessing as mp
import os
import shutil
import sys
import time
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import *  # noqa
from twin_lib import (NET, BASE_ROU, INC_ROU, STATE_OPTS, add_edgedata, run,
                      metrics_series, sensor_observations, write_flows,
                      write_flows_count, strip_flowstate, VTYPE)

GT = os.path.join(FC_DIR, "gt")
HIST = os.path.join(FC_DIR, "hist")
TWIN = os.path.join(FC_DIR, "twin")
FC = os.path.join(FC_DIR, "fc")
STRIP = os.path.join(FC_DIR, "states_forkable")
for d in (GT, HIST, TWIN, FC, STRIP):
    os.makedirs(d, exist_ok=True)

COMMON = ["--time-to-teleport", "-1", "--no-step-log", "true"]
MESO = ["--mesosim", "--meso-junction-control"]


# ==================================================================== GT day
def gt_day(seed):
    d = os.path.join(GT, f"s{seed}")
    ap300, f300 = None, None
    if os.path.exists(d):
        shutil.rmtree(d)
    os.makedirs(d)
    ap300, f300 = add_edgedata(d, 300, "sc")
    ap60, f60 = add_edgedata(d, 60, "fine")
    sens = open(os.path.join(SCEN, "sensors.add.xml")).read().replace(
        'file="e1.xml"', 'file="%s"' % os.path.join(d, "e1.xml"))
    sp = os.path.join(d, "sensors.add.xml")
    open(sp, "w").write(sens)
    args = ["-n", NET, "-r", f"{BASE_ROU},{INC_ROU}",
            "-a", ",".join([sp, ap300, ap60]),
            "--end", str(SIM_END), "--seed", str(seed)] + COMMON + [
            "--tripinfo-output", "tripinfo.xml", "--summary-output", "summary.xml",
            "--stop-output", "stops.xml",
            "--save-state.period", str(CYCLE), "--save-state.prefix", "gtst",
            "--save-state.suffix", ".xml.gz"] + STATE_OPTS
    wall, _ = run(d, args, clean=False)
    json.dump({"seed": seed, "wall_s": wall}, open(os.path.join(d, "timing.json"), "w"))
    return d


def hist_day(seed):
    """Incident-FREE replication of the same demand profile -> historical average."""
    d = os.path.join(HIST, f"s{seed}")
    if os.path.exists(d):
        shutil.rmtree(d)
    os.makedirs(d)
    ap300, _ = add_edgedata(d, 300, "sc")
    args = ["-n", NET, "-r", BASE_ROU, "-a", ap300,
            "--end", str(SIM_END), "--seed", str(seed)] + COMMON + [
            "--summary-output", "summary.xml"]
    run(d, args, clean=False)
    return d


# ============================================================ twin advance
def observed_entry_counts(seed):
    """Vehicles counted by the ENTRY E1 station per CYCLE-long interval.
    This is the ONLY demand information the twin ever receives."""
    obs = sensor_observations(os.path.join(GT, f"s{seed}", "e1.xml"), agg=CYCLE)
    return {b: obs[("ENTRY", b)]["count"] for (st, b) in obs if st == "ENTRY"}


def build_twin_demand(seed):
    counts = observed_entry_counts(seed)
    iv = [(b, b + CYCLE, counts.get(b, 0.0))
          for b in range(0, SIM_END, CYCLE)]
    p = os.path.join(TWIN, f"twin_obs_s{seed}.rou.xml")
    write_flows_count(p, iv, "obs")
    return p, counts


def twin_advance(seed, mode="micro"):
    """Chain of CYCLE-long runs, each warm-started from the previous state.

    The twin never sees the incident and never sees ground-truth state; it only
    sees the entry-station counts.
    """
    rou, counts = build_twin_demand(seed)
    base = os.path.join(TWIN, f"s{seed}_{mode}")
    if os.path.exists(base):
        shutil.rmtree(base)
    os.makedirs(base)
    engine = MESO if mode == "meso" else []
    states = {}
    prev = None
    timing = []
    for t in range(0, SIM_END, CYCLE):
        te = t + CYCLE
        d = os.path.join(base, f"adv_{te}")
        args = ["-n", NET, "-r", rou, "--end", str(te + 1), "--seed", str(seed),
                "--summary-output", "summary.xml"] + COMMON + engine + [
                "--save-state.times", str(te), "--save-state.prefix", "st",
                "--save-state.suffix", ".xml.gz"] + STATE_OPTS
        if prev is None:
            args += ["--begin", "0"]
        else:
            args += ["--load-state", prev]
        wall, _ = run(d, args)
        st = os.path.join(d, f"st_{te}.00.xml.gz")
        if not os.path.exists(st):
            raise RuntimeError(f"no state at {te}: {sorted(os.listdir(d))}")
        states[te] = st
        timing.append({"t_end": te, "wall_s": wall})
        prev = st
    json.dump({"states": states, "timing": timing},
              open(os.path.join(base, "index.json"), "w"), indent=1)
    return states


# ============================================================ forecasting
def persistence_rate(counts, t):
    """veh/h implied by the entry count observed over [t-CYCLE, t)."""
    return counts.get(t - CYCLE, 0.0) * 3600.0 / CYCLE


def forecast_routes(seed, t, kind, counts):
    """Route file covering [t, t+1800) for one forecast."""
    p = os.path.join(FC, f"rou_s{seed}_{kind}_{t}.rou.xml")
    if kind == "persist":
        q = persistence_rate(counts, t)
        iv = [(b, b + CYCLE, q) for b in range(t, t + max(HORIZONS), CYCLE)]
    elif kind == "true":
        iv = [(b, b + CYCLE, demand_at(b + CYCLE / 2.0))
              for b in range(t, t + max(HORIZONS), CYCLE)]
    else:
        raise ValueError(kind)
    return write_flows(p, iv, f"fc{t}")


BLOCKER_DEPART = INCIDENT_START - 120   # 5280; matches build_scenario.py

ARMS = {
    #  name              : (state source, demand forecast, engine, drop_pending_blockers)
    "twin":               ("twin", "persist", "micro", False),
    "oracle_demand":      ("twin", "true",    "micro", False),
    "oracle_state":       ("gt",   "persist", "micro", True),
    "oracle_both":        ("gt",   "true",    "micro", True),
    "twin_meso":          ("twin", "persist", "meso",  False),
    # kept deliberately: the same two oracles WITHOUT removing the blockers that
    # SUMO leaves in every state as loaded-but-not-yet-departed vehicles
    "oracle_state_leaky": ("gt",   "persist", "micro", False),
    "oracle_both_leaky":  ("gt",   "true",    "micro", False),
}


def forecast_one(args):
    seed, arm, t, statefile, roufile, remove = args
    src, dem, eng, _drop = ARMS[arm]
    d = os.path.join(FC, f"s{seed}", arm, f"t{t}")
    os.makedirs(os.path.dirname(d), exist_ok=True)
    ap, fp = None, None
    if os.path.exists(d):
        shutil.rmtree(d)
    os.makedirs(d)
    ap, fp = add_edgedata(d, 300, "sc")
    engine = MESO if eng == "meso" else []
    # fork the state: <flowState> MUST be stripped, otherwise the restored flows
    # emit alongside the forecast's own flows (see twin_lib.strip_flowstate)
    fork = os.path.join(STRIP, f"s{seed}_{src}_{eng}_{t}.xml.gz")
    if not os.path.exists(fork):
        strip_flowstate(statefile, fork)
    a = ["-n", NET, "-r", roufile, "-a", ap,
         "--load-state", fork, "--end", str(t + max(HORIZONS)),
         "--seed", str(seed + 900000)] + COMMON + engine
    if remove:
        a += ["--load-state.remove-vehicles", ",".join(remove)]
    wall, _ = run(d, a, clean=False)
    return {"seed": seed, "arm": arm, "t": t, "wall_s": wall, "edgedata": fp,
            "state_src": src, "removed": remove, "fork_state": fork}


def build_tasks(seed):
    counts = observed_entry_counts(seed)
    gts = {}
    gd = os.path.join(GT, f"s{seed}")
    for f in os.listdir(gd):
        if f.startswith("gtst_"):
            gts[int(float(f[5:-7]))] = os.path.join(gd, f)
    tasks = []
    for arm, (src, dem, eng, drop) in ARMS.items():
        if src == "twin":
            idx = json.load(open(os.path.join(TWIN, f"s{seed}_{eng}", "index.json")))
            states = {int(k): v for k, v in idx["states"].items()}
        else:
            states = gts
        for t in CYCLES:
            if t not in states:
                raise RuntimeError(f"no state for {arm} seed{seed} t={t}; "
                                   f"have {sorted(states)[:5]}...")
            rou = forecast_routes(seed, t, dem, counts)
            rem = ["BLOCK_0", "BLOCK_1"] if (drop and t < BLOCKER_DEPART) else []
            tasks.append((seed, arm, t, states[t], rou, rem))
    return tasks


# ==================================================================== driver
def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    nproc = 8
    if what in ("gt", "all"):
        with mp.Pool(nproc) as pool:
            pool.map(gt_day, SEEDS)
        print("gt done")
    if what in ("hist", "all"):
        with mp.Pool(nproc) as pool:
            pool.map(hist_day, HIST_SEEDS)
        print("hist done")
    if what in ("twin", "all"):
        jobs = [(s, m) for s in SEEDS for m in ("micro", "meso")]
        with mp.Pool(nproc) as pool:
            pool.starmap(twin_advance, jobs)
        print("twin advance done")
    if what in ("forecast", "all"):
        tasks = []
        for s in SEEDS:
            tasks += build_tasks(s)
        print("forecast tasks:", len(tasks), flush=True)
        t0 = time.time()
        with mp.Pool(nproc) as pool:
            res = pool.map(forecast_one, tasks)
        json.dump(res, open(os.path.join(FC_DIR, "forecast_index.json"), "w"), indent=1)
        print("forecast done in %.1f s wall (%d processes)" % (time.time() - t0, nproc))


if __name__ == "__main__":
    main()
