#!/usr/bin/env python3
"""Run one (controller, penetration, seed) configuration and log every layer.

Every arm — including the fixed-time and actuated benchmarks — is stepped
through TraCI so that the ground-truth instrumentation (per-approach queue,
phase service gaps, max queue) is produced identically for all arms; the
benchmark arms simply have no controller attached and SUMO drives its own
program.
"""
import csv
import gzip
import json
import os
import sys
import xml.etree.ElementTree as ET

import cvcontrol as CC
import cvlib as CV
import traci

DECISION_INTERVAL = 5.0
MIN_GREEN_FRAC = 0.6
THETA = 0.0
FORCE_OFF = 150.0   # s — starvation mitigation max-out timer
FLOOR = 15.0
LOG_EVERY = 5.0


class PhaseWatcher(object):
    """Tracks, from the ACTUAL tls phase index each second, the time between
    successive services of each green phase — valid for every arm."""

    def __init__(self, tls, green_phases):
        self.tls = tls
        self.green = set(green_phases)
        self.last_seen = {g: None for g in green_phases}
        self.gaps = {g: [] for g in green_phases}
        self.cur = None
        self.started = {g: None for g in green_phases}

    def step(self, now, ph):
        if ph in self.green and ph != self.cur:
            if self.last_seen[ph] is not None:
                self.gaps[ph].append(now - self.last_seen[ph])
            self.last_seen[ph] = now
            self.cur = ph
        elif ph in self.green:
            self.last_seen[ph] = now      # keep updating while active
        elif self.cur is not None and ph not in self.green:
            self.cur = None


def build_controllers(kind, p, seed, tls_ids, min_green_frac=MIN_GREEN_FRAC,
                      theta=0.0, floor=FLOOR):
    if kind in ("fixed", "actuated", "coordact"):
        return None
    if kind == "perfect":
        return {t: CC.PerfectMP(t, min_green_frac, DECISION_INTERVAL, theta, floor) for t in tls_ids}
    est = "naive" if kind.startswith("naive") else "shockwave"
    mem = kind.endswith("_mit")
    fo = FORCE_OFF if (kind.endswith("_mit") or kind.endswith("_fo")) else None
    return {t: CC.CVMP(t, p, est, min_green_frac, DECISION_INTERVAL,
                       memory=mem, force_off=fo, switch_theta=theta,
                       min_green_floor=floor)
            for t in tls_ids}


