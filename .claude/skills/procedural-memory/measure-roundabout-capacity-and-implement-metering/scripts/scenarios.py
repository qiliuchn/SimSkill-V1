"""
Demand scenarios + the metric extraction used by parts 3, 4 and 5.

Movement split on every approach: 15% right / 70% through / 15% left.

Unbalanced ("starvation") pattern
    The major axis is E-W.  E->W is the 2nd exit from E, and its path
        in_E -> rg_E -> rl_N -> rg_N -> out_W
    occupies rl_N -- the ring segment directly in front of the N ENTRY.  So a
    heavy E->W stream is exactly a dominant flow that keeps the circulatory
    roadway continuously occupied in front of the minor N entry (symmetrically,
    W->E occupies rl_S and starves the S entry).  Minor-approach volume M is held
    fixed while the dominant approach volume D is swept.

Censoring-robust delay
    (per `design-actuated-signal-detector-placement-and-fault-tolerance` and
     `validate-congested-scenario-results-against-teleport-artifacts`)
    tripinfo only holds vehicles that COMPLETED.  A starved approach's whole point
    is that its vehicles do NOT complete, so a naive tripinfo mean delay is
    survivorship-censored and can make starvation look harmless.  Here:
      * --tripinfo-output.write-unfinished captures vehicles still in the network
        at the horizon (arrival = -1)
      * --max-depart-delay -1 keeps un-inserted vehicles pending forever rather
        than silently discarding them
      * every vehicle in the analytical departure schedule that never appeared in
        tripinfo at all is charged (T_end - t_scheduled) of delay
    All three populations are reported separately as well as combined.
"""
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import vtype_xml, run_sumo, ARMS

RIGHT = {"N": "W", "W": "S", "S": "E", "E": "N"}
THRU = {"N": "S", "S": "N", "E": "W", "W": "E"}
LEFT = {"N": "E", "E": "S", "S": "W", "W": "N"}
SPLIT = dict(right=0.15, through=0.70, left=0.15)


def approach_volumes(totals):
    """totals: {arm: veh/h entering on that arm} -> {(o,d): veh/h}"""
    vol = {}
    for a, t in totals.items():
        vol[(a, RIGHT[a])] = t * SPLIT["right"]
        vol[(a, THRU[a])] = t * SPLIT["through"]
        vol[(a, LEFT[a])] = t * SPLIT["left"]
    return {k: v for k, v in vol.items() if v > 0}


def unbalanced(D, M, w_frac=0.3):
    """PEAK-DIRECTION dominant pattern.

    A symmetric two-way major axis does NOT starve a minor entry on a single-lane
    ring: the dominant entry is then itself gap-limited (its own conflicting
    stream is fed by the opposing major direction), so it can never deliver
    enough flow onto the ring to starve anybody -- measured directly, at
    E=W=1000 / N=S=400 the DOMINANT approaches had 8x the delay of the minor
    ones and the minor approaches were served 98%.

    The pattern that does starve is a one-way peak-direction dominance: the E
    approach is heavy, the opposing W approach is light.  Then
        v_c(E) = W->N + S->N + S->W          (small)   -> E enters nearly freely
        v_c(N) = 0.85*D + 0.15*M             (large)   -> N is starved
    which is exactly "a dominant flow that keeps the circulatory roadway
    continuously occupied in front of one minor entry".
    """
    return approach_volumes({"E": D, "W": w_frac * D, "N": M, "S": M})


def balanced(V):
    return approach_volumes({a: V for a in ARMS})


def write_scenario(path, vol, end, ssm=False, vtype_overrides=None, depart_lane="free"):
    """Deterministic (equally spaced) departures per OD flow -- this makes the
    analytical departure schedule below exact, which the censoring-robust delay
    metric needs.  All variants get the identical file."""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<routes>",
             vtype_xml(ssm=ssm, overrides=vtype_overrides)]
    for (o, d), v in sorted(vol.items()):
        lines.append(f'    <flow id="f_{o}{d}" type="car" from="in_{o}" to="out_{d}" '
                     f'begin="0" end="{end}" vehsPerHour="{v:.4f}" '
                     f'departLane="{depart_lane}" departSpeed="max" departPos="base"/>')
    lines.append("</routes>")
    open(path, "w").write("\n".join(lines) + "\n")
    return path


def schedule(vol, end):
    """SUMO emits a vehsPerHour flow at equal spacing; reproduce it exactly so
    never-inserted vehicles can be identified and charged."""
    sched = {}
    for (o, d), v in vol.items():
        n = int(round(v * end / 3600.0))
        if n <= 0:
            continue
        step = end / n
        sched[(o, d)] = [i * step for i in range(n)]
    return sched


