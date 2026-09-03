#!/usr/bin/env python3
"""Validate the Edie FCD reconstruction before trusting anything built on it.

Three independent checks per run, all on retained files:

  1. KNOWN DEMAND. In free flow every departing pedestrian traverses the section
     exactly once, so Edie flow through the section must equal the <personFlow>
     rate (within Poisson sampling error of the realised departures).
  2. INDEPENDENT COUNTING ESTIMATOR. Count boundary CROSSINGS of the section's
     mid-plane x = xc in the FCD (a "virtual induction loop" for persons) and
     divide by the window length.  This shares no arithmetic with the Edie
     space-time integral, so agreement is a real cross-check -- the pedestrian
     analogue of the MFD skill's two-independent-density-estimator rule.
  3. TRIPINFO CROSS-CHECK. Compare Edie's space-mean speed against the
     <walk routeLength>/<walk duration> ratio aggregated over <personinfo>
     entries, and compare person counts against tripinfo's completed count.
"""
import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_corridor   # noqa: E402
import edie           # noqa: E402
import build_corridor  # noqa: E402


def counting_estimator(fcd, xc, t1, t2):
    """Virtual loop at x = xc: count sign changes of (x - xc) per person."""
    last = {}
    n_fwd = n_bwd = 0
    ctx = ET.iterparse(fcd, events=("start", "end"))
    tnow = 0.0
    for ev, el in ctx:
        if ev == "start" and el.tag == "timestep":
            tnow = float(el.get("time"))
        elif ev == "end" and el.tag == "person":
            pid = el.get("id")
            x = float(el.get("x"))
            if pid in last:
                p = last[pid]
                if t1 <= tnow <= t2:
                    if p < xc <= x:
                        n_fwd += 1
                    elif x <= xc < p:
                        n_bwd += 1
            last[pid] = x
            el.clear()
        elif ev == "end" and el.tag == "timestep":
            el.clear()
    return n_fwd, n_bwd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--rates", default="0.1,0.3,0.6,1.0,1.5")
    a = ap.parse_args()
    os.makedirs(a.root, exist_ok=True)
    rows = []
    for rate in [float(r) for r in a.rates.split(",")]:
        d = os.path.join(a.root, "val_r%g" % rate)
        m = run_corridor.run(d, 2.24, rate, 1, end=1500.0, demand_end=1200.0,
                             warmup=500.0, meas_end=1200.0, x1=60.0, x2=140.0,
                             step=1.0, keep_fcd=True)
        fcd = os.path.join(d, "fcd.xml")
        info = build_corridor.verify(os.path.join(d, "corr.net.xml"),
                                     {"EA": 6.0, "EM": 2.24, "EO": 6.0})
        xc = 0.5 * (info["EM_x0"] + info["EM_x1"])
        T = 1200.0 - 500.0
        nf, nb = counting_estimator(fcd, xc, 500.0, 1200.0)
        q_count = (nf + nb) / T
        ti = m["tripinfo"]
        rows.append({
            "demand_rate_p_s": rate,
            "realised_departures": m["accounting"]["inserted"],
            "realised_rate_p_s": m["accounting"]["inserted"] / 1200.0,
            "edie_flow_p_s": m["flow_p_s"],
            "counting_flow_p_s": q_count,
            "counting_crossings": nf + nb,
            "edie_vs_demand_pct": 100 * (m["flow_p_s"] - rate) / rate,
            "edie_vs_realised_pct": 100 * (m["flow_p_s"] - m["accounting"]["inserted"] / 1200.0)
                                    / (m["accounting"]["inserted"] / 1200.0),
            "edie_vs_counting_pct": 100 * (m["flow_p_s"] - q_count) / q_count,
            "edie_speed_ms": m["speed_ms"],
            "tripinfo_whole_route_speed_ms": ti["mean_walk_speed"],
            "edie_density_p_m2": m["density_p_m2"],
            "density_from_q_over_v_p_m2": m["flow_p_s"] / m["speed_ms"] / 2.24,
            "completed_persons": ti["n_personinfo"],
            "still_walking_at_end": m["accounting"]["still_walking_at_end"],
            "jam_events_per_1000_person_seconds": m["person_summary"]["jam_events_per_1000_person_seconds"],
        })
        os.remove(fcd)
        print(json.dumps(rows[-1], indent=1), flush=True)
    json.dump({"region": "middle 80 m of the 197 m section, t in [500,1200] s",
               "rows": rows}, open(a.out_json, "w"), indent=2)


if __name__ == "__main__":
    main()
