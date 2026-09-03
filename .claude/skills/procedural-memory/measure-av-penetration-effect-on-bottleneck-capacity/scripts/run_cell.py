#!/usr/bin/env python3
"""Run ONE simulation cell and write its compacted metrics to <rundir>/metrics.json.

Each cell gets its OWN directory containing its OWN additional file, so the
detector/edgeData output paths (which resolve relative to the additional file's
directory) can never collide between parallel replications.
"""
import os
import sys
import json
import time
import shutil
import subprocess
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scenario as S  # noqa: E402

ROOT = os.path.dirname(HERE)
NET = os.path.join(ROOT, "net", "bneck.net.xml")
SUMO = shutil.which("sumo") or "sumo"


def build_cell(rundir, av_type, p, seed, arrangement="random", demand_mode="explicit",
               fcd=False, block=24, net=NET):
    os.makedirs(rundir, exist_ok=True)
    add = os.path.join(rundir, "add.xml")
    with open(add, "w") as f:
        f.write(S.additional_xml())
    rou = os.path.join(rundir, "routes.rou.xml")
    if demand_mode == "explicit":
        n, n_av = S.write_routes(rou, seed, av_type, p, arrangement, block)
    else:
        S.write_routes_vtypedist(rou, av_type, p)
        n, n_av = -1, -1
    extra = ""
    if fcd:
        extra = ("    <output>\n"
                 '        <fcd-output value="fcd.xml.gz"/>\n'
                 '        <device.fcd.period value="5.0"/>\n'
                 '        <fcd-output.max-leader-distance value="120.0"/>\n'
                 "    </output>\n")
    cfg = os.path.join(rundir, "run.sumocfg")
    with open(cfg, "w") as f:
        f.write(S.sumocfg_xml(net, "routes.rou.xml", "add.xml", extra))
    return cfg, n, n_av


def run(rundir, cfg, seed=1, timeout=1500):
    t0 = time.time()
    cmd = [SUMO, "-c", "run.sumocfg",
           "--tripinfo-output", "tripinfo.xml",
           "--summary-output", "summary.xml",
           "--statistic-output", "stats.xml",
           "--seed", str(seed)]
    pr = subprocess.run(cmd, cwd=rundir, capture_output=True, text=True, timeout=timeout)
    with open(os.path.join(rundir, "sumo.stderr"), "w") as f:
        f.write(pr.stderr or "")
    return pr.returncode, time.time() - t0, (pr.stderr or "")


# ---------------------------------------------------------------- parsing ----
def parse_e1(path):
    """-> {det_id: [(begin,end,nVehContrib,speed,occupancy), ...]}"""
    out = {}
    if not os.path.exists(path):
        return out
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag != "interval":
            continue
        out.setdefault(el.get("id"), []).append((
            float(el.get("begin")), float(el.get("end")),
            float(el.get("nVehContrib")), float(el.get("speed")),
            float(el.get("occupancy")), float(el.get("harmonicMeanSpeed", -1))))
        el.clear()
    return out


def group_flow(e1, prefix, nlanes):
    """Sum nVehContrib across lanes -> per-interval (t, veh/h total, mean speed)."""
    ids = [k for k in e1 if k.startswith(prefix)]
    if not ids:
        return []
    n = len(e1[ids[0]])
    rows = []
    for i in range(n):
        t = e1[ids[0]][i][0]
        dt = e1[ids[0]][i][1] - t
        cnt = sum(e1[k][i][2] for k in ids)
        sp = [e1[k][i][3] for k in ids if e1[k][i][3] >= 0 and e1[k][i][2] > 0]
        rows.append((t, cnt * 3600.0 / dt, (sum(sp) / len(sp)) if sp else -1.0))
    return rows


def parse_tripinfo(path):
    n, dur, tl, dd, byt = 0, 0.0, 0.0, 0.0, {}
    if not os.path.exists(path):
        return dict(n=0)
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag != "tripinfo":
            el.clear()
            continue
        n += 1
        dur += float(el.get("duration"))
        tl += float(el.get("timeLoss"))
        dd += float(el.get("departDelay"))
        vt = el.get("vType")
        byt[vt] = byt.get(vt, 0) + 1
        el.clear()
    if n == 0:
        return dict(n=0)
    return dict(n=n, mean_duration=dur / n, mean_timeloss=tl / n,
                mean_departdelay=dd / n, by_type=byt)


