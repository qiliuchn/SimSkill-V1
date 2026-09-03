"""Single work-zone simulation run, driven through TraCI.

EVERY arm -- including `donothing` and `negctrl` -- goes through the identical TraCI
harness, so the control comparison is never confounded by the plumbing itself.  This is
the `negctrl` discipline from `implement-coordinated-corridor-ramp-metering`: the
negative-control arm runs the full dynamic controller (subscriptions, logging, decision
loop) but is clamped so it can never actuate, and must reproduce `donothing` exactly.

Arms
  donothing  default merge at the taper (net variant with N4 type="priority")
  early      static EARLY merge: the closing lane is prohibited from the START of the
             advance-warning area (traci.lane.setDisallowed on fC_k, fD_k)
  late       static LATE merge: closing lane usable to the taper, N4 type="zipper",
             and strategic lane-changes suppressed while a vehicle is on fB/fC
             ("USE BOTH LANES TO MERGE POINT")
  dynamic    DYNAMIC LATE MERGE: starts in EARLY mode, switches to LATE mode when
             smoothed upstream occupancy crosses ON_TH, back below OFF_TH, with a
             minimum dwell time (two-sided hysteresis)
  vsl        upstream speed harmonisation on fB/fC using a speed ladder
  negctrl    dynamic controller plumbing, actuation clamped off (must equal donothing)

Work-zone driver-behaviour effects (speedFactor, sigma) are applied on entry to the
activity area and restored on exit, IDENTICALLY in every arm.
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo/tools")
import traci  # noqa: E402

import wz_common as W  # noqa: E402

# --- lane-change mode bitmasks (LC2013) ------------------------------------
LCM_DEFAULT = 0b011001010101      # 1621, SUMO default
LCM_NO_STRATEGIC = 0b011001010100  # 1620, strategic bits cleared

# --- dynamic-late-merge controller ----------------------------------------
CTRL_INTERVAL = 30.0     # s between decisions
OCC_ON = 18.0            # % occupancy -> switch to LATE (zipper) mode
OCC_OFF = 9.0            # % occupancy -> switch back to EARLY mode
MIN_DWELL = 120.0        # s minimum time between mode switches

# --- VSL ladder (same structure as implement-variable-speed-limits) --------
VSL_SPEEDS = [33.33, 27.78, 22.22, 16.67]
VSL_UP = [10.0, 18.0, 28.0]
VSL_DOWN = [6.0, 12.0, 21.0]
VSL_ZONE_EDGES = ["fB", "fC"]


def run(net, routes, add, outdir, arm, p, seed=1, step=0.5, end=4800,
        ttt=300, ballistic=True, extra_sumo=None, fcd=None, ssm=False):
    os.makedirs(outdir, exist_ok=True)
    lanes_closed = p["lanes_closed"]

    cmd = [W.SUMO, "-n", net, "-r", routes, "-a", add,
           "--begin", "0", "--end", str(end),
           "--step-length", str(step),
           "--seed", str(seed),
           "--time-to-teleport", str(ttt),
           "--no-step-log", "true", "--no-warnings", "true",
           "--tripinfo-output", f"{outdir}/tripinfo.xml",
           "--tripinfo-output.write-unfinished", "true",
           "--summary-output", f"{outdir}/summary.xml",
           "--statistic-output", f"{outdir}/stats.xml",
           "--collision-output", f"{outdir}/collisions.xml",
           "--collision.action", "warn",
           "--collision.mingap-factor", "0",
           "--error-log", f"{outdir}/errors.log",
           "--log", f"{outdir}/sumo.log"]
    if ballistic:
        cmd += ["--step-method.ballistic"]
    if fcd:
        cmd += ["--fcd-output", f"{outdir}/fcd.xml", "--fcd-output.period", str(fcd)]
    if ssm:
        cmd += ["--device.ssm.probability", "1",
                "--device.ssm.file", f"{outdir}/ssm.xml",
                "--device.ssm.measures", "TTC DRAC",
                "--device.ssm.thresholds", "3.0 3.0",
                "--device.ssm.geo", "false"]
    if extra_sumo:
        cmd += list(extra_sumo)

    label = os.path.basename(outdir)
    traci.start(cmd, label=label)
    c = traci.getConnection(label)

    # --------------------------------------------------------------- setup
    closing_lanes_up = [f"fC_{i}" for i in range(lanes_closed)] + \
                       [f"fD_{i}" for i in range(lanes_closed)]
    # Two control stations.  The DYNAMIC merge controller must read a station upstream
    # of BOTH candidate merge points (fB), because the fC station is downstream of the
    # early-merge bottleneck and reads free flow whenever early merge is active.
    # The VSL arm keeps the fC (near-bottleneck) station: it never moves the merge point.
    vsl_dets = [d for d in c.lanearea.getIDList() if d.startswith("e2_ctrl_")]
    dlm_dets = [d for d in c.lanearea.getIDList() if d.startswith("e2_up_")]
    ctrl_dets = dlm_dets if arm in ("dynamic", "negctrl") else vsl_dets
    for d in set(ctrl_dets) | set(vsl_dets) | set(dlm_dets):
        c.lanearea.subscribe(d, [0x13, 0x11])  # last-step occupancy, mean speed

    # Per-vehicle state comes from ONE subscription round-trip per step
    # (road id + acceleration), not per-vehicle getters.  The time-discretization
    # skill measured per-vehicle polling at 39-48x the cost of a plain CLI run.
    VAR_ROAD, VAR_ACC = 0x50, 0x72

    def set_early_mode(on):
        for ln in closing_lanes_up:
            c.lane.setDisallowed(ln, ["passenger"] if on else [])

    mode = None
    if arm == "early":
        set_early_mode(True)
        mode = "EARLY"
    elif arm in ("dynamic",):
        set_early_mode(True)
        mode = "EARLY"
    elif arm in ("late",):
        mode = "LATE"
    else:
        mode = "OPEN"

    # --------------------------------------------------------------- state
    in_wz = set()          # vehicles currently under work-zone behaviour
    lc_suppressed = set()  # vehicles with strategic LC suppressed (late arms)
    seen = set()
    ctrl_log = []
    pending_integral = 0.0
    vsl_level = 0
    occ_smooth = None
    last_switch = -1e9
    next_ctrl = CTRL_INTERVAL
    hard_brakes = 0
    hard_brakes_taper = 0
    t = 0.0
    veh_sub = [0x40]  # speed
    max_running = 0

    suppress_edges = {"fB", "fC"}
    restore_edges = {"fD"}

    braking = set()  # vehicles currently inside a hard-braking event

    while t < end:
        c.simulationStep()
        t = c.simulation.getTime()

        for v in c.simulation.getDepartedIDList():
            c.vehicle.subscribe(v, [VAR_ROAD, VAR_ACC])

        pending = c.simulation.getPendingVehicles()
        pending_integral += len(pending) * step
        nrun = c.simulation.getMinExpectedNumber()

        vsub = c.vehicle.getAllSubscriptionResults()
        max_running = max(max_running, len(vsub))

        on_edge = {}
        for v, d in vsub.items():
            on_edge.setdefault(d.get(VAR_ROAD, ""), []).append(v)

        # --- work-zone driver behaviour (identical in every arm)
        cur_wz = set(on_edge.get("fE", ()))
        for v in cur_wz - in_wz:
            try:
                c.vehicle.setSpeedFactor(v, p["wz_speed_factor"])
                c.vehicle.setImperfection(v, p["wz_sigma"])
            except traci.TraCIException:
                pass
        for v in in_wz - cur_wz:
            try:
                c.vehicle.setSpeedFactor(v, 1.0)
                c.vehicle.setImperfection(v, 0.5)
            except traci.TraCIException:
                pass
        in_wz = cur_wz & set(vsub)

        # --- late-merge lane-change discipline
        if arm in ("late", "dynamic") and mode == "LATE":
            up = set()
            for e in suppress_edges:
                up |= set(on_edge.get(e, ()))
            for v in up - lc_suppressed:
                try:
                    c.vehicle.setLaneChangeMode(v, LCM_NO_STRATEGIC)
                    lc_suppressed.add(v)
                except traci.TraCIException:
                    pass
        if lc_suppressed:
            at_taper = set()
            for e in restore_edges:
                at_taper |= set(on_edge.get(e, ()))
            for v in (at_taper & lc_suppressed):
                try:
                    c.vehicle.setLaneChangeMode(v, LCM_DEFAULT)
                except traci.TraCIException:
                    pass
                lc_suppressed.discard(v)
            lc_suppressed &= set(vsub)

        # --- hard-braking surrogate safety: count EVENTS (entries into a < -4 m/s2),
        #     not vehicle-steps, so the count is step-length invariant.
        now_braking = set()
        for e in ("fC", "fD", "fE"):
            for v in on_edge.get(e, ()):
                if vsub[v].get(VAR_ACC, 0.0) < -4.0:
                    now_braking.add(v)
                    if v not in braking:
                        hard_brakes += 1
                        if e in ("fD", "fE"):
                            hard_brakes_taper += 1
        braking = now_braking

        # --- controller decisions
        if t >= next_ctrl:
            next_ctrl += CTRL_INTERVAL
            sub = c.lanearea.getAllSubscriptionResults()
            occs = [sub[d][0x13] for d in ctrl_dets if d in sub]
            occ = sum(occs) / len(occs) if occs else 0.0
            occ_smooth = occ if occ_smooth is None else 0.6 * occ_smooth + 0.4 * occ
            occ_up = np.mean([sub[d][0x13] for d in dlm_dets if d in sub]) if dlm_dets else 0.0
            occ_fc = np.mean([sub[d][0x13] for d in vsl_dets if d in sub]) if vsl_dets else 0.0

            if arm == "dynamic":
                if (t - last_switch) >= MIN_DWELL:
                    if mode == "EARLY" and occ_smooth > OCC_ON:
                        set_early_mode(False)
                        mode = "LATE"
                        last_switch = t
                    elif mode == "LATE" and occ_smooth < OCC_OFF:
                        set_early_mode(True)
                        mode = "EARLY"
                        last_switch = t
                        for v in list(lc_suppressed):
                            try:
                                c.vehicle.setLaneChangeMode(v, LCM_DEFAULT)
                            except traci.TraCIException:
                                pass
                        lc_suppressed.clear()
            elif arm == "vsl":
                lv = vsl_level
                if lv < 3 and occ_smooth > VSL_UP[lv]:
                    lv += 1
                elif lv > 0 and occ_smooth < VSL_DOWN[lv - 1]:
                    lv -= 1
                if lv != vsl_level:
                    vsl_level = lv
                    for e in VSL_ZONE_EDGES:
                        for i in range(c.edge.getLaneNumber(e)):
                            c.lane.setMaxSpeed(f"{e}_{i}", VSL_SPEEDS[vsl_level])
            elif arm == "negctrl":
                # full plumbing, decision computed and logged, NEVER actuated
                _ = (occ_smooth > OCC_ON)

            ctrl_log.append(dict(t=t, occ=occ, occ_smooth=occ_smooth, mode=mode,
                                 occ_up=float(occ_up), occ_fc=float(occ_fc),
                                 vsl=vsl_level, pending=len(pending)))

        if nrun == 0 and t > 4000:
            break

    teleports = c.simulation.getEndingTeleportNumber()
    arrived_total = c.simulation.getArrivedNumber()
    still_running = c.vehicle.getIDCount()
    c.close()

    meta = dict(arm=arm, seed=seed, step=step, end=end, ttt=ttt,
                ballistic=ballistic, params=p,
                pending_integral_vehs=pending_integral,
                final_still_running=still_running,
                max_running=max_running,
                hard_brakes=hard_brakes, hard_brakes_taper=hard_brakes_taper,
                final_mode=mode, net=net, routes=routes)
    with open(f"{outdir}/meta.json", "w") as fh:
        json.dump(meta, fh, indent=1)
    with open(f"{outdir}/ctrl_log.json", "w") as fh:
        json.dump(ctrl_log, fh)
    return meta


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", required=True)
    ap.add_argument("--routes", required=True)
    ap.add_argument("--add", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--arm", required=True)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--step", type=float, default=0.5)
    ap.add_argument("--end", type=float, default=4800)
    ap.add_argument("--ttt", type=float, default=300)
    ap.add_argument("--euler", action="store_true")
    ap.add_argument("--lanes-closed", type=int, default=1)
    a = ap.parse_args()
    p = W.params(lanes_closed=a.lanes_closed)
    m = run(a.net, a.routes, a.add, a.outdir, a.arm, p, seed=a.seed, step=a.step,
            end=a.end, ttt=a.ttt, ballistic=not a.euler)
    print(json.dumps(m)[:400])
