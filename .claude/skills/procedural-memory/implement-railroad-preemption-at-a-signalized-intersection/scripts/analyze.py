#!/usr/bin/env python3
"""
Derive every reported number from the raw run outputs in outputs/runs/*/.

Writes into outputs/tables/:
  occupancy_by_cell.csv     track occupancy at gate-down, per cell
  delay_by_cell.csv         per-approach delay/queue cost, per cell
  design_curve.csv          minimum advance preemption time for zero occupancy
  ite_comparison.json       simulated vs. ITE closed-form decomposition
  failure_modes.json        short-APT and short-headway failure evidence
  per_event.csv             one row per gate-down event in every cell
"""
import csv
import json
import os
import statistics as st
import xml.etree.ElementTree as ET

import common as C

RUNS = os.path.join(C.ROOT, "outputs", "runs")
TAB = os.path.join(C.ROOT, "outputs", "tables")
os.makedirs(TAB, exist_ok=True)
FLOWS = {"f_eb": "EB_across_tracks", "f_wb": "WB_feeds_crossing",
         "f_nb": "NB_cross_street", "f_sb": "SB_cross_street"}


def load_cell(name):
    d = os.path.join(RUNS, name)
    out = {"name": name, "cfg": json.load(open(os.path.join(d, "config.json"))),
           "events": json.load(open(os.path.join(d, "events.json"))),
           "fsm": json.load(open(os.path.join(d, "fsm_log.json")))}
    with open(os.path.join(d, "timeseries.csv")) as f:
        out["ts"] = list(csv.DictReader(f))
    tri = {}
    for v in ET.parse(os.path.join(d, "tripinfo.xml")).getroot():
        fl = v.get("id").split(".")[0]
        if fl not in FLOWS:
            continue
        a = tri.setdefault(FLOWS[fl], {"n": 0, "timeLoss": 0.0, "waitingTime": 0.0,
                                       "duration": 0.0})
        a["n"] += 1
        a["timeLoss"] += float(v.get("timeLoss"))
        a["waitingTime"] += float(v.get("waitingTime"))
        a["duration"] += float(v.get("duration"))
    out["tripinfo"] = tri
    return out


def row_occ(c):
    ev = c["events"]
    occ = [e["occ_at_gate_down"] for e in ev]
    occs = [e["occ_stopped_at_gate_down"] for e in ev]
    trapped = [sum(e.get("trapped_durations_s", {}).values()) for e in ev]
    return {
        "cell": c["name"], "eb_vph": c["cfg"]["eb"], "headway_s": c["cfg"]["headway"],
        "preempt": c["cfg"]["preempt"], "apt_s": c["cfg"]["apt"],
        "n_gate_events": len(ev),
        "occ_at_gatedown_list": " ".join(str(x) for x in occ),
        "occ_mean": round(st.mean(occ), 3) if occ else "",
        "occ_max": max(occ) if occ else "",
        "n_events_with_occupancy": sum(1 for x in occ if x > 0),
        "occ_stopped_mean": round(st.mean(occs), 3) if occs else "",
        "trapped_veh_seconds_total": round(sum(trapped), 1),
        "trapped_veh_seconds_per_event": round(sum(trapped) / len(ev), 2) if ev else "",
        "max_trapped_duration_s": max(
            [max(e.get("trapped_durations_s", {}).values(), default=0) for e in ev],
            default=0),
        "mean_gate_down_duration_s": round(
            st.mean([e.get("gate_down_duration", 0) for e in ev]), 2) if ev else "",
    }


def row_delay(c):
    r = {"cell": c["name"], "eb_vph": c["cfg"]["eb"], "headway_s": c["cfg"]["headway"],
         "preempt": c["cfg"]["preempt"], "apt_s": c["cfg"]["apt"],
         "n_gate_events": len(c["events"])}
    for k, v in c["tripinfo"].items():
        r[f"{k}_n"] = v["n"]
        r[f"{k}_total_timeLoss_s"] = round(v["timeLoss"], 1)
        r[f"{k}_mean_timeLoss_s"] = round(v["timeLoss"] / v["n"], 2)
        r[f"{k}_total_waiting_s"] = round(v["waitingTime"], 1)
    for key in ("EB_across_tracks", "WB_feeds_crossing", "NB_cross_street",
                "SB_cross_street", "EB_upstream_of_crossing"):
        col = "q_" + key
        vals = [int(x[col]) for x in c["ts"] if col in x]
        r[f"maxq_{key}"] = max(vals) if vals else ""
    # per-gate-event max queue (from events.json max_q)
    for key in ("WB_feeds_crossing", "NB_cross_street", "SB_cross_street"):
        v = [e["max_q"][key] for e in c["events"]]
        r[f"event_maxq_{key}_mean"] = round(st.mean(v), 2) if v else ""
        r[f"event_maxq_{key}_max"] = max(v) if v else ""
    return r


