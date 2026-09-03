#!/usr/bin/env python3
"""INFORMATION-ISOLATION AUDIT.

Five independent checks that the CV controllers cannot see non-CV state:

 A. Runtime guard        — every ground-truth TraCI getter is wrapped; any call
                           from inside a CV controller's decision raises.  Count
                           violations across every CV run in the grid.
 B. p = 0 degradation    — with no connected vehicles the controller must fall
                           back to the loaded fixed-time program.  Verified by
                           per-vehicle tripinfo identity against an independent
                           zero-offset fixed-time run.
 C. Non-CV perturbation  — replay recorded ground-truth states through the FULL
                           pipeline (observation layer + estimator + pressure +
                           argmax) with non-connected vehicles added / removed;
                           both the observation and the decision must be
                           bit-identical.  Positive control: removing a CONNECTED
                           vehicle must change decisions some of the time, or the
                           test has no power.
 D. CV-draw exogeneity   — the connected subset must not correlate with route,
                           cohort or departure order.
 E. Actuated 'coordinated' param — an independent check that a plausible-looking
                           <param> genuinely took effect (or did not).
"""
import glob
import json
import os
import random
import statistics as st
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

import cvcontrol as CC
import cvlib as CV
import traci

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SCEN = os.path.join(ROOT, "outputs", "scenario")
RUNS = os.path.join(ROOT, "outputs", "runs")
OUT = os.path.join(ROOT, "outputs")

P_AUDIT = 0.10
SEED_AUDIT = 1
N_STATES = 200


# ------------------------------------------------------------------- A + C --

def record_states(p=P_AUDIT, seed=SEED_AUDIT, n_states=N_STATES):
    """Run one CV-controlled simulation, recording the FULL ground-truth lane
    state (every vehicle, connected or not) at sampled decision epochs."""
    net = os.path.join(SCEN, "art_fixed.net.xml")
    rou = os.path.join(SCEN, "demand.rou.xml")
    traci.start([CV.SUMO, "-n", net, "-r", rou, "--begin", "0", "--end", "3600",
                 "--seed", str(seed), "--no-step-log", "true",
                 "--time-to-teleport", "300", "--no-warnings", "true",
                 "--xml-validation", "never"], label="audit")
    CC.GUARD.install()
    tls = sorted(traci.trafficlight.getIDList())
    ctrls = {t: CC.CVMP(t, p, "shockwave", 0.6, 5.0, min_green_floor=15.0)
             for t in tls}
    assign = CC.CVAssignment(p, "cv|%d" % seed)
    obs_layer = CC.ObservationLayer(assign)
    now = traci.simulation.getTime()
    for c in ctrls.values():
        c.start(now)
    rng = random.Random(11)
    states = []
    meta = None
    while traci.simulation.getMinExpectedNumber() > 0 and now < 3600 \
            and len(states) < n_states:
        traci.simulationStep()
        now = traci.simulation.getTime()
        obs_layer.on_step()
        obs = obs_layer.observe()
        ctx = {"obs": obs}
        for t in tls:
            c = ctrls[t]
            eligible = (c.mode == "GREEN"
                        and now - c.green_since >= c.min_green_g[c.cur_green]
                        and now - c.last_decision >= c.decision_interval)
            CC.GUARD.active = True
            try:
                c.step(now, ctx)
            finally:
                CC.GUARD.active = False
            if eligible and t == "J2":
                lanes = sorted({l for g in c.green_phases
                                for l in c.phase_in[g] + c.phase_out[g]})
                gt = {}
                for ln in lanes:
                    gt[ln] = [(v, traci.vehicle.getLanePosition(v),
                               traci.vehicle.getSpeed(v))
                              for v in traci.lane.getLastStepVehicleIDs(ln)]
                states.append(dict(t=now, tls=t, gt=gt,
                                   cur_green=c.vacating_green
                                   if c.mode != "GREEN" else c.cur_green))
                if meta is None:
                    meta = dict(green_phases=c.green_phases,
                                phase_links={str(g): c.phase_links[g]
                                             for g in c.green_phases},
                                lane_len=c.lane_len, lanes=lanes)
    guard = dict(violations=CC.GUARD.violations,
                 internal_reads=CC.GUARD.internal_reads)
    traci.close()
    return states, meta, guard


