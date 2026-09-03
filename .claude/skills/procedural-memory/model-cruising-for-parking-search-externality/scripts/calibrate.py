"""Calibration probe: map the demand index to realised occupancy, under BOTH
normalisations (curb-capacity, used for the study; total-capacity, discarded).
Writes data/calibration.json from the retained probe runs."""
import json, os, statistics, subprocess, sys
from concurrent.futures import ProcessPoolExecutor
from common import RUN_DIR, DATA_DIR

HERE = os.path.dirname(os.path.abspath(__file__))
LEVELS_CURB = [0.60, 0.70, 0.80, 0.88, 0.94, 1.00, 1.06, 1.15, 1.30, 1.50, 1.75]
LEVELS_TOTAL = [0.72, 0.86, 1.00, 1.24, 1.48, 1.75, 2.10]


def one(args):
    mode, o = args
    d = os.path.join(RUN_DIR, "calib_%s_%.2f" % (mode, o))
    os.makedirs(d, exist_ok=True)
    if not os.path.exists(os.path.join(d, "result.json")):
        p = subprocess.run([sys.executable, os.path.join(HERE, "run_scenario.py"), "--out", d,
                            "--cfg", json.dumps(dict(seed=1, occ=o, ref_mode=mode, label="cal"))],
                           capture_output=True, text=True, cwd=HERE)
        if p.returncode:
            return dict(mode=mode, occ_index=o, error=p.stderr[-400:])
    r = json.load(open(os.path.join(d, "result.json")))
    kind, cap = r["lot_kind"], r["lot_cap"]
    ccap = sum(v for k, v in cap.items() if kind[k] == "curb")
    ser = [(t, s) for t, s in r["occupancy"] if 1500 <= t <= 3600]
    curb = [sum(v for k, v in s.items() if kind[k] == "curb") / ccap for _, s in ser]
    tot = [sum(s.values()) / r["capacity"] for _, s in ser]
    P = r["parkers"]
    sr = [q["search_t"] for q in P if q["search_t"] is not None and q["t_park"]
          and 1500 <= q["t_park"] <= 3600]
    return dict(mode=mode, occ_index=o, run_dir=os.path.relpath(d, os.path.dirname(HERE)),
                curb_occ=round(statistics.mean(curb), 3), total_occ=round(statistics.mean(tot), 3),
                search_mean_s=round(statistics.mean(sr), 1) if sr else None,
                n_parkers=len(P), never_parked=sum(1 for q in P if q["t_park"] is None),
                teleports=len(r["teleports"]))


if __name__ == "__main__":
    jobs = [("curb", o) for o in LEVELS_CURB] + [("total", o) for o in LEVELS_TOTAL]
    with ProcessPoolExecutor(max_workers=9) as ex:
        rows = list(ex.map(one, jobs))
    out = dict(
        description=("Single-seed (seed 1, baseline supply, no policy, visible=false) mapping from the "
                     "demand index `occ` to realised occupancy over the 1500-3600 s window. "
                     "ref_mode='curb': parker arrival rate = occ * 144 / 920 veh/s (144 = baseline curb "
                     "capacity) -- the normalisation used throughout the study. ref_mode='total': "
                     "occ * 200 / 920 -- the DISCARDED normalisation."),
        why_total_was_discarded=("Under the total-supply normalisation, realised CURB occupancy pins near "
                                 "saturation for every demand level while total occupancy never exceeds "
                                 "~0.70, because with no information and no price signal essentially every "
                                 "parker targets the curb and the two garages stay near-empty. The sweep is "
                                 "degenerate: search time and never-parked counts explode while the nominal "
                                 "occupancy variable barely moves."),
        provenance="Every row is backed by a retained run at outputs/<run_dir>/result.json(.gz).",
        rows=rows)
    with open(os.path.join(DATA_DIR, "calibration.json"), "w") as f:
        json.dump(out, f, indent=2)
    for r in rows:
        print(r)
