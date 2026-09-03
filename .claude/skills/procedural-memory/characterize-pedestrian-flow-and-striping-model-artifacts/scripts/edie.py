#!/usr/bin/env python3
"""Edie-style space-time reconstruction of pedestrian flow/density/speed from SUMO FCD.

SUMO has no induction-loop equivalent for persons (E1/E2/E3 detectors are vehicle
detectors; <personinfo> only gives completed-trip aggregates).  So the pedestrian
fundamental diagram must be reconstructed from trajectories.

Edie (1963) generalised definitions over a space-time region A = [x1,x2] x [t1,t2]
with |A| = L*T:

    TTD = total travel distance of all agents inside A          [m]
    TTS = total travel time of all agents inside A              [s]
    q  = TTD / |A|      (persons/s)          -- flow
    k  = TTS / |A|      (persons/m)          -- linear density
    v  = TTD / TTS      (m/s)                -- space-mean speed  (== q/k exactly)

`v = TTD/TTS` is the space-mean (harmonic-in-time) speed, which is the correct
averaging -- an arithmetic mean over FCD samples would over-weight fast agents.
Areal density (persons/m^2) = k / W, and specific flow (persons/s/m) = q / W.

With FCD sampled every `dt` seconds, for each sample of person p at time t with
x(t) inside [x1,x2]:   TTS += dt,  TTD += speed(t)*dt.
This is an O(dt) approximation of the exact trajectory integral; it is unbiased and
the relative error is ~ v*dt / L  (<2% for dt=1 s, v=1.4 m/s, L=80 m).

The corridor runs along the x-axis, so the FCD `x` attribute is the longitudinal
coordinate and `y` is the lateral coordinate -- no edge/pos bookkeeping needed and
it works identically for forward and reverse walkers.
"""
import argparse
import json
import math
import xml.etree.ElementTree as ET


def parse_fcd(fcd, x1, x2, t1, t2, y_center=0.0):
    """Stream FCD, returning per-sample records inside the space-time region."""
    recs = []          # (t, pid, x, ylat, speed)
    allsamp = 0
    t_seen = set()
    dirs = {}          # pid -> +1/-1 inferred from motion
    last_x = {}
    # <person> carries no time attribute, so track the enclosing <timestep> via
    # start-events while streaming (keeps memory flat on multi-hundred-MB FCD files).
    ctx = ET.iterparse(fcd, events=("start", "end"))
    tnow = None
    for ev, el in ctx:
        if ev == "start" and el.tag == "timestep":
            tnow = float(el.get("time"))
        elif ev == "end" and el.tag == "person":
            allsamp += 1
            x = float(el.get("x")); y = float(el.get("y"))
            pid = el.get("id"); sp = float(el.get("speed"))
            if pid in last_x:
                dx = x - last_x[pid]
                if abs(dx) > 1e-6:
                    dirs[pid] = 1 if dx > 0 else -1
            last_x[pid] = x
            if x1 <= x <= x2 and t1 <= tnow <= t2:
                t_seen.add(tnow)
                recs.append((tnow, pid, x, y - y_center, sp))
            el.clear()
        elif ev == "end" and el.tag == "timestep":
            el.clear()
    return recs, allsamp, sorted(t_seen), dirs


def edie(recs, dt, L, T, width):
    tts = len(recs) * dt
    ttd = sum(r[4] for r in recs) * dt
    area = L * T
    q = ttd / area
    k = tts / area
    v = (ttd / tts) if tts > 0 else float("nan")
    return {
        "TTD_m": ttd, "TTS_s": tts, "area_m_s": area,
        "flow_p_s": q, "flow_p_s_per_m": q / width,
        "density_p_m": k, "density_p_m2": k / width,
        "speed_ms": v, "n_samples": len(recs),
    }


def lateral_stats(recs, dirs, width, nbins=32):
    """Lateral-position histograms by direction + a segregation index (H3)."""
    half = width / 2.0
    edges = [-half + i * width / nbins for i in range(nbins + 1)]
    hf = [0] * nbins
    hb = [0] * nbins
    for (t, pid, x, ylat, sp) in recs:
        d = dirs.get(pid, 1)
        b = int((ylat + half) / width * nbins)
        b = min(max(b, 0), nbins - 1)
        (hf if d > 0 else hb)[b] += 1
    nf, nb = sum(hf), sum(hb)
    # Segregation index = 1/2 * sum |p_f(b) - p_b(b)|   (total variation distance).
    # 0 = the two direction groups occupy the width identically (fully mixed),
    # 1 = they occupy disjoint lateral bands (perfect lane formation).
    if nf > 0 and nb > 0:
        seg = 0.5 * sum(abs(hf[i] / nf - hb[i] / nb) for i in range(nbins))
    else:
        seg = float("nan")
    def mean_sd(h):
        n = sum(h)
        if n == 0:
            return float("nan"), float("nan")
        cs = [(edges[i] + edges[i + 1]) / 2 for i in range(nbins)]
        m = sum(h[i] * cs[i] for i in range(nbins)) / n
        var = sum(h[i] * (cs[i] - m) ** 2 for i in range(nbins)) / n
        return m, math.sqrt(var)
    mf, sf = mean_sd(hf)
    mb, sb = mean_sd(hb)
    sep = abs(mf - mb) / ((sf + sb) / 2) if (sf == sf and sb == sb and (sf + sb) > 0) else float("nan")
    return {"bin_edges": edges, "hist_fwd": hf, "hist_bwd": hb,
            "n_fwd_samples": nf, "n_bwd_samples": nb,
            "segregation_index": seg,
            "mean_lat_fwd": mf, "mean_lat_bwd": mb,
            "sd_lat_fwd": sf, "sd_lat_bwd": sb,
            "separation_ratio": sep}


def measure(fcd, x1, x2, t1, t2, width, dt=1.0, y_center=0.0, lateral=False,
            traj_out=None, traj_stride=1):
    recs, allsamp, ts, dirs = parse_fcd(fcd, x1, x2, t1, t2, y_center)
    L = x2 - x1
    T = t2 - t1
    out = edie(recs, dt, L, T, width)
    out.update({"region_x": [x1, x2], "region_t": [t1, t2], "width_m": width,
                "dt": dt, "fcd_person_samples_total": allsamp,
                "n_persons_in_region": len(set(r[1] for r in recs))})
    if lateral:
        out["lateral"] = lateral_stats(recs, dirs, width)
    if traj_out:
        trj = {}
        for (t, pid, x, ylat, sp) in recs:
            trj.setdefault(pid, []).append([t, x])
        with open(traj_out, "w") as f:
            json.dump({k: v for i, (k, v) in enumerate(sorted(trj.items())) if i % traj_stride == 0}, f)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fcd", required=True)
    ap.add_argument("--x1", type=float, default=60.0)
    ap.add_argument("--x2", type=float, default=140.0)
    ap.add_argument("--t1", type=float, required=True)
    ap.add_argument("--t2", type=float, required=True)
    ap.add_argument("--width", type=float, required=True)
    ap.add_argument("--dt", type=float, default=1.0)
    ap.add_argument("--y-center", type=float, default=0.0)
    ap.add_argument("--lateral", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args()
    r = measure(a.fcd, a.x1, a.x2, a.t1, a.t2, a.width, a.dt, a.y_center, a.lateral)
    s = json.dumps(r, indent=2)
    print(s)
    if a.out:
        open(a.out, "w").write(s)
