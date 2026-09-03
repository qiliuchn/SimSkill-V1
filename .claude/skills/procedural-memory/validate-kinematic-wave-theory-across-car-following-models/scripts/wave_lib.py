#!/usr/bin/env python3
"""Open-road scenario construction + FCD wave-front extraction.

Wave-front extraction follows the technique established in the
`demonstrate-and-stabilize-phantom-traffic-jams` skill: do NOT eyeball a
time-space diagram -- extract discrete (time, position) markers of the front from
raw FCD and fit a line, reporting R^2.

Here the marker is per-VEHICLE rather than per-instant, which is sharper:
  stopping front  = the (t, x) at which each vehicle FIRST drops below v_thr
  start-up front  = the (t, x) at which each vehicle FIRST rises above v_thr again
The set of such points is exactly the shock trajectory, and OLS of x on t gives
the shock speed in m/s (negative = travelling upstream).
"""
import os, sys, subprocess, math, json
import xml.etree.ElementTree as ET
import numpy as np

sys.path.insert(0, os.path.join(os.environ['SUMO_HOME'], 'tools'))


# ------------------------------------------------------------------ networks ---
def build_straight(prefix, length_m, speed_ms, lanes=1, tls_at=None, tail_m=500.0):
    """A -> B (-> C).  If tls_at is given, B is a traffic light and the link is
    split into an approach of tls_at metres plus a tail."""
    os.makedirs(os.path.dirname(prefix) or '.', exist_ok=True)
    if tls_at is None:
        nodes = f'<nodes><node id="A" x="0" y="0" type="priority"/>' \
                f'<node id="B" x="{length_m}" y="0" type="priority"/></nodes>'
        edges = f'<edges><edge id="in" from="A" to="B" numLanes="{lanes}" ' \
                f'speed="{speed_ms}" priority="1"/></edges>'
    else:
        nodes = (f'<nodes><node id="A" x="0" y="0" type="priority"/>'
                 f'<node id="B" x="{tls_at}" y="0" type="traffic_light"/>'
                 f'<node id="C" x="{tls_at+tail_m}" y="0" type="priority"/></nodes>')
        edges = (f'<edges><edge id="in" from="A" to="B" numLanes="{lanes}" '
                 f'speed="{speed_ms}" priority="1"/>'
                 f'<edge id="out" from="B" to="C" numLanes="{lanes}" '
                 f'speed="{speed_ms}" priority="1"/></edges>')
    open(prefix + '.nod.xml', 'w').write(nodes)
    open(prefix + '.edg.xml', 'w').write(edges)
    cmd = ['netconvert', '-n', prefix + '.nod.xml', '-e', prefix + '.edg.xml',
           '-o', prefix + '.net.xml', '--no-internal-links', 'true',
           '--no-turnarounds', 'true', '--offset.disable-normalization', 'true']
    if tls_at is not None:
        cmd += ['--tls.default-type', 'static']
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr)
    return prefix + '.net.xml'


# --------------------------------------------------------------------- FCD ---
def read_fcd(path):
    """-> {vid: (t[], x[], v[])} sorted by t.  Accepts a plain or gzipped FCD file
    (the retained archives are gzipped; a bare .xml path resolves to .xml.gz)."""
    import gzip
    veh = {}
    t = None
    if not os.path.exists(path) and os.path.exists(path + '.gz'):
        path = path + '.gz'
    src = gzip.open(path, 'rb') if path.endswith('.gz') else path
    for _, el in ET.iterparse(src, events=('end',)):
        if el.tag == 'timestep':
            t = float(el.get('time'))
            for v in el:
                d = veh.setdefault(v.get('id'), ([], [], []))
                d[0].append(t)
                d[1].append(float(v.get('x')))
                d[2].append(float(v.get('speed')))
            el.clear()
    return {k: (np.array(a), np.array(b), np.array(c)) for k, (a, b, c) in veh.items()}


def first_below(t, x, v, thr, t0=None, t1=None, xmin=None, xmax=None):
    m = np.ones_like(t, dtype=bool)
    if t0 is not None: m &= t >= t0
    if t1 is not None: m &= t <= t1
    if xmin is not None: m &= x >= xmin
    if xmax is not None: m &= x <= xmax
    m &= v < thr
    idx = np.nonzero(m)[0]
    return (float(t[idx[0]]), float(x[idx[0]])) if idx.size else None


def first_above(t, x, v, thr, t0=None, t1=None, xmin=None, xmax=None):
    m = np.ones_like(t, dtype=bool)
    if t0 is not None: m &= t >= t0
    if t1 is not None: m &= t <= t1
    if xmin is not None: m &= x >= xmin
    if xmax is not None: m &= x <= xmax
    m &= v > thr
    idx = np.nonzero(m)[0]
    return (float(t[idx[0]]), float(x[idx[0]])) if idx.size else None


