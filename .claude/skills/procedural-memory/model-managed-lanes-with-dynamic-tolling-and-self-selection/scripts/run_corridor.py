#!/usr/bin/env python3
"""
Run one managed-lane policy arm on the corridor.

Arms
  A  gp4 network, all 4 lanes general purpose, no controller
  B  managed network, lane 3 = allow "hov bus" (static HOV), no controller
  C  managed network + HOT: SOVs may BUY IN at a FIXED toll
  D  managed network + HOT: SOVs may BUY IN at an ALINEA-style DYNAMIC toll

Self-selection (arms C/D): at corridor entry each SOV estimates its own time saving from
the managed lane using the *currently measured* per-lane corridor speeds, and buys in iff
      (estimated time saving [h])  x  (its own VOT [$/h])  >  current toll [$]
Eligibility is granted by switching the vehicle's vClass to "hov"
(traci.vehicle.setVehicleClass), which is what makes the lane legal for it.

ALINEA toll regulator (arm D), on managed-lane occupancy from E2 detectors:
      toll(k) = clip( toll(k-1) + K * (occ_measured(k) - occ_target), toll_min, toll_max )
"""
import argparse
import csv
import os
import subprocess
import sys

sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import traci  # noqa: E402

MAIN = [f"m{i}" for i in range(1, 15)]
DECISION_EDGES = MAIN[3:]          # m4..m14: the section a managed lane can actually help on
ML = 3                             # managed lane index
E2_ML_EDGES = ["m7", "m10", "m12"]  # ALINEA measurement points on the managed lane
E2_GP_EDGES = ["m7", "m10", "m12"]
EXIT_EDGE = "m14"


# --------------------------------------------------------------------------- #
def write_additional(path, outdir):
    L = ['<additional>']
    for e in E2_ML_EDGES:
        L.append(f'    <laneAreaDetector id="e2_ml_{e}" lane="{e}_{ML}" pos="5" length="480" '
                 f'period="60" file="{outdir}/e2.xml"/>')
    for e in E2_GP_EDGES:
        for ln in range(3):
            L.append(f'    <laneAreaDetector id="e2_gp_{e}_{ln}" lane="{e}_{ln}" pos="5" length="480" '
                     f'period="60" file="{outdir}/e2.xml"/>')
    for ln in range(4):
        L.append(f'    <inductionLoop id="e1_exit_{ln}" lane="{EXIT_EDGE}_{ln}" pos="-20" '
                 f'period="300" file="{outdir}/e1_exit.xml"/>')
    L.append(f'    <edgeData id="ed" period="300" file="{outdir}/edgedata.xml" excludeEmpty="false"/>')
    L.append(f'    <laneData id="ld" period="600" file="{outdir}/lanedata.xml" excludeEmpty="false"/>')
    L.append('</additional>')
    open(path, "w").write("\n".join(L))


def nudge(conn, vid):
    """A managed-lane-eligible vehicle actively seeks the managed lane instead of keeping
    right.  This is the behavioural content of managed-lane ELIGIBILITY and is applied only
    in the managed-lane arms (B/C/D); arm A keeps ordinary keep-right behaviour for all."""
    conn.vehicle.setParameter(vid, "laneChangeModel.lcKeepRight", "0")
    conn.vehicle.setParameter(vid, "laneChangeModel.lcSpeedGain", "2.5")


