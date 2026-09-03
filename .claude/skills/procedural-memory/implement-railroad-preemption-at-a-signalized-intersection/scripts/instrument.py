#!/usr/bin/env python3
"""
STEP 2 -- INSTRUMENTATION FIRST.

Establishes and writes to disk how the two quantities the preemption logic
depends on can actually be observed at runtime:

(a) GATE STATE. Is the rail_crossing junction "X" exposed as a TraCI traffic
    light?  What is its program and what do its state strings look like as a
    train approaches / clears?  What is the fallback (direct train detection
    on the rail approach via traci.vehicle / traci.edge)?

(b) TRACK OCCUPANCY. Road vehicles whose PHYSICAL EXTENT overlaps the crossing
    footprint at a given instant, from polled positions -- NOT inferred from
    queue length.  Two envelope definitions are recorded side by side so the
    difference between "standing ON the tracks" and "waiting AT the gate" is
    explicit and auditable.

Writes outputs/instrumentation/{instrumentation_report.json,
gate_state_timeline.csv}.
"""
import csv
import json
import os
import sys

sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import traci  # noqa: E402
import common as C  # noqa: E402

OUT = os.path.join(C.ROOT, "outputs", "instrumentation")
os.makedirs(OUT, exist_ok=True)


def main():
    cfg = [
        "sumo", "-n", C.NET_FILE,
        "-r", os.path.join(C.NET_DIR, "demand_eb600_h300.rou.xml"),
        "--begin", "0", "--end", "1500", "--step-length", "1",
        "--seed", "42", "--no-step-log", "true", "--time-to-teleport", "-1",
    ]
    traci.start(cfg)
    rep = {}
    ids = list(traci.trafficlight.getIDList())
    rep["traffic_light_id_list"] = ids
    rep["crossing_X_exposed_as_traci_trafficlight"] = "X" in ids
    rep["X_controlled_links"] = [[list(t) for t in g]
                                 for g in traci.trafficlight.getControlledLinks("X")]
    lg = traci.trafficlight.getAllProgramLogics("X")
    rep["X_program"] = [{"programID": p.programID, "type_code": p.type,
                         "phases": [{"duration": ph.duration, "state": ph.state}
                                    for ph in p.phases]} for p in lg]
    rep["X_rail_links_are_tls_controlled"] = any(
        "R" in l[0][0] or l[0][0].startswith("R")
        for l in rep["X_controlled_links"])
    rep["geometry"] = {
        "junction_X_footprint_x": [C.JX_LO, C.JX_HI],
        "junction_X_footprint_width_m": round(C.JX_HI - C.JX_LO, 3),
        "mutcd_margin_m": C.MUTCD_MARGIN,
        "mutcd_envelope_x": [round(C.ENV_LO, 3), round(C.ENV_HI, 3)],
        "stopbar_x": C.STOPBAR_X,
        "clear_storage_distance_m": round(C.CLEAR_STORAGE, 3),
        "storage_in_vehicles_at_7.5m": round(C.CLEAR_STORAGE / 7.5, 2),
        "min_overlap_to_count_m": C.MIN_OVERLAP,
    }

    rows, transitions, prev = [], [], None
    while traci.simulation.getTime() < 1500:
        traci.simulationStep()
        t = traci.simulation.getTime()
        st = traci.trafficlight.getRedYellowGreenState("X")
        tr = C.nearest_train(traci)
        occ_j = C.occupancy(traci)                                  # footprint
        occ_m = C.occupancy(traci, C.ENV_LO, C.ENV_HI)              # +MUTCD margin
        rows.append({
            "t": t, "X_state": st, "gate_down": int(C.gate_is_down(traci)),
            "J_state": traci.trafficlight.getRedYellowGreenState("J"),
            "J_phase": traci.trafficlight.getPhase("J"),
            "train": tr[0] if tr else "", "train_dist_m": round(tr[1], 2) if tr else "",
            "train_speed": round(tr[2], 2) if tr else "",
            "occ_footprint": len(occ_j), "occ_footprint_ids": " ".join(v for v, _, _ in occ_j),
            "occ_mutcd": len(occ_m), "occ_mutcd_ids": " ".join(v for v, _, _ in occ_m),
            "eb_halting_X_J": C.eb_queue(traci),
        })
        if st != prev:
            transitions.append({"t": t, "from": prev, "to": st,
                                "train": tr[0] if tr else None,
                                "train_dist_m": round(tr[1], 2) if tr else None,
                                "train_speed": round(tr[2], 2) if tr else None,
                                "implied_lead_time_s": round(tr[1] / tr[2], 2)
                                if tr and tr[2] > 0 else None})
            prev = st
    traci.close()

    rep["X_state_transitions"] = transitions
    rep["distinct_X_states"] = sorted({r["X_state"] for r in rows})
    # measure the gate-down lead time (state -> "rr") relative to train arrival
    leads = [tr["implied_lead_time_s"] for tr in transitions
             if tr["to"] == "rr" and tr["implied_lead_time_s"] is not None]
    rep["measured_gatedown_lead_times_s"] = leads
    rep["gate_down_intervals"] = []
    down = None
    for r in rows:
        if r["gate_down"] and down is None:
            down = r["t"]
        elif not r["gate_down"] and down is not None:
            rep["gate_down_intervals"].append([down, r["t"], r["t"] - down])
            down = None
    rep["occ_footprint_at_gatedown"] = [
        r["occ_footprint"] for r in rows
        if any(abs(r["t"] - iv[0]) < 1e-6 for iv in rep["gate_down_intervals"])]
    rep["occ_mutcd_at_gatedown"] = [
        r["occ_mutcd"] for r in rows
        if any(abs(r["t"] - iv[0]) < 1e-6 for iv in rep["gate_down_intervals"])]
    rep["max_occ_footprint_any_instant"] = max(r["occ_footprint"] for r in rows)

    with open(os.path.join(OUT, "gate_state_timeline.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(OUT, "instrumentation_report.json"), "w") as f:
        json.dump(rep, f, indent=2)
    print(json.dumps({k: v for k, v in rep.items() if k != "X_state_transitions"},
                     indent=2))


if __name__ == "__main__":
    main()
