"""Controlled single-vehicle probe of SUMO's ACTUAL stop/go rule at yellow onset.

One vehicle, no car-following interference. The vehicle is brought to a steady approach
speed, then the signal is switched to yellow via TraCI at the exact step the vehicle's
front bumper is at a target distance `d` from the stop line. The realized outcome
(stop / clear-on-yellow / enter-on-red) is recorded, together with the realized peak
deceleration and, when it stops, the realized stopping distance.

Sweeping `d` finely locates SUMO's own stop/go boundary x_s^SUMO to sub-metre resolution.
This is the empirical object that the ITE/kinematic x_s is compared against, and it is
what makes the "is the dilemma zone real or a SUMO artifact" question answerable.

Also used to test, with negative controls, which vType knobs actually move that boundary:
  decel, emergencyDecel, actionStepLength (perception-reaction proxy), tau, sigma,
  grade (z-coordinates), vClass/length.
"""
import argparse
import csv
import json
import os

from common import ANA_DIR, RUN_DIR, SUMO, add_tools_to_path
from build_net import build
import analytic

add_tools_to_path()
import traci  # noqa: E402


def probe_one(net_meta, rundir, v_target, d_target, vtype_attrs, yellow=3.0, allred=1.0,
              step=0.05, grade_pct=0.0, arm_lane="in_N_0", max_t=200.0, ballistic=True):
    """Return the outcome dict for one (v, d, vType) probe."""
    os.makedirs(rundir, exist_ok=True)
    n = net_meta["n_tls_links"]
    by_arm = net_meta["links_by_arm"]
    li = by_arm["N"][0]
    ns = sorted(by_arm["N"] + by_arm["S"])

    def st(ch):
        s = ["r"] * n
        for k in ns:
            s[k] = ch
        return "".join(s)

    green, yel, red = st("G"), st("y"), "r" * n

    vtype_attrs = dict(vtype_attrs)
    # pin the desired speed so the probe really travels at v_target (the lane speed limit is
    # deliberately set well above it so the approach is never speed-limited)
    vtype_attrs["maxSpeed"] = "%.6f" % v_target
    vtype_attrs["speedFactor"] = "1.0"
    vtype_attrs["speedDev"] = "0"
    vtype_attrs.pop("__asl_default", None)
    attrs = " ".join('%s="%s"' % (k, x) for k, x in vtype_attrs.items())
    rou = os.path.join(rundir, "p.rou.xml")
    open(rou, "w").write(
        '<routes>\n  <vType id="probe" %s/>\n'
        '  <route id="r" edges="in_N out_S"/>\n'
        '  <vehicle id="p0" type="probe" route="r" depart="0" departSpeed="%.4f" '
        'departLane="0" departPos="0"/>\n</routes>\n' % (attrs, v_target))
    add = os.path.join(rundir, "p.add.xml")
    open(add, "w").write('<additional>\n  <tlLogic id="C" type="static" programID="custom" '
                         'offset="0">\n    <phase duration="10000" state="%s"/>\n'
                         '  </tlLogic>\n</additional>\n' % green)

    cmd = [SUMO, "-n", net_meta["net"], "-r", rou, "-a", add,
           "--step-length", str(step), "--begin", "0", "--end", str(max_t),
           "--no-step-log", "true", "--no-warnings", "true",
           "--step-method.ballistic", str(bool(ballistic)).lower(),
           "--collision.action", "warn", "--collision.check-junctions", "true",
           "--time-to-teleport", "-1", "--seed", "1"]
    label = os.path.basename(rundir) + "_%s_%s" % (v_target, d_target)
    traci.start(cmd, label=label)
    c = traci.getConnection(label)
    c.trafficlight.setProgram("C", "custom")
    lane_len = net_meta["approach_lane_length"][arm_lane]

    triggered = False
    t_trigger = None
    d_trigger = None
    v_trigger = None
    outcome = None
    cross_t = None
    cross_state = None
    stop_dist = None
    maxdec = 0.0
    vprev = None
    t = 0.0
    speeds = []
    try:
        while t < max_t:
            c.simulationStep()
            t = c.simulation.getTime()
            if "p0" not in c.vehicle.getIDList():
                if triggered and outcome is None:
                    outcome = "GONE"
                break
            pos = c.vehicle.getLanePosition("p0")
            road = c.vehicle.getRoadID("p0")
            sp = c.vehicle.getSpeed("p0")
            if vprev is not None and triggered:
                maxdec = max(maxdec, (vprev - sp) / step)
            vprev = sp
            if road == "in_N":
                d = lane_len - pos
                if not triggered and d <= d_target:
                    triggered = True
                    t_trigger, d_trigger, v_trigger = t, d, sp
                    c.trafficlight.setRedYellowGreenState("C", yel)
                    speeds.append((0.0, sp, d))
                elif triggered:
                    speeds.append((round(t - t_trigger, 3), sp, d))
                    if sp < 0.05 and outcome is None:
                        outcome = "STOP"
                        stop_dist = d
                        break
            elif triggered and outcome is None:
                # crossed the stop line
                cross_t = t - t_trigger
                cur = c.trafficlight.getRedYellowGreenState("C")
                cross_state = cur[li]
                outcome = "CLEAR_YELLOW" if cross_state in "yY" else "RED_ENTRY"
                break
            elif not triggered and road != "in_N":
                outcome = "NEVER_TRIGGERED"
                break
            if triggered:
                el = t - t_trigger
                if el >= yellow and el < yellow + allred:
                    c.trafficlight.setRedYellowGreenState("C", red)
                elif el >= yellow + allred:
                    c.trafficlight.setRedYellowGreenState("C", red)
    finally:
        try:
            c.close()
        except Exception:
            pass
    return dict(v_target=v_target, d_target=d_target, d_actual=d_trigger,
                v_actual=v_trigger, outcome=outcome, cross_t=cross_t,
                cross_state=cross_state, stop_dist=stop_dist, maxdecel=round(maxdec, 4),
                grade_pct=grade_pct, yellow=yellow, allred=allred, step=step)


