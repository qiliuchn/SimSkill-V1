"""H3: measure START-UP and CLEARANCE lost time directly, and compare against the
assumed intergreen (yellow + all-red).

Method (extends `measure-saturation-flow-and-validate-webster-method`):
  * permanently oversaturated approach -> every green is served from a standing queue
  * instantInductionLoop at the stop line, REAR-bumper crossings (state="leave"), the
    HCM/Teply convention and the only one defined for the first vehicle in queue
  * TraCI supplies the exact green-onset / yellow-onset / red-onset times for each cycle
  * per cycle:  h_n  = headway of the n-th discharging vehicle
                h_s  = mean headway over a saturated window of n  (primary estimator;
                       the green-duration regression is NOT used as primary because this
                       fleet is nearly deterministic -- see the skill's documented
                       integer-quantisation gotcha)
                l1   = sum_{n < window} (h_n - h_s)          start-up lost time
                N_d  = vehicles discharged in green+yellow+all-red
                g_eff = N_d * h_s                             effective green
                L    = (g + y + ar) - g_eff                   TOTAL lost time
                l2   = L - l1                                 clearance lost time
The comparison of interest is L (measured) versus (y + ar) (the value Webster's method is
almost always fed).
"""
import argparse
import json
import os
import statistics as st
import xml.etree.ElementTree as ET
from multiprocessing import Pool

from common import ANA_DIR, RUN_DIR, SUMO, add_tools_to_path
from build_net import build
import sim_rig

add_tools_to_path()
import traci  # noqa: E402


NETS = {}


def get_meta(speed):
    """Nets are pre-built in main() before the Pool starts; workers only READ the meta,
    so several workers never race to write the same .net.xml."""
    key = round(speed, 3)
    if key not in NETS:
        NETS[key] = json.load(open(os.path.join(
            os.path.dirname(build.__globals__["NET_DIR"]), "net",
            "lt_v%.0f.meta.json" % (speed * 100))))
    return NETS[key]


def run_one(args):
    yellow, allred, green, seed, speed, truck_share = args
    name = "LT_y%.1f_ar%.1f_g%.0f_v%.2f_t%.2f_s%d" % (yellow, allred, green, speed,
                                                      truck_share, seed)
    rd = os.path.join(RUN_DIR, name)
    if os.path.exists(os.path.join(rd, "lt.json")):
        return json.load(open(os.path.join(rd, "lt.json")))
    os.makedirs(rd, exist_ok=True)
    meta = get_meta(speed)
    cycle = 2 * (green + yellow + allred)
    cfg = dict(cycle=cycle, yellow=yellow, allred=allred, greens=(green, green),
               vph=4000, demand_end=1500, sim_end=1800, seed=seed, step_length=0.1,
               warmup=300, ssm=False, detectors=True, ttt=-1, truck_share=truck_share,
               car_over=dict(decel="4.5", actionStepLength="0.1"),
               extra_args=["--max-depart-delay", "60"])
    add_p, rou_p, phases, idx = sim_rig.write_inputs(rd, meta, cfg)
    cmd = sim_rig.sumo_cmd(rd, meta, cfg, add_p, rou_p)

    n = meta["n_tls_links"]
    ns_links = sorted(meta["links_by_arm"]["N"] + meta["links_by_arm"]["S"])
    li = meta["links_by_arm"]["N"][0]
    traci.start(cmd, label=name)
    c = traci.getConnection(name)
    c.trafficlight.setProgram("C", "custom")
    c.trafficlight.setPhase("C", 0)
    events = []          # (t, kind) kind in {G,Y,R}
    q_at_green = {}
    prev = None
    t = 0.0
    qlen = []
    try:
        while t < cfg["sim_end"]:
            c.simulationStep()
            t = c.simulation.getTime()
            s = c.trafficlight.getRedYellowGreenState("C")[li]
            if prev is not None and s != prev:
                events.append((round(t, 2), s))
                if s in "gG":
                    # standing queue at the instant of green onset -- the independent check
                    # that this cycle was served from a queue that never ran out
                    q_at_green[round(t, 2)] = c.lane.getLastStepHaltingNumber("in_N_0")
            prev = s
            if abs(t - round(t)) < 1e-6 and t > cfg["warmup"]:
                qlen.append(c.lane.getLastStepHaltingNumber("in_N_0"))
    finally:
        try:
            c.close()
        except Exception:
            pass

    # instant loop: rear-bumper stop-line crossings on in_N_0
    inst = os.path.join(rd, "instant.xml")
    leaves = []
    for _, el in ET.iterparse(inst, events=("end",)):
        if el.tag == "instantOut" and el.get("state") == "leave" and el.get("id") == "il_in_N_0":
            leaves.append((float(el.get("time")), el.get("vehID")))
        el.clear()
    leaves.sort()

    # cycles: green onset -> next green onset
    greens = [t0 for t0, s in events if s in "gG" and t0 > cfg["warmup"]]
    yells = [t0 for t0, s in events if s in "yY"]
    reds = [t0 for t0, s in events if s == "r"]
    cycles = []
    for gi, g0 in enumerate(greens[:-1]):
        g_end = min([x for x in yells if x > g0], default=None)
        if g_end is None:
            continue
        r_end = min([x for x in greens if x > g0], default=None)
        xs = [tt for tt, _ in leaves if g0 <= tt < r_end]
        if len(xs) < 4:
            continue
        h = [xs[0] - g0] + [xs[k] - xs[k - 1] for k in range(1, len(xs))]
        cycles.append(dict(g0=g0, g_end=g_end, r_end=r_end, n=len(xs),
                           q_at_green=q_at_green.get(g0),
                           cross=[round(x - g0, 3) for x in xs],
                           h=[round(x, 3) for x in h],
                           n_in_green=sum(1 for x in xs if x <= g_end),
                           n_in_yellow=sum(1 for x in xs if g_end < x <= g_end + yellow),
                           n_in_allred=sum(1 for x in xs if x > g_end + yellow)))
    out = dict(name=name, yellow=yellow, allred=allred, green=green, seed=seed,
               speed=speed, truck_share=truck_share, cycle=cycle,
               n_cycles=len(cycles), cycles=cycles,
               min_halting=min(qlen) if qlen else None,
               mean_halting=st.mean(qlen) if qlen else None)
    json.dump(out, open(os.path.join(rd, "lt.json"), "w"))
    sim_rig.prune_run(rd, keep=("lt.json", "extra.add.xml", "plan.json", "stats.xml",
                                "summary.xml", "sumo.err", "demand.rou.xml"))
    return out


