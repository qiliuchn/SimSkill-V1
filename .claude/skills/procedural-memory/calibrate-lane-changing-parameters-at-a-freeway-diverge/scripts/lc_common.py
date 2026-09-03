#!/usr/bin/env python3
"""Shared machinery for the LC2013 lane-change calibration episode
(freeway off-ramp DIVERGE, no on-ramp, no shared auxiliary lane).

FACILITY (hand-authored plain XML -> netconvert, NOT netgenerate)
-----------------------------------------------------------------
  x =    0 .. 600   edge A  3 lanes 120 km/h   insertion settling zone
  x =  600 .. 2100  edge B  3 lanes 120 km/h   DISCRETIONARY-LC measurement window
                                               (exactly the 1.5 km upstream of the station)
  x = 2100 .. 3300  edge C  3 lanes 120 km/h   STATION at x=2100 (= C's entry cross-section,
                                               1.5 km upstream of the gore)
  x = 3300 .. 3600  edge D  4 lanes            lane 0 = 300 m deceleration/auxiliary lane
                                               (no upstream connection -> reachable only by LC)
  x = 3600 .. 4200  edge E  3 lanes            mainline continuation
  x = 3600 .. ~4004 edge R  1 lane  80 km/h    off-ramp
  GORE  = x 3600.

Connections (all explicit):
  A_i->B_i->C_i (i=0,1,2);  C_0->D_1, C_1->D_2, C_2->D_3;
  D_1->E_0, D_2->E_1, D_3->E_2;  D_0->R_0.
=> the ONLY path to R is  ... C_0 -> D_1 -> (lane change) -> D_0 -> R_0.
   An exiting vehicle must therefore be in the RIGHTMOST THROUGH lane, so its exit
   manoeuvre is a genuine mandatory (strategic) lane change.
"""
import os, sys, math, json, subprocess, shutil, hashlib
import xml.etree.ElementTree as ET

SUMO_BIN = "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/bin"
SUMO = os.path.join(SUMO_BIN, "sumo")
NETCONVERT = os.path.join(SUMO_BIN, "netconvert")

EP = "/Users/liuqi/Desktop/simskill/episodic-memory/2026-08-05_08-00-00"
SCRIPTS = os.path.join(EP, "attempts/attempt-1/scripts")
OUT = os.path.join(EP, "outputs")
NETDIR = os.path.join(OUT, "net")
DEMDIR = os.path.join(OUT, "demand")
TBL = os.path.join(OUT, "tables")
FIG = os.path.join(OUT, "figures")
LOGS = os.path.join(OUT, "logs")
RUNS = ("/private/tmp/claude-501/-Users-liuqi-Desktop-simskill/"
        "73c4d241-de1e-411f-9fbf-eda6b9d3b094/scratchpad/lcruns")
for d in (NETDIR, DEMDIR, TBL, FIG, LOGS, RUNS):
    os.makedirs(d, exist_ok=True)

NET = os.path.join(NETDIR, "diverge.net.xml")

# ---- geometry constants (must match build_net.py) -------------------------
EDGE_X0 = {"A": 0.0, "B": 600.0, "C": 2100.0, "D": 3300.0, "E": 3600.0, "R": 3600.0}
EDGE_LEN = {"A": 600.0, "B": 1500.0, "C": 1200.0, "D": 300.0, "E": 600.0}
GORE_X = 3600.0
STATION_X = 2100.0          # 1.5 km upstream of the gore
LC_WINDOW_EDGE = "B"        # the 1.5 km upstream of the station
LC_WINDOW_KM = 1.5
FREE_SPEED = 33.33          # 120 km/h

# lanes from which the ramp is reachable without a further *leftward-blocked* move
EXIT_READY = {"A_0", "B_0", "C_0", "D_1", "D_0"}
RIGHTMOST_THROUGH = {"A_0", "B_0", "C_0", "D_1"}

# ---- run window ----------------------------------------------------------
WARMUP = 300.0
T_END_MEAS = 3900.0         # measurement window [WARMUP, T_END_MEAS] = 3600 s
FLOW_END = 4000.0
SIM_END = 4150.0
E1_PERIOD = 60.0

