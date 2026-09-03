#!/usr/bin/env python3
"""Applied egress scenario: run + measure.

Deliverables produced per run:
  * clearance-time percentiles and the cumulative clearance curve
  * a space-time density / Fruin-LOS map along the whole egress path
  * pedestrian time-space trajectory data (with the signal timeline)
  * vehicle throughput / delay on the crossed street (the reverse coupling)
  * pedestrian jam exposure and vehicle teleport/collision counts
"""
import argparse
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_egress          # noqa: E402
import run_corridor          # noqa: E402

# Fruin walkway Level of Service, expressed as upper density bounds in persons/m^2
# (reciprocals of the classic area-module bounds 3.24 / 2.32 / 1.39 / 0.93 / 0.46 m^2/p)
LOS_BOUNDS = [(0.3086, "A"), (0.4310, "B"), (0.7194, "C"),
              (1.0753, "D"), (2.1739, "E"), (float("inf"), "F")]


def los_of(k):
    for b, name in LOS_BOUNDS:
        if k <= b:
            return name
    return "F"


def write_demand(path, n_ped, release_end, veh_per_hour, veh_end):
    L = ['<routes>',
         '  <vType id="ped" vClass="pedestrian"/>',
         '  <vType id="car" vClass="passenger"/>']
    if veh_per_hour > 0:
        L.append('  <flow id="v_sn" type="car" begin="0" end="%.1f" vehsPerHour="%.1f" '
                 'from="SJ" to="JN" departSpeed="max"/>' % (veh_end, veh_per_hour))
        L.append('  <flow id="v_ns" type="car" begin="0" end="%.1f" vehsPerHour="%.1f" '
                 'from="NJ" to="JS" departSpeed="max"/>' % (veh_end, veh_per_hour))
    L.append('  <personFlow id="eg" type="ped" begin="0" end="%.1f" number="%d">' % (release_end, n_ped))
    L.append('    <walk edges="EPLAZA EBOT EFAR" departPosLat="random" arrivalPos="-1"/>')
    L.append('  </personFlow>')
    L.append('</routes>')
    open(path, "w").write("\n".join(L) + "\n")


def lane_widths(net):
    root = ET.parse(net).getroot()
    w = {}
    for e in root.findall("edge"):
        for ln in e.findall("lane"):
            if "pedestrian" in (ln.get("allow") or "").split():
                w[e.get("id")] = float(ln.get("width")) if ln.get("width") else None
    return w


