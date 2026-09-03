#!/usr/bin/env python3
"""PART 5 - MOVING BOTTLENECK (Newell / Laval-Daganzo), built from first principles.

No skill or knowledge page in memory covers moving bottlenecks, so the theory used
here is stated explicitly and tested against each model's OWN part-1 triangular FD.

  5A  ONE lane, no passing possible.
      Every follower is forced to the truck's speed u, so the traffic state behind
      the truck is the FD point whose CHORD SLOPE q/k equals u -- on a triangular
      FD, the congested-branch point
          k_u = w*k_j/(u + w),   q_u = u*k_u          (u, w in km/h)
      Prediction: measured flow behind the truck = min(D, q_u), and the queue grows
      (demand is not served) only when D > q_u.

  5B  TWO lanes, truck occupies lane 0 and never changes lane.
      In the truck's moving frame only lane 1 is available, so the maximum passing
      rate is the moving-frame throughput of a SINGLE lane
          r = max_k [q(k) - u*k] = q_max - u*k_c      (triangular FD)
      Downstream the released vehicles spread over both lanes in free flow, and
      moving-frame conservation q_d - u*k_d = r with q_d = v_f*k_d gives
          q_d = r / (1 - u/v_f) = q_max               (triangular FD)
      i.e. the theory predicts the two-lane road's capacity collapses to exactly the
      ONE-lane capacity, INDEPENDENT of u, while the passing rate r does depend on u.
      Prediction: downstream flow = min(D, q_d), queue forms only when D > q_d.

Both experiments therefore test the same statement -- "a moving bottleneck is the
FD point defined by its own speed" -- but 5A tests the u-dependent chord-slope form
and 5B tests the u-independent moving-frame-maximum form.
"""
import os, sys, json, subprocess, argparse
from concurrent.futures import ProcessPoolExecutor
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wave_lib as W
import ring_lib as R

OUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NETD, RUND = os.path.join(OUT, 'net'), os.path.join(OUT, 'runs', 'p5')
MODELS = ['Krauss', 'IDM', 'EIDM', 'ACC']
SEEDS = [42, 43]
VF = 30.0
ROAD = 15000.0
DET_1L, DET_2L = 5000.0, 12000.0
T_TRUCK = 300.0
END = 2500.0
US = [6.0, 9.0, 12.0, 15.0]
D_1L = [600, 900, 1200, 1500, 1800, 2100]
D_2L = [1500, 2000, 2400, 2700, 3000, 3400]


def build_nets():
    os.makedirs(NETD, exist_ok=True)
    for lanes in (1, 2):
        pre = os.path.join(NETD, f'mb{lanes}')
        open(pre + '.nod.xml', 'w').write(
            f'<nodes><node id="A" x="0" y="0" type="priority"/>'
            f'<node id="B" x="{ROAD}" y="0" type="priority"/></nodes>')
        open(pre + '.edg.xml', 'w').write(
            f'<edges><edge id="in" from="A" to="B" numLanes="{lanes}" '
            f'speed="{VF}" priority="1"/></edges>')
        r = subprocess.run(['netconvert', '-n', pre + '.nod.xml', '-e', pre + '.edg.xml',
                            '-o', pre + '.net.xml', '--no-internal-links', 'true',
                            '--no-turnarounds', 'true',
                            '--offset.disable-normalization', 'true'],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr)


TRUCK_LC = ('lcStrategic="0" lcCooperative="0" lcSpeedGain="0" lcKeepRight="0" '
            'lcAssertive="0"')


