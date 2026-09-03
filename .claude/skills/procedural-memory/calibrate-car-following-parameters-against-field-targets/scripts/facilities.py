#!/usr/bin/env python3
"""The two VALIDATION facilities + the microscopic probe.

fwy_fd()   : open-road 3-lane freeway demand sweep, E1 station upstream of the
             merge/lane-drop, per-lane flow/density/space-mean-speed exactly per
             `build-macroscopic-fundamental-diagram` (harmonic mean speed;
             density per lane BEFORE summing; two independent density
             estimators cross-checked).
sat_flow() : held-out signalised approach; discharge headway vs queue position
             from an instantInductionLoop at the stop line, rear-bumper
             (state="leave") convention, per
             `measure-saturation-flow-and-validate-webster-method`.
micro()    : microscopic signature of a parameter vector on the ring at a fixed
             near-capacity density -- time-headway distribution, speed
             oscillation amplitude, and perturbation (string-stability) growth.
             Used for the H3 equifinality test.
"""
import os, sys, math, json, shutil
import xml.etree.ElementTree as ET
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cf_common import (SUMO, run_sumo, read_summary, vtype_xml, RUNS, FWY_NET,
                       SIG_NET, RING_NET, RING_L, RING_LANES, RING_N_EDGES,
                       FREE_SPEED, SIG_SPEED, _write_ring_routes, SF_WARN)

# ==========================================================================
#  FREEWAY
# ==========================================================================
FWY_STATION = 2000.0          # pos on edge 'main'
FWY_LANES = 3


def _parse_e1(path, t0, t1):
    """Per-lane aggregation over [t0,t1). Returns list of per-lane dicts."""
    per = {}
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag != "interval":
            el.clear(); continue
        b = float(el.get("begin")); e = float(el.get("end"))
        if b < t0 or e > t1 + 1e-6:
            el.clear(); continue
        d = per.setdefault(el.get("id"), dict(n=0.0, dur=0.0, occ=0.0,
                                              inv=0.0, ln=0.0, nl=0))
        n = float(el.get("nVehContrib"))
        hs = float(el.get("harmonicMeanSpeed"))
        d["n"] += n
        d["dur"] += (e - b)
        d["occ"] += float(el.get("occupancy")) * (e - b)
        if n > 0 and hs > 0:
            d["inv"] += n / hs               # sum n_i / v_i  -> harmonic mean
        ln = float(el.get("length"))
        if n > 0 and ln > 0:
            d["ln"] += ln * n; d["nl"] += n
        el.clear()
    out = []
    for lid, d in sorted(per.items()):
        q = d["n"] / d["dur"] * 3600.0 if d["dur"] > 0 else 0.0
        v = d["n"] / d["inv"] if d["inv"] > 0 else float("nan")     # m/s, space-mean
        occ = d["occ"] / d["dur"] if d["dur"] > 0 else 0.0
        meanlen = d["ln"] / d["nl"] if d["nl"] > 0 else float("nan")
        k_qv = q / (v * 3.6) if v == v and v > 0 else float("nan")
        k_occ = 10.0 * occ / meanlen if meanlen == meanlen and meanlen > 0 else float("nan")
        out.append(dict(lane=lid, q=q, v_ms=v, v_kmh=v * 3.6 if v == v else float("nan"),
                        occ=occ, k_qv=k_qv, k_occ=k_occ, n=d["n"]))
    return out


