#!/usr/bin/env python3
"""
Shared library: day-draw generator, per-cell SUMO run, and output parsing
for the travel-time-reliability study.

A "day" is one Monte-Carlo draw of the exogenous state of the world:
    (demand multiplier, incident realisation, simulator seed)
The SAME list of days is replayed under every scenario -> Common Random
Numbers / paired comparison.
"""
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

import numpy as np

# ----------------------------------------------------------------- demand ---
# veh/h at demand multiplier 1.0, loaded over the 3600 s peak
CORRIDOR_VPH = 4150.0     # O -> D  (the measured corridor movement)
CORRIDOR_ALT_SHARE = 0.10  # statically pre-assigned to the parallel detour
SIDE_IN_VPH = 250.0       # N -> D  (side street joining the corridor)
MAIN_OUT_VPH = 150.0      # O -> N  (corridor traffic leaving at the signal)
PEAK_END = 3600.0
SIM_END = 10800.0
TIME_TO_TELEPORT = 200    # > longest legitimate red (46 s) by a wide margin

ROUTE_MAIN = "OA AC CB1 CB2 BD"
ROUTE_ALT = "OA AP PB BD"
ROUTE_SIDE_IN = "NC CB1 CB2 BD"
ROUTE_MAIN_OUT = "OA AC CN"

# name: (approach lanes OA/AC, midblock lanes CB1/CB2, equipped probability)
SCENARIOS = {
    "A_base":       (3, 3, 0.0),
    "B_capacity":   (4, 4, 0.0),   # full corridor widening (expensive ref.)
    "C_info":       (3, 3, 0.4),   # 40 % rerouting-device penetration
    "D_shoulder":   (3, 4, 0.0),   # midblock hard-shoulder lane only
}
NETNAME = {(3, 3): "a3m3", (4, 4): "a4m4", (3, 4): "a3m4"}


# ------------------------------------------------------------ day drawing ---
def draw_days(n_days, master_seed, cv=0.20, p_incident=0.25):
    """Draw the Monte-Carlo day list.

    demand multiplier : lognormal, E[m]=1, CV=cv
    incident          : Bernoulli(p_incident); start U(600,2700) s,
                        duration U(600,1800) s, lanes closed {1:0.6, 2:0.4},
                        location uniform over {CB1, CB2}
    seed              : uniform integer
    """
    rng = np.random.default_rng(master_seed)
    sigma = np.sqrt(np.log(1.0 + cv ** 2))
    mu = -0.5 * sigma ** 2                     # so that E[exp(X)] == 1
    days = []
    for i in range(n_days):
        mult = float(np.exp(rng.normal(mu, sigma)))
        has_inc = bool(rng.random() < p_incident)
        if has_inc:
            # NOTE: rerouter interval begin/end MUST be integer seconds.
            # Verified on SUMO 1.27.1: a fractional `begin` silently never
            # activates the closure, and a fractional `end` silently never
            # lifts it.  Both failure modes are completely silent.
            start = float(int(round(rng.uniform(600.0, 2700.0))))
            dur = float(int(round(rng.uniform(600.0, 1800.0))))
            lanes = int(1 if rng.random() < 0.6 else 2)
            loc = str(rng.choice(["CB1", "CB2"]))
        else:
            start, dur, lanes, loc = 0.0, 0.0, 0, ""
        days.append(dict(day=i, mult=round(mult, 6), incident=int(has_inc),
                         inc_start=float(start), inc_dur=float(dur),
                         inc_lanes=lanes, inc_edge=loc,
                         seed=int(rng.integers(1, 1_000_000))))
    return days


# ------------------------------------------------------- scenario writing ---
def write_routes(path, mult, equip_prob):
    r_corr = CORRIDOR_VPH * mult / 3600.0
    r_main = r_corr * (1.0 - CORRIDOR_ALT_SHARE)
    r_alt = r_corr * CORRIDOR_ALT_SHARE
    r_side = SIDE_IN_VPH * mult / 3600.0
    r_out = MAIN_OUT_VPH * mult / 3600.0
    with open(path, "w") as f:
        f.write('<routes>\n')
        f.write('    <vType id="car" accel="2.6" decel="4.5" sigma="0.5" '
                'length="5" minGap="2.5" maxSpeed="30" tau="1.0" '
                'speedFactor="1.0" carFollowModel="Krauss"/>\n')
        f.write(f'    <route id="rMain" edges="{ROUTE_MAIN}"/>\n')
        f.write(f'    <route id="rAlt" edges="{ROUTE_ALT}"/>\n')
        f.write(f'    <route id="rSide" edges="{ROUTE_SIDE_IN}"/>\n')
        f.write(f'    <route id="rOut" edges="{ROUTE_MAIN_OUT}"/>\n')
        common = ('type="car" departLane="best" departSpeed="max" '
                  'departPos="base" begin="0" end="%g"' % PEAK_END)
        f.write(f'    <flow id="corrM" route="rMain" {common} '
                f'period="exp({r_main:.6f})"/>\n')
        f.write(f'    <flow id="corrA" route="rAlt" {common} '
                f'period="exp({r_alt:.6f})"/>\n')
        f.write(f'    <flow id="side" route="rSide" {common} '
                f'period="exp({r_side:.6f})"/>\n')
        f.write(f'    <flow id="out" route="rOut" {common} '
                f'period="exp({r_out:.6f})"/>\n')
        f.write('</routes>\n')


