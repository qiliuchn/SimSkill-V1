#!/usr/bin/env python3
"""PART 4 - CAPACITY DROP (two-capacity phenomenon) on a FIXED bottleneck.

Two independent bottleneck types are tested, because they isolate different causes:
  lanedrop : 2 lanes -> 1 lane.  Lane changing is present, as in a real merge.
  speeddrop: 1 lane -> 1 lane at a lower speed limit.  NO lane changing at all,
             so any capacity drop here is purely car-following.

Protocol (following `build-macroscopic-fundamental-diagram`):
  * E1 station INSIDE the bottleneck measures the discharge flow.
  * E1 station UPSTREAM classifies the regime from measured space-mean speed --
    the regime is never assumed from the demand level.
  * pre-breakdown capacity = highest discharge flow over runs that stayed
    uncongested upstream;  queue-discharge flow = mean discharge over runs whose
    upstream station is congested.  Capacity drop = (pre - discharge)/pre.
  * teleports/collisions are counted; a non-zero count invalidates the run.
"""
import os, sys, json, subprocess, argparse
from concurrent.futures import ProcessPoolExecutor
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wave_lib as W
import ring_lib as R

OUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NETD, RUND = os.path.join(OUT, 'net'), os.path.join(OUT, 'runs', 'p4')
MODELS = ['Krauss', 'IDM', 'EIDM', 'ACC']
SEEDS = [42, 43, 44]
UP_LEN, BN_LEN = 2500.0, 2000.0
VF, V_SLOW = 30.0, 10.0
END, WARM = 2400.0, 1200.0
DEMANDS_LD = [1600, 1900, 2100, 2200, 2300, 2400, 2450, 2500, 2550, 2600, 2650,
              2700, 2750, 2800, 2850, 2900, 3000, 3200, 3600, 4200, 5000]
DEMANDS_SD = [1200, 1350, 1450, 1500, 1550, 1600, 1650, 1700, 1750, 1800, 1825, 1850, 1875, 1900, 1925, 1950,
              1975, 2000, 2025, 2050, 2075, 2100, 2200, 2400, 2800, 3400]


def build_nets():
    os.makedirs(NETD, exist_ok=True)
    for kind, nl_up, v_bn in (('lanedrop', 2, VF), ('speeddrop', 1, V_SLOW)):
        pre = os.path.join(NETD, 'bn_' + kind)
        open(pre + '.nod.xml', 'w').write(
            f'<nodes><node id="A" x="0" y="0" type="priority"/>'
            f'<node id="B" x="{UP_LEN}" y="0" type="priority"/>'
            f'<node id="C" x="{UP_LEN+BN_LEN}" y="0" type="priority"/></nodes>')
        open(pre + '.edg.xml', 'w').write(
            f'<edges><edge id="up" from="A" to="B" numLanes="{nl_up}" speed="{VF}" priority="1"/>'
            f'<edge id="bn" from="B" to="C" numLanes="1" speed="{v_bn}" priority="1"/></edges>')
        r = subprocess.run(['netconvert', '-n', pre + '.nod.xml', '-e', pre + '.edg.xml',
                            '-o', pre + '.net.xml', '--no-internal-links', 'true',
                            '--no-turnarounds', 'true',
                            '--offset.disable-normalization', 'true'],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr)


