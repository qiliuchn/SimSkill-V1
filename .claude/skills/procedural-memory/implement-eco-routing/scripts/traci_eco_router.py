"""Online (in-simulation) eco-router: generalized cost pushed onto SUMO's
EFFORT channel via traci.edge.setEffort() + traci.vehicle.rerouteEffort().

    effort_e(t) = alpha * traveltime_e(t) + beta * fuelPerVeh_e(t)

Only *equipped* vehicles (vType "eco") are rerouted; unequipped vehicles
(vType "base"/"side") keep the route they were assigned offline, so the two
classes can be compared directly out of the same run.

Design notes / traps handled here:
 * SUMO keeps TWO independent edge-weight containers -- "travel time"
   (adaptTraveltime / rerouteTraveltime) and "effort" (setEffort /
   rerouteEffort). They are separate; a vehicle rerouted with rerouteEffort
   uses ONLY the effort container, falling back to the edge's travel time for
   any edge whose effort was never set. Effort is therefore set on EVERY edge
   every control step.
 * traci.edge.getFuelConsumption() is a RATE (mg/s) summed over the vehicles
   currently on the edge. Per-vehicle per-traversal fuel is
   rate / n_veh * traveltime. With n_veh == 0 the rate is 0, which would make
   an empty edge look free -- exactly the same zero-sample trap as the offline
   weight files -- so empty edges fall back to the free-flow probe table.
 * Efforts and travel times are exponentially smoothed across control steps.
"""
import argparse
import json
import os
import random
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.environ["SUMO_HOME"], "tools"))
from common import NET, WORK, SIM_END, sumo_bin, classify_route  # noqa: E402
import simlib  # noqa: E402
import probe_freeflow  # noqa: E402
import traci  # noqa: E402

CONTROL_PERIOD = 60      # s between effort updates / reroute triggers
EMA = 0.35               # smoothing of the measured cost surface
MAX_TT = 600.0           # cap on a jammed edge's measured travel time


def tag_routes(src_routes, out_path, penetration, seed):
    """Copy a route file, re-typing a `penetration` share of main-OD vehicles
    to the equipped vType 'eco'. Demand, departure times and initial routes are
    byte-identical across penetration levels (Common Random Numbers)."""
    import xml.etree.ElementTree as ET
    tree = ET.parse(src_routes)
    root = tree.getroot()
    rng = random.Random(90000 + seed)
    n_eq = 0
    n_main = 0
    for v in root.findall("vehicle"):
        if not v.get("id").startswith("main."):
            continue
        n_main += 1
        if rng.random() < penetration:
            v.set("type", "eco")
            n_eq += 1
    tree.write(out_path)
    return n_eq, n_main


def run(routes, prefix, alpha, beta, seed=1, control_period=CONTROL_PERIOD,
        force_bypass_effort=None, log_every=None):
    ff = probe_freeflow.load()
    ed_out = prefix + "_edgeemis.xml"
    add_ed = simlib.write_edgedata_add(prefix + "_edgedata.add.xml", ed_out, period=SIM_END)
    vt = os.path.join(WORK, "vtypes.add.xml")
    cmd = [sumo_bin("sumo"), "-n", NET, "-r", routes,
           "-a", ",".join([vt, add_ed]),
           "--seed", str(seed), "--end", str(SIM_END),
           "--device.emissions.probability", "1.0",
           "--time-to-teleport", "300",
           "--tripinfo-output", prefix + "_tripinfo.xml",
           "--vehroute-output", prefix + "_vehroute.xml",
           "--vehroute-output.write-unfinished", "true",
           "--no-step-log", "true", "--duration-log.statistics", "true",
           "--xml-validation", "never"]
    traci.start(cmd, label=os.path.basename(prefix))
    conn = traci.getConnection(os.path.basename(prefix))

    edges = [e for e in conn.edge.getIDList() if not e.startswith(":")]
    eff = {e: alpha * ff[e]["traveltime"] + beta * ff[e]["fuel_perVeh"] for e in edges}
    tt_s = {e: ff[e]["traveltime"] for e in edges}
    fuel_s = {e: ff[e]["fuel_perVeh"] for e in edges}

    n_reroute_calls = 0
    n_route_changes = 0
    trace = []
    t = 0
    while t < SIM_END:
        conn.simulationStep()
        t = conn.simulation.getTime()
        if conn.simulation.getMinExpectedNumber() <= 0:
            break
        if int(t) % control_period:
            continue

        # ---- 1. measure, smooth, and push the generalized cost as EFFORT ----
        for e in edges:
            n = conn.edge.getLastStepVehicleNumber(e)
            tt = min(conn.edge.getTraveltime(e), MAX_TT)
            if n > 0:
                fuel = conn.edge.getFuelConsumption(e) / n * tt   # mg per traversal
            else:
                tt = ff[e]["traveltime"]
                fuel = ff[e]["fuel_perVeh"]
            tt_s[e] = (1 - EMA) * tt_s[e] + EMA * tt
            fuel_s[e] = (1 - EMA) * fuel_s[e] + EMA * fuel
            v = alpha * tt_s[e] + beta * fuel_s[e]
            if force_bypass_effort is not None and e in ("A_P1", "P1_P2", "P2_P3",
                                                         "P3_P4", "P4_M"):
                v = force_bypass_effort
            eff[e] = v
            conn.edge.setEffort(e, v)

        # ---- 2. trigger effort-based rerouting for EQUIPPED vehicles only ----
        for vid in conn.vehicle.getIDList():
            if conn.vehicle.getTypeID(vid) != "eco":
                continue
            before = conn.vehicle.getRoute(vid)
            conn.vehicle.rerouteEffort(vid)
            n_reroute_calls += 1
            if conn.vehicle.getRoute(vid) != before:
                n_route_changes += 1

        if log_every and int(t) % log_every == 0:
            trace.append(dict(t=t, running=conn.vehicle.getIDCount(),
                              eff_art=sum(eff[e] for e in
                                          ("A_I1", "I1_I2", "I2_I3", "I3_I4", "I4_M")),
                              eff_byp=sum(eff[e] for e in
                                          ("A_P1", "P1_P2", "P2_P3", "P3_P4", "P4_M"))))
    conn.close()
    return dict(reroute_calls=n_reroute_calls, route_changes=n_route_changes,
                tripinfo=prefix + "_tripinfo.xml", vehroute=prefix + "_vehroute.xml",
                edge_emissions=ed_out, trace=trace)