def write_additional(path, day, mid_lanes, edgedata_name="edgedata.xml"):
    """Incident rerouter + edgeData.  The closure takes the LEFTMOST lanes so
    the side-street entry connection (which feeds CB1_0) is never severed."""
    with open(path, "w") as f:
        f.write('<additional>\n')
        if day["incident"]:
            e = day["inc_edge"]
            b = int(round(day["inc_start"]))
            en = int(round(day["inc_start"] + day["inc_dur"]))
            assert float(b) == day["inc_start"], "incident begin must be int s"
            f.write('    <rerouter id="incident" edges="OA">\n')
            f.write(f'        <interval begin="{b}" end="{en}">\n')
            for k in range(day["inc_lanes"]):
                lane = mid_lanes - 1 - k
                f.write(f'            <closingLaneReroute id="{e}_{lane}" '
                        f'disallow="all"/>\n')
            f.write('        </interval>\n')
            f.write('    </rerouter>\n')
        f.write(f'    <edgeData id="ed" file="{edgedata_name}" begin="0" '
                f'end="{SIM_END:.0f}" period="300" excludeEmpty="true"/>\n')
        f.write('</additional>\n')


# --------------------------------------------------------------- run cell ---
def run_cell(rundir, netfile, day, equip_prob, mid_lanes,
             keep_raw=False, vehroute=False, ttt=None):
    os.makedirs(rundir, exist_ok=True)
    rou = os.path.join(rundir, "demand.rou.xml")
    add = os.path.join(rundir, "scenario.add.xml")
    write_routes(rou, day["mult"], equip_prob)
    write_additional(add, day, mid_lanes)

    tri = os.path.join(rundir, "tripinfo.xml")
    summ = os.path.join(rundir, "summary.xml")
    stat = os.path.join(rundir, "stats.xml")
    log = os.path.join(rundir, "sumo.log")

    cmd = ["sumo", "-n", netfile, "-r", rou, "-a", add,
           "--tripinfo-output", tri,
           "--tripinfo-output.write-unfinished", "true",
           "--summary-output", summ,
           "--summary-output.period", "60",
           "--statistic-output", stat,
           "--device.rerouting.probability", str(equip_prob),
           "--device.rerouting.period", "60",
           "--device.rerouting.pre-period", "10",
           "--device.rerouting.adaptation-interval", "10",
           "--device.rerouting.adaptation-steps", "6",
           "--seed", str(day["seed"]),
           "--begin", "0", "--end", str(int(SIM_END)),
           "--time-to-teleport", str(TIME_TO_TELEPORT if ttt is None
                                     else ttt),
           "--no-step-log", "true",
           "--duration-log.statistics", "true",
           "--default.speeddev", "0",
           "--xml-validation", "never"]
    if vehroute:
        cmd += ["--vehroute-output", os.path.join(rundir, "vehroutes.xml"),
                "--vehroute-output.exit-times", "true"]
    with open(log, "w") as lf:
        p = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"sumo failed in {rundir} (rc={p.returncode}); "
                           f"see {log}")
    res = parse_cell(rundir)
    if not keep_raw:
        for fn in ("demand.rou.xml",):
            fp = os.path.join(rundir, fn)
            if os.path.exists(fp):
                os.remove(fp)
    return res


# ---------------------------------------------------------------- parsing ---
# SUMO emits TWO warning lines per teleport ("Teleporting vehicle
# 'x'; waited too long ..." and "Vehicle 'x' ends teleporting on
# edge ..."), so counting every line mentioning "teleport" double-counts.
TELEPORT_RE = re.compile(r"Teleporting vehicle")
TELEPORT_ANY_RE = re.compile(r"teleporting", re.I)


