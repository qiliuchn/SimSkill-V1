#!/usr/bin/env python3
"""
Run ONE sweep cell (bay length x left share x signal condition x seed) and
measure the two left-turn-bay failure modes DIRECTLY from per-step vehicle
state, plus throughput and per-movement delay.

--------------------------------------------------------------------------
THE TWO FAILURE MODES (measured separately, from raw per-vehicle state)
--------------------------------------------------------------------------
(a) BAY OVERFLOW -- the bay is physically full, so a left-turner has to stop
    in the UPSTREAM THROUGH-ONLY lane, where it blocks through traffic.
    Detected when, in the same simulation second:
        * the bay lane's rearmost vehicle is stopped with its tail within
          BAY_ENTRANCE_TOL m of the bay entrance  (=> bay is full), AND
        * at least one vehicle whose intended movement is LEFT is stopped
          (v < 0.1 m/s) on the upstream through-only lane.
    Damage measured as `overflow_thru_blocked_vs`: vehicle-seconds of
    through/right vehicles stopped BEHIND (upstream of) that stopped
    left-turner -- i.e. through traffic that a bay overflow is holding up.

(b) BAY BLOCKAGE / STARVATION -- the bay has room, but a through queue has
    grown past the bay entrance, so left-turners cannot reach the bay.
    Detected when, in the same simulation second:
        * the bay is NOT full, AND
        * a left-turner is stopped on the upstream lane, AND
        * at least one THROUGH/RIGHT vehicle is stopped AHEAD of it
          (between it and the bay entrance).
    The wasted green is measured two ways during the NS protected-left phase:
        `blocked_left_green_s`   -- left arrow green while a left-turner is
                                    stuck behind a stopped through queue
        `starved_left_green_s`   -- left arrow green while the bay is EMPTY
                                    near the stop line AND >=1 left-turner is
                                    waiting upstream (green with nothing to
                                    serve, purest starvation signal)

Both are also accumulated as sets of distinct vehicle ids, and reported as
per-cycle event rates (events / number of NS-left cycles in the window).

Also emitted, for independent verification by a third party:
  * lane-usage traces: which of in_N_bay_0 / in_N_bay_1 each N-approach
    vehicle actually occupied (proves the bay geometry restricts movements)
  * teleport counts (SUMO's gridlock-resolution machinery)
  * optional full FCD + lane-occupancy raw output
"""
import argparse
import csv
import json
import os
import sys

TOOLS = os.path.join(os.environ.get(
    "SUMO_HOME", "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo"),
    "tools")
if TOOLS not in sys.path:
    sys.path.append(TOOLS)
import traci  # noqa: E402

WARMUP = 600.0          # s discarded (initialisation transient)
DEMAND_END = 3600.0     # s demand stops
SIM_END = 4500.0        # s run on to flush the network
BAY_ENTRANCE_TOL = 7.5  # m; one vehicle slot (length 5 + minGap 2.5)
STOP_SPEED = 0.1        # m/s
STOPLINE_ZONE = 15.0    # m upstream of stop line = "able to discharge now"
NS_LEFT_PHASE = 0


