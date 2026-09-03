"""TESTBED B rig -- 3-lane -> 1-lane freeway lane drop, queue-discharge capacity.

Discipline reused from `build-macroscopic-fundamental-diagram`:
  * a GENUINE downstream bottleneck is required; an unconstrained corridor only
    ever traces the free-flow branch.  The lane drop is verified from the
    compiled net's connections (build_networks.py).
  * the measurement station is E1 induction loops; space-mean speed uses the
    HARMONIC mean (`harmonicMeanSpeed`), never the arithmetic mean.
  * congestion must be shown PHYSICAL (0 teleports / 0 collisions), not a
    simulation artefact, before any congested-branch number is trusted.
  * measured discharge is sanity-checked against the per-vType theoretical
    single-lane bound  v/(v*tau + length + minGap)*3600.

Bottleneck-binding evidence recorded for every single run:
  - upstream station (3 lanes on `main`, 200 m before the drop): space-mean
    speed and occupancy -> must show a standing queue over the station;
  - laneAreaDetector over the last 500 m of every `main` lane -> queue presence;
  - the discharge station 600 m INSIDE the 1-lane bottleneck -> the capacity;
  - stationarity of the 60-s discharge series over the measurement window.
"""
import os
import xml.etree.ElementTree as ET

from common import (WORK, NETS, FWY_SPEED, FWY_NLANES, FWY_TEND, FWY_WARMUP,
                    FWY_DEMAND, DET_POS, STEP, vtype_xml, run_sumo, ols)
import demand

ROUTE_EDGES = "feed main bneck exit"
PERIOD = 60.0
LAD_LEN = 500.0          # queue detector over the last 500 m of `main`

# Lane lengths are read from the COMPILED net, never assumed from the source
# .edg.xml: netconvert shortens each edge by the junction's internal geometry
# (`main` is authored 2000 m but compiles to 1996 m), and an out-of-range
# laneAreaDetector endPos is a hard error.
def _compiled_lengths():
    import json
    d = json.load(open(os.path.join(WORK, "network_verification.json")))
    g0 = d["freeway"]["g0"]["edge_lane_length"]
    return {k: float(v) for k, v in g0.items()}


LANE_LEN = _compiled_lengths()
MAIN_LEN = LANE_LEN["main"]
UP_POS = MAIN_LEN - 200.0     # upstream station: 200 m before the lane drop


def net_for(grade_pct):
    return os.path.join(NETS, "fwy_g%g.net.xml" % grade_pct)


def prepare(outdir, grade_pct, p, seed, hv_attrs, car_attrs, demand_vph=None):
    os.makedirs(outdir, exist_ok=True)
    dv = FWY_DEMAND if demand_vph is None else demand_vph
    rou = os.path.join(outdir, "fwy.rou.xml")
    with open(rou, "w") as f:
        f.write('<routes>\n')
        f.write(vtype_xml("car", car_attrs, FWY_SPEED))
        f.write(vtype_xml("hv", hv_attrs, FWY_SPEED))
        f.write('  <route id="r0" edges="%s"/>\n' % ROUTE_EDGES)
    n, k = demand.write_freeway_routes(rou, dv, FWY_TEND, p, seed,
                                       "car", "hv", FWY_NLANES)
    with open(rou, "a") as f:
        f.write('</routes>\n')

    add = os.path.join(outdir, "det.add.xml")
    with open(add, "w") as f:
        f.write('<additional>\n')
        # --- capacity station: inside the 1-lane bottleneck, downstream of drop
        f.write('  <inductionLoop id="cap_0" lane="bneck_0" pos="%g" period="%g" '
                'file="e1_cap.xml"/>\n' % (DET_POS, PERIOD))
        f.write('  <instantInductionLoop id="icap" lane="bneck_0" pos="%g" '
                'file="instant_cap.xml"/>\n' % DET_POS)
        # --- upstream station: proves the queue reaches back over the mainline
        for l in range(FWY_NLANES):
            f.write('  <inductionLoop id="up_%d" lane="main_%d" pos="%g" period="%g" '
                    'file="e1_up.xml"/>\n' % (l, l, UP_POS, PERIOD))
            f.write('  <laneAreaDetector id="q_%d" lane="main_%d" pos="%g" '
                    'endPos="%g" friendlyPos="true" period="%g" file="e2_q.xml"/>\n'
                    % (l, l, MAIN_LEN - LAD_LEN, MAIN_LEN, PERIOD))
        f.write('</additional>\n')
    return rou, add, n, k


def run(outdir, grade_pct, p, seed, hv_attrs, car_attrs, demand_vph=None):
    rou, add, n, k = prepare(outdir, grade_pct, p, seed, hv_attrs, car_attrs, demand_vph)
    args = ["-n", net_for(grade_pct), "-r", "fwy.rou.xml", "-a", "det.add.xml",
            "--begin", "0", "--end", str(FWY_TEND), "--step-length", str(STEP),
            "--seed", str(seed), "--time-to-teleport", "-1",
            "--no-step-log", "true", "--xml-validation", "never",
            "--duration-log.statistics", "true", "--statistic-output", "stats.xml",
            "--summary-output", "summary.xml", "--summary-output.period", "10",
            "--collision.action", "warn"]
    _, err = run_sumo(args, "fwy g=%g p=%g s=%d" % (grade_pct, p, seed), cwd=outdir)
    with open(os.path.join(outdir, "sumo.stderr.txt"), "w") as f:
        f.write(err)
    return dict(n_generated=n, n_hv_generated=k)


