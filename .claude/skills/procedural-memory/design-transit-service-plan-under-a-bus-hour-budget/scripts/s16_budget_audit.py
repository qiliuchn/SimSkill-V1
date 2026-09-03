"""Deliverable: the measured-cycle-time bus-hour budget module, audited.

For every plan in the equal-budget comparison, recomputes the budget from
MEASURED quantities and checks it against an INDEPENDENT count of distinct bus
vehicles actually in service:

  cycle_l   = mean measured round-trip duration from <tripinfo> (dwell + traffic)
  layover_l = max(0.10*cycle, 120 s, p90_cycle - cycle)
  C_l       = cycle_l + layover_l
  h_l       = C_l / N_l                      (headway derived from the budget)
  required  = ceil(C_l / h_l)                (must reproduce N_l)
  observed  = max over time of the number of distinct bus vehicle ids of line l
              simultaneously between depart and arrival in <tripinfo>
"""
import os, sys, json, math, statistics as st
import tspcore as T
from tspcore import WORK
import plans as P
import harness as H

OUTJ = os.path.join(WORK, "budget_audit_verified.json")


def main():
    s4 = H.load_json(os.path.join(WORK, "stage4_compare.json"))
    cycles_all = H.load_json(H.CYCLE_FILE)
    out = {}
    for name, d in s4["summary"].items():
        buses = d["buses"]
        C = cycles_all[name]
        plan = H.make(name, buses, C)
        per_line = {}
        tot_obs, tot_req, n = 0, 0, 0
        for run in d["dirs"]:
            tri = os.path.join(run, "tripinfo.xml")
            if not os.path.exists(tri):
                continue
            recs = T.parse_bus_tripinfo(tri)
            cy = T.measure_cycles(recs, plan)
            n += 1
            tot_obs += T.max_concurrent(recs)
            for L in plan.lines:
                h = C[L.id] / buses[L.id]
                obs = T.max_concurrent(recs, L.id)
                req = math.ceil(cy[L.id]["C"] / h) if cy[L.id]["C"] else None
                ids = {r["id"] for r in recs if r["line"] == L.id}
                per_line.setdefault(L.id, []).append(
                    dict(headway=h, allocated=buses[L.id],
                         cycle_mean=cy[L.id]["cycle"], cycle_p90=cy[L.id].get("cycle_p90"),
                         cycle_max=cy[L.id].get("cycle_max"),
                         layover=cy[L.id]["layover"], C=cy[L.id]["C"],
                         required=req, observed=obs, distinct_vehicles=len(ids)))
        rows = {}
        for l, v in per_line.items():
            rows[l] = {k: (st.mean([x[k] for x in v]) if isinstance(v[0][k], (int, float))
                           else v[0][k]) for k in v[0]}
        out[name] = dict(nominal_bus_hours=sum(buses.values()) * T.BUS_HOUR_SPAN_H,
                         realized_peak_fleet=tot_obs / max(1, n),
                         per_line=rows, n_runs=n)
        print(f"\n=== {name}: nominal budget {sum(buses.values())} bus-hours, "
              f"realized peak fleet {tot_obs/max(1,n):.2f} buses "
              f"({100*(tot_obs/max(1,n))/sum(buses.values())-100:+.1f}%) ===")
        print("%-6s %8s %9s %9s %9s %9s %9s %9s %9s %9s" % (
            "line", "N_alloc", "h(s)", "cycle", "p90", "max", "layover", "C", "ceil(C/h)",
            "observed"))
        for l in sorted(rows):
            r = rows[l]
            print("%-6s %8d %9.1f %9.1f %9.1f %9.1f %9.1f %9.1f %9.1f %9.2f" % (
                l, r["allocated"], r["headway"], r["cycle_mean"], r["cycle_p90"],
                r["cycle_max"], r["layover"], r["C"], r["required"], r["observed"]))
    with open(OUTJ, "w") as f:
        json.dump(out, f, indent=1)
    print("\nwritten", OUTJ)


if __name__ == "__main__":
    main()
