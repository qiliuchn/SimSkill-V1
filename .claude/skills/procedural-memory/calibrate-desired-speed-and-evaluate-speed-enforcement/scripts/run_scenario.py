#!/usr/bin/env python3
"""STAGE 2 - the automated-speed-enforcement TraCI controller, and the single
runner used for EVERY arm of the study (baseline included) so that the stepping
loop and bookkeeping code path are byte-identical across treatments.

Modes
  baseline  no intervention at all
  limit40   posted-limit reduction 50 -> 40 km/h on the measured corridor,
            NO enforcement (traci.lane.setMaxSpeed at t=0)
  point     point speed camera at --camera-pos: compliant drivers hold at or
            below the posted limit inside an upstream awareness zone and
            resume their own desired speed downstream of the camera
  section   average-speed (section) enforcement over [--sec-start, --sec-end]:
            compliant drivers hold at or below the limit for the whole segment

Partial compliance: each vehicle draws u ~ U(0,1) from a stream keyed by
(seed, vehicle id) ONLY - so the same vehicle gets the same u in every arm and
the compliant sets are nested across p (CRN on the compliance draw too).

Actuator (--actuator):
  speedfactor  traci.vehicle.setSpeedFactor(v, min(own_sf, limit_ratio)) and
               restore the vehicle's OWN sampled factor on release  [default]
  maxspeed     traci.vehicle.setMaxSpeed(v, enforce_ms) and restore the vType
               maxSpeed on release

Outputs per run: tripinfo.xml, summary.xml, e1.xml (aggregated E1),
e1_instant.xml (per-vehicle E1 spot speeds), ssm.xml, traj.csv.gz
(t,id,x,v,a - TraCI floating-car data), run_meta.json.
"""
import argparse
import gzip
import json
import os
import random
import sys

sys.path.append(os.environ['SUMO_HOME'] + '/tools')
import traci  # noqa: E402
import traci.constants as tc  # noqa: E402

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import build_network as bn  # noqa: E402

# The COMPILED net rounds lane speed to 2 decimals: 13.89 m/s = 50.004 km/h.
# Every speed threshold in this study uses the compiled value, not the nominal 50.
LIMIT_MS = 13.89
CORR_LEN = bn.N_SEG * bn.SEG_LEN          # 4000 m measured corridor
DET_POS = [600, 1400, 1900, 2000, 2100, 2300, 2600, 3000, 3500]


def write_routes(path, mu, sigma, vph_eb, vph_wb, demand_end):
    eb = ' '.join(['e_in'] + [f'e{i:02d}' for i in range(bn.N_SEG)] + ['e_out'])
    wb = ' '.join(['w_in'] + [f'w{i:02d}' for i in range(bn.N_SEG)] + ['w_out'])
    x = ['<routes>']
    x.append(f'    <vType id="car" vClass="passenger" length="4.5" minGap="2.5" accel="2.6" '
             f'decel="4.5" sigma="0.5" tau="1.0" '
             f'speedFactor="normc({mu:.6f},{sigma:.6f},0.2,2.0)">')
    x.append('        <param key="has.ssm.device" value="true"/>')
    x.append('        <param key="device.ssm.measures" value="TTC DRAC"/>')
    x.append('        <param key="device.ssm.thresholds" value="5.0 1.5"/>')
    x.append('        <param key="device.ssm.range" value="60.0"/>')
    x.append('        <param key="device.ssm.extratime" value="3.0"/>')
    x.append('    </vType>')
    x.append(f'    <route id="rEB" edges="{eb}"/>')
    x.append(f'    <route id="rWB" edges="{wb}"/>')
    x.append(f'    <flow id="eb" type="car" route="rEB" begin="0" end="{demand_end}" '
             f'vehsPerHour="{vph_eb}" departLane="free" departSpeed="desired"/>')
    x.append(f'    <flow id="wb" type="car" route="rWB" begin="0" end="{demand_end}" '
             f'vehsPerHour="{vph_wb}" departLane="free" departSpeed="desired"/>')
    x.append('</routes>')
    open(path, 'w').write('\n'.join(x) + '\n')


