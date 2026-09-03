#!/usr/bin/env python3
"""Batch replication runner for the SUMO stochastic-variability study.

Runs N independent SUMO replications in parallel, one output directory per
replication, with an explicitly recorded seed list, then compacts each
replication down to a one-row metrics record so that the raw XML traces do not
have to be kept for every run.

Randomness sources are controlled *separately*:
  * demand seed   -> passed to randomTrips.py (--seed): changes the OD / route
                     realisation and the departure-time realisation.
  * sumo seed     -> passed to sumo (--seed): drives car-following noise
                     (sigma), speedFactor draws, lane-change and junction
                     decisions, insertion tie-breaking.
  * driver spread -> vType sigma / speedDev, supplied via an extra additional
                     file; set to 0 to switch this source off.

Usage (see run_all.py for the full experiment plan):
  python3 run_replications.py --design designs.json --out-root /work/dir
"""
import argparse
import csv
import json
import math
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ProcessPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
NET = os.path.join(HERE, "grid4x4.net.xml")
EDGEDATA_ADD = os.path.join(HERE, "edgedata.add.xml")

SIM_END = 7200          # hard stop; demand ends at 3600, rest is drain
WINDOW_BEGIN = 600      # steady-state analysis window (see warm-up analysis)
WINDOW_END = 3600

# ---------------------------------------------------------------------------
# vType additional files (driver-behaviour dispersion switch)
# ---------------------------------------------------------------------------
VTYPE_STOCHASTIC = """<additional>
    <vType id="DEFAULT_VEHTYPE" vClass="passenger" sigma="0.5" speedDev="0.1" speedFactor="1.0"/>
</additional>
"""
VTYPE_DETERMINISTIC = """<additional>
    <vType id="DEFAULT_VEHTYPE" vClass="passenger" sigma="0.0" speedDev="0.0" speedFactor="1.0"/>
</additional>
"""

EDGEDATA_TEMPLATE = """<additional>
    <edgeData id="ed_window" file="edgedata_window.xml" begin="600" end="3600" excludeEmpty="false"/>
    <edgeData id="ed_60" file="edgedata_60.xml" period="60" begin="0" end="7200" excludeEmpty="true"/>
</additional>
"""

# ---------------------------------------------------------------------------
# Empirically calibrated interior-link capacity (veh/h per interior directed
# edge). Established by probe_capacity.py from the maximum sustained discharge
# actually observed on this network's interior links; NOT assumed from theory.
# Overwritten at import time if capacity.json exists.
# ---------------------------------------------------------------------------
CAPACITY_VPH = 730.0
_cap_file = os.path.join(HERE, "capacity.json")
if os.path.exists(_cap_file):
    with open(_cap_file) as fh:
        CAPACITY_VPH = json.load(fh)["capacity_vph"]


def interior_edges(net=NET):
    import re
    grid = re.compile(r"^[A-D][0-3]$")
    root = ET.parse(net).getroot()
    out = []
    for e in root.findall("edge"):
        if e.get("function") == "internal":
            continue
        if grid.match(e.get("from") or "") and grid.match(e.get("to") or ""):
            out.append(e.get("id"))
    return set(out)


INTERIOR = None  # lazily filled per process


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------
def parse_tripinfo(path):
    """Per-vehicle completed-trip metrics."""
    dur, loss, wait, rlen, depart = [], [], [], [], []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "tripinfo":
            dur.append(float(el.get("duration")))
            loss.append(float(el.get("timeLoss")))
            wait.append(float(el.get("waitingTime")))
            rlen.append(float(el.get("routeLength")))
            depart.append(float(el.get("depart")))
            el.clear()
    return dur, loss, wait, rlen, depart


