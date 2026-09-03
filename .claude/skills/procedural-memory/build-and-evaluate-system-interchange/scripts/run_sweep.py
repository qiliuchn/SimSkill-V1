#!/usr/bin/env python3
"""
Run the demand sweep (3 variants x 8 demand scales x 3 seeds) and aggregate each run
into a small metrics.json immediately, so the sweep does not leave ~250 MB of tripinfo
behind.  Raw detector/tripinfo XML is preserved only for the reference seed, which is
what the time-space plots and the per-movement travel-time table are built from.

Every run uses FIXED routes and no rerouting device: a vehicle that meets congestion in
the weaving section must sit in it, exactly as the design comparison intends.  If
rerouting were enabled the three designs would silently differ in path choice as well as
in geometry, which would confound the capacity comparison.
"""
import argparse
import glob
import json
import math
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scenario as S                                     # noqa: E402

EPISODE = S.EPISODE
NETDIR = S.NETDIR
DEMDIR = S.DEMDIR
RUNDIR = os.path.join(EPISODE, "outputs", "runs")

MEAS0, MEAS1 = S.T_WARM, S.T_END_FLOW                    # measurement window
LC_DURATION = 2.0        # s; see FINDINGS -- lane-change duration is the single most
                         # consequential SUMO parameter for a weaving-capacity study
TTT = 900                # --time-to-teleport.  NOT -1: with teleporting fully disabled a
                         # severely oversaturated run of this network deadlocks and never
                         # terminates (verified -- it hung a 10 min budget).  900 s is long
                         # enough that ordinary heavy queueing is never teleported away,
                         # while still breaking a genuine deadlock.  Teleports are counted
                         # and reported per run so their influence stays auditable.
RUN_TIMEOUT = 900        # hard wall-clock limit per run


def run_one(job):
    variant, scale, seed, keep, lcdur, tag = job
    rd = os.path.join(RUNDIR, variant, "%s_s%.2f_seed%d" % (tag, scale, seed))
    os.makedirs(rd, exist_ok=True)
    tmpl = open(os.path.join(DEMDIR, variant, "detectors.add.template.xml")).read()
    with open(os.path.join(rd, "detectors.add.xml"), "w") as fh:
        fh.write(tmpl % {"out": "det"})       # relative -> lands next to the add file
    cmd = ["sumo",
           "-n", os.path.join(NETDIR, variant, "%s.net.xml" % variant),
           "-r", os.path.join(DEMDIR, variant, "demand_%s_%.2f.rou.xml" % (variant, scale)),
           "-a", os.path.join(rd, "detectors.add.xml"),
           "--tripinfo-output", os.path.join(rd, "tripinfo.xml"),
           "--summary-output", os.path.join(rd, "summary.xml"),
           "--statistic-output", os.path.join(rd, "stats.xml"),
           "--duration-log.statistics", "true",
           "--end", str(S.T_END),
           "--seed", str(seed),
           "--lanechange.duration", str(lcdur),
           "--time-to-teleport", str(TTT),
           "--no-step-log", "true",
           "--xml-validation", "never",
           "--eager-insert", "false",
           "--default.action-step-length", "1.0"]
    if keep:
        cmd += ["--lanechange-output", os.path.join(rd, "lanechanges.xml")]
    with open(os.path.join(rd, "sumo.log"), "w") as fh:
        try:
            r = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, timeout=RUN_TIMEOUT)
            rc = r.returncode
        except subprocess.TimeoutExpired:
            fh.write("\n*** RUN EXCEEDED %ds WALL LIMIT AND WAS KILLED ***\n" % RUN_TIMEOUT)
            rc = "timeout"
    m = aggregate(rd, variant, scale, seed, lcdur, tag)
    m["sumo_rc"] = rc
    with open(os.path.join(rd, "metrics.json"), "w") as fh:
        json.dump(m, fh, indent=1)
    if not keep:
        for f in ("tripinfo.xml", "det_e1.xml", "det_e2.xml", "det_edge.xml"):
            p = os.path.join(rd, f)
            if os.path.exists(p):
                os.remove(p)
    return m


