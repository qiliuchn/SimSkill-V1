#!/usr/bin/env python3
"""
Drive los_report.py across the whole v/c x control x arrival-process sweep and
produce the comparison tables, the LOS agreement counts, the residual-queue bias
quantification and the plots.
"""
import os, sys, json, csv, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hcm_lib as H
import los_report as LR

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.abspath(os.path.join(HERE, "..", "runs"))
OUT = os.path.abspath(os.path.join(HERE, "..", "..", "..", "outputs"))
os.makedirs(OUT, exist_ok=True)
CFG = json.load(open(os.path.join(BASE, "sweep_config.json")))
XS = CFG["XS"]
ARRIVALS = ["uniform", "poisson"]
CONTROLS = ["pretimed", "actuated"]
LOS_IDX = {c: i for i, c in enumerate("ABCDEF")}

PERIODS = {
    "T1.0h_full":     dict(t0=0.0, t1=3600.0, trunc=None, qb=False),
    "T1.0h_trunc":    dict(t0=0.0, t1=3600.0, trunc=3600.0, qb=False),
    "T0.25h_first":   dict(t0=0.0, t1=900.0, trunc=None, qb=False),
    "T0.25h_last":    dict(t0=2700.0, t1=3600.0, trunc=None, qb=True),
}


def initial_queue(run, t):
    """HCM Qb per lane group (veh), read from the E2 chains at time t."""
    e2 = H.parse_e2(os.path.join(run, "queue.xml"))
    def at(det):
        rows = [r for r in e2.get(det, []) if r[0] <= t]
        return rows[-1][2] if rows else 0
    out = {}
    for a in LR.APPROACHES:
        out[(a, "L")] = at(f"q_{a}_Lall")
        out[(a, "TR")] = at(f"q_{a}_T0") + at(f"q_{a}_T1")
    return out


def main():
    recs = []
    for arr in ARRIVALS:
        for ctrl in CONTROLS:
            for X in XS:
                run = os.path.join(BASE, "sweep_" + arr, f"{ctrl}_X{int(round(X*100)):03d}")
                for pname, p in PERIODS.items():
                    qb = initial_queue(run, p["t0"]) if p["qb"] else None
                    res = LR.build(run, CFG, ctrl, p["t0"], p["t1"],
                                   truncate_at=p["trunc"], Qb_map=qb)
                    for r in res["rows"]:
                        recs.append(dict(arrivals=arr, control=ctrl, X_nominal=X,
                                         period=pname, cycle=res["cycle"],
                                         int_hcm=res["hcm_int_delay"],
                                         int_sim=res["sim_int_delay"],
                                         int_hcm_los=res["hcm_int_los"],
                                         int_sim_los=res["sim_int_los"], **r))
                print("  analysed", arr, ctrl, X)
    keys = list(recs[0].keys())
    with open(os.path.join(OUT, "sweep_results.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(recs)
    json.dump(recs, open(os.path.join(OUT, "sweep_results.json"), "w"), indent=1, default=str)
    print("wrote", os.path.join(OUT, "sweep_results.csv"), len(recs), "rows")
    return recs


def sel(recs, **kw):
    return [r for r in recs if all(r[k] == v for k, v in kw.items())]


def lg_mean(recs, field, **kw):
    """Mean of `field` over the four approaches of one lane group."""
    rs = sel(recs, **kw)
    v = [r[field] for r in rs if isinstance(r[field], float) and r[field] == r[field]]
    return sum(v) / len(v) if v else float("nan")


if __name__ == "__main__":
    main()
