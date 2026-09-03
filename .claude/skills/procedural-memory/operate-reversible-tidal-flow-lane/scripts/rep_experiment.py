#!/usr/bin/env python3
"""REPRESENTATION EXPERIMENT -- how should a reversible lane be encoded in SUMO?

Three candidate encodings are built and exercised empirically; nothing is
assumed.  Writes outputs/analysis/representation_experiment.json

  B  one directional edge pair, all six physical lanes declared on BOTH
     directional edges, gated at runtime with traci.lane.setAllowed.
     B1  compiled OPEN, gated at t=0                      (candidate accepted)
     B2  compiled CLOSED, reopened at runtime on the NORMAL lanes only
     B3  compiled CLOSED, reopened on normal AND internal connector lanes
  A  the reversible lane as a pair of opposing single-lane edges over the same
     geometry, exactly one open at a time.
     A1  demand routed only over the permanent edges, reversible edges open
     A2  demand explicitly routed over the reversible edge, then reversed
         mid-run underneath those vehicles
  C  rerouter <closingLaneReroute> on the reversible lane.
     C1  does it actually keep vehicles off the lane?
     C2  is the interval controllable at runtime through TraCI?
"""
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (NETDIR, DEMDIR, RUNDIR, ANADIR, TOOLS, DIR_EDGES, PHYS_LANES,
                    lane_id, assignment, OPEN_CLASSES, CLOSED_CLASSES, ensure_dirs)

sys.path.append(TOOLS)
import traci  # noqa: E402

VT = ('    <vType id="car" vClass="passenger" length="5.0" minGap="2.5" '
      'accel="2.6" decel="4.5" sigma="0.5" tau="1.0" maxSpeed="20.0" '
      'speedFactor="normc(1.0,0.10,0.75,1.25)"/>')


def write(p, s):
    with open(p, "w") as f:
        f.write(s)


def internal_map(netfile):
    root = ET.parse(netfile).getroot()
    conns = [c.attrib for c in root.findall("connection")]
    out = defaultdict(list)
    for d in ("EB", "WB"):
        edges = DIR_EDGES[d]
        for phys in PHYS_LANES:
            for a, b in zip(edges[:-1], edges[1:]):
                lid = lane_id(d, a, phys)
                fe, fi = lid.rsplit("_", 1)
                for c in conns:
                    if c.get("from") == fe and c.get("fromLane") == fi and c.get("to") == b:
                        if c.get("via"):
                            out[(d, phys)].append(c["via"])
    return out


# ---------------------------------------------------------------- encoding B
def wb_heavy_routes(path, n=2200, tmax=1800.0):
    lines = ["<routes>", VT,
             '    <route id="rWB" edges="apE_in COR_WB apW_out"/>']
    for i in range(n):
        lines.append(f'    <vehicle id="WB.{i}" type="car" route="rWB" '
                     f'depart="{i * tmax / n:.2f}" departLane="best" departSpeed="max"/>')
    lines.append("</routes>")
    write(path, "\n".join(lines) + "\n")


