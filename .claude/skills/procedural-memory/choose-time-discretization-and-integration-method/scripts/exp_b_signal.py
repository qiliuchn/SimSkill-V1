"""Testbed (b): signalized single-lane approach.

Measures per factorial cell:
  * saturation flow s (veh/h/lane) + startup lost time l1  (windowed headway-position
    estimator, primary per `measure-saturation-flow-and-validate-webster-method`)
  * mean delay (timeLoss) / trip duration
  * HBEFA CO2 + fuel per vehicle
  * teleports, collisions, completed vs still-running vs not-inserted
  * queue-never-exhausted verification via laneAreaDetector

Plus a DETERMINISTIC single-vehicle STOP-LINE PROBE (sigma=0, one vehicle, red light)
that measures the front-bumper resting position relative to the stop line -> the direct
Euler-vs-ballistic positional-accuracy test (Q3).
"""
import os
import sys
import json
import math
import shutil
import xml.etree.ElementTree as ET
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dtcommon import (NET, RUNS, TAB, SEEDS, cells, cell_id, cell_args, asl_value,
                      run_sumo, BASE_ARGS, read_tripinfo, summary_totals, read_instant,
                      vtype_xml, DEFAULT_CAR, mean, sd, ci95, savejson)

APPR_NET = os.path.join(NET, "appr.net.xml")
STOPLINE_X = 600.0
LANE_LEN = 600.0
APPR_V = 13.89
CYCLE, GREEN, YEL = 60.0, 30.0, 4.0
END = 960.0
WARM_CYCLES = 3          # discard first 3 cycles (queue building)
DEMAND_VPH = 1400.0
BASE = os.path.join(RUNS, "b_signal")
os.makedirs(BASE, exist_ok=True)

TLS_XML = """<additional>
  <tlLogic id="a1" type="static" programID="sat" offset="0">
    <phase duration="%g" state="G"/>
    <phase duration="%g" state="y"/>
    <phase duration="%g" state="r"/>
  </tlLogic>
</additional>""" % (GREEN, YEL, CYCLE - GREEN - YEL)


def write_demand(path, seed=7):
    """CRN demand: identical vehicle list (ids, depart times) for EVERY cell."""
    import random
    rng = random.Random(seed)
    hdw = 3600.0 / DEMAND_VPH
    t, i, lines = 0.0, 0, []
    while t < END - 60.0:
        lines.append('  <vehicle id="v%d" type="car" depart="%.2f" departSpeed="max" '
                     'departPos="base" departLane="0"><route edges="ein eout"/></vehicle>' % (i, t))
        i += 1
        t += hdw * rng.uniform(0.6, 1.4)    # mild randomness, but FIXED across cells
    open(path, "w").write('<routes>\n' + "\n".join(lines) + "\n</routes>")
    return i


DEMAND = os.path.join(BASE, "demand.rou.xml")
NVEH = write_demand(DEMAND)


def add_xml(d, asl):
    """per-run additional file (detector file paths resolve relative to THIS file's dir)."""
    vt = vtype_xml("car", DEFAULT_CAR, asl=asl)
    s = ('<additional>\n%s\n' % vt +
         '  <instantInductionLoop id="stop" lane="ein_0" pos="%.2f" file="instant.xml"/>\n'
         % (LANE_LEN - 0.5) +
         '  <laneAreaDetector id="q" lane="ein_0" pos="0" endPos="%.2f" '
         'freq="%g" file="lad.xml"/>\n' % (LANE_LEN, CYCLE) +
         '</additional>\n')
    p = os.path.join(d, "add.xml")
    open(p, "w").write(s)
    tl = os.path.join(d, "tls.xml")
    open(tl, "w").write(TLS_XML)
    return p, tl


