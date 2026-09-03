#!/usr/bin/env python3
"""
02_build_demand_and_sensors.py

(a) Time-varying demand profile that builds the EB arterial to oversaturation at J3
    and then recovers.
(b) The E1 induction-loop sensing layer:
      * stop-bar loops on every EB approach (J1..J5), both lanes
      * a mid-link "spot speed" station at the midpoint of every EB link
      * an advance-loop ladder at setbacks {40,80,120,160,200,250,320} m on the
        EB approach to J3 (the bottleneck), both lanes
      * a 120 m advance loop on every other EB approach
    Base aggregation period 30 s (60/300 s are formed offline by re-aggregation);
    a duplicate NATIVE 300 s station is emitted so that offline re-aggregation can
    be verified against SUMO's own aggregation.
"""
import os
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
SCEN = os.path.abspath(os.path.join(HERE, "..", "scenario"))

N_INT = 5
SIM_END = 5400

# EB through demand profile (veh/h) -- builds to oversaturation, then recovers.
# J3 EB capacity = 2 lanes x ~1800 veh/h/lane x (44/90) ~= 1760 veh/h
EB_PROFILE = [
    (0,    600,  600),
    (600,  1200, 900),
    (1200, 1800, 1300),
    (1800, 2400, 1700),
    (2400, 3600, 2000),   # oversaturated at J3
    (3600, 4200, 1500),
    (4200, 4800, 900),
    (4800, 5400, 600),
]
WB_RATE = 800.0     # veh/h, constant
CROSS_RATE = 250.0  # veh/h per cross movement, constant

SETBACKS_J3 = [40, 80, 120, 160, 200, 250, 320]
SETBACK_DEFAULT = 120
# fine 1 m ladder on the J3 EB approach, to test whether occupancy-based queue
# detection is hypersensitive to sub-vehicle-length detector positioning
FINE_SETBACKS = list(range(60, 261))
BASE_PERIOD = 30
NATIVE_CHECK_PERIOD = 300


def lane_lengths(net):
    tree = ET.parse(net)
    out = {}
    for e in tree.getroot().findall("edge"):
        if e.get("function") == "internal":
            continue
        ls = e.findall("lane")
        out[e.get("id")] = (len(ls), float(ls[0].get("length")))
    return out


def write_routes():
    eb_route = " ".join(f"eb_{i}" for i in range(N_INT + 1))
    wb_route = " ".join(f"wb_{i}" for i in range(N_INT, -1, -1))
    L = ['<routes>']
    L.append('  <vType id="car" vClass="passenger" length="5.0" minGap="2.5" maxSpeed="16.7" '
             'accel="2.6" decel="4.5" sigma="0.5" tau="1.0" speedFactor="normc(1.0,0.10,0.7,1.3)"/>')
    L.append(f'  <route id="r_eb" edges="{eb_route}"/>')
    L.append(f'  <route id="r_wb" edges="{wb_route}"/>')
    for i in range(1, N_INT + 1):
        L.append(f'  <route id="r_nb{i}" edges="nb_{i} nbo_{i}"/>')
        L.append(f'  <route id="r_sb{i}" edges="sb_{i} sbo_{i}"/>')
    # NOTE: SUMO silently IGNORES <flow> elements that are out of departure-time
    # order (warning only, no error, no vehicles inserted) -- flows must be
    # emitted sorted by `begin`.
    flows = []
    for n, (b, e, rate) in enumerate(EB_PROFILE):
        flows.append((b, f'  <flow id="f_eb_{n}" type="car" route="r_eb" begin="{b}" end="{e}" '
                         f'vehsPerHour="{rate}" departLane="best" departSpeed="max"/>'))
    flows.append((0, f'  <flow id="f_wb" type="car" route="r_wb" begin="0" end="{SIM_END}" '
                     f'vehsPerHour="{WB_RATE}" departLane="best" departSpeed="max"/>'))
    for i in range(1, N_INT + 1):
        flows.append((0, f'  <flow id="f_nb{i}" type="car" route="r_nb{i}" begin="0" end="{SIM_END}" '
                         f'vehsPerHour="{CROSS_RATE}" departLane="best" departSpeed="max"/>'))
        flows.append((0, f'  <flow id="f_sb{i}" type="car" route="r_sb{i}" begin="0" end="{SIM_END}" '
                         f'vehsPerHour="{CROSS_RATE}" departLane="best" departSpeed="max"/>'))
    flows.sort(key=lambda t: t[0])
    L += [x[1] for x in flows]
    L.append('</routes>')
    open(os.path.join(SCEN, "demand.rou.xml"), "w").write("\n".join(L) + "\n")