def run_encB(net, tag, open_internal, outdir):
    """Force config 2+4 (both reversible lanes westbound) at t=0 and see whether
    westbound traffic can actually use them end to end."""
    os.makedirs(outdir, exist_ok=True)
    rou = os.path.join(DEMDIR, "rep_wb_heavy.rou.xml")
    if not os.path.exists(rou):
        wb_heavy_routes(rou)
    errlog = os.path.join(outdir, "sumo_errors.log")
    traci.start(["sumo", "-n", net, "-r", rou,
                 "--tripinfo-output", os.path.join(outdir, "tripinfo.xml"),
                 "--tripinfo-output.write-unfinished", "true",
                 "--summary-output", os.path.join(outdir, "summary.xml"),
                 "--seed", "7", "--begin", "0", "--end", "3600",
                 "--time-to-teleport", "300", "--no-step-log", "true",
                 "--xml-validation", "never", "--error-log", errlog])
    imap = internal_map(net)
    asg = assignment("2+4")
    for phys in PHYS_LANES:
        owner = asg[phys]
        other = "EB" if owner == "WB" else "WB"
        for d, want_open in ((owner, True), (other, False)):
            for e in DIR_EDGES[d]:
                lid = lane_id(d, e, phys)
                traci.lane.setAllowed(lid, OPEN_CLASSES if want_open else CLOSED_CLASSES)
            if open_internal or not want_open:
                for iv in imap[(d, phys)]:
                    traci.lane.setAllowed(iv, OPEN_CLASSES if want_open else CLOSED_CLASSES)

    # per physical lane: who entered the CORRIDOR representation, and who
    # subsequently reached the DOWNSTREAM continuation of the same lane
    entered = {p: set() for p in ("L3", "L4", "L5", "L6")}
    completed = {p: set() for p in entered}
    maxq = 0
    teleports = 0
    t = 0.0
    while t < 3600:
        traci.simulationStep()
        t = traci.simulation.getTime()
        teleports += traci.simulation.getStartingTeleportNumber()
        for p in entered:
            entered[p].update(traci.lane.getLastStepVehicleIDs(lane_id("WB", "COR_WB", p)))
            completed[p].update(traci.lane.getLastStepVehicleIDs(lane_id("WB", "apW_out", p)))
        maxq = max(maxq, traci.vehicle.getIDCount())
        if traci.simulation.getMinExpectedNumber() == 0:
            break
    stuck = {}
    for vid in traci.vehicle.getIDList():
        lane = traci.vehicle.getLaneID(vid)
        stuck[lane] = stuck.get(lane, 0) + 1
    traci.close()

    root = ET.parse(os.path.join(outdir, "tripinfo.xml")).getroot()
    arrived = sum(1 for tr in root if float(tr.get("arrival")) >= 0)
    last = None
    for s in ET.parse(os.path.join(outdir, "summary.xml")).getroot():
        last = s.attrib
    errs = open(errlog).read() if os.path.exists(errlog) else ""
    per = {}
    for p in entered:
        ent = len(entered[p])
        comp = len(entered[p] & completed[p])
        per[p] = dict(entered_corridor_lane=ent, completed_through_downstream_junction=comp,
                      completion_rate=round(comp / ent, 4) if ent else None)
    return dict(
        variant=tag, net=os.path.basename(net), reopened_internal_lanes=open_internal,
        westbound_lane_use=per,
        demand=2200, loaded=int(last["loaded"]), inserted=int(last["inserted"]),
        arrived=arrived, still_running_at_sim_end=int(last["running"]),
        never_inserted=int(last["loaded"]) - int(last["inserted"]),
        teleports=teleports, max_concurrent_vehicles=maxq,
        lanes_of_vehicles_stuck_at_sim_end=dict(
            sorted(stuck.items(), key=lambda kv: -kv[1])[:8]),
        n_error_lines=len([l for l in errs.splitlines() if l.strip()]),
        first_errors=[l for l in errs.splitlines() if l.strip()][:5])


# ---------------------------------------------------------------- encoding A
def encA_routes(path, share_on_rev, n=2000, tmax=1800.0):
    lines = ["<routes>", VT,
             '    <route id="rEB_main" edges="apW_in COR_EB apE_out"/>',
             '    <route id="rEB_rev3" edges="apW_in RL3_EB apE_out"/>']
    for i in range(n):
        rid = "rEB_rev3" if (share_on_rev > 0 and i % int(1 / share_on_rev) == 0) else "rEB_main"
        lines.append(f'    <vehicle id="EB.{i}" type="car" route="{rid}" '
                     f'depart="{i * tmax / n:.2f}" departLane="best" departSpeed="max"/>')
    lines.append("</routes>")
    write(path, "\n".join(lines) + "\n")


