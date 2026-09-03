#!/usr/bin/env python3
"""Shared library: build ring route files, run a ring point, parse summary output,
fit a triangular fundamental diagram.

Density on a closed ring is CONTROLLED EXACTLY by vehicle count:
    k [veh/km] = 1000 * N_running / L_ring[m]
No detector estimation is needed, which is why the ring is the right instrument
for an FD (cf. `build-macroscopic-fundamental-diagram`, which must estimate k
from E1 occupancy on an open road).

Space-mean speed on a ring == the arithmetic mean over the vehicles present at an
instant (they all occupy the same homogeneous 1-D space), which is exactly what
SUMO's <summary> meanSpeed reports.  So  q = k * v_bar  is exact, not an estimate.
"""
import os, sys, math, subprocess, json
import xml.etree.ElementTree as ET

SUMO = 'sumo'

# ---------------------------------------------------------------- vType XML ---
BASE = dict(accel=2.6, decel=4.5, emergencyDecel=9.0, length=5.0, minGap=2.5,
            tau=1.0, maxSpeed=30.0, sigma=0.5)


def vtype_xml(vid, cfmodel, **over):
    p = dict(BASE)
    p.update(over)
    extra = p.pop('extra', '')
    attrs = ' '.join(f'{k}="{v}"' for k, v in p.items())
    return f'<vType id="{vid}" carFollowModel="{cfmodel}" {attrs} {extra}/>'


