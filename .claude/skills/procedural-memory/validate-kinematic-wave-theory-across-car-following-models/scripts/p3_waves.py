#!/usr/bin/env python3
"""PART 3 - DIRECT WAVE MEASUREMENT on two independent OPEN-ROAD experiments.

  3a  signalised link : stopping wave at red onset, start-up wave at green onset
  3b  incident        : a stopped vehicle fully blocks the single lane for 180 s,
                        giving a stopping wave and a recovery wave on release

Wave fronts are traced from raw FCD trajectories, never eyeballed:
  * stopping front = the QUEUE-BACK trajectory x_back(t), obtained per timestep by
    walking upstream from the stop line / blockage through a CONTIGUOUS chain of
    slow vehicles.  Contiguity matters: EIDM strands slow platoons hundreds of
    metres upstream between signal cycles, and pooling those with the real shock
    destroys the fit.
  * start-up front = per-vehicle first time above the speed threshold after
    release, restricted to vehicles that were actually in the queue chain.
Both are fitted by OLS with an R^2 reported.

They are then compared against Rankine-Hugoniot  w = (q2-q1)/(k2-k1)  computed
from THAT MODEL'S OWN ring-measured FD (part 1), and additionally against a
variant that substitutes the DIRECTLY MEASURED queue density for the FD's k_j.

Teleporting is disabled (--time-to-teleport -1); teleports/collisions are counted
per run and any non-zero count invalidates the corresponding measurement
(cf. `validate-congested-scenario-results-against-teleport-artifacts`).
"""
import os, sys, json, subprocess
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wave_lib as W
import ring_lib as R

OUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NETD = os.path.join(OUT, 'net')
RUND = os.path.join(OUT, 'runs', 'p3')
VF = 30.0
MODELS = ['Krauss', 'IDM', 'EIDM', 'ACC']
SEEDS = [42, 43, 44]
# "in queue" threshold.  0.5 m/s (a genuine full stop) misses ACC entirely -- ACC
# creeps rather than stopping -- so a congested-regime threshold of 0.1*v_free is
# used uniformly for every model, and the fraction of arrivals that reach a REAL
# full stop is reported separately as a diagnostic.
VQ = 3.0
VSTOP = 0.5


def sumo(args):
    return subprocess.run(['sumo'] + args, capture_output=True, text=True)


# --------------------------------------------------------------- 3a signal ---
APPROACH, TAIL = 2000.0, 400.0
GREEN, YELLOW, RED = 40.0, 4.0, 40.0     # cycle 84 s
CYC = GREEN + YELLOW + RED
SIG_END = 1600.0
SIG_DEMAND = 950.0     # veh/h; below every model's G/C-scaled capacity so each
                       # cycle's queue fully clears (verified per cycle below)
CYCLES = (6, 7, 8, 9, 10, 11, 12)


def run_signal(model, seed):
    os.makedirs(RUND, exist_ok=True)
    net, tag = os.path.join(NETD, 'sig.net.xml'), f'sig_{model}_s{seed}'
    add = os.path.join(RUND, tag + '.add.xml')
    open(add, 'w').write(
        '<additional>\n'
        f'  <tlLogic id="B" type="static" programID="P" offset="0">\n'
        f'    <phase duration="{GREEN}" state="G"/>\n'
        f'    <phase duration="{YELLOW}" state="y"/>\n'
        f'    <phase duration="{RED}" state="r"/>\n  </tlLogic>\n'
        f'  <inductionLoop id="up" lane="in_0" pos="200" period="60" file="{tag}.e1.xml"/>\n'
        '</additional>')
    rou = os.path.join(RUND, tag + '.rou.xml')
    open(rou, 'w').write(
        f'<routes>\n  {R.vtype_xml("car", model)}\n  <route id="r" edges="in out"/>\n'
        f'  <flow id="f" type="car" route="r" begin="0" end="{SIG_END}" '
        f'vehsPerHour="{SIG_DEMAND}" departSpeed="max" departPos="base"/>\n</routes>')
    fcd, smf = os.path.join(RUND, tag + '.fcd.xml'), os.path.join(RUND, tag + '.sum.xml')
    p = sumo(['-n', net, '-r', rou, '-a', add, '--fcd-output', fcd,
              '--fcd-output.attributes', 'x,y,speed', '--summary-output', smf,
              '--step-length', '0.5', '--end', str(SIG_END + 200),
              '--no-step-log', 'true', '--no-warnings', 'true',
              '--time-to-teleport', '-1', '--collision.action', 'warn',
              '--seed', str(seed), '--step-method.ballistic', 'true',
              '--default.speeddev', '0'])
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-1500:])
    return dict(fcd=fcd, e1=os.path.join(RUND, tag + '.e1.xml'), sum=smf, tag=tag)


