#!/usr/bin/env python3
"""
Turn one run directory into a single row of person-based and vehicle-based metrics.

Joins:  tripinfo.xml  x  <fleet>.fleet.csv (occupancy, VOT)  x  decisions.csv (toll paid,
eligibility, seconds observed on the managed lane)  x  summary.xml (teleports, running)
x  e1_exit.xml (per-lane exit flow)  x  sumo_stdout.log (insertion accounting).

Person-hours are reported BOTH in-network only and including departDelay (SUMO's insertion
backlog), because a managed lane that oversaturates the GP lanes pushes a large part of its
cost into the insertion queue where tripinfo's waitingTime cannot see it.
"""
import csv
import gzip
import io
import json
import math
import os
import re
import xml.etree.ElementTree as ET


def xopen(path):
    """Open path, transparently falling back to path + '.gz' (archived runs are gzipped)."""
    if os.path.exists(path):
        return open(path, "rb")
    if os.path.exists(path + ".gz"):
        return gzip.open(path + ".gz", "rb")
    raise FileNotFoundError(path)


def xexists(path):
    return os.path.exists(path) or os.path.exists(path + ".gz")


def xtext(path):
    with xopen(path) as f:
        return f.read().decode("utf-8", "replace")

PEAK_LO, PEAK_HI = 900.0, 3600.0        # window used for "peak person throughput"


