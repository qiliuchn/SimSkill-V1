"""TraCI runner for the cruising-for-parking study.

Per simulation it produces, in one pass:
  1. PHASE DECOMPOSITION per parker -- APPROACH (depart -> first entry into the
     search zone), SEARCH (search-zone entry -> parking manoeuvre begins),
     PARKED, WALK (parkingArea -> final destination) -- with VMT and VHT
     attributed to each phase.
  2. Per-lot occupancy time series (TraCI: there is no CLI output for
     parkingArea occupancy -- see `model-parking-with-rerouting`).
  3. Separate delay/travel-time/throughput statistics for parkers vs. through
     traffic (plus SUMO's own tripinfo/stop-output/summary files).
  4. Door-to-door generalized cost per parker.
  5. Optional controllers:
       * INFORMATION (H3): a fraction of parkers are "informed" and get
         guidance from true global occupancy via traci.vehicle.rerouteParkingArea;
         the rest rely on native parkingAreaReroute with visible="false"
         (discover-on-arrival = genuine cruising).
       * PRICE / SELF-SELECTION (H4): a performance-pricing feedback loop on
         curb price plus per-driver curb/garage/balk choice on
         fee + E[search]*VOT + walk*VOT.
  6. Validity instrumentation: teleports (IDs via TraCI + reasons via the SUMO
     log), completion accounting extended to still-SEARCHING / still-PARKED /
     still-WALKING / never-parked, and an instantaneous consistency check
     between summed parkingArea occupancy and the phase decomposition's parked
     count.
"""
import csv
import json
import math
import os
import re
import sys
import tempfile

from common import NET_DIR, SUMO, SUMO_HOME
import build_parking as bp
import gen_demand as gd

sys.path.insert(0, os.path.join(SUMO_HOME, "tools"))
import traci                      # noqa: E402
import traci.constants as tc      # noqa: E402
import sumolib                    # noqa: E402

NET = os.path.join(NET_DIR, "downtown.net.xml")
SAMPLE_EVERY = 10
GUIDANCE_EVERY = 20
PRICE_EVERY = 120
STOP_PARKING_BIT = 2

DEFAULTS = dict(
    seed=1, occ=0.85, supply="baseline", visible=False, informed_share=0.0,
    policy="none",              # none | selfselect
    fee_curb=0.5, fee_garage=2.0, price_target=None, price_gain=6.0,
    price_cap=20.0,
    maneuver=False, balk_cost=6.0, horizon=gd.HORIZON, ttt=300,
    informed_mode="naive",      # naive | reserve | reserve_walk (H3 guidance variant)
    nosearch_cohort=0.0,        # H2: fraction of parkers replaced by
                                #     identical-OD trips that vanish at the lot
    ref_mode="curb",       # curb | total (total reproduces the discarded normalisation)
    label="run",
)


def _walk_dist(conn, net, from_edge, to_edge, cache):
    """Walk distance (m) via SUMO's own pedestrian router.

    NOTE (verified): sumolib's net.getShortestPath(..., vClass='pedestrian')
    returns inf between sidewalks on this net, because the pedestrian graph runs
    through walkingarea/crossing INTERNAL edges that the sumolib edge graph does
    not traverse.  traci.simulation.findIntermodalRoute is the working
    mechanism; results are cached, and an L1 (Manhattan) fallback -- exact for a
    rectangular grid -- is used if the router fails."""
    key = (from_edge, to_edge)
    if key not in cache:
        d = None
        try:
            stages = conn.simulation.findIntermodalRoute(from_edge, to_edge, modes="", pType="ped")
            d = sum(s.length for s in stages)
            if d <= 0:
                d = None
        except Exception:
            d = None
        if d is None:
            a = gd.edge_centroid(net, from_edge)
            b = gd.edge_centroid(net, to_edge)
            d = abs(a[0] - b[0]) + abs(a[1] - b[1])
        cache[key] = d
    return cache[key]


