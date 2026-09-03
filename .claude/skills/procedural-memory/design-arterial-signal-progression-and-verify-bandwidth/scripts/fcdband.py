#!/usr/bin/env python3
"""Measurement layer (b): the band that ACTUALLY gets through, from FCD.

For each corridor-through vehicle (id prefix thruE / thruW) this reconstructs
the along-corridor trajectory from FCD x-coordinates and reports:

  * stop_count  - number of distinct standstill episodes (speed < STOP_V for at
                  least STOP_MIN s) strictly between the first and last signal
  * zero_stop   - stop_count == 0 over the whole coordinated corridor
  * t_ref       - the time the vehicle crossed the REFERENCE signal's stop line
                  (J0 for EB, J_{n-1} for WB); its phase, (t_ref mod C), is the
                  x-axis of the analytic band
  * cruise      - the vehicle's 85th-percentile speed while on the arterial,
                  used to calibrate the analytic progression speed

The MEASURED band is then the measure of the set of arrival phases that
actually get through unstopped, estimated as
    C * (number of 1 s phase bins whose zero-stop rate >= 0.5) / C
plus, separately, the raw zero-stop fraction of all corridor-through vehicles.
Both are reported; they answer slightly different questions (how wide is the
usable window vs. how much of the random arrival stream benefits).
"""
import xml.etree.ElementTree as ET
from collections import defaultdict

STOP_V = 0.3          # m/s -- treated as standing
STOP_MIN = 1.0        # s   -- minimum standstill duration to count as a stop


def load(fcd, prefixes=("thruE", "thruW")):
    """vid -> list of (t, x, v), time-sorted."""
    tr = defaultdict(list)
    for _, el in ET.iterparse(fcd, events=("end",)):
        if el.tag != "timestep":
            continue
        t = float(el.get("time"))
        for veh in el:
            vid = veh.get("id")
            if any(vid.startswith(p) for p in prefixes):
                tr[vid].append((t, float(veh.get("x")), float(veh.get("speed"))))
        el.clear()
    for v in tr.values():
        v.sort()
    return tr


def _cross_time(pts, x0, rising):
    """First time the trajectory crosses x0 (linear interp)."""
    for (t1, a, _), (t2, b, _) in zip(pts, pts[1:]):
        if rising and a <= x0 < b:
            return t1 + (t2 - t1) * (x0 - a) / (b - a)
        if (not rising) and a >= x0 > b:
            return t1 + (t2 - t1) * (a - x0) / (a - b)
    return None


def analyse(fcd, xs, C, t0=600.0, t1=1e9, prefixes=("thruE", "thruW")):
    tr = load(fcd, prefixes)
    x_first, x_last = xs[0], xs[-1]
    out = {"EB": [], "WB": []}
    for vid, pts in tr.items():
        d = "EB" if vid.startswith("thruE") else "WB"
        xa, xb = (x_first, x_last) if d == "EB" else (x_last, x_first)
        t_ref = _cross_time(pts, xa, d == "EB")
        t_end = _cross_time(pts, xb, d == "EB")
        if t_ref is None or t_end is None or not (t0 <= t_ref < t1):
            continue
        seg = [(t, x, v) for t, x, v in pts
               if min(xa, xb) - 1 <= x <= max(xa, xb) + 1 and t_ref <= t <= t_end]
        if len(seg) < 5:
            continue
        # standstill episodes strictly inside the coordinated corridor
        stops, run = 0, 0.0
        prev_t = seg[0][0]
        for t, x, v in seg:
            dt = t - prev_t
            prev_t = t
            if v < STOP_V:
                run += dt
            else:
                if run >= STOP_MIN:
                    stops += 1
                run = 0.0
        if run >= STOP_MIN:
            stops += 1
        sp = sorted(v for _, _, v in seg)
        p85 = sp[int(0.85 * (len(sp) - 1))]
        out[d].append(dict(id=vid, t_ref=t_ref, phase=t_ref % C, stops=stops,
                           zero=1 if stops == 0 else 0, tt=t_end - t_ref,
                           cruise=p85))
    return out


def band_stats(recs, C, bin_s=1.0, thresh=0.5, minn=3):
    """(zero-stop fraction, measured band width, per-bin table)."""
    if not recs:
        return dict(n=0, zero_frac=float("nan"), band_meas=float("nan"),
                    tt=float("nan"), cruise=float("nan"), bins=[])
    nb = int(round(C / bin_s))
    tot = [0] * nb
    zer = [0] * nb
    for r in recs:
        k = int(r["phase"] / bin_s) % nb
        tot[k] += 1
        zer[k] += r["zero"]
    good = sum(1 for k in range(nb)
               if tot[k] >= minn and zer[k] / float(tot[k]) >= thresh)
    cov = sum(1 for k in range(nb) if tot[k] >= minn)
    band = C * good / float(nb)
    band_cov = (C * good / float(cov)) if cov else float("nan")
    sp = sorted(r["cruise"] for r in recs)
    return dict(n=len(recs),
                zero_frac=sum(r["zero"] for r in recs) / float(len(recs)),
                band_meas=band, band_meas_coverage_adj=band_cov,
                bins_covered=cov, bins_total=nb,
                tt=sum(r["tt"] for r in recs) / len(recs),
                stops=sum(r["stops"] for r in recs) / float(len(recs)),
                cruise=sp[len(sp) // 2],
                bins=[(k * bin_s, tot[k], zer[k]) for k in range(nb)])
