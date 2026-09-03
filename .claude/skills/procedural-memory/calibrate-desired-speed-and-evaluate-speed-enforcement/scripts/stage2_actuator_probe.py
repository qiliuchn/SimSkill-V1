#!/usr/bin/env python3
"""STAGE 2 - measure the behavioural difference between the two TraCI actuators
an enforcement controller could use, instead of assuming it.

PROBE A (latency): does a setSpeedFactor / setMaxSpeed call take effect on the
CURRENT step, or only after the next simulationStep()? Read the vehicle's
speed and its own reported factor/maxSpeed immediately after the call without
stepping, then after one step, then after two.

PROBE B (limit-relative vs absolute): drive the capped vehicle onto a link whose
posted limit is RAISED to 20 m/s. setSpeedFactor is limit-relative so the cap
must follow the new limit; setMaxSpeed is absolute so it must not.

PROBE C (restoring heterogeneous desired speed on release): after release, does
every vehicle return to ITS OWN speedFactor x limit, and is the population
dispersion restored? Compared for both actuators and for the naive
"restore the speed it had when I capped it" variant.
"""
import json
import os
import sys

sys.path.append(os.environ['SUMO_HOME'] + '/tools')
import traci  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.append(HERE)
import build_network as bn  # noqa: E402
import analysis as A  # noqa: E402

LIMIT = 13.89
NET = sys.argv[1]
OUT = sys.argv[2]
os.makedirs(OUT, exist_ok=True)


def make_routes(path, n=40):
    eb = ' '.join(['e_in'] + [f'e{i:02d}' for i in range(bn.N_SEG)] + ['e_out'])
    x = ['<routes>',
         '    <vType id="car" vClass="passenger" length="4.5" minGap="2.5" accel="2.6"'
         ' decel="4.5" sigma="0" tau="1.0" speedFactor="normc(1.17563,0.17517,0.2,2.0)"/>',
         f'    <route id="rEB" edges="{eb}"/>']
    for i in range(n):
        x.append(f'    <vehicle id="v{i}" type="car" route="rEB" depart="{i*6}" '
                 f'departLane="0" departSpeed="desired"/>')
    x.append('</routes>')
    open(path, 'w').write('\n'.join(x) + '\n')


def start(label, rou, raise_limit_edge=None):
    cmd = ['sumo', '-n', NET, '-r', rou, '--seed', '7', '--step-length', '0.5',
           '--no-step-log', 'true', '--end', '3000', '--start', '--quit-on-end']
    traci.start(cmd, label=label)
    c = traci.getConnection(label)
    if raise_limit_edge is not None:
        for ln in range(2):
            c.lane.setMaxSpeed(f'{raise_limit_edge}_{ln}', 20.0)
    return c


R = {}
rou = os.path.join(OUT, 'probe.rou.xml')
make_routes(rou)

# ------------------------------------------------------------------- PROBE A
R['A_latency'] = {}
for act in ('speedfactor', 'maxspeed'):
    c = start(f'A_{act}', rou)
    log = None
    while c.simulation.getMinExpectedNumber() > 0:
        c.simulationStep()
        t = c.simulation.getTime()
        if 'v0' in c.vehicle.getIDList() and c.vehicle.getPosition('v0')[0] > 1000 and log is None:
            v = 'v0'
            own_sf = c.vehicle.getSpeedFactor(v)
            log = {'t_call': t, 'own_speedFactor': own_sf,
                   'allowedSpeed': c.vehicle.getAllowedSpeed(v),
                   'before': {'speed': c.vehicle.getSpeed(v),
                              'speedFactor': c.vehicle.getSpeedFactor(v),
                              'maxSpeed': c.vehicle.getMaxSpeed(v)}}
            if act == 'speedfactor':
                c.vehicle.setSpeedFactor(v, 1.0)
            else:
                c.vehicle.setMaxSpeed(v, LIMIT)
            log['same_step_no_step_call'] = {
                'speed': c.vehicle.getSpeed(v),
                'speedFactor': c.vehicle.getSpeedFactor(v),
                'maxSpeed': c.vehicle.getMaxSpeed(v)}
            for k in range(1, 5):
                c.simulationStep()
                log[f'after_{k}_steps'] = {
                    't': c.simulation.getTime(),
                    'speed': c.vehicle.getSpeed(v),
                    'speedFactor': c.vehicle.getSpeedFactor(v),
                    'maxSpeed': c.vehicle.getMaxSpeed(v)}
            break
    c.close()
    R['A_latency'][act] = log
    print(act, json.dumps(log, indent=1))