def fwy_run(wd, model, p, mainline_vph, ramp_vph=500.0, seed=42,
            end=3600.0, warmup=1800.0, ttt=300, net=None, n_out_lanes=3):
    os.makedirs(wd, exist_ok=True)
    net = net or FWY_NET
    vt = vtype_xml("car", model, p)
    rou = os.path.join(wd, "f.rou.xml")
    with open(rou, "w") as f:
        f.write("<routes>\n  %s\n" % vt)
        f.write('  <route id="main" edges="in main merge out"/>\n')
        f.write('  <route id="ramp" edges="ramp merge out"/>\n')
        f.write('  <flow id="fm" route="main" type="car" begin="0" end="%g" '
                'vehsPerHour="%g" departLane="best" departSpeed="max"/>\n'
                % (end, mainline_vph))
        if ramp_vph > 0:
            f.write('  <flow id="fr" route="ramp" type="car" begin="0" end="%g" '
                    'vehsPerHour="%g" departLane="free" departSpeed="max"/>\n'
                    % (end, ramp_vph))
        f.write("</routes>\n")
    add = os.path.join(wd, "det.add.xml")
    with open(add, "w") as f:
        f.write("<additional>\n")
        for l in range(FWY_LANES):
            f.write('  <inductionLoop id="st_%d" lane="main_%d" pos="%g" '
                    'period="60" file="e1.xml"/>\n' % (l, l, FWY_STATION))
        for l in range(n_out_lanes):
            f.write('  <inductionLoop id="dn_%d" lane="out_%d" pos="800" period="60" '
                    'file="e1d.xml"/>\n' % (l, l))
        f.write("</additional>\n")
    smy = os.path.join(wd, "s.xml")
    r = run_sumo(["-n", net, "-r", rou, "-a", add, "--summary-output", smy,
                  "--begin", "0", "--end", str(end), "--step-length", "0.5",
                  "--no-step-log", "true", "--xml-validation", "never",
                  "--time-to-teleport", str(ttt), "--collision.action", "warn",
                  "--max-depart-delay", "120",
                  "--step-method.ballistic", "true", "--default.speeddev", "0",
                  "--seed", str(seed)], cwd=wd)
    if r.returncode != 0:
        return dict(ok=False, err=r.stderr[-500:])
    if SF_WARN in r.stderr:
        return dict(ok=False, err="speedFactor silently rewritten")
    lanes = _parse_e1(os.path.join(wd, "e1.xml"), warmup, end)
    dn = _parse_e1(os.path.join(wd, "e1d.xml"), warmup, end)
    rows = read_summary(smy)
    last = rows[-1]
    q = sum(l["q"] for l in lanes)
    n = sum(l["n"] for l in lanes)
    inv = sum(l["n"] / l["v_ms"] for l in lanes if l["v_ms"] == l["v_ms"] and l["v_ms"] > 0)
    v = n / inv if inv > 0 else float("nan")
    k_qv = sum(l["k_qv"] for l in lanes if l["k_qv"] == l["k_qv"])
    k_occ = sum(l["k_occ"] for l in lanes if l["k_occ"] == l["k_occ"])
    return dict(ok=True, demand=mainline_vph, ramp=ramp_vph,
                q_station=q, q_per_lane=q / FWY_LANES,
                v_kmh=v * 3.6 if v == v else float("nan"),
                k_qv=k_qv, k_occ=k_occ,
                k_qv_per_lane=k_qv / FWY_LANES, k_occ_per_lane=k_occ / FWY_LANES,
                q_downstream=sum(l["q"] for l in dn),
                q_downstream_per_lane=sum(l["q"] for l in dn) / max(len(dn), 1),
                n_out_lanes=len(dn),
                lanes=lanes,
                teleports=last["teleports"], collisions=last["collisions"],
                inserted=last["inserted"], loaded=last["loaded"],
                arrived=last["arrived"], running_end=last["running"])


FWY_DEMANDS = [1500, 2500, 3500, 4200, 4800, 5200, 5600, 6000, 6500, 7500, 9000]


def fwy_sweep(tag, model, p, seed=42, demands=None, ramp_vph=500.0, keep=False):
    demands = demands or FWY_DEMANDS
    root = os.path.join(RUNS, "fwy", tag)
    pts = []
    for d in demands:
        pts.append(fwy_run(os.path.join(root, "d%d" % d), model, p, d,
                           ramp_vph=ramp_vph, seed=seed))
    if not keep:
        shutil.rmtree(root, ignore_errors=True)
    return pts