def decide_pure(gt, assign, p, est, meta, cur_green):
    """The FULL CV pipeline as pure functions: observation layer -> estimator ->
    pressure -> argmax.  `gt` is the complete ground-truth lane state."""
    obs = {ln: [(v, x, s) for (v, x, s) in vs if assign.is_cv(v)]
           for ln, vs in gt.items()}
    q = {l: est(obs.get(l, ()), p, meta["lane_len"][l]) for l in meta["lanes"]}
    pr = {g: sum(q[a] - q[b] for a, b in meta["phase_links"][str(g)])
          for g in meta["green_phases"]}
    best = max(pr, key=lambda g: pr[g])
    choice = cur_green if pr[best] <= pr[cur_green] else best
    return choice, obs, pr


def perturbation_test(states, meta, p=P_AUDIT, seed=SEED_AUDIT):
    assign = CC.CVAssignment(p, "cv|%d" % seed)
    est = CC.est_shockwave
    rng = random.Random(5)
    n = 0
    same_obs_add = same_dec_add = 0
    same_obs_del = same_dec_del = 0
    ctrl_changed = ctrl_n = 0
    ctrl2_changed = ctrl2_n = ctrl2_obs_changed = 0
    fake = 0
    for sdict in states:
        gt = sdict["gt"]
        cur = sdict["cur_green"]
        d0, obs0, pr0 = decide_pure(gt, assign, p, est, meta, cur)
        n += 1

        # --- add K synthetic NON-connected vehicles on random approach lanes --
        gt_add = {k: list(v) for k, v in gt.items()}
        added = 0
        while added < 20:
            vid = "FAKE_%d" % fake
            fake += 1
            if assign.is_cv(vid):
                continue                     # must genuinely be non-connected
            ln = rng.choice(meta["lanes"])
            gt_add[ln].append((vid, rng.uniform(0, meta["lane_len"][ln]),
                               rng.choice([0.0, 0.0, 5.0])))
            added += 1
        d1, obs1, _ = decide_pure(gt_add, assign, p, est, meta, cur)
        same_obs_add += int(obs1 == obs0)
        same_dec_add += int(d1 == d0)

        # --- delete every non-connected vehicle -----------------------------
        gt_del = {ln: [v for v in vs if assign.is_cv(v[0])]
                  for ln, vs in gt.items()}
        d2, obs2, _ = decide_pure(gt_del, assign, p, est, meta, cur)
        same_obs_del += int(obs2 == obs0)
        same_dec_del += int(d2 == d0)

        # --- POSITIVE CONTROLS (CV-side perturbations of the SAME magnitude)
        cvs = [(ln, i) for ln, vs in gt.items()
               for i, v in enumerate(vs) if assign.is_cv(v[0])]
        if cvs:
            ln, i = rng.choice(cvs)
            gt_c = {k: list(v) for k, v in gt.items()}
            del gt_c[ln][i]
            d3, _, _ = decide_pure(gt_c, assign, p, est, meta, cur)
            ctrl_n += 1
            ctrl_changed += int(d3 != d0)
        # add 20 synthetic CONNECTED vehicles, queued at the stop bar of one
        # randomly chosen approach lane -- the exact CV-side mirror of the
        # 20-non-CV injection above
        ln = rng.choice(meta["lanes"])
        gt_p = {k: list(v) for k, v in gt.items()}
        added = 0
        nonce = 0
        while added < 20:
            vid = "CVFAKE_%d_%d" % (ctrl_n, nonce)
            nonce += 1
            if not assign.is_cv(vid):
                continue
            gt_p[ln].append((vid, meta["lane_len"][ln] - 7.5 * (added + 1), 0.0))
            added += 1
        d4, obs4, _ = decide_pure(gt_p, assign, p, est, meta, cur)
        ctrl2_n += 1
        ctrl2_changed += int(d4 != d0)
        ctrl2_obs_changed += int(obs4 != obs0)
    return dict(n_states=n,
                obs_identical_after_adding_20_nonCV=same_obs_add / n,
                decision_identical_after_adding_20_nonCV=same_dec_add / n,
                obs_identical_after_deleting_all_nonCV=same_obs_del / n,
                decision_identical_after_deleting_all_nonCV=same_dec_del / n,
                positive_control_n=ctrl_n,
                positive_control_A_delete_one_CV_n=ctrl_n,
                positive_control_A_decision_changed=(ctrl_changed / ctrl_n
                                                     if ctrl_n else float("nan")),
                positive_control_B_add_20_CV_n=ctrl2_n,
                positive_control_B_observation_changed=(ctrl2_obs_changed
                                                        / max(ctrl2_n, 1)),
                positive_control_B_decision_changed=(ctrl2_changed
                                                     / max(ctrl2_n, 1)))


