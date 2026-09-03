"""Parsing / metric definitions for the work-zone study.

ONE AUTHORITATIVE DEFINITION PER METRIC (convention inherited from
`build-diamond-interchange-with-signal-offset-spillback` / the ramp-metering skill):

* QUEUED INTERVAL -- a 60 s detector interval in which the upstream control station
  (e2_ctrl_*, last 400 m of the advance-warning area) reports a lane-mean speed below
  0.6 x free-flow (i.e. < 20.0 m/s against a 33.33 m/s limit).  A queue upstream of the
  taper is the precondition for calling anything a *queue-discharge* rate.

* WORK-ZONE QUEUE-DISCHARGE CAPACITY (veh/h/open-lane) -- the mean, over queued
  intervals excluding the first QD_WARMUP seconds after queue onset, of the total flow
  recorded by the E1 station 15 m before the end of the activity area (det_disch_*,
  one loop per open lane), divided by the number of open lanes.  Demand is 100 %
  passenger cars, so veh/h/ln == pc/h/ln and the HCM 1600 pc/h/ln work-zone reference
  is directly comparable with no PCE conversion.

* TSTT (veh-h) -- in-network vehicle-hours from edgeData `sampledSeconds` over ALL
  edges including internal, PLUS the origin-insertion integral
  int len(getPendingVehicles()) dt.  Decomposed into freeway / ramps / detour-arterial /
  origin.  The origin term is what makes the accounting honest: a vehicle that is never
  inserted appears in no tripinfo and no edgeData.
"""
import json
import os
import xml.etree.ElementTree as ET
from collections import defaultdict

import numpy as np

import wz_common as W

FREE_SPEED = 33.33
QUEUE_SPEED_FRAC = 0.6
QD_WARMUP = 300.0          # s after queue onset excluded as the startup transient
HCM_WZ_REF = 1600.0        # pc/h/ln, HCM freeway work-zone reference

FREEWAY_EDGES = set(W.MAINLINE_ORDER)
RAMP_EDGES = {"rOFF", "rON"}
DETOUR_EDGES = {"dA", "dB", "dC", "dD"}


# ------------------------------------------------------------------ detectors
def read_e1(path):
    """[{id, begin, end, nVehContrib, flow, occupancy, speed}] from an E1 output file."""
    if not os.path.exists(path):
        return []
    root = ET.parse(path).getroot()
    out = []
    for iv in root.findall("interval"):
        out.append(dict(id=iv.get("id"), begin=float(iv.get("begin")),
                        end=float(iv.get("end")),
                        n=float(iv.get("nVehContrib")),
                        flow=float(iv.get("flow")),
                        occ=float(iv.get("occupancy")),
                        speed=float(iv.get("speed"))))
    return out


def read_e2(path):
    if not os.path.exists(path):
        return []
    root = ET.parse(path).getroot()
    out = []
    for iv in root.findall("interval"):
        try:
            sp = float(iv.get("meanSpeed"))
        except (TypeError, ValueError):
            sp = -1.0
        out.append(dict(id=iv.get("id"), begin=float(iv.get("begin")),
                        end=float(iv.get("end")), speed=sp,
                        occ=float(iv.get("occupancy") or 0.0),
                        jam=float(iv.get("maxJamLengthInMeters") or 0.0),
                        nveh=float(iv.get("nVehSeen") or 0.0)))
    return out


def queued_intervals(rundir):
    """Set of interval begin-times during which an upstream queue is present."""
    rows = read_e2(os.path.join(rundir, "e2_ctrl.xml"))
    by_t = defaultdict(list)
    for r in rows:
        if r["speed"] >= 0:
            by_t[r["begin"]].append(r["speed"])
    q = {t for t, v in by_t.items() if np.mean(v) < QUEUE_SPEED_FRAC * FREE_SPEED}
    return q, {t: float(np.mean(v)) for t, v in by_t.items()}


