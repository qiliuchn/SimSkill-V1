#!/usr/bin/env python3
"""
Measure SUMO's own emergent saturation flow rate `s` and net lost time for each
lane group of the driveway intersection, using the WINDOW-FREE green-duration
regression from `measure-saturation-flow-and-validate-webster-method`:

    N_d(g) = (s/3600) * (g - l_net)

fitted over four displayed green durations, with each lane group saturated in a
SEPARATE run (the HCM-LOS skill's finding: a jointly-oversaturated run cannot
measure an exclusive left-turn bay, because the saturated through queue blocks
left-turners from ever reaching it).

Fleet has sigma=0.5 (>0) so the regression estimator is the appropriate primary;
the windowed headway-position estimator is reported as a secondary cross-check.

--step-length 0.1 with vType actionStepLength PINNED at 1.0 s and ballistic
integration (the discretization gotcha).  A 0.5 s cross-check run is also done
because the 12-hour operational runs use 0.5 s.
"""
import json
import os
import shutil
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import CAL, SCEN, find_bin, run, write, ACTION_STEP

NET = os.path.join(SCEN, "net", "signal.net.xml")

# link index -> movement (read off the compiled net, see network_verification.txt)
LINKS = {0: "DWR", 1: "DWT", 2: "DWL", 3: "WBR", 4: "WBT", 5: "WBT", 6: "WBL",
         7: "SBR", 8: "SBT", 9: "SBL", 10: "EBR", 11: "EBT", 12: "EBT", 13: "EBL"}
NLINK = 14

# lane group -> (green link indices, measured stop-bar lanes, demand flows)
GROUPS = {
    "major_through": {
        "green": [3, 4, 5, 10, 11, 12],
        "lanes": ["maj_W_bay_0", "maj_W_bay_1"],
        "nlanes": 2,
        "flows": [("EBT", "maj_W_feed maj_W_bay maj_out_E", 4400, "random")],
    },
    "major_left_bay": {
        "green": [6, 13],
        "lanes": ["maj_W_bay_2"],
        "nlanes": 1,
        "flows": [("EBL", "maj_W_feed maj_W_bay drw_N_out", 1800, "1")],
    },
    "driveway": {
        "green": [0, 1, 2, 7, 8, 9],
        "lanes": ["drw_N_in_0"],
        "nlanes": 1,
        "flows": [("DWR", "drw_N_in maj_out_W", 900, "0"),
                  ("DWL", "drw_N_in maj_out_E", 900, "0")],
    },
    "minor_street": {
        "green": [0, 1, 2, 7, 8, 9],
        "lanes": ["min_S_in_0"],
        "nlanes": 1,
        "flows": [("SBR", "min_S_in maj_out_E", 900, "0"),
                  ("SBL", "min_S_in maj_out_W", 900, "0")],
    },
}
GREENS = [16, 24, 32, 40]
YELLOW, ALLRED, RED_REST = 3, 2, 30
CAL_END = 3600


def state(green_idx, ch):
    return "".join(ch if i in green_idx else "r" for i in range(NLINK))


def tls_xml(green_idx, g):
    ph = [(g, state(green_idx, "G")), (YELLOW, state(green_idx, "y")),
          (ALLRED, "r" * NLINK), (RED_REST, "r" * NLINK)]
    # netconvert already wrote a programID "0"; a second logic with the same
    # id+programID is a hard error, so ours is a distinct program activated at
    # t=0 by a WAUT (see switch-signal-plans-by-time-of-day-with-waut).
    x = ['<?xml version="1.0" encoding="UTF-8"?>', "<additional>",
         '  <tlLogic id="C" type="static" programID="cal" offset="0">']
    for d, s in ph:
        x.append(f'    <phase duration="{d}" state="{s}"/>')
    x += ["  </tlLogic>",
          '  <WAUT id="w" refTime="0" startProg="cal"/>',
          '  <wautJunction wautID="w" junctionID="C" procedure="Immediate"/>',
          "</additional>"]
    return "\n".join(x) + "\n", sum(p[0] for p in ph)


def routes_xml(flows):
    x = ['<?xml version="1.0" encoding="UTF-8"?>', "<routes>",
         f'  <vType id="car" vClass="passenger" accel="2.6" decel="4.5" sigma="0.5"'
         f' length="5.0" minGap="2.5" tau="1.0" maxSpeed="22.0" speedFactor="1.0"'
         f' speedDev="0" actionStepLength="{ACTION_STEP}" carFollowModel="Krauss"'
         f' lcKeepRight="0"/>']
    for name, edges, vph, dl in flows:
        x.append(f'  <route id="r_{name}" edges="{edges}"/>')
        x.append(f'  <flow id="f_{name}" type="car" route="r_{name}" begin="0" '
                 f'end="{CAL_END}" vehsPerHour="{vph}" departLane="{dl}" departSpeed="max"/>')
    x.append("</routes>")
    return "\n".join(x) + "\n"


def det_xml(lanes):
    x = ['<?xml version="1.0" encoding="UTF-8"?>', "<additional>"]
    for ln in lanes:
        x.append(f'  <instantInductionLoop id="i_{ln}" lane="{ln}" pos="-2" '
                 f'file="instant.xml"/>')
        x.append(f'  <laneAreaDetector id="q_{ln}" lane="{ln}" pos="0" endPos="-0.1" '
                 f'period="{CAL_END}" file="e2.xml"/>')
    x.append("</additional>")
    return "\n".join(x) + "\n"


