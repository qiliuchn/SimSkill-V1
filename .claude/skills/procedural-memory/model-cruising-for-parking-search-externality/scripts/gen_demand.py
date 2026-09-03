"""Generate the three demand classes for the cruising-for-parking scenario.

  (a) PARKERS  : fringe origin -> drive to the CBD -> park at a parkingArea ->
                 the driver (a TraCI-spawned <person>) walks to a final
                 destination and dwells there -> the car later leaves to a
                 fringe sink.  Each parker carries an explicit value of time
                 (lognormal) and walking speed, persisted to a side-channel CSV
                 (SUMO has no native per-vehicle VOT attribute) -- the pattern
                 from `model-managed-lanes-with-dynamic-tolling-and-self-selection`.
  (b) THROUGH  : fringe -> fringe, never parks.
  (c) TURNOVER : vehicles already parked at t=0 (warm start of the occupancy
                 stock) that depart after a residual dwell.

Routes are built directly from the compiled net with sumolib shortest paths
(vClass=passenger), so every emitted route is guaranteed connection-valid; this
replaces a duarouter round-trip and keeps origin/destination/departure-time
*identical* across policy arms, which is what makes the arm comparison clean.
"""
import csv
import math
import re
import os
import random
import sys

from common import NET_DIR, SUMO_HOME
import build_parking as bp

sys.path.insert(0, os.path.join(SUMO_HOME, "tools"))
import sumolib  # noqa: E402

MEAN_DWELL = 920.0          # s, realised mean of the lognormal below
DWELL_MEDIAN = 720.0
DWELL_SIGMA = 0.70
VOT_MEDIAN = 18.0           # $/h in-vehicle
VOT_SIGMA = 0.60
VOT_WALK_FACTOR = 1.6       # walking time valued higher than in-vehicle time
WALK_SPEED_MEAN = 1.35
WALK_SPEED_SD = 0.15

HORIZON = 4200
DEPART_END = 3600
THROUGH_VEH_PER_HOUR = 700
REF_CURB_CAPACITY = 144      # baseline curb supply; the demand-index denominator


def _sp_cache(net):
    return {}


def shortest(net, cache, a, b):
    key = (a, b)
    if key in cache:
        return cache[key]
    try:
        path, _ = net.getShortestPath(net.getEdge(a), net.getEdge(b), vClass="passenger")
    except Exception:
        path = None
    r = [e.getID() for e in path] if path else None
    cache[key] = r
    return r


def edge_centroid(net, eid):
    shp = net.getEdge(eid).getShape()
    return (sum(p[0] for p in shp) / len(shp), sum(p[1] for p in shp) / len(shp))


