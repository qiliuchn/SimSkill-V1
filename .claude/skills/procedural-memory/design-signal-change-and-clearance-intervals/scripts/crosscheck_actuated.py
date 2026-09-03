"""Item 6 cross-check.

(a) Does SUMO's ACTUATED controller touch the yellow / all-red phases, or gap-out/max-out in
    a way that would confound a yellow-length sweep? Answered from the realized phase trace,
    not from documentation.
(b) Does a dilemma-zone-protection detector placement actually reduce measured red-light
    running? Custom E1 detectors are bound to the tlLogic via <param key="<laneID>"
    value="<detID>"/> (per `design-actuated-signal-detector-placement-and-fault-tolerance`),
    and the binding is PROVEN with the manipulation-plus-negative-control protocol:
      - baseline custom binding
      - detector moved to an implausible position   -> phase trace MUST change
      - NO_DETECTOR                                  -> phase pinned at minDur
      - unrecognised <param> key (negative control)  -> phase trace MUST be byte-identical
"""
import argparse
import hashlib
import json
import os
import shutil
from multiprocessing import Pool

from common import ANA_DIR, RUN_DIR
from build_net import build
import analytic
import run_sweeps as RS
import sim_rig

SEEDS = RS.SEEDS


def det_add(meta, setback, lanes, bind=True, bogus_key=False, no_detector=False):
    """Custom E1 detectors + the tlLogic <param> binding lines."""
    dets, params = [], {}
    for a in ("N", "E", "S", "W"):
        for i in range(lanes):
            lid = "in_%s_%d" % (a, i)
            did = "d_" + lid
            dets.append('  <inductionLoop id="%s" lane="%s" pos="-%.2f" friendlyPos="true" '
                        'period="100000" file="det.xml"/>' % (did, lid, setback))
            if no_detector:
                params[lid] = "NO_DETECTOR"
            elif bind:
                params[lid] = did
    if bogus_key:
        params["NOT_A_LANE_ID_xyz"] = "d_in_N_0"
    return "\n".join(dets), params


def build_inputs(rd, meta, cfg, setback, bind, bogus_key, no_detector):
    os.makedirs(rd, exist_ok=True)
    dets, params = det_add(meta, setback, meta["lanes"], bind, bogus_key, no_detector)
    cfg = dict(cfg)
    cfg["tls_params"] = params
    tls, phases, idx = sim_rig.tls_xml(meta, cfg["cycle"], cfg["yellow"], cfg["allred"],
                                       cfg.get("tls_type", "static"), cfg.get("minDur"),
                                       cfg.get("maxDur"), cfg.get("greens"), params)
    add_p = os.path.join(rd, "extra.add.xml")
    open(add_p, "w").write("<additional>\n%s\n%s\n</additional>\n" % (tls, dets))
    rou_p = os.path.join(rd, "demand.rou.xml")
    open(rou_p, "w").write(sim_rig.routes_xml(
        cfg["vph"], cfg["demand_end"], cfg.get("truck_share", 0.0), cfg.get("jm"),
        cfg.get("ssm", True), cfg.get("car_over"), cfg.get("truck_over"),
        noncomp_share=cfg.get("noncomp_share", 0.0),
        noncomp_jm=cfg.get("noncomp_jm")) + "\n")
    json.dump(dict(phases=phases, group_links=idx), open(os.path.join(rd, "plan.json"), "w"))
    return add_p, rou_p