def run_encA(tag, share_on_rev, reverse_at, outdir, ignore_route_errors=False):
    os.makedirs(outdir, exist_ok=True)
    net = os.path.join(NETDIR, "encA.net.xml")
    rou = os.path.join(DEMDIR, f"rep_encA_{tag}.rou.xml")
    encA_routes(rou, share_on_rev)
    errlog = os.path.join(outdir, "sumo_errors.log")
    cmd = ["sumo", "-n", net, "-r", rou,
           "--tripinfo-output", os.path.join(outdir, "tripinfo.xml"),
           "--tripinfo-output.write-unfinished", "true",
           "--summary-output", os.path.join(outdir, "summary.xml"),
           "--seed", "7", "--begin", "0", "--end", "3600",
           "--time-to-teleport", "300", "--no-step-log", "true",
           "--xml-validation", "never", "--error-log", errlog]
    if ignore_route_errors:
        cmd += ["--ignore-route-errors", "true"]
    traci.start(cmd)
    # start: both eastbound reversible edges open, both westbound ones closed
    for lid in ("RL3_EB_0", "RL4_EB_0"):
        traci.lane.setAllowed(lid, OPEN_CLASSES)
    for lid in ("RL3_WB_0", "RL4_WB_0"):
        traci.lane.setAllowed(lid, CLOSED_CLASSES)

    ever_rev, ever_main = set(), set()
    teleports = 0
    flipped, crashed = False, None
    on_rev_at_flip, stranded_after = 0, []
    t = 0.0
    try:
        while t < 3600:
            traci.simulationStep()
            t = traci.simulation.getTime()
            teleports += traci.simulation.getStartingTeleportNumber()
            ever_rev.update(traci.lane.getLastStepVehicleIDs("RL3_EB_0"))
            ever_main.update(traci.lane.getLastStepVehicleIDs("COR_EB_0"))
            ever_main.update(traci.lane.getLastStepVehicleIDs("COR_EB_1"))
            if reverse_at is not None and not flipped and t >= reverse_at:
                on_rev = traci.lane.getLastStepVehicleIDs("RL3_EB_0")
                on_rev_at_flip = len(on_rev)
                traci.lane.setAllowed("RL3_EB_0", CLOSED_CLASSES)
                traci.lane.setAllowed("RL3_WB_0", OPEN_CLASSES)
                flipped = True
            if traci.simulation.getMinExpectedNumber() == 0:
                break
        traci.close()
    except traci.exceptions.FatalTraCIError as ex:      # SUMO quit on error
        crashed = f"{type(ex).__name__}: {ex} at t={t}"
        try:
            traci.close()
        except Exception:                                # noqa: BLE001
            pass

    arrived = unfinished = None
    tri = os.path.join(outdir, "tripinfo.xml")
    if os.path.exists(tri):
        try:
            root = ET.parse(tri).getroot()
            arrived = sum(1 for tr in root if float(tr.get("arrival")) >= 0)
            unfinished = sum(1 for tr in root if float(tr.get("arrival")) < 0)
        except ET.ParseError:
            arrived = unfinished = "tripinfo truncated (SUMO aborted)"
    errs = [l for l in (open(errlog).read().splitlines() if os.path.exists(errlog) else []) if l.strip()]
    return dict(variant=tag, net="encA.net.xml", share_routed_over_reversible=share_on_rev,
                reversed_at=reverse_at, ignore_route_errors=ignore_route_errors,
                sumo_aborted=crashed,
                vehicles_that_used_RL3_EB=len(ever_rev),
                vehicles_that_used_permanent_COR_EB=len(ever_main),
                vehicles_on_reversible_lane_at_instant_of_reversal=on_rev_at_flip,
                arrived=arrived, never_arrived=unfinished, teleports=teleports,
                n_error_lines=len(errs), first_errors=errs[:6])