def generate(seed, occupancy_target, supply_preset="baseline", out_dir=None,
             through_vph=THROUGH_VEH_PER_HOUR, tag="demand", ref_mode="curb"):
    """Return (route_file, meta_csv, meta_dict). Deterministic in `seed`.

    Common Random Numbers: the same seed yields the same parker cohort
    (origins, destinations, departure times, dwell, VOT, walk speed) for every
    policy arm; only the arm's own configuration differs.
    """
    rng = random.Random(seed * 7919 + 13)
    net = bp.load_net()
    cache = _sp_cache(net)
    lots = bp.build_supply(net, supply_preset)
    capacity = sum(l["cap"] for l in lots)
    curb_lots = [l for l in lots if l["kind"] == "curb"]

    src, snk = bp.fringe_edge_ids(net)
    core_area = bp.core_area_edge_ids(net)
    core_zone = set(bp.core_edge_ids(net))

    # walk destinations concentrated on the CBD centre
    cx, cy = edge_centroid(net, "C2C3")
    dest_pool, dest_w = [], []
    for eid in core_area:
        x, y = edge_centroid(net, eid)
        d = math.hypot(x - cx, y - cy)
        dest_pool.append(eid)
        dest_w.append(math.exp(-d / 180.0))

    # Demand index is normalised against the BASELINE CURB capacity, not total
    # supply: under no information and no price signal essentially every parker
    # targets the curb, so curb capacity -- not total capacity -- is the binding
    # constraint.  Using a FIXED reference capacity also keeps absolute demand
    # identical across supply presets, so a supply-increment arm differs from the
    # baseline only in supply (a clean policy contrast, not a demand confound).
    # ref_mode='total' reproduces the DISCARDED normalisation (against total supply)
    # that produced the degenerate sweep documented in FINDINGS.md section 1.3.
    ref_cap = capacity if ref_mode == "total" else REF_CURB_CAPACITY
    lam = occupancy_target * ref_cap / MEAN_DWELL           # parkers per second
    n_parkers = int(round(lam * DEPART_END))
    curb_capacity = sum(l["cap"] for l in curb_lots)
    n_init = min(int(round(occupancy_target * ref_cap)), curb_capacity - 1)
    n_through = int(round(through_vph * DEPART_END / 3600.0))

    rows = []
    _veh = []   # (depart, xml) -- SUMO requires the route file sorted by departure

    class _L(list):
        def append(self, x):
            m = re.search(r'depart="([0-9.]+)"', x)
            _veh.append((float(m.group(1)), x))

    veh_xml = _L()

    def draw_vot():
        return VOT_MEDIAN * math.exp(rng.gauss(0, VOT_SIGMA))

    def draw_dwell():
        return max(120.0, DWELL_MEDIAN * math.exp(rng.gauss(0, DWELL_SIGMA)))

    # ---------------- (c) TURNOVER: pre-parked stock at t=0 ------------------
    lot_slots = []
    for l in curb_lots:
        lot_slots += [l["id"]] * l["cap"]
    rng.shuffle(lot_slots)
    by_id = {l["id"]: l for l in lots}
    init_placed = 0
    for i in range(n_init):
        lot = by_id[lot_slots[i]]
        exit_edge = rng.choice(snk)
        r = shortest(net, cache, lot["edge"], exit_edge)
        if not r:
            continue
        residual = rng.uniform(30.0, draw_dwell())
        veh_xml.append(
            '    <vehicle id="init_%d" type="car" depart="0.00" departPos="0" departSpeed="0">\n'
            '        <route edges="%s"/>\n'
            '        <stop parkingArea="%s" duration="%.1f" parking="true"/>\n'
            '    </vehicle>' % (i, " ".join(r), lot["id"], residual))
        init_placed += 1

    # ---------------- (a) PARKERS -------------------------------------------
    parker_ids = []
    for i in range(n_parkers):
        depart = rng.uniform(0, DEPART_END)
        origin = rng.choice(src)
        dest_edge = rng.choices(dest_pool, weights=dest_w, k=1)[0]
        dx, dy = edge_centroid(net, dest_edge)
        # assigned lot = the curb lot closest to the final destination
        best = min(curb_lots, key=lambda l: math.hypot(*(a - b for a, b in
                                                         zip(edge_centroid(net, l["edge"]), (dx, dy)))))
        exit_edge = rng.choice(snk)
        r1 = shortest(net, cache, origin, best["edge"])
        r2 = shortest(net, cache, best["edge"], exit_edge)
        if not r1 or not r2:
            continue
        route = r1 + r2[1:]
        dwell = draw_dwell()
        vot = draw_vot()
        wsp = max(0.7, rng.gauss(WALK_SPEED_MEAN, WALK_SPEED_SD))
        vid = "park_%d" % i
        parker_ids.append(vid)
        veh_xml.append(
            '    <vehicle id="%s" type="car" depart="%.2f">\n'
            '        <route edges="%s"/>\n'
            '        <stop parkingArea="%s" duration="%.1f" parking="true"/>\n'
            '    </vehicle>' % (vid, depart, " ".join(route), best["id"], dwell))
        rows.append(dict(vid=vid, cls="parker", depart="%.2f" % depart, origin=origin,
                         dest_edge=dest_edge, assigned_lot=best["id"], exit_edge=exit_edge,
                         dwell="%.1f" % dwell, vot="%.4f" % vot,
                         vot_walk="%.4f" % (vot * VOT_WALK_FACTOR), walk_speed="%.3f" % wsp))

    # ---------------- (b) THROUGH -------------------------------------------
    for i in range(n_through):
        depart = rng.uniform(0, DEPART_END)
        for _ in range(12):
            o = rng.choice(src)
            d = rng.choice(snk)
            r = shortest(net, cache, o, d)
            if r and len(r) >= 5:
                break
        else:
            continue
        vid = "thru_%d" % i
        veh_xml.append('    <vehicle id="%s" type="car" depart="%.2f">\n'
                       '        <route edges="%s"/>\n'
                       '    </vehicle>' % (vid, depart, " ".join(r)))
        rows.append(dict(vid=vid, cls="through", depart="%.2f" % depart, origin=o,
                         dest_edge=d, assigned_lot="", exit_edge=d, dwell="",
                         vot="%.4f" % draw_vot(), vot_walk="", walk_speed=""))

    out_dir = out_dir or NET_DIR
    rou = os.path.join(out_dir, "%s.rou.xml" % tag)
    with open(rou, "w") as f:
        f.write('<routes>\n')
        f.write('    <vType id="car" vClass="passenger" length="4.8" minGap="2.0" '
                'maxSpeed="13.9" accel="2.6" decel="4.5" sigma="0.5"/>\n')
        f.write('    <vType id="ped" vClass="pedestrian"/>\n')
        f.write("\n".join(x for _, x in sorted(_veh, key=lambda t: t[0])))
        f.write('\n</routes>\n')

    meta = os.path.join(out_dir, "%s.meta.csv" % tag)
    with open(meta, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["vid", "cls", "depart", "origin", "dest_edge",
                                          "assigned_lot", "exit_edge", "dwell", "vot",
                                          "vot_walk", "walk_speed"])
        w.writeheader()
        for r in rows:
            w.writerow(r)

    info = dict(seed=seed, occupancy_target=occupancy_target, supply_preset=supply_preset,
                ref_mode=ref_mode,
                capacity=capacity, curb_capacity=curb_capacity, ref_capacity=ref_cap, n_parkers=len(parker_ids), n_init=init_placed,
                n_through=n_through, lam=lam, core_zone=sorted(core_zone))
    return rou, meta, info


if __name__ == "__main__":
    rou, meta, info = generate(1, 0.85, tag="probe")
    info.pop("core_zone")
    print(rou, meta, info)