def _retarget(conn, vid, lot, dwell, stats):
    """Send a searching vehicle to `lot`, repairing SUMO's silent stop-loss.

    VERIFIED SUMO 1.27.1 behaviour: traci.vehicle.rerouteParkingArea can log
    "could not assign stop '<PA>' after rerouting" and leave the vehicle with NO
    parking stop at all -- it then keeps driving and every later reroute attempt
    fails with "is not driving to a parking area".  The call does not raise on
    the step it happens, so it must be detected by re-reading getStops()."""
    ok = False
    try:
        conn.vehicle.rerouteParkingArea(vid, lot)
        ok = True
    except Exception:
        stats["reroute_exceptions"] += 1
    try:
        stops = conn.vehicle.getStops(vid, 1)
        has = any(getattr(s, "stoppingPlaceID", "") for s in stops)
    except Exception:
        has = True
    if not has:
        stats["stop_lost"] += 1
        stats["lost_vehicles"].add(vid)
        for repair_lot in (lot, stats.get("fallback", {}).get(vid)):
            if not repair_lot:
                continue
            try:
                # re-route the vehicle onto the lot's edge first: setParkingAreaStop
                # only succeeds if the parkingArea lies ahead on the current route
                conn.vehicle.changeTarget(vid, stats["lot_edge"][repair_lot])
                conn.vehicle.setParkingAreaStop(vid, repair_lot, duration=dwell)
                stats["stop_repaired"] += 1
                ok = True
                break
            except Exception:
                continue
    return ok


