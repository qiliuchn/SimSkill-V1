#!/usr/bin/env python3
"""
Scenario generation + raw-output parsing helpers for the SUMO toll-plaza queueing study.

Everything measured downstream comes out of raw SUMO output files:
  stop-output      -> realized service times (ended-started) per vehicle per booth
  instant loops    -> per-vehicle plaza-entry timestamps and per-booth departure timestamps
  e2 detector      -> jamLengthInMeters on the 2-lane mainline approach (spillback)
  e3 detector      -> in-zone vehicle count / mean in-zone time (Little's law cross-check)
  tripinfo         -> per-vehicle duration / waitingTime / timeLoss / departDelay
"""
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET

import numpy as np

BOOTH_STOP_POS = 25.0      # m from the start of the 30 m booth island
ENTRY_POS = 1190.0         # m along the 1196 m `app` edge -> plaza-system entry line
DEP_POS = 10.0             # m along chout_i -> booth departure line


def find_bin(name):
    p = shutil.which(name)
    if p:
        return p
    sumo = shutil.which("sumo")
    if sumo:
        c = os.path.join(os.path.dirname(sumo), name)
        if os.path.exists(c):
            return c
    home = os.environ.get("SUMO_HOME")
    if home:
        c = os.path.join(home, "bin", name)
        if os.path.exists(c):
            return c
    raise RuntimeError("cannot find " + name)


# --------------------------------------------------------------------------- #
# service-time distributions
# --------------------------------------------------------------------------- #
def lane_lengths(net_file):
    """{lane_id: length} for every non-internal lane in a compiled .net.xml."""
    out = {}
    for e in ET.parse(net_file).getroot().findall("edge"):
        if e.get("function") == "internal":
            continue
        for ln in e.findall("lane"):
            out[ln.get("id")] = float(ln.get("length"))
    return out


def draw_service(rng, dist, mean, n):
    """Return n service-time draws with the requested mean and shape."""
    if dist == "exp":
        s = rng.exponential(mean, n)
    elif dist == "erlang8":
        s = rng.gamma(8.0, mean / 8.0, n)
    elif dist == "det":
        s = np.full(n, float(mean))
    else:
        raise ValueError(dist)
    # SUMO cannot represent a stop shorter than one simulation step; clip and report.
    return np.clip(s, 0.5, 300.0)


