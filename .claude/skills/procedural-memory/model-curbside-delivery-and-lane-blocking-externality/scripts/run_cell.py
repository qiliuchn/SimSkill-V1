#!/usr/bin/env python3
"""
Run ONE experimental cell/replication and compact its raw SUMO output into a
single metrics JSON.

Usage (single run, for debugging / raw archiving):
    python3 run_cell.py --net-dir NET --run-dir DIR --variant A --volume 1200 \
        --cell D30 --seed 7 [--fcd] [--keep-raw]
"""
import argparse
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scenario as SC  # noqa: E402

BULK = ["lanechange.xml", "tripinfo.xml", "fcd.xml", "edgedata.xml",
        "lanedata_van.xml", "lanedata_car.xml", "e1.xml", "e2.xml",
        "summary.xml", "stops.xml", "routes.rou.xml", "extra.add.xml"]


def _f(el, k, d=0.0):
    v = el.get(k)
    return d if v is None else float(v)


def overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def run(net_dir, run_dir, variant, volume, cell, seed, fcd=False):
    net_dir = os.path.abspath(net_dir)
    run_dir = os.path.abspath(run_dir)
    SC.build_run_dir(run_dir, variant, volume, cell, seed)
    net = os.path.join(net_dir, f"variant{variant}.net.xml")
    cmd = [
        "sumo", "-n", net, "-r", "routes.rou.xml", "-a", "extra.add.xml",
        "--begin", "0", "--end", str(SC.SIM_END), "--seed", str(seed),
        "--tripinfo-output", "tripinfo.xml",
        "--tripinfo-output.write-unfinished",
        "--summary-output", "summary.xml",
        "--stop-output", "stops.xml",
        "--lanechange-output", "lanechange.xml",
        "--time-to-teleport", "300",
        "--no-step-log", "--xml-validation", "never",
        "--duration-log.statistics", "true",
        "--no-warnings", "true",
    ]
    if fcd:
        cmd += ["--fcd-output", "fcd.xml", "--fcd-output.acceleration"]
    proc = subprocess.run(cmd, cwd=run_dir, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"sumo failed in {run_dir}:\n{proc.stderr[-3000:]}")
    stdout = proc.stdout
    m = parse(run_dir, variant, volume, cell, seed, stdout)
    m["stderr_tail"] = proc.stderr[-500:]
    with open(os.path.join(run_dir, "metrics.json"), "w") as fh:
        json.dump(m, fh, indent=1)
    return m