def run(cfg, out_dir):
    c = dict(DEFAULTS)
    c.update(cfg)
    os.makedirs(out_dir, exist_ok=True)
    net = bp.load_net()
    lots = bp.build_supply(net, c["supply"])
    lot_kind = {l["id"]: l["kind"] for l in lots}
    lot_cap = {l["id"]: l["cap"] for l in lots}
    lot_edge = {l["id"]: l["edge"] for l in lots}
    curb_ids = [l["id"] for l in lots if l["kind"] == "curb"]
    gar_ids = [l["id"] for l in lots if l["kind"] == "garage"]
    capacity = sum(lot_cap.values())
    curb_capacity = sum(lot_cap[i] for i in curb_ids)
    core_zone = set(bp.core_edge_ids(net))
    _, snk = bp.fringe_edge_ids(net)

    # ---- demand (Common Random Numbers: identical for every arm at a seed) ---
    rou, meta_csv, dinfo = gd.generate(c["seed"], c["occ"], c["supply"],
                                       out_dir=out_dir, tag="demand", ref_mode=c["ref_mode"])
    meta = {}
    with open(meta_csv) as f:
        for r in csv.DictReader(f):
            meta[r["vid"]] = r

    padd = os.path.join(NET_DIR, "parking_%s.add.xml" % c["supply"])
    radd = os.path.join(NET_DIR, "rerouter_%s_vis%d.add.xml" % (c["supply"], int(c["visible"])))

    logf = os.path.join(out_dir, "sumo.log")
    tripinfo = os.path.join(out_dir, "tripinfo.xml")
    stopout = os.path.join(out_dir, "stopinfo.xml")
    summ = os.path.join(out_dir, "summary.xml")

    cmd = [SUMO, "-n", NET, "-r", rou, "-a", "%s,%s" % (padd, radd),
           "--begin", "0", "--end", str(c["horizon"]),
           "--step-length", "1",
           "--device.rerouting.probability", "1",
           "--device.rerouting.period", "60",
           "--time-to-teleport", str(c["ttt"]),
           "--pedestrian.model", "striping",
           "--tripinfo-output", tripinfo,
           "--stop-output", stopout,
           "--summary-output", summ,
           "--log", logf,
           "--no-step-log", "true", "--duration-log.disable", "true",
           "--seed", str(c["seed"]),
           "--xml-validation", "never"]
    if c["maneuver"]:
        cmd += ["--parking.maneuver"]

    rng = __import__("random").Random(c["seed"] * 104729 + 7)
    informed = set()
    nosearch = set()
    parkers = [v for v, m in meta.items() if m["cls"] == "parker"]
    parkers.sort()
    for v in parkers:
        if rng.random() < c["informed_share"]:
            informed.add(v)
    if c["nosearch_cohort"] > 0:
        rng2 = __import__("random").Random(c["seed"] * 15485863 + 3)
        for v in parkers:
            if rng2.random() < c["nosearch_cohort"]:
                nosearch.add(v)

    wcache = {}
    # pre-compute walk times from every lot to every parker's destination lazily
    st = {}
    for v in parkers:
        m = meta[v]
        st[v] = dict(phase="pre", t_depart=float(m["depart"]), t_zone=None, t_park=None,
                     t_walk_end=None, lot=None, kind=None,
                     vmt_app=0.0, vmt_srch=0.0, vmt_egr=0.0,
                     vht_app=0.0, vht_srch=0.0, vht_egr=0.0,
                     walk_time=None, fee=0.0, balked=False,
                     informed=v in informed, decided=False,
                     vot=float(m["vot"]), vot_walk=float(m["vot_walk"]),
                     walk_speed=float(m["walk_speed"]), dwell=float(m["dwell"]),
                     dest=m["dest_edge"], assigned=m["assigned_lot"],
                     nosearch=v in nosearch, reroutes=0)
    thru = {}
    for v, m in meta.items():
        if m["cls"] == "through":
            thru[v] = dict(vmt=0.0, vht=0.0, t_depart=float(m["depart"]), t_arr=None,
                           vmt_core=0.0, vht_core=0.0)
    initveh = {}          # warm-start (turnover) vehicles: id -> [vmt, vht]

    curb_edges = set(lot_edge[l] for l in curb_ids)
    standing = dict(curb_edge_veh_s=0.0, core_veh_s=0.0, all_veh_s=0.0,
                    invalid_speed_samples=0)
    occ_series = []          # (t, {lot: count})
    consistency = []         # (t, sum_lot_occ, phase_parked_count, delta)
    price_series = []
    teleports = set()
    person_of = {}
    walk_start = {}
    fee_curb = c["fee_curb"]
    Es = {"curb": 60.0, "garage": 20.0}   # rolling expected search time by kind
    rstats = dict(reroute_exceptions=0, stop_lost=0, stop_repaired=0, dispatched=0,
                  lost_vehicles=set(), lot_edge=lot_edge,
                  fallback=dict((v, st[v]['assigned']) for v in st))
    dispatch = {}            # lot -> count of informed vehicles currently sent there
    ES_ALPHA = 0.15

    traci.start(cmd, label=c["label"] + str(os.getpid()))
    conn = traci
    conn.simulation.subscribe([tc.VAR_DEPARTED_VEHICLES_IDS, tc.VAR_ARRIVED_VEHICLES_IDS,
                               tc.VAR_TELEPORT_STARTING_VEHICLES_IDS,
                               tc.VAR_ARRIVED_PERSONS_IDS])
    for lid in lot_cap:
        conn.parkingarea.subscribe(lid, [tc.VAR_STOP_STARTING_VEHICLES_NUMBER])
    # audit: walking distance from every lot to the CBD-centre block face
    walk_ref = {lid: round(_walk_dist(conn, net, lot_edge[lid], "C2C3", wcache), 1)
                for lid in lot_cap}
    # audit: parkingArea geometry as SUMO itself compiled it
    pa_geom = {lid: dict(lane=conn.parkingarea.getLaneID(lid),
                         start=round(conn.parkingarea.getStartPos(lid), 2),
                         end=round(conn.parkingarea.getEndPos(lid), 2)) for lid in lot_cap}

    step = 0
    try:
        while step < c["horizon"]:
            conn.simulationStep()
            step += 1
            sres = conn.simulation.getSubscriptionResults()
            for vid in sres.get(tc.VAR_DEPARTED_VEHICLES_IDS, ()):
                conn.vehicle.subscribe(vid, [tc.VAR_ROAD_ID, tc.VAR_SPEED, tc.VAR_STOPSTATE])
            for vid in sres.get(tc.VAR_TELEPORT_STARTING_VEHICLES_IDS, ()):
                teleports.add(vid)
            for pid in sres.get(tc.VAR_ARRIVED_PERSONS_IDS, ()):
                v = person_of.get(pid)
                if v is not None and st[v]["walk_time"] is None:
                    st[v]["walk_time"] = step - walk_start[pid]
                    st[v]["t_walk_end"] = step

            vres = conn.vehicle.getAllSubscriptionResults()
            newly_parked = []
            n_parked_stopstate = 0
            n_invalid_speed = 0
            n_parked_init = 0
            for vid, d in vres.items():
                spd = d.get(tc.VAR_SPEED, 0.0)
                # VERIFIED GOTCHA: while a vehicle is being teleported, the
                # subscribed VAR_SPEED comes back as SUMO's INVALID_DOUBLE_VALUE
                # (-2**30). Accumulating it silently poisons per-step VMT by ~1e9
                # per step. Clamp to the physically possible range.
                if not (0.0 <= spd <= 60.0):
                    spd = 0.0
                    n_invalid_speed += 1
                road = d.get(tc.VAR_ROAD_ID, "")
                stpe = d.get(tc.VAR_STOPSTATE, 0)
                parked = bool(int(stpe) & STOP_PARKING_BIT)
                if parked:
                    n_parked_stopstate += 1
                elif spd < 0.1:
                    # standing (not parked) vehicle-seconds: the direct signal for
                    # a blocked single-lane street
                    standing["all_veh_s"] += 1.0
                    if road in curb_edges:
                        standing["curb_edge_veh_s"] += 1.0
                    if road in core_zone:
                        standing["core_veh_s"] += 1.0
                if vid.startswith("init_"):
                    e = initveh.setdefault(vid, [0.0, 0.0])
                    if parked:
                        n_parked_init += 1
                    else:
                        e[0] += spd
                        e[1] += 1.0
                    continue
                if vid in thru:
                    if not parked:
                        thru[vid]["vmt"] += spd
                        thru[vid]["vht"] += 1.0
                        if road in core_zone:
                            thru[vid]["vmt_core"] += spd
                            thru[vid]["vht_core"] += 1.0
                    continue
                s = st.get(vid)
                if s is None:
                    continue          # init_* warm-start vehicle
                if parked:
                    if s["phase"] not in ("parked", "egress"):
                        s["phase"] = "parked"
                        s["t_park"] = step
                        newly_parked.append(vid)
                    continue
                if s["phase"] == "parked":
                    s["phase"] = "egress"
                if s["phase"] == "pre":
                    s["phase"] = "approach"
                if s["phase"] == "approach":
                    if road in core_zone:
                        s["phase"] = "search"
                        s["t_zone"] = step
                    else:
                        s["vmt_app"] += spd
                        s["vht_app"] += 1.0
                        continue
                if s["phase"] == "search":
                    s["vmt_srch"] += spd
                    s["vht_srch"] += 1.0
                elif s["phase"] == "egress":
                    s["vmt_egr"] += spd
                    s["vht_egr"] += 1.0

            # ---- newly parked: record lot, fee, spawn the walking driver -----
            for vid in newly_parked:
                s = st[vid]
                lid = None
                try:
                    lid = conn.vehicle.getStops(vid, -1)[0].stoppingPlaceID
                except Exception:
                    pass
                if not lid or lid not in lot_kind:
                    for cand in lot_kind:
                        if vid in conn.parkingarea.getVehicleIDs(cand):
                            lid = cand
                            break
                s["lot"] = lid
                s["kind"] = lot_kind.get(lid)
                hours = s["dwell"] / 3600.0
                s["fee"] = (fee_curb if s["kind"] == "curb" else c["fee_garage"]) * hours
                if s["t_zone"] is not None and s["kind"]:
                    obs = s["t_park"] - s["t_zone"]
                    Es[s["kind"]] = (1 - ES_ALPHA) * Es[s["kind"]] + ES_ALPHA * obs
                # walking driver
                if lid:
                    pid = "p_" + vid
                    try:
                        conn.person.add(pid, lot_edge[lid], 5.0, step, "ped")
                        stages = conn.simulation.findIntermodalRoute(
                            lot_edge[lid], s["dest"], modes="", pType="ped")
                        for sg in stages:
                            conn.person.appendStage(pid, sg)
                        conn.person.setSpeed(pid, s["walk_speed"])
                        person_of[pid] = vid
                        walk_start[pid] = step
                    except Exception:
                        pass

            # ---- H2 no-search cohort: vanish on first search-zone entry ------
            if nosearch:
                for vid in list(nosearch):
                    s = st.get(vid)
                    if s and s["phase"] == "search" and s["t_zone"] == step:
                        try:
                            conn.vehicle.remove(vid, reason=tc.REMOVE_ARRIVED)
                        except Exception:
                            pass
                        s["phase"] = "removed_nosearch"
                        nosearch.discard(vid)

            # ---- H4 self-selection at search-zone entry ---------------------
            if c["policy"] == "selfselect":
                for vid, d in vres.items():
                    s = st.get(vid)
                    if s is None or s["decided"] or s["phase"] != "search":
                        continue
                    s["decided"] = True
                    hours = s["dwell"] / 3600.0
                    wt_curb = _walk_dist(conn, net, lot_edge[s["assigned"]], s["dest"],
                                         wcache) / s["walk_speed"]
                    best_g = min(gar_ids, key=lambda g: _walk_dist(
                        conn, net, lot_edge[g], s["dest"], wcache)) if gar_ids else None
                    cost_curb = fee_curb * hours + (Es["curb"] * s["vot"] +
                                                    wt_curb * s["vot_walk"]) / 3600.0
                    if best_g:
                        wt_g = _walk_dist(conn, net, lot_edge[best_g], s["dest"],
                                          wcache) / s["walk_speed"]
                        cost_gar = c["fee_garage"] * hours + (Es["garage"] * s["vot"] +
                                                              wt_g * s["vot_walk"]) / 3600.0
                    else:
                        cost_gar = 1e9
                    choice = "curb" if cost_curb <= cost_gar else "garage"
                    best_cost = min(cost_curb, cost_gar)
                    if best_cost > c["balk_cost"]:
                        choice = "balk"
                    s["choice"] = choice
                    s["cost_curb_exp"] = cost_curb
                    s["cost_gar_exp"] = cost_gar
                    if choice == "garage":
                        if _retarget(conn, vid, best_g, s["dwell"], rstats):
                            s["reroutes"] += 1
                    elif choice == "balk":
                        try:
                            conn.vehicle.replaceStop(vid, 0, "")
                            conn.vehicle.changeTarget(vid, meta[vid]["exit_edge"])
                            s["balked"] = True
                            s["phase"] = "egress"
                        except Exception:
                            s["balked"] = False

            # ---- H3 information: guidance from true occupancy ---------------
            if informed and step % GUIDANCE_EVERY == 0:
                occ_now = {lid: conn.parkingarea.getSubscriptionResults(lid).get(
                    tc.VAR_STOP_STARTING_VEHICLES_NUMBER, 0) for lid in lot_cap}
                # drop stale dispatch reservations (vehicle parked / left search)
                if c["informed_mode"].startswith("reserve"):
                    for vv, ll in list(dispatch.items()):
                        if st.get(vv, {}).get("phase") != "search":
                            del dispatch[vv]
                    booked = {}
                    for ll in dispatch.values():
                        booked[ll] = booked.get(ll, 0) + 1
                else:
                    booked = {}
                for vid, d in vres.items():
                    if vid not in informed:
                        continue
                    s = st.get(vid)
                    if s is None or s["phase"] != "search":
                        continue
                    road = d.get(tc.VAR_ROAD_ID, "")
                    if not road or road.startswith(":"):
                        continue
                    eff = {l: occ_now[l] + booked.get(l, 0) for l in lot_cap}
                    if c["informed_mode"].startswith("reserve") and dispatch.get(vid):
                        eff[dispatch[vid]] -= 1
                    free = [l for l in lot_cap if eff[l] < lot_cap[l]]
                    cand = [l for l in free if lot_kind[l] == "curb"] or free
                    if not cand:
                        continue
                    if c["informed_mode"] == "reserve_walk":
                        # WALK-AWARE objective: minimise the traveller's own
                        # door-to-door time cost, not "nearest free space to me".
                        here = gd.edge_centroid(net, road)
                        def _cost(l):
                            drive = math.dist(here, gd.edge_centroid(net, lot_edge[l])) / 11.11
                            walk = _walk_dist(conn, net, lot_edge[l], s["dest"], wcache) / s["walk_speed"]
                            return drive * s["vot"] + walk * s["vot_walk"]
                        tgt = min(cand, key=_cost)
                    else:
                        here = gd.edge_centroid(net, road)
                        tgt = min(cand, key=lambda l: math.dist(here, gd.edge_centroid(net, lot_edge[l])))
                    if tgt != s.get("lot_target"):
                        if _retarget(conn, vid, tgt, s["dwell"], rstats):
                            s["lot_target"] = tgt
                            s["reroutes"] += 1
                            rstats["dispatched"] += 1
                            if c["informed_mode"].startswith("reserve"):
                                dispatch[vid] = tgt
                                booked[tgt] = booked.get(tgt, 0) + 1

            # ---- occupancy sampling + consistency check ----------------------
            standing["invalid_speed_samples"] += n_invalid_speed

            if step % SAMPLE_EVERY == 0:
                snap = {lid: int(conn.parkingarea.getSubscriptionResults(lid).get(tc.VAR_STOP_STARTING_VEHICLES_NUMBER, 0))
                        for lid in lot_cap}
                occ_series.append([step, snap])
                tot = sum(snap.values())
                phase_parked = sum(1 for s in st.values() if s["phase"] == "parked")
                # [t, summed parkingArea occupancy, vehicles whose STOPSTATE says
                #  "parking", parkers the phase decomposition calls parked,
                #  warm-start vehicles currently parked]
                consistency.append([step, tot, n_parked_stopstate, phase_parked, n_parked_init])

            # ---- H4 performance pricing feedback -----------------------------
            if c["price_target"] is not None and step % PRICE_EVERY == 0:
                cur = sum(int(conn.parkingarea.getSubscriptionResults(l).get(tc.VAR_STOP_STARTING_VEHICLES_NUMBER, 0))
                          for l in curb_ids)
                rho = cur / float(curb_capacity)
                fee_curb = min(c["price_cap"], max(0.0, fee_curb + c["price_gain"] * (rho - c["price_target"])))
                price_series.append([step, round(rho, 4), round(fee_curb, 3)])

            if step > 600 and conn.simulation.getMinExpectedNumber() <= 0:
                break
    finally:
        try:
            conn.close()
        except Exception:
            pass

    # -------------------- teleport reasons from the SUMO log ------------------
    tel_reasons = {}
    ped_jams = 0
    try:
        with open(logf) as f:
            for line in f:
                low = line.lower()
                if "teleporting" in low:
                    m = re.search(r"[Vv]ehicle '([^']+)'", line)
                    reason = "other"
                    for key in ("wrong lane", "yield", "jam", "collision"):
                        if key in low:
                            reason = key
                            break
                    tel_reasons[reason] = tel_reasons.get(reason, 0) + 1
                    if m:
                        teleports.add(m.group(1))
                elif "is jammed on edge" in low and "person" in low:
                    ped_jams += 1
    except IOError:
        pass

    # -------------------- assemble per-parker records ------------------------
    recs = []
    for vid, s in st.items():
        approach = (s["t_zone"] - s["t_depart"]) if s["t_zone"] is not None else None
        if s["t_park"] is not None and s["t_zone"] is not None:
            search = s["t_park"] - s["t_zone"]
        else:
            search = None
        gc = None
        if s["t_park"] is not None and s["walk_time"] is not None:
            in_veh = (s["t_park"] - s["t_depart"])
            gc = in_veh * s["vot"] / 3600.0 + s["walk_time"] * s["vot_walk"] / 3600.0 + s["fee"]
        recs.append(dict(
            vid=vid, phase_end=s["phase"], approach_t=approach, search_t=search,
            walk_t=s["walk_time"], t_depart=s["t_depart"], t_park=s["t_park"],
            lot=s["lot"], kind=s["kind"], fee=round(s["fee"], 4),
            vot=s["vot"], vot_walk=s["vot_walk"], dwell=s["dwell"],
            balked=s["balked"], informed=s["informed"], nosearch=s["nosearch"],
            reroutes=s["reroutes"], choice=s.get("choice"),
            vmt_app=round(s["vmt_app"], 1), vmt_srch=round(s["vmt_srch"], 1),
            vmt_egr=round(s["vmt_egr"], 1), vht_app=round(s["vht_app"], 1),
            vht_srch=round(s["vht_srch"], 1), vht_egr=round(s["vht_egr"], 1),
            gencost=gc, teleported=vid in teleports))

    thru_recs = [dict(vid=v, vmt=round(d["vmt"], 1), vht=round(d["vht"], 1),
                      vmt_core=round(d["vmt_core"], 1), vht_core=round(d["vht_core"], 1),
                      teleported=v in teleports) for v, d in thru.items()]

    # tripinfo (SUMO's own) for cross-checking travel time / time loss
    ti = {}
    try:
        for t in sumolib.xml.parse(tripinfo, "tripinfo"):
            ti[t.id] = dict(duration=float(t.duration), timeLoss=float(t.timeLoss),
                            routeLength=float(t.routeLength),
                            waitingTime=float(t.waitingTime))
    except Exception:
        pass

    result = dict(
        config=c, demand=dict((k, v) for k, v in dinfo.items() if k != "core_zone"),
        capacity=capacity, curb_capacity=curb_capacity,
        lot_kind=lot_kind, lot_cap=lot_cap,
        parkers=recs, through=thru_recs, tripinfo=ti,
        initveh=dict((k, [round(v[0], 1), round(v[1], 1)]) for k, v in initveh.items()),
        pedestrian_jams=ped_jams, standing=standing,
        occupancy=occ_series, consistency=consistency, price=price_series,
        teleports=sorted(teleports), teleport_reasons=tel_reasons,
        final_fee_curb=fee_curb, Es=Es, walk_ref=walk_ref, pa_geom=pa_geom,
        reroute_stats=dict(reroute_exceptions=rstats['reroute_exceptions'],
                           stop_lost=rstats['stop_lost'],
                           stop_repaired=rstats['stop_repaired'],
                           dispatched=rstats['dispatched'],
                           n_lost_vehicles=len(rstats['lost_vehicles']),
                           lost_vehicles=sorted(rstats['lost_vehicles'])))
    with open(os.path.join(out_dir, "result.json"), "w") as f:
        json.dump(result, f)
    return result


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--cfg", required=True, help="JSON config")
    a = ap.parse_args()
    r = run(json.loads(a.cfg), a.out)
    print(json.dumps({k: r[k] for k in ("capacity", "final_fee_curb", "teleport_reasons")}))
