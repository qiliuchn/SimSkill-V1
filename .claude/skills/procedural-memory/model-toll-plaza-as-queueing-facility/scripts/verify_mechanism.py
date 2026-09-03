#!/usr/bin/env python3
"""
STEP 2 - verify the booth service mechanism from RAW SUMO OUTPUT ONLY, and measure the
single-booth capacity actually delivered (as opposed to the 3600/E[S] textbook value).

For each mechanism variant we run a deliberately OVER-saturated plaza so every booth has a
standing queue, then read:
  * realized service times   <- stop-output (ended - started)
  * departure headways       <- instantInductionLoop on chout_i (per booth, 'enter' events)
  * per-booth capacity        = 3600 / mean(headway) in the saturated window
"""
import json
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plaza_lib as P

HERE = os.path.dirname(os.path.abspath(__file__))
EP = os.path.abspath(os.path.join(HERE, "..", "..", ".."))          # episode root
RUNS = os.path.join(EP, "attempts", "attempt-1", "runs")
NET = os.path.join(EP, "outputs", "network", "plaza_c6.net.xml")
W0, W1 = 600.0, 1500.0                                        # saturated measurement window


def one(tag, extra, rate=2600.0, horizon=1800.0):
    d = os.path.join(RUNS, "mech_" + tag)
    cmd = [sys.executable, os.path.join(HERE, "run_plaza.py"),
           "--run-dir", d, "--net", NET, "--rate", str(rate),
           "--horizon", str(horizon), "--end-pad", "2400", "--seed", "11"] + extra
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(tag + ": " + r.stderr[-2000:])
    return d


def analyse(tag, d, intended_mean, has_stops=True, rate=2600.0):
    res = {"variant": tag, "offered_rate_vph": rate,
           "arrival_headway_per_booth_s": 3600.0 / (rate / 6.0)}
    meta = json.load(open(os.path.join(d, "meta_full.json")))
    if has_stops:
        st = [s for s in P.parse_stops(os.path.join(d, "stops.xml")) if W0 <= s["started"] <= W1]
        dur = np.array([s["dur"] for s in st])
        res["n_services_in_window"] = len(dur)
        res["realized_service_mean_s"] = float(dur.mean())
        res["realized_service_sd_s"] = float(dur.std(ddof=1))
        res["realized_service_CV"] = float(dur.std(ddof=1) / dur.mean())
        res["realized_service_p95_s"] = float(np.percentile(dur, 95))
        # intended draws for exactly those vehicles
        idx = [int(s["veh"][1:]) for s in st]
        want = np.array([meta["svc"][i] for i in idx])
        res["intended_service_mean_s"] = float(want.mean())
        res["intended_service_CV"] = float(want.std(ddof=1) / want.mean())
        res["mean_rounding_bias_s"] = float((dur - want).mean())
        # DIRECT measurement of the move-up ("headway floor"): at a saturated booth the
        # next vehicle is already waiting, so started[k+1] - ended[k] is purely the time
        # for the follower to release, accelerate and roll forward into the booth.
        gaps = []
        for b in range(6):
            sb = sorted([s2 for s2 in P.parse_stops(os.path.join(d, "stops.xml"))
                         if s2["booth"] == b and W0 <= s2["started"] <= W1],
                        key=lambda z: z["started"])
            gaps += [sb[k + 1]["started"] - sb[k]["ended"] for k in range(len(sb) - 1)]
        g = np.array(gaps)
        res["n_inter_service_gaps"] = len(g)
        res["mean_inter_service_gap_s"] = float(g.mean())
        res["median_inter_service_gap_s"] = float(np.median(g))
        res["p10_inter_service_gap_s"] = float(np.percentile(g, 10))
        res["frac_gaps_under_6s"] = float((g < 6.0).mean())
    else:
        res["realized_service_mean_s"] = None

    inst = P.parse_instant(os.path.join(d, "instant.xml"))
    hs, per_booth = [], {}
    for b in range(6):
        ts = np.array([t for t, _ in inst.get("dep_%d" % b, []) if W0 <= t <= W1])
        h = np.diff(ts)
        per_booth[b] = dict(n=len(ts), mean_headway=float(h.mean()) if len(h) else None,
                            cap_vph=float(3600.0 / h.mean()) if len(h) else None)
        hs.append(h)
    allh = np.concatenate(hs)
    res["mean_departure_headway_s"] = float(allh.mean())
    res["sd_departure_headway_s"] = float(allh.std(ddof=1))
    res["CV_departure_headway"] = float(allh.std(ddof=1) / allh.mean())
    res["min_departure_headway_s"] = float(allh.min())
    res["p05_departure_headway_s"] = float(np.percentile(allh, 5))
    res["per_booth_capacity_vph"] = float(3600.0 / allh.mean())
    res["plaza_capacity_vph"] = 6 * res["per_booth_capacity_vph"]
    res["theoretical_per_booth_cap_vph"] = 3600.0 / intended_mean
    res["theoretical_plaza_cap_vph"] = 6 * 3600.0 / intended_mean
    res["capacity_shortfall_pct"] = 100.0 * (1 - res["plaza_capacity_vph"] / res["theoretical_plaza_cap_vph"])
    if has_stops:
        res["headway_floor_s"] = res["mean_departure_headway_s"] - res["realized_service_mean_s"]
    res["saturated"] = bool(res["mean_departure_headway_s"] > 1.15 * res["arrival_headway_per_booth_s"])
    res["per_booth"] = per_booth
    res["teleports"] = P.parse_summary_teleports(os.path.join(d, "summary.xml"))
    return res


def main():
    out = []
    variants = [
        ("exp8", ["--service-dist", "exp", "--service-mean", "8"], 8.0, True, 2600.0),
        ("erlang8_m8", ["--service-dist", "erlang8", "--service-mean", "8"], 8.0, True, 2600.0),
        ("det8", ["--service-dist", "det", "--service-mean", "8"], 8.0, True, 2600.0),
        ("exp3", ["--service-dist", "exp", "--service-mean", "3"], 3.0, True, 4200.0),
        ("vss8", ["--booth-speed-service", "--service-mean", "8"], 8.0, False, 5200.0),
        ("nostop", ["--no-stops"], 8.0, False, 5200.0),
    ]
    for tag, extra, m, hs, rate in variants:
        d = one(tag, extra, rate=rate)
        r = analyse(tag, d, m, hs, rate=rate)
        out.append(r)
        print("== %-11s SAT=%-5s realized_S=%s CV_S=%s  headway=%.3fs (CV %.3f, min %.2f)  "
              "booth_cap=%.0f vs theory %.0f veh/h  shortfall %.1f%%  gap=%s teleports=%d"
              % (tag, r["saturated"],
                 ("%.3f" % r["realized_service_mean_s"]) if r["realized_service_mean_s"] else "n/a",
                 ("%.3f" % r["realized_service_CV"]) if r.get("realized_service_CV") else "n/a",
                 r["mean_departure_headway_s"], r["CV_departure_headway"],
                 r["min_departure_headway_s"],
                 r["per_booth_capacity_vph"], r["theoretical_per_booth_cap_vph"],
                 r["capacity_shortfall_pct"],
                 ("%.2f" % r["mean_inter_service_gap_s"]) if "mean_inter_service_gap_s" in r else "n/a",
                 r["teleports"]))
    json.dump(out, open(os.path.join(EP, "outputs", "step2_mechanism_verification.json"), "w"), indent=1)
    print("\nwritten:", os.path.join(EP, "outputs", "step2_mechanism_verification.json"))


if __name__ == "__main__":
    main()