STEP_LENGTH = 0.5
STEP_METHOD = "ballistic"

# --------------------------------------------------------------------------
#  FIELD TARGETS  (stated explicitly up front; treated as field data)
# --------------------------------------------------------------------------
# (a) per-lane flow SHARE at the station 1.5 km upstream of the gore.
#     right(lane0)/middle(lane1)/left(lane2).  A typical 3-lane 120 km/h
#     directional freeway at ~1600 veh/h/ln with 10% HGV runs left-loaded.
TARGET_LANE_SHARE = {0: 0.28, 1: 0.35, 2: 0.37}
# (b) DISCRETIONARY lane-change rate over the 1.5 km upstream of the station
#     (= edge B), LC per vehicle per km.  Discretionary := reason speedGain or
#     keepRight (cooperative and strategic are reported separately).
TARGET_DLC = 0.45           # LC/veh/km
# (c) spatial mandatory-LC target: 85th percentile of the distance-to-gore of
#     the LAST lane change into the rightmost THROUGH lane, over exiting
#     vehicles that performed at least one such change.
TARGET_P85 = 400.0          # m
# ... and essentially no exiting vehicle still left of the exit-capable lanes
#     at the gore.
TARGET_FAILFRAC = 0.0
TOL_FAILFRAC = 0.005        # 0.5% treated as "essentially none"

OBJ_WEIGHTS = dict(lane=2.0, dlc=1.0, p85=1.5, fail=1.0)

# --------------------------------------------------------------------------
#  LC2013 PARAMETER SPACE
# --------------------------------------------------------------------------
# name -> (low, high, default)
PARAM_SPACE = {
    "lcStrategic":     (0.05, 6.00, 1.0),
    "lcCooperative":   (0.00, 1.00, 1.0),
    "lcSpeedGain":     (0.05, 6.00, 1.0),
    "lcKeepRight":     (0.00, 6.00, 1.0),
    "lcAssertive":     (0.50, 3.00, 1.0),
    "lcLookaheadLeft": (0.50, 8.00, 2.0),
    "lcSpeedGainRight": (0.05, 3.00, 1.0),
    "lcDuration":      (0.00, 4.00, 0.0),   # the --lanechange.duration SETTING
}
LC_NAMES = list(PARAM_SPACE.keys())
LC_DEFAULTS = {k: v[2] for k, v in PARAM_SPACE.items()}
VTYPE_LC = [n for n in LC_NAMES if n != "lcDuration"]   # vType attributes


def full_params(overrides=None):
    p = dict(LC_DEFAULTS)
    if overrides:
        p.update({k: v for k, v in overrides.items() if k in p})
    return p


def unit_to_params(u, names=None):
    names = names or LC_NAMES
    p = full_params()
    for n, x in zip(names, u):
        lo, hi, _ = PARAM_SPACE[n]
        p[n] = lo + float(x) * (hi - lo)
    return p


def params_to_unit(p, names=None):
    names = names or LC_NAMES
    return [(p[n] - PARAM_SPACE[n][0]) / (PARAM_SPACE[n][1] - PARAM_SPACE[n][0])
            for n in names]