def parse_summary(path):
    rows = []
    if not os.path.exists(path):
        return rows
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag != "step":
            el.clear()
            continue
        rows.append((float(el.get("time")), int(el.get("running")),
                     float(el.get("meanSpeed", -1)), int(el.get("halting", 0)),
                     int(el.get("inserted", 0)), int(el.get("ended", 0))))
        el.clear()
    return rows


def parse_e2_maxjam(path):
    """max jam length (m) summed over the 3 approach lanes, per interval."""
    per = {}
    if not os.path.exists(path):
        return []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag != "interval":
            el.clear()
            continue
        t = float(el.get("begin"))
        per.setdefault(t, 0.0)
        per[t] += float(el.get("maxJamLengthInMeters", 0))
        el.clear()
    return sorted(per.items())



AV_TYPES = {"ACC", "CACC", "CACC_TIGHT", "HUMAN_FAST"}


def leader_stats(rundir, av_type, t_min=1200.0, max_gap=120.0):
    """From FCD (with --fcd-output.max-leader-distance), measure DIRECTLY the
    fraction of AV vehicles whose immediate leader is also an AV.

    Restricted to the last 1000 m of the approach plus the bottleneck section,
    i.e. exactly where the capacity-determining car-following happens, and to
    t >= t_min so the measurement is taken in the congested/discharge regime.
    NOTHING here assumes p or p-squared; leaders come from SUMO's own query."""
    import gzip
    path = os.path.join(rundir, "fcd.xml.gz")
    if not os.path.exists(path):
        return {}
    n_av = n_av_led_av = 0
    n_all = n_all_led_av = 0
    n_hv = n_hv_led_av = 0
    gaps_av_av, gaps_av_hv = [], []
    tg_av_av, tg_av_hv = [], []   # TIME gaps: gap/speed, the speed-invariant quantity
    fh = gzip.open(path, "rb")
    for _, el in ET.iterparse(fh, events=("end",)):
        if el.tag != "timestep":
            continue
        t = float(el.get("time"))
        if t < t_min:
            el.clear()
            continue
        vehs = el.findall("vehicle")
        types = {v.get("id"): v.get("type") for v in vehs}
        for v in vehs:
            lane = v.get("lane", "")
            pos = float(v.get("pos", 0))
            in_zone = (lane.startswith("E_app_") and pos >= 1496.0) or lane.startswith("E_bn_")
            if not in_zone:
                continue
            lid = v.get("leaderID", "")
            if not lid or lid not in types:
                continue
            g = float(v.get("leaderGap", -1))
            if g < 0 or g > max_gap:
                continue
            ego_av = v.get("type") in AV_TYPES
            led_av = types[lid] in AV_TYPES
            sp = float(v.get("speed", 0))
            n_all += 1
            n_all_led_av += led_av
            if ego_av:
                n_av += 1
                n_av_led_av += led_av
                (gaps_av_av if led_av else gaps_av_hv).append(g)
                if sp > 2.0:
                    (tg_av_av if led_av else tg_av_hv).append(g / sp)
            else:
                n_hv += 1
                n_hv_led_av += led_av
        el.clear()
    fh.close()
    if n_all == 0:
        return {}
    import statistics as st
    return dict(
        n_obs=n_all,
        realized_av_share_obs=n_av / n_all,
        # THE quantity of interest: P(leader is AV | ego is AV)
        p_leader_av_given_av=(n_av_led_av / n_av) if n_av else None,
        p_leader_av_given_hv=(n_hv_led_av / n_hv) if n_hv else None,
        p_leader_av_overall=n_all_led_av / n_all,
        mean_gap_av_behind_av=(st.mean(gaps_av_av) if gaps_av_av else None),
        mean_gap_av_behind_hv=(st.mean(gaps_av_hv) if gaps_av_hv else None),
        # time gaps are what the car-following model actually controls, and unlike
        # distance gaps they are comparable across different local speeds
        mean_timegap_av_behind_av=(st.median(tg_av_av) if tg_av_av else None),
        mean_timegap_av_behind_hv=(st.median(tg_av_hv) if tg_av_hv else None),
        n_timegap_av_av=len(tg_av_av), n_timegap_av_hv=len(tg_av_hv),
        n_av_behind_av=len(gaps_av_av), n_av_behind_hv=len(gaps_av_hv))