def sat_from_instant(instant_rows):
    """Rear-bumper (state='leave') crossings -> per-cycle discharge headways."""
    lv = sorted(float(r["time"]) for r in instant_rows if r.get("state") == "leave")
    per_pos = {}
    ncyc = 0
    veh_per_cycle = []
    for c in range(int(END // CYCLE)):
        g0 = c * CYCLE
        g1 = g0 + GREEN + YEL          # vehicles may still clear during yellow
        if c < WARM_CYCLES:
            continue
        ts = [t for t in lv if g0 <= t < g1]
        if len(ts) < 4:
            continue
        ncyc += 1
        veh_per_cycle.append(len(ts))
        prev = g0
        for n, t in enumerate(ts, start=1):
            per_pos.setdefault(n, []).append(t - prev)
            prev = t
    if ncyc == 0:
        return None
    hn = {n: mean(v) for n, v in sorted(per_pos.items()) if len(v) >= max(2, ncyc // 2)}
    win = [n for n in hn if 5 <= n <= 12]
    if len(win) < 4:
        win = [n for n in hn if n >= 4]
    if not win:
        return None
    hs = mean([hn[n] for n in win])
    n0 = min(win)
    l1 = sum(hn[n] - hs for n in hn if n < n0)
    # window sensitivity: alternative windows
    alts = {}
    for lo, hi in ((4, 10), (6, 14), (5, 15)):
        wn = [n for n in hn if lo <= n <= hi]
        if len(wn) >= 3:
            h2 = mean([hn[n] for n in wn])
            alts["%d-%d" % (lo, hi)] = dict(s=3600.0 / h2,
                                            l1=sum(hn[n] - h2 for n in hn if n < min(wn)))
    return dict(s=3600.0 / hs, hs=hs, l1=l1, n_cycles=ncyc, hn={str(k): v for k, v in hn.items()},
                veh_per_cycle=veh_per_cycle, alt_windows=alts)


def lad_min_queue(path):
    """min number of halting vehicles reported by the laneAreaDetector after warmup."""
    if not os.path.exists(path):
        return None
    vals = []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "interval":
            if float(el.get("begin", 0)) >= WARM_CYCLES * CYCLE:
                vals.append(float(el.get("jamLengthInVehiclesMax", el.get("nVehSeen", 0))))
            el.clear()
    return min(vals) if vals else None


def run_cell(job):
    c, seed = job
    d = os.path.join(BASE, "%s_s%d" % (cell_id(c), seed))
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    add, tl = add_xml(d, asl_value(c))
    tri = os.path.join(d, "tripinfo.xml")
    smy = os.path.join(d, "summary.xml")
    args = (["-n", APPR_NET, "-r", DEMAND, "-a", add + "," + tl,
             "--tripinfo-output", tri, "--summary-output", smy,
             "--device.emissions.probability", "1.0",
             "--begin", "0", "--end", str(END),
             "--time-to-teleport", "300", "--max-depart-delay", "3600",
             "--collision.action", "warn", "--collision.mingap-factor", "0",
             "--seed", str(seed)] + cell_args(c) + BASE_ARGS)
    r = run_sumo(args, cwd=d, tag=cell_id(c))
    if r["rc"] != 0:
        return dict(cell=cell_id(c), seed=seed, ok=False, err=r["err"][-600:])
    tot = summary_totals(smy)
    ti = read_tripinfo(tri)
    dur = [float(x["duration"]) for x in ti]
    tl_ = [float(x["timeLoss"]) for x in ti]
    wt = [float(x["waitingTime"]) for x in ti]
    co2 = [float(x["em_CO2_abs"]) / 1e6 for x in ti if "em_CO2_abs" in x]   # mg -> kg
    fuel = [float(x["em_fuel_abs"]) / 1e6 for x in ti if "em_fuel_abs" in x]
    dist = [float(x["routeLength"]) for x in ti]
    sat = sat_from_instant(read_instant(os.path.join(d, "instant.xml")))
    res = dict(cell=cell_id(c), dt=float(c[0]), method=c[1], asl=c[2], seed=seed, ok=True,
               wall=r["wall"], rtf=END / r["wall"],
               n_completed=len(ti), still_running=tot["running"],
               inserted=tot["inserted"], loaded=tot["loaded"],
               not_inserted=tot["loaded"] - tot["inserted"],
               teleports=tot["teleports"], collisions=tot["collisions"],
               mean_dur=mean(dur), mean_timeloss=mean(tl_), mean_wait=mean(wt),
               mean_co2_kg=mean(co2), mean_fuel_kg=mean(fuel),
               co2_g_per_km=(sum(co2) * 1e6 / 1000.0) / (sum(dist) / 1000.0) if dist else float("nan"),
               min_queue_after_warmup=lad_min_queue(os.path.join(d, "lad.xml")))
    if sat:
        res.update(sat_flow=sat["s"], sat_headway=sat["hs"], lost_time=sat["l1"],
                   n_cycles=sat["n_cycles"], hn=sat["hn"], alt_windows=sat["alt_windows"],
                   veh_per_cycle=sat["veh_per_cycle"])
    else:
        res.update(sat_flow=float("nan"), lost_time=float("nan"))
    return res


# ------------------------------------------------ deterministic stop-line probe
PROBE_V = dict(DEFAULT_CAR)
PROBE_V.update(sigma="0", speedDev="0", speedFactor="1.0", tau="1.0",
               accel="2.6", decel="4.5")


def _fcd_trace(fcd):
    tr = []
    for _, el in ET.iterparse(fcd, events=("end",)):
        if el.tag == "timestep":
            t = float(el.attrib["time"])
            for v in el:
                tr.append((t, float(v.attrib["x"]), float(v.attrib["speed"])))
            el.clear()
    return tr


def probe_stopline(c):
    """Two DETERMINISTIC single-vehicle probes on the same approach.

    P1 free acceleration from standstill (green) -> position error vs the ANALYTIC
       constant-acceleration solution x(t)=0.5*a*t^2 (the exact answer).
    P2 cruise -> red light -> brake-onset point, braking distance, resting position,
       and whether the front bumper ever passes the stop line.

    NOTE: this must NOT pass --default.action-step-length. Supplying that option at
    all (even with value 0) silently switches Euler to the exact/ballistic position
    update -- verified separately, see outputs/tables/integration_rule_probe.json.
    """
    d = os.path.join(BASE, "probe_" + cell_id(c))
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    vt = vtype_xml("car", PROBE_V, asl=asl_value(c))
    open(os.path.join(d, "tls_red.xml"), "w").write(
        '<additional><tlLogic id="a1" type="static" programID="red" offset="0">'
        '<phase duration="1000" state="r"/></tlLogic></additional>')
    open(os.path.join(d, "tls_grn.xml"), "w").write(
        '<additional><tlLogic id="a1" type="static" programID="grn" offset="0">'
        '<phase duration="1000" state="G"/></tlLogic></additional>')
    res = dict(cell=cell_id(c), dt=float(c[0]), method=c[1], asl=c[2], ok=True)

    # ---- P1 free acceleration, green ----
    open(os.path.join(d, "acc.rou.xml"), "w").write(
        '<routes>%s\n<vehicle id="p" type="car" depart="0" departSpeed="0" '
        'departPos="0" departLane="0"><route edges="ein eout"/></vehicle></routes>' % vt)
    f1 = os.path.join(d, "acc.fcd.xml")
    r = run_sumo(["-n", APPR_NET, "-r", os.path.join(d, "acc.rou.xml"),
                  "-a", os.path.join(d, "tls_grn.xml"), "--fcd-output", f1,
                  "--begin", "0", "--end", "30", "--seed", "1"]
                 + cell_args(c) + BASE_ARGS, cwd=d)
    if r["rc"] != 0:
        return dict(cell=cell_id(c), ok=False, err=r["err"][-400:])
    tr1 = _fcd_trace(f1)
    a = float(PROBE_V["accel"])
    vfree = APPR_V
    t_reach = vfree / a
    errs = []
    for t, x, s in tr1:
        if t <= 0 or t > t_reach:
            continue
        errs.append(x - 0.5 * a * t * t)          # + => vehicle ahead of exact
    # cumulative position offset once free speed is reached
    after = [(t, x) for t, x, s in tr1 if t >= t_reach + 2.0]
    x_exact = None
    if after:
        t0, x0 = after[0]
        x_exact = 0.5 * a * t_reach ** 2 + vfree * (t0 - t_reach)
    res.update(accel_max_pos_err=max(errs, key=abs) if errs else float("nan"),
               accel_mean_pos_err=mean(errs) if errs else float("nan"),
               accel_settled_pos_err=(after[0][1] - x_exact) if after else float("nan"),
               accel_exact_theory="x=0.5*a*t^2, a=%.2f" % a)

    # ---- P2 stop at red ----
    open(os.path.join(d, "stp.rou.xml"), "w").write(
        '<routes>%s\n<vehicle id="p" type="car" depart="0" departSpeed="max" '
        'departPos="0" departLane="0"><route edges="ein eout"/></vehicle></routes>' % vt)
    f2 = os.path.join(d, "stp.fcd.xml")
    r = run_sumo(["-n", APPR_NET, "-r", os.path.join(d, "stp.rou.xml"),
                  "-a", os.path.join(d, "tls_red.xml"), "--fcd-output", f2,
                  "--begin", "0", "--end", "200", "--seed", "1"]
                 + cell_args(c) + BASE_ARGS, cwd=d)
    tr2 = _fcd_trace(f2)
    if not tr2:
        res["ok"] = False
        return res
    vmax = max(s for _, _, s in tr2)
    stopped = [(t, x) for t, x, s in tr2 if s < 1e-6]
    rest_x = stopped[0][1] if stopped else float("nan")
    t_stop = stopped[0][0] if stopped else float("nan")
    cruise = [(t, x) for t, x, s in tr2 if s >= vmax - 1e-9]
    t_b, x_b = (cruise[-1] if cruise else (float("nan"), float("nan")))
    max_x = max(x for _, x, _ in tr2 if _ <= t_stop) if not math.isnan(t_stop) \
        else max(x for _, x, _ in tr2)
    res.update(cruise_speed=vmax, rest_x=rest_x,
               gap_to_stopline=STOPLINE_X - rest_x,      # >0 undershoot, <0 overshoot
               max_x_before_stop=max_x,
               overshot=bool(max_x > STOPLINE_X + 1e-6),
               brake_onset_x=x_b, brake_dist=(rest_x - x_b),
               brake_time=(t_stop - t_b), t_stop=t_stop,
               ideal_brake_dist=vmax ** 2 / (2.0 * float(PROBE_V["decel"])))
    return res


if __name__ == "__main__":
    jobs = [(c, s) for c in cells() for s in SEEDS]
    print("testbed (b): %d runs (%d cells x %d CRN seeds), demand=%d veh" %
          (len(jobs), len(list(cells())), len(SEEDS), NVEH))
    with ProcessPoolExecutor(max_workers=8) as ex:
        rows = list(ex.map(run_cell, jobs))
    savejson("b_signal_runs.json", rows)
    with ProcessPoolExecutor(max_workers=8) as ex:
        probes = list(ex.map(probe_stopline, list(cells())))
    savejson("b_stopline_probe.json", probes)
    bad = [r for r in rows if not r.get("ok")]
    print("failed runs:", len(bad))
    if bad:
        print(json.dumps(bad[:2], indent=1))
    for c in cells():
        rr = [r for r in rows if r.get("ok") and r["cell"] == cell_id(c)]
        if not rr:
            continue
        m, h = ci95([r["sat_flow"] for r in rr])
        m2, h2 = ci95([r["lost_time"] for r in rr])
        print("%-26s s=%7.1f+-%5.1f  l1=%5.2f+-%.2f  tl=%6.2f  co2=%6.1f g/km  "
              "tele=%d coll=%d minQ=%s" %
              (cell_id(c), m, h, m2, h2, mean([r["mean_timeloss"] for r in rr]),
               mean([r["co2_g_per_km"] for r in rr]),
               sum(r["teleports"] for r in rr), sum(r["collisions"] for r in rr),
               min(r["min_queue_after_warmup"] or 0 for r in rr)))
    print("\n-- stop-line probe --")
    for p in probes:
        if p.get("ok"):
            print("%-26s rest_x=%9.4f  gap=%+8.4f m  brake_dist=%8.3f  v=%.3f" %
                  (p["cell"], p["rest_x"], p["gap_to_stopline"], p["brake_dist"], p["cruise_speed"]))
        else:
            print(p)
