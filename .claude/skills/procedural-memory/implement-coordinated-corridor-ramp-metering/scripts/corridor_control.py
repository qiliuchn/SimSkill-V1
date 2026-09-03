#!/usr/bin/env python3
"""
Coordinated corridor ramp metering over TraCI -- 6 control arms sharing identical
demand, network and seeds.

ARMS
  nocontrol    every ramp meter held permanently green (baseline)
  fixed        fixed release rate at every ramp while the metering window is open
  alinea       per-ramp ISOLATED ALINEA on that ramp's own local downstream E1
               (setpoint = the LOCAL station's own critical occupancy)
  bnalinea     single-ramp ALINEA at the bottleneck-adjacent ramp only, regulated on
               the BOTTLENECK detector -- isolates the detector-location effect from
               the upstream-recruitment effect when compared against `coord`
  coord        HERO-style master/slave: the bottleneck-adjacent ramp (r3) is the
               master, regulated by ALINEA on the BOTTLENECK detector; when the
               master's queue-to-storage ratio exceeds W_HI the next upstream ramp
               is recruited as a slave and metered so the cluster's queue ratios
               equalise; if the slave also saturates, the next one up is recruited.
               De-recruit below W_LO.
  coord_flush  coord + a strict ramp-queue override: any ramp whose queue ratio
               reaches W_FLUSH is flushed (green) until it drains below W_RELEASE
  negctrl      the full coord controller runs, logs, and actuates, but its rate is
               clamped so it is NEVER restrictive -> must reproduce `nocontrol`

RATE -> SIGNAL translation (from `implement-alinea-ramp-metering`): one-car-per-green,
cycle C = 3600/r s, green GREEN_T s, red the remainder; if C <= GREEN_T hold green.
"""
import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

sys.path.append(os.environ.get("SUMO_HOME",
                "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo") + "/tools")
import traci  # noqa: E402
from traci import constants as tc  # noqa: E402

RAMPS = ["r1", "r2", "r3"]
MASTER = "r3"                       # bottleneck-adjacent ramp
UPSTREAM_OF = {"r3": "r2", "r2": "r1", "r1": None}
LOCAL_DET = {"r1": "s03", "r2": "s06", "r3": "s09"}
# CONTROL detector for the coordinated master: just downstream of the master ramp's
# merge, 800 m upstream of the lane drop. NOT s10: s10 sits inside the lane drop's
# permanent merge-turbulence zone, where the flow-occupancy curve is almost flat
# (3600-4080 veh/h between 8% and 31% occupancy) and free-flow occupancy is already
# 7-18% -- a controller regulating on it meters continuously at every demand level.
BN_DET = "s09"
ONSET_DET = "s10"                   # breakdown-onset MONITORING detector (reporting only)
DISCH_DET = "s11"                   # bottleneck discharge detector
STATIONS = [f"s{i:02d}" for i in range(1, 13)]

CTRL_DT = 30.0                      # control interval (s)
GREEN_T = 2.0                       # one-car-per-green green duration
R_MIN, R_MAX = 180.0, 1800.0        # veh/h
K_ALINEA = 70.0                     # veh/h per % occupancy
VEH_SLOT = 7.5                      # m per queued vehicle (length 5.0 + minGap 2.5)
T_BAL = 300.0                       # HERO queue-balancing time constant (s)
PEND_DT = 10.0                      # sampling interval for the insertion-queue integral


def lanes_of(net, edge):
    root = ET.parse(net).getroot()
    for e in root.findall("edge"):
        if e.get("id") == edge:
            return [l.get("id") for l in e.findall("lane")]
    return []


def det_ids(net):
    """station -> list of E1 ids, from the additional file conventions"""
    root = ET.parse(net).getroot()
    nl = {}
    for e in root.findall("edge"):
        if e.get("function") != "internal":
            nl[e.get("id")] = len(e.findall("lane"))
    from gen_additional import STATIONS as ST
    out = {}
    for sid, e, p in ST:
        out[sid] = [f"e1_{sid}_{l}" for l in range(nl[e])]
    return out


