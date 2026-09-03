#!/usr/bin/env python3
"""STEP 2 & 3 -- empirically measure saturation flow rate s and startup lost
time l1 at a signalised approach, for several car-following parameterisations.

Test bed
--------
Isolated 4-way signalised intersection (create-single-intersection skill),
1 through lane per approach, 300 m arms, 13.89 m/s.  Only the four THROUGH
movements ever get green or demand -> no turning-conflict confounds.
All four approaches are loaded at 3600 veh/h/lane, i.e. far above capacity, so
every approach carries a permanently spilled-back standing queue and every
green interval is fully saturated from the first second.

TWO INDEPENDENT ESTIMATORS
--------------------------
(A) Headway-vs-queue-position.  An <instantInductionLoop> at the stop line of
    in_N_0 gives per-vehicle crossing timestamps.  Discharge headways are taken
    from the REAR-BUMPER crossing (state="leave"), the standard field
    convention and the only one that is well defined when vehicle 1 already
    stands ON the stop line:
        h_1 = t_leave(1) - t_greenOnset ,  h_n = t_leave(n) - t_leave(n-1)
    h_s = mean h_n over the saturated window n in [N_LO, N_HI];
    s = 3600/h_s ;  l1 = sum_{n < N_LO} (h_n - h_s).
    Window sensitivity is reported because SUMO's headways do NOT flatten to a
    perfect asymptote (see FINDINGS.md).

(B) Green-duration regression (window-free, HCM "saturation flow from
    discharge counts").  The SAME oversaturated scenario is re-run with green
    durations g in GREENS.  The number of vehicles N_d discharged per cycle is
    linear in g:   N_d(g) = (s/3600)*(g - l1 + e)
    where e = mean discharge extension past the end of green (into yellow).
    OLS of N_d on g gives s = 3600*slope directly, and
    l1 = e - intercept/slope.  This estimator needs no choice of which queue
    positions count as "saturated", so it is the primary reported value.

Outputs work/saturation_results.json.
"""
import os
import sys
import json
import xml.etree.ElementTree as ET
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (WORK, NET, VTYPES, vtype_xml, ROUTES, tls_xml, YELLOW,
                    ALLRED, STEP_LENGTH, run_sumo, SPEED_LIMIT)

GREENS = [16.0, 24.0, 32.0, 40.0]   # NS green durations used for the regression
G_HEADWAY = 32.0                    # the run used for the headway-vs-n table
G_EW = 30.0                         # opposing phase green, held fixed
T_END = 4400.0
WARMUP = 400.0                      # discard cycles before the queue is spilled back
DEMAND = 4000.0                     # veh/h/lane, >> capacity
N_LO, N_HI = 4, 15                  # saturated queue-position window (HCM-style)
SEED = 42

MEAS = os.path.join(WORK, "measure")
os.makedirs(MEAS, exist_ok=True)


# ---------------------------------------------------------------- inputs ---
def write_inputs(vt_name, g_ns):
    tag = "%s_g%g" % (vt_name, g_ns)
    outdir = os.path.join(MEAS, tag)
    os.makedirs(outdir, exist_ok=True)

    rou = os.path.join(outdir, "sat.rou.xml")
    with open(rou, "w") as f:
        f.write('<routes>\n')
        f.write(vtype_xml(vt_name, VTYPES[vt_name]))
        for rid, edges in ROUTES.items():
            f.write('    <route id="r_%s" edges="%s"/>\n' % (rid, edges))
        for rid in ROUTES:
            f.write('    <flow id="f_%s" route="r_%s" type="%s" begin="0" end="%g" '
                    'vehsPerHour="%g" departLane="0" departSpeed="max" '
                    'departPos="base"/>\n' % (rid, rid, vt_name, T_END, DEMAND))
        f.write('</routes>\n')

    # SUMO gotcha: detector `file` paths resolve relative to the additional
    # file's directory, so this must live in the per-run output directory.
    add = os.path.join(outdir, "detectors.add.xml")
    with open(add, "w") as f:
        f.write('<additional>\n')
        for app in ("N", "S", "E", "W"):
            f.write('    <e1Detector id="e1_%s" lane="in_%s_0" pos="-0.1" '
                    'friendlyPos="true" period="60" file="e1_flow.xml"/>\n' % (app, app))
        f.write('    <instantInductionLoop id="inst_N" lane="in_N_0" pos="-0.1" '
                'friendlyPos="true" file="instant_N.xml"/>\n')
        # full-lane queue detector: verifies the standing queue never runs out.
        # length must be clipped to the lane's own length (endPos), not left
        # oversized -- an oversized laneAreaDetector silently continues onto
        # upstream lanes and measures traffic that isn't on this approach.
        f.write('    <laneAreaDetector id="e2_N" lane="in_N_0" pos="0" '
                'endPos="292.80" friendlyPos="true" period="%g" '
                'file="e2_queue.xml"/>\n' % (g_ns + YELLOW + G_EW + YELLOW))
        f.write('</additional>\n')

    tls = os.path.join(outdir, "tls.add.xml")
    with open(tls, "w") as f:
        f.write(tls_xml(g_ns, G_EW, program="satmeas"))
    return outdir, rou, add, tls


