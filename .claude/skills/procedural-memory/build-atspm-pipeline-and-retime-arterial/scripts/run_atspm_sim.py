#!/usr/bin/env python3
"""Run the arterial and write (a) a high-resolution ENUMERATED EVENT LOG that is
the SUMO analogue of an Indiana/ATSPM controller log, and (b) a completely
SEPARATE ground-truth file set that downstream ATSPM analysis is forbidden to read.

(a) EVENT LOG  outputs/logs/events_<tag>.csv
    columns: timestamp, signal_id, event_code, event_param
    Sub-second resolution (simulation step-length 0.1 s).

    Event codes (Indiana / ATSPM enumerated-event convention):
      1  Phase Begin Green            param = NEMA phase number
      4  Phase Gap Out                param = NEMA phase number   [derived]
      5  Phase Max Out                param = NEMA phase number   [derived]
      6  Phase Force Off              param = NEMA phase number   [derived]
      8  Phase Begin Yellow Clearance param = NEMA phase number
      10 Phase Begin Red Clearance    param = NEMA phase number
      81 Detector Off                 param = detector channel
      82 Detector On                  param = detector channel

    Codes 1/8/10/81/82 are OBSERVED directly from the controller's displayed
    state and detector presence. Codes 4/5/6 are DERIVED by comparing the
    realised green duration to the configured maxDur (a real controller emits
    them natively; we reconstruct them). No ATSPM measure computed downstream
    depends on 4/5/6 -- they are informational only.

    Phase green is detected from PROTECTED green ('G') only, never from the
    permissive 'g' used for J3's permissive left turns -- matching what a real
    controller logs (phase state, not link state).

(b) GROUND TRUTH (never read by atspm_analysis.py):
    outputs/logs/gt_queue_<tag>.csv  -- 1 Hz halting-vehicle count per approach
                                        movement group (the "queue output")
    outputs/logs/gt_veh_<tag>.csv    -- per vehicle per approach link: entry time,
                                        exit (stop-bar crossing) time, and the
                                        delta of SUMO's own timeLoss over that
                                        link = control delay for that movement
    outputs/logs/tripinfo_<tag>.xml, summary_<tag>.xml, stats_<tag>.xml,
    outputs/logs/edgedata_<tag>.xml
"""
import argparse
import csv
import os
import subprocess
import sys

sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import sumolib  # noqa: E402
import traci  # noqa: E402
import traci.constants as tc  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_signals import build_states, PHASE_ORDER, PHASE_LABEL  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))

