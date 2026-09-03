#!/usr/bin/env python3
"""
STEP 5 - design study at a fixed design-hour demand.

 (a) sweep booth count c and find the minimum c* that keeps 95th-percentile plaza delay
     under a stated threshold AND keeps the queue inside the available upstream storage;
     locate the spillback point where the queue reaches the 2-lane mainline and mainline
     throughput collapses.
 (b) sweep ETC/transponder penetration 0..100% under two lane policies (2 dedicated ETC
     booths vs all-mixed-use booths) and find where dedication stops helping and where the
     plaza can be replaced by open-road all-electronic tolling.
 (c) cross-check the all-electronic endpoint against the e3-detector cordon abstraction.
"""
import itertools
import json
import multiprocessing as mp
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plaza_lib as P
import metrics as M

HERE = os.path.dirname(os.path.abspath(__file__))
EP = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
RUNS = os.path.join(EP, "attempts", "attempt-1", "runs", "design")
NETD = os.path.join(EP, "outputs", "network")
OUT = os.path.join(EP, "outputs")

DESIGN_DEMAND = 1500.0        # veh/h design hour
HORIZON, WARM, W1 = 5400.0, 900.0, 5400.0
SEEDS = [101, 202, 303]
P95_THRESHOLD = 120.0         # s, stated 95th-percentile plaza-delay design threshold
APP_STORAGE_M = 1196.0        # compiled length of the 2-lane mainline approach


def launch(job):
    tag, net, booths, extra, seed = job
    d = os.path.join(RUNS, tag)
    cmd = [sys.executable, os.path.join(HERE, "run_plaza.py"),
           "--run-dir", d, "--net", net, "--booths", str(booths),
           "--rate", "%.2f" % DESIGN_DEMAND, "--horizon", str(HORIZON),
           "--end-pad", "5400", "--seed", str(seed),
           "--service-dist", "exp", "--service-mean", "8"] + extra
    r = subprocess.run(cmd, capture_output=True, text=True)
    return tag, r.returncode, r.stderr[-1200:]