def compact(rundir, meta):
    e1 = parse_e1(os.path.join(rundir, "e1_bn.xml"))
    bn = group_flow(e1, "e1_bn", 2)
    dn = group_flow(parse_e1(os.path.join(rundir, "e1_dn.xml")), "e1_dn", 2)
    src = group_flow(parse_e1(os.path.join(rundir, "e1_src.xml")), "e1_src", 3)
    app = parse_e1(os.path.join(rundir, "e1_app.xml"))
    fd = {}
    for pos, tag in S.FD_POSITIONS:
        ids = [k for k in app if k.startswith("e1_app_%s_" % tag)]
        rows = []
        if ids:
            n = len(app[ids[0]])
            for i in range(n):
                t = app[ids[0]][i][0]
                dt = app[ids[0]][i][1] - t
                cnt = sum(app[k][i][2] for k in ids)
                # space-mean speed via harmonic mean, weighted by counts
                num = sum(app[k][i][2] for k in ids)
                den = sum(app[k][i][2] / app[k][i][5] for k in ids
                          if app[k][i][2] > 0 and app[k][i][5] > 0)
                v = (num / den) if den > 0 else -1.0
                q = cnt * 3600.0 / dt          # veh/h total over 3 lanes
                k_ = (q / 3.0) / (v * 3.6) if v > 0 else -1.0   # veh/km/lane
                rows.append((t, q, v, k_))
        fd[tag] = rows
    tri = parse_tripinfo(os.path.join(rundir, "tripinfo.xml"))
    summ = parse_summary(os.path.join(rundir, "summary.xml"))
    jam = parse_e2_maxjam(os.path.join(rundir, "e2_app.xml"))
    err = ""
    p = os.path.join(rundir, "sumo.stderr")
    if os.path.exists(p):
        err = open(p).read()[:4000]
    lead = leader_stats(rundir, meta.get("av_type", "ACC"))
    out = dict(meta=meta, bn_flow=bn, dn_flow=dn, src_flow=src, fd=fd, leader=lead,
               tripinfo=tri, summary=summ[::10], jam=jam,
               collisions=err.lower().count("collision"), stderr_head=err[:1500])
    with open(os.path.join(rundir, "metrics.json"), "w") as f:
        json.dump(out, f)
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--rundir", required=True)
    ap.add_argument("--av-type", default="ACC")
    ap.add_argument("--p", type=float, default=0.0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--arrangement", default="random")
    ap.add_argument("--demand-mode", default="explicit")
    ap.add_argument("--fcd", action="store_true")
    ap.add_argument("--block", type=int, default=24)
    ap.add_argument("--cell", default="")
    ap.add_argument("--keep-raw", action="store_true")
    ap.add_argument("--net", default=NET)
    a = ap.parse_args()

    cfg, n, n_av = build_cell(a.rundir, a.av_type, a.p, a.seed, a.arrangement,
                              a.demand_mode, a.fcd, a.block, a.net)
    rc, wall, err = run(a.rundir, cfg, a.seed)
    meta = dict(cell=a.cell, av_type=a.av_type, p=a.p, seed=a.seed,
                arrangement=a.arrangement, demand_mode=a.demand_mode,
                net=os.path.basename(a.net),
                n_veh_planned=n, n_av_planned=n_av, rc=rc, wall_s=round(wall, 1))
    if rc != 0:
        meta["error"] = err[-2000:]
        with open(os.path.join(a.rundir, "metrics.json"), "w") as f:
            json.dump(dict(meta=meta), f)
        print("FAIL", a.cell, a.seed, err[-500:])
        return 1
    compact(a.rundir, meta)
    # bulk raw traces stay in the attempt working dir; drop the biggest ones unless asked
    if a.fcd and not a.keep_raw:
        fp = os.path.join(a.rundir, "fcd.xml.gz")
        if os.path.exists(fp):
            os.remove(fp)          # leader stats already extracted into metrics.json
    if not a.keep_raw:
        for f in ["tripinfo.xml", "summary.xml"]:
            p = os.path.join(a.rundir, f)
            if os.path.exists(p) and os.path.getsize(p) > 8_000_000:
                os.remove(p)
    print("OK", a.cell, "seed", a.seed, "wall %.0fs" % wall)
    return 0


if __name__ == "__main__":
    sys.exit(main())