def collect(outdir, vol, end):
    """returns per-arm and aggregate metrics with the three vehicle populations
    separated."""
    tri = os.path.join(outdir, "tripinfo.xml")
    seen = {}
    for _, el in ET.iterparse(tri, events=("end",)):
        if el.tag == "tripinfo":
            vid = el.get("id")
            core = vid.split(".")[0]
            o, d = core[2], core[3]
            arrived = float(el.get("arrival", -1)) >= 0
            seen.setdefault((o, d), []).append(
                dict(arrived=arrived, timeLoss=float(el.get("timeLoss")),
                     departDelay=float(el.get("departDelay")),
                     duration=float(el.get("duration")),
                     waitingTime=float(el.get("waitingTime"))))
            el.clear()
    sch = schedule(vol, end)

    per_arm = {}
    for a in ARMS:
        dem = comp = run_ = never = 0
        dsum = 0.0
        comp_tl = []
        for (o, d), times in sch.items():
            if o != a:
                continue
            dem += len(times)
            recs = seen.get((o, d), [])
            ncomp = sum(1 for r in recs if r["arrived"])
            nrun = len(recs) - ncomp
            comp += ncomp
            run_ += nrun
            for r in recs:
                dsum += r["timeLoss"] + r["departDelay"]
                if r["arrived"]:
                    comp_tl.append(r["timeLoss"] + r["departDelay"])
            k = len(times) - len(recs)          # never inserted at all
            never += max(0, k)
            for t in times[len(recs):]:         # charge the un-emitted tail
                dsum += max(0.0, end - t)
        per_arm[a] = dict(demand=dem, completed=comp, still_running=run_, never_inserted=never,
                          throughput_vph=round(comp / end * 3600.0, 1),
                          served_frac=round(comp / dem, 4) if dem else 0.0,
                          delay_robust_s=round(dsum / dem, 2) if dem else 0.0,
                          delay_completed_only_s=round(sum(comp_tl) / len(comp_tl), 2) if comp_tl else 0.0)

    tot_dem = sum(v["demand"] for v in per_arm.values())
    tot_comp = sum(v["completed"] for v in per_arm.values())
    agg = dict(demand=tot_dem, completed=tot_comp,
               still_running=sum(v["still_running"] for v in per_arm.values()),
               never_inserted=sum(v["never_inserted"] for v in per_arm.values()),
               throughput_vph=round(tot_comp / end * 3600.0, 1),
               served_frac=round(tot_comp / tot_dem, 4) if tot_dem else 0.0,
               delay_robust_s=round(sum(v["delay_robust_s"] * v["demand"] for v in per_arm.values()) / tot_dem, 2) if tot_dem else 0.0,
               delay_completed_only_s=round(
                   sum(v["delay_completed_only_s"] * v["completed"] for v in per_arm.values()) / tot_comp, 2) if tot_comp else 0.0)

    d = [per_arm[a]["delay_robust_s"] for a in ARMS]
    agg["equity_maxmin_delay_ratio"] = round(max(d) / min(d), 3) if min(d) > 0 else float("inf")
    agg["equity_gini_delay"] = gini(d)
    sf = [per_arm[a]["served_frac"] for a in ARMS]
    agg["min_approach_served_frac"] = round(min(sf), 4)
    agg["equity_gini_throughput"] = gini([per_arm[a]["throughput_vph"] for a in ARMS])

    # teleports (cumulative -> read last step, never sum)
    tel = 0
    running = []
    for _, el in ET.iterparse(os.path.join(outdir, "summary.xml"), events=("end",)):
        if el.tag == "step":
            tel = max(tel, int(float(el.get("teleports", 0))))
            running.append((float(el.get("time")), int(float(el.get("running")))))
            el.clear()
    agg["teleports"] = tel
    agg["teleport_share_of_completed"] = round(tel / tot_comp, 4) if tot_comp else 0.0
    tail = [r for t, r in running if t > 0.8 * end]
    agg["running_frozen_tail"] = bool(tail and max(tail) == min(tail) and max(tail) > 0)
    agg["running_final"] = running[-1][1] if running else 0
    return dict(per_arm=per_arm, agg=agg)


def gini(x):
    x = sorted(float(v) for v in x)
    n = len(x)
    s = sum(x)
    if n == 0 or s == 0:
        return 0.0
    cum = sum((2 * (i + 1) - n - 1) * v for i, v in enumerate(x))
    return round(cum / (n * s), 4)