# ---------------------------------------------------------------- encoding C
def run_encC(outdir):
    os.makedirs(outdir, exist_ok=True)
    net = os.path.join(NETDIR, "encB_open.net.xml")
    rou = os.path.join(DEMDIR, "rep_eb_heavy.rou.xml")
    lines = ["<routes>", VT, '    <route id="rEB" edges="apW_in COR_EB apE_out"/>']
    for i in range(2200):
        lines.append(f'    <vehicle id="EB.{i}" type="car" route="rEB" '
                     f'depart="{i * 1800 / 2200:.2f}" departLane="best" departSpeed="max"/>')
    lines.append("</routes>")
    write(rou, "\n".join(lines) + "\n")

    add = os.path.join(outdir, "rerouter.add.xml")
    write(add, """<additional>
    <rerouter id="rev_close" edges="apW_in">
        <interval begin="600" end="1200">
            <closingLaneReroute id="COR_EB_2" disallow="all"/>
            <closingLaneReroute id="COR_EB_3" disallow="all"/>
        </interval>
    </rerouter>
</additional>
""")
    errlog = os.path.join(outdir, "sumo_errors.log")
    traci.start(["sumo", "-n", net, "-r", rou, "-a", add,
                 "--tripinfo-output", os.path.join(outdir, "tripinfo.xml"),
                 "--seed", "7", "--begin", "0", "--end", "2400",
                 "--time-to-teleport", "300", "--no-step-log", "true",
                 "--xml-validation", "never", "--error-log", errlog])
    counts = {"before": 0, "during": 0, "after": 0}
    steps = {"before": 0, "during": 0, "after": 0}
    new_entries = {"before": 0, "during": 0, "after": 0}
    prev_on = set()
    series = []
    perm_samples = {}
    rr_ids = list(traci.rerouter.getIDList())
    api = {}
    for attempt, fn in (("setParameter(begin)", lambda: traci.rerouter.setParameter(
                            rr_ids[0], "begin", "1800")),
                        ("getParameter(begin)", lambda: traci.rerouter.getParameter(
                            rr_ids[0], "begin"))):
        try:
            api[attempt] = repr(fn())
        except Exception as ex:                       # noqa: BLE001
            api[attempt] = f"EXCEPTION: {type(ex).__name__}: {ex}"
    t = 0.0
    while t < 2400:
        traci.simulationStep()
        t = traci.simulation.getTime()
        key = "before" if t < 600 else ("during" if t < 1200 else "after")
        on = set(traci.lane.getLastStepVehicleIDs("COR_EB_2")) | \
            set(traci.lane.getLastStepVehicleIDs("COR_EB_3"))
        new_entries[key] += len(on - prev_on)
        prev_on = on
        counts[key] += len(on)
        steps[key] += 1
        if int(t) % 30 == 0:
            series.append((int(t), len(on)))
        if int(t) in (300, 630, 900, 1190, 1500):
            perm_samples[int(t)] = dict(
                COR_EB_2_allowed=list(traci.lane.getAllowed("COR_EB_2")),
                COR_EB_2_disallowed=list(traci.lane.getDisallowed("COR_EB_2")))
    traci.close()
    errs = [l for l in (open(errlog).read().splitlines() if os.path.exists(errlog) else []) if l.strip()]
    return dict(variant="C1_closingLaneReroute", rerouter_ids=rr_ids,
                interval="begin=600 end=1200, closingLaneReroute COR_EB_2 + COR_EB_3",
                mean_vehicles_on_reversible_lanes={
                    k: round(counts[k] / max(steps[k], 1), 2) for k in counts},
                new_lane_entries={k: new_entries[k] for k in new_entries},
                occupancy_series_every_30s=series,
                lane_permission_samples=perm_samples,
                traci_rerouter_api_probe=api,
                traci_rerouter_domain_methods=[m for m in dir(traci.rerouter)
                                               if not m.startswith("_")],
                n_error_lines=len(errs), first_errors=errs[:5])


def main():
    ensure_dirs()
    res = {}
    print("--- encoding B ---")
    res["B1_compiled_open_gated_at_t0"] = run_encB(
        os.path.join(NETDIR, "encB_open.net.xml"), "B1", True,
        os.path.join(RUNDIR, "rep_B1"))
    print(res["B1_compiled_open_gated_at_t0"])
    res["B2_compiled_closed_reopen_normal_lanes_only"] = run_encB(
        os.path.join(NETDIR, "encB_closed.net.xml"), "B2", False,
        os.path.join(RUNDIR, "rep_B2"))
    print(res["B2_compiled_closed_reopen_normal_lanes_only"])
    res["B3_compiled_closed_reopen_normal_and_internal"] = run_encB(
        os.path.join(NETDIR, "encB_closed.net.xml"), "B3", True,
        os.path.join(RUNDIR, "rep_B3"))
    print(res["B3_compiled_closed_reopen_normal_and_internal"])

    print("--- encoding A ---")
    res["A1_no_demand_routed_over_reversible_edge"] = run_encA(
        "A1", 0.0, None, os.path.join(RUNDIR, "rep_A1"))
    print(res["A1_no_demand_routed_over_reversible_edge"])
    res["A2_reversed_under_committed_vehicles_strict"] = run_encA(
        "A2", 0.25, 900.0, os.path.join(RUNDIR, "rep_A2"))
    print(res["A2_reversed_under_committed_vehicles_strict"])
    res["A3_reversed_under_committed_vehicles_ignore_route_errors"] = run_encA(
        "A3", 0.25, 900.0, os.path.join(RUNDIR, "rep_A3"), ignore_route_errors=True)
    print(res["A3_reversed_under_committed_vehicles_ignore_route_errors"])

    print("--- encoding C ---")
    res["C_rerouter_closingLaneReroute"] = run_encC(os.path.join(RUNDIR, "rep_C"))
    print(res["C_rerouter_closingLaneReroute"])

    out = os.path.join(ANADIR, "representation_experiment.json")
    with open(out, "w") as f:
        json.dump(res, f, indent=2)
    print("\nwrote", out)


if __name__ == "__main__":
    main()