def run(net, rou, tls_add, program, seed, outdir, ttt=300, fcd=False, label="cell",
        keep_raw=True):
    os.makedirs(outdir, exist_ok=True)
    trip = os.path.join(outdir, "tripinfo.xml")
    summ = os.path.join(outdir, "summary.xml")

    full_variant = program is not None and _is_full(net)
    up_lane = "in_N_bay_0" if full_variant else "in_N_up_0"
    thru_lane = "in_N_bay_0"      # the through lane of the bay section
    bay_lane = "in_N_bay_1"
    bay_len = _lane_len(net, bay_lane)
    up_len = _lane_len(net, up_lane)

    cmd = ["sumo", "-n", net, "-r", rou, "-a", tls_add,
           "--begin", "0", "--end", str(SIM_END),
           "--step-length", "1",
           "--seed", str(seed),
           "--time-to-teleport", str(ttt),
           "--tripinfo-output", trip,
           "--tripinfo-output.write-unfinished", "true",
           "--summary-output", summ,
           "--no-step-log", "true",
           "--duration-log.disable", "true",
           "--xml-validation", "never",
           "--waiting-time-memory", "10000"]
    if fcd:
        cmd += ["--fcd-output", os.path.join(outdir, "fcd.xml"),
                "--fcd-output.attributes", "id,x,y,speed,lane,pos",
                "--device.fcd.begin", str(WARMUP), "--device.fcd.period", "1"]

    traci.start(cmd, label=label)
    c = traci.getConnection(label)
    c.trafficlight.setProgram("C", program)

    # ---- accumulators -------------------------------------------------
    ev = dict(overflow_s=0.0, blockage_s=0.0, bay_full_s=0.0,
              overflow_thru_blocked_vs=0.0,
              blocked_left_green_s=0.0, starved_left_green_s=0.0,
              left_green_s=0.0, ns_thru_green_s=0.0,
              overflow_during_left_green_s=0.0,
              thru_blocked_during_ns_green_vs=0.0)
    overflow_veh, blockage_veh = set(), set()
    overflow_cycles, blockage_cycles = set(), set()
    cycles = 0
    prev_phase = None
    cyc_idx = -1
    cycle_starts = []

    served = dict(L=0, T=0, R=0)          # N-approach vehicles crossing the stop line
    prev_edge = {}
    lane_use = {}                          # N vehicle -> set of in_N_bay lanes occupied
    up_lane_use = {}                       # N vehicle -> did it occupy the upstream lane
    max_left_queue_up = 0                  # peak # of left-turners stopped upstream
    left_queue_bay_samples = []            # per-cycle max bay-lane occupancy (veh)
    # UNCENSORED left-turn queue: per-cycle maximum back-of-queue distance from
    # the stop line (m) and vehicle count over ALL stopped left-turners --
    # those in the bay AND any spilled back onto the upstream lane. This is the
    # quantity the "1.5-2x the 95th-percentile left queue" design rule refers
    # to; counting only what fits inside the bay would censor the observation
    # at the bay's own capacity and make the rule look self-fulfilling.
    left_q_m_samples = []
    left_q_n_samples = []
    # Queue measured on the EXCLUSIVE LEFT LANE only. On the full-length-lane
    # control this is the unconstrained left-turn queue the design rule of
    # thumb refers to; on a finite bay it is censored at L by construction and
    # is therefore only used as a diagnostic there.
    bayonly_q_m_samples = []
    bayonly_q_left_samples = []
    thru_q_m_samples = []
    cyc_bq_m = 0.0
    cyc_bq_left = 0
    cyc_tq_m = 0.0
    cyc_bay_max = 0
    cyc_q_m = 0.0
    cyc_q_n = 0
    teleports = 0

    # Only NORTH-approach vehicles can ever occupy in_N_up / in_N_bay, so
    # subscribing just those vehicles gives the complete state of both lanes in
    # ONE call per step instead of ~3 calls per vehicle per step.
    import traci.constants as tc
    SUB = [tc.VAR_ROAD_ID, tc.VAR_LANE_ID, tc.VAR_LANEPOSITION, tc.VAR_SPEED]
    VEH_LEN = 5.0   # vType "car" length, constant

    step = 0.0
    while step < SIM_END:
        c.simulationStep()
        step = c.simulation.getTime()
        teleports += c.simulation.getStartingTeleportNumber()

        phase = c.trafficlight.getPhase("C")
        if prev_phase is not None and phase == NS_LEFT_PHASE and prev_phase != NS_LEFT_PHASE:
            if WARMUP <= step < DEMAND_END:
                cycles += 1
                cyc_idx += 1
                cycle_starts.append(step)
                left_queue_bay_samples.append(cyc_bay_max)
                left_q_m_samples.append(cyc_q_m)
                left_q_n_samples.append(cyc_q_n)
                bayonly_q_m_samples.append(cyc_bq_m)
                bayonly_q_left_samples.append(cyc_bq_left)
                thru_q_m_samples.append(cyc_tq_m)
            cyc_bay_max = 0
            cyc_q_m = 0.0
            cyc_q_n = 0
            cyc_bq_m = 0.0
            cyc_bq_left = 0
            cyc_tq_m = 0.0
        prev_phase = phase

        for vid in c.simulation.getDepartedIDList():
            if vid.startswith("N_"):
                c.vehicle.subscribe(vid, SUB)
        subs = c.vehicle.getAllSubscriptionResults()

        # ---- track N-approach vehicles: lane usage + stop-line throughput ----
        bay_state, up_state, thru_state = [], [], []
        for vid, d in subs.items():
            e = d[tc.VAR_ROAD_ID]
            ln = d[tc.VAR_LANE_ID]
            if ln.startswith("in_N_bay_"):
                lane_use.setdefault(vid, set()).add(ln)
            if ln == bay_lane:
                bay_state.append((d[tc.VAR_LANEPOSITION], d[tc.VAR_SPEED], vid))
            elif ln == up_lane:
                up_state.append((d[tc.VAR_LANEPOSITION], d[tc.VAR_SPEED], vid))
            if ln == thru_lane:
                thru_state.append((d[tc.VAR_LANEPOSITION], d[tc.VAR_SPEED], vid))
            pe = prev_edge.get(vid, "__new__")
            if pe == "in_N_bay" and e != "in_N_bay":
                if WARMUP <= step < DEMAND_END:
                    served[vid.split("_")[1].split(".")[0]] += 1
                prev_edge.pop(vid, None)
                c.vehicle.unsubscribe(vid)
            else:
                prev_edge[vid] = e

        # ---- per-second failure-mode instrumentation ----
        cyc_bay_max = max(cyc_bay_max, len(bay_state))
        if not (WARMUP <= step < DEMAND_END):
            continue

        # bay state
        bay_full = False
        bay_near_stopline = any(p > bay_len - STOPLINE_ZONE for p, _, _ in bay_state)
        if bay_state:
            tmin = min(p - VEH_LEN for p, _, _ in bay_state)
            slow = min(s for _, s, _ in bay_state) < 1.0
            bay_full = (tmin < BAY_ENTRANCE_TOL) and slow
        if bay_full:
            ev["bay_full_s"] += 1.0

        # upstream lane state
        stopped_left, stopped_thru = [], []
        for p, sp, v in up_state:
            if sp >= STOP_SPEED:
                continue
            (stopped_left if v.startswith("N_L") else stopped_thru).append((p, v))
        if len(stopped_left) > max_left_queue_up:
            max_left_queue_up = len(stopped_left)

        # ---- left-turn queue: CONTIGUOUS back-of-queue from the stop line ----
        # Walking outward from the stop line and stopping at the first moving
        # vehicle or first oversized gap. A naive "rearmost stopped vehicle"
        # measure is corrupted by vehicles that momentarily stop far upstream
        # for unrelated reasons (insertion, lane changing) and is not a queue.
        GAP_TOL = 12.0      # m; larger than one stopped slot (7.5 m)

        def walk(states, lane_end, start_ref):
            """states: [(pos, speed, id)]; returns (tail_pos, n, n_left) of the
            contiguous stopped queue reaching back from `start_ref`."""
            ref, n, nl = start_ref, 0, 0
            for p, sp, _v in sorted(states, key=lambda t: -t[0]):
                if p > ref:
                    continue
                if sp >= STOP_SPEED or (ref - p) > GAP_TOL:
                    break
                ref = p - VEH_LEN
                n += 1
                if _v.startswith("N_L"):
                    nl += 1
            return ref, n, nl

        bay_tail, n_bay_q, n_bay_left = walk(bay_state, bay_len, bay_len)
        # LEFT-TURNERS ONLY in that queue. On the full-length-lane control,
        # through vehicles can legally sit in the left lane while the through
        # lane is jammed (they merge back before the stop line), which would
        # contaminate a design-queue measured as raw metres of occupancy; the
        # left-vehicle count x 7.5 m slot is immune to that.
        if n_bay_left > cyc_bq_left:
            cyc_bq_left = n_bay_left
        q_bay_m = max(0.0, bay_len - bay_tail)
        if q_bay_m > cyc_bq_m:
            cyc_bq_m = q_bay_m

        q_m, q_n = q_bay_m, n_bay_q
        # if the bay queue has reached the bay entrance, continue the walk onto
        # the upstream lane to recover the UNCENSORED left-turn queue
        if not full_variant and bay_tail <= GAP_TOL and up_state:
            up_tail, n_up, _nl = walk(up_state, up_len, up_len)
            if n_up:
                q_m = bay_len + max(0.0, up_len - up_tail)
                q_n = n_bay_q + n_up
        if q_m > cyc_q_m:
            cyc_q_m = q_m
        if q_n > cyc_q_n:
            cyc_q_n = q_n

        # ---- THROUGH queue, same contiguous walk, measured back from the stop
        # line along the through lane and (if it reaches the bay entrance) on
        # into the upstream lane. This is what has to be SHORTER than the bay
        # for left-turners to still be able to reach the bay entrance, so it is
        # the quantity that governs failure mode (b) -- and it is a completely
        # different quantity from the left queue the design rule sizes against.
        t_tail, t_n, _ = walk(thru_state, bay_len, bay_len)
        tq_m = max(0.0, bay_len - t_tail)
        if not full_variant and t_tail <= GAP_TOL and up_state:
            u_tail, u_n, _ = walk(up_state, up_len, up_len)
            if u_n:
                tq_m = bay_len + max(0.0, up_len - u_tail)
        if tq_m > cyc_tq_m:
            cyc_tq_m = tq_m

        is_left_green = (phase == NS_LEFT_PHASE)
        if is_left_green:
            ev["left_green_s"] += 1.0
        if phase == 2:
            ev["ns_thru_green_s"] += 1.0

        if stopped_left:
            headmost_left = max(p for p, _ in stopped_left)   # closest to the bay entrance
            if bay_full:
                # ---------- (a) BAY OVERFLOW ----------
                ev["overflow_s"] += 1.0
                if is_left_green:
                    ev["overflow_during_left_green_s"] += 1.0
                for _, v in stopped_left:
                    overflow_veh.add(v)
                overflow_cycles.add(cyc_idx)
                blocked = sum(1 for p, _ in stopped_thru if p < headmost_left)
                ev["overflow_thru_blocked_vs"] += blocked
                if phase == 2:
                    ev["thru_blocked_during_ns_green_vs"] += blocked
            else:
                # ---------- (b) BAY BLOCKAGE / STARVATION ----------
                ahead = [p for p, _ in stopped_thru if p > headmost_left]
                if ahead:
                    ev["blockage_s"] += 1.0
                    for _, v in stopped_left:
                        blockage_veh.add(v)
                    blockage_cycles.add(cyc_idx)
                    if is_left_green:
                        ev["blocked_left_green_s"] += 1.0
            # purest starvation signal: left arrow green, nothing in the bay near
            # the stop line to discharge, yet left-turners are waiting upstream
            if is_left_green and not bay_near_stopline:
                ev["starved_left_green_s"] += 1.0

    n_running_end = c.simulation.getMinExpectedNumber()
    c.close()

    # ---- lane-usage verification (geometry actually restricts movements?) ----
    viol_left_in_thru = sorted(v for v, s in lane_use.items()
                               if v.startswith("N_L") and "in_N_bay_0" in s)
    viol_thru_in_bay = sorted(v for v, s in lane_use.items()
                              if not v.startswith("N_L") and "in_N_bay_1" in s)
    left_used_bay = sum(1 for v, s in lane_use.items()
                        if v.startswith("N_L") and "in_N_bay_1" in s)
    n_left_seen = sum(1 for v in lane_use if v.startswith("N_L"))
    n_other_seen = sum(1 for v in lane_use if not v.startswith("N_L"))

    mean_cycle = ((cycle_starts[-1] - cycle_starts[0]) / (len(cycle_starts) - 1)
                  if len(cycle_starts) > 1 else float("nan"))
    res = dict(
        bay_len=bay_len, up_len=up_len, cycles=cycles, mean_cycle_s=mean_cycle,
        served_L=served["L"], served_T=served["T"], served_R=served["R"],
        teleports=teleports, running_at_end=n_running_end,
        overflow_veh=len(overflow_veh), blockage_veh=len(blockage_veh),
        overflow_cycles=len([x for x in overflow_cycles if x >= 0]),
        blockage_cycles=len([x for x in blockage_cycles if x >= 0]),
        max_left_queue_up=max_left_queue_up,
        bay_q_samples=left_queue_bay_samples,
        left_q_m_samples=left_q_m_samples,
        bayonly_q_m_samples=bayonly_q_m_samples,
        bayonly_q_left_samples=bayonly_q_left_samples,
        thru_q_m_samples=thru_q_m_samples,
        q95_thru_queue_m=(float(__import__("statistics").quantiles(thru_q_m_samples, n=20)[-1])
                          if len(thru_q_m_samples) > 3 else float("nan")),
        mean_thru_queue_m=(sum(thru_q_m_samples) / len(thru_q_m_samples)
                           if thru_q_m_samples else float("nan")),
        q95_bayonly_left_veh=(float(__import__("statistics").quantiles(bayonly_q_left_samples, n=20)[-1])
                              if len(bayonly_q_left_samples) > 3 else float("nan")),
        q95_bayonly_queue_m=(float(__import__("statistics").quantiles(bayonly_q_m_samples, n=20)[-1])
                             if len(bayonly_q_m_samples) > 3 else float("nan")),
        mean_bayonly_queue_m=(sum(bayonly_q_m_samples) / len(bayonly_q_m_samples)
                              if bayonly_q_m_samples else float("nan")),
        left_q_n_samples=left_q_n_samples,
        q95_left_queue_m=(float(__import__("statistics").quantiles(left_q_m_samples, n=20)[-1])
                          if len(left_q_m_samples) > 3 else float("nan")),
        q95_left_queue_veh=(float(__import__("statistics").quantiles(left_q_n_samples, n=20)[-1])
                            if len(left_q_n_samples) > 3 else float("nan")),
        mean_left_queue_m=(sum(left_q_m_samples) / len(left_q_m_samples)
                           if left_q_m_samples else float("nan")),
        n_left_traced=n_left_seen, n_other_traced=n_other_seen,
        left_used_bay=left_used_bay,
        viol_left_in_thru_lane=len(viol_left_in_thru),
        viol_thru_in_bay_lane=len(viol_thru_in_bay),
        viol_examples=(viol_left_in_thru[:5] + viol_thru_in_bay[:5]),
        **ev)
    res.update(parse_tripinfo(trip, rou))
    with open(os.path.join(outdir, "events.json"), "w") as f:
        json.dump(res, f, indent=1)
    with open(os.path.join(outdir, "lane_usage_trace.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["vehicle", "intended_movement", "in_N_bay_lanes_occupied"])
        for v in sorted(lane_use):
            w.writerow([v, v.split("_")[1].split(".")[0], "|".join(sorted(lane_use[v]))])
    if not keep_raw:
        # bulk raw XML is only retained for the designated raw-output cells;
        # everything needed downstream is already in events.json
        for f_ in (trip, summ):
            try:
                os.remove(f_)
            except OSError:
                pass
    return res


def parse_tripinfo(trip, rou):
    """Per-movement delay for NORTH-approach vehicles.

    Vehicles are selected by their INTENDED departure time
    (depart - departDelay), not their realised insertion time: when the
    approach is oversaturated the insertion buffer backs up by many minutes,
    and windowing on realised departure would silently drop exactly the
    vehicles that suffered most (a survivorship artifact).

    Vehicles that never got inserted at all do NOT appear in tripinfo even with
    --tripinfo-output.write-unfinished, so `never_inserted_*` is computed as
    (analytic demand in window) - (tripinfo records intended in window) and
    reported explicitly rather than being silently ignored.
    """
    import xml.etree.ElementTree as ET
    root = ET.parse(trip).getroot()
    acc = {}
    for t in root.findall("tripinfo"):
        vid = t.get("id")
        if not vid.startswith("N_"):
            continue
        dep = float(t.get("depart"))
        dd = float(t.get("departDelay"))
        intended = dep - dd
        if not (WARMUP <= intended < DEMAND_END):
            continue
        m = vid.split("_")[1].split(".")[0]
        a = acc.setdefault(m, dict(tl=[], wt=[], dur=[], dd=[], unf=0, n=0))
        a["n"] += 1
        a["tl"].append(float(t.get("timeLoss")))
        a["wt"].append(float(t.get("waitingTime")))
        a["dur"].append(float(t.get("duration")))
        a["dd"].append(dd)
        if float(t.get("arrival")) < 0:
            a["unf"] += 1

    # analytic demand in the window, straight from the flow definitions
    rroot = ET.parse(rou).getroot()
    want = {}
    for fl in rroot.findall("flow"):
        fid = fl.get("id")
        if not fid.startswith("N_"):
            continue
        want[fid.split("_")[1]] = float(fl.get("vehsPerHour")) * (DEMAND_END - WARMUP) / 3600.0

    out = {}
    for m in ("L", "T", "R"):
        a = acc.get(m, dict(tl=[], wt=[], dur=[], dd=[], unf=0, n=0))
        n = max(a["n"], 1)
        out[f"n_{m}"] = a["n"]
        out[f"unfinished_{m}"] = a["unf"]
        out[f"timeloss_{m}"] = sum(a["tl"]) / n if a["n"] else float("nan")
        out[f"waiting_{m}"] = sum(a["wt"]) / n if a["n"] else float("nan")
        out[f"duration_{m}"] = sum(a["dur"]) / n if a["n"] else float("nan")
        out[f"departdelay_{m}"] = sum(a["dd"]) / n if a["n"] else float("nan")
        out[f"demand_{m}"] = want.get(m, 0.0)
        out[f"never_inserted_{m}"] = max(0.0, want.get(m, 0.0) - a["n"])
    # combined THROUGH MOVEMENT = through + right (they share bay-lane 0)
    tl = acc.get("T", {}).get("tl", []) + acc.get("R", {}).get("tl", [])
    dd = acc.get("T", {}).get("dd", []) + acc.get("R", {}).get("dd", [])
    out["timeloss_TR"] = sum(tl) / len(tl) if tl else float("nan")
    out["departdelay_TR"] = sum(dd) / len(dd) if dd else float("nan")
    out["n_TR"] = len(tl)
    return out


def _lane_len(net, lane):
    import xml.etree.ElementTree as ET
    r = ET.parse(net).getroot()
    for ed in r.findall("edge"):
        for ln in ed.findall("lane"):
            if ln.get("id") == lane:
                return float(ln.get("length"))
    raise KeyError(lane)


def _is_full(net):
    import xml.etree.ElementTree as ET
    r = ET.parse(net).getroot()
    return not any(ed.get("id") == "in_N_up" for ed in r.findall("edge"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    for k in ("net", "rou", "tls", "program", "outdir"):
        ap.add_argument("--" + k, required=True)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--ttt", type=int, default=300)
    ap.add_argument("--fcd", action="store_true")
    ap.add_argument("--label", default="cell")
    ap.add_argument("--no-keep-raw", action="store_true")
    a = ap.parse_args()
    r = run(a.net, a.rou, a.tls, a.program, a.seed, a.outdir,
            ttt=a.ttt, fcd=a.fcd, label=a.label, keep_raw=not a.no_keep_raw)
    print(json.dumps({k: v for k, v in r.items() if k != "bay_q_samples"}, indent=1))