def load_fleet(csvpath):
    fleet = {}
    with open(csvpath) as f:
        for r in csv.DictReader(f):
            fleet[r["id"]] = {"cls": r["cls"], "occ": int(r["occ"]), "vot": float(r["vot"]),
                              "route": r["route"], "depart_plan": float(r["depart"])}
    return fleet


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True, choices=["A", "B", "C", "D"])
    ap.add_argument("--net", required=True)
    ap.add_argument("--routes", required=True)
    ap.add_argument("--fleet", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--toll", type=float, default=0.0, help="fixed toll ($) for arm C")
    ap.add_argument("--toll-init", type=float, default=1.0, help="initial toll ($) for arm D")
    ap.add_argument("--occ-target", type=float, default=11.0, help="ALINEA managed-lane occupancy setpoint (%)")
    ap.add_argument("--alinea-k", type=float, default=0.25, help="$ per occupancy point")
    ap.add_argument("--toll-min", type=float, default=0.10)
    ap.add_argument("--toll-max", type=float, default=20.0)
    ap.add_argument("--control-interval", type=float, default=60.0)
    ap.add_argument("--speed-interval", type=float, default=30.0)
    ap.add_argument("--ema", type=float, default=0.35)
    ap.add_argument("--time-to-teleport", type=float, default=300.0)
    ap.add_argument("--end", type=float, default=7800.0)
    ap.add_argument("--lanechange-output", action="store_true")
    ap.add_argument("--ssm", type=float, default=0.0, help="ssm device probability (0 = off)")
    ap.add_argument("--nudge-in-a", action="store_true",
                    help="control: also apply the managed-lane-seeking nudge to hov/bus in arm A, "
                         "to test whether the asymmetric nudge (B/C/D only) biases the baseline")
    a = ap.parse_args()

    outdir = os.path.abspath(a.outdir)
    os.makedirs(outdir, exist_ok=True)
    add = os.path.join(outdir, "detectors.add.xml")
    write_additional(add, outdir)

    cmd = ["sumo", "-n", os.path.abspath(a.net), "-r", os.path.abspath(a.routes),
           "-a", add,
           "--tripinfo-output", f"{outdir}/tripinfo.xml",
           "--summary-output", f"{outdir}/summary.xml",
           "--seed", str(a.seed),
           "--time-to-teleport", str(a.time_to_teleport),
           "--duration-log.statistics", "true",
           "--no-step-log", "true",
           "--begin", "0", "--end", str(a.end),
           "--step-length", "1.0",
           "--default.speeddev", "0.0",     # dispersion comes from the vType speedFactor dist
           "--xml-validation", "never"]
    if a.lanechange_output:
        cmd += ["--lanechange-output", f"{outdir}/lanechanges.xml"]
    if a.ssm > 0:
        cmd += ["--device.ssm.probability", str(a.ssm),
                "--device.ssm.measures", "TTC DRAC PET",
                "--device.ssm.thresholds", "3.0 3.0 2.0",
                "--device.ssm.range", "60",
                "--device.ssm.extratime", "4.0",
                "--device.ssm.file", f"{outdir}/ssm.xml"]

    fleet = load_fleet(a.fleet)
    label = f"c{os.getpid()}_{os.path.basename(outdir)}"
    traci.start(cmd, label=label, stdout=open(f"{outdir}/sumo_stdout.log", "w"))
    conn = traci.getConnection(label)

    # corridor geometry for the time-saving estimator
    seglen = {e: conn.lane.getLength(f"{e}_0") for e in MAIN}
    dec_len = sum(seglen[e] for e in DECISION_EDGES)
    ff = conn.lane.getMaxSpeed("m1_0")

    v_gp = {e: ff for e in DECISION_EDGES}
    v_ml = {e: ff for e in DECISION_EDGES}

    toll = a.toll if a.arm == "C" else (a.toll_init if a.arm == "D" else 0.0)
    revenue = 0.0
    rec = {}                      # vid -> decision record
    ml_time = {}                  # vid -> seconds observed on the managed lane
    toll_rows = []
    ml_lanes = [f"{e}_{ML}" for e in MAIN]
    interval_offers = 0
    interval_buys = 0
    e2_ml_ids = [f"e2_ml_{e}" for e in E2_ML_EDGES]

    t = 0.0
    next_speed = 0.0
    next_ctrl = a.control_interval
    ML_SAMPLE = 5

    while conn.simulation.getMinExpectedNumber() > 0 and t < a.end:
        conn.simulationStep()
        t = conn.simulation.getTime()

        # ---- measure per-lane corridor speeds -------------------------------
        if t >= next_speed:
            next_speed += a.speed_interval
            for e in DECISION_EDGES:
                sp = [conn.lane.getLastStepMeanSpeed(f"{e}_{ln}") for ln in range(3)]
                n = [conn.lane.getLastStepVehicleNumber(f"{e}_{ln}") for ln in range(3)]
                tot = sum(n)
                cur_gp = (sum(s * c for s, c in zip(sp, n)) / tot) if tot > 0 else ff
                cur_ml = conn.lane.getLastStepMeanSpeed(f"{e}_{ML}")
                if conn.lane.getLastStepVehicleNumber(f"{e}_{ML}") == 0:
                    cur_ml = ff
                v_gp[e] = (1 - a.ema) * v_gp[e] + a.ema * max(cur_gp, 0.5)
                v_ml[e] = (1 - a.ema) * v_ml[e] + a.ema * max(cur_ml, 0.5)

        # ---- ALINEA dynamic toll (arm D) ------------------------------------
        if t >= next_ctrl:
            next_ctrl += a.control_interval
            occ = sum(conn.lanearea.getLastStepOccupancy(d) for d in e2_ml_ids) / len(e2_ml_ids)
            spd = [conn.lanearea.getLastStepMeanSpeed(d) for d in e2_ml_ids]
            spd = [s for s in spd if s >= 0]
            ml_speed = sum(spd) / len(spd) if spd else ff
            if a.arm == "D":
                toll = min(a.toll_max, max(a.toll_min, toll + a.alinea_k * (occ - a.occ_target)))
            t_gp = sum(seglen[e] / v_gp[e] for e in DECISION_EDGES)
            t_ml = sum(seglen[e] / v_ml[e] for e in DECISION_EDGES)
            toll_rows.append([f"{t:.0f}", f"{toll:.4f}", f"{occ:.3f}", f"{ml_speed:.3f}",
                              f"{t_gp:.1f}", f"{t_ml:.1f}", f"{max(0.0, t_gp - t_ml):.1f}",
                              interval_offers, interval_buys, f"{revenue:.2f}"])
            interval_offers = interval_buys = 0

        # ---- self-selection at corridor entry -------------------------------
        dep = conn.simulation.getDepartedIDList()
        if dep:
            t_gp = sum(seglen[e] / v_gp[e] for e in DECISION_EDGES)
            t_ml = sum(seglen[e] / v_ml[e] for e in DECISION_EDGES)
            saving_full = max(0.0, t_gp - t_ml)          # s over m4..m14
            for vid in dep:
                info = fleet.get(vid)
                if info is None:
                    continue
                cls = info["cls"]
                # fraction of the decision section this vehicle actually traverses
                route = conn.vehicle.getRoute(vid)
                own = sum(seglen[e] for e in route if e in DECISION_EDGES)
                frac = own / dec_len if dec_len > 0 else 0.0
                sav = saving_full * frac
                wtp = sav / 3600.0 * info["vot"] * 1.0   # SOV: 1 occupant
                r = {"est_saving_s": sav, "wtp": wtp, "toll_at_entry": toll,
                     "eligible": 0, "paid": 0.0, "offered": 0}
                if a.arm == "A":
                    r["eligible"] = 1                    # all 4 lanes are GP
                    if a.nudge_in_a and cls in ("hov", "bus"):
                        nudge(conn, vid)
                elif cls in ("hov", "bus"):
                    r["eligible"] = 1                    # free-of-charge eligibility
                    nudge(conn, vid)
                elif a.arm in ("C", "D"):
                    r["offered"] = 1
                    interval_offers += 1
                    if wtp > toll:
                        conn.vehicle.setVehicleClass(vid, "hov")
                        nudge(conn, vid)
                        r["eligible"] = 1
                        r["paid"] = toll
                        revenue += toll
                        interval_buys += 1
                rec[vid] = r

        # ---- managed-lane occupancy sampling per vehicle --------------------
        if int(t) % ML_SAMPLE == 0:
            for ln in ml_lanes:
                for vid in conn.lane.getLastStepVehicleIDs(ln):
                    ml_time[vid] = ml_time.get(vid, 0.0) + ML_SAMPLE

    # ---- final accounting of vehicles still in the network -------------------
    still = []
    for vid in conn.vehicle.getIDList():
        still.append((vid, conn.vehicle.getDeparture(vid), conn.vehicle.getDistance(vid)))
    teleports_live = conn.simulation.getStartingTeleportNumber()
    conn.close()

    # ---- write per-vehicle decision log -------------------------------------
    with open(f"{outdir}/decisions.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "cls", "occ", "vot", "route", "offered", "eligible", "paid",
                    "toll_at_entry", "est_saving_s", "wtp", "ml_seconds"])
        for vid, info in fleet.items():
            r = rec.get(vid)
            if r is None:
                continue
            w.writerow([vid, info["cls"], info["occ"], f"{info['vot']:.4f}", info["route"],
                        r["offered"], r["eligible"], f"{r['paid']:.4f}",
                        f"{r['toll_at_entry']:.4f}", f"{r['est_saving_s']:.2f}",
                        f"{r['wtp']:.4f}", f"{ml_time.get(vid, 0.0):.0f}"])

    with open(f"{outdir}/toll_log.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "toll", "ml_occ_pct", "ml_speed_mps", "gp_tt_s", "ml_tt_s",
                    "est_saving_s", "sov_offers", "sov_buys", "revenue_cum"])
        w.writerows(toll_rows)

    with open(f"{outdir}/still_running.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "depart", "distance_m"])
        w.writerows([[v, f"{d:.2f}", f"{x:.1f}"] for v, d, x in still])

    with open(f"{outdir}/run_meta.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["key", "value"])
        for k, v in [("arm", a.arm), ("net", a.net), ("routes", a.routes), ("seed", a.seed),
                     ("toll_fixed", a.toll), ("toll_final", toll), ("occ_target", a.occ_target),
                     ("alinea_k", a.alinea_k), ("revenue", f"{revenue:.2f}"),
                     ("sim_end_time", t), ("still_running", len(still)),
                     ("teleports_live", teleports_live),
                     ("fleet_size", len(fleet)), ("decisions_recorded", len(rec)),
                     ("time_to_teleport", a.time_to_teleport)]:
            w.writerow([k, v])
    print(f"[{a.arm}] {os.path.basename(outdir)} done t={t:.0f} revenue=${revenue:.2f} "
          f"still_running={len(still)} teleports={teleports_live}")


if __name__ == "__main__":
    main()