def fwy_features(pts):
    """FD features from the freeway sweep, per lane."""
    g = [x for x in pts if x.get("ok")]
    if len(g) < 4:
        return None
    q = np.array([x["q_per_lane"] for x in g])
    k = np.array([x["k_occ_per_lane"] for x in g])
    v = np.array([x["v_kmh"] for x in g])
    free = v > 70.0                       # regime from MEASURED speed, not demand
    i_pk = int(np.argmax(q))
    vf = float((k[free][:3] * q[free][:3]).sum() / (k[free][:3] ** 2).sum()) if free.sum() >= 3 else float(v[0])
    cong = (~free) & (k > k[i_pk])
    if cong.sum() >= 2:
        A = np.vstack([k[cong], np.ones(int(cong.sum()))]).T
        sl, ic = np.linalg.lstsq(A, q[cong], rcond=None)[0]
        w = -float(sl); kj = float(-ic / sl) if sl < 0 else float("nan")
    else:
        w = kj = float("nan")
    disc = float(np.mean([x["q_downstream_per_lane"] for x in g if x["v_kmh"] < 60]))\
        if any(x["v_kmh"] < 60 for x in g) else float("nan")
    return dict(v_free_kmh=vf, q_max=float(q[i_pk]), k_crit=float(k[i_pk]),
                k_jam=kj, w_kmh=w, q_discharge_per_lane=disc,
                n_free=int(free.sum()), n_cong=int(cong.sum()),
                teleports_total=float(sum(x["teleports"] for x in g)),
                collisions_total=float(sum(x["collisions"] for x in g)))


# ==========================================================================
#  SIGNALISED APPROACH (held out)
# ==========================================================================
SIG_THROUGH = {"NS": 1, "SN": 7, "EW": 4, "WE": 10}   # verified from compiled net
SIG_NLINK = 12
SIG_YELLOW = 4.0


def _sig_state(gidx, ch="G"):
    s = ["r"] * SIG_NLINK
    for i in gidx:
        s[i] = ch
    return "".join(s)


