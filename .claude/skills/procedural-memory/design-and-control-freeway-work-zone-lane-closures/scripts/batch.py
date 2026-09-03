"""Parallel batch runner.  Each cell is a dict describing one simulation run.

Every run gets its OWN output directory and its OWN additional file (detector `file=`
paths are absolutised inside gen_additional.build), so parallel workers can never
overwrite each other's detector output -- the gotcha recorded in
`quantify-sumo-run-to-run-variability` / `implement-coordinated-corridor-ramp-metering`.
"""
import json
import os
import traceback
from multiprocessing import Pool

import wz_common as W
import gen_demand
import gen_additional as GA
import analyze
import run_wz

NPROC = 9
STEP = 0.5          # chosen in exp_discretization.py; see DISCRETIZATION_DECISION.md
BALLISTIC = True


def cell_run(cell):
    """cell keys: label, outroot, params, rep, merge, arm, peak, seed, phi,
                  demand_seed, ttt, step, end, extra_add, profile"""
    try:
        p = W.params(**cell.get("params", {}))
        rep = cell.get("rep", "geom")
        merge = cell.get("merge", "priority")
        net = W.build_net(p, rep, merge=merge)
        if cell.get("permission_lanes"):
            dst = os.path.join(W.NETS, f"perm_{cell['label']}.net.xml")
            net = W.apply_permission_closure(net, dst, cell["permission_lanes"])
        od = os.path.join(cell["outroot"], cell["label"])
        rou, nveh = gen_demand.gen(cell["peak"], cell.get("demand_seed", 100 + cell["seed"]),
                                   cell.get("phi", 0.0),
                                   out=os.path.join(W.RUNS, "rou",
                                                    f"q{cell['peak']}_d{cell.get('demand_seed', 100+cell['seed'])}"
                                                    f"_phi{int(cell.get('phi',0)*1000)}.rou.xml"),
                                   profile=cell.get("profile", gen_demand.PROFILE),
                                   sim_end=cell.get("end", 4800))
        add = GA.build(net, od, cell["label"], e2=cell.get("e2", True))
        if cell.get("extra_add"):
            add = add + "," + cell["extra_add"]
        m = run_wz.run(net, rou, add, od, cell["arm"], p,
                       seed=cell["seed"], step=cell.get("step", STEP),
                       end=cell.get("end", 4800), ttt=cell.get("ttt", 300),
                       ballistic=cell.get("ballistic", BALLISTIC),
                       ssm=cell.get("ssm", False))
        n_open = W.MAIN_LANES - p["lanes_closed"]
        s = analyze.summarize(od, n_open)
        s.update({k: v for k, v in cell.items()
                  if k in ("label", "arm", "peak", "seed", "phi", "rep", "merge",
                           "demand_seed", "ttt", "step", "tagname")})
        s["params"] = p
        s["hard_brakes"] = m["hard_brakes"]
        s["hard_brakes_taper"] = m["hard_brakes_taper"]
        s["final_mode"] = m["final_mode"]
        s["nveh_demand"] = nveh
        s["freeze"] = analyze.running_freeze(od)
        s["ok"] = True
        return s
    except Exception:
        return dict(label=cell.get("label"), ok=False, error=traceback.format_exc())


def run_cells(cells, outjson, nproc=NPROC):
    os.makedirs(os.path.join(W.RUNS, "rou"), exist_ok=True)
    # pre-build all nets serially (netconvert is not safe to race on the same file)
    seen = set()
    for c in cells:
        p = W.params(**c.get("params", {}))
        key = (W.tag(p, c.get("rep", "geom"), c.get("merge", "priority")))
        if key in seen:
            continue
        seen.add(key)
        W.build_net(p, c.get("rep", "geom"), merge=c.get("merge", "priority"))
    with Pool(nproc) as pool:
        res = []
        for i, r in enumerate(pool.imap_unordered(cell_run, cells)):
            res.append(r)
            st = "OK " if r.get("ok") else "FAIL"
            print(f"[{i+1}/{len(cells)}] {st} {r.get('label')} "
                  f"cap={r.get('cap', float('nan')):.0f} "
                  f"dur={r.get('mean_duration', float('nan')):.0f}", flush=True)
            if not r.get("ok"):
                print(r.get("error", "")[-800:], flush=True)
    json.dump(res, open(outjson, "w"), indent=1, default=float)
    return res