def parse(run_dir, variant, volume, cell, seed, stdout=""):
    W0, W1 = SC.WARMUP, SC.MEAS_END
    j = lambda n: os.path.join(run_dir, n)
    m = dict(variant=variant, volume=volume, cell=cell, seed=seed,
             stops_per_hour=SC.DELIVERY_CELLS[cell][0],
             dwell_s=SC.DELIVERY_CELLS[cell][1])

    # ---- tripinfo: cars (main street) separated from vans and cross traffic
    car_d, car_tl, car_dd, car_wt = [], [], [], []
    van_d, van_tl = [], []
    unfinished = 0
    for tr in ET.parse(j("tripinfo.xml")).getroot():
        vid = tr.get("id")
        dep = _f(tr, "depart")
        if tr.get("arrival") is None or _f(tr, "arrival", -1) < 0:
            unfinished += 1
        if vid.startswith("car."):
            if W0 <= dep < W1:
                car_d.append(_f(tr, "duration"))
                car_tl.append(_f(tr, "timeLoss"))
                car_dd.append(_f(tr, "departDelay"))
                car_wt.append(_f(tr, "waitingTime"))
        elif vid.startswith("van."):
            if W0 <= dep < W1:
                van_d.append(_f(tr, "duration"))
                van_tl.append(_f(tr, "timeLoss"))
    n = max(len(car_d), 1)
    m["car_n"] = len(car_d)
    m["car_mean_duration_s"] = sum(car_d) / n
    m["car_mean_timeloss_s"] = sum(car_tl) / n
    m["car_mean_departdelay_s"] = sum(car_dd) / n
    m["car_mean_waiting_s"] = sum(car_wt) / n
    m["car_mean_delay_s"] = (sum(car_tl) + sum(car_dd)) / n
    m["car_total_timeloss_vehh"] = sum(car_tl) / 3600.0
    m["car_total_delay_vehh"] = (sum(car_tl) + sum(car_dd)) / 3600.0
    m["van_n"] = len(van_d)
    m["van_mean_duration_s"] = sum(van_d) / max(len(van_d), 1)
    m["unfinished_trips"] = unfinished

    # ---- E1 downstream of curb zone -> corridor throughput
    thr = 0.0
    for iv in ET.parse(j("e1.xml")).getroot():
        b, e = _f(iv, "begin"), _f(iv, "end")
        if b >= W0 and e <= W1:
            thr += _f(iv, "nVehContrib")
    m["throughput_vph"] = thr * 3600.0 / (W1 - W0)

    # ---- E2 upstream lane-area detectors -> queue (summed across lanes)
    per_iv = {}
    for iv in ET.parse(j("e2.xml")).getroot():
        b = _f(iv, "begin")
        if not (W0 <= b < W1):
            continue
        d = per_iv.setdefault(b, [0.0, 0.0])
        d[0] += _f(iv, "maxJamLengthInVehicles")
        d[1] += _f(iv, "meanMaxJamLengthInVehicles")
    if per_iv:
        m["queue_max_veh"] = max(v[0] for v in per_iv.values())
        m["queue_mean_veh"] = sum(v[1] for v in per_iv.values()) / len(per_iv)
    else:
        m["queue_max_veh"] = m["queue_mean_veh"] = 0.0

    # ---- lane changes (cars only) in / upstream of the curb zone
    lc_all = lc_zone = lc_out_of_curblane = 0
    for ch in ET.parse(j("lanechange.xml")).getroot():
        if ch.get("type") != "car":
            continue
        t = _f(ch, "time")
        if not (W0 <= t < W1):
            continue
        frm = ch.get("from") or ""
        lc_all += 1
        edge = frm.rsplit("_", 1)[0]
        if edge in ("E0", "ECURB"):
            lc_zone += 1
            # the "forced merge out of the blocked curb lane" event:
            # variant A right travel lane is ECURB_0 / E0_0,
            # variant B right travel lane is ECURB_1 / E0_0.
            right = "ECURB_0" if variant == "A" else "ECURB_1"
            if frm in (right, "E0_0") and int(_f(ch, "dir")) > 0:
                lc_out_of_curblane += 1
    m["lc_car_total"] = lc_all
    m["lc_car_curbzone"] = lc_zone
    m["lc_car_forced_merge"] = lc_out_of_curblane

    # ---- stop-output -> ACTUAL curb blockage (dwell clipped to the window)
    block = 0.0
    nstops = 0
    lane_ok = 0
    parking_flags = set()
    for st in ET.parse(j("stops.xml")).getroot():
        if not (st.get("id") or "").startswith("van."):
            continue
        s, e = _f(st, "started", -1), _f(st, "ended", -1)
        if s < 0:
            continue
        if e < 0:
            e = SC.SIM_END
        ov = overlap(s, e, W0, W1)
        if ov > 0:
            nstops += 1
            block += ov
        parking_flags.add(st.get("parking"))
        if (st.get("lane") or "").startswith("ECURB"):
            lane_ok += 1
    m["curb_block_s"] = block
    m["curb_block_vehh"] = block / 3600.0
    m["n_stops_in_window"] = nstops
    m["stop_parking_flags"] = sorted(x for x in parking_flags if x is not None)
    m["stops_on_curb_edge"] = lane_ok

    # ---- laneData (delivery only) -> van vehicle-seconds per ECURB lane
    vl = {}
    for iv in ET.parse(j("lanedata_van.xml")).getroot():
        if not (W0 <= _f(iv, "begin") < W1):
            continue
        for ed in iv.findall("edge"):
            if ed.get("id") != "ECURB":
                continue
            for ln in ed.findall("lane"):
                vl[ln.get("id")] = vl.get(ln.get("id"), 0.0) + \
                    _f(ln, "sampledSeconds")
    m["van_lane_seconds_ECURB"] = {k: round(v, 1) for k, v in sorted(vl.items())}
    # car vehicle-seconds per ECURB lane -> shows cars vacating the blocked lane
    cl = {}
    for iv in ET.parse(j("lanedata_car.xml")).getroot():
        if not (W0 <= _f(iv, "begin") < W1):
            continue
        for ed in iv.findall("edge"):
            if ed.get("id") != "ECURB":
                continue
            for ln in ed.findall("lane"):
                cl[ln.get("id")] = cl.get(ln.get("id"), 0.0) + \
                    _f(ln, "sampledSeconds")
    m["car_lane_seconds_ECURB"] = {k: round(v, 1) for k, v in sorted(cl.items())}

    # ---- summary -> teleports (CUMULATIVE: read the LAST step, never sum)
    tele = coll = 0
    last_running = 0
    for step in ET.parse(j("summary.xml")).getroot():
        tele = int(_f(step, "teleports", tele))
        coll = int(_f(step, "collisions", coll))
        last_running = int(_f(step, "running"))
    m["teleports"] = tele
    m["collisions"] = coll
    m["running_at_end"] = last_running

    for line in stdout.splitlines():
        s = line.strip()
        if s.startswith("Inserted:"):
            m["inserted"] = s
        if "not inserted" in s.lower() or s.startswith("Emergency"):
            m.setdefault("insert_notes", []).append(s)
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--net-dir", required=True)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--variant", required=True)
    ap.add_argument("--volume", type=int, required=True)
    ap.add_argument("--cell", required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--fcd", action="store_true")
    a = ap.parse_args()
    m = run(a.net_dir, a.run_dir, a.variant, a.volume, a.cell, a.seed, a.fcd)
    print(json.dumps(m, indent=1))


if __name__ == "__main__":
    main()