class RampCtl:
    def __init__(self, rid, storage_len):
        self.rid = rid
        self.S = max(1.0, storage_len / VEH_SLOT)   # storage in vehicles
        self.r = R_MAX
        self.active = False
        self.override = False
        self.cyc_t = 0.0
        self.state = "G"
        self.recruited = False

    def step_signal(self, dt, permanent_green):
        if permanent_green or self.r >= R_MAX - 1e-6:
            self.state = "G"
            self.cyc_t = 0.0
            return
        C = 3600.0 / max(self.r, 1e-6)
        if C <= GREEN_T:
            self.state = "G"
            self.cyc_t = 0.0
            return
        self.cyc_t = (self.cyc_t + dt) % C
        self.state = "G" if self.cyc_t < GREEN_T else "r"


def run(args):
    net = args.net
    storage = {}
    root = ET.parse(net).getroot()
    for e in root.findall("edge"):
        if e.get("id", "").endswith("_stor"):
            storage[e.get("id")[:2]] = float(e.find("lane").get("length"))

    E1 = det_ids(net)
    disch_det = {r: f"e1_{r}_disch_0" for r in RAMPS}
    entry_det = {r: f"e1_{r}_entry_0" for r in RAMPS}
    e2_stor = {r: f"e2_{r}_stor" for r in RAMPS}
    e2_capp = {r: f"e2_{r}_capp" for r in RAMPS}
    e2_sapp = {r: [f"e2_{r}_sapp_0", f"e2_{r}_sapp_1"] for r in RAMPS}

    cmd = ["sumo", "-n", net, "-r", args.routes, "-a", args.additional,
           "--begin", "0", "--end", str(args.end),
           "--step-length", "1.0", "--seed", str(args.seed),
           "--time-to-teleport", str(args.ttt),
           "--tripinfo-output", args.tripinfo,
           "--tripinfo-output.write-unfinished", "true",
           "--summary-output", args.summary,
           "--no-step-log", "true", "--duration-log.disable", "true",
           "--xml-validation", "never", "--collision.action", "warn",
           "--default.speeddev", "0"]
    if args.fcd:
        # NOTE: do NOT use --device.fcd.period here -- it offsets each vehicle's
        # sampling by that vehicle's own departure time, so almost no vehicle is
        # ever sampled on a control instant. Report every step and subsample.
        cmd += ["--fcd-output", args.fcd,
                "--fcd-output.filter-edges.input-file", args.fcd_filter]
    label = os.path.basename(args.outjson)
    traci.start(cmd, label=label)
    conn = traci.getConnection(label)

    ctl = {r: RampCtl(r, storage[r]) for r in RAMPS}
    for r in RAMPS:
        conn.trafficlight.setProgram(f"{r}_met", "ctl")
        conn.trafficlight.setProgram(f"{r}_term", "ctl")

    # ---- TraCI SUBSCRIPTIONS ----------------------------------------------
    # Querying ~150 detector getters per simulation step over the TraCI socket
    # dominated runtime (measured: ~5x slower than the simulation itself).
    # Subscribing collapses all of it into ONE round trip per step.
    E1_VARS = [tc.LAST_STEP_OCCUPANCY, tc.LAST_STEP_MEAN_SPEED,
               tc.LAST_STEP_VEHICLE_NUMBER, tc.LAST_STEP_VEHICLE_ID_LIST]
    E2_VARS = [tc.JAM_LENGTH_METERS, tc.LAST_STEP_VEHICLE_NUMBER]
    all_e1 = [d for s in STATIONS for d in E1[s]] + \
             [disch_det[r] for r in RAMPS] + [entry_det[r] for r in RAMPS]
    for d in all_e1:
        conn.inductionloop.subscribe(d, E1_VARS)
    all_e2 = [e2_stor[r] for r in RAMPS] + [e2_capp[r] for r in RAMPS] + \
             [d for r in RAMPS for d in e2_sapp[r]]
    for d in all_e2:
        conn.lanearea.subscribe(d, E2_VARS)

    # accumulators over the current control interval
    acc = {s: dict(occ=0.0, n=0, spd_sum=0.0, spd_w=0.0, cnt=0) for s in STATIONS}
    last_ids = defaultdict(set)
    ramp_acc = {r: dict(disch=0, entry=0, red_s=0.0) for r in RAMPS}

    log = []
    pend_integral = 0.0
    teleports = 0
    tele_ids = set()
    t = 0.0
    dt = 1.0
    next_ctrl = CTRL_DT
    next_pend = 0.0

    def sample_e1():
        res = conn.inductionloop.getAllSubscriptionResults()
        for s in STATIONS:
            a = acc[s]
            for d in E1[s]:
                v = res[d]
                a["occ"] += max(v[tc.LAST_STEP_OCCUPANCY], 0.0)
                a["n"] += 1
                n = v[tc.LAST_STEP_VEHICLE_NUMBER]
                sp = v[tc.LAST_STEP_MEAN_SPEED]
                if sp >= 0 and n > 0:
                    a["spd_sum"] += sp * n
                    a["spd_w"] += n
                ids = set(v[tc.LAST_STEP_VEHICLE_ID_LIST])
                a["cnt"] += len(ids - last_ids[d])
                last_ids[d] = ids
        for r in RAMPS:
            for key, d in (("disch", disch_det[r]), ("entry", entry_det[r])):
                ids = set(res[d][tc.LAST_STEP_VEHICLE_ID_LIST])
                ramp_acc[r][key] += len(ids - last_ids[d])
                last_ids[d] = ids

    while t < args.end:
        # ---- actuate meters (every step) ----
        for r in RAMPS:
            c = ctl[r]
            c.step_signal(dt, permanent_green=(args.arm == "nocontrol"))
            conn.trafficlight.setRedYellowGreenState(f"{r}_met", c.state)
            if c.state == "r":
                ramp_acc[r]["red_s"] += dt
        conn.simulationStep()
        t += dt
        sample_e1()
        tl = conn.simulation.getStartingTeleportIDList()
        if tl:
            teleports += len(tl)
            tele_ids.update(tl)
        if t >= next_pend:
            pend_integral += len(conn.simulation.getPendingVehicles()) * PEND_DT
            next_pend += PEND_DT

        # ---- control update ----
        if t >= next_ctrl - 1e-9:
            occ = {s: (acc[s]["occ"] / acc[s]["n"] if acc[s]["n"] else 0.0) for s in STATIONS}
            spd = {s: (acc[s]["spd_sum"] / acc[s]["spd_w"] if acc[s]["spd_w"] > 0 else float("nan"))
                   for s in STATIONS}
            flw = {s: acc[s]["cnt"] * 3600.0 / CTRL_DT for s in STATIONS}
            e2r = conn.lanearea.getAllSubscriptionResults()
            q = {}
            for r in RAMPS:
                jam = e2r[e2_stor[r]][tc.JAM_LENGTH_METERS]
                nveh = e2r[e2_stor[r]][tc.LAST_STEP_VEHICLE_NUMBER]
                q[r] = dict(jam_m=jam, nveh=nveh, ratio=min(nveh / ctl[r].S, 2.0),
                            capp_jam=e2r[e2_capp[r]][tc.JAM_LENGTH_METERS],
                            capp_n=e2r[e2_capp[r]][tc.LAST_STEP_VEHICLE_NUMBER],
                            sapp_jam=max(e2r[d][tc.JAM_LENGTH_METERS] for d in e2_sapp[r]),
                            sapp_n=sum(e2r[d][tc.LAST_STEP_VEHICLE_NUMBER] for d in e2_sapp[r]))
            arr = {r: ramp_acc[r]["entry"] * 3600.0 / CTRL_DT for r in RAMPS}
            realized = {r: ramp_acc[r]["disch"] * 3600.0 / CTRL_DT for r in RAMPS}

            cmd_before = {r: ctl[r].r for r in RAMPS}
            _update_rates(args, ctl, occ, q, arr)
            rec = dict(t=t,
                       occ={s: round(occ[s], 3) for s in STATIONS},
                       spd={s: (None if spd[s] != spd[s] else round(spd[s], 3)) for s in STATIONS},
                       flow={s: flw[s] for s in STATIONS},
                       ramp={r: dict(cmd_prev=round(cmd_before[r], 1),
                                     cmd=round(ctl[r].r, 1),
                                     realized=realized[r], arrivals=arr[r],
                                     jam_m=round(q[r]["jam_m"], 2), nveh=q[r]["nveh"],
                                     ratio=round(q[r]["ratio"], 4),
                                     capp_jam=round(q[r]["capp_jam"], 2), capp_n=q[r]["capp_n"],
                                     sapp_jam=round(q[r]["sapp_jam"], 2), sapp_n=q[r]["sapp_n"],
                                     active=ctl[r].active, override=ctl[r].override,
                                     recruited=ctl[r].recruited,
                                     red_frac=round(ramp_acc[r]["red_s"] / CTRL_DT, 4))
                             for r in RAMPS},
                       running=conn.vehicle.getIDCount(),
                       pending=len(conn.simulation.getPendingVehicles()),
                       teleports=teleports)
            log.append(rec)
            for s in STATIONS:
                acc[s] = dict(occ=0.0, n=0, spd_sum=0.0, spd_w=0.0, cnt=0)
            for r in RAMPS:
                ramp_acc[r] = dict(disch=0, entry=0, red_s=0.0)
            next_ctrl += CTRL_DT

        if conn.simulation.getMinExpectedNumber() == 0 and t > 600:
            break

    loaded = conn.simulation.getLoadedNumber()
    conn.close()
    meta = dict(arm=args.arm, seed=args.seed, demand=args.demand, net=net,
                routes=args.routes, end=t, storage=storage,
                pend_integral_veh_s=pend_integral, teleports=teleports,
                teleport_ids=sorted(tele_ids),
                o_target_local=args.o_target_local, o_target_bn=args.o_target_bn,
                o_on_local=args.o_on_local, o_off_local=args.o_off_local,
                o_on_bn=args.o_on_bn, o_off_bn=args.o_off_bn,
                w_hi=args.w_hi, w_lo=args.w_lo, w_flush=args.w_flush,
                w_release=args.w_release, fixed_rate=args.fixed_rate)
    json.dump(dict(meta=meta, log=log), open(args.outjson, "w"))
    return meta