def work(job):
    name, meta, cfg, setback, bind, bogus, nodet = job
    rd = os.path.join(RUN_DIR, name)
    if os.path.exists(os.path.join(rd, "cc.json")):
        return name, "cached"
    if os.path.exists(rd):
        shutil.rmtree(rd)
    try:
        add_p, rou_p = build_inputs(rd, meta, cfg, setback, bind, bogus, nodet)
        # reuse the standard TraCI loop by pointing it at the inputs we just wrote
        orig = sim_rig.write_inputs
        sim_rig.write_inputs = lambda r, m, c: (add_p, rou_p,
                                                json.load(open(os.path.join(rd, "plan.json")))["phases"],
                                                json.load(open(os.path.join(rd, "plan.json")))["group_links"])
        try:
            log_p, recs = sim_rig.run_cell(rd, meta, cfg)
        finally:
            sim_rig.write_inputs = orig
        m = sim_rig.read_metrics(rd)
        v = json.load(open(os.path.join(rd, "tls_verify.json")))
        trace = v["phase_trace"]
        # realized durations per phase index
        durs = {}
        for k in range(1, len(trace)):
            t0, ph0, s0 = trace[k - 1]
            t1, ph1, s1 = trace[k]
            durs.setdefault(ph0, []).append(round(t1 - t0, 2))
        h = hashlib.sha1(json.dumps(trace).encode()).hexdigest()
        from collections import Counter
        oc = Counter(r["outcome"] for r in recs)
        out = dict(name=name, cfg={k: x for k, x in cfg.items() if k != "meta"},
                   setback=setback, bind=bind, bogus=bogus, nodet=nodet,
                   trace_sha1=h, n_phase_changes=v["n_phase_changes"],
                   realized_phase_durations={str(k): dict(
                       n=len(x), min=min(x), max=max(x),
                       mean=round(sum(x) / len(x), 3)) for k, x in durs.items()},
                   outcomes=dict(oc), n_decision=len(recs), metrics=m)
        json.dump(out, open(os.path.join(rd, "cc.json"), "w"), indent=2)
        sim_rig.prune_run(rd, keep=("cc.json", "decision_log.csv", "tls_verify.json",
                                    "extra.add.xml", "plan.json", "stats.xml", "sumo.err",
                                    "summary.xml", "collisions.xml", "jpet.json"))
        return name, "ok"
    except Exception:
        import traceback
        return name, "FAIL\n" + traceback.format_exc()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--procs", type=int, default=9)
    a = ap.parse_args()
    v = 19.44
    meta = build("n_v1944_g+0_l2", speed=v, grade_pct=0.0, lanes=2, arm=400.0)[1]
    xs_ite = analytic.x_stop(v, 1.0, 3.05)
    xc = lambda y: v * y
    base = dict(RS.base_cfg(allred=1.0, vph=RS.LOW, **RS.DRIVERS["ITE"]))

    jobs = []
    # (a) static vs actuated at several yellows -- does actuation touch yellow/all-red?
    for tt in ("static", "actuated", "delay_based"):
        for y in (2.0, 3.0, 5.0):
            for sd in SEEDS:
                cfg = dict(base)
                cfg.update(yellow=y, seed=sd, tls_type=tt, minDur=8.0, maxDur=50.0)
                cfg["_arm"] = "tlstype"
                jobs.append(("X_%s_y%.1f_s%d" % (tt, y, sd), meta, cfg,
                             2.0 * v, True, False, False))
    # (b) detector placement under ACTUATED control, incl. a dilemma-zone-protection setback
    placements = {"default_2s": 2.0 * v, "close_20m": 20.0, "dz_ite": xs_ite,
                  "dz_beyond": xs_ite + 30.0, "far_150m": 150.0}
    for pn, sb in placements.items():
        for y in (2.0, 3.0):
            for sd in SEEDS:
                cfg = dict(base)
                cfg.update(yellow=y, seed=sd, tls_type="actuated", minDur=8.0, maxDur=50.0)
                cfg["_arm"] = "placement"
                jobs.append(("X_det_%s_y%.1f_s%d" % (pn, y, sd), meta, cfg,
                             sb, True, False, False))
    # (c) binding-verification protocol (single seed each)
    cfgv = dict(base)
    cfgv.update(yellow=3.0, seed=SEEDS[0], tls_type="actuated", minDur=8.0, maxDur=50.0)
    cfgv["_arm"] = "verify"
    jobs += [
        ("X_ver_baseline", meta, dict(cfgv), 2.0 * v, True, False, False),
        ("X_ver_moved", meta, dict(cfgv), 150.0, True, False, False),
        ("X_ver_nodetector", meta, dict(cfgv), 2.0 * v, True, False, True),
        ("X_ver_bogus_negctrl", meta, dict(cfgv), 2.0 * v, True, True, False),
        ("X_ver_unbound", meta, dict(cfgv), 2.0 * v, False, False, False),
    ]
    print("crosscheck jobs:", len(jobs), flush=True)
    with Pool(a.procs) as p:
        for n, s in p.imap_unordered(work, jobs):
            if s.startswith("FAIL"):
                print("FAIL", n, s[:800], flush=True)
    res = []
    for j in jobs:
        p = os.path.join(RUN_DIR, j[0], "cc.json")
        if os.path.exists(p):
            res.append(json.load(open(p)))
    json.dump(res, open(os.path.join(ANA_DIR, "crosscheck.json"), "w"), indent=2)
    print("wrote", len(res))


if __name__ == "__main__":
    main()