# --------------------------------------------------------------------------- #
# scenario writer
# --------------------------------------------------------------------------- #
def write_scenario(run_dir, net_file, booths, veh_rate, horizon,
                   seed=1, service_dist="exp", service_mean=8.0,
                   etc_share=0.0, etc_mean=3.0, etc_booths=0,
                   assign="random", stop_mode="route",
                   booth_speed_service=False, no_stops=False,
                   step_length=0.5, end_pad=1800.0, warmup=600.0):
    """
    Write <run_dir>/plaza.rou.xml, plaza.add.xml, plaza.sumocfg.

    assign      : 'random' (Bernoulli split of the Poisson stream over booths)
                  'roundrobin'
                  'traci'  (routes carry a placeholder booth; the TraCI assigner overrides)
    stop_mode   : 'route' (service stop written into the route file)
                  'traci' (no stop in the route file; imposed at runtime by setStop)
    no_stops    : open-road all-electronic tolling reference -> no service at all
    booth_speed_service : instead of a <stop>, slow the booth lane via a variableSpeedSign
                  (mechanism (b)); service time then = 30 m / v_booth, deterministic
    """
    run_dir = os.path.abspath(run_dir)   # every output path in the cfg/add must be absolute
    os.makedirs(run_dir, exist_ok=True)
    rng = np.random.default_rng(seed)

    # ---- Poisson arrival process ----
    n_expect = int(veh_rate / 3600.0 * horizon * 1.4) + 200
    gaps = rng.exponential(3600.0 / veh_rate, n_expect)
    times = np.cumsum(gaps)
    times = times[times < horizon]
    n = len(times)

    is_etc = rng.random(n) < etc_share
    etc_set = set(range(etc_booths))                     # rightmost booths reserved
    man_booths = [b for b in range(booths) if b not in etc_set]
    if not man_booths:                                   # all booths ETC-only
        man_booths = list(range(booths))

    booth_of = np.empty(n, dtype=int)
    for k in range(n):
        if etc_booths > 0:
            pool = sorted(etc_set) if is_etc[k] else man_booths
        else:
            pool = list(range(booths))
        if assign == "roundrobin":
            booth_of[k] = pool[k % len(pool)]
        else:
            booth_of[k] = pool[rng.integers(len(pool))]

    svc = np.where(is_etc,
                   draw_service(rng, service_dist, etc_mean, n),
                   draw_service(rng, service_dist, service_mean, n))

    # ---- route file ----
    rou = os.path.join(run_dir, "plaza.rou.xml")
    L = ['<?xml version="1.0" encoding="UTF-8"?>', "<routes>"]
    L.append('    <vType id="manual" vClass="passenger" length="5.0" minGap="2.5" '
             'accel="2.6" decel="4.5" tau="1.0" sigma="0.5" speedDev="0" maxSpeed="30"/>')
    L.append('    <vType id="etc" vClass="custom1" length="5.0" minGap="2.5" '
             'accel="2.6" decel="4.5" tau="1.0" sigma="0.5" speedDev="0" maxSpeed="30"/>')
    for b in range(booths):
        L.append('    <route id="r%d" edges="app fan lock chin_%d booth_%d chout_%d post exit"/>' % (b, b, b, b))
    for k in range(n):
        b = int(booth_of[k])
        vt = "etc" if is_etc[k] else "manual"
        L.append('    <vehicle id="v%d" type="%s" route="r%d" depart="%.2f" '
                 'departLane="best" departSpeed="max">' % (k, vt, b, times[k]))
        if (not no_stops) and (not booth_speed_service) and stop_mode == "route":
            L.append('        <stop lane="booth_%d_0" endPos="%.1f" duration="%.2f" parking="false"/>'
                     % (b, BOOTH_STOP_POS, svc[k]))
        L.append("    </vehicle>")
    L.append("</routes>")
    open(rou, "w").write("\n".join(L) + "\n")

    # ---- additional file (detectors) ----
    add = os.path.join(run_dir, "plaza.add.xml")
    A = ['<?xml version="1.0" encoding="UTF-8"?>', "<additional>"]
    inst = os.path.join(run_dir, "instant.xml")
    e2f = os.path.join(run_dir, "e2.xml")
    e3f = os.path.join(run_dir, "e3.xml")
    for ln in (0, 1):
        A.append('    <instantInductionLoop id="ent_%d" lane="app_%d" pos="%.1f" file="%s"/>'
                 % (ln, ln, ENTRY_POS, inst))
    for b in range(booths):
        A.append('    <instantInductionLoop id="bin_%d" lane="booth_%d_0" pos="1.0" file="%s"/>'
                 % (b, b, inst))
        A.append('    <instantInductionLoop id="dep_%d" lane="chout_%d_0" pos="%.1f" file="%s"/>'
                 % (b, b, DEP_POS, inst))
    LLa = lane_lengths(net_file)
    for ln in (0, 1):
        A.append('    <laneAreaDetector id="q_app_%d" lane="app_%d" pos="0" endPos="%.2f" '
                 'period="30" file="%s"/>' % (ln, ln, LLa["app_%d" % ln] - 0.5, e2f))
    # the compiled `lock` lane length shrinks as the number of channels shrinks (netconvert
    # grows the diverge junction with the lateral spread), so endPos MUST come from the
    # compiled net, not a hard-coded constant.
    LL = lane_lengths(net_file)
    for b in range(booths):
        A.append('    <laneAreaDetector id="q_lock_%d" lane="lock_%d" pos="0" endPos="%.2f" '
                 'period="30" file="%s"/>' % (b, b, LL["lock_%d" % b] - 0.5, e2f))
    A.append('    <entryExitDetector id="e3_plaza" period="60" file="%s" timeThreshold="1" speedThreshold="1.39">' % e3f)
    for ln in (0, 1):
        A.append('        <detEntry lane="app_%d" pos="%.1f"/>' % (ln, ENTRY_POS))
    for b in range(booths):
        A.append('        <detExit lane="chout_%d_0" pos="%.1f"/>' % (b, DEP_POS))
    A.append("    </entryExitDetector>")
    if booth_speed_service:
        # mechanism (b): speed-based booth server (no <stop>)
        v = 30.0 / service_mean
        A.append('    <variableSpeedSign id="vss_booths" lanes="%s">'
                 % " ".join("booth_%d_0" % b for b in range(booths)))
        A.append('        <step time="0" speed="%.3f"/>' % v)
        A.append("    </variableSpeedSign>")
    A.append("</additional>")
    open(add, "w").write("\n".join(A) + "\n")

    # ---- sumocfg ----
    cfg = os.path.join(run_dir, "plaza.sumocfg")
    C = ['<?xml version="1.0" encoding="UTF-8"?>', "<configuration>",
         "    <input>",
         '        <net-file value="%s"/>' % os.path.abspath(net_file),
         '        <route-files value="%s"/>' % rou,
         '        <additional-files value="%s"/>' % add,
         "    </input>", "    <output>",
         '        <tripinfo-output value="%s"/>' % os.path.join(run_dir, "tripinfo.xml"),
         '        <summary-output value="%s"/>' % os.path.join(run_dir, "summary.xml"),
         '        <stop-output value="%s"/>' % os.path.join(run_dir, "stops.xml"),
         "    </output>", "    <time>",
         '        <begin value="0"/>',
         '        <end value="%.0f"/>' % (horizon + end_pad),
         '        <step-length value="%.2f"/>' % step_length,
         "    </time>", "    <processing>",
         '        <time-to-teleport value="600"/>',
         '        <max-depart-delay value="-1"/>',
         '        <lateral-resolution value="-1"/>',
         "    </processing>", "    <report>",
         '        <no-step-log value="true"/>',
         '        <duration-log.statistics value="true"/>',
         "    </report>", "</configuration>"]
    open(cfg, "w").write("\n".join(C) + "\n")

    meta = dict(n=n, booth_of=booth_of.tolist(), svc=svc.tolist(),
                is_etc=is_etc.tolist(), depart=times.tolist(),
                booths=booths, warmup=warmup, horizon=horizon,
                veh_rate=veh_rate, service_mean=service_mean, etc_mean=etc_mean)
    return cfg, meta