def parse_summary(path):
    """Time series from summary output.

    meanSpeed == -1 is SUMO's sentinel for 'no vehicles running this step' and
    is converted to NaN rather than treated as a speed (project convention).
    teleports is a CUMULATIVE count -> take the last step's value, never a sum.
    """
    t, running, mspeed, halting, loaded, inserted, ended = [], [], [], [], [], [], []
    tele_last = 0
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "step":
            t.append(float(el.get("time")))
            running.append(int(el.get("running")))
            ms = float(el.get("meanSpeed"))
            mspeed.append(float("nan") if ms < 0 else ms)
            halting.append(int(el.get("halting")))
            loaded.append(int(el.get("loaded")))
            inserted.append(int(el.get("inserted")))
            ended.append(int(el.get("ended")))
            tele_last = int(el.get("teleports"))
            el.clear()
    return dict(time=t, running=running, meanSpeed=mspeed, halting=halting,
                loaded=loaded, inserted=inserted, ended=ended,
                teleports=tele_last)


def parse_edgedata_window(path, interior):
    """Achieved v/c on interior links, measured from edgeData flow."""
    dur = float(WINDOW_END - WINDOW_BEGIN)
    vc, flows = [], []
    root = ET.parse(path).getroot()
    for iv in root.findall("interval"):
        for e in iv.findall("edge"):
            eid = e.get("id")
            if eid not in interior:
                continue
            left = float(e.get("left", 0.0))       # veh that left the edge
            arrived = float(e.get("arrived", 0.0))
            n = left + arrived
            f = n * 3600.0 / dur                   # veh/h
            flows.append(f)
            vc.append(f / CAPACITY_VPH)
    return vc, flows


def parse_queue(path):
    """Max-jam metric from --queue-output: network-total standing queue length.

    Returns (max over time of summed queueing_length, mean over time).
    """
    tot_by_t = {}
    cur_t = None
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "data":
            cur_t = float(el.get("timestep"))
            el.clear()
        elif el.tag == "lane":
            q = float(el.get("queueing_length", 0.0))
            if cur_t is not None:
                tot_by_t[cur_t] = tot_by_t.get(cur_t, 0.0) + q
            el.clear()
    if not tot_by_t:
        return 0.0, 0.0
    # restrict to the steady-state window
    vals = [v for t, v in tot_by_t.items() if WINDOW_BEGIN <= t <= WINDOW_END]
    if not vals:
        vals = list(tot_by_t.values())
    return max(vals), sum(vals) / len(vals)


def _mean(x):
    x = [v for v in x if not math.isnan(v)]
    return sum(x) / len(x) if x else float("nan")


def _pct(sorted_x, p):
    if not sorted_x:
        return float("nan")
    k = (len(sorted_x) - 1) * p
    lo, hi = int(math.floor(k)), int(math.ceil(k))
    if lo == hi:
        return sorted_x[lo]
    return sorted_x[lo] * (hi - k) + sorted_x[hi] * (k - lo)