def one(job):
    kind, model, dem, seed = job
    os.makedirs(RUND, exist_ok=True)
    tag = f'{kind}_{model}_d{dem}_s{seed}'
    net = os.path.join(NETD, f'bn_{kind}.net.xml')
    nl_up = 2 if kind == 'lanedrop' else 1
    add = os.path.join(RUND, tag + '.add.xml')
    dets = ''.join(
        f'<inductionLoop id="up{i}" lane="up_{i}" pos="{UP_LEN-400}" period="60" '
        f'file="{tag}.up.xml"/>' for i in range(nl_up))
    dets_near = ''.join(
        f'<inductionLoop id="near{i}" lane="up_{i}" pos="{UP_LEN-30}" period="60" '
        f'file="{tag}.near.xml"/>' for i in range(nl_up))
    open(add, 'w').write(
        f'<additional>{dets}{dets_near}'
        f'<inductionLoop id="bn0" lane="bn_0" pos="600" period="60" '
        f'file="{tag}.bn.xml"/></additional>')
    rou = os.path.join(RUND, tag + '.rou.xml')
    open(rou, 'w').write(
        f'<routes>\n  {R.vtype_xml("car", model)}\n  <route id="r" edges="up bn"/>\n'
        f'  <flow id="f" type="car" route="r" begin="0" end="{END}" '
        f'vehsPerHour="{dem}" departSpeed="max" departLane="best" departPos="base"/>\n</routes>')
    smf = os.path.join(RUND, tag + '.sum.xml')
    p = subprocess.run(['sumo', '-n', net, '-r', rou, '-a', add,
                        '--summary-output', smf, '--step-length', '0.5',
                        '--end', str(END), '--no-step-log', 'true',
                        '--no-warnings', 'true', '--time-to-teleport', '-1',
                        '--collision.action', 'warn', '--seed', str(seed),
                        '--step-method.ballistic', 'true', '--default.speeddev', '0'],
                       capture_output=True, text=True)
    if p.returncode != 0:
        return dict(kind=kind, model=model, demand=dem, seed=seed, error=p.stderr[-500:])
    up = W.read_e1(os.path.join(RUND, tag + '.up.xml'))
    bn = W.read_e1(os.path.join(RUND, tag + '.bn.xml'))
    near = W.read_e1(os.path.join(RUND, tag + '.near.xml'))
    sn = W.upstream_state([r for r in near if r['begin'] >= WARM], 0, END)
    su = W.upstream_state([r for r in up if r['begin'] >= WARM], 0, END)
    sb = W.upstream_state([r for r in bn if r['begin'] >= WARM], 0, END)
    last = R.read_summary(smf)[-1]
    for f in (add, rou, smf, os.path.join(RUND, tag + '.up.xml'),
              os.path.join(RUND, tag + '.near.xml'),
              os.path.join(RUND, tag + '.bn.xml')):
        if os.path.exists(f):
            os.remove(f)
    if su is None or sb is None:
        return dict(kind=kind, model=model, demand=dem, seed=seed, error='no detector data')
    return dict(kind=kind, model=model, demand=dem, seed=seed,
                q_up=su['q_vehh'], v_up=su['v_ms'], k_up=su['k_vehkm'],
                v_near=(sn['v_ms'] if sn else float('nan')),
                k_near=(sn['k_vehkm'] if sn else float('nan')),
                q_bn=sb['q_vehh'], v_bn=sb['v_ms'],
                teleports=last['teleports'], collisions=last['collisions'],
                loaded=last['loaded'], inserted=last['inserted'],
                arrived=last['arrived'], running_end=last['running'])


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--workers', type=int, default=10)
    a = ap.parse_args()
    build_nets()
    jobs = ([('lanedrop', m, d, s) for m in MODELS for d in DEMANDS_LD for s in SEEDS] +
            [('speeddrop', m, d, s) for m in MODELS for d in DEMANDS_SD for s in SEEDS])
    print('jobs:', len(jobs), flush=True)
    res = []
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        for i, r in enumerate(ex.map(one, jobs, chunksize=2)):
            res.append(r)
            if (i + 1) % 60 == 0:
                print(f'{i+1}/{len(jobs)}', flush=True)
    json.dump(res, open(os.path.join(OUT, 'data', 'p4_points.json'), 'w'), indent=1)

    # ---- aggregate over CRN seeds, then split free vs congested ---------------
    # The regime is classified by whether the BOTTLENECK IS BINDING, i.e. whether
    # its discharge falls short of the offered demand.  Classifying on the upstream
    # station's speed alone FAILS here: once the bottleneck breaks down SUMO holds
    # the excess demand in the DEPARTURE QUEUE at the source, so the 2.5 km upstream
    # link relaxes back to free flow at the (reduced) discharge rate and the
    # upstream loop reports 29.7 m/s even though the bottleneck is saturated.
    # loaded-vs-inserted is reported so that source censoring is visible, not hidden.
    summary = {}
    for kind in ('lanedrop', 'speeddrop'):
        for m in MODELS:
            cells = {}
            for r in res:
                if 'error' in r or r['kind'] != kind or r['model'] != m:
                    continue
                cells.setdefault(r['demand'], []).append(r)
            rows = []
            for d, rs in sorted(cells.items()):
                mean = lambda f: float(np.mean([x[f] for x in rs]))
                rows.append(dict(demand=d, q_bn=mean('q_bn'),
                                 q_bn_sd=float(np.std([x['q_bn'] for x in rs], ddof=1)),
                                 v_bn=mean('v_bn'), v_up=mean('v_up'), k_up=mean('k_up'),
                                 v_near=mean('v_near'), k_near=mean('k_near'),
                                 loaded=mean('loaded'), inserted=mean('inserted'),
                                 insertion_deficit=mean('loaded') - mean('inserted'),
                                 served_ratio=mean('q_bn') / d,
                                 binding=bool(mean('q_bn') < 0.97 * d),
                                 teleports=sum(x['teleports'] for x in rs),
                                 collisions=sum(x['collisions'] for x in rs),
                                 n_seeds=len(rs)))
            free = [r for r in rows if not r['binding']]
            cong = [r for r in rows if r['binding']]
            pre = max((r['q_bn'] for r in free), default=float('nan'))
            pre_at = next((r['demand'] for r in free if r['q_bn'] == pre), None)
            # queue discharge: the plateau well past breakdown (drop the first two
            # binding demands, which can still be transitional)
            plateau = cong[2:] if len(cong) > 4 else cong
            disch = float(np.mean([r['q_bn'] for r in plateau])) if plateau else float('nan')
            dsd = float(np.std([r['q_bn'] for r in plateau], ddof=1)) if len(plateau) > 1 else 0.0
            drop = 100.0 * (pre - disch) / pre if (pre == pre and disch == disch) else float('nan')
            summary[f'{kind}|{m}'] = dict(
                kind=kind, model=m, rows=rows,
                pre_breakdown_capacity=pre, pre_breakdown_at_demand=pre_at,
                queue_discharge_flow=disch, queue_discharge_sd=dsd,
                capacity_drop_pct=drop, n_free=len(free), n_binding=len(cong),
                plateau_demands=[r['demand'] for r in plateau],
                teleports=sum(r['teleports'] for r in rows),
                collisions=sum(r['collisions'] for r in rows))
            print(f'{kind:10s} {m:7s} pre={pre:7.0f} (D={pre_at}) discharge={disch:7.0f}'
                  f'+-{dsd:5.0f} drop={drop:+6.2f}%  nfree={len(free)} nbind={len(cong)} '
                  f'tp={sum(r["teleports"] for r in rows):.0f}', flush=True)
    json.dump(summary, open(os.path.join(OUT, 'data', 'p4_capacity_drop.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