def write_detectors(path, period, lanes=2):
    x = ['<additional>']
    for p in DET_POS:
        idx = int(p // bn.SEG_LEN)
        pos = p - idx * bn.SEG_LEN
        for ln in range(lanes):
            x.append(f'    <inductionLoop id="e1_{p}_{ln}" lane="e{idx:02d}_{ln}" '
                     f'pos="{pos:.1f}" period="{period}" file="e1.xml" friendlyPos="true"/>')
            x.append(f'    <instantInductionLoop id="e1i_{p}_{ln}" lane="e{idx:02d}_{ln}" '
                     f'pos="{pos:.1f}" file="e1_instant.xml" friendlyPos="true"/>')
    x.append('</additional>')
    open(path, 'w').write('\n'.join(x) + '\n')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--net', required=True)
    ap.add_argument('--outdir', required=True)
    ap.add_argument('--mode', required=True,
                    choices=['baseline', 'limit40', 'point', 'section'])
    ap.add_argument('--p', type=float, default=0.0, help='compliant fraction')
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--mu', type=float, default=1.0)
    ap.add_argument('--sigma', type=float, default=0.10)
    ap.add_argument('--vph', type=float, default=1200.0)
    ap.add_argument('--demand-end', type=float, default=1800.0)
    ap.add_argument('--end', type=float, default=3600.0)
    ap.add_argument('--step-length', type=float, default=0.5)
    ap.add_argument('--camera-pos', type=float, default=2000.0)
    ap.add_argument('--zone-up', type=float, default=300.0)
    ap.add_argument('--zone-down', type=float, default=30.0)
    ap.add_argument('--sec-start', type=float, default=1000.0)
    ap.add_argument('--sec-end', type=float, default=3000.0)
    ap.add_argument('--reduced-kmh', type=float, default=40.0)
    ap.add_argument('--actuator', default='speedfactor',
                    choices=['speedfactor', 'maxspeed'])
    ap.add_argument('--no-traj', action='store_true')
    ap.add_argument('--det-period', type=float, default=300.0)
    a = ap.parse_args()

    os.makedirs(a.outdir, exist_ok=True)
    rou = os.path.join(a.outdir, 'demand.rou.xml')
    add = os.path.join(a.outdir, 'detectors.add.xml')
    write_routes(rou, a.mu, a.sigma, a.vph, a.vph, a.demand_end)
    write_detectors(add, a.det_period)

    label = f'{a.mode}_p{a.p}_s{a.seed}'
    cmd = ['sumo', '-n', a.net, '-r', rou, '-a', add,
           '--seed', str(a.seed), '--step-length', str(a.step_length),
           '--no-step-log', 'true', '--time-to-teleport', '300',
           '--end', str(a.end), '--start', '--quit-on-end',
           '--tripinfo-output', os.path.join(a.outdir, 'tripinfo.xml'),
           '--tripinfo-output.write-unfinished',
           '--summary-output', os.path.join(a.outdir, 'summary.xml'),
           '--device.ssm.file', os.path.join(a.outdir, 'ssm.xml'),
           '--collision-output', os.path.join(a.outdir, 'collisions.xml'),
           '--log', os.path.join(a.outdir, 'sumo.log')]
    traci.start(cmd, label=label)
    c = traci.getConnection(label)

    # posted-limit reduction: applied once, at t=0, to the measured corridor only
    if a.mode == 'limit40':
        v = a.reduced_kmh / 3.6
        for i in range(bn.N_SEG):
            for ln in range(2):
                c.lane.setMaxSpeed(f'e{i:02d}_{ln}', v)

    enforce_ms = LIMIT_MS          # cameras enforce the POSTED limit
    vtype_maxspeed = None
    state = {}          # vid -> dict
    traj = None
    if not a.no_traj:
        traj = gzip.open(os.path.join(a.outdir, 'traj.csv.gz'), 'wt')
        traj.write('t,id,x,v,a\n')

    hard_brakes = []    # (t, id, x, a)
    teleports_cum = 0
    n_capped = 0
    n_released = 0
    step = 0
    SUBS = (tc.VAR_POSITION, tc.VAR_SPEED, tc.VAR_ACCELERATION, tc.VAR_LANE_INDEX)

    while c.simulation.getMinExpectedNumber() > 0 and c.simulation.getTime() < a.end:
        c.simulationStep()
        t = c.simulation.getTime()
        for v in c.simulation.getDepartedIDList():
            c.vehicle.subscribe(v, SUBS)
            if vtype_maxspeed is None:
                vtype_maxspeed = c.vehicle.getMaxSpeed(v)
            sf = c.vehicle.getSpeedFactor(v)
            u = random.Random(f'{a.seed}:{v}').random()
            state[v] = {'sf': sf, 'u': u, 'compliant': u < a.p, 'capped': False,
                        'eb': v.startswith('eb')}
        res = c.vehicle.getAllSubscriptionResults()
        rows = []
        for v, d in res.items():
            st = state.get(v)
            if st is None:
                continue
            x = d[tc.VAR_POSITION][0]
            sp = d[tc.VAR_SPEED]
            ac = d[tc.VAR_ACCELERATION]
            if st['eb']:
                if traj is not None and -50.0 <= x <= CORR_LEN + 50.0:
                    rows.append(f'{t:.1f},{v},{x:.2f},{sp:.4f},{ac:.4f}\n')
                if ac <= -3.0 and 0.0 <= x <= CORR_LEN:
                    hard_brakes.append((t, v, x, ac))
                # ---- enforcement controller ----
                if a.mode in ('point', 'section') and st['compliant']:
                    if a.mode == 'point':
                        inzone = (a.camera_pos - a.zone_up) <= x <= (a.camera_pos + a.zone_down)
                    else:
                        inzone = a.sec_start <= x <= a.sec_end
                    if inzone and not st['capped']:
                        if a.actuator == 'speedfactor':
                            c.vehicle.setSpeedFactor(v, min(st['sf'], 1.0))
                        else:
                            c.vehicle.setMaxSpeed(v, min(vtype_maxspeed, enforce_ms))
                        st['capped'] = True
                        n_capped += 1
                    elif (not inzone) and st['capped']:
                        if a.actuator == 'speedfactor':
                            c.vehicle.setSpeedFactor(v, st['sf'])
                        else:
                            c.vehicle.setMaxSpeed(v, vtype_maxspeed)
                        st['capped'] = False
                        n_released += 1
        if rows:
            traj.writelines(rows)
        teleports_cum += c.simulation.getStartingTeleportNumber()
        step += 1

    running_at_end = c.vehicle.getIDCount()
    teleports_live = teleports_cum
    c.close()
    if traj is not None:
        traj.close()

    meta = {
        'args': vars(a), 'limit_ms_compiled': LIMIT_MS,
        'n_vehicles_seen': len(state),
        'n_eb': sum(1 for s in state.values() if s['eb']),
        'n_eb_compliant': sum(1 for s in state.values() if s['eb'] and s['compliant']),
        'n_capped_events': n_capped, 'n_released_events': n_released,
        'running_at_end': running_at_end, 'teleports_live_cumulative': teleports_live,
        'hard_brakes': [{'t': t_, 'id': v_, 'x': x_, 'a': a_} for t_, v_, x_, a_ in hard_brakes],
        'speed_factors': {v: s['sf'] for v, s in state.items()},
        'compliant': {v: s['compliant'] for v, s in state.items() if s['eb']},
    }
    json.dump(meta, open(os.path.join(a.outdir, 'run_meta.json'), 'w'))
    print(f"{label}: veh={len(state)} eb={meta['n_eb']} capped={n_capped} "
          f"released={n_released} running_at_end={running_at_end} hb={len(hard_brakes)}")


if __name__ == '__main__':
    main()