STEP = 0.1
J = ["J0", "J1", "J2", "J3"]
NEIGH = {
    "J0": {"W": "AW", "E": "J1", "N": "N_J0", "S": "S_J0"},
    "J1": {"W": "J0", "E": "J2", "N": "N_J1", "S": "S_J1"},
    "J2": {"W": "J1", "E": "J3", "N": "N_J2", "S": "S_J2"},
    "J3": {"W": "J2", "E": "AE", "N": "N_J3", "S": "S_J3"},
}
APPROACH = {"EB": ("W", 6, 1), "WB": ("E", 2, 5), "SB": ("N", 8, 3), "NB": ("S", 4, 7)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--plan", required=True, help="timing plan JSON (for maxDur -> gap/max-out derivation)")
    ap.add_argument("--tls-add", required=True)
    ap.add_argument("--end", type=float, default=7800.0)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    import json
    plan = json.load(open(args.plan))
    net_f = os.path.join(ROOT, "outputs", "net", "arterial.net.xml")
    rou_f = os.path.join(ROOT, "outputs", "demand", "demand.rou.xml")
    det_f = os.path.join(ROOT, "outputs", "det", "detectors.add.xml")
    logs = os.path.join(ROOT, "outputs", "logs")
    os.makedirs(logs, exist_ok=True)

    # edgeData ground truth additional file
    ed_add = os.path.join(logs, f"edgedata_{args.tag}.add.xml")
    with open(ed_add, "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<additional>\n'
                f'  <edgeData id="ed" period="{plan["cycle"]}" '
                f'file="edgedata_{args.tag}.xml" excludeEmpty="true"/>\n</additional>\n')

    net = sumolib.net.readNet(net_f)
    # phase -> link indices, from geometry (same routine that built the plan)
    phase_links = {}
    for tls in net.getTrafficLights():
        jid = tls.getID()
        perm = plan["junctions"][jid].get("permissive_left", False)
        _, _, _, pl = build_states(tls, perm)
        phase_links[jid] = pl
    maxdur = {jid: {p: plan["junctions"][jid]["splits"][str(p)] - 5 for p in range(1, 9)}
              for jid in J}

    # detector config
    det_cfg = list(csv.DictReader(open(os.path.join(ROOT, "outputs", "det", "detector_config.csv"))))
    e2 = [(r["det_id"], r["signal_id"], int(r["channel"])) for r in det_cfg if r["sumo_type"] == "e2"]
    e1 = [(r["det_id"], r["signal_id"], int(r["channel"])) for r in det_cfg if r["sumo_type"] == "e1"]

    cmd = ["sumo", "-n", net_f, "-r", rou_f, "-a", f"{det_f},{args.tls_add},{ed_add}",
           "--step-length", str(STEP), "--end", str(args.end), "--seed", str(args.seed),
           "--no-step-log", "true", "--time-to-teleport", "300",
           "--tripinfo-output", os.path.join(logs, f"tripinfo_{args.tag}.xml"),
           "--summary-output", os.path.join(logs, f"summary_{args.tag}.xml"),
           "--statistic-output", os.path.join(logs, f"stats_{args.tag}.xml"),
           "--collision.action", "warn", "--default.speeddev", "0.0",
           "--error-log", os.path.join(logs, f"sumoerr_{args.tag}.txt")]
    traci.start(cmd)

    for did, _, _ in e2:
        traci.lanearea.subscribe(did, [tc.LAST_STEP_VEHICLE_NUMBER])
    for did, _, _ in e1:
        traci.inductionloop.subscribe(did, [tc.LAST_STEP_VEHICLE_NUMBER])
    for jid in J:
        traci.trafficlight.subscribe(jid, [tc.TL_RED_YELLOW_GREEN_STATE])

    # ---- ground-truth bookkeeping ----
    appr_edges = {}          # edge id -> (junction, dir)
    lane_groups = {}         # (junction,dir) -> {"T":[lanes], "L":[lanes]}
    for j in J:
        for d, (nk, _, _) in APPROACH.items():
            eid = f"{NEIGH[j][nk]}_{j}"
            appr_edges[eid] = (j, d)
            lanes = [l.getID() for l in net.getEdge(eid).getLanes()]
            lane_groups[(j, d)] = {"T": lanes[:-1], "L": [lanes[-1]]}

    ev = open(os.path.join(logs, f"events_{args.tag}.csv"), "w", newline="")
    evw = csv.writer(ev)
    evw.writerow(["timestamp", "signal_id", "event_code", "event_param"])
    qf = open(os.path.join(logs, f"gt_queue_{args.tag}.csv"), "w", newline="")
    qw = csv.writer(qf)
    qw.writerow(["t", "signal_id", "approach_dir", "group", "halting"])
    vf = open(os.path.join(logs, f"gt_veh_{args.tag}.csv"), "w", newline="")
    vw = csv.writer(vf)
    vw.writerow(["veh_id", "movement", "signal_id", "approach_dir", "t_enter", "t_cross_stopbar",
                 "link_timeloss_s"])

    det_state = {}
    ph_state = {j: {p: "R" for p in range(1, 9)} for j in J}
    ph_green_t0 = {j: {p: None for p in range(1, 9)} for j in J}
    onlink = {}    # (edge, veh) -> (t_enter, timeloss_enter)
    prev_on = {e: set() for e in appr_edges}

    t = 0.0
    n_steps = int(round(args.end / STEP))
    next_gt = 0.0
    for _ in range(n_steps):
        traci.simulationStep()
        t = round(t + STEP, 1)

        # ---------- (a) EVENT LOG ----------
        lares = traci.lanearea.getAllSubscriptionResults()
        e1res = traci.inductionloop.getAllSubscriptionResults()
        tlres = traci.trafficlight.getAllSubscriptionResults()

        for did, sig, chan in e2:
            occ = lares[did][tc.LAST_STEP_VEHICLE_NUMBER] > 0
            if occ != det_state.get(did, False):
                evw.writerow([f"{t:.1f}", sig, 82 if occ else 81, chan])
                det_state[did] = occ
        for did, sig, chan in e1:
            occ = e1res[did][tc.LAST_STEP_VEHICLE_NUMBER] > 0
            if occ != det_state.get(did, False):
                evw.writerow([f"{t:.1f}", sig, 82 if occ else 81, chan])
                det_state[did] = occ

        for jid in J:
            st = tlres[jid][tc.TL_RED_YELLOW_GREEN_STATE]
            for p in PHASE_ORDER:
                idxs = phase_links[jid][p]
                if not idxs:
                    continue
                has_G = any(st[i] == "G" for i in idxs)
                has_y = any(st[i] in "yY" for i in idxs)
                cur = ph_state[jid][p]
                if has_G and cur != "G":
                    evw.writerow([f"{t:.1f}", jid, 1, p])
                    ph_state[jid][p] = "G"
                    ph_green_t0[jid][p] = t
                elif cur == "G" and not has_G:
                    # green terminated -> classify, then begin yellow
                    dur = t - ph_green_t0[jid][p] if ph_green_t0[jid][p] is not None else 0.0
                    if p in (2, 6):
                        code = 6                       # coordinated -> force off
                    elif dur >= maxdur[jid][p] - 0.35:
                        code = 5                       # max out
                    else:
                        code = 4                       # gap out
                    evw.writerow([f"{t:.1f}", jid, code, p])
                    evw.writerow([f"{t:.1f}", jid, 8, p])
                    ph_state[jid][p] = "Y"
                elif cur == "Y" and not has_y and not has_G:
                    evw.writerow([f"{t:.1f}", jid, 10, p])
                    ph_state[jid][p] = "R"

        # ---------- (b) GROUND TRUTH, 1 Hz ----------
        if t >= next_gt - 1e-9:
            next_gt += 1.0
            for (j, d), grp in lane_groups.items():
                for g, lanes in grp.items():
                    h = sum(traci.lane.getLastStepHaltingNumber(l) for l in lanes)
                    qw.writerow([f"{t:.0f}", j, d, g, h])
            for eid, (j, d) in appr_edges.items():
                now = set(traci.edge.getLastStepVehicleIDs(eid))
                for v in now - prev_on[eid]:
                    try:
                        onlink[(eid, v)] = (t, traci.vehicle.getTimeLoss(v))
                    except traci.TraCIException:
                        pass
                for v in prev_on[eid] - now:
                    rec = onlink.pop((eid, v), None)
                    if rec is None:
                        continue
                    try:
                        tl = traci.vehicle.getTimeLoss(v) - rec[1]
                    except traci.TraCIException:
                        continue
                    vw.writerow([v, v.split(".")[0].rsplit("_", 1)[0] if "_" in v.split(".")[0]
                                 else v.split(".")[0], j, d, f"{rec[0]:.0f}", f"{t:.0f}", f"{tl:.2f}"])
                prev_on[eid] = now

    traci.close()
    ev.close(); qf.close(); vf.close()

    # ---- run health ----
    import xml.etree.ElementTree as ET
    st = ET.parse(os.path.join(logs, f"stats_{args.tag}.xml")).getroot()
    veh = st.find("vehicles"); tel = st.find("teleports"); saf = st.find("safety")
    print(f"\n=== run '{args.tag}' health ===")
    print(f"  vehicles loaded={veh.get('loaded')} inserted={veh.get('inserted')} "
          f"running={veh.get('running')} waiting(never inserted)={veh.get('waiting')}")
    print(f"  teleports total={tel.get('total')} jam={tel.get('jam')} yield={tel.get('yield')} "
          f"wrongLane={tel.get('wrongLane')}")
    print(f"  collisions={saf.get('collisions')} emergencyBraking={saf.get('emergencyBraking')}")
    n_ev = sum(1 for _ in open(os.path.join(logs, f"events_{args.tag}.csv"))) - 1
    print(f"  event-log rows = {n_ev}")


if __name__ == "__main__":
    main()