# --------------------------------------------------------------------------
#  DEMAND
# --------------------------------------------------------------------------
def routes_xml(p, mainline_per_lane=1600.0, exit_share=0.20, hgv_share=0.10,
               flow_end=FLOW_END, lcmodel="LC2013"):
    """Route-BASED flows (not randomTrips): every vehicle's exit intention is
    known a priori from which of the two routes it is on."""
    tot = mainline_per_lane * 3.0
    lc = " ".join('%s="%.5f"' % (n, p[n]) for n in VTYPE_LC)
    rows = [
        ("f_thru_car", "car", "thru", tot * (1 - exit_share) * (1 - hgv_share)),
        ("f_thru_hgv", "hgv", "thru", tot * (1 - exit_share) * hgv_share),
        ("f_exit_car", "car", "exit", tot * exit_share * (1 - hgv_share)),
        ("f_exit_hgv", "hgv", "exit", tot * exit_share * hgv_share),
    ]
    s = ['<routes>']
    s.append('  <vType id="car" vClass="passenger" carFollowModel="Krauss" '
             'length="5.0" minGap="2.5" accel="2.6" decel="4.5" tau="1.0" '
             'sigma="0.5" maxSpeed="55.55" speedFactor="normc(1.0,0.10,0.20,2.00)" '
             'laneChangeModel="%s" %s/>' % (lcmodel, lc))
    s.append('  <vType id="hgv" vClass="truck" carFollowModel="Krauss" '
             'length="12.0" minGap="2.5" accel="1.3" decel="4.0" tau="1.2" '
             'sigma="0.5" maxSpeed="25.0" speedFactor="normc(1.0,0.05,0.20,2.00)" '
             'laneChangeModel="%s" %s/>' % (lcmodel, lc))
    s.append('  <route id="thru" edges="A B C D E"/>')
    s.append('  <route id="exit" edges="A B C D R"/>')
    for fid, ty, ro, vph in rows:
        s.append('  <flow id="%s" type="%s" route="%s" begin="0" end="%.0f" '
                 'vehsPerHour="%.4f" departLane="random" departSpeed="max"/>'
                 % (fid, ty, ro, flow_end, vph))
    s.append('</routes>')
    return "\n".join(s)


def additional_xml(t0=WARMUP, t1=T_END_MEAS):
    """laneData + edgeData meandata AND per-lane E1 loops at the station, so the
    two independent instruments can be cross-checked before either is trusted.
    NOTE: a meandata `file` path resolves relative to the ADDITIONAL file's own
    directory (verified prior finding) -- every run gets its own copy, so plain
    filenames are safe here."""
    s = ['<additional>']
    s.append('  <laneData id="ld" file="lanedata.xml" begin="%.0f" end="%.0f" '
             'excludeEmpty="false"/>' % (t0, t1))
    s.append('  <edgeData id="ed" file="edgedata.xml" begin="%.0f" end="%.0f" '
             'excludeEmpty="false"/>' % (t0, t1))
    for ln in range(3):
        s.append('  <inductionLoop id="e1_C_%d" lane="C_%d" pos="1.0" '
                 'period="%.0f" file="e1.xml"/>' % (ln, ln, E1_PERIOD))
    s.append('</additional>')
    return "\n".join(s)


# --------------------------------------------------------------------------
#  RUN
# --------------------------------------------------------------------------
def run_scenario(workdir, p, seed=42, net=NET, sublane=None, lcmodel="LC2013",
                 mainline_per_lane=1600.0, exit_share=0.20, hgv_share=0.10,
                 sim_end=SIM_END, flow_end=FLOW_END, t0=WARMUP, t1=T_END_MEAS,
                 extra_args=None, keep=True):
    os.makedirs(workdir, exist_ok=True)
    rou = os.path.join(workdir, "d.rou.xml")
    add = os.path.join(workdir, "d.add.xml")
    with open(rou, "w") as f:
        f.write(routes_xml(p, mainline_per_lane, exit_share, hgv_share,
                           flow_end, lcmodel=lcmodel))
    with open(add, "w") as f:
        f.write(additional_xml(t0, t1))
    args = [SUMO, "-n", net, "-r", rou, "-a", add,
            "--lanechange-output", os.path.join(workdir, "lanechanges.xml"),
            "--tripinfo-output", os.path.join(workdir, "tripinfo.xml"),
            "--summary-output", os.path.join(workdir, "summary.xml"),
            "--statistic-output", os.path.join(workdir, "stats.xml"),
            "--begin", "0", "--end", "%.0f" % sim_end,
            "--step-length", str(STEP_LENGTH),
            "--step-method.%s" % STEP_METHOD, "true",
            "--lanechange.duration", "%.4f" % p.get("lcDuration", 0.0),
            "--time-to-teleport", "900",
            "--collision.action", "warn",
            "--no-step-log", "true", "--xml-validation", "never",
            "--seed", str(seed)]
    if sublane is not None:
        args += ["--lateral-resolution", str(sublane)]
        # --lanechange.duration is incompatible with the sublane model
        i = args.index("--lanechange.duration"); del args[i:i + 2]
    if extra_args:
        args += list(extra_args)
    r = subprocess.run(args, capture_output=True, text=True, timeout=1800)
    with open(os.path.join(workdir, "stderr.txt"), "w") as f:
        f.write(r.stderr)
    with open(os.path.join(workdir, "cmd.txt"), "w") as f:
        f.write(" ".join(args))
    return r