def one_run(gname, g, step):
    cfg = GROUPS[gname]
    d = os.path.join(CAL, f"{gname}_g{g}_st{str(step).replace('.','p')}")
    if os.path.isdir(d):
        shutil.rmtree(d)
    os.makedirs(d)
    tls, cycle = tls_xml(cfg["green"], g)
    write(os.path.join(d, "tls.add.xml"), tls)
    write(os.path.join(d, "routes.rou.xml"), routes_xml(cfg["flows"]))
    write(os.path.join(d, "det.add.xml"), det_xml(cfg["lanes"]))
    cmd = [find_bin("sumo"), "-n", NET, "-r", "routes.rou.xml",
           "-a", "tls.add.xml,det.add.xml", "--begin", "0", "--end", str(CAL_END),
           "--step-length", str(step), "--step-method.ballistic",
           "--seed", "11", "--time-to-teleport", "-1",
           "--max-depart-delay", "60",
           "--no-step-log", "true", "--xml-validation", "never",
           "--duration-log.statistics", "true",
           "--statistic-output", "statistics.xml"]
    r = run(cmd, cwd=d)
    if r.returncode != 0:
        print(r.stderr[:2000]); sys.exit(f"calibration run failed: {gname} g={g}")
    return d, cycle


def parse_leaves(d, lanes):
    """instant loop 'leave' events -> {lane: sorted list of times}"""
    ev = {ln: [] for ln in lanes}
    for e in ET.parse(os.path.join(d, "instant.xml")).getroot():
        if e.get("state") != "leave":
            continue
        did = e.get("id")
        ln = did[2:]
        if ln in ev:
            ev[ln].append(float(e.get("time")))
    for ln in ev:
        ev[ln].sort()
    return ev


def analyse(gname, step):
    cfg = GROUPS[gname]
    rows = []
    per_cycle_counts = {}
    headway_by_pos = {}
    for g in GREENS:
        d, cycle = one_run(gname, g, step)
        ev = parse_leaves(d, cfg["lanes"])
        # a discharge window = [green start, start of the NEXT phase's green]
        # i.e. the whole green + yellow + all-red; vehicles keep discharging into
        # the yellow, so this is the window the regression intercept refers to.
        window = g + YELLOW + ALLRED
        ncyc = int(CAL_END // cycle)
        counts = []
        pos_h = {}
        for c in range(1, ncyc):          # skip cycle 0 (warm-up / queue building)
            t0 = c * cycle
            tot = 0
            for ln in cfg["lanes"]:
                ts = [t for t in ev[ln] if t0 <= t < t0 + window]
                tot += len(ts)
                for i in range(1, len(ts)):
                    pos_h.setdefault(i + 1, []).append(ts[i] - ts[i - 1])
            counts.append(tot / cfg["nlanes"])   # per lane
        per_cycle_counts[g] = counts
        headway_by_pos[g] = {k: sum(v) / len(v) for k, v in sorted(pos_h.items())}
        rows.append((g, sum(counts) / len(counts), len(counts)))
    # ---- OLS  N = a*g + b   ->  s = 3600*a ,  l_net = -b/a
    n = len(rows)
    sx = sum(r[0] for r in rows); sy = sum(r[1] for r in rows)
    sxx = sum(r[0] ** 2 for r in rows); sxy = sum(r[0] * r[1] for r in rows)
    a = (n * sxy - sx * sy) / (n * sxx - sx * sx)
    b = (sy - a * sx) / n
    ybar = sy / n
    ss_tot = sum((r[1] - ybar) ** 2 for r in rows)
    ss_res = sum((r[1] - (a * r[0] + b)) ** 2 for r in rows)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    s = 3600 * a
    l_net = -b / a
    # ---- secondary: windowed headway-position estimator on the longest green
    hp = headway_by_pos[GREENS[-1]]
    sat_positions = [p for p in hp if p >= 6]
    h_s = sum(hp[p] for p in sat_positions) / len(sat_positions) if sat_positions else float("nan")
    s_hw = 3600 / h_s if h_s == h_s else float("nan")
    l1_hw = sum(hp[p] - h_s for p in hp if p < 6) if sat_positions else float("nan")
    return {"group": gname, "step_length": step,
            "regression": {"points": [{"g": r[0], "N_per_lane": round(r[1], 3),
                                       "cycles": r[2]} for r in rows],
                           "slope_veh_per_s": a, "intercept": b, "r2": r2,
                           "s_veh_per_h_per_lane": s, "l_net_s": l_net},
            "headway_position": {"mean_headway_by_position":
                                 {str(k): round(v, 3) for k, v in hp.items()},
                                 "h_sat_s": h_s, "s_veh_per_h_per_lane": s_hw,
                                 "l1_s": l1_hw}}


def main():
    out = {}
    for gname in GROUPS:
        res = analyse(gname, 0.1)
        out[gname] = res
        rg = res["regression"]
        print(f"[cal] {gname:15s} step=0.1  s={rg['s_veh_per_h_per_lane']:7.1f} veh/h/ln  "
              f"l_net={rg['l_net_s']:5.2f} s  R2={rg['r2']:.4f}  "
              f"| headway-pos s={res['headway_position']['s_veh_per_h_per_lane']:7.1f}")
    # cross-check at the operational step length
    cross = {}
    for gname in GROUPS:
        res = analyse(gname, 0.5)
        cross[gname] = res
        rg = res["regression"]
        print(f"[cal] {gname:15s} step=0.5  s={rg['s_veh_per_h_per_lane']:7.1f} veh/h/ln  "
              f"l_net={rg['l_net_s']:5.2f} s  R2={rg['r2']:.4f}")
    write(os.path.join(CAL, "saturation_flow.json"),
          json.dumps({"step_0.1": out, "step_0.5": cross}, indent=2))
    print("\n[cal] wrote", os.path.join(CAL, "saturation_flow.json"))


if __name__ == "__main__":
    main()