def run(vt_name, g_ns):
    outdir, rou, add, tls = write_inputs(vt_name, g_ns)
    args = [
        "-n", NET, "-r", rou, "-a", "%s,%s" % (add, tls),
        "--begin", "0", "--end", str(T_END),
        "--step-length", str(STEP_LENGTH),
        "--seed", str(SEED),
        "--time-to-teleport", "-1",
        "--no-step-log", "true",
        "--xml-validation", "never",
        # discard vehicles that cannot be inserted within 60 s: the approach is
        # already spilled back, so keeping a huge unserved insertion backlog only
        # slows the run down without changing the queue at the stop line.
        "--max-depart-delay", "60",
    ]
    cwd = os.getcwd()
    os.chdir(outdir)
    try:
        run_sumo(args, "sat-%s-g%g" % (vt_name, g_ns))
    finally:
        os.chdir(cwd)
    return outdir


# ---------------------------------------------------------------- parsing --
def parse_leave_times(path):
    """Rear-bumper stop-line crossing times, sorted."""
    ts = []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "instantOut" and el.get("state") == "leave":
            ts.append(float(el.get("time")))
            el.clear()
    ts.sort()
    return ts


def parse_enter_times(path):
    ts = []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "instantOut" and el.get("state") == "enter":
            ts.append(float(el.get("time")))
            el.clear()
    ts.sort()
    return ts