def sat_flow(wd, model, p, g_ns=32.0, g_ew=30.0, seed=42, end=2400.0,
             warmup=300.0, demand=4000.0, n_lo=4, n_hi=14):
    """Measure saturation headway/flow at the stop line of in_N_0."""
    os.makedirs(wd, exist_ok=True)
    vt = vtype_xml("car", model, p, maxspeed=55.55)
    rou = os.path.join(wd, "s.rou.xml")
    routes = {"NS": "in_N out_S", "SN": "in_S out_N",
              "EW": "in_E out_W", "WE": "in_W out_E"}
    with open(rou, "w") as f:
        f.write("<routes>\n  %s\n" % vt)
        for rid, e in routes.items():
            f.write('  <route id="r_%s" edges="%s"/>\n' % (rid, e))
        for rid in routes:
            f.write('  <flow id="f_%s" route="r_%s" type="car" begin="0" end="%g" '
                    'vehsPerHour="%g" departLane="0" departSpeed="max" '
                    'departPos="base"/>\n' % (rid, rid, end, demand))
        f.write("</routes>\n")
    add = os.path.join(wd, "d.add.xml")
    with open(add, "w") as f:
        f.write('<additional>\n')
        f.write('  <instantInductionLoop id="inst_N" lane="in_N_0" pos="-0.1" '
                'friendlyPos="true" file="inst.xml"/>\n')
        f.write('  <laneAreaDetector id="e2_N" lane="in_N_0" pos="0" endPos="392.0" '
                'friendlyPos="true" period="%g" file="e2.xml"/>\n'
                % (g_ns + g_ew + 2 * SIG_YELLOW))
        f.write('</additional>\n')
    tls = os.path.join(wd, "t.add.xml")
    ns, ew = (SIG_THROUGH["NS"], SIG_THROUGH["SN"]), (SIG_THROUGH["EW"], SIG_THROUGH["WE"])
    with open(tls, "w") as f:
        f.write('<additional>\n  <tlLogic id="C" type="static" programID="sat" offset="0">\n')
        for d, st in ((g_ns, _sig_state(ns)), (SIG_YELLOW, _sig_state(ns, "y")),
                      (g_ew, _sig_state(ew)), (SIG_YELLOW, _sig_state(ew, "y"))):
            f.write('    <phase duration="%g" state="%s"/>\n' % (d, st))
        f.write('  </tlLogic>\n</additional>\n')
    r = run_sumo(["-n", SIG_NET, "-r", rou, "-a", "%s,%s" % (add, tls),
                  "--begin", "0", "--end", str(end), "--step-length", "0.1",
                  "--no-step-log", "true", "--xml-validation", "never",
                  "--time-to-teleport", "-1", "--max-depart-delay", "60",
                  "--collision.action", "warn", "--seed", str(seed)], cwd=wd)
    if r.returncode != 0:
        return dict(ok=False, err=r.stderr[-400:])
    if SF_WARN in r.stderr:
        return dict(ok=False, err="speedFactor silently rewritten")
    # rear-bumper crossings
    leaves = []
    for _, el in ET.iterparse(os.path.join(wd, "inst.xml"), events=("end",)):
        if el.tag == "instantOut" and el.get("state") == "leave":
            leaves.append(float(el.get("time")))
        el.clear()
    leaves.sort()
    C = g_ns + g_ew + 2 * SIG_YELLOW
    onsets = [t for t in np.arange(0.0, end, C) if t >= warmup]
    by_pos = {}
    ncyc = 0
    for t0 in onsets:
        veh = [t for t in leaves if t0 <= t < t0 + g_ns + SIG_YELLOW]
        if len(veh) < n_hi + 1:
            continue
        ncyc += 1
        prev = t0
        for i, t in enumerate(veh, start=1):
            by_pos.setdefault(i, []).append(t - prev)
            prev = t
    if ncyc < 5:
        return dict(ok=False, err="only %d saturated cycles" % ncyc)
    hn = {i: float(np.mean(v)) for i, v in sorted(by_pos.items()) if len(v) >= max(3, ncyc // 2)}
    win = [hn[i] for i in range(n_lo, n_hi + 1) if i in hn]
    if len(win) < 4:
        return dict(ok=False, err="short window")
    h_s = float(np.mean(win))
    l1 = float(sum(hn[i] - h_s for i in range(1, n_lo) if i in hn))
    # window sensitivity
    alts = {}
    for lo, hi in ((3, 12), (5, 15), (4, 10)):
        wv = [hn[i] for i in range(lo, hi + 1) if i in hn]
        if len(wv) >= 4:
            alts["%d-%d" % (lo, hi)] = float(np.mean(wv))
    return dict(ok=True, h_sat=h_s, s_vph=3600.0 / h_s, l1=l1, n_cycles=ncyc,
                headway_by_pos={str(k): round(v, 4) for k, v in hn.items()},
                window_sensitivity={k: round(v, 4) for k, v in alts.items()},
                h_sat_spread=float(max(alts.values()) - min(alts.values())) if alts else 0.0)


# ==========================================================================
#  MICROSCOPIC PROBE (H3)
# ==========================================================================
def micro(wd, model, p, k_per_lane=22, seed=42, end=600.0, warmup=240.0):
    """Microscopic signature at one near-capacity density on the ring."""
    os.makedirs(wd, exist_ok=True)
    n_veh = int(round(k_per_lane * RING_L * RING_LANES / 1000.0))
    vt = vtype_xml("car", model, p)
    rou = os.path.join(wd, "m.rou.xml")
    laps = max(8, int(math.ceil(end * FREE_SPEED * 1.3 / RING_L)) + 2)
    v_cap = 0.95 * FREE_SPEED * max(0.25, p["speedFactor"] - 3.0 * p["speedDev"])
    _write_ring_routes(rou, n_veh, vt, "car", laps, 0.6, perturb=True,
                       tau=p["tau"], length=p["length"], mingap=p["minGap"],
                       v_dep_cap=v_cap)
    add = os.path.join(wd, "m.add.xml")
    with open(add, "w") as f:
        f.write('<additional>\n')
        for l in range(RING_LANES):
            f.write('  <instantInductionLoop id="il_%d" lane="e4_%d" pos="30" '
                    'file="inst.xml"/>\n' % (l, l))
        f.write('</additional>\n')
    fcd = os.path.join(wd, "fcd.xml")
    smy = os.path.join(wd, "s.xml")
    r = run_sumo(["-n", RING_NET, "-r", rou, "-a", add, "--summary-output", smy,
                  "--fcd-output", fcd, "--device.fcd.period", "1",
                  "--step-length", "0.5", "--begin", "0", "--end", str(end),
                  "--no-step-log", "true", "--xml-validation", "never",
                  "--time-to-teleport", "-1", "--collision.action", "warn",
                  "--step-method.ballistic", "true", "--default.speeddev", "0",
                  "--seed", str(seed)], cwd=wd)
    if r.returncode != 0:
        return dict(ok=False, err=r.stderr[-400:])
    if SF_WARN in r.stderr:
        return dict(ok=False, err="speedFactor silently rewritten")
    # --- time headways at the loop (front-bumper 'enter' = time headway) ---
    ent = {0: [], 1: []}
    for _, el in ET.iterparse(os.path.join(wd, "inst.xml"), events=("end",)):
        if el.tag == "instantOut" and el.get("state") == "enter":
            t = float(el.get("time"))
            if t >= warmup:
                ent[0 if el.get("id").endswith("_0") else 1].append(t)
        el.clear()
    H = []
    for l in ent:
        a = sorted(ent[l])
        H += [a[i + 1] - a[i] for i in range(len(a) - 1)]
    H = np.array(H) if H else np.array([float("nan")])
    # --- speed oscillation from FCD ---
    per_veh, times = {}, []
    for _, el in ET.iterparse(fcd, events=("end",)):
        if el.tag == "timestep":
            t = float(el.get("time"))
            if t >= warmup:
                times.append(t)
                for v in el.iter("vehicle"):
                    per_veh.setdefault(v.get("id"), []).append(float(v.get("speed")))
            el.clear()
    sds = [float(np.std(s)) for s in per_veh.values() if len(s) > 10]
    rows = [x for x in read_summary(smy) if x["time"] >= warmup]
    ms = np.array([x["meanSpeed"] for x in rows])
    # --- perturbation growth (string stability): how far the transient from the
    # one-shot brake pulse persists, measured on the pre-warmup window
    pre = [x for x in read_summary(smy) if 20.0 <= x["time"] < warmup]
    pv = np.array([x["meanSpeed"] for x in pre]) if pre else np.array([float("nan")])
    return dict(ok=True, n_veh=n_veh, k=k_per_lane,
                headway_mean=float(np.nanmean(H)), headway_sd=float(np.nanstd(H)),
                headway_cv=float(np.nanstd(H) / np.nanmean(H)) if np.nanmean(H) > 0 else float("nan"),
                headway_p15=float(np.nanpercentile(H, 15)),
                headway_p50=float(np.nanpercentile(H, 50)),
                headway_p85=float(np.nanpercentile(H, 85)),
                headway_n=int(len(H)),
                veh_speed_sd_mean=float(np.mean(sds)) if sds else float("nan"),
                stream_speed_sd=float(np.std(ms)),
                stream_speed_mean=float(np.mean(ms)),
                osc_amplitude=float(np.max(ms) - np.min(ms)) if len(ms) else float("nan"),
                transient_range=float(np.max(pv) - np.min(pv)) if len(pv) > 1 else float("nan"),
                teleports=rows[-1]["teleports"], collisions=rows[-1]["collisions"],
                headways=[round(float(x), 3) for x in H[:4000]])


# ---------------------------------------------------------- parallel sweep ---
def _fwy_job(a):
    tag, model, p, d, ramp, seed, net = a
    nol = 2 if (net and "drop" in net) else 3
    return d, fwy_run(os.path.join(RUNS, "fwy", tag, "d%d_r%d_s%d" % (d, ramp, seed)),
                      model, p, d, ramp_vph=ramp, seed=seed, net=net,
                      n_out_lanes=nol)


FWY_DEMANDS3 = [1500, 2700, 3900, 4800, 5400, 5800, 6100, 6400, 6800, 7500, 9000]


def fwy_sweep_par(tag, model, p, seed=42, demands=None, ramp_vph=500.0,
                  nproc=9, keep=False):
    from concurrent.futures import ProcessPoolExecutor
    demands = demands or FWY_DEMANDS3
    jobs = [(tag, model, p, d, ramp_vph, seed, None) for d in demands]
    with ProcessPoolExecutor(max_workers=nproc) as ex:
        out = list(ex.map(_fwy_job, jobs))
    pts = [r for _, r in sorted(out, key=lambda x: x[0])]
    if not keep:
        shutil.rmtree(os.path.join(RUNS, "fwy", tag), ignore_errors=True)
    return pts
