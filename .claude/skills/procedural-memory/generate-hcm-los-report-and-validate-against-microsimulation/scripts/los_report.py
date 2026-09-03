#!/usr/bin/env python3
"""
los_report.py - turn ANY SUMO signalized-intersection run into a standard
engineering HCM-style Level-of-Service report.

Produces, per approach and per lane group:
    volume (veh/h) | v/c | control delay (s/veh) | LOS | 95th-%ile queue (veh/ln)
for BOTH the HCM 6th Ed. Chapter 19 analytical model and the microsimulation,
plus the volume-weighted intersection-aggregate delay and LOS.

It also reports the three competing delay definitions side by side
    (a) tripinfo timeLoss           (SUMO native, whole trip, lane-limit datum)
    (b) tripinfo waitingTime        (stopped delay)
    (c) HCM control delay           (measured segment travel time - free flow)
and quantifies the residual-queue truncation bias.

Required run artefacts (see scenario.write_detectors):
    segment.xml   entry/exit instantInductionLoop pairs bracketing the
                  intersection influence area
    queue.xml     laneAreaDetector chains, one per lane
    tlsswitch.xml SaveTLSSwitchStates log
    tripinfo.xml, summary.xml

Usage:
    python3 los_report.py --run <dir> --config <sweep_config.json> \
        --control pretimed --begin 0 --end 3600 [--md out.md] [--json out.json]
"""
import os, sys, json, math, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hcm_lib as H
import scenario as S

APPROACHES = ["N", "E", "S", "W"]
LG_OF_MOVE = {"L": "L", "T": "TR", "R": "TR"}
PHASE_OF_LG = {("N", "L"): "NSL", ("S", "L"): "NSL", ("E", "L"): "EWL", ("W", "L"): "EWL",
               ("N", "TR"): "NST", ("S", "TR"): "NST", ("E", "TR"): "EWT", ("W", "TR"): "EWT"}
NLANES = {"L": 1, "TR": 2}


# ---------------------------------------------------------------- measurement

def segment_records(run):
    """{(approach, movement): [(veh, t_entry, t_exit)]} from the paired
    entry/exit instant loops.  Movement is read off the flow id."""
    ev = H.parse_instant(os.path.join(run, "segment.xml"))
    ent, ext = {}, {}
    for det, t, st, veh in ev:
        if st != "enter":
            continue
        if det.startswith("en_"):
            if veh not in ent or t < ent[veh]:
                ent[veh] = t
        elif det.startswith("ex_"):
            if veh not in ext or t < ext[veh]:
                ext[veh] = t
    out = {}
    for veh, t0 in ent.items():
        tag = veh.split(".")[0]
        out.setdefault((tag[2], tag[3]), []).append((veh, t0, ext.get(veh)))
    return out


def tripinfo_by_movement(run):
    out = {}
    for r in H.parse_tripinfo(os.path.join(run, "tripinfo.xml")):
        tag = r["id"].split(".")[0]
        out.setdefault((tag[2], tag[3]), []).append(r)
    return out


def signal_timing(run, t0, t1):
    """Measured mean green per phase and mean cycle length inside [t0,t1]."""
    sw = H.parse_tls_switch(os.path.join(run, "tlsswitch.xml"))
    g = {}
    for nm in ("NSL", "NST", "EWL", "EWT"):
        d = [b - a for n, a, b in H.phase_intervals(sw, {nm}) if t0 <= a < t1]
        g[nm] = sum(d) / len(d) if d else float("nan")
    starts = [a for n, a, b in H.phase_intervals(sw, {"NSL"}) if t0 <= a < t1]
    cyc = [starts[i] - starts[i - 1] for i in range(1, len(starts))]
    C = sum(cyc) / len(cyc) if cyc else float("nan")
    return g, C, starts


def cycle_queues(run, starts, t0, t1):
    """{detector: (max, p95, mean) of the per-cycle maximum back of queue}
    in vehicles, using the ACTUAL signal cycle boundaries (which vary under
    actuated control) rather than a fixed window."""
    e2 = H.parse_e2(os.path.join(run, "queue.xml"))
    bounds = [(starts[i], starts[i + 1]) for i in range(len(starts) - 1)]
    out = {}
    for det, rows in e2.items():
        per = []
        for a, b in bounds:
            v = [r[2] for r in rows if a <= r[0] < b]
            if v:
                per.append(max(v))
        perm = []
        for a, b in bounds:
            v = [r[3] for r in rows if a <= r[0] < b]
            if v:
                perm.append(max(v))
        if per:
            out[det] = dict(max=max(per), p95=H.percentile(per, 0.95),
                            mean=sum(per) / len(per), n_cycles=len(per),
                            max_m=max(perm), p95_m=H.percentile(perm, 0.95),
                            frac_beyond_entry=sum(1 for x in perm if x > 250.0) / len(perm))
    return out


