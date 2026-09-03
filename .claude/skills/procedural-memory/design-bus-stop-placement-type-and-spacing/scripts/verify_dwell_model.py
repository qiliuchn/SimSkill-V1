"""Verify dwell is ENDOGENOUS (scales with the realised boarding/alighting load)
and quantify any fixed overhead that SUMO adds for a parking="true" stop.

Two conditions:
  loaded    : full car + cross traffic (the study's operating point)
  cleanroom : zero car traffic, so the bus's dwell is uncontaminated by traffic
              interference -> the honest place to test for a fixed parking overhead
"""
import os
import sys
import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from scenario import Cfg, build_scenario, SUMO  # noqa: E402

ROOT = os.path.dirname(HERE)
RUNS = os.path.join(ROOT, "runs", "verify_dwell")
RES = os.path.join(ROOT, "results")


def go(cfg, outdir, seed):
    if os.path.isdir(outdir):
        shutil.rmtree(outdir)
    os.makedirs(outdir)
    sc = build_scenario(cfg, outdir, seed)
    opts = [SUMO, "-n", sc["net"], "-a", sc["busstops"],
            "-r", f'{sc["cars"]},{sc["buses"]},{sc["persons"]}',
            "--stop-output", os.path.join(outdir, "stopinfo.xml"),
            "--tripinfo-output", os.path.join(outdir, "tripinfo.xml"),
            "--tripinfo-output.write-unfinished", "true",
            "--no-step-log", "true", "--time-to-teleport", "300",
            "--seed", str(seed), "-e", str(int(cfg.sim_end))]
    with open(os.path.join(outdir, "err.txt"), "w") as fe:
        subprocess.run(opts, stdout=subprocess.DEVNULL, stderr=fe, check=True)
    rows = sorted([s.attrib for s in ET.parse(os.path.join(outdir, "stopinfo.xml")).getroot()
                   if s.attrib.get("busStop")], key=lambda r: (r["id"], float(r["started"])))
    merged = []
    for r in rows:
        if merged and merged[-1]["id"] == r["id"] and merged[-1]["busStop"] == r["busStop"] \
                and float(r["started"]) - float(merged[-1]["ended"]) <= 3.0:
            merged[-1]["ended"] = r["ended"]
            merged[-1]["loadedPersons"] = str(int(merged[-1]["loadedPersons"]) + int(r["loadedPersons"]))
            merged[-1]["unloadedPersons"] = str(int(merged[-1]["unloadedPersons"]) + int(r["unloadedPersons"]))
            continue
        merged.append(dict(r))
    D = np.array([float(r["ended"]) - float(r["started"]) for r in merged])
    B = np.array([int(r["loadedPersons"]) for r in merged], float)
    U = np.array([int(r["unloadedPersons"]) for r in merged], float)
    X = np.c_[np.ones(len(D)), B, U]
    beta, *_ = np.linalg.lstsq(X, D, rcond=None)
    pred = X @ beta
    r2 = 1 - ((D - pred) ** 2).sum() / max(((D - D.mean()) ** 2).sum(), 1e-9)
    return {"n_events": int(len(D)), "intercept_s": round(float(beta[0]), 3),
            "per_boarding_s": round(float(beta[1]), 3),
            "per_alighting_s": round(float(beta[2]), 3), "R2": round(float(r2), 4),
            "corr_dwell_vs_pax": round(float(np.corrcoef(D, B + U)[0, 1]), 4),
            "mean_dwell": round(float(D.mean()), 2),
            "mean_pax": round(float((B + U).mean()), 2),
            "configured_boardingDuration": cfg.boarding_duration,
            "configured_min_dwell": cfg.min_dwell}


if __name__ == "__main__":
    os.makedirs(RES, exist_ok=True)
    out = {}
    for cond, kw in (("loaded", dict(q_art=900.0, q_cross=250.0)),
                     ("cleanroom", dict(q_art=0.0, q_cross=0.0))):
        for stype in ("inlane", "bay"):
            cfg = Cfg(stop_type=stype, stop_placement="farside",
                      pax_rate=700.0, headway=200.0, **kw)
            out[f"{cond}-{stype}"] = go(cfg, os.path.join(RUNS, f"{cond}_{stype}"), 4)
            print(f"{cond:9s} {stype:7s} dwell = {out[f'{cond}-{stype}']['intercept_s']:.2f}"
                  f" + {out[f'{cond}-{stype}']['per_boarding_s']:.3f}*board"
                  f" + {out[f'{cond}-{stype}']['per_alighting_s']:.3f}*alight"
                  f"  R2={out[f'{cond}-{stype}']['R2']:.4f} n={out[f'{cond}-{stype}']['n_events']}"
                  f" meanDwell={out[f'{cond}-{stype}']['mean_dwell']}")
    # how does the parked-stop overhead scale with the flow the bus re-enters into?
    sweep = []
    for lanes, qs in ((2, (0, 450, 900, 1350, 1800)), (1, (0, 300, 600, 900))):
        for q in qs:
            r = {}
            for stype in ("inlane", "bay"):
                cfg = Cfg(stop_type=stype, stop_placement="midblock", lanes_art=lanes,
                          q_art=float(q), q_cross=200.0, pax_rate=700.0, headway=200.0)
                r[stype] = go(cfg, os.path.join(RUNS, f"sw_{lanes}_{q}_{stype}"), 4)
            sweep.append({"lanes_art": lanes, "q_art": q,
                          "q_per_lane": q / lanes,
                          "intercept_inlane": r["inlane"]["intercept_s"],
                          "intercept_bay": r["bay"]["intercept_s"],
                          "overhead_s": round(r["bay"]["intercept_s"] - r["inlane"]["intercept_s"], 3),
                          "mean_dwell_inlane": r["inlane"]["mean_dwell"],
                          "mean_dwell_bay": r["bay"]["mean_dwell"],
                          "R2_bay": r["bay"]["R2"]})
            print(f"  lanes={lanes} q={q:5d} (q/lane={q/lanes:6.1f}) parked-stop overhead = "
                  f"{sweep[-1]['overhead_s']:6.2f}s  (R2_bay={r['bay']['R2']:.3f})")
    out["parking_overhead_vs_flow"] = sweep
    out["parking_overhead_cleanroom_s"] = round(
        out["cleanroom-bay"]["intercept_s"] - out["cleanroom-inlane"]["intercept_s"], 3)
    out["parking_overhead_loaded_s"] = round(
        out["loaded-bay"]["intercept_s"] - out["loaded-inlane"]["intercept_s"], 3)
    json.dump(out, open(os.path.join(RES, "verify_dwell_model.json"), "w"), indent=1)
    print("cleanroom parking overhead (s/stop):", out["parking_overhead_cleanroom_s"])
    print("loaded    parking overhead (s/stop):", out["parking_overhead_loaded_s"])