# --------------------------------------------------------------------------- #
# raw-output parsers
# --------------------------------------------------------------------------- #
def parse_stops(path):
    """stop-output -> list of dicts with vehicle id, booth index, started, ended, duration."""
    out = []
    for ev in ET.parse(path).getroot():
        lane = ev.get("lane") or ""
        if not lane.startswith("booth_"):
            continue
        b = int(lane.split("_")[1])
        st, en = float(ev.get("started")), float(ev.get("ended"))
        out.append(dict(veh=ev.get("id"), booth=b, started=st, ended=en, dur=en - st))
    return out


def parse_instant(path):
    """instant induction loop -> {det_id: [(time, vehID), ...]} using only 'enter' events."""
    d = {}
    for ev in ET.parse(path).getroot():
        if ev.get("state") != "enter":
            continue
        d.setdefault(ev.get("id"), []).append((float(ev.get("time")), ev.get("vehID")))
    for k in d:
        d[k].sort()
    return d


def parse_e2(path):
    """laneAreaDetector -> {det_id: [(begin, maxJamLengthInMeters, maxVehicleNumber), ...]}"""
    d = {}
    for iv in ET.parse(path).getroot():
        d.setdefault(iv.get("id"), []).append(
            (float(iv.get("begin")), float(iv.get("maxJamLengthInMeters")),
             float(iv.get("maxVehicleNumber") or 0)))
    return d


def parse_e3(path):
    rows = []
    for iv in ET.parse(path).getroot():
        rows.append(dict(begin=float(iv.get("begin")), end=float(iv.get("end")),
                         vehicleSum=float(iv.get("vehicleSum")),
                         vehicleSumWithin=float(iv.get("vehicleSumWithin")),
                         meanDurationWithin=float(iv.get("meanDurationWithin")),
                         meanTravelTime=float(iv.get("meanTravelTime")),
                         meanHaltsPerVehicle=float(iv.get("meanHaltsPerVehicle") or 0),
                         meanTimeLoss=float(iv.get("meanTimeLoss") or 0)))
    return rows


