"""THE REPRESENTATION QUESTION: three ways to express the same lane closure.

  R1  rerouter  -- full 3-lane net, closure expressed as a <rerouter> containing
                   <closingLaneReroute id="fE_0" disallow="all"/> over the whole run
                   (`simulate-incident-rerouting` / [[incident-rerouting-and-closures]])
  R2  permission-- full 3-lane net, disallow="all" written directly onto lane fE_0 of
                   the COMPILED .net.xml
  R3a geom-prio -- genuinely rebuilt net: fE has 2 lanes, drop at node N4, N4 priority
  R3b geom-zip  -- same rebuild with N4 type="zipper"

Each is verified FROM THE COMPILED NET (and, for R1, from a live TraCI query, since a
rerouter closure lives in an additional file and cannot be seen in the net at all).

Measured: work-zone queue-discharge capacity, mean trip duration, hard-braking events,
teleports/collisions, and the MERGE-POSITION PROFILE -- the share of vehicles observed
in the closing lane at each E2 station along the corridor, which is what actually
distinguishes the representations' lane-change behaviour.
"""
import json
import os
import sys
from collections import defaultdict

import numpy as np

import wz_common as W
import gen_demand
import gen_additional as GA
import analyze
import run_wz

OUTD = os.path.join(W.OUT, "representation")
os.makedirs(OUTD, exist_ok=True)
STEP = 0.5


def make_rerouter_add(path, lanes, begin=0, end=100000):
    lines = ['<additional>', '  <rerouter id="wz" edges="fB">',
             f'    <interval begin="{begin}" end="{end}">']
    for ln in lanes:
        lines.append(f'      <closingLaneReroute id="{ln}" disallow="all"/>')
    lines += ['    </interval>', '  </rerouter>', '</additional>']
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return path


def merge_profile(rundir, netfile, closing_lane_idx=0):
    """Share of vehicles seen in the closing lane at each E2 station vs distance."""
    rows = analyze.read_e2(os.path.join(rundir, "e2.xml"))
    dists = GA.station_distances(netfile)
    per = defaultdict(lambda: defaultdict(float))
    for r in rows:
        if not r["id"].startswith("e2_s"):
            continue
        parts = r["id"].split("_")
        s = int(parts[1][1:])
        li = int(parts[-1][1:])
        per[s][li] += r["nveh"]
    out = []
    for s in sorted(per):
        tot = sum(per[s].values())
        if tot <= 0:
            continue
        out.append(dict(station=s, dist=dists.get(s, np.nan),
                        share_closing=per[s].get(closing_lane_idx, 0.0) / tot,
                        n=tot, nlanes=len(per[s])))
    return out


def verify(rep, netfile, add_extra, rundir):
    """Compiled-net (and live-TraCI, for R1) verification of every geometry variant."""
    t = W.net_lane_table(netfile)
    v = dict(rep=rep, net=os.path.basename(netfile),
             fE_nlanes=len(t["fE"]), fD_nlanes=len(t["fD"]),
             fE_len=round(t["fE"][0][1], 1), fD_len=round(t["fD"][0][1], 1),
             fE_lane_disallow={ln[0]: ln[4] for ln in t["fE"]},
             fD_to_fE_states=[(c["fromLane"], c["toLane"], c["state"])
                              for c in W.net_connections(netfile, "fD", "fE")])
    return v


def run_one(rep, seed, peak, p, force=False):
    lab = f"{rep}_q{peak}_s{seed}"
    od = os.path.join(OUTD, lab)
    rou, _ = gen_demand.gen(peak, 100 + seed, 0.0)
    extra = None
    if rep == "R1_rerouter":
        net = W.build_net(p, "full")
        rr = make_rerouter_add(os.path.join(OUTD, "rerouter.add.xml"), ["fE_0"])
        n_open = 2
        extra = rr
    elif rep == "R2_permission":
        src = W.build_net(p, "full")
        net = os.path.join(W.NETS, "R2_permission.net.xml")
        if not os.path.exists(net) or force:
            W.apply_permission_closure(src, net, ["fE_0"])
        n_open = 2
    elif rep == "R3a_geom_prio":
        net = W.build_net(p, "geom", merge="priority")
        n_open = 2
    elif rep == "R3b_geom_zip":
        net = W.build_net(p, "geom", merge="zipper")
        n_open = 2
    else:
        raise ValueError(rep)

    add = GA.build(net, od, lab)
    if extra:
        add = add + "," + extra
    m = run_wz.run(net, rou, add.split(",")[0] if extra is None else add,
                   od, "donothing", p, seed=seed, step=STEP)
    s = analyze.summarize(od, n_open)
    s["merge_profile"] = merge_profile(od, net)
    s["verify"] = verify(rep, net, extra, od)
    s["rep"] = rep
    s["peak"] = peak
    s["seed"] = seed
    s["hard_brakes"] = m["hard_brakes"]
    s["hard_brakes_taper"] = m["hard_brakes_taper"]
    s["freeze"] = analyze.running_freeze(od)
    return s


def live_permission_check(p):
    """R1's closure is invisible in the net -- query it live instead."""
    import traci
    net = W.build_net(p, "full")
    rr = make_rerouter_add(os.path.join(OUTD, "rerouter.add.xml"), ["fE_0"])
    rou, _ = gen_demand.gen(600, 999, 0.0)
    od = os.path.join(OUTD, "live_check")
    os.makedirs(od, exist_ok=True)
    add = GA.build(net, od, "live", e2=False, edgedata=False, emissions=False)
    traci.start([W.SUMO, "-n", net, "-r", rou, "-a", f"{add},{rr}",
                 "--end", "400", "--step-length", "1", "--no-step-log", "true",
                 "--no-warnings", "true", "--step-method.ballistic"], label="live")
    c = traci.getConnection("live")
    c.simulationStep(100)
    # NB SUMO returns an EMPTY allowed-list to mean "all vClasses permitted", so the
    # allowed list alone is ambiguous -- always read getDisallowed too.
    res = {}
    for ln in ("fE_0", "fE_1", "fE_2", "fD_0"):
        res[ln] = dict(allowed=list(c.lane.getAllowed(ln)),
                       disallowed_n=len(c.lane.getDisallowed(ln)),
                       passenger_blocked="passenger" in c.lane.getDisallowed(ln))
    res["_note"] = ("empty allowed-list means ALL permitted in SUMO; "
                    "passenger_blocked is the unambiguous test")
    c.close()
    return res


if __name__ == "__main__":
    p = W.params(lanes_closed=1)
    peak = int(sys.argv[1]) if len(sys.argv) > 1 else 3600
    seeds = (1, 2, 3, 4)
    print("--- live TraCI check of what a closingLaneReroute actually does ---")
    lc = live_permission_check(p)
    print(json.dumps(lc, indent=1))

    res = []
    for rep in ("R1_rerouter", "R2_permission", "R3a_geom_prio", "R3b_geom_zip"):
        for sd in seeds:
            r = run_one(rep, sd, peak, p)
            res.append(r)
            print(f"{rep:16s} s{sd} cap={r['cap']:.0f} dur={r['mean_duration']:.0f} "
                  f"hb_taper={r['hard_brakes_taper']} tele={r.get('teleports')} "
                  f"coll={r['n_collisions']}", flush=True)
    json.dump(dict(live_check=lc, runs=res),
              open(os.path.join(OUTD, "representation_results.json"), "w"), indent=1,
              default=float)
    print("\nwrote", os.path.join(OUTD, "representation_results.json"))
