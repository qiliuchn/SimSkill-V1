"""Stage 2 smoke test: compile one service plan, route persons intermodally,
simulate, and report the basic quantities + wall-clock cost."""
import os, sys, time, json, collections
import tspcore as T
from tspcore import WORK, ensure
import plans as P

def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "coverage"
    nb = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    net = T.Net(os.path.join(WORK, "base.net.xml"))
    plan = P.make_plan(name, buses={l[0]: nb for l in P.PLAN_DEFS[name]})
    sd = ensure(os.path.join(WORK, "smoke", name))
    t0 = time.time()
    comp = T.compile_plan(plan, net, sd)
    print(f"compile {time.time()-t0:.1f}s  stops={len(comp['stops'])} "
          f"headways={ {k: round(v['headway']) for k, v in comp['sched'].items()} }")
    t0 = time.time()
    routed = T.route_persons(net, comp, os.path.join(WORK, "persons.trips.xml"), sd)
    print(f"duarouter {time.time()-t0:.1f}s")
    t0 = time.time()
    res = T.simulate(net, comp, routed, [os.path.join(WORK, "cars.rou.xml")],
                     os.path.join(sd, "run1"), seed=1)
    print(f"sumo {time.time()-t0:.1f}s")

    pis = T.parse_personinfos(res["tripinfo"])
    nrides = sum(1 for p in pis if p["n_rides"] > 0)
    print(f"persons in output: {len(pis)}  with >=1 ride: {nrides}  "
          f"walk-only: {len(pis)-nrides}")
    print("transfers:", collections.Counter(p['n_transfers'] for p in pis if p['n_rides']))
    comp_n = sum(1 for p in pis if p["complete"])
    print(f"complete: {comp_n}  incomplete: {len(pis)-comp_n}")
    bus = T.parse_bus_tripinfo(res["tripinfo"])
    cyc = T.measure_cycles(bus, plan)
    for k, v in cyc.items():
        print(f"  {k}: n={v['n']} cycle={v['cycle'] and round(v['cycle'])} "
              f"C={v['C'] and round(v['C'])}")
    print("cars:", T.parse_car_stats(res["tripinfo"]))
    print("teleports:", T.teleport_count(res["log"]))
    tr = [p for p in pis if p["mode"] == "transit" and p["complete"]]
    if tr:
        print("mean access %.0f wait %.0f ivt %.0f xwalk %.0f xwait %.0f egress %.0f" % (
            sum(p['access'] for p in tr)/len(tr), sum(p['wait'] for p in tr)/len(tr),
            sum(p['ivt'] for p in tr)/len(tr), sum(p['xwalk'] for p in tr)/len(tr),
            sum(p['xwait'] for p in tr)/len(tr), sum(p['egress'] for p in tr)/len(tr)))

if __name__ == "__main__":
    main()