def one(job):
    lanes, model, u, dem, seed = job
    os.makedirs(RUND, exist_ok=True)
    tag = f'mb{lanes}_{model}_u{u:g}_d{dem}_s{seed}'
    net = os.path.join(NETD, f'mb{lanes}.net.xml')
    det_x = DET_1L if lanes == 1 else DET_2L
    add = os.path.join(RUND, tag + '.add.xml')
    dets = ''.join(f'<inductionLoop id="d{i}" lane="in_{i}" pos="{det_x}" period="30" '
                   f'file="{tag}.d.xml"/>' for i in range(lanes))
    dets += ''.join(f'<inductionLoop id="u{i}" lane="in_{i}" pos="600" period="60" '
                    f'file="{tag}.u.xml"/>' for i in range(lanes))
    open(add, 'w').write(f'<additional>{dets}</additional>')
    rou = os.path.join(RUND, tag + '.rou.xml')
    open(rou, 'w').write(
        f'<routes>\n  {R.vtype_xml("car", model)}\n'
        f'  <vType id="truck" carFollowModel="{model}" length="5.0" minGap="2.5" '
        f'tau="1.0" accel="2.6" decel="4.5" maxSpeed="{u}" {TRUCK_LC}/>\n'
        f'  <route id="r" edges="in"/>\n'
        f'  <flow id="f" type="car" route="r" begin="0" end="{END}" '
        f'vehsPerHour="{dem}" departSpeed="max" departLane="best" departPos="base"/>\n'
        f'  <vehicle id="TRUCK" type="truck" route="r" depart="{T_TRUCK}" '
        f'departLane="0" departSpeed="{u}" departPos="base"/>\n</routes>')
    smf = os.path.join(RUND, tag + '.sum.xml')
    p = subprocess.run(['sumo', '-n', net, '-r', rou, '-a', add,
                        '--summary-output', smf, '--step-length', '0.5',
                        '--end', str(END), '--no-step-log', 'true',
                        '--no-warnings', 'true', '--time-to-teleport', '-1',
                        '--collision.action', 'warn', '--seed', str(seed),
                        '--step-method.ballistic', 'true', '--default.speeddev', '0'],
                       capture_output=True, text=True)
    if p.returncode != 0:
        return dict(lanes=lanes, model=model, u=u, demand=dem, seed=seed,
                    error=p.stderr[-500:])
    det = W.read_e1(os.path.join(RUND, tag + '.d.xml'))
    ups = W.read_e1(os.path.join(RUND, tag + '.u.xml'))
    t_pass = T_TRUCK + det_x / u            # truck reaches the detector
    t_exit = T_TRUCK + ROAD / u             # truck leaves the road
    if lanes == 1:
        # 5A: the quantity of interest is the state INSIDE the platoon that the
        # truck drags behind it.  Once the platoon tail has passed the loop, the
        # loop again sees free-flow vehicles that have not yet caught up, so a
        # plain time-window average mixes two states.  Select the intervals in
        # which the loop is actually inside the platoon (speed <= 1.3u).
        t0, t1 = t_pass + 30.0, min(END, t_exit) - 30.0
        win = [r for r in det if t0 <= r['begin'] and r['end'] <= t1 and r['nVehContrib'] > 0]
        plat = [r for r in win if r['harmonicMeanSpeed'] <= 1.3 * u]
        st = _state(plat) or _state(win)   # sparse platoon -> fall back to window
        # slow_fraction is the threshold indicator: if demand exceeds the moving
        # bottleneck's capacity the platoon GROWS and eventually covers the whole
        # window (fraction -> 1); if not, the platoon is finite and passes by.
        slow_frac = len(plat) / len(win) if win else float('nan')
        st_all = _state(win)
        lane_q = {}
    else:
        # 5B: measure DOWNSTREAM of the truck, after the vehicles that were already
        # ahead of it at t=T_TRUCK have cleared the detector.
        t0, t1 = T_TRUCK + det_x / VF + 60.0, min(t_pass - 30.0, END)
        win = [r for r in det if t0 <= r['begin'] and r['end'] <= t1]
        st = _state([r for r in win if r['nVehContrib'] > 0])
        st_all, slow_frac = st, float('nan')
        lane_q = {}
        for i in range(lanes):
            rs = [r for r in win if r['id'] == f'd{i}']
            dur = sum(r['end'] - r['begin'] for r in rs)
            lane_q[f'lane{i}'] = (sum(r['nVehContrib'] for r in rs) / dur * 3600.0
                                  if dur > 0 else 0.0)
    su = W.upstream_state(ups, T_TRUCK + 200, min(t_exit, END))
    last = R.read_summary(smf)[-1]
    for f in (add, rou, smf, os.path.join(RUND, tag + '.d.xml'),
              os.path.join(RUND, tag + '.u.xml')):
        if os.path.exists(f):
            os.remove(f)
    if st is None:
        return dict(lanes=lanes, model=model, u=u, demand=dem, seed=seed,
                    error=f'window too short/empty [{t0:.0f},{t1:.0f}]')
    return dict(lanes=lanes, model=model, u=u, demand=dem, seed=seed,
                win=[t0, t1], q_meas=st['q_vehh'], v_meas=st['v_ms'],
                k_meas=st['k_vehkm'], n_meas=st['n'],
                q_window_all=(st_all['q_vehh'] if st_all else float('nan')),
                v_window_all=(st_all['v_ms'] if st_all else float('nan')),
                slow_fraction=slow_frac, lane_q=lane_q,
                q_up=(su['q_vehh'] if su else float('nan')),
                v_up=(su['v_ms'] if su else float('nan')),
                teleports=last['teleports'], collisions=last['collisions'],
                loaded=last['loaded'], inserted=last['inserted'],
                arrived=last['arrived'], running_end=last['running'],
                insertion_deficit=last['loaded'] - last['inserted'])