def write_detectors(net):
    LL = lane_lengths(net)
    L = ['<additional>']
    meta = []

    def add(did, edge, ln, pos, period, kind, jn, setback):
        L.append(f'  <inductionLoop id="{did}" lane="{edge}_{ln}" pos="{pos:.2f}" '
                 f'period="{period}" file="e1_out.xml" friendlyPos="true"/>')
        meta.append(dict(id=did, edge=edge, lane=ln, pos=pos, period=period,
                         kind=kind, junction=jn, setback=setback))

    for i in range(1, N_INT + 1):
        app = f"eb_{i-1}"                   # EB approach edge to Ji
        nl, length = LL[app]
        for ln in range(nl):
            # stop bar
            add(f"SB_J{i}_l{ln}", app, ln, length - 1.0, BASE_PERIOD, "stopbar", i, 0)
            # mid-link spot-speed station (on the link UPSTREAM of Ji, i.e. app)
            add(f"MID_L{i-1}_l{ln}", app, ln, length / 2.0, BASE_PERIOD, "midlink", i, None)
            add(f"MIDNAT_L{i-1}_l{ln}", app, ln, length / 2.0, NATIVE_CHECK_PERIOD,
                "midlink_native300", i, None)
            # advance ladder
            sets = SETBACKS_J3 if i == 3 else [SETBACK_DEFAULT]
            for d in sets:
                add(f"ADV{d}_J{i}_l{ln}", app, ln, length - 1.0 - d, BASE_PERIOD,
                    "advance", i, d)
    # fine 1 m positioning ladder on the J3 EB approach (both lanes)
    app3 = "eb_2"
    nl3, len3 = LL[app3]
    for d in FINE_SETBACKS:
        for ln in range(nl3):
            add(f"FINE{d}_J3_l{ln}", app3, ln, len3 - 1.0 - d, BASE_PERIOD, "fine", 3, d)

    # last EB link (J5 -> E6) mid-link station, completes the 6-link corridor
    nl, length = LL["eb_5"]
    for ln in range(nl):
        add(f"MID_L5_l{ln}", "eb_5", ln, length / 2.0, BASE_PERIOD, "midlink", 6, None)
        add(f"MIDNAT_L5_l{ln}", "eb_5", ln, length / 2.0, NATIVE_CHECK_PERIOD,
            "midlink_native300", 6, None)
    L.append('</additional>')
    open(os.path.join(SCEN, "e1.add.xml"), "w").write("\n".join(L) + "\n")

    import json
    json.dump(meta, open(os.path.join(SCEN, "detector_meta.json"), "w"), indent=1)
    return meta


def write_edgedata():
    L = ['<additional>',
         '  <edgeData id="ed30" freq="30" file="edgedata.xml" excludeEmpty="false"/>',
         '</additional>']
    open(os.path.join(SCEN, "edgedata.add.xml"), "w").write("\n".join(L) + "\n")


def main():
    net = os.path.join(SCEN, "arterial.net.xml")
    write_routes()
    meta = write_detectors(net)
    write_edgedata()
    print(f"routes written; {len(meta)} E1 detectors written")
    from collections import Counter
    print(Counter(m["kind"] for m in meta))


if __name__ == "__main__":
    main()
