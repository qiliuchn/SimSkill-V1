#!/usr/bin/env python3
"""
Measure this network's OWN emergent saturation flow rate `s` and startup lost
time `l1` at the stop line, instead of assuming a textbook / tool-default value
(`measure-saturation-flow-and-validate-webster-method`).

Rig: the study's own net, an oversaturated N+S through-only demand, a hand-written
tlLogic that greens only the N/S through links, an instantInductionLoop at each
N stop line (per-vehicle enter/leave timestamps), --step-length 0.1 (the 1 s
default cannot resolve a ~2 s saturation headway) and departSpeed="max" (
departSpeed=0 silently caps insertion around 1500 veh/h/lane).

Two independent estimators:
  1. headway-vs-queue-position (windowed), rear-bumper ("leave") convention
  2. green-duration regression  N_d(g) = (s/3600)(g - l1 + e)   -- valid here
     because the fleet has sigma=0.5 (driver noise), see the skill's correction
     about the deterministic (sigma=0) case.
"""
import argparse
import os
import statistics as st
import subprocess
import sys
import xml.etree.ElementTree as ET

SUMO_HOME = os.environ["SUMO_HOME"]
SUMO = os.path.join(SUMO_HOME, "bin", "sumo")
GREEN_NS_THRU = "rGGrrrrrrGGrrrrr"   # links 1,2 (N through) and 9,10 (S through) only
ALL_RED = "r" * 16


def write_inputs(d, green, cycle, q, tend):
    with open(os.path.join(d, "add.xml"), "w") as f:
        f.write('<additional>\n')
        f.write('  <tlLogic id="center" type="static" programID="sat" offset="0">\n')
        f.write('    <phase duration="%d" state="%s"/>\n' % (green, GREEN_NS_THRU))
        f.write('    <phase duration="%d" state="%s"/>\n' % (cycle - green, ALL_RED))
        f.write('  </tlLogic>\n')
        for ln in ("in_N_0", "in_N_1", "in_S_0", "in_S_1"):
            f.write('  <instantInductionLoop id="il_%s" lane="%s" pos="-0.5" '
                    'file="loop.xml"/>\n' % (ln, ln))
        f.write('</additional>\n')
    with open(os.path.join(d, "rou.xml"), "w") as f:
        f.write('<routes>\n')
        f.write('  <vType id="hdv" vClass="passenger" length="4.5" minGap="2.5" accel="2.6"'
                ' decel="4.5" sigma="0.5" tau="1.0" maxSpeed="16.0"'
                ' speedFactor="normc(1.00,0.10,0.85,1.15)"/>\n')
        f.write('  <route id="ns" edges="in_N out_S"/>\n')
        f.write('  <route id="sn" edges="in_S out_N"/>\n')
        for r in ("ns", "sn"):
            f.write('  <flow id="f_%s" route="%s" begin="0" end="%d" vehsPerHour="%d"'
                    ' type="hdv" departLane="random" departSpeed="max"/>\n' % (r, r, tend, q))
        f.write('</routes>\n')


def run(d, net, green, cycle, q, tend, seed):
    os.makedirs(d, exist_ok=True)
    write_inputs(d, green, cycle, q, tend)
    cmd = [SUMO, "-n", net, "-r", os.path.join(d, "rou.xml"),
           "-a", os.path.join(d, "add.xml"),
           "--step-length", "0.1", "--begin", "0", "--end", str(tend + 200),
           "--seed", str(seed), "--no-step-log", "true",
           "--time-to-teleport", "600", "--max-depart-delay", "300",
           "--xml-validation", "never",
           "--tripinfo-output", os.path.join(d, "tripinfo.xml")]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit("sumo failed: " + p.stderr[-2000:])
    return os.path.join(d, "loop.xml")


