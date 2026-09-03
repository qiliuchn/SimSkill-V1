#!/usr/bin/env python3
"""Experiment driver: defines every cell of the BEB study and runs them in parallel.

Common Random Numbers: the car route file and the person-demand file are generated
ONCE per seed and shared by every arm, so paired (per-seed) differences isolate the
treatment.  Seeds 1,2,3 are used everywhere.
"""
import os, sys, json, time, shutil, traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import runner as RN
import metrics as MT

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
RUNS = os.path.join(ROOT, "runs")
SEEDS = [1, 2, 3]

CAPS = [80, 120, 160, 200, 240]
CHARGERS = [0, 1, 2]
MIDDAY = dict(plan={"0": 0, "2": 1, "4": 2, "6": 3}, duration=1200)


def cells():
    C = []
    # --- A. feasibility frontier: battery capacity x terminal charger count
    for cap in CAPS:
        for nch in CHARGERS:
            for s in SEEDS:
                C.append(dict(tag=f"A_cap{cap}_ch{nch}_s{s}", kind="cli",
                              kw=dict(cap_kwh=cap, n_term_chargers=nch, seed=s,
                                      charger_policy="skip")))
    # --- B. H4 contrast: 1 charger, queueing policy instead of session truncation
    for cap in [120, 160]:
        for s in SEEDS:
            C.append(dict(tag=f"B_cap{cap}_ch1queue_s{s}", kind="cli",
                          kw=dict(cap_kwh=cap, n_term_chargers=1, seed=s,
                                  charger_policy="queue")))
    # --- C. H5 mass channel: identical sweep with vehicle mass held at the 200 kWh value
    for cap in CAPS:
        for s in SEEDS:
            C.append(dict(tag=f"C_cap{cap}_massfixed_s{s}", kind="cli",
                          kw=dict(cap_kwh=cap, n_term_chargers=2, seed=s,
                                  mass_mode="fixed")))
    # --- D/E. H1: TSP on/off x auxiliary load on/off (2x2), TraCI arms
    for tsp in ["off", "conditional"]:
        for aux in [7000, 0]:
            for s in SEEDS:
                C.append(dict(tag=f"D_tsp{tsp}_aux{aux}_s{s}", kind="traci", mode=tsp,
                              kw=dict(cap_kwh=240, n_term_chargers=2, seed=s, aux_w=aux)))
    # --- F. H2: regeneration on/off x stop density (12 vs 6 en-route stops)
    for recup in [0.85, 0.0]:
        for stride in [1, 2]:
            for s in SEEDS:
                C.append(dict(tag=f"F_rec{recup}_stride{stride}_s{s}", kind="cli",
                              kw=dict(cap_kwh=240, n_term_chargers=2, seed=s,
                                      recup=recup, stop_stride=stride)))
    # --- G. strategy (c): mid-day depot recharge, depot-only otherwise
    for cap in [120, 160]:
        for s in SEEDS:
            C.append(dict(tag=f"G_cap{cap}_midday_s{s}", kind="cli",
                          kw=dict(cap_kwh=cap, n_term_chargers=0, seed=s,
                                  midday_depot=MIDDAY)))
    # --- H. terminal charger power sweep at 1 charger
    for pw in [200, 300]:
        for cap in [80, 120]:
            for s in SEEDS:
                C.append(dict(tag=f"H_p{pw}_cap{cap}_ch1_s{s}", kind="cli",
                              kw=dict(cap_kwh=cap, n_term_chargers=1, seed=s,
                                      term_power_kw=pw, charger_policy="skip")))
    return C


def _one(c):
    d = os.path.join(RUNS, c["tag"])
    try:
        if c["kind"] == "cli":
            r = RN.run_cell(d, **c["kw"])
        else:
            import tsp_runner as TR
            r = TR.run_tsp(d, c["mode"], **c["kw"])
        m = MT.run_metrics(d, keep_traces=False)
        json.dump(m, open(os.path.join(d, "metrics.json"), "w"), indent=1)
        # battery.xml is ~50-90 MB per run: keep only for the traced reference cells
        keep = c["tag"] in KEEP_RAW
        if not keep:
            bp = os.path.join(d, "battery.xml")
            if os.path.exists(bp):
                os.remove(bp)
        return c["tag"], dict(run=r, ok=True)
    except Exception as e:
        return c["tag"], dict(ok=False, err=traceback.format_exc()[-2000:])


KEEP_RAW = set()


def main(only=None, workers=9):
    global KEEP_RAW
    os.makedirs(RUNS, exist_ok=True)
    C = cells()
    if only:
        C = [c for c in C if any(c["tag"].startswith(p) for p in only)]
    KEEP_RAW = {"A_cap160_ch2_s1", "A_cap120_ch1_s1", "A_cap200_ch0_s1",
                "D_tspoff_aux7000_s1", "D_tspoff_aux0_s1",
                "F_rec0.85_stride1_s1", "F_rec0.0_stride1_s1",
                "G_cap160_midday_s1", "A_cap80_ch2_s1"}
    # make the CRN demand files first (single-threaded) so workers don't race
    for s in SEEDS:
        RN.ensure_demand(s, RN.DEFAULTS["n_persons"])
    print(f"running {len(C)} cells on {workers} workers")
    t0 = time.time()
    res = {}
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_one, c): c["tag"] for c in C}
        done = 0
        for f in as_completed(futs):
            tag, r = f.result()
            res[tag] = r
            done += 1
            print(f"[{done}/{len(C)}] {tag} ok={r['ok']} ({time.time()-t0:.0f}s)", flush=True)
            if not r["ok"]:
                print(r["err"][-800:])
    json.dump(res, open(os.path.join(RUNS, "_driver.json"), "w"), indent=1)
    print(f"total {time.time()-t0:.0f}s; failures: {[k for k,v in res.items() if not v['ok']]}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--workers", type=int, default=9)
    a = ap.parse_args()
    main(a.only, a.workers)