def bisect_boundary(net_meta, rundir, v, vtype_attrs, yellow, lo=1.0, hi=250.0,
                    tol=0.25, step=0.05, grade_pct=0.0, max_iter=30, ballistic=True):
    kw = dict(step=step, grade_pct=grade_pct, ballistic=ballistic)
    return _bisect(net_meta, rundir, v, vtype_attrs, yellow, lo, hi, tol, max_iter, kw)


def _bisect(net_meta, rundir, v, vtype_attrs, yellow, lo, hi, tol, max_iter, kw):
    probe = lambda d: probe_one(net_meta, rundir, v, d, vtype_attrs, yellow, **kw)
    return _bisect_impl(probe, lo, hi, tol, max_iter)


def _bisect_impl(probe, lo, hi, tol, max_iter):
    it = 0
    res_lo, res_hi = probe(lo), probe(hi)
    if res_lo["outcome"] == "STOP" or res_hi["outcome"] != "STOP":
        return dict(boundary=None, lo=lo, hi=hi, outcome_lo=res_lo["outcome"],
                    outcome_hi=res_hi["outcome"], note="non-bracketing")
    d_lo, d_hi = res_lo["d_actual"], res_hi["d_actual"]
    while hi - lo > tol and it < max_iter:
        mid = 0.5 * (lo + hi)
        r = probe(mid)
        if r["outcome"] == "STOP":
            hi, d_hi = mid, r["d_actual"]
        else:
            lo, d_lo = mid, r["d_actual"]
        it += 1
    return dict(boundary=0.5 * (d_lo + d_hi), boundary_target=0.5 * (lo + hi),
                lo=lo, hi=hi, d_lo=d_lo, d_hi=d_hi, iters=it,
                outcome_lo=res_lo["outcome"], outcome_hi=res_hi["outcome"])