# --------------------------------------------------------------------------
#  PARSERS  -- every number below comes from one of these raw SUMO files
# --------------------------------------------------------------------------
def parse_lanechanges(path):
    """--lanechange-output event XML -> list of dicts (a dataframe row each),
    keyed by vehicle id, time, from/to lane, LONGITUDINAL position and reason."""
    ev = []
    n_dropped = [0]
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag != "change":
            continue
        a = el.attrib
        frm = a["from"]; to = a["to"]
        e_from = frm.rsplit("_", 1)[0]
        pos = float(a.get("pos", "nan"))
        x = EDGE_X0.get(e_from, float("nan")) + pos
        if e_from not in EDGE_X0:
            # a lane change logged on an internal junction lane cannot be
            # located on the corridor's x axis; SUMO does not normally emit
            # these (verified: 0 of 12988 events in the baseline run) but drop
            # them explicitly rather than propagating a NaN position.
            n_dropped[0] += 1
            el.clear()
            continue
        ev.append(dict(veh=a["id"], vtype=a.get("type", ""),
                       t=float(a["time"]), frm=frm, to=to,
                       edge=e_from, pos=pos, x=x,
                       lane_from=int(frm.rsplit("_", 1)[1]),
                       lane_to=int(to.rsplit("_", 1)[1]),
                       dir=int(a.get("dir", "0")),
                       speed=float(a.get("speed", "nan")),
                       reason=a.get("reason", "")))
        el.clear()
    ev.sort(key=lambda r: (r["veh"], r["t"]))
    parse_lanechanges.n_dropped_internal = n_dropped[0]
    return ev


REASON_CLASSES = ["strategic", "cooperative", "speedGain", "keepRight", "sublane", "other"]


def reason_class(reason):
    """SUMO writes the reason as a '|'-joined string, e.g. 'strategic|urgent'.
    Classify by the leading motivation token, keeping the qualifier separately."""
    toks = reason.split("|")
    for c in ("strategic", "cooperative", "speedGain", "keepRight", "sublane"):
        if c in toks:
            return c
    return "other"


def parse_lanedata(path):
    """laneData meandata -> {(edge, lane_index): {...}} for the LAST interval."""
    out = {}
    tree = ET.parse(path)
    for iv in tree.getroot().findall("interval"):
        for e in iv.findall("edge"):
            eid = e.get("id")
            for ln in e.findall("lane"):
                idx = int(ln.get("id").rsplit("_", 1)[1])
                out[(eid, idx)] = {k: v for k, v in ln.attrib.items()}
    return out


def parse_edgedata(path):
    out = {}
    tree = ET.parse(path)
    for iv in tree.getroot().findall("interval"):
        for e in iv.findall("edge"):
            out[e.get("id")] = {k: v for k, v in e.attrib.items()}
    return out


def parse_e1(path, t0=None, t1=None):
    """inductionLoop output -> {lane_index: nVehContrib} summed over the
    intervals that fall inside [t0, t1) (the same window as the meandata)."""
    out = {}
    tree = ET.parse(path)
    for iv in tree.getroot().findall("interval"):
        b = float(iv.get("begin")); e = float(iv.get("end"))
        if t0 is not None and (b < t0 - 1e-6 or e > t1 + 1e-6):
            continue
        idx = int(iv.get("id").rsplit("_", 1)[1])
        out[idx] = out.get(idx, 0.0) + float(iv.get("nVehContrib", "0"))
    return out


