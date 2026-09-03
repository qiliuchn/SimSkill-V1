#!/usr/bin/env python3
"""
Scenario assembly for the HCM LOS test bed: signal plans (pretimed + actuated),
detectors (stop-line instant loops, segment entry/exit instant loops,
laneAreaDetector queue chains), demand, and the sumocfg.

All detector `file=` attributes are written as ABSOLUTE paths: SUMO resolves
them relative to the ADDITIONAL FILE's own directory, not the caller's cwd
(documented gotcha in `measure-saturation-flow-and-validate-webster-method`
and [[sumo-output-files]]).
"""
import os, subprocess, shutil
import xml.etree.ElementTree as ET
from gen_network import MOV, find_bin, SEG_LEN, BAY_LEN, FEED_LEN, SPEED

APPROACHES = ["N", "E", "S", "W"]
EXIT_POS = 100.0          # exit cross-section, m along the downstream out_ edge

# --- signal design -----------------------------------------------------------
# 4 phases, fully protected left turns:
#   P1 N/S left | P2 N/S through+right | P3 E/W left | P4 E/W through+right
YEL = 3.0
ARD = 2.0
PRETIMED_GREEN = {"NSL": 10.0, "NST": 30.0, "EWL": 10.0, "EWT": 30.0}
CYCLE = sum(PRETIMED_GREEN.values()) + 4 * (YEL + ARD)      # = 100 s
# actuated bounds (same phase skeleton)
ACT_BOUNDS = {"NSL": (8.0, 25.0), "NST": (12.0, 45.0),
              "EWL": (8.0, 25.0), "EWT": (12.0, 45.0)}
MAX_GAP = 3.0            # unit extension (s) -> HCM k_min lookup
PHASE_ORDER = ["NSL", "NST", "EWL", "EWT"]

# movement key -> (approach, movement letter)
MOVEMENTS = [(a, m) for a in APPROACHES for m in ("L", "T", "R")]
# HCM lane groups: exclusive-left (1 lane) and shared through+right (2 lanes)
LANE_GROUPS = [(a, "L") for a in APPROACHES] + [(a, "TR") for a in APPROACHES]


def link_index_map(net):
    """{(approach, dir_char): [link indices]} plus per-link (fromLane)."""
    r = ET.parse(net).getroot()
    out = {}
    for c in r.findall("connection"):
        if c.get("tl") is None:
            continue
        a = c.get("from").split("_")[1]
        d = {"l": "L", "s": "T", "r": "R"}[c.get("dir")]
        out.setdefault((a, d), []).append(int(c.get("linkIndex")))
    return out


def phase_links(lmap):
    """{phase key: set of green link indices}"""
    return {
        "NSL": set(lmap[("N", "L")] + lmap[("S", "L")]),
        "NST": set(lmap[("N", "T")] + lmap[("N", "R")] + lmap[("S", "T")] + lmap[("S", "R")]),
        "EWL": set(lmap[("E", "L")] + lmap[("W", "L")]),
        "EWT": set(lmap[("E", "T")] + lmap[("E", "R")] + lmap[("W", "T")] + lmap[("W", "R")]),
    }


def _state(n, greens, ch="G"):
    return "".join(ch if i in greens else "r" for i in range(n))


