#!/usr/bin/env python3
"""
Analysis for the driveway-signalization TIA.

Produces (all under outputs/tables/):
  warrant_worksheet.csv        one row per (scenario, volume basis, hour)
  warrant_summary.csv          which warrants are met, per scenario / basis / column
  demand_vs_served.csv         nominal vs generated vs inserted vs stop-bar counts
  los_queue_table.csv          TWSC vs signal vs non-signal mitigation
  network_totals.csv           vehicle-hours, teleports, collisions, validity flags
  seed_variability.csv         mean / sd / CV over the 3 seeds
  freeflow_datum.csv           the measured control-delay reference

Every number traces to a raw SUMO output file in outputs/runs/<run>/.
"""
import csv
import glob
import gzip
import json
import math
import os
import statistics
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import RUNS, SCEN, TABLES, N_HOURS, HOUR, hour_label
import mutcd_warrants as W

SEEDS = [11, 23, 37]
SCEN_LIST = ["nobuild", "build", "build_high"]
CONTROLS = ["twsc", "sig_fixed", "sig_act", "twsc_rt", "twsc_riro"]

APPROACH_OF = {"EBT": "EB", "EBR": "EB", "EBL": "EB",
               "WBT": "WB", "WBR": "WB", "WBL": "WB",
               "DWL": "DW", "DWR": "DW", "SBL": "MN", "SBR": "MN"}
MAJOR_APPR = ("EB", "WB")

# HCM LOS thresholds -- DIFFERENT for signalised and unsignalised control
LOS_SIGNAL = [(10, "A"), (20, "B"), (35, "C"), (55, "D"), (80, "E")]
LOS_UNSIG = [(10, "A"), (15, "B"), (25, "C"), (35, "D"), (50, "E")]


def los(delay, signalised):
    tbl = LOS_SIGNAL if signalised else LOS_UNSIG
    for t, l in tbl:
        if delay <= t:
            return l
    return "F"


def rundir(scen, ctrl, seed):
    return os.path.join(RUNS, f"{scen}__{ctrl}__s{seed}")