def _state(rows):
    """Station state; lane-aware (flow summed across lanes)."""
    return W.upstream_state(rows, -1e9, 1e9)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--workers', type=int, default=10)
    a = ap.parse_args()
    build_nets()
    jobs = ([(1, m, u, d, s) for m in MODELS for u in US for d in D_1L for s in SEEDS] +
            [(2, m, u, d, s) for m in MODELS for u in US for d in D_2L for s in SEEDS])
    print('jobs:', len(jobs), flush=True)
    res = []
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        for i, r in enumerate(ex.map(one, jobs, chunksize=2)):
            res.append(r)
            if (i + 1) % 60 == 0:
                print(f'{i+1}/{len(jobs)}', flush=True)
    json.dump(res, open(os.path.join(OUT, 'data', 'p5_points.json'), 'w'), indent=1)
    print('errors:', len([r for r in res if 'error' in r]))

    fd = json.load(open(os.path.join(OUT, 'data', 'p1_fd_fits.json')))['fits']
    rows = []
    for lanes in (1, 2):
        for m in MODELS:
            f = fd[m]
            vf_kmh, w_kmh, kj, kc, qmax = (f['v_free_kmh'], f['w_kmh'], f['k_jam_fit'],
                                           f['k_crit'], f['q_max'])
            for u in US:
                ukmh = u * 3.6
                if lanes == 1:
                    k_pred = w_kmh * kj / (ukmh + w_kmh)
                    q_pred = ukmh * k_pred
                    r_pred = float('nan')
                else:
                    r_pred = qmax - ukmh * kc                      # passing rate
                    q_pred = r_pred / (1.0 - u / (vf_kmh / 3.6))   # downstream flow
                    k_pred = q_pred / vf_kmh
                cells = {}
                for r in res:
                    if 'error' in r or r['lanes'] != lanes or r['model'] != m or r['u'] != u:
                        continue
                    cells.setdefault(r['demand'], []).append(r)
                per_d = []
                for d, rs in sorted(cells.items()):
                    mean = lambda fl: float(np.mean([x[fl] for x in rs]))
                    per_d.append(dict(demand=d, q_meas=mean('q_meas'),
                                      q_sd=float(np.std([x['q_meas'] for x in rs], ddof=1)),
                                      v_meas=mean('v_meas'), k_meas=mean('k_meas'),
                                      v_up=mean('v_up'),
                                      insertion_deficit=mean('insertion_deficit'),
                                      served_ratio=mean('q_meas') / d,
                                      queue_forming=bool(mean('q_meas') < 0.95 * d),
                                      slow_fraction=float(np.mean([x['slow_fraction'] for x in rs])),
                                      q_window_all=mean('q_window_all'),
                                      lane_q={k: float(np.mean([x['lane_q'][k] for x in rs]))
                                              for k in rs[0]['lane_q']},
                                      teleports=sum(x['teleports'] for x in rs),
                                      collisions=sum(x['collisions'] for x in rs)))
                # Saturated == the measured state can no longer carry the offered
                # demand.  On ONE lane every follower is trapped behind the truck at
                # speed u regardless of demand, so the platoon always exists; what
                # identifies saturation is the platoon FLOW falling below demand.
                sat = [p for p in per_d if p['queue_forming']]
                served = [p['demand'] for p in per_d if not p['queue_forming']]
                thr_obs = max(served) if served else float('nan')
                q_sat = float(np.mean([p['q_meas'] for p in sat])) if sat else float('nan')
                q_sat_sd = float(np.std([p['q_meas'] for p in sat], ddof=1)) if len(sat) > 1 else 0.0
                rows.append(dict(lanes=lanes, model=m, u_ms=u,
                                 q_predicted=q_pred, k_predicted=k_pred,
                                 r_passing_predicted=r_pred,
                                 q_measured_saturated=q_sat, q_measured_sd=q_sat_sd,
                                 err_pct=100 * (q_sat - q_pred) / q_pred if q_pred else float('nan'),
                                 k_measured_saturated=float(np.mean([p['k_meas'] for p in sat])) if sat else float('nan'),
                                 v_measured_saturated=float(np.mean([p['v_meas'] for p in sat])) if sat else float('nan'),
                                 threshold_demand_observed=thr_obs,
                                 threshold_demand_predicted=q_pred,
                                 per_demand=per_d,
                                 teleports=sum(p['teleports'] for p in per_d),
                                 collisions=sum(p['collisions'] for p in per_d)))
    json.dump(rows, open(os.path.join(OUT, 'data', 'p5_moving_bottleneck.json'), 'w'), indent=1)
    print(f'\n{"lanes":5s} {"model":7s} {"u m/s":>6s} {"q_pred":>8s} {"q_meas":>8s} {"err%":>7s} '
          f'{"v_meas":>7s} {"thr_obs":>8s} {"tp":>4s}')
    for r in rows:
        print(f'{r["lanes"]:5d} {r["model"]:7s} {r["u_ms"]:6.1f} {r["q_predicted"]:8.0f} '
              f'{r["q_measured_saturated"]:8.0f} {r["err_pct"]:+7.1f} '
              f'{r["v_measured_saturated"]:7.2f} {str(r["threshold_demand_observed"]):>8s} '
              f'{r["teleports"]:4.0f}')


if __name__ == '__main__':
    main()
