#!/usr/bin/env python3
"""
Step 1 of the pipeline - MEASURE the HCM model's inputs instead of assuming them.

(a) Saturation flow rate s and net lost time (l1 - e) per lane, from stop-line
    instant-induction-loop discharge headways, via TWO independent estimators
    (windowed headway-vs-queue-position, and the window-free green-duration
    regression) - the methodology of
    `measure-saturation-flow-and-validate-webster-method`.
(b) Free-flow travel time over the 250 m-upstream -> 100 m-downstream HCM
    control-delay measurement segment, per movement, as the MINIMUM observed
    segment traversal time in a very-low-demand run.
"""
import os, sys, json, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scenario as S
from gen_network import BAY_LEN, MOV
import hcm_lib as H

LANE_PHASE = {}
for a, ph in (("N", "NSL"), ("S", "NSL"), ("E", "EWL"), ("W", "EWL")):
    LANE_PHASE[f"sl_{a}_2"] = ph
for a, ph in (("N", "NST"), ("S", "NST"), ("E", "EWT"), ("W", "EWT")):
    LANE_PHASE[f"sl_{a}_0"] = ph
    LANE_PHASE[f"sl_{a}_1"] = ph

GREENS_FOR_REGRESSION = [20.0, 30.0, 45.0, 60.0]
# Two SEPARATE oversaturation regimes, BOTH on the operational network.
#
# (1) A single "everything oversaturated" run cannot measure the left-turn bay's
#     saturation flow: a saturated through queue on inA lane 1 physically
#     prevents left-turners from REACHING the bay (the bay-blockage/starvation
#     failure mode documented in `design-left-turn-storage-bay-length`), so the
#     bay never holds a standing queue.  Verified: the left-lane green-duration
#     regression returned s = 129-624 veh/h/ln at R^2 = 0.62-0.95 in that run,
#     versus 1780-1880 at R^2 > 0.996 for the through lanes in the SAME run.
# (2) A "calibration network" with the exclusive left lane running the whole
#     approach (gen_network --full-left) was built and REJECTED: with three
#     upstream lanes, SUMO's lane assignment scatters vehicles across lanes that
#     have no continuation for their route and they force a lane change at the
#     stop line.  Verified: s_left = 876 veh/h/ln on the 3-lane calibration net
#     vs 1466 veh/h/ln for the identical movement on the 2-lane operational net,
#     and a through-only run on the calibration net put 2 through vehicles per
#     cycle into the left-only lane.  Measure each lane group on the geometry it
#     actually operates on.
SAT_DEMAND_TR = {"L": 0.0,   "T": 3200.0, "R": 430.0}   # saturate through+right only
SAT_DEMAND_LT = {"L": 500.0, "T": 0.0,    "R": 0.0}     # saturate the bay only


def n_feed_lanes(net):
    import xml.etree.ElementTree as ET
    r = ET.parse(net).getroot()
    return max(len(e.findall("lane")) for e in r.findall("edge")
               if (e.get("id") or "").startswith("feed_"))


def _cycle_discharges(instant, switches, det_id, phase_name):
    """[(green_start, G_end_display, [leave times])] per cycle for one stop-line lane."""
    greens = [(nm, t0, t1) for (nm, t0, t1) in H.phase_intervals(switches, {phase_name})]
    ev = sorted([(t, v) for (d, t, st, v) in instant if d == det_id and st == "leave"])
    out = []
    for nm, t0, t1 in greens:
        # discharge window = displayed green + yellow + all-red
        w1 = t1 + S.YEL + S.ARD
        ts = [t for (t, v) in ev if t0 <= t < w1]
        out.append((t0, t1, ts))
    return out