def analyse_fcd(fcd, widths, dx=10.0, dt_cell=30.0, x_min=-200.0, x_max=80.0,
                step=1.0, traj_out=None, n_traj=120):
    """Space-time Edie cells along the egress path -> density / speed / LOS map."""
    cells = {}
    trj = {}
    ctx = ET.iterparse(fcd, events=("start", "end"))
    tnow = 0.0
    tmax = 0.0
    for ev, el in ctx:
        if ev == "start" and el.tag == "timestep":
            tnow = float(el.get("time"))
            tmax = max(tmax, tnow)
        elif ev == "end" and el.tag == "person":
            x = float(el.get("x"))
            sp = float(el.get("speed"))
            edge = el.get("edge")
            pid = el.get("id")
            if x_min <= x <= x_max:
                i = int((x - x_min) // dx)
                j = int(tnow // dt_cell)
                c = cells.setdefault((i, j), [0.0, 0.0, 0.0, 0])   # tts, ttd, wsum, n
                c[0] += step
                c[1] += sp * step
                w = widths.get(edge)
                if w:
                    c[2] += w
                    c[3] += 1
            if traj_out:
                trj.setdefault(pid, []).append([tnow, round(x, 2)])
            el.clear()
        elif ev == "end" and el.tag == "timestep":
            el.clear()
    out = []
    for (i, j), (tts, ttd, wsum, n) in sorted(cells.items()):
        w = wsum / n if n else float("nan")
        area = dx * dt_cell
        k_lin = tts / area
        k = k_lin / w if w else float("nan")
        v = ttd / tts if tts > 0 else float("nan")
        out.append({"x": x_min + (i + 0.5) * dx, "t": (j + 0.5) * dt_cell,
                    "width": w, "density_p_m2": k, "flow_p_s": ttd / area,
                    "speed_ms": v, "los": los_of(k), "n_samples": int(tts / step)})
    if traj_out:
        ids = sorted(trj)
        stride = max(1, len(ids) // n_traj)
        sub = {ids[i]: trj[ids[i]] for i in range(0, len(ids), stride)}
        json.dump(sub, open(traj_out, "w"))
    return out, tmax


def veh_metrics(tri, net_info):
    """Vehicle throughput / delay on the crossed street."""
    n, dur, tl, wt, route = 0, 0.0, 0.0, 0.0, 0.0
    for _, el in ET.iterparse(tri, events=("end",)):
        if el.tag == "tripinfo":
            n += 1
            dur += float(el.get("duration"))
            tl += float(el.get("timeLoss"))
            wt += float(el.get("waitingTime"))
            route += float(el.get("routeLength"))
            el.clear()
    if n == 0:
        return {"n_vehicles_completed": 0}
    return {"n_vehicles_completed": n, "mean_veh_duration_s": dur / n,
            "mean_veh_timeloss_s": tl / n, "mean_veh_waiting_s": wt / n,
            "mean_veh_speed_ms": route / dur}


def clearance(tri):
    arr = []
    for _, el in ET.iterparse(tri, events=("end",)):
        if el.tag == "personinfo":
            w = el.findall("walk")
            if w:
                arr.append((float(w[-1].get("arrival")), float(el.get("duration")),
                            float(w[0].get("routeLength")), float(el.get("timeLoss"))))
            el.clear()
    arr.sort()
    n = len(arr)
    out = {"n_completed": n}
    if n:
        for p in (50, 90, 95, 99, 100):
            out["clearance_p%d" % p] = arr[min(n - 1, int(round(p / 100.0 * n)) - 1 if p < 100 else n - 1)][0]
        out["mean_egress_duration_s"] = sum(a[1] for a in arr) / n
        tot_len = sum(a[2] for a in arr)
        tot_dur = sum(a[1] for a in arr)
        out["mean_walk_speed_ms"] = tot_len / tot_dur
        out["mean_timeloss_s"] = sum(a[3] for a in arr) / n
        out["curve"] = [[a[0], i + 1] for i, a in enumerate(arr)]
    return out


def run(outdir, w_bottleneck, ped_green, veh_green=40, n_ped=1500, release_end=300.0,
        veh_per_hour=500.0, end=3600.0, seed=1, model="striping", step=1.0,
        keep_fcd=False, traj=False, jupedsim_model=None, extra=None):
    os.makedirs(outdir, exist_ok=True)
    info = build_egress.build(outdir, w_bottleneck, ped_green, veh_green)
    if not info["verification"]["ok"]:
        raise SystemExit("signal verification failed: %s" % info["verification"])
    net = info["net"]
    rou = os.path.join(outdir, "eg.rou.xml")
    write_demand(rou, n_ped, release_end, veh_per_hour, end)
    fcd = os.path.join(outdir, "fcd.xml")
    tri = os.path.join(outdir, "tripinfo.xml")
    psum = os.path.join(outdir, "psummary.xml")
    vsum = os.path.join(outdir, "summary.xml")
    log = os.path.join(outdir, "sumo.log")
    cmd = ["sumo", "-n", net, "-r", rou, "--pedestrian.model", model,
           "--fcd-output", fcd, "--tripinfo-output", tri,
           "--person-summary-output", psum, "--summary-output", vsum,
           "--end", str(end), "--step-length", str(step), "--seed", str(seed),
           "--no-step-log", "--message-log", log, "--error-log", log,
           "--time-to-teleport", "300",
           "--fcd-output.attributes", "x,y,speed,pos,edge"]
    if jupedsim_model:
        cmd += ["--pedestrian.jupedsim.model", jupedsim_model]
    if extra:
        cmd += list(extra)
    r = subprocess.run(cmd, capture_output=True, text=True)
    with open(log, "a") as f:
        f.write(r.stdout + r.stderr)
    if r.returncode != 0:
        raise SystemExit("sumo failed in %s:\n%s" % (outdir, (r.stdout + r.stderr)[-4000:]))

    widths = lane_widths(net)
    traj_out = os.path.join(outdir, "traj.json") if traj else None
    cellmap, tmax = analyse_fcd(fcd, widths, step=step, traj_out=traj_out)
    res = {
        "config": {"w_bottleneck": w_bottleneck, "ped_green": ped_green,
                   "veh_green": veh_green, "cycle": info["cycle"], "n_ped": n_ped,
                   "release_end": release_end, "veh_per_hour": veh_per_hour,
                   "end": end, "seed": seed, "model": model, "step": step,
                   "jupedsim_model": jupedsim_model},
        "net_verification": {"ok": info["verification"]["ok"],
                             "used_crossing": info["used_crossing"],
                             "used_crossing_link": info["used_crossing_link"],
                             "phases": info["phases"],
                             "ped_green_s": info["verification"]["ped_green_seconds"],
                             "cycle_s": info["verification"]["cycle_seconds"],
                             "ped_lane_widths": {k: widths[k] for k in
                                                 ("EPLAZA", "EBOT", "EFAR") if k in widths}},
        "clearance": clearance(tri),
        "vehicles": veh_metrics(tri, info),
        "events": run_corridor.count_log_events(log),
    }
    ps = run_corridor.person_summary(psum, step=step)
    ps_series = ps.pop("series")
    res["person_summary"] = ps
    vs = run_corridor.veh_summary(vsum)
    vs_series = vs.pop("series")
    res["veh_summary"] = vs
    res["accounting"] = {
        "n_ped_demanded": n_ped, "inserted": ps["inserted_final"],
        "completed": res["clearance"]["n_completed"],
        "still_walking_at_end": ps["walking_at_end"],
        "discarded": ps["discarded_final"], "peak_walking": ps["peak_walking"],
        "person_teleports": ps["teleports_final"],
        "vehicle_teleports": vs["veh_teleports_final"],
        "vehicle_collisions": vs["veh_collisions_final"],
    }
    # LOS summary: worst / modal LOS per longitudinal station over the surge
    bystat = {}
    for c in cellmap:
        bystat.setdefault(c["x"], []).append(c)
    res["los_profile"] = []
    for x in sorted(bystat):
        cs = [c for c in bystat[x] if c["n_samples"] > 0]
        if not cs:
            continue
        kmax = max(c["density_p_m2"] for c in cs)
        ktot = sum(c["density_p_m2"] * c["n_samples"] for c in cs) / sum(c["n_samples"] for c in cs)
        res["los_profile"].append({"x": x, "width": cs[0]["width"],
                                   "peak_density": kmax, "peak_los": los_of(kmax),
                                   "mean_density": ktot, "mean_los": los_of(ktot)})
    json.dump(res, open(os.path.join(outdir, "result.json"), "w"), indent=2)
    with open(os.path.join(outdir, "losmap.csv"), "w") as f:
        f.write("x,t,width,density_p_m2,flow_p_s,speed_ms,los,n_samples\n")
        for c in cellmap:
            f.write("%.1f,%.1f,%.2f,%.5f,%.5f,%.4f,%s,%d\n" %
                    (c["x"], c["t"], c["width"], c["density_p_m2"], c["flow_p_s"],
                     c["speed_ms"], c["los"], c["n_samples"]))
    with open(os.path.join(outdir, "accum.csv"), "w") as f:
        f.write("time,walking,jammed,running_vehicles\n")
        vmap = dict((t, v) for t, v in vs_series)
        for t, w, j in ps_series:
            f.write("%.1f,%d,%d,%d\n" % (t, w, j, vmap.get(t, 0)))
    if not keep_fcd and os.path.exists(fcd):
        os.remove(fcd)
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--w-bottleneck", type=float, required=True)
    ap.add_argument("--ped-green", type=int, default=20)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--model", default="striping")
    ap.add_argument("--n-ped", type=int, default=1500)
    ap.add_argument("--traj", action="store_true")
    a = ap.parse_args()
    r = run(a.outdir, a.w_bottleneck, a.ped_green, seed=a.seed, model=a.model,
            n_ped=a.n_ped, traj=a.traj)
    print(json.dumps({"clearance": {k: v for k, v in r["clearance"].items() if k != "curve"},
                      "vehicles": r["vehicles"], "accounting": r["accounting"]}, indent=2))
