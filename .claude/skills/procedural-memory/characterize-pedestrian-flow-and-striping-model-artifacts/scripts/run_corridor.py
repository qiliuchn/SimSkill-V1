#!/usr/bin/env python3
"""Corridor run driver: build net -> demand -> sumo -> Edie measurement -> row.

Raw FCD is deleted immediately after measurement unless --keep-fcd, because the
sweeps here produce several hundred runs of multi-hundred-MB trajectory data.
Everything downstream reads the retained per-run measurement JSON, the retained
tripinfo.xml and the retained sumo stderr log.
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
import build_corridor          # noqa: E402
import make_demand             # noqa: E402
import edie                    # noqa: E402

JAM_RE = re.compile(r"jam|squeez", re.I)


def tripinfo_accounting(path):
    """Completed-vs-still-walking accounting from <personinfo>/<walk>."""
    out = {"n_personinfo": 0, "walk_dur_sum": 0.0, "walk_len_sum": 0.0,
           "time_loss_sum": 0.0, "waiting_sum": 0.0, "n_vehicles": 0,
           "veh_dur_sum": 0.0, "veh_timeloss_sum": 0.0, "veh_waiting_sum": 0.0}
    if not os.path.exists(path):
        return out
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "personinfo":
            out["n_personinfo"] += 1
            for w in el.findall("walk"):
                out["walk_dur_sum"] += float(w.get("duration"))
                out["walk_len_sum"] += float(w.get("routeLength"))
                out["time_loss_sum"] += float(w.get("timeLoss"))
                out["waiting_sum"] += float(w.get("waitingTime"))
            el.clear()
        elif el.tag == "tripinfo":
            out["n_vehicles"] += 1
            out["veh_dur_sum"] += float(el.get("duration"))
            out["veh_timeloss_sum"] += float(el.get("timeLoss"))
            out["veh_waiting_sum"] += float(el.get("waitingTime"))
            el.clear()
    if out["n_personinfo"]:
        out["mean_walk_duration"] = out["walk_dur_sum"] / out["n_personinfo"]
        out["mean_walk_speed"] = (out["walk_len_sum"] / out["walk_dur_sum"]
                                  if out["walk_dur_sum"] else float("nan"))
        out["mean_walk_timeloss"] = out["time_loss_sum"] / out["n_personinfo"]
    if out["n_vehicles"]:
        out["mean_veh_duration"] = out["veh_dur_sum"] / out["n_vehicles"]
        out["mean_veh_timeloss"] = out["veh_timeloss_sum"] / out["n_vehicles"]
    return out


def person_summary(path, step=1.0, t_from=None, t_to=None):
    """Parse --person-summary-output.

    VERIFIED SEMANTICS (SUMO 1.27.1), checked directly against a run's own series:
      * `walking` is INSTANTANEOUS (rises and falls).
      * `jammed` is CUMULATIVE -- it is monotone non-decreasing and routinely exceeds
        `walking` (observed 12326 jam events vs a peak of 4690 walking persons in one
        run).  It counts jam EVENTS, not pedestrians currently jammed.  Integrating it
        over time is meaningless; read the last value, or difference two times to get
        the events inside a window.  Same convention as summary.xml's `teleports`.
      * loaded / inserted / ended / arrived / teleports / discarded are cumulative too.
    """
    out = {"peak_walking": 0, "walking_at_end": 0,
           "jam_events_total": 0, "jam_events_in_window": 0,
           "person_seconds_window": 0.0, "jam_series_monotone": True,
           "teleports_final": 0, "loaded_final": 0, "inserted_final": 0,
           "ended_final": 0, "arrived_final": 0, "discarded_final": 0,
           "series": []}
    if not os.path.exists(path):
        return out
    j_at_from = None
    j_at_to = None
    prev_j = -1
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag != "step":
            continue
        t = float(el.get("time"))
        w = int(float(el.get("walking", 0) or 0))
        j = int(float(el.get("jammed", 0) or 0))
        if j < prev_j:
            out["jam_series_monotone"] = False
        prev_j = j
        out["peak_walking"] = max(out["peak_walking"], w)
        if t_from is not None:
            if j_at_from is None and t >= t_from:
                j_at_from = j
            if t <= t_to:
                j_at_to = j
            if t_from <= t <= t_to:
                out["person_seconds_window"] += w * step
        for k, a in [("teleports_final", "teleports"), ("loaded_final", "loaded"),
                     ("inserted_final", "inserted"), ("ended_final", "ended"),
                     ("arrived_final", "arrived"), ("discarded_final", "discarded")]:
            out[k] = int(float(el.get(a, 0) or 0))
        out["jam_events_total"] = j
        out["walking_at_end"] = w
        out["series"].append((t, w, j))
        el.clear()
    if j_at_from is not None and j_at_to is not None:
        out["jam_events_in_window"] = j_at_to - j_at_from
    out["jam_events_per_1000_person_seconds"] = (
        1000.0 * out["jam_events_in_window"] / out["person_seconds_window"]
        if out["person_seconds_window"] > 0 else 0.0)
    out["jam_events_per_inserted_person"] = (
        out["jam_events_total"] / out["inserted_final"] if out["inserted_final"] else 0.0)
    return out


def veh_summary(path):
    """Vehicle summary: peak running + final cumulative teleports."""
    out = {"peak_running_vehicles": 0, "veh_teleports_final": 0, "veh_collisions_final": 0,
           "veh_inserted_final": 0, "veh_arrived_final": 0, "series": []}
    if not os.path.exists(path):
        return out
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag != "step":
            continue
        rv = int(float(el.get("running", 0) or 0))
        out["peak_running_vehicles"] = max(out["peak_running_vehicles"], rv)
        out["veh_teleports_final"] = int(float(el.get("teleports", 0) or 0))
        out["veh_collisions_final"] = int(float(el.get("collisions", 0) or 0))
        out["veh_inserted_final"] = int(float(el.get("inserted", 0) or 0))
        out["veh_arrived_final"] = int(float(el.get("arrived", 0) or 0))
        out["series"].append((float(el.get("time")), rv))
        el.clear()
    return out


def count_log_events(log_path):
    n_jam = 0
    n_tel = 0
    n_coll = 0
    jam_ped = set()
    if os.path.exists(log_path):
        for line in open(log_path, errors="ignore"):
            low = line.lower()
            if "jam" in low and "person" in low:
                n_jam += 1
                m = re.search(r"[Pp]erson '([^']+)'", line)
                if m:
                    jam_ped.add(m.group(1))
            if "teleport" in low:
                n_tel += 1
            if "collision" in low:
                n_coll += 1
    return {"log_jam_lines": n_jam, "log_teleport_lines": n_tel,
            "log_collision_lines": n_coll, "log_jammed_persons": len(jam_ped)}


def run(outdir, w_mid, rate, seed, frac_fwd=1.0, w_feed=6.0, w_exit=6.0,
        end=1800.0, demand_end=1500.0, warmup=600.0, meas_end=1500.0,
        x1=60.0, x2=140.0, step=1.0, model="striping", stripe_width=None,
        jamtime=None, jamtime_crossing=None, keep_fcd=False, mid_len=200.0,
        lateral=False, extra_args=None, traj_out=None, speed_exit=13.89):
    os.makedirs(outdir, exist_ok=True)
    net = os.path.join(outdir, "corr.net.xml")
    info = build_corridor.build(net, w_feed, w_mid, w_exit, mid_len=mid_len,
                                speed_exit=speed_exit)
    if not info["ok"]:
        raise SystemExit("net verification failed: %s" % info["errors"])
    rou = os.path.join(outdir, "ped.rou.xml")
    dem = make_demand.write_demand(rou, rate, frac_fwd, 0.0, demand_end)

    fcd = os.path.join(outdir, "fcd.xml")
    tri = os.path.join(outdir, "tripinfo.xml")
    summ = os.path.join(outdir, "psummary.xml")
    log = os.path.join(outdir, "sumo.log")

    cmd = ["sumo", "-n", net, "-r", rou,
           "--pedestrian.model", model,
           "--fcd-output", fcd, "--tripinfo-output", tri, "--person-summary-output", summ,
           "--end", str(end), "--step-length", str(step), "--seed", str(seed),
           "--no-step-log", "--message-log", log, "--error-log", log,
           "--duration-log.statistics", "true",
           "--fcd-output.attributes", "x,y,speed,pos,edge"]
    if stripe_width is not None:
        cmd += ["--pedestrian.striping.stripe-width", str(stripe_width)]
    if jamtime is not None:
        cmd += ["--pedestrian.striping.jamtime", str(jamtime)]
    if jamtime_crossing is not None:
        cmd += ["--pedestrian.striping.jamtime.crossing", str(jamtime_crossing)]
    if extra_args:
        cmd += list(extra_args)
    r = subprocess.run(cmd, capture_output=True, text=True)
    with open(log, "a") as f:
        f.write(r.stdout)
        f.write(r.stderr)
    if r.returncode != 0:
        raise SystemExit("sumo failed in %s:\n%s\n%s" % (outdir, r.stdout[-3000:], r.stderr[-3000:]))

    # Put the Edie region in the MIDDLE of the measurement edge, derived from the
    # compiled lane shape -- never at the edge boundary, where the entry transition
    # from the wide feed and the junction walkingarea would contaminate it.
    xc = 0.5 * (info["EM_x0"] + info["EM_x1"])
    half = 0.5 * (x2 - x1)
    x1, x2 = xc - half, xc + half
    m = edie.measure(fcd, x1, x2, warmup, meas_end, w_mid, dt=step,
                     y_center=info["EM_y_center"], lateral=lateral,
                     traj_out=traj_out)
    m["config"] = {"w_mid": w_mid, "w_feed": w_feed, "w_exit": w_exit, "rate": rate,
                   "seed": seed, "frac_fwd": frac_fwd, "model": model,
                   "stripe_width": stripe_width, "jamtime": jamtime,
                   "jamtime_crossing": jamtime_crossing, "end": end,
                   "demand_end": demand_end, "warmup": warmup, "meas_end": meas_end,
                   "step": step, "mid_len": mid_len, "speed_exit": speed_exit}
    m["demand"] = dem
    m["tripinfo"] = tripinfo_accounting(tri)
    s = person_summary(summ, step=step, t_from=warmup, t_to=meas_end)
    series = s.pop("series")
    m["person_summary"] = s
    m["events"] = count_log_events(log)
    # demand / completed-vs-still-walking accounting
    m["accounting"] = {
        "expected_departures": rate * demand_end,
        "loaded": s["loaded_final"],
        "inserted": s["inserted_final"],
        "completed_persons": m["tripinfo"]["n_personinfo"],
        "arrived": s["arrived_final"],
        "discarded": s["discarded_final"],
        "still_walking_at_end": s["walking_at_end"],
        "peak_walking": s["peak_walking"],
        "jam_events_total": s["jam_events_total"],
        "completion_rate": (m["tripinfo"]["n_personinfo"] / s["inserted_final"]
                            if s["inserted_final"] else float("nan")),
    }
    json.dump(m, open(os.path.join(outdir, "measure.json"), "w"), indent=2)
    with open(os.path.join(outdir, "accum.csv"), "w") as f:
        f.write("time,walking,jammed\n")
        for t, w, j in series:
            f.write("%.1f,%d,%d\n" % (t, w, j))
    if not keep_fcd and os.path.exists(fcd):
        os.remove(fcd)
    return m


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--w-mid", type=float, required=True)
    ap.add_argument("--rate", type=float, required=True)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--frac-fwd", type=float, default=1.0)
    ap.add_argument("--w-exit", type=float, default=6.0)
    ap.add_argument("--keep-fcd", action="store_true")
    ap.add_argument("--lateral", action="store_true")
    a = ap.parse_args()
    m = run(a.outdir, a.w_mid, a.rate, a.seed, a.frac_fwd, w_exit=a.w_exit,
            keep_fcd=a.keep_fcd, lateral=a.lateral)
    print(json.dumps({k: m[k] for k in ("flow_p_s", "flow_p_s_per_m", "density_p_m2",
                                        "speed_ms", "accounting", "events")}, indent=2))