def run(kind, p, seed, outdir, net, routes, add="", sim_end=CV.SIM_END,
        write_epochs=True, min_green_frac=MIN_GREEN_FRAC, theta=THETA, floor=FLOOR):
    os.makedirs(outdir, exist_ok=True)
    tripinfo = os.path.join(outdir, "tripinfo.xml")
    summary = os.path.join(outdir, "summary.xml")
    cmd = [CV.SUMO, "-n", net, "-r", routes,
           "--tripinfo-output", tripinfo, "--summary-output", summary,
           "--begin", "0", "--end", "%.0f" % sim_end,
           "--seed", str(seed), "--no-step-log", "true",
           "--time-to-teleport", "300", "--duration-log.statistics", "true",
           "--xml-validation", "never", "--no-warnings", "true"]
    label = "%s_p%03d_s%d" % (kind, round(p * 100), seed)
    traci.start(cmd, label=label)
    CC.GUARD.install()
    CC.GUARD.active = False
    CC.GUARD.violations = []
    CC.GUARD.internal_reads = 0

    tls_ids = sorted(traci.trafficlight.getIDList())
    ctrls = build_controllers(kind, p, seed, tls_ids, min_green_frac, theta, floor)
    # monitors give the phase->lane-group mapping for EVERY arm
    monitors = {t: CC.BaseJunctionController(t, min_green_frac, DECISION_INTERVAL,
                                             theta, floor)
                for t in tls_ids} if ctrls is None else ctrls
    watchers = {t: PhaseWatcher(t, monitors[t].green_phases) for t in tls_ids}

    assign = CC.CVAssignment(p, "cv|%d" % seed)
    obslayer = CC.ObservationLayer(assign)

    if ctrls is not None:
        now = traci.simulation.getTime()
        for c in ctrls.values():
            c.start(now)

    ep_rows, dec_rows = [], []
    maxq = {t: {g: 0.0 for g in monitors[t].green_phases} for t in tls_ids}
    teleports = 0
    next_log = 0.0
    now = traci.simulation.getTime()

    while traci.simulation.getMinExpectedNumber() > 0 and now < sim_end:
        traci.simulationStep()
        now = traci.simulation.getTime()
        obslayer.on_step()
        teleports += traci.simulation.getStartingTeleportNumber()
        obs = obslayer.observe() if p > 0 or kind.startswith(("naive", "shock")) \
            else {}

        ctx = {"obs": obs}
        if ctrls is not None:
            for t in tls_ids:
                c = ctrls[t]
                decide_now = (c.mode == "GREEN"
                              and now - c.green_since >= c.min_green_g[c.cur_green]
                              and now - c.last_decision >= c.decision_interval)
                if isinstance(c, CC.CVMP):
                    CC.GUARD.active = True
                    try:
                        c.step(now, ctx)
                    finally:
                        CC.GUARD.active = False
                else:
                    c.step(now, ctx)
                if decide_now:
                    # perfect-information reference decision on the SAME state
                    q = {l: traci.lane.getLastStepHaltingNumber(l)
                         for l in set(sum([c.phase_in[g] + c.phase_out[g]
                                           for g in c.green_phases], []))}
                    tp = c.pressure_from(q)
                    cur_before = c.vacating_green if c.mode in ("YELLOW", "ALLRED") \
                        else c.cur_green
                    bt = max(tp, key=lambda g: tp[g])
                    perfect = cur_before if tp[bt] <= tp[cur_before] else bt
                    chosen = c.target_green if c.mode in ("YELLOW", "ALLRED") \
                        else c.cur_green
                    dec_rows.append(dict(
                        t=now, tls=t, cur=cur_before, cv_choice=chosen,
                        perfect_choice=perfect,
                        agree=int(chosen == perfect),
                        true_pressure=json.dumps({str(k): v for k, v in tp.items()}),
                        est_pressure=json.dumps(
                            {str(k): round(v, 4) for k, v in
                             ctx.get("est_pressure", {}).get(t, {}).items()})))

        for t in tls_ids:
            watchers[t].step(now, traci.trafficlight.getPhase(t))

        if now >= next_log:
            next_log += LOG_EVERY
            for t in tls_ids:
                m = monitors[t]
                curph = traci.trafficlight.getPhase(t)
                for g in m.green_phases:
                    tq = sum(traci.lane.getLastStepHaltingNumber(l)
                             for l in m.phase_in[g])
                    tqo = sum(traci.lane.getLastStepHaltingNumber(l)
                              for l in m.phase_out[g])
                    ocv = sum(len(obs.get(l, ())) for l in m.phase_in[g])
                    ost = sum(1 for l in m.phase_in[g]
                              for (_, _, s) in obs.get(l, ())
                              if s < CC.HALT_SPEED)
                    if isinstance(m, CC.CVMP):
                        eq = sum(m.last_est.get(l, 0.0) for l in m.phase_in[g])
                        eqo = sum(m.last_est.get(l, 0.0) for l in m.phase_out[g])
                    else:
                        eq = eqo = ""
                    maxq[t][g] = max(maxq[t][g], tq)
                    if write_epochs:
                        ep_rows.append(dict(
                            t=now, tls=t, group=g, true_q_in=tq, true_q_out=tqo,
                            obs_cv=ocv, obs_cv_stop=ost,
                            est_q_in=("" if eq == "" else round(eq, 4)),
                            est_q_out=("" if eqo == "" else round(eqo, 4)),
                            is_current=int(curph == g)))

    end_time = now
    traci.close()

    if write_epochs and ep_rows:
        with gzip.open(os.path.join(outdir, "epochs.csv.gz"), "wt", newline="") as f:
            w = csv.DictWriter(f, list(ep_rows[0].keys()))
            w.writeheader()
            w.writerows(ep_rows)
    if dec_rows:
        with gzip.open(os.path.join(outdir, "decisions.csv.gz"), "wt", newline="") as f:
            w = csv.DictWriter(f, list(dec_rows[0].keys()))
            w.writeheader()
            w.writerows(dec_rows)

    meta = dict(kind=kind, p=p, seed=seed, end_time=end_time, min_green_frac=min_green_frac, theta=theta, floor=floor,
                teleports=teleports,
                cv_subscribed=obslayer.n_subscribed,
                guard_violations=CC.GUARD.violations,
                guard_internal_reads=CC.GUARD.internal_reads,
                max_queue={t: {str(g): maxq[t][g] for g in maxq[t]}
                           for t in maxq},
                service_gaps={t: {str(g): watchers[t].gaps[g]
                                  for g in watchers[t].gaps} for t in tls_ids},
                n_forced=({t: ctrls[t].n_forced for t in tls_ids}
                          if ctrls and isinstance(list(ctrls.values())[0], CC.CVMP)
                          else {}),
                n_fallback=({t: ctrls[t].n_fallback for t in tls_ids}
                            if ctrls and isinstance(list(ctrls.values())[0], CC.CVMP)
                            else {}),
                n_decisions=({t: ctrls[t].n_decisions for t in tls_ids}
                             if ctrls else {}),
                cmd=cmd)
    with open(os.path.join(outdir, "run.json"), "w") as f:
        json.dump(meta, f, indent=1)
    return meta


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", required=True)
    ap.add_argument("--p", type=float, default=0.0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--net", required=True)
    ap.add_argument("--routes", required=True)
    ap.add_argument("--add", default="")
    ap.add_argument("--min-green-frac", type=float, default=MIN_GREEN_FRAC)
    ap.add_argument("--theta", type=float, default=THETA)
    ap.add_argument("--floor", type=float, default=FLOOR)
    a = ap.parse_args()
    m = run(a.kind, a.p, a.seed, a.outdir, a.net, a.routes, a.add,
            min_green_frac=a.min_green_frac, theta=a.theta, floor=a.floor)
    print(json.dumps({k: v for k, v in m.items()
                      if k in ("kind", "p", "seed", "end_time", "teleports",
                               "cv_subscribed", "guard_violations")}))
