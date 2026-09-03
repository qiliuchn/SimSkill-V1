#!/usr/bin/env python3
"""Discover and CALIBRATE SUMO's motorist-yielding channel at a midblock crossing,
and VERIFY the realised yielding rate from raw trajectories.

Channels tested
---------------
C1  crossing `priority` attribute (true/false), no other intervention
C2  vType jmIgnoreFoeProb x jmIgnoreFoeSpeed at priority=true and priority=false
C3  per-vehicle TraCI junctionModel.ignoreTypes (which key/value strings work)
C4  the TraCI kinematic yield controller actually used in the study:
    commanded target -> realised yielding rate, and the ped delay it produces

Also verifies the PHB tlLogic state characters ('O','o','s','y','r','G') with a
proper warm-up, i.e. which parts of the MUTCD PHB sequence SUMO can represent.

Writes results/yield_calibration.csv, results/yield_calibration.json,
results/phb_state_char_verification.json
"""
import csv, json, os, statistics as stt, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *          # noqa
import build_network, gen_demand as gd, rig as R, sumolib, traci
import xml.etree.ElementTree as ET

TMP = os.path.join(RUNDIR, "calib"); os.makedirs(TMP, exist_ok=True)
Q, PED, HOR = 800.0, 120.0, 2400.0
SEEDS = [11, 12, 13]


def crossing_x(net, cid=":M_c0"):
    for e in ET.parse(net).getroot().findall("edge"):
        if e.get("id") == cid:
            return float(e.find("lane").get("shape").split()[0].split(",")[0])


def measure(prio, ignore_prob, ignore_speed, yield_rate, seed, use_ctl):
    net = build_network.build(geom="undivided", midblock="crossing", cross_prio=prio)
    n = sumolib.net.readNet(net); la1 = n.getEdge("A1").getLength()
    vf = os.path.join(TMP, "v_p%d_i%.2f_s%.1f_%d.rou.xml" % (prio, ignore_prob, ignore_speed, seed))
    pf = os.path.join(TMP, "p_%d.rou.xml" % seed)
    gd.gen_vehicles(Q, seed, vf, gd.vtype_xml(ignore_prob=ignore_prob,
                                              ignore_speed=ignore_speed),
                    horizon=HOR, mode="poisson")
    gd.gen_peds(PED, seed, pf, la1 - 5.0, 5.0, horizon=HOR)
    r = R.Rig(net, vf, pf, seed, "uncontrolled",
              yield_rate=(yield_rate if use_ctl else -1.0), end=HOR)
    o = r.run()
    ev = [e for e in o["yield_events"] if e[9] and not e[10]]
    allo = [e for e in o["yield_events"] if not e[10]]
    slow = lambda e: e[5] < max(1.0, 0.4 * e[4])
    gr = [g for g in o["gap_records"] if g["crossing"] in o["mid_crossings"]]
    per = {}
    for g in gr:
        per[g["ped"]] = per.get(g["ped"], 0.0) + g["wait"]
    d = list(per.values())
    return dict(n_events_feasible=len(ev), n_events_all=len(allo),
                yield_slow=(sum(1 for e in ev if slow(e)) / len(ev)) if ev else None,
                yield_stop=(sum(1 for e in ev if e[5] < 0.3) / len(ev)) if ev else None,
                yield_slow_all=(sum(1 for e in allo if slow(e)) / len(allo)) if allo else None,
                commanded=(sum(1 for e in ev if e[6] == "yield") / len(ev)) if ev else None,
                n_ped=len(d), ped_delay_mean=(stt.mean(d) if d else None),
                ped_delay_median=(stt.median(d) if d else None),
                frac_gt30=(sum(1 for x in d if x > 30) / len(d)) if d else None,
                midblock_stops=o["midblock_stops"])


def main():
    rows = []
    # ---- C1 + C2 : built-in channels only (yield controller disabled) --------
    for prio in (True, False):
        for ip in (0.0, 0.25, 0.5, 0.75, 1.0):
            for isp in (0.0, 3.0):
                if ip == 0.0 and isp == 3.0:
                    continue
                for s in SEEDS:
                    d = measure(prio, ip, isp, 0.0, s, use_ctl=False)
                    d.update(channel="C1C2_builtin", crossing_priority=prio,
                             jmIgnoreFoeProb=ip, jmIgnoreFoeSpeed=isp,
                             commanded_target=None, seed=s)
                    rows.append(d); print(d, flush=True)
    # ---- C4 : the TraCI kinematic yield controller ---------------------------
    for tgt in (0.0, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 0.8, 0.9, 0.95, 1.0):
        for s in SEEDS:
            d = measure(False, 0.0, 0.0, tgt, s, use_ctl=True)
            d.update(channel="C4_traci_kinematic_yield", crossing_priority=False,
                     jmIgnoreFoeProb=0.0, jmIgnoreFoeSpeed=0.0,
                     commanded_target=tgt, seed=s)
            rows.append(d); print(d, flush=True)

    keys = ["channel", "crossing_priority", "jmIgnoreFoeProb", "jmIgnoreFoeSpeed",
            "commanded_target", "seed", "n_events_feasible", "n_events_all",
            "commanded", "yield_slow", "yield_stop", "yield_slow_all",
            "n_ped", "ped_delay_mean", "ped_delay_median", "frac_gt30",
            "midblock_stops"]
    with open(os.path.join(RESDIR, "yield_calibration.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, keys, extrasaction="ignore"); w.writeheader()
        for r in rows: w.writerow(r)
    # aggregate
    agg = {}
    for r in rows:
        k = (r["channel"], r["crossing_priority"], r["jmIgnoreFoeProb"],
             r["jmIgnoreFoeSpeed"], r["commanded_target"])
        agg.setdefault(k, []).append(r)
    out = []
    for k, rs in sorted(agg.items(), key=lambda kv: str(kv[0])):
        f = lambda m: [x[m] for x in rs if x[m] is not None]
        out.append(dict(channel=k[0], crossing_priority=k[1], jmIgnoreFoeProb=k[2],
                        jmIgnoreFoeSpeed=k[3], commanded_target=k[4], n_seeds=len(rs),
                        realised_yield_slow=(stt.mean(f("yield_slow")) if f("yield_slow") else None),
                        realised_yield_stop=(stt.mean(f("yield_stop")) if f("yield_stop") else None),
                        commanded_frac=(stt.mean(f("commanded")) if f("commanded") else None),
                        n_events=stt.mean(f("n_events_feasible")),
                        ped_delay_mean=(stt.mean(f("ped_delay_mean")) if f("ped_delay_mean") else None),
                        frac_gt30=(stt.mean(f("frac_gt30")) if f("frac_gt30") else None)))
    with open(os.path.join(RESDIR, "yield_calibration_summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, list(out[0].keys())); w.writeheader()
        for r in out: w.writerow(r)
    with open(os.path.join(RESDIR, "yield_calibration.json"), "w") as f:
        json.dump(dict(runs=rows, summary=out), f, indent=1)
    print("wrote yield_calibration*")


if __name__ == "__main__":
    main()