# --------------------------------------------------------------------- aggregation
def aggregate(rd, variant, scale, seed, lcdur, tag):
    m = dict(variant=variant, scale=scale, seed=seed, lc_duration=lcdur, tag=tag,
             demand_total_vph=round(S.summary_total() * scale, 1))

    # ---- statistic-output: loaded / inserted / arrived, teleports, collisions
    sp = os.path.join(rd, "stats.xml")
    if os.path.exists(sp):
        root = ET.parse(sp).getroot()
        veh = root.find("vehicles")
        tel = root.find("teleports")
        saf = root.find("safety")
        pf = root.find("vehicleTripStatistics")
        m["loaded"] = int(veh.get("loaded")) if veh is not None else None
        m["inserted"] = int(veh.get("inserted")) if veh is not None else None
        m["running"] = int(veh.get("running")) if veh is not None else None
        m["waiting"] = int(veh.get("waiting")) if veh is not None else None
        m["teleports"] = int(tel.get("total")) if tel is not None else 0
        m["teleports_jam"] = int(tel.get("jam")) if tel is not None else 0
        m["collisions"] = int(saf.get("collisions")) if saf is not None else 0
        if pf is not None:
            m["mean_duration_s"] = float(pf.get("duration"))
            m["mean_timeloss_s"] = float(pf.get("timeLoss"))
            m["mean_waiting_s"] = float(pf.get("waitingTime"))
            m["mean_route_length_m"] = float(pf.get("routeLength"))
    m["not_inserted"] = (m.get("loaded", 0) or 0) - (m.get("inserted", 0) or 0)

    # ---- summary: arrivals inside the measurement window (network throughput)
    arrived0 = arrived1 = None
    tel_series = []
    for st in ET.parse(os.path.join(rd, "summary.xml")).getroot().iter("step"):
        t = float(st.get("time"))
        if abs(t - MEAS0) < 0.51:
            arrived0 = int(st.get("ended", st.get("arrived")))
        if abs(t - MEAS1) < 0.51:
            arrived1 = int(st.get("ended", st.get("arrived")))
        tel_series.append(int(st.get("teleports")))
    if arrived0 is not None and arrived1 is not None:
        m["network_throughput_vph"] = round((arrived1 - arrived0) / (MEAS1 - MEAS0) * 3600.0, 1)
    m["teleports_summary_last"] = tel_series[-1] if tel_series else 0

    # ---- E1 chain
    e1 = os.path.join(rd, "det_e1.xml")
    if os.path.exists(e1):
        st = {}
        for iv in ET.parse(e1).getroot().iter("interval"):
            t0 = float(iv.get("begin"))
            if not (MEAS0 <= t0 < MEAS1):
                continue
            did = iv.get("id")           # e1_EB_+0020_l2
            _, cw, pos, lane = did.split("_")
            key = (cw, int(pos))
            n = float(iv.get("nVehContrib"))
            v = float(iv.get("harmonicMeanSpeed"))
            occ = float(iv.get("occupancy"))
            d = st.setdefault(key, dict(n=0.0, inv=0.0, occ=0.0, nlane=set(), niv=0))
            d["n"] += n
            if v > 0:
                d["inv"] += n / v
            d["occ"] += occ
            d["nlane"].add(lane)
            d["niv"] += 1
        prof = {}
        dur = MEAS1 - MEAS0
        for (cw, pos), d in st.items():
            nl = len(d["nlane"])
            q = d["n"] / dur * 3600.0
            v = (d["n"] / d["inv"]) if d["inv"] > 0 else 0.0
            prof.setdefault(cw, {})[pos] = dict(
                q_vph=round(q, 1), q_vph_lane=round(q / nl, 1),
                v_ms=round(v, 2), occ_pct=round(d["occ"] / d["niv"], 2),
                k_veh_km=round(q / v / nl, 2) if v > 0.5 else None, lanes=nl)
        m["e1_profile"] = prof
        for cw in prof:
            far = max(prof[cw]); near = min(prof[cw])
            m["q_out_%s_vph" % cw] = prof[cw][far]["q_vph"]
            m["q_in_%s_vph" % cw] = prof[cw][near]["q_vph"]

    # ---- E2 detectors
    e2 = os.path.join(rd, "det_e2.xml")
    if os.path.exists(e2):
        agg = {}
        for iv in ET.parse(e2).getroot().iter("interval"):
            t0 = float(iv.get("begin"))
            if not (MEAS0 <= t0 < MEAS1):
                continue
            did = iv.get("id")                      # e2_weaveEB_l0
            grp = did.rsplit("_l", 1)[0]
            lane = int(did.rsplit("_l", 1)[1])
            n = float(iv.get("nVehSeen"))
            d = agg.setdefault(grp, dict(n=0.0, inv=0.0, occ=0.0, niv=0,
                                         jam_max=0.0, jam_sum=0.0, lanes=set(),
                                         per_lane={}, ivjam=[]))
            v = float(iv.get("meanSpeed"))
            d["n"] += n
            if v > 0:
                d["inv"] += n / v
            d["occ"] += float(iv.get("meanOccupancy"))
            d["niv"] += 1
            d["lanes"].add(lane)
            jm = float(iv.get("maxJamLengthInMeters"))
            d["jam_max"] = max(d["jam_max"], jm)
            d["jam_sum"] += jm
            d["ivjam"].append((t0, jm))
            pl = d["per_lane"].setdefault(lane, dict(jam_max=0.0, occ=0.0, niv=0,
                                                     n=0.0, inv=0.0))
            pl["jam_max"] = max(pl["jam_max"], jm)
            pl["occ"] += float(iv.get("meanOccupancy"))
            pl["n"] += n
            if v > 0:
                pl["inv"] += n / v
            pl["niv"] += 1
        meta = json.load(open(os.path.join(DEMDIR, variant, "e2_meta.json")))
        out = {}
        for grp, d in agg.items():
            nl = len(d["lanes"])
            L = meta.get(grp, {}).get("length_m")
            # SPILLBACK definition (used identically everywhere in this study):
            # the fraction of 60 s intervals in the measurement window in which the
            # queue on the WORST lane of this section reaches >=85% of the section's
            # length -- i.e. the queue has run out of storage and is discharging into
            # whatever lies upstream.  Worst-of-lanes (not per-lane average) because a
            # queue filling ANY lane is enough to obstruct the upstream junction.
            sb = None
            if L:
                worst = {}
                for iv_t, jm in d["ivjam"]:
                    worst[iv_t] = max(worst.get(iv_t, 0.0), jm)
                if worst:
                    sb = round(sum(1 for j in worst.values() if j >= 0.85 * L)
                               / len(worst), 3)
            out[grp] = dict(
                mean_speed_ms=round(d["n"] / d["inv"], 2) if d["inv"] > 0 else 0.0,
                mean_occupancy_pct=round(d["occ"] / d["niv"], 2),
                max_jam_len_m=round(d["jam_max"], 1),
                mean_jam_len_m=round(d["jam_sum"] / d["niv"], 1),
                section_length_m=L, lanes=nl, spillback_fraction=sb,
                per_lane_max_jam_m={k: round(v["jam_max"], 1)
                                    for k, v in sorted(d["per_lane"].items())},
                per_lane_speed_ms={k: (round(v["n"] / v["inv"], 2) if v["inv"] > 0 else 0.0)
                                   for k, v in sorted(d["per_lane"].items())},
                per_lane_occ_pct={k: round(v["occ"] / v["niv"], 2)
                                  for k, v in sorted(d["per_lane"].items())})
        m["e2"] = out

    # ---- tripinfo -> per-movement OD travel time
    tp = os.path.join(rd, "tripinfo.xml")
    if os.path.exists(tp):
        mv = {}
        for ti in ET.parse(tp).getroot().iter("tripinfo"):
            vid = ti.get("id")                        # f_A-West__B-North.123
            mid = vid.split(".")[0][2:].replace("__", "|", 1)
            dep = float(ti.get("depart"))
            if not (MEAS0 <= dep < MEAS1):
                continue
            d = mv.setdefault(mid, dict(n=0, dur=0.0, tl=0.0, rl=0.0, dd=0.0))
            d["n"] += 1
            d["dur"] += float(ti.get("duration"))
            d["tl"] += float(ti.get("timeLoss"))
            d["rl"] += float(ti.get("routeLength"))
            d["dd"] += float(ti.get("departDelay"))
        m["movement"] = {k: dict(n=v["n"],
                                 mean_duration_s=round(v["dur"] / v["n"], 2),
                                 mean_timeloss_s=round(v["tl"] / v["n"], 2),
                                 mean_route_len_m=round(v["rl"] / v["n"], 1),
                                 mean_depart_delay_s=round(v["dd"] / v["n"], 2))
                         for k, v in sorted(mv.items()) if v["n"]}
    return m