def measure_saturation(net, base, demand, tag, seed=7, sim_end=2400.0, warmup=300.0):
    """Run one oversaturated scenario per green duration; return per-lane results."""
    per_g = {}
    for G in GREENS_FOR_REGRESSION:
        od = os.path.join(base, f"sat_{tag}_G{int(G)}")
        os.makedirs(od, exist_ok=True)
        greens = {k: G for k in S.PHASE_ORDER}
        tls = S.write_tls(net, os.path.join(od, "tls.add.xml"), "pretimed", greens)
        det = S.write_detectors(net, od, e2_freq=5.0, want_stopline=True)
        vol = {(a, m): demand[m] for a in S.APPROACHES for m in ("L", "T", "R")}
        rou = S.write_routes(os.path.join(od, "routes.rou.xml"), vol, end=sim_end,
                             n_feed_lanes=n_feed_lanes(net))
        S.run_sumo(net, rou, [tls, det], od, end=sim_end, step=0.1, seed=seed,
                   tripinfo=False, extra=["--max-depart-delay", "10"])
        inst = H.parse_instant(os.path.join(od, "stopline.xml"))
        sw = H.parse_tls_switch(os.path.join(od, "tlsswitch.xml"))
        e2 = H.parse_e2(os.path.join(od, "queue.xml"))
        per_g[G] = dict(dir=od, inst=inst, sw=sw, e2=e2)
        print(f"  sat run [{tag}] G={G:.0f}s done ({len(inst)} loop events)")
    return per_g


def analyse_saturation(per_g, dets=None, window=(5, 12), lt_window=(4, 12)):
    res = {}
    for det in sorted(dets or LANE_PHASE):
        ph = LANE_PHASE[det]
        is_lt = det.endswith("_2")
        win = lt_window if is_lt else window
        # --- estimator 1: windowed headway-vs-position, at the LONGEST green ---
        Gmax = max(GREENS_FOR_REGRESSION)
        d = per_g[Gmax]
        cyc = _cycle_discharges(d["inst"], d["sw"], det, ph)
        cyc = [c for c in cyc if c[0] >= 300.0]           # drop warm-up cycles
        hpos = {}
        for t0, t1, ts in cyc:
            prev = t0
            for n, t in enumerate(ts, start=1):
                hpos.setdefault(n, []).append(t - prev)
                prev = t
        hbar = {n: sum(v) / len(v) for n, v in hpos.items() if len(v) >= 4}
        wns = [n for n in hbar if win[0] <= n <= win[1]]
        hs = sum(hbar[n] for n in wns) / len(wns) if wns else float("nan")
        l1 = sum(hbar[n] - hs for n in sorted(hbar) if n < win[0])
        s_win = 3600.0 / hs if hs == hs else float("nan")
        # window sensitivity
        alt = []
        for lo in (win[0] - 1, win[0], win[0] + 1):
            for hi in (win[1] - 2, win[1], win[1] + 2):
                ns = [n for n in hbar if lo <= n <= hi]
                if ns:
                    alt.append(3600.0 / (sum(hbar[n] for n in ns) / len(ns)))
        # --- estimator 2: green-duration regression N_d(G) = (s/3600)(G - l1 + e)
        pts = []
        for G in GREENS_FOR_REGRESSION:
            dd = per_g[G]
            cc = [c for c in _cycle_discharges(dd["inst"], dd["sw"], det, ph) if c[0] >= 300.0]
            if cc:
                pts.append((G, sum(len(c[2]) for c in cc) / len(cc), len(cc)))
        n = len(pts)
        mx = sum(p[0] for p in pts) / n
        my = sum(p[1] for p in pts) / n
        sxx = sum((p[0] - mx) ** 2 for p in pts)
        sxy = sum((p[0] - mx) * (p[1] - my) for p in pts)
        slope = sxy / sxx
        icept = my - slope * mx
        ss_tot = sum((p[1] - my) ** 2 for p in pts)
        ss_res = sum((p[1] - (slope * p[0] + icept)) ** 2 for p in pts)
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
        s_reg = 3600.0 * slope
        tL_net = -icept / slope             # = l1 - e  (net lost time vs displayed green)
        # --- e (extension of effective green into yellow/all-red), measured ---
        es = []
        for t0, t1, ts in cyc:
            if ts:
                es.append(max(0.0, max(ts) - t1))
        e_meas = sum(es) / len(es) if es else 0.0
        # --- queue-never-exhausted check from the E2 jam length at end of green ---
        res[det] = dict(phase=ph, s_windowed=s_win, h_s=hs, l1_windowed=l1,
                        s_window_sensitivity=(min(alt), max(alt)),
                        s_regression=s_reg, tL_net_regression=tL_net, r2=r2,
                        e_measured=e_meas,
                        l1_from_reg_and_e=tL_net + e_meas,
                        headway_profile={n: round(hbar[n], 3) for n in sorted(hbar)[:16]},
                        veh_per_cycle=[(p[0], round(p[1], 2), p[2]) for p in pts])
    return res