def discharge_capacity(rundir, n_open_lanes):
    """Work-zone queue-discharge capacity, veh/h/open-lane.  See module docstring."""
    e1 = read_e1(os.path.join(rundir, "e1_disch.xml"))
    if not e1:
        return dict(cap=np.nan, n_intervals=0, onset=None, total_flow=np.nan)
    q, _ = queued_intervals(rundir)
    if not q:
        return dict(cap=np.nan, n_intervals=0, onset=None, total_flow=np.nan)
    onset = min(q)
    by_t = defaultdict(float)
    for r in e1:
        by_t[r["begin"]] += r["flow"]
    use = [by_t[t] for t in sorted(q) if t >= onset + QD_WARMUP and t in by_t]
    if not use:
        use = [by_t[t] for t in sorted(q) if t in by_t]
    tot = float(np.mean(use)) if use else np.nan
    return dict(cap=tot / n_open_lanes, n_intervals=len(use), onset=onset,
                total_flow=tot)


def sustained_capacity(rundir, n_open_lanes, k=10):
    """Fallback capacity definition for cells where no UPSTREAM queue forms (e.g. the
    unobstructed reference, where the binding constraint is insertion, so the
    queue-discharge gate never fires): the highest mean total flow over any k
    consecutive 60 s intervals at the activity-area exit, per open lane.
    Reported ALONGSIDE the queue-discharge number, never silently substituted."""
    e1 = read_e1(os.path.join(rundir, "e1_disch.xml"))
    if not e1:
        return dict(cap_sust=np.nan)
    by_t = defaultdict(float)
    for r in e1:
        by_t[r["begin"]] += r["flow"]
    ts = sorted(by_t)
    if len(ts) < k:
        k = max(1, len(ts))
    vals = [np.mean([by_t[t] for t in ts[i:i + k]]) for i in range(len(ts) - k + 1)]
    return dict(cap_sust=float(max(vals)) / n_open_lanes if vals else np.nan)


# ------------------------------------------------------------------ tripinfo
def read_tripinfo(path):
    if not os.path.exists(path):
        return dict(n=0)
    root = ET.parse(path).getroot()
    dur, tl, wt, dd, rl, co2, fuel = [], [], [], [], [], [], []
    n_unfinished = 0
    for t in root.findall("tripinfo"):
        if t.get("arrival") is not None and float(t.get("arrival")) < 0:
            n_unfinished += 1
            continue
        dur.append(float(t.get("duration")))
        tl.append(float(t.get("timeLoss")))
        wt.append(float(t.get("waitingTime")))
        dd.append(float(t.get("departDelay")))
        rl.append(float(t.get("routeLength")))
        e = t.find("emissions")
        if e is not None:
            co2.append(float(e.get("CO2_abs")))
            fuel.append(float(e.get("fuel_abs")))
    f = lambda a: float(np.mean(a)) if a else np.nan
    return dict(n=len(dur), n_unfinished=n_unfinished,
                mean_duration=f(dur), mean_timeloss=f(tl), mean_waiting=f(wt),
                mean_departdelay=f(dd), mean_routelength=f(rl),
                total_duration_h=float(np.sum(dur)) / 3600.0 if dur else np.nan,
                co2_kg=float(np.sum(co2)) / 1e6 if co2 else np.nan,
                fuel_l=float(np.sum(fuel)) / 1e6 / 0.74 if fuel else np.nan)


def read_summary(path):
    if not os.path.exists(path):
        return dict()
    root = ET.parse(path).getroot()
    steps = root.findall("step")
    if not steps:
        return dict()
    last = steps[-1]
    run_series = [(float(s.get("time")), int(s.get("running"))) for s in steps]
    return dict(loaded=int(last.get("loaded")), inserted=int(last.get("inserted")),
                ended=int(last.get("ended")), running=int(last.get("running")),
                teleports=int(last.get("teleports")),
                collisions=int(last.get("collisions")),
                running_series=run_series)


def read_stats(path):
    if not os.path.exists(path):
        return dict()
    root = ET.parse(path).getroot()
    out = {}
    v = root.find("vehicles")
    if v is not None:
        out.update({k: int(x) for k, x in v.attrib.items()})
    tp = root.find("teleports")
    if tp is not None:
        out["teleports_total"] = int(tp.get("total"))
    return out


def count_collisions(path):
    if not os.path.exists(path):
        return 0
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return 0
    return len(root.findall("collision"))