# --------------------------------------------------------------- ring routes ---
def write_ring_routes(path, n_veh, L, n_edges, vtype_line, vtype_id='car',
                      laps=50, perturb=True, perturb_edge=None,
                      perturb_dur=5.0, dep_factor=0.9):
    """Place n_veh vehicles evenly on the ring, downstream-most first so each
    insertion sees its leader.  Vehicle 'v0' optionally gets a ONE-SHOT <stop>
    (a disclosed transient brake pulse, per the phantom-jam skill) to break the
    symmetric unstable equilibrium of a deterministic car-following model."""
    c = L / n_edges
    if perturb_edge is None:
        perturb_edge = n_edges // 2
    order = list(range(n_veh))[::-1]          # descending position
    # Insert every vehicle at (a conservative estimate of) its equilibrium speed.
    # departSpeed="max" fails at moderate density because the FIRST inserted vehicle
    # gets v_free and every follower then needs a free-flow-sized safe gap, so the
    # insertion cascade aborts and the ring silently ends up under-filled.
    import re as _re
    def _attr(name, dflt):
        m = _re.search(rf'{name}="([^"]+)"', vtype_line)
        return float(m.group(1)) if m else dflt
    _len, _gap, _tau, _vmax = (_attr('length', 5.0), _attr('minGap', 2.5),
                               _attr('tau', 1.0), _attr('maxSpeed', 30.0))
    s = L / max(n_veh, 1)
    # cap strictly below maxSpeed: SUMO rejects a departSpeed the model cannot
    # itself sustain ("slow lane ahead") -- IDM's equilibrium speed is < v0 at any
    # finite spacing, so departing exactly at v0 aborts insertion for IDM.
    # W99 and ACC need a smaller departSpeed than the Krauss/IDM gap rule implies
    # (their own standstill/headway parameters differ), so dep_factor is tunable and
    # the caller retries with a lower factor until the ring is FULLY loaded.
    v_dep = max(0.0, min(0.95 * _vmax,
                         dep_factor * (s - _len - _gap) / max(_tau, 1e-3)))
    lines = ['<routes>', '  ' + vtype_line]
    for i in order:
        p = i * L / n_veh
        j = min(int(p // c), n_edges - 1)
        pos = p - j * c
        route = ' '.join(f'e{(j + t) % n_edges}' for t in range(laps * n_edges))
        stop = ''
        if perturb and i == 0:
            stop = (f'\n      <stop lane="e{perturb_edge}_0" endPos="{c*0.5:.2f}" '
                    f'duration="{perturb_dur}"/>\n    ')
        lines.append(
            f'  <vehicle id="v{i}" type="{vtype_id}" depart="0" departLane="0" '
            f'departPos="{pos:.3f}" departSpeed="{v_dep:.3f}">'
            f'\n    <route edges="{route}"/>{stop}</vehicle>')
    lines.append('</routes>')
    with open(path, 'w') as f:
        f.write('\n'.join(lines))


# ------------------------------------------------------------------- runner ---
def run_ring(netfile, roufile, sumfile, end, step=0.5, seed=42, extra=()):
    cmd = [SUMO, '-n', netfile, '-r', roufile,
           '--summary-output', sumfile,
           '--step-length', str(step),
           '--begin', '0', '--end', str(end),
           '--no-step-log', 'true', '--no-warnings', 'true',
           '--time-to-teleport', '-1',
           '--collision.action', 'warn',
           '--seed', str(seed),
           '--step-method.ballistic', 'true',
           '--default.speeddev', '0'] + list(extra)
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r


def read_summary(path):
    rows = []
    for _, el in ET.iterparse(path, events=('end',)):
        if el.tag == 'step':
            rows.append({k: float(v) for k, v in el.attrib.items()})
            el.clear()
    return rows


def ring_point(sumfile, L, warmup):
    """Return dict with exact density, space-mean speed, flow over the window."""
    rows = [r for r in read_summary(sumfile) if r['time'] >= warmup]
    if not rows:
        return None
    ks, vs, qs = [], [], []
    for r in rows:
        n = r['running']
        if n <= 0:
            continue
        k = 1000.0 * n / L                       # veh/km
        v = r['meanSpeed']                       # m/s  (space-mean on a ring)
        ks.append(k); vs.append(v); qs.append(k * v * 3.6)   # veh/h
    if not ks:
        return None
    last = rows[-1]
    n = len(ks)
    mean = lambda a: sum(a) / len(a)
    sd = lambda a, m: math.sqrt(sum((x - m) ** 2 for x in a) / max(1, len(a) - 1))
    mv, mq = mean(vs), mean(qs)
    return dict(k=mean(ks), v=mv, q=mq, v_sd=sd(vs, mv), q_sd=sd(qs, mq),
                v_min=min(vs), n_samples=n,
                running_last=last['running'], loaded=last['loaded'],
                inserted=last['inserted'], arrived=last['arrived'],
                teleports=last['teleports'], collisions=last['collisions'],
                halting_mean=mean([r['halting'] for r in rows]))


# ----------------------------------------------------- triangular FD fitting ---
def fit_triangular(points, v_free_hint=30.0):
    """points: list of dicts with k (veh/km), q (veh/h), v (m/s).

    Free branch  q = vf * k            (through origin, fitted on uncongested pts)
    Cong. branch q = w * (kj - k)      (OLS on congested pts, w>0 in km/h)
    Capacity/critical density = intersection.
    """
    import numpy as np
    P = sorted(points, key=lambda p: p['k'])
    kk = np.array([p['k'] for p in P]); qq = np.array([p['q'] for p in P])
    vv = np.array([p['v'] for p in P])
    vf_kmh = v_free_hint * 3.6

    # free branch: points whose space-mean speed is within 3% of the observed max
    vmax = vv.max()
    free = vv >= 0.97 * vmax
    # never let "free" bleed past the flow peak
    kpeak = kk[int(np.argmax(qq))]
    free = free & (kk <= kpeak)
    if free.sum() >= 2:
        vf = float((kk[free] * qq[free]).sum() / (kk[free] ** 2).sum())   # OLS thru origin
    else:
        vf = float(qq[free].sum() / max(kk[free].sum(), 1e-9))

    cong = kk > kpeak
    if cong.sum() >= 2:
        A = np.vstack([kk[cong], np.ones(cong.sum())]).T
        slope, icept = np.linalg.lstsq(A, qq[cong], rcond=None)[0]
        w = -float(slope)                      # km/h, positive
        kj = float(-icept / slope)             # veh/km
        pred = A @ np.array([slope, icept])
        ss_res = float(((qq[cong] - pred) ** 2).sum())
        ss_tot = float(((qq[cong] - qq[cong].mean()) ** 2).sum())
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float('nan')
    else:
        w = kj = r2 = float('nan')

    if w == w and vf > 0:
        kc = w * kj / (vf + w)
        qmax = vf * kc
    else:
        kc = float(kk[int(np.argmax(qq))]); qmax = float(qq.max())

    return dict(v_free_kmh=vf, v_free_ms=vf / 3.6,
                w_kmh=w, w_ms=w / 3.6, k_jam=kj,
                k_crit=kc, q_max=qmax,
                q_max_observed=float(qq.max()),
                k_at_q_max_observed=float(kk[int(np.argmax(qq))]),
                cong_branch_r2=r2, n_free=int(free.sum()), n_cong=int(cong.sum()),
                vf_hint_kmh=vf_kmh)
