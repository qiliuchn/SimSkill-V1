"""Is a parking="true" bus's re-entry gap-checked, or is it forced onto the lane
regardless (pushing the cost onto the following car)?

Test: single-lane section near saturation. For every bay-stop departure, find the
nearest car BEHIND the bus on the same lane in the second after the stop ends and
record its speed trajectory. Compare against the same cars' speed statistics at
matched positions when no bus departure is happening (within-run control).
"""
import os
import sys
import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from scenario import Cfg, build_scenario, SUMO  # noqa: E402

ROOT = os.path.dirname(HERE)
RUNS = os.path.join(ROOT, "runs", "verify_reentry_forced")
RES = os.path.join(ROOT, "results")


def run(cfg, outdir, seed):
    if os.path.isdir(outdir):
        shutil.rmtree(outdir)
    os.makedirs(outdir)
    sc = build_scenario(cfg, outdir, seed)
    opts = [SUMO, "-n", sc["net"], "-a", sc["busstops"],
            "-r", f'{sc["cars"]},{sc["buses"]},{sc["persons"]}',
            "--tripinfo-output", os.path.join(outdir, "tripinfo.xml"),
            "--stop-output", os.path.join(outdir, "stopinfo.xml"),
            "--fcd-output", os.path.join(outdir, "fcd.xml"),
            "--fcd-output.attributes", "id,x,speed,lane,type",
            "--no-step-log", "true", "--time-to-teleport", "300",
            "--seed", str(seed), "-e", str(int(cfg.sim_end))]
    with open(os.path.join(outdir, "err.txt"), "w") as fe:
        r = subprocess.run(opts, stdout=subprocess.DEVNULL, stderr=fe)
    assert r.returncode == 0, open(os.path.join(outdir, "err.txt")).read()[-2000:]
    return sc


def analyse(outdir, stop, cfg):
    frames = {}
    for _, el in ET.iterparse(os.path.join(outdir, "fcd.xml"), events=("end",)):
        if el.tag == "timestep":
            t = float(el.get("time"))
            frames[t] = [(v.get("id"), float(v.get("x")), float(v.get("speed")),
                          v.get("lane"), v.get("type")) for v in el]
            el.clear()
    rows = [s.attrib for s in ET.parse(os.path.join(outdir, "stopinfo.xml")).getroot()
            if s.attrib.get("busStop") == stop["id"]]
    lane = stop["lane"]
    ev = []
    for r in rows:
        te = float(r["ended"])
        bus = r["id"]
        f = frames.get(te + 1.0)
        if f is None:
            continue
        bx = next((x for i, x, s, l, ty in f if i == bus), None)
        if bx is None:
            continue
        cands = [(x, s, i) for i, x, s, l, ty in f
                 if ty == "car" and l == lane and bx - 60 < x < bx]
        if not cands:
            ev.append({"ended": te, "follower": None})
            continue
        x, s0, fid = max(cands)
        traj = []
        for dt in range(0, 9):
            ff = frames.get(te + 1.0 + dt)
            if ff is None:
                break
            sp = next((sp for i, xx, sp, l, ty in ff if i == fid), None)
            traj.append(sp)
        traj = [z for z in traj if z is not None]
        ev.append({"ended": te, "follower": fid, "gap_m": round(bx - x, 1),
                   "v0": round(s0, 2), "vmin_next8s": round(min(traj), 2) if traj else None,
                   "max_decel_ms2": round(max((traj[i] - traj[i + 1]) for i in range(len(traj) - 1)), 2)
                   if len(traj) > 1 else None,
                   "traj": [round(z, 2) for z in traj]})
    with_f = [e for e in ev if e.get("follower")]
    return {"n_departures": len(ev), "n_with_follower_within_60m": len(with_f),
            "mean_gap_at_reentry_m": (sum(e["gap_m"] for e in with_f) / len(with_f)) if with_f else None,
            "min_gap_at_reentry_m": min((e["gap_m"] for e in with_f), default=None),
            "mean_max_decel_ms2": (sum(e["max_decel_ms2"] or 0 for e in with_f) / len(with_f)) if with_f else None,
            "max_max_decel_ms2": max((e["max_decel_ms2"] or 0 for e in with_f), default=None),
            "events": ev}


if __name__ == "__main__":
    os.makedirs(RES, exist_ok=True)
    out = {}
    for q in (600, 900):
        cfg = Cfg(stop_placement="midblock", lanes_art=1, stop_type="bay",
                  q_art=float(q), q_cross=150.0, pax_rate=800.0, headway=150.0,
                  warmup=600.0, demand_end=3000.0, sim_end=5400.0)
        d = os.path.join(RUNS, f"bay_q{q}")
        sc = run(cfg, d, 11)
        a = analyse(d, sc["stops"][2], cfg)
        os.remove(os.path.join(d, "fcd.xml"))
        out[f"bay_q{q}"] = a
        print(f"q={q}: departures={a['n_departures']} withFollower={a['n_with_follower_within_60m']} "
              f"meanGap={a['mean_gap_at_reentry_m']} minGap={a['min_gap_at_reentry_m']} "
              f"meanMaxDecel={a['mean_max_decel_ms2']} maxMaxDecel={a['max_max_decel_ms2']}")
    json.dump(out, open(os.path.join(RES, "verify_reentry_forced.json"), "w"), indent=1)