def _bisect_boundary_old(net_meta, rundir, v, vtype_attrs, yellow, lo=1.0, hi=250.0,
                         tol=0.10, step=0.05, grade_pct=0.0, max_iter=30):
    """Find the smallest distance at which the vehicle STOPS (SUMO's x_s), by bisection.

    Below the boundary the vehicle goes; above it, it stops. Verified monotone by the
    coarse scan that precedes every bisection.
    """
    it = 0
    res_lo = probe_one(net_meta, rundir, v, lo, vtype_attrs, yellow, grade_pct=grade_pct, step=step)
    res_hi = probe_one(net_meta, rundir, v, hi, vtype_attrs, yellow, grade_pct=grade_pct, step=step)
    if res_lo["outcome"] == "STOP" or res_hi["outcome"] != "STOP":
        return dict(boundary=None, lo=lo, hi=hi,
                    outcome_lo=res_lo["outcome"], outcome_hi=res_hi["outcome"],
                    note="non-bracketing")
    d_lo, d_hi = res_lo["d_actual"], res_hi["d_actual"]
    while hi - lo > tol and it < max_iter:
        mid = 0.5 * (lo + hi)
        r = probe_one(net_meta, rundir, v, mid, vtype_attrs, yellow, grade_pct=grade_pct, step=step)
        if r["outcome"] == "STOP":
            hi, d_hi = mid, r["d_actual"]
        else:
            lo, d_lo = mid, r["d_actual"]
        it += 1
    # report the boundary in ACTUAL (realized) distance, not target distance
    return dict(boundary=0.5 * (d_lo + d_hi), boundary_target=0.5 * (lo + hi),
                lo=lo, hi=hi, d_lo=d_lo, d_hi=d_hi, iters=it,
                outcome_lo=res_lo["outcome"], outcome_hi=res_hi["outcome"])


