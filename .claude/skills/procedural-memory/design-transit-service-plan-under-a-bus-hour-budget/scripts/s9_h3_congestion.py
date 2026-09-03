"""H3 -- congestion-cost feedback.

(1) Does mixed-traffic delay inflate the fleet needed for a given headway enough
    to change the optimal allocation?  Measures cycle time with and without the
    background car traffic, then compares the square-root allocation computed
    from FREE-FLOW cycle times against the one computed from CONGESTED cycle
    times, both evaluated in the congested world.
(2) Does spending part of the budget on a BUS LANE buy more effective service
    than spending the same amount on frequency?  Stated exchange rate: a 2-way
    bus lane over the 4 km trunk corridor costs 4 bus-hours per peak hour.
"""
import os, sys, json, math, statistics as st
import tspcore as T
from tspcore import WORK, ensure
import plans as P
import harness as H
import alloc as A

STRUCT = os.environ.get("STRUCT", "trunkfeeder")
BUDGET = int(os.environ.get("BUDGET", "24"))
LANE_COST_BUS_HOURS = 4
SEEDS = [501, 502, 503]
TRUNK_NODES = ["A2", "B2", "C2", "D2", "E2", "F2"]
OUTJ = os.path.join(WORK, "h3_congestion.json")


def trunk_edges():
    e = []
    for i in range(len(TRUNK_NODES) - 1):
        e.append(TRUNK_NODES[i] + TRUNK_NODES[i + 1])
        e.append(TRUNK_NODES[i + 1] + TRUNK_NODES[i])
    return e


