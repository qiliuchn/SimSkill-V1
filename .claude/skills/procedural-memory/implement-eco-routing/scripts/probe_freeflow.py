"""Build a per-edge FREE-FLOW reference table (traveltime + *_perVeh emissions).

Why this exists: an `edgeData type="emissions"` dump only carries `traveltime`
and `*_perVeh` attributes for edges that actually had a vehicle on them. A
zero-flow edge is written with *only* `*_abs`/`*_normed` (all 0.0) -- verified
directly against SUMO 1.27.1. Feeding such a file to
`duarouter --weight-attribute CO2_perVeh` therefore leaves unused edges with no
weight at all, which is fatal for an iterative eco-assignment (an unused edge
must look *free-flow cheap*, not *free* and not *missing*).

The fix used throughout this study: run one ultra-low-density probe simulation
in which every edge is traversed by a handful of vehicles at the speed limit,
and use its per-edge values as the fallback for any edge that has no sample in
a later, congested iteration.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import NET, WORK, SIM_END  # noqa: E402
import simlib  # noqa: E402

sys.path.insert(0, os.path.join(os.environ["SUMO_HOME"], "tools"))
import sumolib  # noqa: E402

FF_JSON = os.path.join(WORK, "freeflow_edge_ref.json")
N_PER_EDGE = 6
HEADWAY = 40.0   # s between probe vehicles on the same edge -> no interaction


def build():
    net = sumolib.net.readNet(NET)
    edges = [e for e in net.getEdges() if not e.getID().startswith(":")]
    trips = os.path.join(WORK, "probe.rou.xml")
    with open(trips, "w") as f:
        f.write('<routes>\n')
        f.write('    <vType id="probe" vClass="passenger" emissionClass="HBEFA3/PC_G_EU4" '
                'length="4.5" accel="2.6" decel="4.5" sigma="0.0" speedDev="0.0" maxSpeed="30.0"/>\n')
        n = 0
        for e in edges:
            for k in range(N_PER_EDGE):
                f.write('    <vehicle id="p.%d" type="probe" depart="%.2f" '
                        'departSpeed="max" departLane="best">\n'
                        '        <route edges="%s"/>\n    </vehicle>\n'
                        % (n, 5 + k * HEADWAY, e.getID()))
                n += 1
        f.write('</routes>\n')

    files = simlib.run_sumo(trips, os.path.join(WORK, "probe"),
                            emissions_edgedata=True, edge_period=SIM_END)
    iv = simlib.parse_edge_emissions(files["edge_emissions"])[0]
    ref = {}
    missing = []
    for e in edges:
        d = iv["edges"].get(e.getID(), {})
        if "traveltime" not in d:
            missing.append(e.getID())
            # analytic fallback of last resort
            d = dict(traveltime=e.getLength() / e.getSpeed(), CO2_perVeh=0.0, fuel_perVeh=0.0)
        ref[e.getID()] = dict(
            length=e.getLength(), speed=e.getSpeed(), lanes=e.getLaneNumber(),
            traveltime=d["traveltime"],
            CO2_perVeh=d.get("CO2_perVeh", 0.0),
            fuel_perVeh=d.get("fuel_perVeh", 0.0),
            NOx_perVeh=d.get("NOx_perVeh", 0.0),
        )
    with open(FF_JSON, "w") as f:
        json.dump(ref, f, indent=1)
    print("free-flow reference for %d edges -> %s (edges w/o sample: %s)"
          % (len(ref), FF_JSON, missing or "none"))
    return ref


def load():
    with open(FF_JSON) as f:
        return json.load(f)


if __name__ == "__main__":
    r = build()
    for k in ("A_I1", "A_P1", "I1_I2", "P1_P2", "P4_M", "I4_M"):
        v = r[k]
        print("%-8s len=%7.1f v=%5.2f tt=%6.2fs CO2/veh=%9.1f mg  fuel/veh=%9.1f mg  "
              "CO2 g/km=%6.1f" % (k, v["length"], v["speed"], v["traveltime"],
                                  v["CO2_perVeh"], v["fuel_perVeh"],
                                  v["CO2_perVeh"] / 1000.0 / (v["length"] / 1000.0)))
