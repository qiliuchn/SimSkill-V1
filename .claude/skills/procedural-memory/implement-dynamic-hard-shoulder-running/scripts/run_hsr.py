#!/usr/bin/env python3
"""Dynamic hard-shoulder-running controller for a SUMO motorway.

Three modes, identical network / demand / seed:
  closed   - hard shoulder stays reserved (emergency/authority only) the whole run.
  open     - hard shoulder opened to passenger cars at t=0 and kept open.
  dynamic  - hysteresis controller: opens the shoulder to passenger cars when the
             upstream through-lane E2 occupancy stays above occ_open for hold_open
             seconds, and re-closes it once occupancy stays below occ_close for
             hold_close seconds. Every open/close event is logged with its sim time.

Occupancy is read from the two through-lane E2 lane-area detectors just upstream of
the bottleneck (ids e2_thru_1, e2_thru_2), averaged.
"""
import argparse, os, sys

import traci

# The hard shoulder spans both the approach (m_0) and the reduced-speed weaving zone (w_0);
# both are opened/closed together.
SHOULDER_LANES = ["m_0", "w_0"]
CLOSED_CLASSES = ["emergency", "authority"]
OPEN_CLASSES = ["passenger", "emergency", "authority"]
E2_IDS = ["e2_thru_1", "e2_thru_2"]
SNAP_LANE = "w_0"  # lane watched for the setAllowed-timing investigation


def set_shoulder(classes):
    for ln in SHOULDER_LANES:
        traci.lane.setAllowed(ln, classes)


def avg_occupancy():
    vals = [traci.lanearea.getLastStepOccupancy(d) for d in E2_IDS]
    return sum(vals) / len(vals)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, choices=["closed", "open", "dynamic"])
    ap.add_argument("--net", required=True)
    ap.add_argument("--routes", required=True)
    ap.add_argument("--add", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--eventlog", required=True)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--end", type=float, default=4200.0)
    # hysteresis params (percent occupancy, seconds)
    ap.add_argument("--occ-open", type=float, default=18.0)
    ap.add_argument("--hold-open", type=float, default=45.0)
    ap.add_argument("--occ-close", type=float, default=6.0)
    ap.add_argument("--hold-close", type=float, default=120.0)
    a = ap.parse_args()

    os.makedirs(a.outdir, exist_ok=True)
    tripinfo = os.path.join(a.outdir, "tripinfo.xml")
    summary = os.path.join(a.outdir, "summary.xml")

    sumo_cmd = [
        "sumo",
        "-n", a.net,
        "-r", a.routes,
        "-a", a.add,
        "--tripinfo-output", tripinfo,
        "--summary-output", summary,
        "--seed", str(a.seed),
        "--end", str(a.end),
        "--time-to-teleport", "300",
        "--no-step-log", "true",
        "--duration-log.statistics", "true",
        "--xml-validation", "never",
    ]

    traci.start(sumo_cmd)

    ev = open(a.eventlog, "w")
    ev.write(f"# mode={a.mode} occ_open={a.occ_open} hold_open={a.hold_open} "
             f"occ_close={a.occ_close} hold_close={a.hold_close} seed={a.seed}\n")
    ev.write("time\tevent\toccupancy\tdetail\n")

    def log(t, event, occ, detail=""):
        ev.write(f"{t:.1f}\t{event}\t{occ:.2f}\t{detail}\n")
        ev.flush()

    shoulder_open = False
    above_since = None
    below_since = None
    windows = []  # list of [open_t, close_t]

    # For the setAllowed-timing investigation: at each close, snapshot vehicles
    # already on the shoulder lane and follow whether they stay on it.
    close_snapshots = []

    def open_shoulder(t, occ):
        nonlocal shoulder_open
        set_shoulder(OPEN_CLASSES)
        shoulder_open = True
        windows.append([t, None])
        log(t, "OPEN", occ, "setAllowed +passenger")

    def close_shoulder(t, occ):
        nonlocal shoulder_open
        # snapshot vehicles already on the shoulder BEFORE changing permission
        before = list(traci.lane.getLastStepVehicleIDs(SNAP_LANE))
        set_shoulder(CLOSED_CLASSES)
        after = list(traci.lane.getLastStepVehicleIDs(SNAP_LANE))
        shoulder_open = False
        if windows and windows[-1][1] is None:
            windows[-1][1] = t
        close_snapshots.append({"t": t, "before": before})
        log(t, "CLOSE", occ, f"setAllowed -passenger; on_shoulder_before={len(before)} after={len(after)}")

    # Establish the initial shoulder state at t=0. The network is COMPILED with the
    # shoulder open (so the best-lanes connectivity graph knows the m_0->w_0->x_0 path);
    # runtime setAllowed/setDisallowed on the edge shoulder lanes then gates actual use.
    # This is required because runtime setAllowed does NOT rebuild the load-time
    # connectivity graph, so a net compiled with the shoulder closed traps cars on m_0
    # (they can enter but cannot route across the junction into w_0).
    step = 0
    if a.mode == "open":
        set_shoulder(OPEN_CLASSES)
        shoulder_open = True
        windows.append([0.0, None])
        log(0.0, "OPEN", 0.0, "permanent-open at t=0")
    else:
        # closed and dynamic both START closed (shoulder reserved for emergency/authority)
        set_shoulder(CLOSED_CLASSES)
        shoulder_open = False
        log(0.0, "INIT_CLOSED", 0.0, "shoulder reserved at t=0")

    # track how many vehicles remain on the shoulder for a while after each close
    while traci.simulation.getMinExpectedNumber() > 0 and traci.simulation.getTime() < a.end:
        traci.simulationStep()
        t = traci.simulation.getTime()

        if a.mode == "dynamic":
            occ = avg_occupancy()
            if not shoulder_open:
                if occ >= a.occ_open:
                    if above_since is None:
                        above_since = t
                    elif t - above_since >= a.hold_open:
                        open_shoulder(t, occ)
                        above_since = None
                        below_since = None
                else:
                    above_since = None
            else:
                if occ <= a.occ_close:
                    if below_since is None:
                        below_since = t
                    elif t - below_since >= a.hold_close:
                        close_shoulder(t, occ)
                        above_since = None
                        below_since = None
                else:
                    below_since = None

            # follow post-close occupants (setAllowed-timing evidence)
            for snap in close_snapshots:
                if "trace" not in snap:
                    snap["trace"] = []
                if t - snap["t"] <= 30 and (t - snap["t"]) % 5 == 0:
                    onlane = set(traci.lane.getLastStepVehicleIDs(SNAP_LANE))
                    still = [v for v in snap["before"] if v in onlane]
                    snap["trace"].append((round(t - snap["t"], 1), len(still)))

        step += 1

    # close any still-open window at sim end
    if windows and windows[-1][1] is None:
        windows[-1][1] = traci.simulation.getTime()

    traci.close()

    # write windows + close snapshots
    with open(os.path.join(a.outdir, "windows.txt"), "w") as f:
        f.write("open_time\tclose_time\n")
        for w in windows:
            f.write(f"{w[0]:.1f}\t{w[1]:.1f}\n")

    if a.mode == "dynamic":
        for snap in close_snapshots:
            log(snap["t"], "POST_CLOSE_TRACE", 0.0,
                f"vehicles_on_shoulder_at_offset_s={snap.get('trace', [])}")

    ev.close()
    print(f"[{a.mode}] done. windows={windows}")


if __name__ == "__main__":
    main()