def main():
    speeds = H.load_json(H.SPEED_FILE)[STRUCT]
    cycles = H.load_json(H.CYCLE_FILE)[STRUCT]
    demand = H.load_json(os.path.join(WORK, "linedemand.json"))[STRUCT]
    ids = [l[0] for l in P.PLAN_DEFS[STRUCT]]
    out = {}

    # ---- (1a) free-flow vs congested cycle times ---------------------------
    base, ok, _ = A.sqrt_rule(BUDGET, cycles, demand, ids)
    net = T.Net(os.path.join(WORK, "base.net.xml"))
    d, plan, comp, routed, _ = H.prepare(STRUCT, base, None, cycles, speeds,
                                         tag=f"h3_base_{STRUCT}")
    res_nc = T.simulate(net, comp, routed, [], os.path.join(d, "nocars"), seed=SEEDS[0])
    m_nc, _, _ = H.metrics(plan, res_nc)
    res_c = T.simulate(net, comp, routed, [H.CARS], os.path.join(d, "cars"), seed=SEEDS[0])
    m_c, _, _ = H.metrics(plan, res_c)
    ff = {l: m_nc["cycles"][l] for l in ids}
    cg = {l: m_c["cycles"][l] for l in ids}
    print("line   free-flow cycle   congested cycle   inflation   "
          "buses needed @ h_congested")
    infl = {}
    for l in ids:
        h = cycles[l] / base[l]
        infl[l] = cg[l] / ff[l] - 1
        print(f"{l:6s} {ff[l]:15.1f} {cg[l]:17.1f} {100*infl[l]:10.1f}%   "
              f"{math.ceil(ff[l]/h)} -> {math.ceil(cg[l]/h)}   (h={h:.0f}s)")
    out["cycle_inflation"] = dict(free_flow=ff, congested=cg,
                                  inflation_pct={l: 100*infl[l] for l in ids},
                                  headways={l: cycles[l]/base[l] for l in ids},
                                  fleet_ff={l: math.ceil(ff[l]/(cycles[l]/base[l])) for l in ids},
                                  fleet_cg={l: math.ceil(cg[l]/(cycles[l]/base[l])) for l in ids})

    # ---- (1b) does it change the ALLOCATION? -------------------------------
    ff_C = {l: ff[l] + max(T.LAYOVER_FRAC*ff[l], T.LAYOVER_MIN) for l in ids}
    alloc_ff, ok1, _ = A.sqrt_rule(BUDGET, ff_C, demand, ids)
    alloc_cg = base
    print(f"\nallocation from FREE-FLOW cycle times : {alloc_ff}")
    print(f"allocation from CONGESTED cycle times: {alloc_cg}")
    arms = {"alloc_from_freeflow_cycles": alloc_ff,
            "alloc_from_congested_cycles": alloc_cg}

    # ---- (2) bus lane ------------------------------------------------------
    lane_net = T.build_network(WORK, buslane_edges=trunk_edges(), tag="buslane")
    LN = T.Net(lane_net)
    nbus = sum(1 for e in trunk_edges()
               if any("bus" in (l or "") for l in [None]))
    # verify the restriction landed on the compiled network
    import xml.etree.ElementTree as ET
    r = ET.parse(lane_net).getroot()
    restricted = []
    for e in r.findall("edge"):
        if e.get("id") in trunk_edges():
            for l in e.findall("lane"):
                if (l.get("allow") or "") .strip() == "bus":
                    restricted.append(l.get("id"))
    print(f"\nbus lane: {len(restricted)} lanes restricted to vClass bus on "
          f"{len(trunk_edges())} trunk edges")
    out["buslane_restricted_lanes"] = restricted
    assert len(restricted) == len(trunk_edges()), "bus lane did not compile"

    # cars keep their existing routes (edge ids unchanged); re-route to be safe
    cars_lane = T.route_cars(LN, WORK, [os.path.join(WORK, "modechoice_cars.trips.xml"),
                                        os.path.join(WORK, "bg.trips.xml")],
                             "cars_buslane.rou.xml")

    budget_minus, ok2, _ = A.sqrt_rule(BUDGET - LANE_COST_BUS_HOURS, cycles, demand, ids)
    print(f"allocation at B={BUDGET-LANE_COST_BUS_HOURS} (bus-lane arm): {budget_minus}")

    jobs, keys = [], []
    for an, b in arms.items():
        for s in SEEDS:
            jobs.append((STRUCT, b, s, None, cycles, speeds, f"h3_{an}", False))
            keys.append((an, s, "base"))
    for s in SEEDS:
        jobs.append((STRUCT, budget_minus, s, None, cycles, speeds,
                     f"h3_freqonly_B{BUDGET-LANE_COST_BUS_HOURS}", False))
        keys.append((f"frequency_only_B{BUDGET-LANE_COST_BUS_HOURS}", s, "base"))
    print(f"\n{len(jobs)} base-network runs")
    res = H.evaluate_many(jobs, workers=8)
    agg = {}
    for (an, s, _), m in zip(keys, res):
        if "error" in m:
            print("ERR", m["error"]); continue
        agg.setdefault(an, []).append(m)

    # bus-lane arm needs its own network + its own person routing + its own cars
    lane_arm = f"buslane_B{BUDGET-LANE_COST_BUS_HOURS}"
    ms = []
    d2, plan2, comp2, routed2, _ = H.prepare(STRUCT, budget_minus, lane_net, cycles,
                                             speeds, tag=f"h3_{lane_arm}")
    for s in SEEDS:
        r2 = T.simulate(LN, comp2, routed2, [cars_lane], os.path.join(d2, f"seed{s}"), seed=s)
        mm, _, _ = H.metrics(plan2, r2)
        ms.append(mm)
    agg[lane_arm] = ms
    # and a bus-lane arm at the FULL budget, to separate "lane" from "lane minus 4 buses"
    d3, plan3, comp3, routed3, _ = H.prepare(STRUCT, base, lane_net, cycles, speeds,
                                             tag=f"h3_buslane_B{BUDGET}")
    ms3 = []
    for s in SEEDS:
        r3 = T.simulate(LN, comp3, routed3, [cars_lane], os.path.join(d3, f"seed{s}"), seed=s)
        mm, _, _ = H.metrics(plan3, r3)
        ms3.append(mm)
    agg[f"buslane_B{BUDGET}_unpriced"] = ms3

    print("\n%-34s %8s %12s %10s %10s %10s %12s" % (
        "arm", "bus-h", "GC(pax-h)", "riders", "meanIVT", "meanWait", "carTimeLoss"))
    rows = {}
    for an, mss in agg.items():
        gc = [H.gc_total(m) for m in mss]
        rows[an] = dict(
            gc_mean=st.mean(gc), gc_sd=st.pstdev(gc),
            riders=st.mean([m["n_riders"] for m in mss]),
            ivt=st.mean([m["sum_ivt"]/max(1, m["n_riders"]) for m in mss]),
            wait=st.mean([m["sum_wait"]/max(1, m["n_riders"]) for m in mss]),
            car_timeloss=st.mean([m["mean_car_timeloss"] for m in mss]),
            car_dur=st.mean([m["mean_car_dur"] for m in mss]),
            cycles=mss[0]["cycles_C"],
            buses=sum(mss[0]["buses"].values()),
            teleports=st.mean([m["teleports"] or 0 for m in mss]),
            incomplete=st.mean([m["n_incomplete"] for m in mss]))
        print("%-34s %8d %12.1f %10.1f %10.1f %10.1f %12.1f" % (
            an, rows[an]["buses"], rows[an]["gc_mean"]/3600, rows[an]["riders"],
            rows[an]["ivt"], rows[an]["wait"], rows[an]["car_timeloss"]))
    out["arms"] = rows
    out["lane_cost_bus_hours"] = LANE_COST_BUS_HOURS
    out["allocations"] = dict(arms, **{f"frequency_only_B{BUDGET-LANE_COST_BUS_HOURS}":
                                       budget_minus})
    with open(OUTJ, "w") as f:
        json.dump(out, f, indent=1)
    print("\nwritten", OUTJ)


if __name__ == "__main__":
    main()