def estimate(cycles, window=(5, 12), yellow=0.0, allred=0.0, green=0.0, require_queue=True):
    """Headway-position estimator + lost-time decomposition.

    Only cycles whose standing queue at green onset was at least as long as the number of
    vehicles that actually discharged are used -- otherwise the queue ran out mid-green and
    N_d underestimates the effective green, which would inflate the measured lost time."""
    n_all = len(cycles)
    if require_queue:
        cycles = [c for c in cycles
                  if c.get("q_at_green") is not None and c["q_at_green"] >= c["n"]]
    if not cycles:
        return None
    maxn = max(len(c["h"]) for c in cycles)
    prof = []
    for k in range(maxn):
        vals = [c["h"][k] for c in cycles if len(c["h"]) > k]
        if len(vals) >= max(3, 0.3 * len(cycles)):
            prof.append((k + 1, st.mean(vals), st.pstdev(vals), len(vals)))
    sat = [m for k, m, s, nn in prof if window[0] <= k <= window[1]]
    if not sat:
        return None
    h_s = st.mean(sat)
    l1 = sum(m - h_s for k, m, s, nn in prof if k < window[0])
    nd = [c["n"] for c in cycles]
    n_mean = st.mean(nd)
    g_eff = n_mean * h_s
    L = (green + yellow + allred) - g_eff
    return dict(n_cycles_used=len(cycles), n_cycles_all=n_all,
                mean_q_at_green=st.mean([c["q_at_green"] for c in cycles]),
                h_s=h_s, sat_flow=3600.0 / h_s, l1=l1, N_d=n_mean,
                N_d_sd=st.pstdev(nd), g_eff=g_eff, L_total=L, l2=L - l1,
                assumed_intergreen=yellow + allred,
                L_minus_intergreen=L - (yellow + allred),
                profile=[(k, round(m, 4), round(s, 4), nn) for k, m, s, nn in prof],
                window=list(window),
                n_in_green=st.mean([c["n_in_green"] for c in cycles]),
                n_in_yellow=st.mean([c["n_in_yellow"] for c in cycles]),
                n_in_allred=st.mean([c["n_in_allred"] for c in cycles]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--procs", type=int, default=6)
    a = ap.parse_args()
    for sp in (13.89,):
        build("lt_v%.0f" % (sp * 100), speed=sp, grade_pct=0.0, lanes=1, arm=400.0)
    jobs = []
    for y in (2.0, 3.0, 4.0, 5.0, 6.0):
        for ar in (0.0, 1.0, 2.0, 3.0):
            for sd in (11, 22, 33):
                jobs.append((y, ar, 30.0, sd, 13.89, 0.0))
    # green-duration variation (secondary cross-check) and a truck-share cell
    for g in (16.0, 24.0, 32.0, 40.0):
        for sd in (11, 22, 33):
            jobs.append((3.0, 1.0, g, sd, 13.89, 0.0))
    for ts in (0.0, 0.30):
        for sd in (11, 22, 33):
            jobs.append((3.0, 1.0, 30.0, sd, 13.89, ts))
    print("lost-time jobs:", len(jobs), flush=True)
    with Pool(a.procs) as p:
        res = p.map(run_one, jobs)

    agg = {}
    for r in res:
        key = (r["yellow"], r["allred"], r["green"], r["truck_share"])
        agg.setdefault(key, []).extend(r["cycles"])
    out = []
    for (y, ar, g, ts), cyc in sorted(agg.items()):
        if not cyc:
            continue
        e = estimate(cyc, (5, 12), y, ar, g)
        if e is None:
            continue
        e.update(yellow=y, allred=ar, green=g, truck_share=ts, n_cycles=len(cyc))
        # window sensitivity, as the skill requires
        for w in ((4, 10), (6, 14), (5, 20)):
            e2 = estimate(cyc, w, y, ar, g)
            e["alt_%d_%d" % w] = dict(h_s=e2["h_s"], l1=e2["l1"], L_total=e2["L_total"])
        out.append(e)
        print("y=%.1f ar=%.1f g=%.0f ts=%.2f  h_s=%.3f s=%.0f veh/h  l1=%.2f  L=%.2f  "
              "intergreen=%.1f  L-ig=%+.2f  N_d=%.2f(y:%.2f,ar:%.2f)"
              % (y, ar, g, ts, e["h_s"], e["sat_flow"], e["l1"], e["L_total"],
                 e["assumed_intergreen"], e["L_minus_intergreen"], e["N_d"],
                 e["n_in_yellow"], e["n_in_allred"]), flush=True)
    json.dump(out, open(os.path.join(ANA_DIR, "lost_time.json"), "w"), indent=2)


if __name__ == "__main__":
    main()