# ------------------------------------------------------------------ parsers
def parse_e1(d):
    """-> {hour: {approach: count}} using stop-bar loops only."""
    out = {}
    for iv in ET.parse(os.path.join(d, "e1_stopbar.xml")).getroot().findall("interval"):
        h = int(float(iv.get("begin")) // HOUR)
        appr = iv.get("id").split("_")[1]
        out.setdefault(h, {}).setdefault(appr, 0)
        out[h][appr] += int(iv.get("nVehContrib"))
    return out


def parse_e2(d):
    """-> {detector: {hour: [maxJamLengthInMeters per 60 s]}}"""
    out = {}
    for iv in ET.parse(os.path.join(d, "e2_queue.xml")).getroot().findall("interval"):
        h = int(float(iv.get("begin")) // HOUR)
        out.setdefault(iv.get("id"), {}).setdefault(h, []).append(
            float(iv.get("maxJamLengthInMeters")))
    return out


def parse_e3(d):
    """-> {movement: {hour: (meanTravelTime, vehicleSum, meanTimeLoss)}}"""
    out = {}
    for iv in ET.parse(os.path.join(d, "e3_movement.xml")).getroot().findall("interval"):
        h = int(float(iv.get("begin")) // HOUR)
        mv = iv.get("id")[3:]
        n = int(iv.get("vehicleSum"))
        tt = float(iv.get("meanTravelTime"))
        tl = float(iv.get("meanTimeLoss"))
        out.setdefault(mv, {})[h] = (tt, n, tl)
    return out


def parse_tripinfo(d):
    """Per-vehicle records keyed by movement.  intended depart = depart - departDelay."""
    p = os.path.join(d, "tripinfo.xml.gz")
    f = gzip.open(p, "rt")
    recs = []
    for _, el in ET.iterparse(f, events=("end",)):
        if el.tag != "tripinfo":
            continue
        vid = el.get("id")
        mv = vid.split("_")[1]
        dep = float(el.get("depart"))
        dd = float(el.get("departDelay"))
        recs.append({"mv": mv, "depart": dep, "departDelay": dd,
                     "intended": dep - dd,
                     "duration": float(el.get("duration")),
                     "timeLoss": float(el.get("timeLoss")),
                     "waitingTime": float(el.get("waitingTime")),
                     "routeLength": float(el.get("routeLength")),
                     "arrival": float(el.get("arrival"))})
        el.clear()
    f.close()
    return recs


def parse_statistics(d):
    root = ET.parse(os.path.join(d, "statistics.xml")).getroot()
    veh = root.find("vehicles")
    tel = root.find("teleports")
    saf = root.find("safety")
    ts = root.find("vehicleTripStatistics")
    return {"loaded": int(veh.get("loaded")), "inserted": int(veh.get("inserted")),
            "running": int(veh.get("running")), "waiting": int(veh.get("waiting")),
            "teleports": int(tel.get("total")), "collisions": int(saf.get("collisions")),
            "emergencyStops": int(saf.get("emergencyStops")),
            "count": int(ts.get("count")),
            "totalTravelTime": float(ts.get("totalTravelTime")),
            "totalDepartDelay": float(ts.get("totalDepartDelay")),
            "meanTimeLoss": float(ts.get("timeLoss")),
            "meanDuration": float(ts.get("duration"))}


# ------------------------------------------------------- free-flow datum
def freeflow_datum():
    """Minimum hourly mean e3 travel time (over hours with >=10 samples) from the
    2%-... 10%-demand runs -- the 'travel time in the absence of the control'
    that HCM control delay is defined against.  Measured, never geometric."""
    out = {}
    for ctrl, variant in (("twsc", "std"), ("twsc_rt", "rt"), ("twsc_riro", "riro")):
        cands = {}
        for tag in ("a", "b"):
            e3 = parse_e3(os.path.join(RUNS, f"freeflow{tag}__{ctrl}"))
            for mv, hv in e3.items():
                for h, (tt, n, tl) in hv.items():
                    if n >= 5 and tt > 0:
                        cands.setdefault(mv, []).append(tt)
        for mv, v in cands.items():
            out.setdefault(variant, {})[mv] = min(v)
    return out


CTRL_VARIANT = {"twsc": "std", "sig_fixed": "std", "sig_act": "std",
                "twsc_rt": "rt", "twsc_riro": "riro"}


# ------------------------------------------------------------- warrant part
def volumes_from_detectors(d):
    e1 = parse_e1(d)
    rows = []
    for h in range(N_HOURS):
        x = e1.get(h, {})
        major = x.get("EB", 0) + x.get("WB", 0)
        dw, mn = x.get("DW", 0), x.get("MN", 0)
        rows.append({"hour": hour_label(h), "h": h, "major": major,
                     "driveway": dw, "minor_street": mn,
                     "minor": max(dw, mn),
                     "minor_which": "driveway" if dw >= mn else "minor_street",
                     "total_entering": major + dw + mn})
    return rows


def volumes_from_demand(scen, man):
    rows = []
    for h in range(N_HOURS):
        t = man["scenarios"][scen]["hourly"][h]
        rows.append({"hour": t["hour"], "h": h,
                     "major": t["major_total_entering"],
                     "driveway": t["driveway_approach"],
                     "minor_street": t["minor_street_approach"],
                     "minor": t["higher_minor_approach"],
                     "minor_which": ("driveway" if t["driveway_approach"] >=
                                     t["minor_street_approach"] else "minor_street"),
                     "total_entering": (t["major_total_entering"] +
                                        t["driveway_approach"] +
                                        t["minor_street_approach"])})
    return rows


def volumes_from_generated(recs, key):
    """key='intended' (realised stochastic demand) or 'depart' (inserted)."""
    rows = []
    for h in range(N_HOURS):
        lo, hi = h * HOUR, (h + 1) * HOUR
        c = {"EB": 0, "WB": 0, "DW": 0, "MN": 0}
        for r in recs:
            if lo <= r[key] < hi:
                c[APPROACH_OF[r["mv"]]] += 1
        major = c["EB"] + c["WB"]
        rows.append({"hour": hour_label(h), "h": h, "major": major,
                     "driveway": c["DW"], "minor_street": c["MN"],
                     "minor": max(c["DW"], c["MN"]),
                     "minor_which": "driveway" if c["DW"] >= c["MN"] else "minor_street",
                     "total_entering": major + c["DW"] + c["MN"]})
    return rows


def minor_delay_veh_hours(recs, d, appr="DW"):
    """Stopped-time delay in vehicle-hours on the given minor approach, per hour.
    Uses tripinfo waitingTime (stopped delay) for vehicles of that approach,
    attributed to the hour of their INTENDED departure, plus the insertion
    (departDelay) backlog, which is delay the vehicle really experiences even
    though no detector on the approach can see it."""
    out = []
    for h in range(N_HOURS):
        lo, hi = h * HOUR, (h + 1) * HOUR
        w = dd = 0.0
        for r in recs:
            if APPROACH_OF[r["mv"]] != appr:
                continue
            if lo <= r["intended"] < hi:
                w += r["waitingTime"]
                dd += r["departDelay"]
        out.append({"h": h, "waiting_veh_h": w / 3600.0,
                    "departdelay_veh_h": dd / 3600.0})
    return out


def main():
    man = json.load(open(os.path.join(SCEN, "demand", "demand_manifest.json")))
    ff = freeflow_datum()
    os.makedirs(TABLES, exist_ok=True)

    # ---------------------------------------------------------- free-flow table
    with open(os.path.join(TABLES, "freeflow_datum.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["route_variant", "movement", "freeflow_segment_travel_time_s"])
        for v in ff:
            for mv in sorted(ff[v]):
                w.writerow([v, mv, f"{ff[v][mv]:.2f}" if ff[v][mv] else ""])

    # ============================================================ WARRANTS
    ww_rows, ws_rows = [], []
    dvs_rows = []
    w3a_rows = []
    for scen in SCEN_LIST:
        # detector basis: use seed 11 as the primary, and report the spread
        bases = {}
        bases["demand_nominal"] = volumes_from_demand(scen, man)
        recs_by_seed = {s: parse_tripinfo(rundir(scen, "twsc", s)) for s in SEEDS}
        bases["demand_generated"] = volumes_from_generated(recs_by_seed[11], "intended")
        bases["inserted"] = volumes_from_generated(recs_by_seed[11], "depart")
        bases["detector_stopbar"] = volumes_from_detectors(rundir(scen, "twsc", 11))

        for basis, rows in bases.items():
            for pct, colname in ((100, "standard_100pct"), (70, "reduced_70pct")):
                ev = W.evaluate_hours(rows, "2+", "1", pct)
                summ = W.summarise(ev)
                ws_rows.append(dict(scenario=scen, basis=basis, column=colname, **summ))
                if pct == 100:
                    for r in ev:
                        ww_rows.append({
                            "scenario": scen, "basis": basis, "hour": r["hour"],
                            "major_total_vph": round(r["major"], 1),
                            "driveway_vph": round(r["driveway"], 1),
                            "minor_street_vph": round(r["minor_street"], 1),
                            "minor_higher_vph": round(r["minor"], 1),
                            "minor_higher_is": r["minor_which"],
                            "W1A_thr_major": r["W1A_thr_major"],
                            "W1A_thr_minor": r["W1A_thr_minor"],
                            "W1A_pass": r["W1A_pass"],
                            "W1B_thr_major": r["W1B_thr_major"],
                            "W1B_thr_minor": r["W1B_thr_minor"],
                            "W1B_pass": r["W1B_pass"],
                            "W1_combo80_pass": r["W1A80_pass"] and r["W1B80_pass"],
                            "W2_thr_minor": round(r["W2_thr_minor"], 1),
                            "W2_pass": r["W2_pass"], "W2_margin": round(r["W2_margin"], 3),
                            "W3_thr_minor": round(r["W3_thr_minor"], 1),
                            "W3_pass": r["W3_pass"], "W3_margin": round(r["W3_margin"], 3),
                        })
        # ------------------- demand vs served (the metering trap)
        e1 = parse_e1(rundir(scen, "twsc", 11))
        md = minor_delay_veh_hours(recs_by_seed[11], rundir(scen, "twsc", 11), "DW")
        for h in range(N_HOURS):
            nom = bases["demand_nominal"][h]
            gen = bases["demand_generated"][h]
            ins = bases["inserted"][h]
            det = bases["detector_stopbar"][h]
            dvs_rows.append({
                "scenario": scen, "hour": hour_label(h),
                "driveway_nominal_vph": round(nom["driveway"], 1),
                "driveway_generated_vph": gen["driveway"],
                "driveway_inserted_vph": ins["driveway"],
                "driveway_stopbar_vph": det["driveway"],
                "served_over_generated": (round(det["driveway"] / gen["driveway"], 3)
                                          if gen["driveway"] else ""),
                "inserted_over_generated": (round(ins["driveway"] / gen["driveway"], 3)
                                            if gen["driveway"] else ""),
                "minor_higher_nominal": round(nom["minor"], 1),
                "minor_higher_detector": det["minor"],
                "major_nominal": round(nom["major"], 1),
                "major_detector": det["major"],
                "driveway_waiting_veh_h": round(md[h]["waiting_veh_h"], 2),
                "driveway_departdelay_veh_h": round(md[h]["departdelay_veh_h"], 2),
            })
            w3a_rows.append({"scenario": scen, "hour": hour_label(h),
                             "minor": det["minor"],
                             "minor_delay_veh_h": md[h]["waiting_veh_h"],
                             "total_entering": det["total_entering"]})

    def dump(name, rows):
        if not rows:
            return
        with open(os.path.join(TABLES, name), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print("[analyze] wrote", name, f"({len(rows)} rows)")

    dump("warrant_worksheet.csv", ww_rows)
    dump("warrant_summary.csv", ws_rows)
    dump("demand_vs_served.csv", dvs_rows)

    # Warrant 3 Condition A (three-part test), on the detector basis
    w3a_out = []
    for scen in SCEN_LIST:
        rr = [r for r in w3a_rows if r["scenario"] == scen]
        for r in W.w3_condition_a(rr, "1", 4):
            pass
        for src, res in zip(rr, W.w3_condition_a(rr, "1", 4)):
            w3a_out.append({"scenario": scen, "hour": src["hour"],
                            "minor_vph_detector": src["minor"],
                            "minor_stopped_delay_veh_h": round(src["minor_delay_veh_h"], 2),
                            "total_entering_detector": src["total_entering"],
                            "delay_ge_4vehh": res["delay_ok"],
                            "vol_ge_100vph": res["volume_ok"],
                            "entering_ge_800vph": res["entering_ok"],
                            "W3_conditionA_all_three": res["all_three"]})
    dump("warrant3_conditionA.csv", w3a_out)

    # ======================================================= LOS / QUEUE / TOTALS
    los_rows, tot_rows, var_rows = [], [], []
    for scen in ["nobuild", "build", "build_high"]:
        for ctrl in (["twsc", "sig_fixed", "sig_act"] if scen == "nobuild" else CONTROLS):
            variant = CTRL_VARIANT[ctrl]
            signalised = ctrl.startswith("sig")
            per_seed = []
            for seed in SEEDS:
                d = rundir(scen, ctrl, seed)
                st = parse_statistics(d)
                e3 = parse_e3(d)
                e2 = parse_e2(d)
                recs = parse_tripinfo(d)
                # ---- PM peak design hour (17:00-18:00) approach performance
                H = 10
                appr_delay, appr_vol = {}, {}
                for mv, hv in e3.items():
                    if H not in hv:
                        continue
                    tt, n, tl = hv[H]
                    if n <= 0 or tt <= 0:
                        continue
                    base = ff[variant].get(mv)
                    if base is None:
                        continue
                    a = APPROACH_OF[mv]
                    appr_delay.setdefault(a, 0.0)
                    appr_vol.setdefault(a, 0)
                    appr_delay[a] += (tt - base) * n
                    appr_vol[a] += n
                inter_num = sum(appr_delay.values())
                inter_den = sum(appr_vol.values())
                # ---- queues (95th percentile of per-60 s max jam length in the hour)
                def q95(det):
                    v = sorted(e2.get(det, {}).get(H, []))
                    if not v:
                        return 0.0
                    k = min(len(v) - 1, int(math.ceil(0.95 * len(v))) - 1)
                    return v[k]
                # ---- whole-trip totals over the whole 12 h + drain
                vh_travel = sum(r["duration"] for r in recs) / 3600.0
                vh_timeloss = sum(r["timeLoss"] for r in recs) / 3600.0
                vh_departdelay = sum(r["departDelay"] for r in recs) / 3600.0
                # peak INSERTION BACKLOG on the driveway approach: vehicles whose
                # intended departure has passed but which SUMO could not yet insert
                # because the 250 m driveway approach was physically full.  This is
                # the queue that lies inside the site, invisible to every detector.
                ev = []
                for r in recs:
                    if APPROACH_OF[r["mv"]] == "DW":
                        ev.append((r["intended"], 1)); ev.append((r["depart"], -1))
                ev.sort()
                cur = peak = 0
                for _, dlt in ev:
                    cur += dlt
                    peak = max(peak, cur)
                # major-street through travel time over the fixed 350 m segment
                mt = {}
                for mv in ("EBT", "WBT"):
                    hv = e3.get(mv, {})
                    tt, n, tl = hv.get(H, (0, 0, 0))
                    mt[mv] = tt
                per_seed.append({
                    "seed": seed, "stats": st,
                    "appr_delay": {a: appr_delay[a] / appr_vol[a] for a in appr_delay},
                    "appr_vol": appr_vol,
                    "inter_delay": inter_num / inter_den if inter_den else float("nan"),
                    "q95": {k: q95(k) for k in ("q_EBL_bay", "q_EBT", "q_WBL_bay",
                                                "q_WBT", "q_DW", "q_MIN", "q_DW_L")},
                    "vh_travel": vh_travel, "vh_timeloss": vh_timeloss,
                    "vh_departdelay": vh_departdelay,
                    "EBT_tt": mt["EBT"], "WBT_tt": mt["WBT"],
                    "peak_driveway_backlog_veh": peak,
                })

            def ms(f):
                v = [f(p) for p in per_seed]
                v = [x for x in v if x == x]
                if not v:
                    return float("nan"), float("nan")
                return statistics.mean(v), (statistics.stdev(v) if len(v) > 1 else 0.0)

            for a in ("EB", "WB", "DW", "MN"):
                m, s = ms(lambda p: p["appr_delay"].get(a, float("nan")))
                mv_, sv = ms(lambda p: p["appr_vol"].get(a, float("nan")))
                has = m == m
                los_rows.append({
                    "scenario": scen, "control": ctrl, "approach": a,
                    "served_vph_pm_peak": round(mv_, 1) if mv_ == mv_ else "",
                    "control_delay_s_mean": round(m, 1) if has else "",
                    "control_delay_s_sd": round(s, 2) if has else "",
                    "LOS": los(m, signalised) if has else "n/a (no demand)",
                    "LOS_basis": "signalised" if signalised else "unsignalised",
                })
            m, s = ms(lambda p: p["inter_delay"])
            q = {k: ms(lambda p, k=k: p["q95"][k])[0] for k in per_seed[0]["q95"]}
            los_rows.append({
                "scenario": scen, "control": ctrl, "approach": "INTERSECTION",
                "served_vph_pm_peak": round(ms(lambda p: sum(p["appr_vol"].values()))[0], 1),
                "control_delay_s_mean": round(m, 1), "control_delay_s_sd": round(s, 2),
                "LOS": los(m, signalised),
                "LOS_basis": "signalised" if signalised else "unsignalised",
            })
            tot_rows.append({
                "scenario": scen, "control": ctrl,
                "veh_hours_travel": round(ms(lambda p: p["vh_travel"])[0], 1),
                "veh_hours_travel_sd": round(ms(lambda p: p["vh_travel"])[1], 2),
                "veh_hours_timeloss": round(ms(lambda p: p["vh_timeloss"])[0], 1),
                "veh_hours_insertion_backlog": round(ms(lambda p: p["vh_departdelay"])[0], 1),
                "veh_hours_total_delay": round(ms(lambda p: p["vh_timeloss"] +
                                                  p["vh_departdelay"])[0], 1),
                "veh_hours_total_delay_sd": round(ms(lambda p: p["vh_timeloss"] +
                                                     p["vh_departdelay"])[1], 2),
                "EBT_segment_tt_s_pm": round(ms(lambda p: p["EBT_tt"])[0], 2),
                "WBT_segment_tt_s_pm": round(ms(lambda p: p["WBT_tt"])[0], 2),
                "Q95_EBL_bay_m": round(q["q_EBL_bay"], 1),
                "Q95_driveway_m": round(q["q_DW"], 1),
                "Q95_driveway_leftlane_m": round(q["q_DW_L"], 1),
                "Q95_minor_street_m": round(q["q_MIN"], 1),
                "peak_driveway_insertion_backlog_veh":
                    round(ms(lambda p: p["peak_driveway_backlog_veh"])[0], 1),
                "equivalent_backlog_length_m":
                    round(ms(lambda p: p["peak_driveway_backlog_veh"])[0] * 7.5, 1),
                "Q95_EBT_m": round(q["q_EBT"], 1),
                "Q95_WBT_m": round(q["q_WBT"], 1),
                "loaded": per_seed[0]["stats"]["loaded"],
                "inserted_mean": round(ms(lambda p: p["stats"]["inserted"])[0], 1),
                "running_at_end": round(ms(lambda p: p["stats"]["running"])[0], 2),
                "teleports_mean": round(ms(lambda p: p["stats"]["teleports"])[0], 2),
                "teleports_max": max(p["stats"]["teleports"] for p in per_seed),
                "collisions_max": max(p["stats"]["collisions"] for p in per_seed),
            })
            for key, fn in (("veh_hours_total_delay",
                             lambda p: p["vh_timeloss"] + p["vh_departdelay"]),
                            ("intersection_control_delay_s", lambda p: p["inter_delay"]),
                            ("Q95_driveway_m", lambda p: p["q95"]["q_DW"])):
                m, s = ms(fn)
                var_rows.append({"scenario": scen, "control": ctrl, "metric": key,
                                 "mean": round(m, 3), "sd": round(s, 3),
                                 "cv_pct": round(100 * s / m, 2) if m else "",
                                 "n_seeds": len(per_seed),
                                 "values": ";".join(f"{fn(p):.3f}" for p in per_seed)})

    dump("los_queue_table.csv", los_rows)
    dump("network_totals.csv", tot_rows)
    dump("seed_variability.csv", var_rows)

    # ------------------------------------------- validity flags for every run
    val = []
    for d in sorted(glob.glob(os.path.join(RUNS, "*"))):
        if not os.path.isfile(os.path.join(d, "statistics.xml")):
            continue
        st = parse_statistics(d)
        val.append({"run": os.path.basename(d), **st,
                    "never_inserted": st["loaded"] - st["inserted"],
                    "teleport_share_pct": round(100 * st["teleports"] /
                                                max(1, st["inserted"]), 4)})
    dump("run_validity.csv", val)


if __name__ == "__main__":
    main()