def cycle_windows(g_ns):
    C = g_ns + YELLOW + G_EW + YELLOW
    return [i * C for i in range(int(T_END // C) + 1) if WARMUP <= i * C < T_END - C], C


def per_cycle(times, g_ns):
    """-> list of (green_onset, [crossing times in green+yellow])"""
    onsets, C = cycle_windows(g_ns)
    out = []
    for t0 in onsets:
        win = [t for t in times if t0 <= t < t0 + g_ns + YELLOW + ALLRED]
        out.append((t0, win))
    return out, C


def parse_queue(path):
    """laneAreaDetector: (min, mean) of maxVehicleNumber over post-warmup intervals.
    Verifies that the standing queue never ran out during any measured cycle."""
    vals = []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "interval":
            if float(el.get("begin")) >= WARMUP:
                vals.append(float(el.get("maxVehicleNumber")))
            el.clear()
    return (min(vals), sum(vals) / len(vals)) if vals else (None, None)


def ols(xs, ys):
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    b = sxy / sxx
    a = my - b * mx
    ss_res = sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys))
    ss_tot = sum((y - my) ** 2 for y in ys)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return a, b, r2


# --------------------------------------------------------------- analysis --
def analyse_vtype(vt_name):
    res = {"vtype": vt_name, "params": VTYPES[vt_name], "runs": {}}

    # ---- run every green duration, collect discharge counts + extension e
    xs, ys, ext_all = [], [], []
    for g in GREENS:
        od = os.path.join(MEAS, "%s_g%g" % (vt_name, g))
        times = parse_leave_times(os.path.join(od, "instant_N.xml"))
        cyc, C = per_cycle(times, g)
        counts = [len(w) for _, w in cyc]
        # extension of discharge past the end of green, into yellow
        exts = [max(0.0, w[-1] - (t0 + g)) for t0, w in cyc if w]
        nd = sum(counts) / len(counts)
        e = sum(exts) / len(exts)
        xs.append(g)
        ys.append(nd)
        ext_all.extend(exts)
        qv = parse_queue(os.path.join(od, "e2_queue.xml"))
        res["runs"]["g%g" % g] = dict(cycle=C, cycles=len(cyc),
                                      veh_per_cycle=nd, ext_into_yellow=e,
                                      counts_min=min(counts), counts_max=max(counts),
                                      queue_maxVehicleNumber_min=qv[0],
                                      queue_maxVehicleNumber_mean=qv[1])
    a, b, r2 = ols(xs, ys)
    e_mean = sum(ext_all) / len(ext_all)
    s_reg = 3600.0 * b
    l1_reg = e_mean - a / b
    l2_reg = (YELLOW + ALLRED) - e_mean
    res["regression"] = dict(greens=xs, veh_per_cycle=ys, intercept=a, slope=b,
                             r2=r2, s=s_reg, h_s=3600.0 / s_reg,
                             e_into_yellow=e_mean, l1=l1_reg, l2=l2_reg,
                             L_per_phase=l1_reg + l2_reg)

    # ---- headway-vs-queue-position from the G_HEADWAY run
    od = os.path.join(MEAS, "%s_g%g" % (vt_name, G_HEADWAY))
    times = parse_leave_times(os.path.join(od, "instant_N.xml"))
    entr = parse_enter_times(os.path.join(od, "instant_N.xml"))
    cyc, C = per_cycle(times, G_HEADWAY)
    cyc_f, _ = per_cycle(entr, G_HEADWAY)

    per_n = defaultdict(list)
    for t0, win in cyc:
        prev = t0
        for n, t in enumerate(win, start=1):
            per_n[n].append(t - prev)
            prev = t
    per_nf = defaultdict(list)
    for t0, win in cyc_f:
        prev = None
        for n, t in enumerate(win, start=1):
            if prev is not None:
                per_nf[n].append(t - prev)
            prev = t

    ncyc = len(cyc)
    mean_h = {n: sum(v) / len(v) for n, v in per_n.items()}
    cnt_h = {n: len(v) for n, v in per_n.items()}
    win_ns = [n for n in range(N_LO, N_HI + 1)
              if n in per_n and cnt_h[n] >= 0.9 * ncyc]
    allh = [h for n in win_ns for h in per_n[n]]
    h_s = sum(allh) / len(allh)
    sd = (sum((x - h_s) ** 2 for x in allh) / (len(allh) - 1)) ** 0.5
    l1 = sum(mean_h[n] - h_s for n in range(1, N_LO))

    # sensitivity of h_s to the choice of window
    sens = {}
    for lo, hi in ((3, 10), (4, 10), (4, 15), (5, 12), (6, 15), (8, 15)):
        ns = [n for n in range(lo, hi + 1) if n in per_n and cnt_h[n] >= 0.9 * ncyc]
        if not ns:
            continue
        v = [h for n in ns for h in per_n[n]]
        hh = sum(v) / len(v)
        sens["n%d-%d" % (lo, hi)] = dict(h_s=hh, s=3600.0 / hh,
                                         l1=sum(mean_h[n] - hh for n in range(1, lo)))

    mean_hf = {n: sum(v) / len(v) for n, v in per_nf.items()}
    fw = [h for n in win_ns if n in per_nf for h in per_nf[n]]

    p = VTYPES[vt_name]
    res["headway"] = dict(
        green=G_HEADWAY, cycle=C, cycles_used=ncyc,
        mean_headway_by_n={int(n): round(mean_h[n], 4) for n in sorted(mean_h)},
        n_obs_by_n={int(n): cnt_h[n] for n in sorted(cnt_h)},
        mean_front_headway_by_n={int(n): round(mean_hf[n], 4) for n in sorted(mean_hf)},
        window=[N_LO, N_HI], h_s=h_s, h_s_sd=sd, h_s_nobs=len(allh),
        h_s_front_check=(sum(fw) / len(fw)) if fw else None,
        s=3600.0 / h_s, l1=l1, window_sensitivity=sens,
        equilibrium_h_at_speed_limit=p["tau"] + (p["length"] + p["minGap"]) / SPEED_LIMIT,
    )
    return res


def _job(a):
    run(a[0], a[1])
    return a


def main():
    from multiprocessing import Pool
    jobs = [(vt, g) for vt in VTYPES for g in GREENS]
    with Pool(6) as p:
        for a in p.imap_unordered(_job, jobs):
            print("  simulated %s g=%g" % a, flush=True)
    out = {}
    for vt in VTYPES:
        print("=== %s" % vt, flush=True)
        r = analyse_vtype(vt)
        out[vt] = r
        rg, hw = r["regression"], r["headway"]
        print("  REG : s=%7.1f veh/h/ln  h_s=%.3f  l1=%.2f  l2=%.2f  R2=%.5f"
              % (rg["s"], rg["h_s"], rg["l1"], rg["l2"], rg["r2"]), flush=True)
        print("  HDWY: s=%7.1f veh/h/ln  h_s=%.3f (sd %.3f, n=%d)  l1=%.2f  cycles=%d"
              % (hw["s"], hw["h_s"], hw["h_s_sd"], hw["h_s_nobs"], hw["l1"],
                 hw["cycles_used"]), flush=True)
    with open(os.path.join(WORK, "saturation_results.json"), "w") as f:
        json.dump(out, f, indent=2)
    print("written", os.path.join(WORK, "saturation_results.json"))


if __name__ == "__main__":
    main()