# ---------------------------------------------------------------------------
# One replication
# ---------------------------------------------------------------------------
def run_one(job):
    """job: dict with keys
       id, out_dir, rate, demand_seed, sumo_seed, stochastic_driver,
       cycle_scale (1.0 = baseline), tls_type ('static'|'actuated'),
       keep_raw (bool), route_file (optional pre-built .rou.xml)
    """
    global INTERIOR
    if INTERIOR is None:
        INTERIOR = interior_edges()

    d = job["out_dir"]
    os.makedirs(d, exist_ok=True)

    # ---- demand ----------------------------------------------------------
    if job.get("route_file"):
        routes = job["route_file"]
    else:
        sys.path.insert(0, HERE)
        from gen_demand import gen
        routes = gen(job["rate"], job["demand_seed"], d, job["id"])

    # ---- vType additional -------------------------------------------------
    vt = os.path.join(d, "vtype.add.xml")
    with open(vt, "w") as fh:
        fh.write(VTYPE_STOCHASTIC if job.get("stochastic_driver", True)
                 else VTYPE_DETERMINISTIC)

    # edgeData additional is written INTO the replication dir: in SUMO 1.27.1
    # the edgeData 'file' attribute resolves relative to the ADDITIONAL FILE's
    # own directory, not to sumo's cwd (verified experimentally -- see
    # FINDINGS.md). Keeping a per-replication copy makes the output land in the
    # replication dir regardless of which interpretation applies.
    ed = os.path.join(d, "edgedata.add.xml")
    with open(ed, "w") as fh:
        fh.write(EDGEDATA_TEMPLATE)

    adds = [ed, vt]

    # ---- optional TLS treatment ------------------------------------------
    if job.get("tls_type") or job.get("cycle_scale", 1.0) != 1.0:
        tls = os.path.join(d, "tls.add.xml")
        write_tls_add(tls, job.get("tls_type", "static"),
                      job.get("cycle_scale", 1.0))
        adds.append(tls)

    cmd = [
        "sumo", "-n", NET, "-r", routes,
        "-a", ",".join(adds),
        "--seed", str(job["sumo_seed"]),
        "--begin", "0", "--end", str(SIM_END),
        "--tripinfo-output", "tripinfo.xml",
        "--summary-output", "summary.xml",
        "--queue-output", "queue.xml",
        "--queue-output.period", "10",
        "--no-step-log", "--no-warnings",
        "--xml-validation", "never",
        "--default.action-step-length", "1",
    ]
    # cwd = replication dir so that the edgeData 'file' attribute (a bare
    # filename) lands here -- edgeData paths resolve against sumo's cwd.
    p = subprocess.run(cmd, cwd=d, capture_output=True, text=True)
    if p.returncode != 0:
        return {"id": job["id"], "error": (p.stderr or p.stdout)[-2000:]}

    # ---- extract ----------------------------------------------------------
    dur, loss, wait, rlen, dep = parse_tripinfo(os.path.join(d, "tripinfo.xml"))
    summ = parse_summary(os.path.join(d, "summary.xml"))
    vc, flows = parse_edgedata_window(os.path.join(d, "edgedata_window.xml"),
                                      INTERIOR)
    qmax, qmean = parse_queue(os.path.join(d, "queue.xml"))

    svc = sorted(vc)
    rec = {
        "id": job["id"],
        "family": job.get("family", ""),
        "level": job.get("level", ""),
        "arm": job.get("arm", ""),
        "rate": job["rate"],
        "demand_seed": job["demand_seed"],
        "sumo_seed": job["sumo_seed"],
        "stochastic_driver": int(job.get("stochastic_driver", True)),
        "n_completed": len(dur),
        "mean_duration": _mean(dur),
        "mean_timeloss": _mean(loss),
        "mean_waiting": _mean(wait),
        "mean_routelen": _mean(rlen),
        "mean_trip_speed": (_mean(rlen) / _mean(dur)) if dur else float("nan"),
        "teleports": summ["teleports"],
        "max_running": max(summ["running"]) if summ["running"] else 0,
        "vc_mean": _mean(vc),
        "vc_p90": _pct(svc, 0.90),
        "vc_max": max(vc) if vc else float("nan"),
        "flow_mean_vph": _mean(flows),
        "queue_max_m": qmax,
        "queue_mean_m": qmean,
        "inserted": summ["inserted"][-1] if summ["inserted"] else 0,
        "loaded": summ["loaded"][-1] if summ["loaded"] else 0,
    }
    # completed trips that DEPARTED inside the steady-state window
    win = [dd for dd, dp in zip(dur, dep) if WINDOW_BEGIN <= dp <= WINDOW_END]
    winl = [ll for ll, dp in zip(loss, dep) if WINDOW_BEGIN <= dp <= WINDOW_END]
    rec["n_completed_window"] = len(win)
    rec["mean_duration_window"] = _mean(win)
    rec["mean_timeloss_window"] = _mean(winl)

    # compact summary time series (needed for warm-up analysis)
    ts_path = os.path.join(d, "summary_ts.csv")
    with open(ts_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["time", "running", "meanSpeed", "halting"])
        for i in range(0, len(summ["time"])):
            w.writerow([summ["time"][i], summ["running"][i],
                        "" if math.isnan(summ["meanSpeed"][i])
                        else "%.4f" % summ["meanSpeed"][i],
                        summ["halting"][i]])

    if not job.get("keep_raw", False):
        for f in ("queue.xml", "edgedata_60.xml", "tripinfo.xml",
                  "summary.xml"):
            fp = os.path.join(d, f)
            if os.path.exists(fp):
                os.remove(fp)
        for f in os.listdir(d):
            # only delete demand files this job generated; a shared, pre-built
            # route file (fixed-route replication family) must survive
            if f.startswith("trips_") or (f.startswith("routes_")
                                          and not job.get("route_file")):
                os.remove(os.path.join(d, f))
    return rec