def preempt_timing(c):
    """Right-of-way transfer time and queue-clearance time, measured."""
    fsm, ts = c["fsm"], c["ts"]
    tmap = {float(x["t"]): x for x in ts}
    out = []
    call = None
    for r in fsm:
        if r["state"] == "PREEMPT_CALL":
            call = r
        elif r["state"] == "TRACK_CLEAR" and call is not None:
            tc = r["t"]
            row = {"t_call": call["t"], "t_track_clear": tc,
                   "row_transfer_s": round(tc - call["t"], 2),
                   "ped_hold_s": call.get("ped_hold_remaining", 0.0),
                   "native_phase_at_call": call.get("native_phase"),
                   "spent_in_phase_at_call": call.get("spent_in_phase")}
            # queue standing on the EB approach at the call
            rec = tmap.get(call["t"])
            if rec:
                row["eb_halting_on_X_J_at_call"] = int(rec["q_EB_across_tracks"])
                row["occ_at_call"] = int(rec["occ"])
                row["queue_to_clear_veh"] = int(rec["q_EB_across_tracks"]) + int(rec["occ"])
            # time from track-clearance-green start until occupancy first hits 0
            t0 = None
            for x in ts:
                tt = float(x["t"])
                if tt >= tc and int(x["occ"]) == 0:
                    t0 = tt
                    break
            row["queue_clearance_s"] = round(t0 - tc, 2) if t0 is not None else None
            out.append(row)
            call = None
    return out


