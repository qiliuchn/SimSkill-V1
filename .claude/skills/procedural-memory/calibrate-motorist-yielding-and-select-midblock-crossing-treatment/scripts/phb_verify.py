#!/usr/bin/env python3
"""Verify what SUMO's tlLogic state characters actually DO at a midblock crossing,
i.e. which parts of the MUTCD Section 4F pedestrian-hybrid-beacon sequence SUMO
can represent -- measured, with a proper warm-up, not assumed from the docs.

For each candidate character the midblock TLS is held at that state for a fixed
window (after a warm-up) with the pedestrian crossing held GREEN so pedestrians
are genuinely present, and we count:
    veh_pass                vehicles crossing the conflict point
    veh_stop_ticks          vehicle-ticks stopped within 30 m of the crossing
    encroach_pass           vehicles crossing the point while a ped is on the crossing
    ped_cross_ticks         pedestrian-ticks on the crossing edge

A second block runs the full PHB state machine and logs the realised phase
durations plus what happens to vehicles during the 'flashing red' ('s') interval.

Writes results/phb_state_char_verification.json
"""
import json
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *  # noqa
import build_network
import gen_demand as gd
import rig as R
import sumolib
import traci

TMP = os.path.join(RUNDIR, "phbverify")
os.makedirs(TMP, exist_ok=True)
WARM = 180.0
WIN = 120.0
ORDER = ["O", "o", "s", "y", "r", "G"]


def main():
    net = build_network.build(geom="undivided", midblock="tls", cross_prio=False)
    n = sumolib.net.readNet(net)
    la1 = n.getEdge("A1").getLength()
    vf = os.path.join(TMP, "veh.rou.xml")
    pf = os.path.join(TMP, "ped.rou.xml")
    total = WARM + WIN * len(ORDER)
    gd.gen_vehicles(700, 31, vf, gd.vtype_xml(), horizon=total, mode="poisson")
    gd.gen_peds(500, 31, pf, la1 - 5.0, 5.0, horizon=total)
    xc = None
    for e in ET.parse(net).getroot().findall("edge"):
        if e.get("id") == ":M_c0":
            xc = float(e.find("lane").get("shape").split()[0].split(",")[0])

    traci.start([SUMO, "-n", net, "-r", vf + "," + pf, "--pedestrian.model", "striping",
                 "--step-length", "0.5", "--no-step-log", "true", "--no-warnings", "true",
                 "--seed", "31", "--end", str(total + 60), "--time-to-teleport", "-1"])
    links = traci.trafficlight.getControlledLinks("M")
    vi, pi = [], []
    for i, lk in enumerate(links):
        if not lk:
            continue
        frm, to, via = lk[0]
        tgt = via or to
        if ("_c" in tgt and tgt.startswith(":")) or (frm.startswith(":") and "_w" in frm):
            pi.append(i)
        else:
            vi.append(i)

    def state(vc, pc):
        s = ["r"] * len(links)
        for i in vi:
            s[i] = vc
        for i in pi:
            s[i] = pc
        return "".join(s)

    stats = {c: dict(veh_pass=0, veh_stop_ticks=0, veh_ticks_near=0,
                     encroach_pass=0, ped_cross_ticks=0, steps=0) for c in ORDER}
    prev_x = {}
    t = 0.0
    while t < total:
        if t < WARM:
            traci.trafficlight.setRedYellowGreenState("M", state("G", "r"))
            ch = None
        else:
            ch = ORDER[min(int((t - WARM) // WIN), len(ORDER) - 1)]
            traci.trafficlight.setRedYellowGreenState("M", state(ch, "G"))
        traci.simulationStep()
        t = traci.simulation.getTime()
        peds_on = traci.edge.getLastStepPersonIDs(":M_c0")
        cur = {}
        for v in traci.vehicle.getIDList():
            x, y = traci.vehicle.getPosition(v)
            cur[v] = x
            if ch is None:
                continue
            r = traci.vehicle.getRoadID(v)
            if r in ("A1", "B1") and abs(x - xc) < 30:
                stats[ch]["veh_ticks_near"] += 1
                if traci.vehicle.getSpeed(v) < 0.3:
                    stats[ch]["veh_stop_ticks"] += 1
            px = prev_x.get(v)
            if px is not None and ((px < xc <= x) or (px > xc >= x)):
                stats[ch]["veh_pass"] += 1
                if peds_on:
                    stats[ch]["encroach_pass"] += 1
        if ch is not None:
            stats[ch]["steps"] += 1
            stats[ch]["ped_cross_ticks"] += len(peds_on)
        prev_x = cur
    traci.close()

    for c, s in stats.items():
        s["flow_veh_per_h"] = s["veh_pass"] / (WIN / 3600.0)
        s["stop_frac"] = s["veh_stop_ticks"] / max(s["veh_ticks_near"], 1)
        s["encroach_frac"] = s["encroach_pass"] / max(s["veh_pass"], 1)

    # ---------- full PHB state machine: realised phase durations ----------
    net2 = build_network.build(geom="undivided", midblock="tls", cross_prio=False)
    gd.gen_vehicles(900, 41, vf, gd.vtype_xml(), horizon=1800, mode="poisson")
    gd.gen_peds(80, 41, pf, la1 - 5.0, 5.0, horizon=1800)
    ctl = R.PHBCtl()
    o = R.Rig(net2, vf, pf, 41, "phb", ctl=ctl, end=1800).run()
    machine = dict(ctl=o["ctl"],
                   pass_with_ped_on_cross=o["pass_with_ped_on_cross"],
                   pass_total=o["pass_total_mid"],
                   midblock_stops=o["midblock_stops"],
                   n_pet_events=len(o["pet_events"]),
                   min_pet=(min(e[3] for e in o["pet_events"]) if o["pet_events"] else None))

    out = dict(
        state_char_windows=stats,
        window_s=WIN, warmup_s=WARM,
        interpretation={
            "O": "off, no signal: vehicles keep right of way -> models PHB DARK",
            "o": "off, blinking: vehicles must yield -> approximates FLASHING YELLOW",
            "y": "steady yellow -> models the PHB steady-yellow change interval",
            "r": "steady red -> models the PHB steady-red WALK interval",
            "s": "stop-then-proceed-if-clear -> approximates the PHB FLASHING RED "
                 "pedestrian-clearance interval",
            "G": "protected green (not part of the PHB sequence, reference case)",
        },
        phb_state_machine=machine)
    p = os.path.join(RESDIR, "phb_state_char_verification.json")
    with open(p, "w") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out, indent=1))
    print("wrote", p)


if __name__ == "__main__":
    main()