def analyse_signal(files):
    veh = W.read_fcd(files['fcd'])
    frames = W.by_timestep(veh)
    per_cycle = []
    for ci in CYCLES:
        red_on, grn_on = ci * CYC + GREEN + YELLOW, (ci + 1) * CYC
        pts, stats = W.track_queue_back(veh, APPROACH, red_on, grn_on, VQ, frames=frames)
        sf = W.fit_front(pts)
        chain_ids = set(stats[-1]['ids']) if stats else set()
        kq = float(np.median([s['k_queue'] for s in stats[len(stats)//2:]])) if len(stats) >= 4 else float('nan')
        go = []
        for vid in chain_ids:
            t, x, v = veh[vid]
            # no xmax: the head of the queue crosses the stop line onto the tail
            # edge before it exceeds VQ, and dropping it would falsely flag the
            # cycle as un-cleared.
            g = W.first_above(t, x, v, VQ, t0=grn_on, t1=grn_on + GREEN)
            if g:
                go.append(g)
        gf = W.fit_front(go)
        # residual check: did every queued vehicle get released within this green?
        cleared = len(go) >= len(chain_ids) and len(chain_ids) > 0
        n_fullstop = sum(1 for vid in chain_ids
                         if W.first_below(*veh[vid], VSTOP, t0=red_on, t1=grn_on) is not None)
        per_cycle.append(dict(cycle=ci, red_on=red_on, green_on=grn_on,
                              stop_front=sf, start_front=gf, k_queue=kq,
                              n_queued=len(chain_ids), n_released=len(go),
                              n_full_stop=n_fullstop, cleared=cleared,
                              queue_reach_x=min([p[1] for p in pts]) if pts else float('nan')))
    e1 = W.read_e1(files['e1'])
    arr = W.upstream_state(e1, 300.0, CYCLES[0] * CYC)
    last = R.read_summary(files['sum'])[-1]
    return _summarise(per_cycle, arr, last)


# ------------------------------------------------------------- 3b incident ---
INC_LEN, INC_X = 3200.0, 2400.0
INC_T0, INC_DUR = 600.0, 180.0
INC_END, INC_DEMAND = 1400.0, 1400.0


def run_incident(model, seed):
    os.makedirs(RUND, exist_ok=True)
    net, tag = os.path.join(NETD, 'inc.net.xml'), f'inc_{model}_s{seed}'
    add = os.path.join(RUND, tag + '.add.xml')
    open(add, 'w').write('<additional>\n'
                         f'  <inductionLoop id="up" lane="in_0" pos="300" period="60" '
                         f'file="{tag}.e1.xml"/>\n</additional>')
    rou = os.path.join(RUND, tag + '.rou.xml')
    open(rou, 'w').write(
        f'<routes>\n  {R.vtype_xml("car", model)}\n'
        f'  <vType id="blocker" carFollowModel="{model}" length="5.0" minGap="2.5" '
        f'tau="1.0" maxSpeed="30" accel="2.6" decel="4.5" impatience="0"/>\n'
        f'  <route id="r" edges="in"/>\n'
        f'  <flow id="f" type="car" route="r" begin="0" end="{INC_END}" '
        f'vehsPerHour="{INC_DEMAND}" departSpeed="max" departPos="base"/>\n'
        f'  <vehicle id="BLOCK" type="blocker" depart="{INC_T0 - 90}" '
        f'departSpeed="max" departPos="base">\n    <route edges="in"/>\n'
        f'    <stop lane="in_0" startPos="{INC_X-6}" endPos="{INC_X}" '
        f'duration="{INC_DUR}" parking="false"/>\n  </vehicle>\n</routes>')
    fcd, smf = os.path.join(RUND, tag + '.fcd.xml'), os.path.join(RUND, tag + '.sum.xml')
    p = sumo(['-n', net, '-r', rou, '-a', add, '--fcd-output', fcd,
              '--fcd-output.attributes', 'x,y,speed', '--summary-output', smf,
              '--step-length', '0.5', '--end', str(INC_END + 400),
              '--no-step-log', 'true', '--no-warnings', 'true',
              '--time-to-teleport', '-1', '--collision.action', 'warn',
              '--seed', str(seed), '--step-method.ballistic', 'true',
              '--default.speeddev', '0'])
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-1500:])
    return dict(fcd=fcd, e1=os.path.join(RUND, tag + '.e1.xml'), sum=smf, tag=tag)


def analyse_incident(files):
    veh = W.read_fcd(files['fcd'])
    frames = W.by_timestep(veh)
    t, x, v = veh['BLOCK']
    s = W.first_below(t, x, v, VSTOP, t0=0.0, xmin=INC_X - 20)
    t_block = s[0] if s else INC_T0
    t_rel = t_block + INC_DUR
    pts, stats = W.track_queue_back(veh, INC_X - 8, t_block, t_rel, VQ, frames=frames)
    sf = W.fit_front(pts)
    chain_ids = set(stats[-1]['ids']) if stats else set()
    kq = float(np.median([st['k_queue'] for st in stats[len(stats)//2:]])) if len(stats) >= 4 else float('nan')
    go = []
    for vid in chain_ids:
        tt, xx, vv = veh[vid]
        g = W.first_above(tt, xx, vv, VQ, t0=t_rel, t1=t_rel + 400, xmax=INC_X)
        if g:
            go.append(g)
    gf = W.fit_front(go)
    n_fullstop = sum(1 for vid in chain_ids
                     if W.first_below(*veh[vid], VSTOP, t0=t_block, t1=t_rel) is not None)
    per_cycle = [dict(cycle=0, red_on=t_block, green_on=t_rel, stop_front=sf,
                      start_front=gf, k_queue=kq, n_queued=len(chain_ids),
                      n_released=len(go), n_full_stop=n_fullstop,
                      cleared=len(go) >= len(chain_ids),
                      queue_reach_x=min([p[1] for p in pts]) if pts else float('nan'))]
    e1 = W.read_e1(files['e1'])
    arr = W.upstream_state(e1, 120.0, t_block)
    last = R.read_summary(files['sum'])[-1]
    out = _summarise(per_cycle, arr, last)
    out.update(t_block=t_block, t_release=t_rel)
    return out


# ------------------------------------------------------------------ shared ---
def _summarise(per_cycle, arr, last):
    good = [c for c in per_cycle if c['stop_front']['n'] >= 4]
    goodg = [c for c in per_cycle if c['start_front']['n'] >= 4]
    m = lambda cs, k, f: float(np.mean([c[k][f] for c in cs])) if cs else float('nan')
    sd = lambda cs, k, f: float(np.std([c[k][f] for c in cs], ddof=1)) if len(cs) > 1 else 0.0
    return dict(
        stop_front=dict(speed_ms=m(good, 'stop_front', 'speed_ms'),
                        r2=m(good, 'stop_front', 'r2'), sd_ms=sd(good, 'stop_front', 'speed_ms'),
                        n=int(sum(c['stop_front']['n'] for c in good)), n_cycles=len(good)),
        start_front=dict(speed_ms=m(goodg, 'start_front', 'speed_ms'),
                         r2=m(goodg, 'start_front', 'r2'), sd_ms=sd(goodg, 'start_front', 'speed_ms'),
                         n=int(sum(c['start_front']['n'] for c in goodg)), n_cycles=len(goodg)),
        k_queue_measured=float(np.nanmean([c['k_queue'] for c in per_cycle])),
        n_queued_mean=float(np.mean([c['n_queued'] for c in per_cycle])),
        full_stop_fraction=float(np.mean([c['n_full_stop'] / max(c['n_queued'], 1)
                                          for c in per_cycle])),
        queue_reach_x_min=float(np.nanmin([c['queue_reach_x'] for c in per_cycle])),
        n_cycles_cleared=sum(1 for c in per_cycle if c['cleared']),
        n_cycles_examined=len(per_cycle),
        per_cycle=per_cycle, arriving=arr,
        teleports=last['teleports'], collisions=last['collisions'],
        loaded=last['loaded'], inserted=last['inserted'],
        arrived=last['arrived'], running_end=last['running'])


def main():
    os.makedirs(RUND, exist_ok=True)
    W.build_straight(os.path.join(NETD, 'sig'), APPROACH, VF, 1, tls_at=APPROACH, tail_m=TAIL)
    W.build_straight(os.path.join(NETD, 'inc'), INC_LEN, VF, 1)
    fd = json.load(open(os.path.join(OUT, 'data', 'p1_fd_fits.json')))['fits']
    res = {}
    for model in MODELS:
        f = fd[model]
        kj, kc, qmax = f['k_jam_fit'], f['k_crit'], f['q_max']
        for exp, runner, analyser in (('signal', run_signal, analyse_signal),
                                      ('incident', run_incident, analyse_incident)):
            per_seed = []
            for sd in SEEDS:
                a = analyser(runner(model, sd))
                a['seed'] = sd
                per_seed.append(a)
            g = lambda fld, sub: float(np.nanmean([a[sub][fld] for a in per_seed]))
            arr = [a['arriving'] for a in per_seed if a['arriving']]
            q1 = float(np.mean([x['q_vehh'] for x in arr]))
            v1 = float(np.mean([x['v_ms'] for x in arr]))
            k1 = float(np.mean([x['k_vehkm'] for x in arr]))
            kq = float(np.nanmean([a['k_queue_measured'] for a in per_seed]))
            ws_m, wg_m = g('speed_ms', 'stop_front'), g('speed_ms', 'start_front')
            ws_pred = W.rankine_hugoniot(q1, k1, 0.0, kj)          # arriving -> jam
            ws_pred_kq = W.rankine_hugoniot(q1, k1, 0.0, kq)       # arriving -> measured queue
            wg_pred = W.rankine_hugoniot(0.0, kj, qmax, kc)        # jam -> capacity
            wg_pred_kq = W.rankine_hugoniot(0.0, kq, qmax, kc)
            e = lambda a, b: 100 * (a - b) / abs(b) if b == b and abs(b) > 1e-9 else float('nan')
            res[f'{model}|{exp}'] = dict(
                model=model, experiment=exp,
                fd_used=dict(k_jam=kj, k_crit=kc, q_max=qmax, w_ms=f['w_ms'],
                             v_free_ms=f['v_free_ms']),
                arriving_state=dict(q_vehh=q1, v_ms=v1, k_vehkm=k1),
                k_queue_measured=kq,
                stop_front_measured_ms=ws_m, stop_front_sd_ms=g('sd_ms', 'stop_front'),
                stop_front_r2=g('r2', 'stop_front'), stop_front_n=g('n', 'stop_front'),
                stop_front_predicted_ms=ws_pred, stop_front_err_pct=e(ws_m, ws_pred),
                stop_front_predicted_kq_ms=ws_pred_kq, stop_front_err_kq_pct=e(ws_m, ws_pred_kq),
                start_front_measured_ms=wg_m, start_front_sd_ms=g('sd_ms', 'start_front'),
                start_front_r2=g('r2', 'start_front'), start_front_n=g('n', 'start_front'),
                start_front_predicted_ms=wg_pred, start_front_err_pct=e(wg_m, wg_pred),
                start_front_predicted_kq_ms=wg_pred_kq, start_front_err_kq_pct=e(wg_m, wg_pred_kq),
                full_stop_fraction=float(np.mean([a['full_stop_fraction'] for a in per_seed])),
                n_queued_mean=float(np.mean([a['n_queued_mean'] for a in per_seed])),
                cycles_cleared=sum(a['n_cycles_cleared'] for a in per_seed),
                cycles_examined=sum(a['n_cycles_examined'] for a in per_seed),
                teleports=sum(a['teleports'] for a in per_seed),
                collisions=sum(a['collisions'] for a in per_seed),
                loaded=per_seed[0]['loaded'], inserted=per_seed[0]['inserted'],
                arrived=per_seed[0]['arrived'], running_end=per_seed[0]['running_end'],
                per_seed=per_seed)
            r = res[f'{model}|{exp}']
            print(f'{model:7s} {exp:9s} | stop {ws_m:6.2f} vs {ws_pred:6.2f} '
                  f'({r["stop_front_err_pct"]:+6.1f}%) R2={r["stop_front_r2"]:.3f} | '
                  f'start {wg_m:6.2f} vs {wg_pred:6.2f} ({r["start_front_err_pct"]:+6.1f}%) '
                  f'R2={r["start_front_r2"]:.3f} | kq={kq:5.1f} kj={kj:5.1f} '
                  f'fullstop={r["full_stop_fraction"]:.2f} tp={r["teleports"]:.0f}', flush=True)
    json.dump(res, open(os.path.join(OUT, 'data', 'p3_waves.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