def write_tls(net, path, control, greens=None):
    """control in {'pretimed','actuated'}.  greens overrides PRETIMED_GREEN."""
    lmap = link_index_map(net)
    n = 1 + max(i for v in lmap.values() for i in v)
    pl = phase_links(lmap)
    g = dict(PRETIMED_GREEN if greens is None else greens)
    typ = "static" if control == "pretimed" else "actuated"
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<additional>",
             f'  <tlLogic id="C" type="{typ}" programID="P" offset="0">']
    if control == "actuated":
        lines.append(f'    <param key="max-gap" value="{MAX_GAP}"/>')
        lines.append('    <param key="detector-gap" value="2.0"/>')
        lines.append('    <param key="passing-time" value="2.0"/>')
    for k in PHASE_ORDER:
        if control == "actuated":
            lo, hi = ACT_BOUNDS[k]
            lines.append(f'    <phase duration="{hi}" minDur="{lo}" maxDur="{hi}" '
                         f'state="{_state(n, pl[k])}" name="{k}"/>')
        else:
            lines.append(f'    <phase duration="{g[k]}" state="{_state(n, pl[k])}" name="{k}"/>')
        lines.append(f'    <phase duration="{YEL}" state="{_state(n, pl[k], "y")}" name="{k}_y"/>')
        lines.append(f'    <phase duration="{ARD}" state="{_state(n, set())}" name="{k}_ar"/>')
    lines += ["  </tlLogic>", "</additional>"]
    open(path, "w").write("\n".join(lines) + "\n")
    return path


def write_detectors(net, outdir, e2_freq=5.0, want_stopline=True):
    """Additional file with instant loops + E2 queue chains + TLS switch log."""
    od = os.path.abspath(outdir)
    os.makedirs(od, exist_ok=True)
    # the left-lane queue chain differs between the operational network (bay fed
    # by inA lane 1) and the calibration network (exclusive left lane all the way)
    r = ET.parse(net).getroot()
    n_inA = max(len(e.findall("lane")) for e in r.findall("edge")
                if (e.get("id") or "").startswith("inA_"))
    lfeed = 2 if n_inA == 3 else 1
    L = ['<?xml version="1.0" encoding="UTF-8"?>', "<additional>"]
    stop_f = os.path.join(od, "stopline.xml")
    seg_f = os.path.join(od, "segment.xml")
    e2_f = os.path.join(od, "queue.xml")
    for a in APPROACHES:
        if want_stopline:
            for j in range(3):
                L.append(f'  <instantInductionLoop id="sl_{a}_{j}" lane="inB_{a}_{j}" '
                         f'pos="{BAY_LEN - 0.5:.2f}" file="{stop_f}"/>')
        for j in range(2):   # segment ENTRY, 250 m upstream of the stop line
            L.append(f'  <instantInductionLoop id="en_{a}_{j}" lane="inA_{a}_{j}" '
                     f'pos="0.5" file="{seg_f}"/>')
        for j in range(2):   # segment EXIT, 100 m past the junction
            L.append(f'  <instantInductionLoop id="ex_{a}_{j}" lane="out_{a}_{j}" '
                     f'pos="{EXIT_POS}" file="{seg_f}"/>')
        # queue chains (multi-lane E2). through lanes run feed->inA->inB;
        # bay-only + bay-with-upstream-overflow chains for the left lane group.
        L.append(f'  <laneAreaDetector id="q_{a}_T0" lanes="feed_{a}_0 inA_{a}_0 inB_{a}_0" '
                 f'pos="0" endPos="{BAY_LEN}" period="{e2_freq}" file="{e2_f}"/>')
        L.append(f'  <laneAreaDetector id="q_{a}_T1" lanes="feed_{a}_1 inA_{a}_1 inB_{a}_1" '
                 f'pos="0" endPos="{BAY_LEN}" period="{e2_freq}" file="{e2_f}"/>')
        L.append(f'  <laneAreaDetector id="q_{a}_Lbay" lanes="inB_{a}_2" '
                 f'pos="0" endPos="{BAY_LEN}" period="{e2_freq}" file="{e2_f}"/>')
        L.append(f'  <laneAreaDetector id="q_{a}_Lall" lanes="feed_{a}_{lfeed} inA_{a}_{lfeed} inB_{a}_2" '
                 f'pos="0" endPos="{BAY_LEN}" period="{e2_freq}" file="{e2_f}"/>')
    L.append(f'  <timedEvent type="SaveTLSSwitchStates" source="C" '
             f'dest="{os.path.join(od, "tlsswitch.xml")}"/>')
    L.append("</additional>")
    p = os.path.join(od, "detectors.add.xml")
    open(p, "w").write("\n".join(L) + "\n")
    return p