def fit_front(points, min_pts=4):
    """points: [(t, x), ...] -> OLS x = a + b t.  b is the shock speed in m/s."""
    if len(points) < min_pts:
        return dict(n=len(points), speed_ms=float('nan'), r2=float('nan'),
                    intercept=float('nan'), t_span=None, x_span=None)
    P = np.array(sorted(points))
    t, x = P[:, 0], P[:, 1]
    A = np.vstack([t, np.ones_like(t)]).T
    (b, a), *_ = np.linalg.lstsq(A, x, rcond=None)
    pred = A @ np.array([b, a])
    ss_tot = float(((x - x.mean()) ** 2).sum())
    r2 = 1 - float(((x - pred) ** 2).sum()) / ss_tot if ss_tot > 0 else float('nan')
    return dict(n=len(points), speed_ms=float(b), speed_kmh=float(b) * 3.6,
                r2=float(r2), intercept=float(a),
                t_span=[float(t.min()), float(t.max())],
                x_span=[float(x.min()), float(x.max())],
                points=[[float(u), float(w)] for u, w in P])


# ------------------------------------------------------- E1 detector reading ---
def read_e1(path):
    out = []
    for _, el in ET.iterparse(path, events=('end',)):
        if el.tag == 'interval':
            out.append({k: (float(v) if k != 'id' else v) for k, v in el.attrib.items()})
            el.clear()
    return out


def upstream_state(e1_rows, t0, t1):
    """Traffic state (q, space-mean v, k) at an E1 STATION over [t0, t1].

    A station is one loop PER LANE.  Flow must be SUMMED across lanes and density
    computed PER LANE before summing (cf. `build-macroscopic-fundamental-diagram`);
    pooling every lane's intervals into one n/duration ratio silently returns the
    per-lane MEAN flow instead of the station total.
    """
    rows = [r for r in e1_rows if t0 <= r['begin'] and r['end'] <= t1
            and r['nVehContrib'] > 0]
    if not rows:
        return None
    lanes = {}
    for r in rows:
        lanes.setdefault(r['id'], []).append(r)
    q_tot = k_tot = n_tot = 0.0
    per_lane = {}
    for lid, rs in lanes.items():
        n = sum(r['nVehContrib'] for r in rs)
        dur = sum(r['end'] - r['begin'] for r in rs)
        q = n / dur * 3600.0
        v = n / sum(r['nVehContrib'] / r['harmonicMeanSpeed'] for r in rs)
        q_tot += q
        k_tot += q / (v * 3.6)
        n_tot += n
        per_lane[lid] = dict(q_vehh=q, v_ms=v, k_vehkm=q / (v * 3.6), n=n)
    v_space = q_tot / (k_tot * 3.6) if k_tot > 0 else float('nan')
    return dict(q_vehh=q_tot, v_ms=v_space, k_vehkm=k_tot, n=n_tot,
                dur_s=sum(r['end'] - r['begin'] for r in lanes[list(lanes)[0]]),
                n_lanes=len(lanes), per_lane=per_lane)


def rankine_hugoniot(q1, k1, q2, k2):
    """Shock speed between states 1 and 2 (veh/h, veh/km) -> m/s."""
    if abs(k2 - k1) < 1e-9:
        return float('nan')
    return (q2 - q1) / (k2 - k1) / 3.6


# ------------------------------------------------- queue-back shock tracking ---
def by_timestep(veh):
    """{vid:(t,x,v)} -> {t: [(x, v, vid), ...] sorted by x descending}"""
    frames = {}
    for vid, (t, x, v) in veh.items():
        for i in range(len(t)):
            frames.setdefault(round(float(t[i]), 3), []).append((float(x[i]), float(v[i]), vid))
    for t in frames:
        frames[t].sort(key=lambda r: -r[0])
    return frames


def queue_chain(frame, x_anchor, v_thr, gap_max=30.0, anchor_tol=40.0):
    """From the vehicle nearest x_anchor, walk UPSTREAM while vehicles are slow
    (v<v_thr) and contiguous (spacing<=gap_max).  Returns the chain.

    Contiguity is what makes this robust: a stranded slow platoon further upstream
    (EIDM leaves these between signal cycles) is NOT part of the shock and must not
    be fitted together with it."""
    cand = [r for r in frame if r[0] <= x_anchor + 1.0]
    if not cand:
        return []
    head = None
    for r in cand:
        if r[1] < v_thr and r[0] >= x_anchor - anchor_tol:
            head = r
            break
        if r[0] < x_anchor - anchor_tol:
            break
    if head is None:
        return []
    chain = [head]
    i = cand.index(head)
    for r in cand[i + 1:]:
        if r[1] < v_thr and (chain[-1][0] - r[0]) <= gap_max:
            chain.append(r)
        else:
            break
    return chain


def track_queue_back(veh, x_anchor, t0, t1, v_thr, gap_max=30.0, frames=None):
    """-> (front points [(t, x_back)], per-time chain stats)"""
    frames = frames if frames is not None else by_timestep(veh)
    pts, stats = [], []
    for t in sorted(frames):
        if not (t0 <= t <= t1):
            continue
        ch = queue_chain(frames[t], x_anchor, v_thr, gap_max)
        if len(ch) < 2:
            continue
        x_front, x_back = ch[0][0], ch[-1][0]
        pts.append((t, x_back))
        kq = (1000.0 * (len(ch) - 1) / (x_front - x_back)) if x_front > x_back else float('nan')
        stats.append(dict(t=t, n=len(ch), x_front=x_front, x_back=x_back, k_queue=kq,
                          ids=[r[2] for r in ch]))
    return pts, stats