def queue_at(run, det, t):
    e2 = H.parse_e2(os.path.join(run, "queue.xml"))
    rows = [r for r in e2.get(det, []) if r[0] <= t]
    return rows[-1][2] if rows else 0


# ------------------------------------------------------------------ reporting

def build(run, cfg, control, t0, t1, truncate_at=None, Qb_map=None):
    """Core analysis.  truncate_at: if set, discard vehicles that had not yet
    left the segment by that time (emulates a run that simply stopped there)."""
    cal, cap = cfg["cal"], cfg["cap"]
    T_h = (t1 - t0) / 3600.0
    segs = segment_records(run)
    trips = tripinfo_by_movement(run)
    g_meas, C_meas, starts = signal_timing(run, t0, t1)
    qs = cycle_queues(run, starts, t0, t1)
    ff = cal["ff"]

    rows, drops = [], {}
    for a in APPROACHES:
        for lg in ("L", "TR"):
            moves = ["L"] if lg == "L" else ["T", "R"]
            # --- demand volume: scheduled departures inside the period -------
            n_dem = 0
            tl, wt, wtrip = [], [], []
            for m in moves:
                fftrip = cal.get("ff_trip", {}).get(a + m)
                for r in trips.get((a, m), []):
                    if t0 <= r["depart"] - r["departDelay"] < t1:
                        n_dem += 1
                        tl.append(r["timeLoss"])
                        wt.append(r["waitingTime"])
                        if fftrip:
                            # whole-trip delay: includes the queue upstream of the
                            # 250 m HCM reference point AND any insertion backlog
                            wtrip.append(r["arrival"] - (r["depart"] - r["departDelay"]) - fftrip)
            v = n_dem / T_h
            # --- control delay over the measured segment ---------------------
            cd, cd_all, n_drop = [], [], 0
            for m in moves:
                fftt = ff[a + m]
                for veh, te, tx in segs.get((a, m), []):
                    if not (t0 <= te < t1):
                        continue
                    if tx is None:
                        n_drop += 1
                        continue
                    cd_all.append(tx - te - fftt)
                    if truncate_at is not None and tx > truncate_at:
                        n_drop += 1
                        continue
                    cd.append(tx - te - fftt)
            drops[(a, lg)] = n_drop
            # --- HCM prediction ---------------------------------------------
            ph = PHASE_OF_LG[(a, lg)]
            tL = cal["tL_LT"] if lg == "L" else cal["tL_TR"]
            s = cal["s_LT"] if lg == "L" else cal["s_TR_per_lane"]
            if control == "pretimed":
                G, C = cfg["OP_GREEN"][ph], cfg["CYCLE"]
            else:
                G, C = g_meas[ph], C_meas
            g = G - tL
            Qb = (Qb_map or {}).get((a, lg), 0.0)
            hcm = H.lane_group(v, s, NLANES[lg], g, C, T_h, control, Qb=Qb,
                               PF=1.0, I=1.0, unit_extension=S.MAX_GAP,
                               label=f"{a}-{lg}")
            # --- simulated queue --------------------------------------------
            if lg == "L":
                qd = [f"q_{a}_Lall"]
            else:
                qd = [f"q_{a}_T0", f"q_{a}_T1"]
            have = [d for d in qd if d in qs]
            qmax = max((qs[d]["max"] for d in have), default=float("nan"))
            q95 = sum(qs[d]["p95"] for d in have) / max(1, len(have))
            q95_m = max((qs[d]["p95_m"] for d in have), default=float("nan"))
            qmax_m = max((qs[d]["max_m"] for d in have), default=float("nan"))
            fbe = max((qs[d]["frac_beyond_entry"] for d in have), default=float("nan"))
            rows.append(dict(
                approach=a, lane_group=lg, v=v, n=len(cd),
                sim_control_delay=(sum(cd) / len(cd)) if cd else float("nan"),
                sim_control_delay_full=(sum(cd_all) / len(cd_all)) if cd_all else float("nan"),
                sim_timeLoss=(sum(tl) / len(tl)) if tl else float("nan"),
                sim_p95_delay=H.percentile(cd, 0.95) if cd else float("nan"),
                dropped=n_drop,
                sim_waitingTime=(sum(wt) / len(wt)) if wt else float("nan"),
                sim_delay_wholetrip=(sum(wtrip) / len(wtrip)) if wtrip else float("nan"),
                sim_q95=q95, sim_qmax=qmax, sim_q95_m=q95_m, sim_qmax_m=qmax_m,
                frac_cycles_queue_beyond_entry=fbe,
                g=g, C=C, **{k: hcm[k] for k in
                             ("c", "X", "k", "d1", "d2", "d3", "delay", "los",
                              "Q_Q", "Q_Q95", "Q_Q1", "Q_Q2")}))
    for r in rows:
        r["sim_los"] = H.los_letter(r["sim_control_delay"], r["X"])
        r["sim_los_delayonly"] = H.los_letter(r["sim_control_delay"])
    agg_hcm = H.intersection_aggregate([dict(v=r["v"], delay=r["delay"]) for r in rows])
    V = sum(r["v"] for r in rows)
    agg_sim_d = sum(r["v"] * r["sim_control_delay"] for r in rows) / V
    return dict(rows=rows, control=control, t0=t0, t1=t1, T_h=T_h,
                cycle=C_meas, greens=g_meas,
                hcm_int_delay=agg_hcm["delay"], hcm_int_los=agg_hcm["los"],
                sim_int_delay=agg_sim_d, sim_int_los=H.los_letter(agg_sim_d),
                V=V)


