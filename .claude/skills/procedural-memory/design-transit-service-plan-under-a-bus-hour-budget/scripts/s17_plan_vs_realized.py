"""How optimistic is duarouter's a-priori intermodal plan, once the buses are
actually simulated in mixed traffic?

Compares, person by person, the plan written by duarouter (planned boarding
times and planned number of rides) against what <personinfo> reports after the
simulation.  This is the quantitative form of the semantic that the published
timetable is built from UNCONGESTED running times, so `until` is (almost) never
binding and the router's plan is systematically early.
"""
import os, sys, json, statistics as st
import xml.etree.ElementTree as ET
import tspcore as T
from tspcore import WORK
import harness as H

OUTJ = os.path.join(WORK, "plan_vs_realized.json")


def planned(routed):
    out = {}
    r = ET.parse(routed).getroot()
    for p in r.findall("person"):
        rides = [c for c in p if c.tag == "ride"]
        out[p.get("id")] = dict(
            n_rides=len(rides),
            first_board=float(rides[0].get("depart")) if rides else None,
            vehicles=[c.get("intended") for c in rides],
            depart=float(p.get("depart")))
    return out


def main():
    s4 = H.load_json(os.path.join(WORK, "stage4_compare.json"))
    res = {}
    for name, d in s4["summary"].items():
        pl = planned(os.path.join(os.path.dirname(d["dirs"][0]),
                                  "persons.routed.rou.xml"))
        slips, nride_match, nride_more, nride_less, tot = [], 0, 0, 0, 0
        stranded_but_planned = 0
        for run in d["dirs"]:
            f = os.path.join(run, "persons.json")
            if not os.path.exists(f):
                continue
            for r in json.load(open(f)):
                p = pl.get(r["id"])
                if not p:
                    continue
                tot += 1
                if p["n_rides"] == r["n_ride_legs_planned"]:
                    nride_match += 1
                if r["stranded"]:
                    stranded_but_planned += 1
                if r["mode"] == "transit" and p["first_board"] is not None:
                    realized_board = r["depart"] + r["access"] + r["wait"]
                    slips.append(realized_board - p["first_board"])
        res[name] = dict(
            n=tot,
            plan_ride_count_matches_share=nride_match/max(1, tot),
            stranded_share=stranded_but_planned/max(1, tot),
            boarding_slip_mean=st.mean(slips) if slips else None,
            boarding_slip_median=st.median(slips) if slips else None,
            boarding_slip_p90=sorted(slips)[int(0.9*len(slips))] if slips else None,
            share_boarded_later_than_planned=sum(1 for s in slips if s > 1)/max(1, len(slips)))
        print(f"{name:12s} n={tot:5d}  plan ride-count matches {res[name]['plan_ride_count_matches_share']*100:5.1f}%  "
              f"boarding slip mean {res[name]['boarding_slip_mean']:7.1f}s "
              f"median {res[name]['boarding_slip_median']:7.1f}s "
              f"p90 {res[name]['boarding_slip_p90']:7.1f}s  "
              f"boarded later than planned {res[name]['share_boarded_later_than_planned']*100:5.1f}%  "
              f"stranded {res[name]['stranded_share']*100:4.1f}%")
    with open(OUTJ, "w") as f:
        json.dump(res, f, indent=1)
    print("written", OUTJ)


if __name__ == "__main__":
    main()