def write_tls_add(path, tls_type, cycle_scale):
    """Emit a TLS program override for all 16 junctions.

    tls_type='actuated' converts the fixed-time program to a gap-based
    actuated one; cycle_scale rescales green durations of the static program.
    """
    root = ET.parse(NET).getroot()
    out = ['<additional>']
    for tl in root.findall("tlLogic"):
        tid = tl.get("id")
        phases = tl.findall("phase")
        if tls_type == "actuated":
            out.append('  <tlLogic id="%s" type="actuated" programID="t" offset="%s">'
                       % (tid, tl.get("offset", "0")))
            for ph in phases:
                dur = float(ph.get("duration"))
                st = ph.get("state")
                if "y" in st:
                    out.append('    <phase duration="%g" state="%s"/>' % (dur, st))
                else:
                    out.append('    <phase duration="%g" minDur="6" maxDur="%g" state="%s"/>'
                               % (dur, dur * 1.6, st))
            out.append('  </tlLogic>')
        else:
            out.append('  <tlLogic id="%s" type="static" programID="t" offset="%s">'
                       % (tid, tl.get("offset", "0")))
            for ph in phases:
                dur = float(ph.get("duration"))
                st = ph.get("state")
                if "y" not in st:
                    dur = round(dur * cycle_scale)
                out.append('    <phase duration="%g" state="%s"/>' % (dur, st))
            out.append('  </tlLogic>')
    out.append('</additional>')
    with open(path, "w") as fh:
        fh.write("\n".join(out) + "\n")


FIELDS = ["id", "family", "level", "arm", "rate", "demand_seed", "sumo_seed",
          "stochastic_driver", "n_completed", "mean_duration", "mean_timeloss",
          "mean_waiting", "mean_routelen", "mean_trip_speed", "teleports",
          "max_running", "vc_mean", "vc_p90", "vc_max", "flow_mean_vph",
          "queue_max_m", "queue_mean_m", "inserted", "loaded",
          "n_completed_window", "mean_duration_window", "mean_timeloss_window"]


def run_batch(jobs, csv_out, workers=None):
    workers = workers or max(1, (os.cpu_count() or 4) - 2)
    recs, errs = [], []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(run_one, j): j for j in jobs}
        done = 0
        for f in as_completed(futs):
            r = f.result()
            done += 1
            if "error" in r:
                errs.append(r)
                sys.stderr.write("[ERR] %s: %s\n" % (r["id"], r["error"][:300]))
            else:
                recs.append(r)
            if done % 10 == 0:
                sys.stderr.write("  ... %d/%d done\n" % (done, len(jobs)))
                sys.stderr.flush()
    recs.sort(key=lambda r: r["id"])
    with open(csv_out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for r in recs:
            w.writerow({k: r.get(k, "") for k in FIELDS})
    return recs, errs


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--design", required=True, help="JSON list of job dicts")
    ap.add_argument("--csv-out", required=True)
    ap.add_argument("--workers", type=int, default=None)
    a = ap.parse_args()
    with open(a.design) as fh:
        jobs = json.load(fh)
    recs, errs = run_batch(jobs, a.csv_out, a.workers)
    print("ok=%d err=%d -> %s" % (len(recs), len(errs), a.csv_out))
