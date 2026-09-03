#!/usr/bin/env python3
"""PART 6 - CONSEQUENCE: models matched on free-flow speed AND capacity still
differ in w and k_j, and that difference changes a concrete engineering answer.

Step 1  For each car-following model, search tau so that the ring-measured
        triangular capacity q_max equals a common target (2000 veh/h).  maxSpeed,
        length and minGap are identical across models, so v_f is matched by
        construction and verified from the measurement.
Step 2  Refit each tuned model's FD -> report the residual spread in w and k_j.
Step 3  Run the identical incident scenario (full single-lane blockage) with each
        tuned model and measure
          * SPILLBACK TIME: how long until the queue back reaches an upstream
            junction 1000 m behind the incident,
          * CLEARANCE TIME: how long after the blockage is lifted until the last
            queued vehicle is moving again.
        Both are compared against the kinematic-wave prediction computed from that
        model's own tuned FD:  t_spill = L / |w_stop|,  w_stop = -q1/(k_j-k1).
"""
import os, sys, json, subprocess
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ring_lib as R
import wave_lib as W
from p1_fit import fit_model, agg

OUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NETD, RUND = os.path.join(OUT, 'net'), os.path.join(OUT, 'runs', 'p6')
RING = os.path.join(NETD, 'ring1000.net.xml')
L, N_EDGES, END, WARM, STEP = 1000.0, 20, 1500.0, 750.0, 0.5
MODELS = ['Krauss', 'IDM', 'EIDM', 'ACC']
Q_TARGET = 1950.0
FRACS = [0.04, 0.10, 0.14, 0.16, 0.18, 0.20, 0.22, 0.25, 0.28, 0.32,
         0.40, 0.50, 0.62, 0.75, 0.88]


def ring_fd(model, tau, seed=42):
    os.makedirs(RUND, exist_ok=True)
    kj = 1000.0 / 7.5
    pts = []
    for fr in FRACS:
        n = max(2, round(fr * kj))
        tag = f'p6_{model}_t{tau:.3f}_n{n}'
        rou, smf = os.path.join(RUND, tag + '.rou.xml'), os.path.join(RUND, tag + '.sum.xml')
        vt = R.vtype_xml('car', model, tau=tau)
        pt = None
        for f in (0.9, 0.6, 0.4, 0.25, 0.1, 0.0):
            R.write_ring_routes(rou, n, L, N_EDGES, vt, perturb=True, dep_factor=f)
            p = R.run_ring(RING, rou, smf, END, step=STEP, seed=seed)
            cand = R.ring_point(smf, L, WARM)
            if cand is None:
                continue
            pt = cand
            if abs(cand['running_last'] - n) < 0.5:
                break
        for f in (rou, smf):
            if os.path.exists(f):
                os.remove(f)
        if pt:
            pt.update(model=model, n_requested=n)
            pts.append(pt)
    return fit_model(agg(pts, key=('model', 'n_requested')))


def tune(model, q_target=Q_TARGET, tol=0.02):
    """Grid search over tau then secant refinement.

    Bisection is NOT safe here: capacity is monotonically decreasing in tau only
    for Krauss/ACC.  EIDM's fitted capacity is NON-monotonic (it peaks near
    tau=1.0), so a bracketing assumption silently fails.
    """
    grid = [0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.2]
    hist = []
    fits = {}
    for t in grid:
        f = ring_fd(model, t)
        fits[t] = f
        hist.append((t, f['q_max']))
    best = min(grid, key=lambda t: abs(fits[t]['q_max'] - q_target))
    # refine between the two grid points that bracket the target around `best`
    nbrs = [t for t in grid if t != best]
    nbrs.sort(key=lambda t: abs(t - best))
    for _ in range(6):
        f_b = fits[best]
        if abs(f_b['q_max'] - q_target) / q_target <= tol:
            return best, f_b, hist, True
        partner = next((t for t in nbrs
                        if (fits[t]['q_max'] - q_target) * (f_b['q_max'] - q_target) < 0), None)
        if partner is None:
            return best, f_b, hist, False
        mid = 0.5 * (best + partner)
        f = ring_fd(model, mid)
        fits[mid] = f
        hist.append((mid, f['q_max']))
        nbrs = [t for t in fits if t != mid]
        nbrs.sort(key=lambda t: abs(t - mid))
        best = mid
    return best, fits[best], hist, abs(fits[best]['q_max'] - q_target) / q_target <= 2 * tol


