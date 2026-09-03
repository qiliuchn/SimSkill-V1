#!/usr/bin/env python3
"""Performance metrics parsed from raw SUMO output, for GT-vs-rerun comparison."""
import csv
import math
import os
import xml.etree.ElementTree as ET

from common import BIN, N_BINS, JUNCTIONS, RUNS, parse_e2

PEAK_BINS = (7, 8, 9, 10)          # the TRUE peak hour (t = 6300-9900 s)

LOS_THRESHOLDS = [(10.0, "A"), (20.0, "B"), (35.0, "C"),
                  (55.0, "D"), (80.0, "E"), (float("inf"), "F")]


def los_letter(d):
    for thr, letter in LOS_THRESHOLDS:
        if d <= thr:
            return letter
    return "F"


def e3_delay(run_dir):
    """{(J, app, bin): dict(travel, timeloss, halts, n)}"""
    out = {}
    for _, el in ET.iterparse(os.path.join(run_dir, "e3_delay.xml"), events=("end",)):
        if el.tag != "interval":
            continue
        _p, j, app = el.get("id").split("_")
        b = int(float(el.get("begin")) // BIN)
        n = int(el.get("vehicleSum"))
        out[(j, app, b)] = dict(
            travel=float(el.get("meanTravelTime")), timeloss=float(el.get("meanTimeLoss")),
            halts=float(el.get("meanHaltsPerVehicle")), n=n)
        el.clear()
    return out


def approach_delay(run_dir, bins=PEAK_BINS):
    """Vehicle-weighted mean segment time loss (control-delay proxy) per approach
    over the given bins, plus the total vehicle count."""
    e3 = e3_delay(run_dir)
    out = {}
    for j in JUNCTIONS:
        for app in ("EB", "WB", "NB", "SB"):
            num = den = 0.0
            for b in bins:
                r = e3.get((j, app, b))
                if r and r["n"] > 0 and r["timeloss"] >= 0:
                    num += r["timeloss"] * r["n"]
                    den += r["n"]
            if den > 0:
                out[(j, app)] = dict(delay=num / den, n=den, los=los_letter(num / den))
    return out


def cycle_queues(run_dir):
    """{det: [(cycle_start, jam_min, jam_max)]}"""
    out = {}
    with open(os.path.join(run_dir, "queue_cycles.csv")) as f:
        for r in csv.DictReader(f):
            out.setdefault(r["det"], []).append(
                (float(r["cycle_start"]), float(r["jam_min_veh"]), float(r["jam_max_veh"])))
    return out


APPROACH_DETS = {}
for _j in JUNCTIONS:
    for _a in ("EB", "WB"):
        APPROACH_DETS[(_j, _a)] = ["q_%s_%s_F0" % (_j, _a), "q_%s_%s_F1" % (_j, _a),
                                   "q_%s_%s_BAY" % (_j, _a)]
    for _a in ("SB", "NB"):
        APPROACH_DETS[(_j, _a)] = ["q_%s_%s_ALL" % (_j, _a)]


def percentile(v, p):
    if not v:
        return float("nan")
    v = sorted(v)
    k = (len(v) - 1) * p
    lo, hi = math.floor(k), math.ceil(k)
    return v[int(k)] if lo == hi else v[lo] + (v[hi] - v[lo]) * (k - lo)


def back_of_queue(run_dir, bins=PEAK_BINS):
    """95th-percentile back of queue per approach: the per-cycle MAXIMUM jam
    length summed over the approach's detectors, 95th percentile over the cycles
    inside the given bins.  Also the residual (per-cycle minimum) at the END of
    the last bin, i.e. the overflow queue left at the end of the peak."""
    cq = cycle_queues(run_dir)
    t0, t1 = min(bins) * BIN, (max(bins) + 1) * BIN
    out = {}
    for key, dets in APPROACH_DETS.items():
        per_cycle_max, per_cycle_min = {}, {}
        for d in dets:
            for (t, qmin, qmax) in cq.get(d, []):
                per_cycle_max[t] = per_cycle_max.get(t, 0.0) + qmax
                per_cycle_min[t] = per_cycle_min.get(t, 0.0) + qmin
        inwin = [v for t, v in per_cycle_max.items() if t0 <= t < t1]
        tail = [v for t, v in sorted(per_cycle_min.items()) if t1 - 180 <= t < t1]
        out[key] = dict(q95_veh=percentile(inwin, 0.95),
                        qmax_veh=max(inwin) if inwin else float("nan"),
                        residual_end_of_peak_veh=(sum(tail) / len(tail)) if tail else 0.0,
                        n_cycles=len(inwin))
    return out


def residual_series(run_dir):
    """{(J,app,bin): residual queue (veh)} from queue_bins.csv."""
    out = {}
    with open(os.path.join(run_dir, "queue_bins.csv")) as f:
        for r in csv.DictReader(f):
            if r["q_resid_veh"] == "":
                continue
            for key, dets in APPROACH_DETS.items():
                if r["det"] in dets:
                    k = (key[0], key[1], int(r["bin"]))
                    out[k] = out.get(k, 0.0) + float(r["q_resid_veh"])
    return out