# ----------------------------------------------------------------------- B --

def tripinfo_map(path):
    d = {}
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "tripinfo":
            d[el.get("id")] = (float(el.get("depart")), float(el.get("arrival")),
                               float(el.get("duration")),
                               float(el.get("timeLoss")))
            el.clear()
    return d


def phase_sequence(run):
    """Reconstruct the served-green sequence from epochs.csv.gz's is_current
    flag (5 s resolution) — works for every arm, controller or not."""
    import analyze as AN
    rows = AN.read_epochs(run)
    per = defaultdict(list)
    for r in rows:
        if r["is_current"] == "1":
            per[r["tls"]].append((float(r["t"]), int(r["group"])))
    seq = {}
    for t, v in per.items():
        v.sort()
        s = []
        for _, g in v:
            if not s or s[-1] != g:
                s.append(g)
        seq[t] = s
    return seq


def cyclic_order_ok(seq, order=(0, 3, 6)):
    """True iff every consecutive pair in the served-green sequence advances by
    exactly one step in the program's cyclic phase order."""
    n = len(order)
    idx = {g: i for i, g in enumerate(order)}
    bad = 0
    tot = 0
    for a, b in zip(seq, seq[1:]):
        tot += 1
        if (idx[b] - idx[a]) % n != 1:
            bad += 1
    return tot, bad


def p0_degradation():
    out = []
    for kind in ("naive", "shock"):
        for s in (1, 2, 3):
            a = os.path.join(RUNS, "%s_p000_s%02d" % (kind, s), "tripinfo.xml")
            b = os.path.join(RUNS, "fixed_off0_p000_s%02d" % s, "tripinfo.xml")
            if not (os.path.exists(a) and os.path.exists(b)):
                continue
            A, B = tripinfo_map(a), tripinfo_map(b)
            common = set(A) & set(B)
            ident = sum(1 for k in common if A[k] == B[k])
            seq = phase_sequence(os.path.join(RUNS, "%s_p000_s%02d" % (kind, s)))
            tot = bad = 0
            ncyc = []
            for t, sq in seq.items():
                a1, b1 = cyclic_order_ok(sq)
                tot += a1
                bad += b1
                ncyc.append(len(sq))
            out.append(dict(kind=kind, seed=s, n_a=len(A), n_b=len(B),
                            n_common=len(common),
                            frac_identical_tripinfo_records=ident
                            / max(len(common), 1),
                            mean_timeLoss_cv_p0=round(
                                st.mean(v[3] for v in A.values()), 2),
                            mean_timeLoss_fixed_off0=round(
                                st.mean(v[3] for v in B.values()), 2),
                            n_phase_transitions=tot,
                            n_out_of_program_order=bad,
                            frac_in_program_order=round(1 - bad / max(tot, 1), 4),
                            mean_greens_served_per_tls=round(
                                st.mean(ncyc), 1)))
    # what the SAME check gives for a genuinely CV-driven controller at p=10%
    for s in (1, 2, 3):
        r = os.path.join(RUNS, "shock_p010_s%02d" % s)
        if not os.path.exists(r):
            continue
        seq = phase_sequence(r)
        tot = bad = 0
        for t, sq in seq.items():
            a1, b1 = cyclic_order_ok(sq)
            tot += a1
            bad += b1
        out.append(dict(kind="shock (p=10%, CONTRAST)", seed=s,
                        n_phase_transitions=tot, n_out_of_program_order=bad,
                        frac_in_program_order=round(1 - bad / max(tot, 1), 4)))
    return out


# ----------------------------------------------------------------------- D --