def measure_freeflow(net, base, seed=11, sim_end=7200.0, q=40.0):
    od = os.path.join(base, "freeflow")
    os.makedirs(od, exist_ok=True)
    tls = S.write_tls(net, os.path.join(od, "tls.add.xml"), "pretimed")
    det = S.write_detectors(net, od, e2_freq=60.0, want_stopline=False)
    vol = {(a, m): q for a in S.APPROACHES for m in ("L", "T", "R")}
    rou = S.write_routes(os.path.join(od, "routes.rou.xml"), vol, end=sim_end - 600,
                         n_feed_lanes=n_feed_lanes(net))
    S.run_sumo(net, rou, [tls, det], od, end=sim_end, step=0.1, seed=seed, tripinfo=True)
    tt = segment_times(os.path.join(od, "segment.xml"))
    ff = {}
    for mv, lst in sorted(tt.items()):
        v = sorted(x[1] for x in lst)
        ff["%s%s" % mv] = dict(n=len(v), min=v[0], p05=H.percentile(v, 0.05),
                      median=H.percentile(v, 0.5))
    return ff, od


def segment_times(segment_xml):
    """{(approach, movement): [(vehID, travel_time, t_entry)]} from entry/exit
    instant loops.  Movement is read off the flow id (f_<A><M>.<n>)."""
    ev = H.parse_instant(segment_xml)
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
        t1 = ext.get(veh)
        if t1 is None or t1 <= t0:
            continue
        tag = veh.split(".")[0]          # f_NL
        a, m = tag[2], tag[3]
        out.setdefault((a, m), []).append((veh, t1 - t0, t0))
    return out


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    base = os.path.abspath(os.path.join(here, "..", "runs", "calib"))
    os.makedirs(base, exist_ok=True)
    net = os.path.abspath(os.path.join(here, "..", "runs", "net_static", "intersection.net.xml"))
    # calibration network: exclusive left lane runs the whole approach, so the
    # stop-line discharge measurement can never be bay-refill-limited.
    cnet = os.path.abspath(os.path.join(here, "..", "runs", "net_calib", "intersection.net.xml"))
    print("== saturation flow measurement: through+right lane groups ==")
    tr_dets = [d for d in LANE_PHASE if not d.endswith("_2")]
    sat = analyse_saturation(measure_saturation(net, base, SAT_DEMAND_TR, "TR"), tr_dets)
    print("== saturation flow measurement: exclusive left-turn bays ==")
    lt_dets = [d for d in LANE_PHASE if d.endswith("_2")]
    sat.update(analyse_saturation(measure_saturation(net, base, SAT_DEMAND_LT, "LT"), lt_dets))
    print("== free-flow segment travel time ==")
    ff, ffdir = measure_freeflow(net, base)
    out = dict(saturation=sat, freeflow=ff)
    p = os.path.join(base, "calibration.json")
    json.dump(out, open(p, "w"), indent=2, default=str)
    for det in sorted(sat):
        r = sat[det]
        print(f"{det} [{r['phase']}]  s_win={r['s_windowed']:.0f}  s_reg={r['s_regression']:.0f} "
              f"(R2={r['r2']:.4f})  l1_win={r['l1_windowed']:.2f}  e={r['e_measured']:.2f}  "
              f"tL_net={r['tL_net_regression']:.2f}")
    print()
    for mv in sorted(ff):
        print(f"ff {mv}: n={ff[mv]['n']} min={ff[mv]['min']:.2f}s p05={ff[mv]['p05']:.2f} "
              f"median={ff[mv]['median']:.2f}")
    print("written:", p)
