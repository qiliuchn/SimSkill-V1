"""Score every AID algorithm with the standard operational metrics, over the full
threshold grid, for every (demand level, station spacing) cell.

Metrics
  DR   detection rate               = detected incident days / incident days
  FAR  false alarm rate             = alarm onsets on CONTROL days per decision-unit-hour,
                                      and per control day
  MTTD mean time to detect          = mean(t_alarm_end - t_injection) over DETECTED incidents
  LOC  localization error           = |station index of alarm - true nearest-upstream station|,
                                      in stations of the operative spacing
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import *
import numpy as np
import aid_algorithms as A

SPACINGS = (250, 500, 1000)
J0 = int(WARMUP / DET_PERIOD)           # first scored interval (t = 600 s)
J1 = int(SIM_END / DET_PERIOD)
SCORED_HOURS = (J1 - J0) * DET_PERIOD / 3600.0
CLEAR_GRACE = 120.0                     # alarm still counts as a detection this long past clearance


# ------------------------------------------------------------------ data loading
def load(level):
    inc, ctl = [], []
    for s in range(1, N_SEEDS + 1):
        for arm, bucket in (("incident", inc), ("control", ctl)):
            d = os.path.join(RUNS_DIR, level, f"{arm}_s{s:03d}")
            z = np.load(os.path.join(d, "det.npz"))
            m = json.load(open(os.path.join(d, "meta.json")))
            bucket.append({"occ": z["occ"], "spd": z["spd"], "vol": z["vol"], "meta": m})
    return inc, ctl


def truth(meta, stations):
    """Nearest station AT OR UPSTREAM of the incident, as an index into `stations`."""
    inc = meta["incident"]
    x = inc["x"]
    idx = [i for i, k in enumerate(stations) if STATION_X[k] <= x]
    return (idx[-1] if idx else None), inc


# ------------------------------------------------------------------ one algorithm/param cell
def evaluate(algo, params, inc_days, ctl_days, stations, spacing):
    fn = A.ALGOS[algo]
    pair = algo in A.PAIRWISE
    n_units = (len(stations) - 1) if pair else len(stations)

    # ---- false alarms: control days only
    fa = 0
    for d in ctl_days:
        sig = d["spd"][stations] if algo in A.SPEED_BASED else d["occ"][stations]
        fa += len(fn(sig, J0, J1, **params))
    far_per_unit_hr = fa / (n_units * SCORED_HOURS * len(ctl_days))
    far_per_day = fa / len(ctl_days)

    # ---- detections: incident days
    det, ttd, loc = 0, [], []
    n_eval = 0
    per_day = []
    for d in inc_days:
        u, inc = truth(d["meta"], stations)
        if u is None:
            continue
        n_eval += 1
        t0 = d["meta"]["injected_t"]
        t1 = t0 + inc["dur"] + CLEAR_GRACE
        sig = d["spd"][stations] if algo in A.SPEED_BASED else d["occ"][stations]
        ev = fn(sig, J0, J1, **params)
        # spatially valid: at the incident's own upstream station, up to 2 stations further
        # upstream (queue propagates upstream), or the first station downstream of it
        lo, hi = u - 2, u + 1
        if pair:
            lo, hi = u - 2, u          # pair (i, i+1) is labelled by upstream station i
        cand = [(t, i) for (t, i) in ev if t0 <= t <= t1 and lo <= i <= hi]
        if cand:
            t, i = min(cand)
            det += 1
            ttd.append(t - t0)
            loc.append(abs(i - u))
            per_day.append({"seed": d["meta"]["seed"], "detected": True, "ttd": t - t0,
                            "loc": abs(i - u), "n_block": inc["n_block"], "seg": inc["seg"],
                            "x": inc["x"], "u": u, "dist_to_upstream_station":
                            inc["x"] - STATION_X[stations[u]], "dur": inc["dur"]})
        else:
            per_day.append({"seed": d["meta"]["seed"], "detected": False, "ttd": None,
                            "loc": None, "n_block": inc["n_block"], "seg": inc["seg"],
                            "x": inc["x"], "u": u, "dist_to_upstream_station":
                            inc["x"] - STATION_X[stations[u]], "dur": inc["dur"]})
    return {"algo": algo, "params": params, "spacing": spacing,
            "n_units": n_units, "n_incident_days": n_eval,
            "DR": det / max(n_eval, 1), "FAR_per_unit_hour": far_per_unit_hr,
            "FAR_per_day": far_per_day, "n_false_alarms": fa,
            "MTTD": float(np.mean(ttd)) if ttd else None,
            "MTTD_median": float(np.median(ttd)) if ttd else None,
            "LOC_mean": float(np.mean(loc)) if loc else None,
            "per_day": per_day}


def pareto(rows):
    """Upper-left frontier in (FAR_per_unit_hour, DR): keep rows not dominated by another
    row with both <= FAR and >= DR."""
    out = []
    for r in rows:
        dominated = any((o["FAR_per_unit_hour"] <= r["FAR_per_unit_hour"] and o["DR"] >= r["DR"]
                         and (o["FAR_per_unit_hour"] < r["FAR_per_unit_hour"] or o["DR"] > r["DR"]))
                        for o in rows)
        if not dominated:
            out.append(r)
    return sorted(out, key=lambda r: r["FAR_per_unit_hour"])


if __name__ == "__main__":
    os.makedirs(RESULTS_DIR, exist_ok=True)
    G = A.grids()
    all_rows = {}
    for level in DEMAND_LEVELS:
        inc_days, ctl_days = load(level)
        for spacing in SPACINGS:
            stations = stations_for_spacing(spacing)
            for algo in A.ALGOS:
                rows = [evaluate(algo, p, inc_days, ctl_days, stations, spacing)
                        for p in G[algo]]
                all_rows[(level, spacing, algo)] = rows
                fr = pareto(rows)
                best = max(rows, key=lambda r: (r["DR"] - 0.0, -r["FAR_per_unit_hour"]))
                print(f"{level:9s} sp{spacing:4d} {algo:12s} grid={len(rows):3d} "
                      f"frontier={len(fr):2d} maxDR={max(r['DR'] for r in rows):.2f}")
    # persist (drop per_day from the bulk dump, keep it only for frontier points)
    dump = []
    for (level, spacing, algo), rows in all_rows.items():
        fr_ids = {id(r) for r in pareto(rows)}
        for r in rows:
            rr = {k: v for k, v in r.items() if k != "per_day"}
            rr.update(level=level, on_frontier=id(r) in fr_ids)
            if rr["on_frontier"]:
                rr["per_day"] = r["per_day"]
            dump.append(rr)
    with open(os.path.join(RESULTS_DIR, "sweep_all.json"), "w") as f:
        json.dump(dump, f)
    print("wrote", os.path.join(RESULTS_DIR, "sweep_all.json"), len(dump), "rows")