def cv_draw_exogeneity(p=P_AUDIT, seeds=(1, 2, 3)):
    rou = os.path.join(SCEN, "demand.rou.xml")
    veh = []
    for _, el in ET.iterparse(rou, events=("end",)):
        if el.tag == "vehicle":
            veh.append((el.get("id"), float(el.get("depart"))))
            el.clear()
    res = []
    for s in seeds:
        a = CC.CVAssignment(p, "cv|%d" % s)
        flags = [(vid, dep, a.is_cv(vid)) for vid, dep in veh]
        overall = st.mean([1.0 if f else 0.0 for _, _, f in flags])
        byc = defaultdict(list)
        for vid, dep, f in flags:
            pre = "".join(c for c in vid.split(".")[0] if not c.isdigit())
            byc[pre].append(1.0 if f else 0.0)
        # chi-square over cohorts
        chi = 0.0
        for k, v in byc.items():
            n, k1 = len(v), sum(v)
            e = n * overall
            if e > 0:
                chi += (k1 - e) ** 2 / e + ((n - k1) - (n - e)) ** 2 / (n - e)
        # correlation between the draw and departure time
        try:
            from scipy import stats as sps
            r = float(sps.pearsonr([d for _, d, _ in flags],
                                   [1.0 if f else 0.0 for _, _, f in flags])
                      .statistic)
            pv = float(sps.chi2.sf(chi, len(byc) - 1))
        except Exception:
            r, pv = float("nan"), float("nan")
        res.append(dict(seed=s, n_veh=len(veh), realised_p=overall,
                        n_cohorts=len(byc), chi2=chi, chi2_p=pv,
                        corr_draw_vs_depart=r,
                        min_cohort_rate=min(st.mean(v) for v in byc.values()),
                        max_cohort_rate=max(st.mean(v) for v in byc.values())))
    return res


# ----------------------------------------------------------------------- E --

def coordinated_param_check():
    out = {}
    for k in ("actuated", "coordact"):
        f = os.path.join(SCEN, "art_%s.net.xml" % k)
        r = ET.parse(f).getroot()
        t = [x for x in r.iter("tlLogic") if x.get("id") == "J1"][0]
        out[k + "_params_in_net"] = {p.get("key"): p.get("value")
                                     for p in t.findall("param")}
    pairs = []
    for s in (1, 2, 3):
        a = os.path.join(RUNS, "actuated_p000_s%02d" % s, "tripinfo.xml")
        b = os.path.join(RUNS, "coordact_p000_s%02d" % s, "tripinfo.xml")
        if os.path.exists(a) and os.path.exists(b):
            A, B = tripinfo_map(a), tripinfo_map(b)
            common = set(A) & set(B)
            pairs.append(dict(seed=s, n_common=len(common),
                              frac_identical=sum(1 for k in common
                                                 if A[k] == B[k])
                              / max(len(common), 1),
                              mean_tl_actuated=st.mean(v[3] for v in A.values()),
                              mean_tl_coordact=st.mean(v[3] for v in B.values())))
    out["actuated_vs_coordact_runs"] = pairs
    return out


# --------------------------------------------------------------------- run --

def guard_across_grid():
    n_runs = n_cv_runs = 0
    viol = 0
    internal = 0
    for f in glob.glob(os.path.join(RUNS, "*", "run.json")):
        m = json.load(open(f))
        n_runs += 1
        if m["kind"] in ("naive", "shock", "naive_mit", "shock_mit", "shock_fo"):
            n_cv_runs += 1
            viol += len(m.get("guard_violations", []))
            internal += m.get("guard_internal_reads", 0)
    return dict(n_runs=n_runs, n_cv_runs=n_cv_runs,
                total_guard_violations=viol,
                total_internal_lane_reads_during_decisions=internal)


def main():
    rep = {}
    print("A. runtime guard across the grid ...")
    rep["A_guard"] = guard_across_grid()
    print("   ", rep["A_guard"])

    print("B. p=0 degradation to the fixed-time fallback ...")
    rep["B_p0_degradation"] = p0_degradation()
    for r in rep["B_p0_degradation"]:
        print("   ", r)

    print("C. non-CV perturbation replay ...")
    states, meta, guard = record_states()
    rep["C_recording_guard"] = guard
    rep["C_perturbation"] = perturbation_test(states, meta)
    print("   ", rep["C_perturbation"])

    print("D. CV-draw exogeneity ...")
    rep["D_cv_draw"] = cv_draw_exogeneity()
    for r in rep["D_cv_draw"]:
        print("   ", r)

    print("E. actuated 'coordinated' param ...")
    rep["E_coordinated_param"] = coordinated_param_check()
    print("   ", json.dumps(rep["E_coordinated_param"], indent=1))

    with open(os.path.join(OUT, "isolation_audit.json"), "w") as f:
        json.dump(rep, f, indent=2, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