def render_md(res, title=""):
    L = [f"# HCM Level-of-Service report {title}", "",
         f"Control: **{res['control']}**  |  analysis period "
         f"{res['t0']:.0f}-{res['t1']:.0f} s (T = {res['T_h']:.2f} h)  |  "
         f"mean cycle {res['cycle']:.1f} s", "",
         "| Appr | Lane grp | v (veh/h) | c (veh/h) | v/c | HCM d (s) | HCM LOS "
         "| Sim d (s) | Sim LOS | HCM Q95 (veh/ln) | Sim Q95 (veh/ln) |",
         "|---|---|---:|---:|---:|---:|:-:|---:|:-:|---:|---:|"]
    for r in res["rows"]:
        L.append(f"| {r['approach']} | {r['lane_group']} | {r['v']:.0f} | {r['c']:.0f} "
                 f"| {r['X']:.3f} | {r['delay']:.1f} | {r['los']} "
                 f"| {r['sim_control_delay']:.1f} | {r['sim_los']} "
                 f"| {r['Q_Q95']:.1f} | {r['sim_q95']:.1f} |")
    L += ["",
          f"**Intersection aggregate** - HCM {res['hcm_int_delay']:.1f} s/veh "
          f"(LOS {res['hcm_int_los']}) vs simulated {res['sim_int_delay']:.1f} s/veh "
          f"(LOS {res['sim_int_los']}); total volume {res['V']:.0f} veh/h.", "",
          "## Three delay definitions (s/veh)", "",
          "| Appr | Lane grp | (c) HCM control delay | (a) tripinfo timeLoss "
          "| (b) tripinfo waitingTime (stopped) | stopped/control | timeLoss/control |",
          "|---|---|---:|---:|---:|---:|---:|"]
    for r in res["rows"]:
        cd = r["sim_control_delay"]
        L.append(f"| {r['approach']} | {r['lane_group']} | {cd:.1f} | {r['sim_timeLoss']:.1f} "
                 f"| {r['sim_waitingTime']:.1f} | {r['sim_waitingTime']/cd:.3f} "
                 f"| {r['sim_timeLoss']/cd:.3f} |")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--control", required=True, choices=["pretimed", "actuated"])
    ap.add_argument("--begin", type=float, default=0.0)
    ap.add_argument("--end", type=float, default=3600.0)
    ap.add_argument("--truncate-at", type=float, default=None)
    ap.add_argument("--md"); ap.add_argument("--json")
    a = ap.parse_args()
    cfg = json.load(open(a.config))
    res = build(a.run, cfg, a.control, a.begin, a.end, a.truncate_at)
    md = render_md(res, title=os.path.basename(a.run.rstrip("/")))
    print(md)
    if a.md:
        open(a.md, "w").write(md)
    if a.json:
        json.dump(res, open(a.json, "w"), indent=2, default=str)