def _total():
    return sum(sum(r.values()) for r in S.OD.values())


S.summary_total = _total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", nargs="*", default=S.VARIANTS)
    ap.add_argument("--scales", nargs="*", type=float, default=S.SCALES)
    ap.add_argument("--seeds", nargs="*", type=int, default=S.SEEDS)
    ap.add_argument("--lcdur", type=float, default=LC_DURATION)
    ap.add_argument("--tag", default="base")
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()

    jobs = [(v, sc, sd, sd == a.seeds[0], a.lcdur, a.tag)
            for v in a.variants for sc in a.scales for sd in a.seeds]
    print("running %d jobs on %d workers (tag=%s, lanechange.duration=%.1f)"
          % (len(jobs), a.workers, a.tag, a.lcdur))
    res = []
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        for m in ex.map(run_one, jobs):
            res.append(m)
            print("  %-8s scale=%.2f seed=%2d  net_thru=%7.0f vph  q_out_EB=%7.0f  "
                  "notins=%5d  tel=%3d  meanTL=%6.1f s"
                  % (m["variant"], m["scale"], m["seed"],
                     m.get("network_throughput_vph", -1), m.get("q_out_EB_vph", -1),
                     m.get("not_inserted", -1), m.get("teleports", -1),
                     m.get("mean_timeloss_s", -1)))
    outp = os.path.join(EPISODE, "outputs", "tables", "sweep_%s.json" % a.tag)
    with open(outp, "w") as fh:
        json.dump(res, fh, indent=1)
    print("->", outp)


if __name__ == "__main__":
    main()
