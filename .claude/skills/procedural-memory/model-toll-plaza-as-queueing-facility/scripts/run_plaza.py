#!/usr/bin/env python3
"""
Run one toll-plaza scenario.

Two execution modes:
  --controller none      plain `sumo -c plaza.sumocfg` (service stops come from the route file)
  --controller shortest  TraCI join-the-shortest-queue assigner: each arriving vehicle is
                         re-routed to the booth channel with the fewest vehicles queued, its
                         service stop is imposed with vehicle.setStop, and its lane-change
                         mode is set so the strategic change onto the correct mainline lane
                         is actually executed.
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.environ.get("SUMO_HOME", "") + "/tools")

import plaza_lib as P


def run_plain(cfg, seed):
    cmd = [P.find_bin("sumo"), "-c", cfg, "--seed", str(seed), "--no-warnings", "true"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, r.stderr


def run_traci(cfg, seed, meta, run_dir, decision_pos=600.0, assign="shortest"):
    import traci
    c = meta["booths"]
    svc = meta["svc"]
    booth_of = meta["booth_of"]
    half = c // 2

    q_lanes = {b: ["fan_%d" % b, "lock_%d" % b, "chin_%d_0" % b, "booth_%d_0" % b]
               for b in range(c)}
    all_q = sorted({l for v in q_lanes.values() for l in v})

    traci.start([P.find_bin("sumo"), "-c", cfg, "--seed", str(seed), "--no-warnings", "true"])
    for l in all_q:
        traci.lane.subscribe(l, [0x10, 0x11])          # LAST_STEP_VEHICLE_NUMBER, HALTING_NUMBER
    assigned = {}
    log = []
    rr = 0
    while traci.simulation.getMinExpectedNumber() > 0:
        traci.simulationStep()
        sub = traci.lane.getAllSubscriptionResults()
        qlen = {b: sum(sub[l][0x10] for l in q_lanes[b]) for b in range(c)}
        qhalt = {b: sum(sub[l][0x11] for l in q_lanes[b]) for b in range(c)}
        # vehicles already assigned to a booth but still upstream on `app` are committed
        # to that booth and MUST be counted, or the assigner repeatedly sends a whole
        # platoon to the same "shortest" booth on stale information.
        on_app = set(traci.edge.getLastStepVehicleIDs("app"))
        pend = {b: 0 for b in range(c)}
        for v2, b2 in assigned.items():
            if v2 in on_app:
                pend[b2] += 1
        for vid in traci.vehicle.getIDList():
            if vid in assigned:
                continue
            if traci.vehicle.getRoadID(vid) != "app":
                continue
            if traci.vehicle.getLanePosition(vid) < decision_pos:
                continue
            k = int(vid[1:])
            if assign == "shortest":
                # rotating tie-break so equal-length queues do not systematically favour
                # the lowest booth index
                off = rr % c
                rr += 1
                b = min(range(c), key=lambda j: (qlen[j] + pend[j], qhalt[j], (j - off) % c))
                pend[b] += 1
            elif assign == "roundrobin":
                b = rr % c
                rr += 1
            else:
                b = booth_of[k]
            traci.vehicle.setRoute(vid, ["app", "fan", "lock",
                                         "chin_%d" % b, "booth_%d" % b, "chout_%d" % b,
                                         "post", "exit"])
            traci.vehicle.setStop(vid, "booth_%d" % b, pos=P.BOOTH_STOP_POS,
                                  laneIndex=0, duration=svc[k], flags=0)
            # 1621 = SUMO default: strategic/cooperative/speed-gain changes allowed unless
            # they conflict with a TraCI request -> the strategic change onto the mainline
            # lane that actually feeds booth b is executed.
            traci.vehicle.setLaneChangeMode(vid, 1621)
            want = 0 if b < half else 1
            if traci.vehicle.getLaneIndex(vid) != want:
                traci.vehicle.changeLane(vid, want, 20.0)
            assigned[vid] = b
            log.append((traci.simulation.getTime(), vid, b, qlen[b]))
        # cheap safety valve: nothing else to do
    traci.close()
    json.dump({"assign_log_head": log[:50], "n_assigned": len(assigned),
               "booth_counts": {str(b): sum(1 for x in assigned.values() if x == b)
                                for b in range(c)}},
              open(os.path.join(run_dir, "assigner_log.json"), "w"), indent=1)
    return 0, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--net", required=True)
    ap.add_argument("--booths", type=int, default=6)
    ap.add_argument("--rate", type=float, required=True, help="veh/h")
    ap.add_argument("--horizon", type=float, default=3600.0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--service-dist", default="exp")
    ap.add_argument("--service-mean", type=float, default=8.0)
    ap.add_argument("--etc-share", type=float, default=0.0)
    ap.add_argument("--etc-mean", type=float, default=3.0)
    ap.add_argument("--etc-booths", type=int, default=0)
    ap.add_argument("--assign", default="random")
    ap.add_argument("--controller", default="none", choices=["none", "shortest", "roundrobin", "asgen"])
    ap.add_argument("--no-stops", action="store_true")
    ap.add_argument("--booth-speed-service", action="store_true")
    ap.add_argument("--decision-pos", type=float, default=600.0)
    ap.add_argument("--step-length", type=float, default=0.5)
    ap.add_argument("--end-pad", type=float, default=1800.0)
    args = ap.parse_args()

    stop_mode = "route" if args.controller == "none" else "traci"
    cfg, meta = P.write_scenario(
        args.run_dir, args.net, args.booths, args.rate, args.horizon,
        seed=args.seed, service_dist=args.service_dist, service_mean=args.service_mean,
        etc_share=args.etc_share, etc_mean=args.etc_mean, etc_booths=args.etc_booths,
        assign=args.assign, stop_mode=stop_mode, no_stops=args.no_stops,
        booth_speed_service=args.booth_speed_service,
        step_length=args.step_length, end_pad=args.end_pad)
    json.dump({k: v for k, v in meta.items() if k not in ("booth_of", "svc", "is_etc", "depart")},
              open(os.path.join(args.run_dir, "meta.json"), "w"), indent=1)
    json.dump(meta, open(os.path.join(args.run_dir, "meta_full.json"), "w"))

    if args.controller == "none":
        rc, err = run_plain(cfg, args.seed)
    else:
        a = "shortest" if args.controller == "shortest" else (
            "roundrobin" if args.controller == "roundrobin" else "asgen")
        rc, err = run_traci(cfg, args.seed, meta, args.run_dir, assign=a,
                            decision_pos=args.decision_pos)
    if err.strip():
        sys.stderr.write(err)
    sys.exit(rc)


if __name__ == "__main__":
    main()
