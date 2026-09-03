#!/usr/bin/env python3
"""Build a ~4 km straight two-lane-per-direction suburban arterial in SUMO.

Geometry (all on y=0, so the vehicle's x coordinate IS its corridor distance):

    x = -400 ....... 0 ...200...400... ... 4000 ....... 4400
        nA          n0    n1   n2          n20         nB
        |<- entry ->|<---- 4.0 km measured corridor ---->|<- exit ->|

20 measured edges of 200 m each per direction (e00..e19 eastbound,
w00..w19 westbound), plus a 400 m entry/exit edge on each end so that
vehicles are already at their desired speed when they reach x = 0.

Posted speed 50 km/h (13.8889 m/s) everywhere, 2 lanes per direction,
priority junctions with only through connections (no turning, no signals),
so free-flow speed is driver-choice-limited, not control-limited.
"""
import argparse
import os
import subprocess
import sys

N_SEG = 20
SEG_LEN = 200.0
APPROACH = 400.0
POSTED_MS = 50.0 / 3.6  # 13.888888...


def node_x(i):
    return i * SEG_LEN


def build(outdir, lanes=2):
    os.makedirs(outdir, exist_ok=True)
    nod = ['<nodes>']
    nod.append(f'    <node id="nA" x="{-APPROACH}" y="0.0" type="priority"/>')
    for i in range(N_SEG + 1):
        nod.append(f'    <node id="n{i}" x="{node_x(i)}" y="0.0" type="priority"/>')
    nod.append(f'    <node id="nB" x="{node_x(N_SEG) + APPROACH}" y="0.0" type="priority"/>')
    nod.append('</nodes>')

    edg = ['<edges>']
    # eastbound
    edg.append(f'    <edge id="e_in" from="nA" to="n0" numLanes="{lanes}" speed="{POSTED_MS:.6f}" priority="10"/>')
    for i in range(N_SEG):
        edg.append(f'    <edge id="e{i:02d}" from="n{i}" to="n{i+1}" numLanes="{lanes}" speed="{POSTED_MS:.6f}" priority="10"/>')
    edg.append(f'    <edge id="e_out" from="n{N_SEG}" to="nB" numLanes="{lanes}" speed="{POSTED_MS:.6f}" priority="10"/>')
    # westbound
    edg.append(f'    <edge id="w_in" from="nB" to="n{N_SEG}" numLanes="{lanes}" speed="{POSTED_MS:.6f}" priority="10"/>')
    for i in range(N_SEG):
        j = N_SEG - 1 - i
        edg.append(f'    <edge id="w{i:02d}" from="n{j+1}" to="n{j}" numLanes="{lanes}" speed="{POSTED_MS:.6f}" priority="10"/>')
    edg.append(f'    <edge id="w_out" from="n0" to="nA" numLanes="{lanes}" speed="{POSTED_MS:.6f}" priority="10"/>')
    edg.append('</edges>')

    nod_f = os.path.join(outdir, 'arterial.nod.xml')
    edg_f = os.path.join(outdir, 'arterial.edg.xml')
    net_f = os.path.join(outdir, 'arterial.net.xml')
    open(nod_f, 'w').write('\n'.join(nod) + '\n')
    open(edg_f, 'w').write('\n'.join(edg) + '\n')

    cmd = ['netconvert', '-n', nod_f, '-e', edg_f, '-o', net_f,
           '--no-turnarounds', 'true',
           '--junctions.limit-turn-speed', '-1',   # never derate a through movement
           '--default.junctions.radius', '4',
           '--no-internal-links', 'false',
           '--offset.disable-normalization', 'true']
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stdout + r.stderr)
        raise SystemExit('netconvert failed')
    print(r.stderr.strip())
    print('wrote', net_f)
    return net_f


def routes(outdir, veh_per_hour_eb, veh_per_hour_wb, end_time, speed_factor,
           depart_speed='desired', vtype_extra='', fname='demand.rou.xml'):
    eb = ' '.join(['e_in'] + [f'e{i:02d}' for i in range(N_SEG)] + ['e_out'])
    wb = ' '.join(['w_in'] + [f'w{i:02d}' for i in range(N_SEG)] + ['w_out'])
    x = ['<routes>']
    x.append(f'    <vType id="car" vClass="passenger" length="4.5" minGap="2.5" accel="2.6" '
             f'decel="4.5" sigma="0.5" tau="1.0" speedFactor="{speed_factor}" {vtype_extra}>')
    x.append('        <param key="has.ssm.device" value="true"/>')
    x.append('        <param key="device.ssm.measures" value="TTC DRAC BR"/>')
    x.append('        <param key="device.ssm.thresholds" value="3.0 3.0 0.0"/>')
    x.append('        <param key="device.ssm.range" value="60.0"/>')
    x.append('        <param key="device.ssm.extratime" value="3.0"/>')
    x.append('    </vType>')
    x.append(f'    <route id="rEB" edges="{eb}"/>')
    x.append(f'    <route id="rWB" edges="{wb}"/>')
    x.append(f'    <flow id="eb" type="car" route="rEB" begin="0" end="{end_time}" '
             f'vehsPerHour="{veh_per_hour_eb}" departLane="free" departSpeed="{depart_speed}"/>')
    if veh_per_hour_wb > 0:
        x.append(f'    <flow id="wb" type="car" route="rWB" begin="0" end="{end_time}" '
                 f'vehsPerHour="{veh_per_hour_wb}" departLane="free" departSpeed="{depart_speed}"/>')
    x.append('</routes>')
    f = os.path.join(outdir, fname)
    open(f, 'w').write('\n'.join(x) + '\n')
    print('wrote', f)
    return f


def detectors(outdir, positions_m, fname='detectors.add.xml', period=300, lanes=2):
    """E1 induction loops on each eastbound lane at the given corridor x positions."""
    x = ['<additional>']
    for p in positions_m:
        idx = int(p // SEG_LEN)
        pos = p - idx * SEG_LEN
        for ln in range(lanes):
            x.append(f'    <inductionLoop id="e1_{int(p)}_{ln}" lane="e{idx:02d}_{ln}" '
                     f'pos="{pos:.1f}" period="{period}" file="e1.xml" friendlyPos="true"/>')
    x.append('</additional>')
    f = os.path.join(outdir, fname)
    open(f, 'w').write('\n'.join(x) + '\n')
    print('wrote', f)
    return f


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--outdir', required=True)
    a = ap.parse_args()
    build(a.outdir)
    routes(a.outdir, 700, 700, 1800, 'normc(1.0,0.1,0.2,2.0)')
    detectors(a.outdir, [600, 2000, 2600, 3600])