def summarise(res, penetration, alpha, beta, seed, tag):
    ti = simlib.parse_tripinfo(res["tripinfo"])
    vr = simlib.parse_routes(res["vehroute"])
    rows = []
    for t in ti:
        if not t["id"].startswith("main."):
            continue
        ty, edges = vr.get(t["id"], ("?", []))
        rows.append(dict(t, cls=classify_route(edges), equipped=(t["vtype"] == "eco")))
    # subgroup partition cross-check: vType in tripinfo vs vType in vehroute
    mismatch = sum(1 for t in ti if t["id"].startswith("main.")
                   and vr.get(t["id"], ("?",))[0] != t["vtype"])

    def agg(sel):
        s = [r for r in rows if sel(r)]
        if not s:
            return None
        d = sorted(r["duration"] for r in s)
        return dict(n=len(s),
                    mean_dur=statistics.mean(d), p90_dur=d[int(0.9 * (len(d) - 1))],
                    mean_total=statistics.mean(r["duration"] + r["departDelay"] for r in s),
                    CO2_g=statistics.mean(r["CO2"] for r in s) / 1000.0,
                    fuel_g=statistics.mean(r["fuel"] for r in s) / 1000.0,
                    share_bypass=sum(1 for r in s if r["cls"] == "bypass") / len(s),
                    share_arterial=sum(1 for r in s if r["cls"] == "arterial") / len(s),
                    share_hybrid=sum(1 for r in s if r["cls"] == "hybrid") / len(s))

    out = dict(tag=tag, penetration=penetration, alpha=alpha, beta=beta, seed=seed,
               n_all_veh=len(ti),
               net_CO2_kg=sum(t["CO2"] for t in ti) / 1e6,
               net_fuel_kg=sum(t["fuel"] for t in ti) / 1e6,
               net_NOx_kg=sum(t["NOx"] for t in ti) / 1e6,
               main=agg(lambda r: True),
               equipped=agg(lambda r: r["equipped"]),
               unequipped=agg(lambda r: not r["equipped"]),
               reroute_calls=res["reroute_calls"], route_changes=res["route_changes"],
               vtype_mismatches=mismatch)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--routes", required=True)
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--penetration", type=float, default=0.0)
    ap.add_argument("--alpha", type=float, default=1.0)
    ap.add_argument("--beta", type=float, default=0.0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--demand-seed", type=int, default=0)
    ap.add_argument("--tag", default="run")
    ap.add_argument("--force-bypass-effort", type=float, default=None)
    a = ap.parse_args()
    tagged = a.prefix + "_routes.rou.xml"
    n_eq, n_main = tag_routes(a.routes, tagged, a.penetration, a.demand_seed)
    res = run(tagged, a.prefix, a.alpha, a.beta, seed=a.seed,
              force_bypass_effort=a.force_bypass_effort, log_every=300)
    s = summarise(res, a.penetration, a.alpha, a.beta, a.seed, a.tag)
    s["n_equipped"] = n_eq
    s["n_main"] = n_main
    with open(a.prefix + "_summary.json", "w") as f:
        json.dump(s, f, indent=1)
    print(json.dumps({k: v for k, v in s.items() if k not in ("trace",)}, indent=1))