# ------------------------------------------------------------------- PROBE B
# raise the posted limit on e15 (x = 3000..3200) to 20 m/s, cap the vehicle at
# x ~ 1000, and see what speed it reaches on the raised-limit link.
R['B_limit_relative'] = {}
for act in ('speedfactor', 'maxspeed'):
    c = start(f'B_{act}', rou, raise_limit_edge='e15')
    capped = set()
    peak = {}
    while c.simulation.getMinExpectedNumber() > 0:
        c.simulationStep()
        for v in c.vehicle.getIDList():
            x = c.vehicle.getPosition(v)[0]
            if 1000 <= x and v not in capped:
                capped.add(v)
                if act == 'speedfactor':
                    c.vehicle.setSpeedFactor(v, 1.0)
                else:
                    c.vehicle.setMaxSpeed(v, LIMIT)
            if 3050 <= x <= 3190:
                peak[v] = max(peak.get(v, 0.0), c.vehicle.getSpeed(v))
    c.close()
    vals = list(peak.values())
    R['B_limit_relative'][act] = {
        'n': len(vals), 'mean_speed_on_20ms_link': A.mean(vals),
        'max_speed_on_20ms_link': max(vals), 'min': min(vals),
        'posted_on_that_link_ms': 20.0, 'cap_commanded_ms': LIMIT}
    print('B', act, R['B_limit_relative'][act])

# ------------------------------------------------------------------- PROBE C
# cap at x in [1700,2030] (the point-camera zone), release downstream, then
# measure realised speed at x in [2600,2800] against each vehicle's OWN
# speedFactor x limit.
R['C_release'] = {}
for act in ('speedfactor', 'maxspeed', 'maxspeed_naive_restore'):
    c = start(f'C_{act}', rou)
    own, capped, restore_val, downstream = {}, set(), {}, {}
    vtype_max = None
    while c.simulation.getMinExpectedNumber() > 0:
        c.simulationStep()
        for v in c.vehicle.getIDList():
            if v not in own:
                own[v] = c.vehicle.getSpeedFactor(v)
                if vtype_max is None:
                    vtype_max = c.vehicle.getMaxSpeed(v)
            x = c.vehicle.getPosition(v)[0]
            if 1700 <= x <= 2030 and v not in capped:
                capped.add(v)
                restore_val[v] = c.vehicle.getSpeed(v)
                if act == 'speedfactor':
                    c.vehicle.setSpeedFactor(v, min(own[v], 1.0))
                else:
                    c.vehicle.setMaxSpeed(v, LIMIT)
            elif x > 2030 and v in capped:
                capped.discard(v)
                if act == 'speedfactor':
                    c.vehicle.setSpeedFactor(v, own[v])
                elif act == 'maxspeed':
                    c.vehicle.setMaxSpeed(v, vtype_max)
                else:   # naive: restore the absolute speed it had when capped
                    c.vehicle.setMaxSpeed(v, restore_val[v])
            if 2600 <= x <= 2800:
                downstream[v] = max(downstream.get(v, 0.0), c.vehicle.getSpeed(v))
    c.close()
    ratio = [downstream[v] / (own[v] * LIMIT) for v in downstream]
    R['C_release'][act] = {
        'n': len(downstream),
        'mean_downstream_speed_ms': A.mean(list(downstream.values())),
        'sd_downstream_speed_ms': A.sd(list(downstream.values())),
        'sd_of_own_desired_ms': A.sd([own[v] * LIMIT for v in downstream]),
        'mean_ratio_realised_over_own_desired': A.mean(ratio),
        'frac_within_1pct_of_own_desired': sum(1 for r in ratio if r >= 0.99) / len(ratio),
    }
    print('C', act, R['C_release'][act])

json.dump(R, open(os.path.join(OUT, 'actuator_probe.json'), 'w'), indent=2)
print('wrote', os.path.join(OUT, 'actuator_probe.json'))