def parse_tripinfo(path):
    rows = []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag != "tripinfo":
            continue
        a = el.attrib
        rows.append(dict(veh=a["id"], depart=float(a["depart"]),
                         departLane=a.get("departLane", ""),
                         departDelay=float(a.get("departDelay", "0")),
                         arrival=float(a["arrival"]),
                         arrivalLane=a.get("arrivalLane", ""),
                         duration=float(a["duration"]),
                         timeLoss=float(a["timeLoss"]),
                         vtype=a.get("vType", "")))
        el.clear()
    return rows


def parse_summary(path):
    rows = []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "step":
            rows.append({k: float(v) for k, v in el.attrib.items()})
            el.clear()
    return rows


def parse_stats(path):
    d = {}
    root = ET.parse(path).getroot()
    for ch in root:
        for k, v in ch.attrib.items():
            d["%s.%s" % (ch.tag, k)] = v
    return d


# --------------------------------------------------------------------------
#  FEATURE EXTRACTION
# --------------------------------------------------------------------------
def is_exiter(vid):
    return vid.startswith("f_exit")


def extract_features(workdir, t0=WARMUP, t1=T_END_MEAS, want_profiles=False):
    """Turn one run's raw output into the calibration feature vector."""
    lcp = os.path.join(workdir, "lanechanges.xml")
    ev = parse_lanechanges(lcp)
    evw = [e for e in ev if t0 <= e["t"] < t1]

    ld = parse_lanedata(os.path.join(workdir, "lanedata.xml"))
    ed = parse_edgedata(os.path.join(workdir, "edgedata.xml"))
    e1 = parse_e1(os.path.join(workdir, "e1.xml"), t0, t1)
    tri = parse_tripinfo(os.path.join(workdir, "tripinfo.xml"))
    stats = parse_stats(os.path.join(workdir, "stats.xml"))
    stderr = open(os.path.join(workdir, "stderr.txt")).read()

    dur_h = (t1 - t0) / 3600.0

    # ---- (a) per-lane flow at the station, from laneData `entered` on edge C
    ent = {i: float(ld[("C", i)]["entered"]) for i in range(3) if ("C", i) in ld}
    tot_ld = sum(ent.values())
    share_ld = {i: (ent.get(i, 0.0) / tot_ld if tot_ld else float("nan")) for i in range(3)}
    tot_e1 = sum(e1.values())
    share_e1 = {i: (e1.get(i, 0.0) / tot_e1 if tot_e1 else float("nan")) for i in range(3)}

    # ---- (b) discretionary LC rate on edge B (the 1.5 km upstream of station)
    evB = [e for e in evw if e["edge"] == LC_WINDOW_EDGE]
    cls = {}
    for e in evw:
        c = reason_class(e["reason"])
        cls[c] = cls.get(c, 0) + 1
    clsB = {}
    for e in evB:
        c = reason_class(e["reason"])
        clsB[c] = clsB.get(c, 0) + 1
    vehB = float(ed["B"]["entered"]) if "B" in ed else float("nan")
    vehkmB = vehB * LC_WINDOW_KM
    n_disc_B = clsB.get("speedGain", 0) + clsB.get("keepRight", 0)
    dlc = n_disc_B / vehkmB if vehkmB > 0 else float("nan")
    coop_rate = clsB.get("cooperative", 0) / vehkmB if vehkmB > 0 else float("nan")
    strat_rate = clsB.get("strategic", 0) / vehkmB if vehkmB > 0 else float("nan")

    # ---- (c) spatial mandatory-LC statistics for EXITING vehicles
    dep_lane = {r["veh"]: r["departLane"] for r in tri}
    by_veh = {}
    for e in ev:
        by_veh.setdefault(e["veh"], []).append(e)

    d_last, d_arr, no_change, failed = [], [], 0, 0
    exiters = [v for v in dep_lane if is_exiter(v)]
    # restrict to vehicles that DEPARTED inside the measurement window so the
    # spatial statistic is over a homogeneous cohort
    dep_t = {r["veh"]: r["depart"] for r in tri}
    coh = [v for v in exiters if t0 <= dep_t[v] < t1]
    arrive_curve = []            # (distance_to_gore) per exiting vehicle
    for v in coh:
        evs = by_veh.get(v, [])
        # last transition  (left of rightmost-through) -> (rightmost through lane)
        last_x = None
        for e in evs:
            if e["to"] in RIGHTMOST_THROUGH and e["frm"] not in EXIT_READY:
                last_x = e["x"]
        if last_x is not None:
            d_last.append(GORE_X - last_x)
        else:
            no_change += 1
        # cumulative "has reached an exit-capable lane" -- departure lane counts
        start_lane = dep_lane[v]
        cur_ready = start_lane in EXIT_READY
        arr_x = 0.0 if cur_ready else None
        for e in evs:
            was = cur_ready
            cur_ready = e["to"] in EXIT_READY
            if cur_ready and not was:
                arr_x = e["x"]
            elif not cur_ready:
                arr_x = None
        if arr_x is None:
            failed += 1
        else:
            arrive_curve.append(GORE_X - arr_x)
    d_last.sort()

    # ---- diagnostic: lane occupied AT THE STATION (x=2100), split by whether
    # the vehicle is an exiter.  This is what actually connects target (a) to
    # target (c): the aggregate lane split can be met by THROUGH traffic while
    # the exiters are still left, or not.
    def lane_at(vid, x_at):
        lane = dep_lane.get(vid, "")
        for e in by_veh.get(vid, []):
            if e["x"] <= x_at:
                lane = e["to"]
            else:
                break
        return lane

    coh_all = [r["veh"] for r in tri if t0 <= r["depart"] < t1]
    ex0 = th0 = nex = nth = 0
    for v in coh_all:
        ln = lane_at(v, STATION_X)
        r0 = ln.endswith("_0")
        if is_exiter(v):
            nex += 1; ex0 += 1 if r0 else 0
        else:
            nth += 1; th0 += 1 if r0 else 0

    def pct(a, q):
        if not a:
            return float("nan")
        k = (len(a) - 1) * q
        lo, hi = int(math.floor(k)), int(math.ceil(k))
        return a[lo] if lo == hi else a[lo] + (a[hi] - a[lo]) * (k - lo)

    p85 = pct(d_last, 0.85)
    fail_frac = failed / len(coh) if coh else float("nan")

    # ---- sanity / contamination accounting -------------------------------
    smy = parse_summary(os.path.join(workdir, "summary.xml"))
    last = smy[-1] if smy else {}
    tel_wrong = stderr.count("wrong lane")
    tel_all = int(float(stats.get("teleports.total", "0")))
    collisions = int(float(stats.get("safety.collisions", "0")))
    loaded = int(float(stats.get("vehicles.loaded", "0")))
    inserted = int(float(stats.get("vehicles.inserted", "0")))
    dep_delay = float(stats.get("vehicleTripStatistics.departDelay", "nan"))

    feat = dict(
        share_ld=share_ld, share_e1=share_e1, entered_C=ent, e1=e1,
        flow_station_vph=tot_ld / dur_h,
        dlc=dlc, coop_rate=coop_rate, strat_rate=strat_rate,
        n_lc_window=len(evw), reason_counts=cls, reason_counts_B=clsB,
        veh_B=vehB, vehkm_B=vehkmB,
        p85=p85, p50=pct(d_last, 0.50), p15=pct(d_last, 0.15),
        n_dlast=len(d_last), n_nochange=no_change, n_cohort=len(coh),
        fail_frac=fail_frac, n_failed=failed,
        teleports=tel_all, teleports_wrong_lane=tel_wrong,
        collisions=collisions, loaded=loaded, inserted=inserted,
        not_inserted=loaded - inserted, depart_delay=dep_delay,
        running_end=last.get("running", float("nan")),
        ended_total=last.get("ended", float("nan")),
        halting_end=last.get("halting", float("nan")),
        ramp_entered=float(ed["R"]["entered"]) if "R" in ed else float("nan"),
        E_entered=float(ed["E"]["entered"]) if "E" in ed else float("nan"),
        edge_C_entered=float(ed["C"]["entered"]) if "C" in ed else float("nan"),
        lane_C_entered_sum=tot_ld,
        mean_speed_C=float(ld[("C", 0)].get("speed", "nan")) if ("C", 0) in ld
        else float("nan"),
        edge_C_speed=float(ed["C"].get("speed", "nan")) if "C" in ed else float("nan"),
        exiter_lane0_at_station=(ex0 / nex if nex else float("nan")),
        through_lane0_at_station=(th0 / nth if nth else float("nan")),
        n_exiters_station=nex, n_through_station=nth,
    )
    if want_profiles:
        feat["d_last_sorted"] = d_last
        feat["arrive_curve"] = sorted(arrive_curve)
        feat["events"] = evw
    return feat