def _update_rates(args, ctl, occ, q, arr):
    """One control update.  `occ` = mean E1 occupancy (%) per station over the last
    control interval, `q[r]` = ramp queue state, `arr[r]` = measured ramp arrival rate."""
    arm = args.arm
    if arm == "nocontrol":
        for r in RAMPS:
            ctl[r].r = R_MAX
            ctl[r].active = ctl[r].override = ctl[r].recruited = False
        return

    def act(r, o, on, off):
        """activation with hysteresis (occupancy threshold + dead band)"""
        c = ctl[r]
        if not c.active and o > on:
            c.active = True
            c.r = R_MAX
        elif c.active and o < off:
            c.active = False
            c.r = R_MAX
        return c.active

    if arm == "fixed":
        for r in RAMPS:
            if act(r, occ[LOCAL_DET[r]], args.o_on_local, args.o_off_local):
                ctl[r].r = args.fixed_rate
            ctl[r].recruited = ctl[r].active
    elif arm == "alinea":
        for r in RAMPS:
            o = occ[LOCAL_DET[r]]
            if act(r, o, args.o_on_local, args.o_off_local):
                ctl[r].r = min(R_MAX, max(R_MIN, ctl[r].r + K_ALINEA * (args.o_target_local - o)))
            ctl[r].recruited = ctl[r].active
    elif arm == "bnalinea":
        ob = occ[BN_DET]
        for r in RAMPS:
            if r != MASTER:
                ctl[r].r = R_MAX
                ctl[r].active = ctl[r].recruited = False
        if act(MASTER, ob, args.o_on_bn, args.o_off_bn):
            m = ctl[MASTER]
            m.r = min(R_MAX, max(R_MIN, m.r + K_ALINEA * (args.o_target_bn - ob)))
        ctl[MASTER].recruited = ctl[MASTER].active
    elif arm in ("coord", "coord_flush", "negctrl"):
        # ---- MASTER: ALINEA on the BOTTLENECK detector ----
        ob = occ[BN_DET]
        m = ctl[MASTER]
        if act(MASTER, ob, args.o_on_bn, args.o_off_bn):
            m.r = min(R_MAX, max(R_MIN, m.r + K_ALINEA * (args.o_target_bn - ob)))
        m.recruited = m.active
        # ---- SLAVE RECRUITMENT walking upstream (HERO-style) ----
        cur, prev = UPSTREAM_OF[MASTER], MASTER
        while cur is not None:
            c, p = ctl[cur], ctl[prev]
            if p.recruited and q[prev]["ratio"] >= args.w_hi:
                c.recruited = True
                c.active = True
            elif (not p.recruited) or q[prev]["ratio"] < args.w_lo:
                c.recruited = False
                c.active = False
                c.r = R_MAX
            if c.recruited:
                # queue-ratio equalisation: release less than arrivals in proportion
                # to how much more saturated the DOWNSTREAM cluster member is, so the
                # cluster's queues drain toward a common queue-to-storage ratio.
                dw = q[prev]["ratio"] - q[cur]["ratio"]
                c.r = min(R_MAX, max(R_MIN, arr[cur] - 3600.0 * (dw * c.S) / T_BAL))
            cur, prev = UPSTREAM_OF[cur], cur
        for r in RAMPS:
            if not ctl[r].recruited:
                ctl[r].r = R_MAX
                ctl[r].active = False
    else:
        raise ValueError(arm)

    # ---------- ramp-queue override (flush) ----------
    for r in RAMPS:
        c = ctl[r]
        if arm == "coord_flush":
            if not c.override and q[r]["ratio"] >= args.w_flush:
                c.override = True
            elif c.override and q[r]["ratio"] <= args.w_release:
                c.override = False
            if c.override:
                c.r = R_MAX
        else:
            c.override = False

    # ---------- NON-BINDING NEGATIVE CONTROL ----------
    # the controller above ran, logged and actuated exactly as in `coord`, but its
    # commanded rate is clamped open so it can never restrict -> must reproduce
    # `nocontrol` bit-for-bit on every outcome metric.
    if arm == "negctrl":
        for r in RAMPS:
            ctl[r].r = R_MAX


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", required=True)
    ap.add_argument("--routes", required=True)
    ap.add_argument("--additional", required=True)
    ap.add_argument("--arm", required=True)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--demand", type=float, default=1.0)
    ap.add_argument("--end", type=float, default=7200)
    ap.add_argument("--ttt", type=float, default=300)
    ap.add_argument("--tripinfo", required=True)
    ap.add_argument("--summary", required=True)
    ap.add_argument("--outjson", required=True)
    ap.add_argument("--fcd", default=None, help="write FCD here (queue cross-validation)")
    ap.add_argument("--fcd-filter", dest="fcd_filter", default=None)
    # Setpoints calibrated on the CORRIDOR ITSELF (calibrate_corridor.py), not on
    # the mainline-only sweep: pooled no-control 30 s intervals give a critical
    # occupancy of 8.8-10.6% at the 3-lane stations (capacity 6100-6800 veh/h).
    # The mainline-only sweep's setpoint was ~4x too low and made every
    # occupancy-triggered arm meter continuously at every demand level.
    ap.add_argument("--o-target-local", dest="o_target_local", type=float, default=9.0)
    ap.add_argument("--o-on-local", dest="o_on_local", type=float, default=9.5)
    ap.add_argument("--o-off-local", dest="o_off_local", type=float, default=7.0)
    ap.add_argument("--o-target-bn", dest="o_target_bn", type=float, default=8.5)
    ap.add_argument("--o-on-bn", dest="o_on_bn", type=float, default=9.5)
    ap.add_argument("--o-off-bn", dest="o_off_bn", type=float, default=7.0)
    ap.add_argument("--w-hi", dest="w_hi", type=float, default=0.60)
    ap.add_argument("--w-lo", dest="w_lo", type=float, default=0.35)
    ap.add_argument("--w-flush", dest="w_flush", type=float, default=0.85)
    ap.add_argument("--w-release", dest="w_release", type=float, default=0.50)
    ap.add_argument("--fixed-rate", dest="fixed_rate", type=float, default=700.0)
    a = ap.parse_args()
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    m = run(a)
    print(json.dumps({k: v for k, v in m.items() if k != "teleport_ids"}))