def main():
    names = sorted(d for d in os.listdir(RUNS) if os.path.isdir(os.path.join(RUNS, d)))
    cells = {n: load_cell(n) for n in names}

    occ_rows = [row_occ(c) for c in cells.values()]
    occ_rows.sort(key=lambda r: (r["headway_s"], r["eb_vph"], r["preempt"], r["apt_s"]))
    with open(os.path.join(TAB, "occupancy_by_cell.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(occ_rows[0].keys()))
        w.writeheader()
        w.writerows(occ_rows)

    del_rows = [row_delay(c) for c in cells.values()]
    del_rows.sort(key=lambda r: (r["headway_s"], r["eb_vph"], r["preempt"], r["apt_s"]))
    keys = sorted({k for r in del_rows for k in r})
    lead = ["cell", "eb_vph", "headway_s", "preempt", "apt_s", "n_gate_events"]
    keys = lead + [k for k in keys if k not in lead]
    with open(os.path.join(TAB, "delay_by_cell.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(del_rows)

    # ---- per-event table ---------------------------------------------------
    pe = []
    for n, c in cells.items():
        for i, e in enumerate(c["events"]):
            pe.append({"cell": n, "eb_vph": c["cfg"]["eb"], "headway_s": c["cfg"]["headway"],
                       "preempt": c["cfg"]["preempt"], "apt_s": c["cfg"]["apt"],
                       "event": i, "t_gate_down": e["t_gate_down"],
                       "gate_down_duration_s": e.get("gate_down_duration"),
                       "occ_at_gate_down": e["occ_at_gate_down"],
                       "occ_stopped_at_gate_down": e["occ_stopped_at_gate_down"],
                       "occ_mutcd_at_gate_down": e["occ_mutcd_at_gate_down"],
                       "ctrl_state_at_gate_down": e["ctrl_state_at_gate_down"],
                       "J_state_at_gate_down": e["J_state_at_gate_down"],
                       "achieved_advance_time_s": e.get("achieved_advance_time"),
                       "trapped_veh_seconds": round(
                           sum(e.get("trapped_durations_s", {}).values()), 1),
                       "n_veh_occupying_during_gate_down":
                           e.get("n_vehicles_that_occupied_during_gate_down"),
                       "maxq_WB": e["max_q"]["WB_feeds_crossing"],
                       "maxq_NB": e["max_q"]["NB_cross_street"],
                       "maxq_SB": e["max_q"]["SB_cross_street"],
                       "maxq_EB_X_J": e["max_q"]["EB_across_tracks"],
                       "maxq_EB_upstream": e["max_q"]["EB_upstream_of_crossing"]})
    with open(os.path.join(TAB, "per_event.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(pe[0].keys()))
        w.writeheader()
        w.writerows(pe)

    # ---- design curve ------------------------------------------------------
    curve = []
    for eb in sorted({c["cfg"]["eb"] for c in cells.values()}):
        base = cells.get(f"base_eb{eb}_h290")
        if base is None:
            continue
        bocc = [e["occ_at_gate_down"] for e in base["events"]]
        # the design queue that must be cleared: EB standing vehicles between
        # the crossing and the stop bar, plus those on the crossing, measured in
        # the BASELINE at each gate-down instant
        des = [e["q_at_gate_down"]["EB_across_tracks"] + e["occ_at_gate_down"]
               for e in base["events"]]
        rec = {"eb_vph": eb, "baseline_occ_mean": round(st.mean(bocc), 3),
               "baseline_occ_max": max(bocc),
               "baseline_events_with_occupancy": sum(1 for x in bocc if x > 0),
               "design_queue_veh_mean": round(st.mean(des), 2),
               "design_queue_veh_max": max(des)}
        apts = sorted({int(c["cfg"]["apt"]) for c in cells.values()
                       if c["cfg"]["preempt"] and c["cfg"]["headway"] == 290})
        maxocc = {}
        for apt in apts:
            c = cells.get(f"pre_eb{eb}_h290_apt{apt}")
            if c is None:
                continue
            o = [e["occ_at_gate_down"] for e in c["events"]]
            maxocc[apt] = max(o)
            rec[f"occ_max_apt{apt}"] = max(o)
            rec[f"occ_mean_apt{apt}"] = round(st.mean(o), 3)
        # The design value is the smallest advance time from which occupancy is
        # zero AND STAYS zero for every larger swept advance time -- a single
        # lucky zero at a short advance time is not a design point.
        req = None
        for apt in apts:
            if apt in maxocc and all(maxocc.get(a, 1) == 0 for a in apts if a >= apt):
                req = apt
                break
        rec["min_apt_for_zero_occupancy_s"] = req
        # measured components at the required APT (or the largest swept)
        c = cells.get(f"pre_eb{eb}_h290_apt{int(req) if req is not None else 30}")
        pt = preempt_timing(c)
        rec["measured_row_transfer_mean_s"] = round(st.mean([p["row_transfer_s"] for p in pt]), 2)
        rec["measured_row_transfer_max_s"] = max(p["row_transfer_s"] for p in pt)
        qc = [p["queue_clearance_s"] for p in pt if p["queue_clearance_s"] is not None]
        rec["measured_queue_clearance_mean_s"] = round(st.mean(qc), 2) if qc else None
        rec["measured_queue_clearance_max_s"] = max(qc) if qc else None
        rec["measured_queue_to_clear_mean_veh"] = round(
            st.mean([p["queue_to_clear_veh"] for p in pt if "queue_to_clear_veh" in p]), 2)
        curve.append(rec)
    keys = sorted({k for r in curve for k in r})
    lead = ["eb_vph", "design_queue_veh_mean", "design_queue_veh_max",
            "baseline_occ_mean", "baseline_occ_max", "baseline_events_with_occupancy",
            "min_apt_for_zero_occupancy_s"]
    keys = lead + [k for k in keys if k not in lead]
    with open(os.path.join(TAB, "design_curve.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(curve)

    # ---- ITE closed-form comparison ---------------------------------------
    sat = json.load(open(os.path.join(C.ROOT, "outputs", "saturation", "saturation.json")))
    h, l1 = sat["saturation_headway_s"], sat["startup_lost_time_s"]
    ite = {"inputs": {"saturation_headway_s": h, "startup_lost_time_s": l1,
                      "min_yellow_s": C.YELLOW_MIN, "min_allred_s": C.ALLRED_MIN,
                      "ped_walk_s": C.PED_WALK, "ped_fdw_s": C.PED_FDW,
                      "ped_min_total_s": C.PED_MIN_TOTAL,
                      "clear_storage_distance_m": round(C.CLEAR_STORAGE, 2),
                      "crossing_footprint_m": round(C.JX_HI - C.JX_LO, 2)},
           "cells": []}
    for r in curve:
        eb = r["eb_vph"]
        n = r["design_queue_veh_max"]
        row_worst = C.PED_MIN_TOTAL + C.YELLOW_MIN + C.ALLRED_MIN
        row_min = C.YELLOW_MIN + C.ALLRED_MIN
        qct = l1 + n * h
        ite["cells"].append({
            "eb_vph": eb,
            "design_queue_veh": n,
            "ite_row_transfer_worst_case_s": row_worst,
            "ite_row_transfer_best_case_s": row_min,
            "ite_queue_clearance_time_s": round(qct, 2),
            "ite_apt_required_worst_case_s": round(row_worst + qct, 2),
            "ite_apt_required_best_case_s": round(row_min + qct, 2),
            "simulated_min_apt_for_zero_occupancy_s": r["min_apt_for_zero_occupancy_s"],
            "measured_row_transfer_mean_s": r["measured_row_transfer_mean_s"],
            "measured_row_transfer_max_s": r["measured_row_transfer_max_s"],
            "measured_queue_clearance_mean_s": r["measured_queue_clearance_mean_s"],
            "measured_queue_clearance_max_s": r["measured_queue_clearance_max_s"],
        })
    with open(os.path.join(TAB, "ite_comparison.json"), "w") as f:
        json.dump(ite, f, indent=2)

    # ---- failure modes -----------------------------------------------------
    fm = {"too_short_advance_time": [], "short_headway_stability": {}}
    for eb in sorted({c["cfg"]["eb"] for c in cells.values() if c["cfg"]["headway"] == 290}):
        for apt in (0, 5, 10, 15, 20, 25, 30):
            c = cells.get(f"pre_eb{eb}_h290_apt{apt}")
            if not c:
                continue
            o = [e["occ_at_gate_down"] for e in c["events"]]
            tv = sum(sum(e.get("trapped_durations_s", {}).values()) for e in c["events"])
            fm["too_short_advance_time"].append(
                {"eb_vph": eb, "apt_s": apt, "occ_at_gatedown": o,
                 "events_with_trapped_vehicles": sum(1 for x in o if x > 0),
                 "trapped_veh_seconds": round(tv, 1),
                 "ctrl_states_at_gatedown":
                     [e["ctrl_state_at_gate_down"] for e in c["events"]]})
    for n, c in cells.items():
        if c["cfg"]["headway"] != 120:
            continue
        fsm = c["fsm"]
        calls = [r for r in fsm if r["state"] == "PREEMPT_CALL"]
        exits = [r for r in fsm if r["state"] == "EXIT_DONE"]
        # did the intersection ever return to the native cycle between events?
        normal_gaps = []
        for i in range(len(exits)):
            nxt = [x for x in calls if x["t"] > exits[i]["t"]]
            if nxt:
                normal_gaps.append(round(nxt[0]["t"] - exits[i]["t"], 1))
        ebq = [e["q_at_gate_down"]["EB_across_tracks"]
               + e["q_at_gate_down"]["EB_upstream_of_crossing"] for e in c["events"]]
        fm["short_headway_stability"][n] = {
            "eb_vph": c["cfg"]["eb"], "preempt": c["cfg"]["preempt"], "apt_s": c["cfg"]["apt"],
            "n_gate_events": len(c["events"]),
            "n_preempt_calls": len(calls), "n_completed_exits": len(exits),
            "normal_operation_gaps_s": normal_gaps,
            "min_normal_gap_s": min(normal_gaps) if normal_gaps else None,
            "eb_queue_at_successive_gatedowns": ebq,
            "eb_queue_first3_mean": round(st.mean(ebq[:3]), 2) if len(ebq) >= 3 else None,
            "eb_queue_last3_mean": round(st.mean(ebq[-3:]), 2) if len(ebq) >= 3 else None,
            "occ_at_gatedown": [e["occ_at_gate_down"] for e in c["events"]],
            "total_timeLoss_by_approach": {k: round(v["timeLoss"], 1)
                                           for k, v in c["tripinfo"].items()},
            "n_arrived_by_approach": {k: v["n"] for k, v in c["tripinfo"].items()},
        }
    with open(os.path.join(TAB, "failure_modes.json"), "w") as f:
        json.dump(fm, f, indent=2)

    # ---- gate-down prediction accuracy ------------------------------------
    pred = {}
    for n, c in cells.items():
        if not c["cfg"]["preempt"]:
            continue
        calls = [r for r in c["fsm"] if r["state"] == "PREEMPT_CALL"]
        errs, adv = [], []
        for e in c["events"]:
            cand = [r for r in calls if r["t"] <= e["t_gate_down"]]
            if not cand:
                continue
            r = cand[-1]
            errs.append(round(e["t_gate_down"] - r["predicted_gate_down"], 2))
            adv.append(round(e["t_gate_down"] - r["t"], 2))
        pred[n] = {"requested_apt_s": c["cfg"]["apt"],
                   "gate_down_prediction_error_s": errs,
                   "mean_prediction_error_s": round(st.mean(errs), 3) if errs else None,
                   "achieved_advance_time_s": adv,
                   "mean_achieved_advance_time_s": round(st.mean(adv), 2) if adv else None}
    with open(os.path.join(TAB, "gate_down_prediction.json"), "w") as f:
        json.dump(pred, f, indent=2)

    # ---- preempt-timing detail --------------------------------------------
    detail = {n: preempt_timing(c) for n, c in cells.items() if c["cfg"]["preempt"]}
    with open(os.path.join(TAB, "preempt_timing_detail.json"), "w") as f:
        json.dump(detail, f, indent=2)

    print(json.dumps({"cells": len(cells), "design_curve": curve}, indent=2))


if __name__ == "__main__":
    main()