# ------------------------------------------------------------------ parsing --
def parse_e1(path, warmup, end):
    """-> per-detector list of dicts for intervals inside [warmup, end)."""
    out = {}
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "interval":
            b = float(el.get("begin"))
            if warmup <= b < end:
                out.setdefault(el.get("id"), []).append(
                    dict(begin=b, end=float(el.get("end")),
                         n=float(el.get("nVehContrib")),
                         flow=float(el.get("flow")),
                         occ=float(el.get("occupancy")),
                         hspeed=float(el.get("harmonicMeanSpeed")),
                         speed=float(el.get("speed")),
                         length=float(el.get("length"))))
            el.clear()
    return out


def parse_lad(path, warmup, end):
    out = {}
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "interval":
            b = float(el.get("begin"))
            if warmup <= b < end:
                out.setdefault(el.get("id"), []).append(
                    dict(begin=b, meanSpeed=float(el.get("meanSpeed")),
                         maxJamVeh=float(el.get("maxJamLengthInVehicles")),
                         maxJamM=float(el.get("maxJamLengthInMeters")),
                         meanVeh=float(el.get("meanVehicleNumber"))))
            el.clear()
    return out


def parse_instant(path, warmup, end):
    ev = []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "instantOut" and el.get("state") == "leave":
            t = float(el.get("time"))
            if warmup <= t < end:
                vid = el.get("vehID") or ""
                ev.append((t, vid.rsplit("_", 1)[-1], float(el.get("speed", 0))))
            el.clear()
    ev.sort()
    return ev


def parse_stats(path):
    r = ET.parse(path).getroot()
    return {t: dict(r.find(t).attrib) for t in
            ("vehicles", "teleports", "safety", "vehicleTripStatistics")
            if r.find(t) is not None}


def analyse_run(outdir, warmup=FWY_WARMUP, end=FWY_TEND):
    cap = parse_e1(os.path.join(outdir, "e1_cap.xml"), warmup, end)["cap_0"]
    up = parse_e1(os.path.join(outdir, "e1_up.xml"), warmup, end)
    lad = parse_lad(os.path.join(outdir, "e2_q.xml"), warmup, end)
    ev = parse_instant(os.path.join(outdir, "instant_cap.xml"), warmup, end)
    st = parse_stats(os.path.join(outdir, "stats.xml"))

    dur = cap[0]["end"] - cap[0]["begin"]
    ntot = sum(c["n"] for c in cap)
    capacity = ntot / (len(cap) * dur) * 3600.0
    # stationarity of the discharge series over the measurement window
    ts = [c["begin"] for c in cap]
    fs = [c["n"] / dur * 3600.0 for c in cap]
    a, b, r2 = ols(ts, fs)
    trend_per_hour = b * 3600.0

    # upstream station: space-mean speed via HARMONIC mean, per lane then combined
    n_up = 0.0
    inv = 0.0
    occs = []
    for det, rows in up.items():
        nl = sum(r["n"] for r in rows)
        # harmonic combination weighted by counts
        s = 0.0
        for r in rows:
            if r["hspeed"] > 0 and r["n"] > 0:
                s += r["n"] / r["hspeed"]
        n_up += nl
        inv += s
        occs.append(sum(r["occ"] for r in rows) / len(rows))
    v_up = n_up / inv if inv > 0 else None

    jam = {d: max(r["maxJamVeh"] for r in rows) for d, rows in lad.items()}
    jam_mean = {d: sum(r["maxJamVeh"] for r in rows) / len(rows) for d, rows in lad.items()}

    # per-vehicle-class discharge headways at the bottleneck station
    hw = {"c": [], "t": []}
    for i in range(1, len(ev)):
        hw[ev[i][1]].append(ev[i][0] - ev[i - 1][0])
    hv_share = (sum(1 for e in ev if e[1] == "t") / len(ev)) if ev else 0.0
    sp = {"c": [e[2] for e in ev if e[1] == "c"], "t": [e[2] for e in ev if e[1] == "t"]}

    return dict(
        capacity_vph=capacity, n_discharged=ntot, n_intervals=len(cap),
        interval_flows=fs, trend_vph_per_hour=trend_per_hour, trend_r2=r2,
        discharge_speed_ms=sum(c["hspeed"] * c["n"] for c in cap) / ntot if ntot else None,
        cap_occupancy=sum(c["occ"] for c in cap) / len(cap),
        upstream_space_mean_speed_ms=v_up,
        upstream_occupancy_pct=sum(occs) / len(occs) if occs else None,
        queue_maxJamVeh_per_lane=jam, queue_meanJamVeh_per_lane=jam_mean,
        hv_share_discharged=hv_share, n_events=len(ev),
        mean_headway_car=sum(hw["c"]) / len(hw["c"]) if hw["c"] else None,
        mean_headway_hv=sum(hw["t"]) / len(hw["t"]) if hw["t"] else None,
        n_headway_car=len(hw["c"]), n_headway_hv=len(hw["t"]),
        mean_cross_speed_car=sum(sp["c"]) / len(sp["c"]) if sp["c"] else None,
        mean_cross_speed_hv=sum(sp["t"]) / len(sp["t"]) if sp["t"] else None,
        teleports=int(st["teleports"]["total"]), collisions=int(st["safety"]["collisions"]),
        emergency_stops=int(st["safety"].get("emergencyStops", 0)),
        inserted=int(st["vehicles"]["inserted"]), loaded=int(st["vehicles"]["loaded"]),
        running_at_end=int(st["vehicles"]["running"]),
    )
