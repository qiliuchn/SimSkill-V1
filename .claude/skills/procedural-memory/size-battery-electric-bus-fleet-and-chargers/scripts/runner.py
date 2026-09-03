#!/usr/bin/env python3
"""Run one experimental cell of the BEB study (plain command-line SUMO, no TraCI)."""
import os, sys, json, time, subprocess, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scenario as SC
import build_net as BN

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
BUILD = os.path.join(ROOT, "build")
NET = os.path.join(BUILD, "corr.net.xml")
DEMAND = os.path.join(BUILD, "demand")   # CRN: shared car/person files per seed


DEFAULTS = dict(
    cap_kwh=200.0, init_frac=0.90, aux_w=7000, recup=0.85,
    mass_mode="coupled",           # coupled | fixed
    mass_base=13000.0, kg_per_kwh=7.0,
    n_term_chargers=2, term_power_kw=120.0, depot_power_kw=60.0,
    charger_policy="skip",
    stop_stride=1, midday_depot=None,
    nbus=SC.NBUS, ncyc=SC.NCYC, n_persons=2400,
    seed=1, sim_end=SC.SIM_END, battery_precision=4,
)


def ensure_demand(seed, n_persons):
    os.makedirs(DEMAND, exist_ok=True)
    cars = os.path.join(DEMAND, f"cars_s{seed}.rou.xml")
    pers = os.path.join(DEMAND, f"pax_s{seed}_{n_persons}.rou.xml")
    if not os.path.exists(cars):
        SC.write_cars(cars, seed)
    if not os.path.exists(pers):
        SC.write_persons(pers, seed, n_persons)
    return cars, pers


def bus_mass(cfg):
    if cfg["mass_mode"] == "fixed":
        return cfg["mass_base"] + cfg["kg_per_kwh"] * 200.0   # mass of the 200 kWh reference
    return cfg["mass_base"] + cfg["kg_per_kwh"] * cfg["cap_kwh"]


def build_cell(outdir, **kw):
    cfg = dict(DEFAULTS); cfg.update(kw)
    os.makedirs(outdir, exist_ok=True)
    add = os.path.join(outdir, "stops.add.xml")
    SC.write_additional(add, cfg["n_term_chargers"], int(cfg["term_power_kw"] * 1000),
                        int(cfg["depot_power_kw"] * 1000))
    bus = os.path.join(outdir, "buses.rou.xml")
    mass = bus_mass(cfg)
    sched = SC.write_buses(bus, cfg["cap_kwh"], cfg["init_frac"], cfg["aux_w"], cfg["recup"],
                           mass, cfg["n_term_chargers"], cfg["stop_stride"],
                           cfg["midday_depot"], cfg["nbus"], cfg["ncyc"],
                           charger_policy=cfg["charger_policy"])
    cars, pers = ensure_demand(cfg["seed"], cfg["n_persons"])
    cfg["_mass_kg"] = mass
    json.dump({"cfg": {k: v for k, v in cfg.items()}, "sched": sched},
              open(os.path.join(outdir, "cell.json"), "w"), indent=1)

    cmd = ["sumo", "-n", NET,
           "-r", ",".join([bus, cars, pers]),
           "-a", add,
           "--begin", "0", "--end", str(cfg["sim_end"]),
           "--step-length", "1",
           "--battery-output", os.path.join(outdir, "battery.xml"),
           "--battery-output.precision", str(cfg["battery_precision"]),
           "--chargingstations-output", os.path.join(outdir, "chargingstations.xml"),
           "--tripinfo-output", os.path.join(outdir, "tripinfo.xml"),
           "--stop-output", os.path.join(outdir, "stopinfo.xml"),
           "--summary-output", os.path.join(outdir, "summary.xml"),
           "--statistic-output", os.path.join(outdir, "stats.xml"),
           "--seed", str(cfg["seed"]),
           "--time-to-teleport", "600",
           "--pedestrian.model", "striping",
           "--device.rerouting.probability", "0",
           "--no-step-log", "true",
           "--duration-log.statistics", "true",
           "--xml-validation", "never",
           "--tripinfo-output.write-unfinished", "true",
           ]
    open(os.path.join(outdir, "sumo_cmd.txt"), "w").write(" ".join(cmd))
    return cfg, cmd


def run_cell(outdir, **kw):
    cfg, cmd = build_cell(outdir, **kw)
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True)
    dt = time.time() - t0
    open(os.path.join(outdir, "sumo_stderr.txt"), "w").write(p.stderr)
    return {"rc": p.returncode, "wall_s": round(dt, 1),
            "stderr_head": p.stderr[:2000], "outdir": outdir}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir")
    ap.add_argument("--kw", default="{}")
    a = ap.parse_args()
    r = run_cell(a.outdir, **json.loads(a.kw))
    print(json.dumps(r, indent=1))
