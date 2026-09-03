"""Stage 4a: calibrate the published timetable's running speed, then find the
measured cycle time C_l of every line under each route structure by a short
fixed-point (allocation -> run -> measured C -> allocation).  Produces
work/runspeeds.json, work/cycles.json, work/linedemand.json and the
bus-hour budget audit."""
import os, sys, json, math
import tspcore as T
from tspcore import WORK, ensure
import plans as P
import harness as H
import alloc as A

BUDGET = int(os.environ.get("BUDGET", "24"))    # bus-hours == buses (1 h span)


def main():
    net = T.Net(os.path.join(WORK, "base.net.xml"))
    speeds, cycles, demand, audits = {}, {}, {}, {}

    for name in ("coverage", "trunkfeeder", "freqgrid"):
        ids = [l[0] for l in P.PLAN_DEFS[name]]
        plan0 = P.make_plan(name, buses={l: 2 for l in ids})
        sp, info = T.calibrate_run_speed(plan0, net, WORK)
        speeds[name] = sp
        print(f"\n=== {name} ===")
        print("  uncongested cycle:", {k: round(v['free_cycle']) for k, v in info.items()})

        # provisional C from the uncongested run + layover, then two refinements
        C = {k: info[k]["free_cycle"] * 1.15 + max(T.LAYOVER_FRAC * info[k]["free_cycle"],
                                                   T.LAYOVER_MIN) for k in ids}
        Q = {l: 1.0 for l in ids}
        for it in range(3):
            if it == 0:
                buses, ok, msg = A.equal_rule(BUDGET, C, ids)
            else:
                buses, ok, msg = A.sqrt_rule(BUDGET, C, Q, ids)
            if not ok:
                print("  ALLOCATION", msg); sys.exit(1)
            tag = f"ref_{name}_it{it}"
            m = H.evaluate_many([(name, buses, 1, None, C, sp, tag, False)], workers=1)[0]
            if "error" in m:
                print(m["tb"]); sys.exit(1)
            newC = {k: (m["cycles_C"][k] or C[k]) for k in ids}
            Q = {k: max(1.0, m["boardings"].get(k, 1.0)) for k in ids}
            dmax = max(abs(newC[k] - C[k]) for k in ids)
            print(f"  it{it}: buses={buses}  meanCycle="
                  f"{sum(v for v in m['cycles'].values() if v)/len(ids):.0f}  "
                  f"maxdC={dmax:.0f}  boardings={Q}")
            C = newC
        cycles[name] = C
        demand[name] = Q

        # bus-hour budget audit at the final reference allocation
        plan = H.make(name, buses, C)
        audits[name] = dict(
            budget_bus_hours=BUDGET * T.BUS_HOUR_SPAN_H,
            buses=buses, cycles_C=C,
            headways={l: C[l] / buses[l] for l in ids},
            headway_used={l: C[l] / buses[l] for l in ids},
            required_from_measured_cycle={
                l: (math.ceil(m["cycles_C"][l] / (C[l] / buses[l]))
                    if m["cycles_C"].get(l) else None) for l in ids},
            observed_max_concurrent=m["max_concurrent_line"],
            observed_max_concurrent_total=m["max_concurrent_total"],
            allocated_total=sum(buses.values()))
        print("  AUDIT allocated per line :", buses)
        print("  AUDIT observed concurrent:", m["max_concurrent_line"],
              " total", m["max_concurrent_total"], "vs allocated", sum(buses.values()))

    for p, o in ((speeds, H.SPEED_FILE), (cycles, H.CYCLE_FILE),
                 (demand, os.path.join(WORK, "linedemand.json")),
                 (audits, os.path.join(WORK, "budget_audit.json"))):
        with open(o, "w") as f:
            json.dump(p, f, indent=1)
    print("\nwritten cycles.json / runspeeds.json / linedemand.json / budget_audit.json")


if __name__ == "__main__":
    main()