# ---------------------------------------------------------- incident scenario ---
INC_LEN, INC_X, JUNCTION_X = 3600.0, 2600.0, 2000.0     # junction 600 m upstream
INC_T0, INC_DUR, INC_END = 600.0, 300.0, 1600.0
INC_DEMAND = 1400.0
VQ, VSTOP = 3.0, 0.5


def run_incident(model, tau, seed):
    os.makedirs(RUND, exist_ok=True)
    net = os.path.join(NETD, 'inc6.net.xml')
    tag = f'p6inc_{model}_s{seed}'
    add = os.path.join(RUND, tag + '.add.xml')
    open(add, 'w').write(f'<additional><inductionLoop id="up0" lane="in_0" pos="300" '
                         f'period="60" file="{tag}.e1.xml"/></additional>')
    rou = os.path.join(RUND, tag + '.rou.xml')
    open(rou, 'w').write(
        f'<routes>\n  {R.vtype_xml("car", model, tau=tau)}\n'
        f'  <vType id="blocker" carFollowModel="{model}" length="5.0" minGap="2.5" '
        f'tau="{tau}" maxSpeed="30" accel="2.6" decel="4.5" impatience="0"/>\n'
        f'  <route id="r" edges="in"/>\n'
        f'  <flow id="f" type="car" route="r" begin="0" end="{INC_END}" '
        f'vehsPerHour="{INC_DEMAND}" departSpeed="max" departPos="base"/>\n'
        f'  <vehicle id="BLOCK" type="blocker" depart="{INC_T0-90}" departSpeed="max" '
        f'departPos="base">\n    <route edges="in"/>\n'
        f'    <stop lane="in_0" startPos="{INC_X-6}" endPos="{INC_X}" '
        f'duration="{INC_DUR}" parking="false"/>\n  </vehicle>\n</routes>')
    fcd, smf = os.path.join(RUND, tag + '.fcd.xml'), os.path.join(RUND, tag + '.sum.xml')
    p = subprocess.run(['sumo', '-n', net, '-r', rou, '-a', add, '--fcd-output', fcd,
                        '--fcd-output.attributes', 'x,y,speed', '--summary-output', smf,
                        '--step-length', '0.5', '--end', str(INC_END + 500),
                        '--no-step-log', 'true', '--no-warnings', 'true',
                        '--time-to-teleport', '-1', '--collision.action', 'warn',
                        '--seed', str(seed), '--step-method.ballistic', 'true',
                        '--default.speeddev', '0'], capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-800:])
    return dict(fcd=fcd, e1=os.path.join(RUND, tag + '.e1.xml'), sum=smf)


def analyse_incident(files):
    veh = W.read_fcd(files['fcd'])
    frames = W.by_timestep(veh)
    t, x, v = veh['BLOCK']
    s = W.first_below(t, x, v, VSTOP, t0=0.0, xmin=INC_X - 20)
    t_block = s[0] if s else INC_T0
    t_rel = t_block + INC_DUR
    pts, stats = W.track_queue_back(veh, INC_X - 8, t_block, t_rel + 200, VQ, frames=frames)
    # spillback: first time the queue back is at or upstream of the junction
    spill = next((p[0] for p in pts if p[1] <= JUNCTION_X and p[0] <= t_rel), None)
    reach = min([p[1] for p in pts], default=float('nan'))
    chain = set(stats[-1]['ids']) if stats else set()
    # clearance: last queued vehicle to resume motion after release
    resumes = []
    for vid in chain:
        tt, xx, vv = veh[vid]
        g = W.first_above(tt, xx, vv, VQ, t0=t_rel, t1=t_rel + 500)
        if g:
            resumes.append(g[0])
    clear = (max(resumes) - t_rel) if resumes else float('nan')
    e1 = W.read_e1(files['e1'])
    arr = W.upstream_state(e1, 120.0, t_block)
    sf = W.fit_front([p for p in pts if p[0] <= t_rel])
    last = R.read_summary(files['sum'])[-1]
    return dict(t_block=t_block, t_release=t_rel,
                spillback_time_s=(spill - t_block) if spill else float('nan'),
                spilled=spill is not None,
                queue_reach_x=reach, max_queue_len_m=INC_X - reach,
                clearance_time_s=clear, n_queued=len(chain),
                stop_front_ms=sf['speed_ms'], stop_front_r2=sf['r2'],
                arriving=arr, teleports=last['teleports'], collisions=last['collisions'],
                loaded=last['loaded'], inserted=last['inserted'], arrived=last['arrived'])