def parse_tripinfo(path):
    rows = []
    for t in ET.parse(path).getroot():
        if t.tag != "tripinfo":
            continue
        rows.append(dict(id=t.get("id"), depart=float(t.get("depart")),
                         arrival=float(t.get("arrival")), duration=float(t.get("duration")),
                         waitingTime=float(t.get("waitingTime")),
                         timeLoss=float(t.get("timeLoss")),
                         departDelay=float(t.get("departDelay")),
                         vType=t.get("vType")))
    return rows


def parse_summary_teleports(path):
    """summary output: `teleports` is a CUMULATIVE counter, so take the max, not a sum
    (see analyze-simulation-outputs). Transparently accepts a gzipped summary.xml.gz."""
    import gzip
    src = path if os.path.exists(path) else path + ".gz"
    op = gzip.open if src.endswith(".gz") else open
    with op(src, "rb") as f:
        last = 0
        for s in ET.parse(f).getroot():
            last = max(last, int(s.get("teleports")))
    return last


# --------------------------------------------------------------------------- #
# closed-form queueing formulas
# --------------------------------------------------------------------------- #
def erlang_c(c, a):
    """Erlang-C blocking-into-queue probability; a = lambda/mu (offered load in erlangs)."""
    if a >= c:
        return 1.0
    s = 0.0
    term = 1.0
    for k in range(c):
        if k > 0:
            term *= a / k
        s += term
    term_c = term * a / c                      # a^c/c!
    top = term_c * c / (c - a)
    return top / (s + top)


def mmc(c, lam, mu):
    """M/M/c. Returns (Wq, Lq) in (s, veh). lam, mu in veh/s."""
    a = lam / mu
    rho = a / c
    if rho >= 1:
        return float("inf"), float("inf")
    C = erlang_c(c, a)
    Wq = C / (c * mu - lam)
    return Wq, lam * Wq


def allen_cunneen(c, lam, mu, ca2, cs2):
    """Allen-Cunneen M/G/c approximation: Wq ~= Wq_MMc * (Ca^2 + Cs^2)/2."""
    Wq, _ = mmc(c, lam, mu)
    if Wq == float("inf"):
        return float("inf"), float("inf")
    W = Wq * (ca2 + cs2) / 2.0
    return W, lam * W


def mdc_cosmetatos(c, lam, mu):
    """
    M/D/c via the Cosmetatos approximation:
      Wq(M/D/c) = 0.5 * Wq(M/M/c) * [1 + f], f = (1-rho)(c-1)(sqrt(4+5c)-2)/(16 rho c)
    Exact for c=1 (Pollaczek-Khinchine: Wq_MD1 = 0.5 Wq_MM1).
    """
    Wq, _ = mmc(c, lam, mu)
    if Wq == float("inf"):
        return float("inf"), float("inf")
    rho = lam / (c * mu)
    f = (1 - rho) * (c - 1) * ((4 + 5 * c) ** 0.5 - 2) / (16.0 * rho * c)
    W = 0.5 * Wq * (1 + f)
    return W, lam * W


def c_mm1(c, lam, mu):
    """c INDEPENDENT M/M/1 queues fed by a Bernoulli(1/c) split of the Poisson stream."""
    li = lam / c
    if li >= mu:
        return float("inf"), float("inf")
    Wq = li / (mu * (mu - li))
    return Wq, lam * Wq


def c_mg1(c, lam, ES, cs2):
    """
    c INDEPENDENT M/G/1 queues fed by a Bernoulli(1/c) split of the Poisson stream,
    Pollaczek-Khinchine:  Wq = rho_i * E[S] * (1 + Cs^2) / (2 (1 - rho_i)).
    This is the model that actually matches a SUMO plaza with random booth choice, once
    E[S] is the EFFECTIVE service time (service + move-up headway floor) and Cs^2 is the
    measured squared CV of the saturated departure headway.
    """
    rho_i = (lam / c) * ES
    if rho_i >= 1:
        return float("inf"), float("inf")
    Wq = rho_i * ES * (1.0 + cs2) / (2.0 * (1.0 - rho_i))
    return Wq, lam * Wq


def mean_ci(x, alpha=0.05):
    x = np.asarray(x, dtype=float)
    n = len(x)
    m = float(np.mean(x))
    if n < 2:
        return m, 0.0
    from scipy import stats
    h = float(stats.t.ppf(1 - alpha / 2, n - 1) * np.std(x, ddof=1) / np.sqrt(n))
    return m, h
