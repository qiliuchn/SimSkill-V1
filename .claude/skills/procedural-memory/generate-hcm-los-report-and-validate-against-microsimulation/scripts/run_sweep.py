#!/usr/bin/env python3
"""
Degree-of-saturation sweep: v/c from 0.40 to 1.15 per critical movement, under
BOTH a hand-written pretimed plan and an actuated plan with the same phase
skeleton.  Demand is varied; timing is NOT.

Each run loads demand over [0, 3600] s (the 1-hour analysis period) and then
keeps simulating to 7200 s so the residual queue drains: metrics can then be
computed EITHER truncated at 3600 s (the naive analysis, which silently drops
every vehicle still queued) OR over the full drain, and the difference is the
residual-queue bias.
"""
import os, sys, json, math
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scenario as S

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.abspath(os.path.join(HERE, "..", "runs"))
NET = os.path.join(BASE, "net_static", "intersection.net.xml")

# --- operational signal plan (measured lost time -> effective green) ---------
OP_GREEN = {"NSL": 15.0, "NST": 25.0, "EWL": 15.0, "EWT": 25.0}   # C = 100 s
DEMAND_END = 3600.0
SIM_END = 7200.0
XS = [0.40, 0.60, 0.75, 0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15]
CONTROLS = ["pretimed", "actuated"]
ARRIVALS = ["uniform", "poisson"]
SEED = 42
T_SHARE, R_SHARE = 0.882, 0.118      # within the through+right lane group


def load_calibration():
    p = os.path.join(BASE, "calib", "calibration.json")
    cal = json.load(open(p))
    sat = cal["saturation"]
    def avg(keys, field):
        return sum(sat[k][field] for k in keys) / len(keys)
    l0 = [f"sl_{a}_0" for a in S.APPROACHES]
    l1 = [f"sl_{a}_1" for a in S.APPROACHES]
    l2 = [f"sl_{a}_2" for a in S.APPROACHES]
    out = dict(
        s_lane0=avg(l0, "s_regression"), s_lane1=avg(l1, "s_regression"),
        s_lane0_win=avg(l0, "s_windowed"), s_lane1_win=avg(l1, "s_windowed"),
        s_LT=avg(l2, "s_regression"), s_LT_win=avg(l2, "s_windowed"),
        tL_TR=0.5 * (avg(l0, "tL_net_regression") + avg(l1, "tL_net_regression")),
        tL_LT=avg(l2, "tL_net_regression"),
        r2_min=min(sat[k]["r2"] for k in l0 + l1 + l2),
    )
    out["s_TR_per_lane"] = 0.5 * (out["s_lane0"] + out["s_lane1"])
    out["ff"] = {k: v["min"] for k, v in cal["freeflow"].items()}
    return out


def capacities(cal, green=OP_GREEN, cycle=S.CYCLE):
    """HCM lane-group capacity from MEASURED s and MEASURED net lost time."""
    gL = green["NSL"] - cal["tL_LT"]
    gT = green["NST"] - cal["tL_TR"]
    return dict(g_LT=gL, g_TR=gT, C=cycle,
                c_LT=1 * cal["s_LT"] * gL / cycle,
                c_TR=2 * cal["s_TR_per_lane"] * gT / cycle)


def demand_for(X, cap):
    vLT = X * cap["c_LT"]
    vTR = X * cap["c_TR"]
    vol = {}
    for a in S.APPROACHES:
        vol[(a, "L")] = vLT
        vol[(a, "T")] = vTR * T_SHARE
        vol[(a, "R")] = vTR * R_SHARE
    return vol


def one_run(args):
    X, control, arr, cap = args
    tag = f"{control}_X{int(round(X*100)):03d}"
    od = os.path.join(BASE, "sweep_" + arr, tag)
    os.makedirs(od, exist_ok=True)
    tls = S.write_tls(NET, os.path.join(od, "tls.add.xml"), control, OP_GREEN)
    det = S.write_detectors(NET, od, e2_freq=10.0, want_stopline=False)
    rou = S.write_routes(os.path.join(od, "routes.rou.xml"), demand_for(X, cap),
                         end=DEMAND_END, n_feed_lanes=2, arrivals=arr)
    S.run_sumo(NET, rou, [tls, det], od, end=SIM_END, step=0.1, seed=SEED)
    return arr + "/" + tag


if __name__ == "__main__":
    cal = load_calibration()
    cap = capacities(cal)
    print("measured inputs:")
    for k, v in sorted(cal.items()):
        if k != "ff":
            print(f"  {k:16s} {v if not isinstance(v,float) else round(v,2)}")
    print("capacities:", {k: round(v, 2) for k, v in cap.items()})
    json.dump(dict(cal=cal, cap=cap, XS=XS, OP_GREEN=OP_GREEN, CYCLE=S.CYCLE,
                   T_SHARE=T_SHARE, R_SHARE=R_SHARE, DEMAND_END=DEMAND_END,
                   SIM_END=SIM_END),
              open(os.path.join(BASE, "sweep_config.json"), "w"), indent=2)
    jobs = [(X, c, arr, cap) for arr in ARRIVALS for c in CONTROLS for X in XS]
    with ProcessPoolExecutor(max_workers=9) as ex:
        for tag in ex.map(one_run, jobs):
            print("  done", tag)