def main():
    os.makedirs(RUND, exist_ok=True)
    W.build_straight(os.path.join(NETD, 'inc6'), INC_LEN, 30.0, 1)
    out = dict(q_target=Q_TARGET, models={})
    for m in MODELS:
        tau, f, hist, ok = tune(m)
        print(f'{m:7s} tuned tau={tau:.3f} -> q_max={f["q_max"]:.0f} '
              f'(target {Q_TARGET:.0f}, {"OK" if ok else "NOT CONVERGED"}) '
              f'v_f(lowk)={f["v_free_lowest_k_ms"]:.2f} w={f["w_ms"]:.2f} '
              f'k_j={f["k_jam_fit"]:.1f}', flush=True)
        runs = []
        for sd in (42, 43, 44):
            runs.append(analyse_incident(run_incident(m, tau, sd)))
        q1 = float(np.mean([r['arriving']['q_vehh'] for r in runs]))
        k1 = float(np.mean([r['arriving']['k_vehkm'] for r in runs]))
        w_stop_pred = W.rankine_hugoniot(q1, k1, 0.0, f['k_jam_fit'])
        Lup = INC_X - JUNCTION_X
        out['models'][m] = dict(
            tau=tau, tuned_ok=ok, tune_history=hist, fd=f,
            arriving=dict(q_vehh=q1, k_vehkm=k1),
            w_stop_predicted_ms=w_stop_pred,
            spillback_time_predicted_s=Lup / abs(w_stop_pred),
            spillback_time_measured_s=float(np.mean([r['spillback_time_s'] for r in runs])),
            spillback_sd_s=float(np.std([r['spillback_time_s'] for r in runs], ddof=1)),
            clearance_time_measured_s=float(np.mean([r['clearance_time_s'] for r in runs])),
            clearance_sd_s=float(np.std([r['clearance_time_s'] for r in runs], ddof=1)),
            max_queue_len_m=float(np.mean([r['max_queue_len_m'] for r in runs])),
            n_queued=float(np.mean([r['n_queued'] for r in runs])),
            stop_front_ms=float(np.mean([r['stop_front_ms'] for r in runs])),
            stop_front_r2=float(np.mean([r['stop_front_r2'] for r in runs])),
            teleports=sum(r['teleports'] for r in runs),
            collisions=sum(r['collisions'] for r in runs),
            runs=runs)
        o = out['models'][m]
        print(f'        spillback {o["spillback_time_measured_s"]:6.1f}s '
              f'(pred {o["spillback_time_predicted_s"]:6.1f}s)  clearance '
              f'{o["clearance_time_measured_s"]:6.1f}s  queue {o["max_queue_len_m"]:6.0f} m '
              f'tp={o["teleports"]:.0f}', flush=True)
    # spread across capacity-matched models
    ms = out['models']
    for fld, lbl in (('w_ms', 'w'), ('k_jam_fit', 'k_j'), ('q_max', 'q_max'),
                     ('v_free_ms', 'v_f_triangular_fit'),
                     ('v_free_lowest_k_ms', 'v_f_at_lowest_density')):
        vals = [ms[m]['fd'][fld] for m in MODELS]
        out.setdefault('spread', {})[lbl] = dict(
            values={m: ms[m]['fd'][fld] for m in MODELS},
            min=min(vals), max=max(vals),
            spread_pct=100 * (max(vals) - min(vals)) / np.mean(vals))
    for fld in ('spillback_time_measured_s', 'clearance_time_measured_s'):
        vals = [ms[m][fld] for m in MODELS]
        out['spread'][fld] = dict(values={m: ms[m][fld] for m in MODELS},
                                  min=float(np.nanmin(vals)), max=float(np.nanmax(vals)),
                                  spread_pct=100 * (np.nanmax(vals) - np.nanmin(vals)) / np.nanmean(vals))
    json.dump(out, open(os.path.join(OUT, 'data', 'p6_consequence.json'), 'w'), indent=1)
    print('\nSPREAD across capacity-matched models:')
    for k, v in out['spread'].items():
        print(f'  {k:28s} {v["min"]:8.2f} .. {v["max"]:8.2f}  ({v["spread_pct"]:5.1f}%)')


if __name__ == '__main__':
    main()