def geh(m, c):
    return math.sqrt((m - c) ** 2 / max((m + c) / 2.0, 1e-9))


def objective(feat, weights=None, target_lane=None, target_dlc=TARGET_DLC,
              target_p85=TARGET_P85):
    w = weights or OBJ_WEIGHTS
    tl = target_lane or TARGET_LANE_SHARE
    sh = feat["share_ld"]
    errs = []
    for i in range(3):
        m = sh.get(i, float("nan"))
        errs.append(1.0 if m != m else (m - tl[i]) / tl[i])
    rmsn_lane = math.sqrt(sum(e * e for e in errs) / 3.0)
    # GEH on per-lane FLOWS: the target lane flow is the OBSERVED total station
    # flow times the target share, so GEH scores the SPLIT, not the total.
    tot = feat["flow_station_vph"]
    gehs = [geh(sh.get(i, 0.0) * tot, tl[i] * tot) for i in range(3)]

    # dlc and p85 are ratio-scale positive quantities spanning >1 order of
    # magnitude across the parameter space, so a plain relative error saturates
    # the clip and flattens the surface.  Use a LOG-ratio error normalised so
    # that "wrong by a factor of 3" scores 1.0, i.e. comparable in magnitude to
    # a 100% relative error on the lane shares.
    LN3 = math.log(3.0)
    def logerr(m, t):
        if m != m or m <= 0:
            return 3.0
        return math.log(m / t) / LN3
    e_dlc = logerr(feat["dlc"], target_dlc)
    e_p85 = logerr(feat["p85"], target_p85)
    ff = feat["fail_frac"]
    e_fail = 1.0 if ff != ff else max(0.0, (ff - TARGET_FAILFRAC)) / 0.05

    cl = lambda x: max(min(x, 3.0), -3.0)
    e_dlc, e_p85, e_fail = cl(e_dlc), cl(e_p85), cl(e_fail)
    num = (w["lane"] * rmsn_lane ** 2 + w["dlc"] * e_dlc ** 2 +
           w["p85"] * e_p85 ** 2 + w["fail"] * e_fail ** 2)
    den = w["lane"] + w["dlc"] + w["p85"] + w["fail"]
    # Optional HINGE on the practitioner acceptance criterion itself, for the
    # case where the weighted optimum lands outside GEH<5: the lane-share RMSN
    # term alone is far too weak to enforce it (RMSN ~0.05 where the spatial
    # term is ~0.4).  NOT USED in this episode's reported calibration -- the
    # unconstrained optimum passed GEH<5 on 12 independent seeds (max 2.65), so
    # the hinge stays at weight 0 and the objective is exactly the 4-term one.
    wg = w.get("geh", 0.0)
    e_geh = max(0.0, max(gehs) - 5.0) / 5.0
    if wg > 0:
        num += wg * cl(e_geh) ** 2
        den += wg
    return dict(obj=math.sqrt(num / den), rmsn_lane=rmsn_lane, geh=gehs,
                geh_max=max(gehs), e_dlc=e_dlc, e_p85=e_p85, e_fail=e_fail,
                e_geh=e_geh, lane_errs=errs)