def _f(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def vot_quartile_edges(fleet_csv):
    v = sorted(float(r["vot"]) for r in csv.DictReader(open(fleet_csv)))
    n = len(v)
    return [v[int(n * q)] for q in (0.25, 0.5, 0.75)]


def quartile(vot, edges):
    return 1 + sum(vot > e for e in edges)


def analyze(rundir, fleet_csv, qedges=None):
    rundir = os.path.abspath(rundir)
    fleet = {r["id"]: r for r in csv.DictReader(open(fleet_csv))}
    if qedges is None:
        qedges = vot_quartile_edges(fleet_csv)

    dec = {}
    dp = os.path.join(rundir, "decisions.csv")
    if xexists(dp):
        dec = {r["id"]: r for r in csv.DictReader(io.StringIO(xtext(dp)))}

    meta = {}
    mp = os.path.join(rundir, "run_meta.csv")
    if os.path.exists(mp):
        meta = {r["key"]: r["value"] for r in csv.DictReader(open(mp))}

    # ---------------- tripinfo -------------------------------------------------
    trips = []
    for _, el in ET.iterparse(xopen(os.path.join(rundir, "tripinfo.xml")), events=("end",)):
        if el.tag != "tripinfo":
            continue
        vid = el.get("id")
        f = fleet.get(vid)
        if f is not None:
            trips.append({
                "id": vid, "cls": f["cls"], "occ": int(f["occ"]), "vot": float(f["vot"]),
                "depart": _f(el.get("depart")), "arrival": _f(el.get("arrival")),
                "duration": _f(el.get("duration")), "timeLoss": _f(el.get("timeLoss")),
                "departDelay": _f(el.get("departDelay")), "routeLength": _f(el.get("routeLength")),
                "waitingTime": _f(el.get("waitingTime")),
                "paid": _f(dec.get(vid, {}).get("paid"), 0.0),
                "eligible": int(_f(dec.get(vid, {}).get("eligible"), 0)),
                "offered": int(_f(dec.get(vid, {}).get("offered"), 0)),
                "ml_s": _f(dec.get(vid, {}).get("ml_seconds"), 0.0),
                "est_saving_s": _f(dec.get(vid, {}).get("est_saving_s"), 0.0),
            })
        el.clear()

    # ---------------- summary (teleports, peak running) ------------------------
    teleports, max_running, last_running = 0, 0, 0
    inserted_sum, loaded_sum = 0, 0
    for _, el in ET.iterparse(xopen(os.path.join(rundir, "summary.xml")), events=("end",)):
        if el.tag != "step":
            continue
        teleports = max(teleports, int(_f(el.get("teleports"))))
        r = int(_f(el.get("running")))
        max_running = max(max_running, r)
        last_running = r
        inserted_sum = int(_f(el.get("inserted")))
        loaded_sum = int(_f(el.get("loaded")))
        el.clear()

    # ---------------- E1 exit loops (per-lane vehicle flow at x=7000) ----------
    lane_counts = {i: 0 for i in range(4)}
    lane_speed_num = {i: 0.0 for i in range(4)}
    e1 = os.path.join(rundir, "e1_exit.xml")
    if xexists(e1):
        for _, el in ET.iterparse(xopen(e1), events=("end",)):
            if el.tag != "interval":
                continue
            ln = int(el.get("id").split("_")[-1])
            n = _f(el.get("nVehContrib"))
            lane_counts[ln] += n
            lane_speed_num[ln] += n * _f(el.get("speed"), 0.0)
            el.clear()

    # ---------------- insertion accounting from SUMO's own stats ---------------
    log = ""
    lp = os.path.join(rundir, "sumo_stdout.log")
    if xexists(lp):
        log = xtext(lp)

    def gg(pat, d=float("nan")):
        m = re.search(pat, log)
        return float(m.group(1)) if m else d

    still = 0
    sp = os.path.join(rundir, "still_running.csv")
    if os.path.exists(sp):
        still = sum(1 for _ in csv.DictReader(open(sp)))

    # ---------------- aggregate -------------------------------------------------
    def agg(rows):
        if not rows:
            return dict(veh=0, persons=0, pht_h=0.0, pht_dd_h=0.0, phd_h=0.0,
                        mean_dur=float("nan"), mean_tl=float("nan"), mean_dd=float("nan"),
                        mean_speed=float("nan"), gc=float("nan"), paid=0.0)
        persons = sum(r["occ"] for r in rows)
        pht = sum(r["occ"] * r["duration"] for r in rows) / 3600.0
        pht_dd = sum(r["occ"] * (r["duration"] + r["departDelay"]) for r in rows) / 3600.0
        phd = sum(r["occ"] * (r["timeLoss"] + r["departDelay"]) for r in rows) / 3600.0
        # generalised cost per PERSON: own time cost + own share of the toll
        gc = sum(r["occ"] * (r["duration"] + r["departDelay"]) / 3600.0 * r["vot"] + r["paid"]
                 for r in rows) / max(1, persons)
        return dict(
            veh=len(rows), persons=persons, pht_h=pht, pht_dd_h=pht_dd, phd_h=phd,
            mean_dur=sum(r["duration"] for r in rows) / len(rows),
            mean_tl=sum(r["timeLoss"] for r in rows) / len(rows),
            mean_dd=sum(r["departDelay"] for r in rows) / len(rows),
            mean_speed=sum(r["routeLength"] for r in rows) / max(1e-9, sum(r["duration"] for r in rows)),
            gc=gc, paid=sum(r["paid"] for r in rows))

    out = {"run": os.path.basename(rundir), "dir": rundir}
    out.update({f"all_{k}": v for k, v in agg(trips).items()})

    peak = [r for r in trips if PEAK_LO <= r["arrival"] < PEAK_HI]
    out["peak_persons_per_h"] = sum(r["occ"] for r in peak) / ((PEAK_HI - PEAK_LO) / 3600.0)
    out["peak_veh_per_h"] = len(peak) / ((PEAK_HI - PEAK_LO) / 3600.0)
    out["peak_person_km_per_h"] = sum(r["occ"] * r["routeLength"] for r in peak) / 1000.0 / \
        ((PEAK_HI - PEAK_LO) / 3600.0)

    for cls in ("sov", "hov", "bus"):
        a = agg([r for r in trips if r["cls"] == cls])
        for k, v in a.items():
            out[f"{cls}_{k}"] = v

    # managed-lane users vs GP-only users (behavioural, from observed lane occupancy)
    mlu = [r for r in trips if r["ml_s"] > 0]
    gpo = [r for r in trips if r["ml_s"] == 0]
    for tag, rows in (("mluser", mlu), ("gponly", gpo)):
        for k, v in agg(rows).items():
            out[f"{tag}_{k}"] = v

    # take-rate / price elasticity inputs
    offers = [r for r in trips if r["offered"] == 1]
    buys = [r for r in offers if r["paid"] > 0 or r["eligible"] == 1]
    out["sov_offers"] = len(offers)
    out["sov_buys"] = len(buys)
    out["take_rate"] = len(buys) / len(offers) if offers else float("nan")
    out["revenue"] = _f(meta.get("revenue"), sum(r["paid"] for r in trips))
    out["toll_fixed"] = _f(meta.get("toll_fixed"))
    out["toll_final"] = _f(meta.get("toll_final"))
    out["arm"] = meta.get("arm", "?")
    out["seed"] = _f(meta.get("seed"))

    # VOT-quartile equity table
    for q in (1, 2, 3, 4):
        rows = [r for r in trips if quartile(r["vot"], qedges) == q]
        a = agg(rows)
        out[f"q{q}_persons"] = a["persons"]
        out[f"q{q}_gc"] = a["gc"]
        out[f"q{q}_mean_tt"] = a["mean_dur"] + a["mean_dd"]
        out[f"q{q}_paid"] = a["paid"]
        out[f"q{q}_pay_share"] = (sum(1 for r in rows if r["paid"] > 0) / len(rows)) if rows else float("nan")
        out[f"q{q}_ml_share"] = (sum(1 for r in rows if r["ml_s"] > 0) / len(rows)) if rows else float("nan")
    out["vot_q_edges"] = qedges

    # managed-lane exit flow (E1 at x=7000)
    dur_h = max(1e-9, (max((r["arrival"] for r in trips), default=1.0)) / 3600.0)
    out["exit_ml_veh"] = lane_counts[3]
    out["exit_gp_veh"] = sum(lane_counts[i] for i in range(3))
    out["exit_ml_speed"] = lane_speed_num[3] / lane_counts[3] if lane_counts[3] else float("nan")
    out["exit_gp_speed"] = (sum(lane_speed_num[i] for i in range(3)) /
                            max(1e-9, sum(lane_counts[i] for i in range(3))))

    # managed-lane vehicle throughput measured on the corridor itself:
    # vehicles that spent any time on lane 3, per hour of the peak window
    out["ml_veh_per_h_peak"] = sum(1 for r in peak if r["ml_s"] > 0) / ((PEAK_HI - PEAK_LO) / 3600.0)
    out["ml_persons_per_h_peak"] = sum(r["occ"] for r in peak if r["ml_s"] > 0) / ((PEAK_HI - PEAK_LO) / 3600.0)

    # accounting / validity
    out["fleet_size"] = len(fleet)
    out["completed"] = len(trips)
    out["still_running_at_end"] = still
    out["never_inserted"] = len(fleet) - inserted_sum
    out["inserted"] = inserted_sum
    out["loaded"] = loaded_sum
    out["teleports"] = teleports
    out["teleport_share_of_completed"] = teleports / max(1, len(trips))
    out["max_running"] = max_running
    out["last_running"] = last_running
    out["sumo_mean_speed"] = gg(r"\n Speed: ([\d.]+)")
    out["sumo_mean_departdelay"] = gg(r"DepartDelay: ([\d.]+)")
    out["time_to_teleport"] = _f(meta.get("time_to_teleport"), 300.0)

    # ---------------- laneData: per-lane flow/speed/density + lane changes -----
    ld = os.path.join(rundir, "lanedata.xml")
    if xexists(ld):
        acc = {}          # (edge, laneidx) -> dict of sums
        lc_by_edge = {}   # edge -> lane changes (from+to, peak window)
        for _, iv in ET.iterparse(xopen(ld), events=("end",)):
            if iv.tag != "interval":
                continue
            b, e_ = _f(iv.get("begin")), _f(iv.get("end"))
            inpeak = (b >= PEAK_LO and e_ <= PEAK_HI)
            for edge in iv:
                eid = edge.get("id")
                for lane in edge:
                    li = int(lane.get("id").split("_")[-1])
                    if inpeak:
                        d = acc.setdefault((eid, li), dict(ss=0.0, tt_num=0.0, dens=0.0,
                                                           occ=0.0, flow=0.0, n=0, lcf=0.0, lct=0.0))
                        d["ss"] += _f(lane.get("sampledSeconds"))
                        d["dens"] += _f(lane.get("density"))
                        d["occ"] += _f(lane.get("occupancy"))
                        d["flow"] += _f(lane.get("flow"))
                        d["tt_num"] += _f(lane.get("speed")) * _f(lane.get("sampledSeconds"))
                        d["lcf"] += _f(lane.get("laneChangedFrom"))
                        d["lct"] += _f(lane.get("laneChangedTo"))
                        d["n"] += 1
                        lc_by_edge[eid] = lc_by_edge.get(eid, 0.0) + _f(lane.get("laneChangedFrom"))
            iv.clear()
        for eid in ("m5", "m11"):
            for li in range(4):
                d = acc.get((eid, li))
                if not d or d["n"] == 0:
                    continue
                tag = f"ld_{eid}_l{li}"
                out[tag + "_flow"] = d["flow"] / d["n"]
                out[tag + "_speed"] = d["tt_num"] / max(1e-9, d["ss"])
                out[tag + "_density"] = d["dens"] / d["n"]
                out[tag + "_occ"] = d["occ"] / d["n"]
            gp = [acc.get((eid, li)) for li in range(3)]
            gp = [g for g in gp if g and g["n"]]
            if gp:
                out[f"ld_{eid}_gp_flow"] = sum(g["flow"] / g["n"] for g in gp)
                out[f"ld_{eid}_gp_speed"] = sum(g["tt_num"] for g in gp) / max(1e-9, sum(g["ss"] for g in gp))
                out[f"ld_{eid}_gp_density"] = sum(g["dens"] / g["n"] for g in gp) / len(gp)
        out["lc_total_peak"] = sum(lc_by_edge.get(f"m{i}", 0.0) for i in range(1, 15))
        out["lc_by_edge_peak"] = {f"m{i}": lc_by_edge.get(f"m{i}", 0.0) for i in range(1, 15)}

    # ALINEA / toll time series summary
    tl = os.path.join(rundir, "toll_log.csv")
    if os.path.exists(tl):
        rows = list(csv.DictReader(open(tl)))
        peakrows = [r for r in rows if PEAK_LO <= float(r["time"]) < PEAK_HI]
        if peakrows:
            out["ml_occ_peak_mean"] = sum(float(r["ml_occ_pct"]) for r in peakrows) / len(peakrows)
            out["ml_speed_peak_mean"] = sum(float(r["ml_speed_mps"]) for r in peakrows) / len(peakrows)
            out["ml_speed_peak_min"] = min(float(r["ml_speed_mps"]) for r in peakrows)
            out["toll_peak_mean"] = sum(float(r["toll"]) for r in peakrows) / len(peakrows)
            out["est_saving_peak_mean"] = sum(float(r["est_saving_s"]) for r in peakrows) / len(peakrows)
            out["ml_speed_ge_45mph_share"] = sum(
                1 for r in peakrows if float(r["ml_speed_mps"]) >= 20.12) / len(peakrows)
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--rundir", required=True)
    ap.add_argument("--fleet", required=True)
    a = ap.parse_args()
    print(json.dumps(analyze(a.rundir, a.fleet), indent=2, default=str))