def launch_ff(job):
    """Free-flow calibration run for one net: negligible demand, long horizon."""
    tag, net, c, _, seed = job
    d = os.path.join(RUNS, tag)
    cmd = [sys.executable, os.path.join(HERE, "run_plaza.py"),
           "--run-dir", d, "--net", net, "--booths", str(c),
           "--rate", "60", "--horizon", "14400", "--end-pad", "2400",
           "--seed", str(seed), "--service-dist", "exp", "--service-mean", "8"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return tag, r.returncode, r.stderr[-800:]


def main():
    os.makedirs(RUNS, exist_ok=True)
    jobs, ffjobs = [], []
    CS = [3, 4, 5, 6, 7, 8]
    for c in CS:
        net = os.path.join(NETD, "plaza_c%d.net.xml" % c)
        ffjobs.append(("ff_c%d" % c, net, c, ["--ff"], 999))
        for s in SEEDS:
            jobs.append(("c%d_s%d" % (c, s), net, c, [], s))

    PENS = [0.0, 0.2, 0.4, 0.6, 0.8, 0.9, 1.0]
    net6 = os.path.join(NETD, "plaza_c6.net.xml")
    net6e = os.path.join(NETD, "plaza_c6_etc2.net.xml")
    for pen, s in itertools.product(PENS, SEEDS):
        jobs.append(("mix_p%03d_s%d" % (round(pen * 100), s), net6, 6,
                     ["--etc-share", str(pen)], s))
        jobs.append(("ded_p%03d_s%d" % (round(pen * 100), s), net6e, 6,
                     ["--etc-share", str(pen), "--etc-booths", "2"], s))
        # penetration-MATCHED dedication: k = round(6*pen) booths reserved, clamped to 1..5
        k = int(min(5, max(1, round(6 * pen))))
        jobs.append(("dmt_p%03d_s%d" % (round(pen * 100), s),
                     os.path.join(NETD, "plaza_c6_etc%d.net.xml" % k), 6,
                     ["--etc-share", str(pen), "--etc-booths", str(k)], s))
    # open-road all-electronic tolling reference + the cordon-abstraction cross-check
    for s in SEEDS:
        jobs.append(("ort_s%d" % s, net6, 6, ["--no-stops"], s))

    with mp.Pool(8) as pool:
        for t, rc, e in pool.imap_unordered(launch_ff, ffjobs):
            if rc:
                print("FF FAIL", t, e)
        for t, rc, e in pool.imap_unordered(launch, jobs):
            if rc:
                print("FAIL", t, e)
    print("design runs done")

    TFF = {}
    for c in CS:
        d = os.path.join(RUNS, "ff_c%d" % c)
        TFF[c] = (M.calibrate_tff(d, c), M.calibrate_tff_bin(d, c))

    def collect(pre, c, extra_keys=()):
        out = []
        for s in SEEDS:
            d = os.path.join(RUNS, "%s_s%d" % (pre, s))
            tff, tffb = TFF[c]
            m = M.run_metrics(d, c, tff, WARM, W1, HORIZON, tff_bin=tffb)
            if m is None:
                continue
            # served throughput at the plaza exit, from the booth departure loops
            inst = P.parse_instant(os.path.join(d, "instant.xml"))
            n_out = sum(1 for b in range(c) for t, _ in inst.get("dep_%d" % b, [])
                        if WARM <= t <= W1)
            m["served_vph"] = n_out / (W1 - WARM) * 3600.0
            tri = P.parse_tripinfo(os.path.join(d, "tripinfo.xml"))
            m["mean_departDelay_all"] = float(np.mean([t["departDelay"] for t in tri])) if tri else 0.0
            m["n_completed_total"] = len(tri)
            e3 = [r for r in P.parse_e3(os.path.join(d, "e3.xml"))
                  if WARM <= r["begin"] <= W1 and r["vehicleSum"] > 0]
            m["e3_meanTimeLoss"] = float(np.average([r["meanTimeLoss"] for r in e3],
                                         weights=[r["vehicleSum"] for r in e3])) if e3 else float("nan")
            out.append(m)
        return out

    # ---------------- (a) booth-count sizing ---------------- #
    res_a = []
    for c in CS:
        R = collect("c%d" % c, c)
        if not R:
            continue
        p95, p95h = P.mean_ci([r["Wq_p95"] for r in R])
        wq, wqh = P.mean_ci([r["Wq_mean"] for r in R])
        jam, jamh = P.mean_ci([r["max_jam_app_m"] for r in R])
        srv, srvh = P.mean_ci([r["served_vph"] for r in R])
        dd, _ = P.mean_ci([r["mean_departDelay_all"] for r in R])
        cap = c * 3600.0 / 12.438
        res_a.append(dict(c=c, capacity_vph=cap, rho=DESIGN_DEMAND / cap,
                          Wq_mean=wq, Wq_mean_ci=wqh, Wq_p95=p95, Wq_p95_ci=p95h,
                          max_jam_app_m=jam, max_jam_app_ci=jamh,
                          served_vph=srv, served_ci=srvh, mean_departDelay=dd,
                          teleports=int(sum(r["teleports"] for r in R)),
                          e3_meanTimeLoss=float(np.mean([r["e3_meanTimeLoss"] for r in R])),
                          meets_p95=bool(p95 < P95_THRESHOLD),
                          # a jam AT the ceiling is a saturated-storage artifact, and any
                          # non-trivial departDelay means demand could no longer be inserted
                          within_storage=bool(jam < 0.95 * APP_STORAGE_M and dd < 5.0)))
        print("c=%d cap=%6.0f rho=%.3f  Wq=%8.2f  p95=%9.2f  maxjam_app=%7.1f m  "
              "served=%7.1f veh/h  departDelay=%8.1f s  teleports=%d  [p95 ok=%s, storage ok=%s]"
              % (c, cap, DESIGN_DEMAND / cap, wq, p95, jam, srv, dd,
                 int(sum(r["teleports"] for r in R)),
                 p95 < P95_THRESHOLD, jam < APP_STORAGE_M))
    cstar = min([r["c"] for r in res_a if r["meets_p95"] and r["within_storage"]], default=None)
    print("\nc* (min booths meeting p95<%.0fs AND queue within %.0f m storage) = %s"
          % (P95_THRESHOLD, APP_STORAGE_M, cstar))

    # ---------------- (b) ETC penetration ---------------- #
    res_b = []
    for pen in PENS:
        row = dict(penetration=pen)
        for pol, pre in (("mixed", "mix"), ("dedicated2", "ded"), ("dedicated_matched", "dmt")):
            R = collect("%s_p%03d" % (pre, round(pen * 100)), 6)
            if not R:
                continue
            wq, wqh = P.mean_ci([r["Wq_mean"] for r in R])
            p95, _ = P.mean_ci([r["Wq_p95"] for r in R])
            jam, _ = P.mean_ci([r["max_jam_app_m"] for r in R])
            srv, _ = P.mean_ci([r["served_vph"] for r in R])
            dd, _ = P.mean_ci([r["mean_departDelay_all"] for r in R])
            row[pol] = dict(Wq=wq, Wq_ci=wqh, Wq_p95=p95, max_jam_app_m=jam,
                            served_vph=srv, mean_departDelay=dd,
                            e3_meanTimeLoss=float(np.mean([r["e3_meanTimeLoss"] for r in R])),
                            teleports=int(sum(r["teleports"] for r in R)))
        res_b.append(row)
        if "mixed" in row and "dedicated2" in row and "dedicated_matched" in row:
            print("pen %3.0f%%  mixed Wq=%7.2f+-%.2f (p95 %7.2f, e3TL %6.2f) | ded-2 Wq=%8.2f "
                  "(p95 %8.2f) | ded-matched(k=%d) Wq=%8.2f+-%.2f (p95 %8.2f) | "
                  "matched-mixed=%+8.2f s"
                  % (pen * 100, row["mixed"]["Wq"], row["mixed"]["Wq_ci"], row["mixed"]["Wq_p95"],
                     row["mixed"]["e3_meanTimeLoss"],
                     row["dedicated2"]["Wq"], row["dedicated2"]["Wq_p95"],
                     int(min(5, max(1, round(6 * pen)))),
                     row["dedicated_matched"]["Wq"], row["dedicated_matched"]["Wq_ci"],
                     row["dedicated_matched"]["Wq_p95"],
                     row["dedicated_matched"]["Wq"] - row["mixed"]["Wq"]))

    # ---------------- (c) open-road tolling / cordon cross-check ---------------- #
    ort = []
    for s in SEEDS:
        d = os.path.join(RUNS, "ort_s%d" % s)
        inst = P.parse_instant(os.path.join(d, "instant.xml"))
        n_out = sum(1 for b in range(6) for t, _ in inst.get("dep_%d" % b, []) if WARM <= t <= W1)
        e3 = [r for r in P.parse_e3(os.path.join(d, "e3.xml"))
              if WARM <= r["begin"] <= W1 and r["vehicleSum"] > 0]
        tri = P.parse_tripinfo(os.path.join(d, "tripinfo.xml"))
        ort.append(dict(served_vph=n_out / (W1 - WARM) * 3600.0,
                        e3_meanTravelTime=float(np.average([r["meanTravelTime"] for r in e3],
                                                weights=[r["vehicleSum"] for r in e3])),
                        e3_meanTimeLoss=float(np.average([r["meanTimeLoss"] for r in e3],
                                              weights=[r["vehicleSum"] for r in e3])),
                        e3_L=float(np.mean([r["vehicleSumWithin"] for r in e3])),
                        mean_timeLoss=float(np.mean([t["timeLoss"] for t in tri])),
                        mean_waiting=float(np.mean([t["waitingTime"] for t in tri])),
                        max_jam_app_m=max([x[1] for k, v in P.parse_e2(os.path.join(d, "e2.xml")).items()
                                           if k.startswith("q_app") for x in v] + [0.0])))
    ortm = {k: float(np.mean([o[k] for o in ort])) for k in ort[0]}
    print("\nopen-road all-electronic (no booth stop at all): served=%.0f veh/h, e3 zone "
          "travel time=%.2f s, e3 zone time loss=%.2f s, e3 L=%.2f veh, max app jam=%.1f m"
          % (ortm["served_vph"], ortm["e3_meanTravelTime"], ortm["e3_meanTimeLoss"],
             ortm["e3_L"], ortm["max_jam_app_m"]))

    json.dump(dict(design_demand_vph=DESIGN_DEMAND, p95_threshold_s=P95_THRESHOLD,
                   app_storage_m=APP_STORAGE_M, seeds=SEEDS, c_star=cstar,
                   booth_count_sweep=res_a, etc_penetration=res_b, open_road=ortm,
                   open_road_per_seed=ort),
              open(os.path.join(OUT, "step5_design_study.json"), "w"), indent=1)
    print("\nwrote", os.path.join(OUT, "step5_design_study.json"))


if __name__ == "__main__":
    main()