VTYPE = ('  <vType id="car" vClass="passenger" carFollowModel="Krauss" accel="2.6" decel="4.5" '
         'sigma="0.5" tau="1.0" length="5.0" minGap="2.5" maxSpeed="16.67" '
         'speedFactor="1.0" speedDev="0" actionStepLength="1.0"/>')


def write_routes(path, vol, begin=0.0, end=3600.0, depart_speed="max", n_feed_lanes=2,
                 arrivals="uniform"):
    """vol[(approach, movement)] = veh/h.  movement in L/T/R.

    departLane is PINNED per movement rather than left at "best".  Verified
    failure of "best": under oversaturation SUMO's bestLanes ranking inserts
    left-turners into the adjacent THROUGH lane (whichever is momentarily
    shorter), and they then have to force a lane change into the bay AT the stop
    line - which throttled the measured protected-left saturation flow to
    ~900 veh/h/ln (true value ~1800) and simultaneously blocked the through lane.
    """
    lane_of = {"L": str(n_feed_lanes - 1), "T": "free", "R": "0"}
    L = ['<?xml version="1.0" encoding="UTF-8"?>', "<routes>", VTYPE]
    for a in APPROACHES:
        for m, key in (("L", "l"), ("T", "t"), ("R", "r")):
            dest = MOV[a][key]
            L.append(f'  <route id="r_{a}{m}" edges="feed_{a} inA_{a} inB_{a} {dest}"/>')
    for a in APPROACHES:
        for m in ("L", "T", "R"):
            q = vol.get((a, m), 0.0)
            if q <= 0:
                continue
            # `vehsPerHour` inserts vehicles at EQUAL headways (deterministic).
            # HCM's incremental delay term d2 is derived for RANDOM arrivals, so
            # a validation of d2 needs `period="exp(rate)"` (Poisson) instead.
            rate = (f'vehsPerHour="{q:.2f}"' if arrivals == "uniform"
                    else f'period="exp({q/3600.0:.6f})"')
            L.append(f'  <flow id="f_{a}{m}" type="car" route="r_{a}{m}" begin="{begin}" '
                     f'end="{end}" {rate} departLane="{lane_of[m]}" '
                     f'departSpeed="{depart_speed}" departPos="base"/>')
    L.append("</routes>")
    open(path, "w").write("\n".join(L) + "\n")
    return path


def run_sumo(net, routes, adds, outdir, end, step=0.1, seed=42, tripinfo=True,
             extra=None, quiet=True):
    od = os.path.abspath(outdir)
    os.makedirs(od, exist_ok=True)
    cmd = [find_bin("sumo"), "-n", os.path.abspath(net), "-r", os.path.abspath(routes),
           "-a", ",".join(os.path.abspath(x) for x in adds),
           "--begin", "0", "--end", str(end),
           "--step-length", str(step), "--step-method.ballistic",
           "--time-to-teleport", "-1",          # no teleport artifacts in a delay study
           "--summary-output", os.path.join(od, "summary.xml"),
           "--seed", str(seed), "--no-step-log", "true", "--duration-log.statistics", "true",
           "--xml-validation", "never"]
    if tripinfo:
        cmd += ["--tripinfo-output", os.path.join(od, "tripinfo.xml")]
    if extra:
        cmd += extra
    r = subprocess.run(cmd, capture_output=True, text=True)
    open(os.path.join(od, "sumo.stderr.txt"), "w").write(r.stderr)
    open(os.path.join(od, "sumo.cmd.txt"), "w").write(" ".join(cmd))
    if r.returncode != 0:
        raise RuntimeError(f"sumo failed in {od}:\n{r.stderr[-4000:]}")
    if not quiet and r.stderr.strip():
        print(r.stderr[-2000:])
    return od, r.stderr
