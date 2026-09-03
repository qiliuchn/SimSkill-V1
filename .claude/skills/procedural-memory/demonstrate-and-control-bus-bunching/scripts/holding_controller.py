#!/usr/bin/env python3
"""TraCI runner for the bus-bunching study.

Runs the IDENTICAL ring scenario in one of two modes:
  --mode baseline : no control (buses dwell only for boarding)
  --mode control  : forward-headway HOLDING control at every busStop

Holding rule (control mode): when a bus ARRIVES at a stop, compute the forward
headway h = (this arrival time) - (previous bus's arrival time at the same stop).
If h < target headway T, the bus is running EARLY (too close behind the leader):
hold it for hold = min(T - h, max_hold) extra seconds by extending its active
stop dwell via traci.vehicle.setBusStop(...). If h >= T the bus is on-time/late
-> NO hold. Every arrival + decision is logged to <mode>_holdlog.csv.

SUMO writes --stop-output and --tripinfo-output so a critic can recompute
headways/CV independently from the raw stop-output.
"""
import os, sys, argparse, csv

os.environ.setdefault("SUMO_HOME",
    "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo")
sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import traci


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["baseline", "control"], required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--net", required=True)
    ap.add_argument("--add", required=True)
    ap.add_argument("--routes", required=True)  # comma-separated buses,persons
    ap.add_argument("--end", type=float, default=3000.0)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--target-headway", type=float, default=0.0,
                    help="target even headway T (s), control mode")
    ap.add_argument("--max-hold", type=float, default=60.0)
    args = ap.parse_args()

    stop_out = os.path.join(args.out_dir, f"stopinfo_{args.mode}.xml")
    trip_out = os.path.join(args.out_dir, f"tripinfo_{args.mode}.xml")
    holdlog = os.path.join(args.out_dir, f"{args.mode}_holdlog.csv")

    cmd = ["sumo",
           "--net-file", args.net,
           "--additional-files", args.add,
           "--route-files", args.routes,
           "--stop-output", stop_out,
           "--tripinfo-output", trip_out,
           "--begin", "0", "--end", str(args.end), "--step-length", "1",
           "--seed", str(args.seed),
           "--no-step-log", "true",
           "--pedestrian.model", "nonInteracting",
           "--no-warnings", "true"]
    traci.start(cmd)

    T = args.target_headway
    control = (args.mode == "control")

    prev_at_stop = {}                # vid -> bool (was at a stop last step)
    last_arrival_at_stop = {}        # stopID -> last arrival time (any bus)
    logrows = []                     # (time, bus, stop, h_ahead, T, was_early, hold_applied)

    step = 0
    while traci.simulation.getMinExpectedNumber() > 0 and traci.simulation.getTime() < args.end:
        traci.simulationStep()
        t = traci.simulation.getTime()
        for vid in traci.vehicle.getIDList():
            if traci.vehicle.getTypeID(vid) != "bus":
                continue
            at = traci.vehicle.isAtBusStop(vid)
            was = prev_at_stop.get(vid, False)
            if at and not was:
                # rising edge: a fresh arrival at a stop
                stops = traci.vehicle.getStops(vid, 1)
                sid = stops[0].stoppingPlaceID if stops else ""
                prev_t = last_arrival_at_stop.get(sid)
                h_ahead = (t - prev_t) if prev_t is not None else None
                was_early = False
                hold_applied = 0.0
                if control and sid and (h_ahead is not None) and h_ahead < T:
                    was_early = True
                    hold_applied = min(T - h_ahead, args.max_hold)
                    # extend the active stop's minimum dwell -> holds the early bus
                    traci.vehicle.setBusStop(vid, sid, duration=float(hold_applied))
                last_arrival_at_stop[sid] = t
                logrows.append((f"{t:.1f}", vid, sid,
                                f"{h_ahead:.1f}" if h_ahead is not None else "",
                                f"{T:.1f}", int(was_early), f"{hold_applied:.1f}"))
            prev_at_stop[vid] = at
        step += 1

    traci.close()

    with open(holdlog, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "bus", "stop", "h_ahead", "target_T", "was_early", "hold_applied"])
        w.writerows(logrows)

    n_holds = sum(1 for r in logrows if float(r[6]) > 0)
    print(f"mode={args.mode} arrivals_logged={len(logrows)} holds_applied={n_holds}")
    print(f"stop-output -> {stop_out}")
    print(f"tripinfo    -> {trip_out}")
    print(f"holdlog     -> {holdlog}")


if __name__ == "__main__":
    main()