def headways(loopfile, green, cycle, warm=2, lanes=("in_N_0", "in_N_1", "in_S_0", "in_S_1")):
    """Return {queue_position: [headways]} using rear-bumper (leave) crossings."""
    root = ET.parse(loopfile).getroot()
    ev = []
    for e in root:
        if e.tag != "instantOut" or e.get("state") != "leave":
            continue
        lane = e.get("id").replace("il_", "")
        if lane not in lanes:
            continue
        ev.append((float(e.get("time")), lane))
    ev.sort()
    bypos = {}
    percycle = {}
    for (t, lane) in ev:
        c = int(t // cycle)
        if c < warm:
            continue
        into = t - c * cycle
        if into > green:            # discharged after green ended -> ignore
            continue
        key = (c, lane)
        percycle.setdefault(key, []).append(t)
    for key, times in percycle.items():
        times.sort()
        for n in range(1, len(times)):
            bypos.setdefault(n, []).append(times[n] - times[n - 1])
    counts = [len(v) for v in percycle.values()]
    return bypos, counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--greens", default="16,24,32,40")
    ap.add_argument("--cycle", type=int, default=90)
    ap.add_argument("--demand", type=int, default=3600)
    ap.add_argument("--tend", type=int, default=1800)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--window", default="5,12")
    a = ap.parse_args()

    greens = [int(x) for x in a.greens.split(",")]
    w0, w1 = (int(x) for x in a.window.split(","))
    res = {}
    for g in greens:
        d = os.path.join(a.outdir, "g%d" % g)
        lf = run(d, a.net, g, a.cycle, a.demand, a.tend, a.seed)
        bypos, counts = headways(lf, g, a.cycle)
        res[g] = (bypos, counts)

    print("=== estimator 1: headway vs queue position (green=%d) ===" % greens[-1])
    bypos, counts = res[greens[-1]]
    hs = {}
    for n in sorted(bypos):
        if len(bypos[n]) >= 5:
            hs[n] = st.mean(bypos[n])
            print("  pos %2d  n=%3d  h=%.3f s" % (n, len(bypos[n]), hs[n]))
    win = [hs[n] for n in hs if w0 <= n <= w1]
    h_s = st.mean(win)
    s1 = 3600.0 / h_s
    l1 = sum(hs[n] - h_s for n in sorted(hs) if n < w0)
    print("  saturation headway h_s (pos %d-%d) = %.3f s -> s = %.0f veh/h/lane" % (w0, w1, h_s, s1))
    print("  startup lost time l1 = %.2f s" % l1)
    for alt in ((4, 10), (6, 14), (5, 15)):
        wv = [hs[n] for n in hs if alt[0] <= n <= alt[1]]
        if wv:
            print("    window sensitivity %s: h_s=%.3f -> s=%.0f" %
                  (str(alt), st.mean(wv), 3600.0 / st.mean(wv)))

    print("\n=== estimator 2: green-duration regression ===")
    xs, ys = [], []
    for g in greens:
        _bp, counts = res[g]
        n = st.mean(counts)
        xs.append(g)
        ys.append(n)
        print("  g=%2ds  mean vehicles discharged per cycle per lane-set = %.2f (cycles=%d)"
              % (g, n, len(counts)))
    n_ = len(xs)
    mx, my = st.mean(xs), st.mean(ys)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    a0 = my - b * mx
    ss_t = sum((y - my) ** 2 for y in ys)
    ss_r = sum((y - (a0 + b * x)) ** 2 for x, y in zip(xs, ys))
    r2 = 1 - ss_r / ss_t if ss_t > 0 else float("nan")
    n_lanes = 1.0   # `counts` is already per-lane per-cycle
    s2 = b * 3600.0 / n_lanes
    l1b = -a0 / b
    print("  slope=%.4f veh/s over %d lanes -> s = %.0f veh/h/lane ; l1 = %.2f s ; R2=%.4f"
          % (b, int(n_lanes), s2, l1b, r2))
    with open(os.path.join(a.outdir, "saturation.txt"), "w") as f:
        f.write("s_windowed=%.1f\nl1_windowed=%.2f\ns_regression=%.1f\nl1_regression=%.2f\nR2=%.4f\n"
                % (s1, l1, s2, l1b, r2))
    print("\nwritten:", os.path.join(a.outdir, "saturation.txt"))


if __name__ == "__main__":
    main()
