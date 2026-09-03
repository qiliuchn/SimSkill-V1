#!/usr/bin/env python3
"""
Run ONE simulation cell and compact it to a metrics dict (JSON on stdout).

A "cell" = (network arm, route file, --time-to-teleport value, sumo seed).

Teleport accounting follows this project's convention (see semantic memory page
`sumo-output-files`): the `summary` output's `teleports` attribute is a CUMULATIVE
running count -- read the LAST step's value, never sum across steps.

Teleport-AFFECTED vehicle IDs are NOT recorded by `tripinfo` (tripinfo has no
teleport field at all).  They are recovered by parsing SUMO's own warning log
("Teleporting vehicle 'X'; ..."), which is the only per-vehicle record available
without instrumenting the run with TraCI.
"""
import argparse
import json
import os
import re
import subprocess
import shutil
import sys
import xml.etree.ElementTree as ET

TELE_RE = re.compile(r"Teleporting vehicle '([^']+)'(?:;\s*(.*?),)?")


def sumo_bin(name="sumo"):
    p = shutil.which(name)
    if p:
        return p
    raise RuntimeError("no " + name)


def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def run(netfile, roufile, ttt, seed, outdir, end, keep_raw=True, extra=None):
    os.makedirs(outdir, exist_ok=True)
    tripinfo = os.path.join(outdir, "tripinfo.xml")
    summary = os.path.join(outdir, "summary.xml")
    logf = os.path.join(outdir, "sumo.log")

    cmd = [sumo_bin(), "-n", netfile, "-r", roufile,
           "--tripinfo-output", tripinfo,
           "--summary-output", summary,
           "--summary-output.period", "10",
           "--end", str(end),
           "--seed", str(seed),
           "--time-to-teleport", str(ttt),
           "--no-step-log", "true",
           "--duration-log.statistics", "true",
           "--log", logf,
           "--xml-validation", "never",
           "--no-warnings", "false"]
    if extra:
        cmd += extra
    t0 = __import__("time").time()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    wall = __import__("time").time() - t0
    if proc.returncode != 0:
        return {"error": proc.stderr[-4000:], "cmd": " ".join(cmd)}

    # ---- summary: cumulative teleports = LAST step value ----
    steps = []
    for _, el in ET.iterparse(summary, events=("end",)):
        if el.tag == "step":
            steps.append({k: el.get(k) for k in
                          ("time", "loaded", "inserted", "running", "waiting",
                           "ended", "arrived", "teleports", "halting", "meanSpeed",
                           "meanWaitingTime", "meanTravelTime")})
            el.clear()
    last = steps[-1]
    teleports_cum = int(last["teleports"])
    tele_series_max = max(int(s["teleports"]) for s in steps)
    assert teleports_cum == tele_series_max, "teleports not monotone -- convention check failed"

    # network clearance: first time running==0 AND waiting==0 after loading began
    clearance = None
    for s in steps:
        if float(s["time"]) > 60 and int(s["running"]) == 0 and int(s["waiting"]) == 0 \
           and int(s["inserted"]) > 0:
            clearance = float(s["time"])
            break
    peak_running = max(int(s["running"]) for s in steps)
    peak_waiting = max(int(s["waiting"]) for s in steps)
    end_running = int(last["running"])
    end_waiting = int(last["waiting"])

    # time-weighted mean network speed over steps where vehicles are present
    num, den = 0.0, 0.0
    for s in steps:
        r = int(s["running"])
        if r > 0:
            num += r * float(s["meanSpeed"])
            den += r
    mean_net_speed = num / den if den else float("nan")

    # ---- teleport-affected vehicle IDs from the log ----
    tele_ids = set()
    tele_reasons = {}
    nlines = 0
    with open(logf, errors="replace") as fh:
        for line in fh:
            m = TELE_RE.search(line)
            if m:
                nlines += 1
                tele_ids.add(m.group(1))
                r = (m.group(2) or "?").strip()
                tele_reasons[r] = tele_reasons.get(r, 0) + 1

    # ---- tripinfo ----
    trips = []
    for _, el in ET.iterparse(tripinfo, events=("end",)):
        if el.tag == "tripinfo":
            trips.append((el.get("id"), float(el.get("duration")),
                          float(el.get("timeLoss")), float(el.get("waitingTime")),
                          float(el.get("routeLength")), float(el.get("arrival")),
                          float(el.get("depart")), float(el.get("departDelay"))))
            el.clear()
    tripinfo_has_teleport_field = False
    if trips:
        # inspect one record's attribute names once
        root = ET.parse(tripinfo).getroot()
        first = root.find("tripinfo")
        if first is not None:
            tripinfo_has_teleport_field = any("teleport" in k.lower() for k in first.attrib)

    ids = [t[0] for t in trips]
    free = [t for t in trips if t[0] not in tele_ids]
    aff = [t for t in trips if t[0] in tele_ids]

    res = {
        "net": os.path.basename(netfile), "rou": os.path.basename(roufile),
        "ttt": ttt, "seed": seed, "end": end, "wall_s": round(wall, 1),
        "loaded": int(last["loaded"]), "inserted": int(last["inserted"]),
        "completed": len(trips),
        "teleports_cum": teleports_cum,
        "teleport_log_events": nlines,
        "teleport_vehicles": len(tele_ids),
        "teleport_reasons": tele_reasons,
        "tripinfo_has_teleport_field": tripinfo_has_teleport_field,
        "teleports_per_completed": (teleports_cum / len(trips)) if trips else None,
        "tele_affected_share_of_completed": (len(aff) / len(trips)) if trips else None,
        "clearance_time": clearance,
        "peak_running": peak_running, "peak_waiting": peak_waiting,
        "end_running": end_running, "end_waiting": end_waiting,
        "mean_net_speed": round(mean_net_speed, 4),
        "all_mean_duration": round(mean([t[1] for t in trips]), 2) if trips else None,
        "all_mean_timeloss": round(mean([t[2] for t in trips]), 2) if trips else None,
        "all_mean_waiting": round(mean([t[3] for t in trips]), 2) if trips else None,
        "all_mean_departdelay": round(mean([t[7] for t in trips]), 2) if trips else None,
        "free_n": len(free),
        "free_mean_duration": round(mean([t[1] for t in free]), 2) if free else None,
        "free_mean_timeloss": round(mean([t[2] for t in free]), 2) if free else None,
        "aff_n": len(aff),
        "aff_mean_duration": round(mean([t[1] for t in aff]), 2) if aff else None,
        "aff_mean_timeloss": round(mean([t[2] for t in aff]), 2) if aff else None,
    }
    with open(os.path.join(outdir, "cell.json"), "w") as fh:
        json.dump(res, fh, indent=2)
    with open(os.path.join(outdir, "teleported_ids.txt"), "w") as fh:
        fh.write("\n".join(sorted(tele_ids)))
    if not keep_raw:
        for f in (tripinfo, summary, logf):
            if os.path.exists(f):
                os.remove(f)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", required=True)
    ap.add_argument("--rou", required=True)
    ap.add_argument("--ttt", required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--end", type=float, required=True)
    args = ap.parse_args()
    print(json.dumps(run(args.net, args.rou, args.ttt, args.seed, args.outdir, args.end), indent=2))


if __name__ == "__main__":
    sys.exit(main())