def parse_cell(rundir, cached=False):
    """Build the per-cell summary row.

    `cached=True` rebuilds the row from the already-written corr_tt.npz plus
    summary/stats/edgeData/log, without needing tripinfo.xml -- which lets a
    completed cell be re-summarised after its bulky tripinfo has been deleted.
    """
    tri = os.path.join(rundir, "tripinfo.xml")
    corr_dur, corr_fin, corr_ids = [], [], []
    corr_route_len, corr_dev, corr_dd, corr_dep = [], [], [], []
    n_unfinished = 0
    all_dur = []
    if cached:
        z = np.load(os.path.join(rundir, "corr_tt.npz"), allow_pickle=True)
        corr_dur = list(z["dur"])
        corr_fin = list(z["finished"])
        corr_ids = list(z["ids"])
        corr_dev = list(z["devices"])
        corr_dd = list(z["departdelay"])
        corr_dep = list(z["depart"])
        corr_route_len = list(z["routelen"])
    for _, el in ([] if cached else ET.iterparse(tri, events=("end",))):
        if el.tag != "tripinfo":
            continue
        vid = el.get("id")
        dur = float(el.get("duration"))
        arr = float(el.get("arrival"))
        finished = arr >= 0.0
        if vid.startswith("corr"):
            corr_ids.append(vid)
            corr_dur.append(dur)
            corr_fin.append(1 if finished else 0)
            corr_route_len.append(float(el.get("routeLength") or -1))
            corr_dev.append(el.get("devices") or "")
            corr_dd.append(float(el.get("departDelay") or 0.0))
            corr_dep.append(float(el.get("depart")))
        if finished:
            all_dur.append(dur)
        else:
            n_unfinished += 1
        el.clear()

    corr_dur = np.array(corr_dur, dtype=float)
    corr_fin = np.array(corr_fin, dtype=int)

    if cached:
        # unfinished-vehicle count comes from the last summary step's
        # `running` (vehicles still in the network when the run ended)
        n_unfinished = -1
    # ---- summary: teleports (cumulative -> take max), running-count freeze
    tel = 0
    run_series, arr_series, t_series = [], [], []
    sp = os.path.join(rundir, "summary.xml")
    if os.path.exists(sp):
        for _, el in ET.iterparse(sp, events=("end",)):
            if el.tag != "step":
                continue
            tel = max(tel, int(el.get("teleports", 0)))
            run_series.append(int(el.get("running", 0)))
            arr_series.append(int(el.get("ended", el.get("arrived", 0))))
            t_series.append(float(el.get("time")))
            el.clear()

    # ---- statistics: loaded / inserted / not-inserted
    loaded = inserted = waiting = 0
    sp = os.path.join(rundir, "stats.xml")
    if os.path.exists(sp):
        root = ET.parse(sp).getroot()
        v = root.find("vehicles")
        if v is not None:
            loaded = int(v.get("loaded", 0))
            inserted = int(v.get("inserted", 0))
            waiting = int(v.get("waiting", 0))

    # ---- edgeData: detour usage + spillback check
    ap_entered = ac_occ_max = oa_occ_max = 0.0
    ed = os.path.join(rundir, "edgedata.xml")
    if os.path.exists(ed):
        for _, el in ET.iterparse(ed, events=("end",)):
            if el.tag != "edge":
                continue
            eid = el.get("id")
            if eid == "AP":
                ap_entered += float(el.get("entered", 0))
            elif eid == "AC":
                ac_occ_max = max(ac_occ_max, float(el.get("occupancy", 0)))
            elif eid == "OA":
                oa_occ_max = max(oa_occ_max, float(el.get("occupancy", 0)))
            el.clear()

    # ---- teleport warnings from the log (tripinfo has no teleport field)
    tel_log = 0
    tel_ids = set()
    lp = os.path.join(rundir, "sumo.log")
    if os.path.exists(lp):
        with open(lp, errors="ignore") as f:
            for line in f:
                if TELEPORT_RE.search(line):
                    tel_log += 1
                if TELEPORT_ANY_RE.search(line):
                    m = re.search(r"[Vv]ehicle '([^']+)'", line)
                    if m:
                        tel_ids.add(m.group(1))

    if cached and run_series:
        n_unfinished = int(run_series[-1])
    fin = corr_dur[corr_fin == 1]
    out = dict(
        n_corr=len(corr_dur), n_corr_finished=int(corr_fin.sum()),
        n_corr_unfinished=int((corr_fin == 0).sum()),
        n_unfinished_all=n_unfinished,
        loaded=loaded, inserted=inserted, not_inserted=loaded - inserted,
        teleports=tel, teleport_log_lines=tel_log,
        teleport_veh=len(tel_ids),
        teleport_corr_veh=len([v for v in tel_ids if v.startswith("corr")]),
        ap_entered=ap_entered, ac_occ_max=ac_occ_max, oa_occ_max=oa_occ_max,
        mean_tt=float(fin.mean()) if len(fin) else float("nan"),
        gridlock_freeze=_freeze_check(t_series, run_series, arr_series),
    )
    if cached:
        return out
    np.savez_compressed(os.path.join(rundir, "corr_tt.npz"),
                        dur=corr_dur, finished=corr_fin,
                        ids=np.array(corr_ids),
                        devices=np.array(corr_dev),
                        departdelay=np.array(corr_dd, dtype=float),
                        depart=np.array(corr_dep, dtype=float),
                        routelen=np.array(corr_route_len, dtype=float))
    return out


def _freeze_check(t, running, ended):
    """Signature of permanent gridlock: running count frozen and zero arrivals
    over the last stretch of the run while vehicles are still in the network."""
    if len(t) < 20:
        return 0
    r = np.array(running[-15:])
    e = np.array(ended[-15:])
    if r[-1] > 0 and r.std() == 0 and (e[-1] - e[0]) == 0:
        return 1
    return 0