# ------------------------------------------------------------------ TSTT
def tstt(rundir, pending_integral_vehs):
    """TSTT decomposition, vehicle-hours."""
    path = os.path.join(rundir, "edgedata.xml")
    cls = dict(freeway=0.0, ramp=0.0, detour=0.0, internal=0.0)
    tl_cls = dict(freeway=0.0, ramp=0.0, detour=0.0, internal=0.0)
    if os.path.exists(path):
        root = ET.parse(path).getroot()
        for iv in root.findall("interval"):
            for e in iv.findall("edge"):
                eid = e.get("id")
                ss = float(e.get("sampledSeconds") or 0.0)
                tl = float(e.get("timeLoss") or 0.0)
                if eid.startswith(":"):
                    k = "internal"
                elif eid in FREEWAY_EDGES:
                    k = "freeway"
                elif eid in RAMP_EDGES:
                    k = "ramp"
                elif eid in DETOUR_EDGES:
                    k = "detour"
                else:
                    k = "internal"
                cls[k] += ss
                tl_cls[k] += tl
    out = {f"vh_{k}": v / 3600.0 for k, v in cls.items()}
    out.update({f"tl_{k}": v / 3600.0 for k, v in tl_cls.items()})
    out["vh_origin"] = pending_integral_vehs / 3600.0
    out["TSTT_vh"] = sum(out[f"vh_{k}"] for k in
                         ("freeway", "ramp", "detour", "internal", "origin"))
    out["TSD_vh"] = sum(out[f"tl_{k}"] for k in
                        ("freeway", "ramp", "detour", "internal")) + out["vh_origin"]
    return out


# ------------------------------------------------------------------ emissions
def emissions(rundir):
    path = os.path.join(rundir, "emissions.xml")
    if not os.path.exists(path):
        return dict(CO2_kg=np.nan, fuel_l=np.nan, NOx_g=np.nan)
    root = ET.parse(path).getroot()
    co2 = nox = fuel = 0.0
    for iv in root.findall("interval"):
        for e in iv.findall("edge"):
            co2 += float(e.get("CO2_abs") or 0.0)
            nox += float(e.get("NOx_abs") or 0.0)
            fuel += float(e.get("fuel_abs") or 0.0)
    # HBEFA3 `fuel_abs` in edgeData/tripinfo is in MILLIGRAMS (SUMO >=1.14).
    # litres = mg / 1e6 (-> kg) / 0.74 (petrol density kg/L).
    return dict(CO2_kg=co2 / 1e6, NOx_g=nox / 1e3, fuel_l=fuel / 1e6 / 0.74)


# ------------------------------------------------------------------ diversion
def diversion_counts(rundir):
    e1 = read_e1(os.path.join(rundir, "e1_ramp.xml"))
    off = sum(r["n"] for r in e1 if r["id"] == "det_rOFF")
    on = sum(r["n"] for r in e1 if r["id"] == "det_rON")
    return dict(n_offramp=off, n_onramp=on)


# ------------------------------------------------------------------ roll-up
def summarize(rundir, n_open_lanes):
    meta = json.load(open(os.path.join(rundir, "meta.json")))
    d = dict(rundir=rundir)
    d.update({f"meta_{k}": v for k, v in meta.items() if k != "params"})
    d.update(discharge_capacity(rundir, n_open_lanes))
    d.update(sustained_capacity(rundir, n_open_lanes))
    d.update(read_tripinfo(os.path.join(rundir, "tripinfo.xml")))
    s = read_summary(os.path.join(rundir, "summary.xml"))
    d.update({k: v for k, v in s.items() if k != "running_series"})
    d.update(read_stats(os.path.join(rundir, "stats.xml")))
    d["n_collisions"] = count_collisions(os.path.join(rundir, "collisions.xml"))
    d.update(tstt(rundir, meta["pending_integral_vehs"]))
    d.update(emissions(rundir))
    d.update(diversion_counts(rundir))
    d["n_open_lanes"] = n_open_lanes
    return d


def running_freeze(rundir, tail_frac=0.25, tol=0):
    """Teleport-artifact guard: did the running-vehicle count freeze in the tail?"""
    s = read_summary(os.path.join(rundir, "summary.xml"))
    ser = s.get("running_series") or []
    if len(ser) < 20:
        return False
    tail = ser[int(len(ser) * (1 - tail_frac)):]
    vals = [v for _, v in tail]
    return (max(vals) - min(vals) <= tol) and vals[-1] > 0