CAR_BASE = dict(vClass="passenger", length="5.0", minGap="2.5", accel="2.6", decel="4.5",
                emergencyDecel="9.0", sigma="0", speedDev="0", tau="1.0",
                carFollowModel="Krauss", maxSpeed="45")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="all",
                    choices=["all", "scan", "boundary", "params", "grade"])
    a = ap.parse_args()
    # each mode gets its own scratch dir and its own net name so the four modes can be run
    # concurrently without clobbering each other's p.rou.xml / p.add.xml / .net.xml
    rd = os.path.join(RUN_DIR, "stopgo_" + a.mode)
    os.makedirs(rd, exist_ok=True)
    modes = ["scan", "boundary", "params", "grade"] if a.mode == "all" else [a.mode]
    net, meta = build("probe_flat_" + a.mode, speed=45.0, grade_pct=0.0, lanes=1, arm=600.0)

    if "scan" in modes:
        # fine distance scan -> the single-vehicle stop/go curve, both driver models
        rows = []
        for drv, over in (("DEF", dict(decel="4.5")),
                          ("ITE", dict(decel="3.05", actionStepLength="1.0"))):
            for v in (13.89, 19.44, 25.0):
                for y in (2.0, 3.0, 5.0):
                    d = 2.0
                    while d <= 180.0:
                        at = dict(CAR_BASE); at.update(over)
                        r = probe_one(meta, rd, v, d, at, yellow=y)
                        r.update(driver=drv, yellow_set=y)
                        rows.append(r)
                        d += 3.0
        with open(os.path.join(ANA_DIR, "stopgo_scan.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader(); w.writerows(rows)
        print("scan rows", len(rows), flush=True)

    if "boundary" in modes:
        out = []
        for v in (11.11, 13.89, 16.67, 19.44, 22.22, 25.0, 27.78, 30.0):
            for decel in (4.5, 3.05, 2.5):
                for asl in (0.05, 1.0):
                    for ball in (True, False):
                        at = dict(CAR_BASE)
                        at["decel"] = str(decel)
                        at["actionStepLength"] = str(asl)
                        b = bisect_boundary(meta, rd, v, at, yellow=3.0, ballistic=ball)
                        out.append(dict(v=v, decel=decel, actionStepLength=asl,
                                        ballistic=ball,
                                        sumo_boundary=b.get("boundary"),
                                        kinematic_no_prt=analytic.x_stop(v, 0.0, decel),
                                        kinematic_with_prt=analytic.x_stop(v, asl, decel),
                                        ite_x_stop=analytic.x_stop(v, 1.0, 3.05),
                                        x_c_stopline_y3=v * 3.0,
                                        note=b.get("note")))
                        print(out[-1], flush=True)
        json.dump(out, open(os.path.join(ANA_DIR, "stopgo_boundary.json"), "w"), indent=2)

    if "params" in modes:
        v = 22.22
        variants = {
            "base_decel4.5": {},
            "base_decel3.05": dict(decel="3.05"),
            "decel_6.0": dict(decel="6.0"),
            "decel_2.5": dict(decel="2.5"),
            "emergencyDecel_4.6": dict(decel="3.05", emergencyDecel="4.6"),
            "emergencyDecel_15": dict(decel="3.05", emergencyDecel="15"),
            "tau_2.0_NEGCTRL": dict(decel="3.05", tau="2.0"),
            "sigma_0.5_NEGCTRL": dict(decel="3.05", sigma="0.5"),
            "minGap_10_NEGCTRL": dict(decel="3.05", minGap="10.0"),
            "asl_1.0": dict(decel="3.05", actionStepLength="1.0"),
            "asl_2.0": dict(decel="3.05", actionStepLength="2.0"),
            "length_12": dict(decel="3.05", length="12.0"),
            "truck_like": dict(length="12.0", decel="2.5", accel="1.3", vClass="truck",
                               emergencyDecel="5.0", tau="1.4"),
            "jmDriveAfterRedTime_0": dict(decel="3.05", jmDriveAfterRedTime="0"),
            "jmDriveAfterRedTime_1": dict(decel="3.05", jmDriveAfterRedTime="1"),
            "jmDriveAfterRedTime_3": dict(decel="3.05", jmDriveAfterRedTime="3"),
            "jmDriveAfterYellowTime_2": dict(decel="3.05", jmDriveAfterYellowTime="2"),
            "jmDriveAfterYellowTime_5": dict(decel="3.05", jmDriveAfterYellowTime="5"),
            "jmIgnoreFoeProb_1_NEGCTRL": dict(decel="3.05", jmIgnoreFoeProb="1.0",
                                              jmIgnoreFoeSpeed="30"),
            "jmTimegapMinor_0_NEGCTRL": dict(decel="3.05", jmTimegapMinor="0"),
            "jmStoplineGap_5": dict(decel="3.05", jmStoplineGap="5"),
            "impatience_1_NEGCTRL": dict(decel="3.05", impatience="1.0"),
            "bogusParam_NEGCTRL": dict(decel="3.05", jmNotARealParameter="7"),
        }
        out = []
        for name, over in variants.items():
            at = dict(CAR_BASE); at.update(over)
            b = bisect_boundary(meta, rd, v, at, yellow=3.0)
            row = dict(variant=name, v=v, overrides=over, boundary=b.get("boundary"),
                       note=b.get("note"))
            for d, y in ((60.0, 3.0), (75.0, 3.0), (90.0, 3.0), (150.0, 3.0),
                         (150.0, 8.0), (200.0, 8.0)):
                r = probe_one(meta, rd, v, d, at, yellow=y)
                row["d%.0f_y%.0f" % (d, y)] = "%s|md=%.1f" % (r["outcome"], r["maxdecel"])
            out.append(row)
            print(row["variant"], row["boundary"],
                  {k: x for k, x in row.items() if k.startswith("d")}, flush=True)
        json.dump(out, open(os.path.join(ANA_DIR, "stopgo_params.json"), "w"), indent=2)

    if "grade" in modes:
        out = []
        for g in (0.0, -2.0, -4.0, -6.0, 4.0, 6.0):
            gm = build("probe_g%+.0f_%s" % (g, a.mode), speed=45.0, grade_pct=g,
                       lanes=1, arm=600.0)[1]
            realized = gm["realized_grade_pct"]["N"]
            for v in (16.67, 22.22, 27.78):
                for decel in (4.5, 3.05):
                    at = dict(CAR_BASE); at["decel"] = str(decel)
                    b = bisect_boundary(gm, rd, v, at, yellow=3.0, grade_pct=g)
                    r = probe_one(gm, rd, v, 250.0, at, yellow=3.0, grade_pct=g)
                    out.append(dict(grade_nominal=g, grade_realized=realized, v=v,
                                    decel=decel, sumo_boundary=b.get("boundary"),
                                    realized_stop_dist=(r["d_actual"] - r["stop_dist"])
                                    if r["stop_dist"] is not None else None,
                                    maxdecel=r["maxdecel"],
                                    analytic_x_stop_flat=analytic.x_stop(v, 0.0, decel, 0.0),
                                    analytic_x_stop_grade=analytic.x_stop(v, 0.0, decel,
                                                                          g / 100.0),
                                    ite_y_flat=analytic.ite_yellow(v, 1.0, 3.05, 0.0),
                                    ite_y_grade=analytic.ite_yellow(v, 1.0, 3.05, g / 100.0)))
                    print(out[-1], flush=True)
        json.dump(out, open(os.path.join(ANA_DIR, "stopgo_grade.json"), "w"), indent=2)


if __name__ == "__main__":
    main()
