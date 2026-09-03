#!/usr/bin/env python3
"""
Saturation-throughput probe: load every controller far past capacity and measure
the SERVED flow in a steady saturated window (arrivals per hour, from summary
output's cumulative `ended`).  This is the capacity comparison behind the
"where does signal-free AIM break" statement -- capacity is the served flow
under a standing queue, not the demand that was loaded
(`quantify-sumo-run-to-run-variability`: never measure capacity by the flow at
the highest demand tested without checking it is actually served).
"""
import os, sys, json, statistics as st, xml.etree.ElementTree as ET
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def served(d, t0=600.0, t1=1500.0):
    p = os.path.join(BASE, d, "summary.xml")
    if not os.path.exists(p):
        return None
    e0 = e1 = None
    for s in ET.parse(p).getroot().findall("step"):
        t = float(s.get("time"))
        if e0 is None and t >= t0:
            e0 = int(s.get("ended"))
        if t <= t1:
            e1 = int(s.get("ended"))
    if e0 is None or e1 is None:
        return None
    return (e1 - e0) * 3600.0 / (t1 - t0)

if __name__ == "__main__":
    arms = json.load(open(sys.argv[1]))
    out = {}
    for name, dirs in arms.items():
        v = [served(d) for d in dirs]
        v = [x for x in v if x is not None]
        if v:
            out[name] = {"mean_veh_per_h": st.mean(v), "values": v}
            print("%-14s served %.0f veh/h  %s" % (name, st.mean(v),
                                                   [round(x) for x in v]))
    json.dump(out, open(os.path.join(BASE, "analysis/capacity.json"), "w"), indent=1)
