#!/usr/bin/env python3
"""
Parsers for SUMO outputs + an independent implementation of the HCM 6th Ed.
Chapter 19 (Signalized Intersections) motorized-vehicle delay/LOS model and the
HCM back-of-queue estimate.

Nothing here consumes a SUMO or third-party "HCM" helper - every formula is
written out from the published HCM formulation so it can be checked line by
line against the textbook.
"""
import math, os
import xml.etree.ElementTree as ET

# ---------------------------------------------------------------- parsers ---

def parse_instant(path):
    """[(detID, time, state, vehID)] from an instantInductionLoop file."""
    out = []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "instantOut":
            out.append((el.get("id"), float(el.get("time")), el.get("state"), el.get("vehID")))
            el.clear()
    return out


def parse_tripinfo(path):
    out = []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "tripinfo":
            out.append(dict(id=el.get("id"), depart=float(el.get("depart")),
                            arrival=float(el.get("arrival")),
                            duration=float(el.get("duration")),
                            routeLength=float(el.get("routeLength")),
                            waitingTime=float(el.get("waitingTime")),
                            timeLoss=float(el.get("timeLoss")),
                            departDelay=float(el.get("departDelay"))))
            el.clear()
    return out


def parse_e2(path):
    """{detID: [(begin, end, maxJamVeh, maxJamM)]}"""
    out = {}
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "interval":
            out.setdefault(el.get("id"), []).append(
                (float(el.get("begin")), float(el.get("end")),
                 int(el.get("maxJamLengthInVehicles")),
                 float(el.get("maxJamLengthInMeters"))))
            el.clear()
    return out


def parse_tls_switch(path):
    """[(time, phase_index, phase_name, state)] in chronological order."""
    out = []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "tlsState":
            out.append((float(el.get("time")), int(el.get("phase")),
                        el.get("name") or "", el.get("state")))
            el.clear()
    return out


def parse_summary_tail(path):
    """Last <step>: teleports (cumulative), collisions, running, inserted, loaded."""
    last = None
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "step":
            last = {k: el.get(k) for k in ("time", "loaded", "inserted", "running",
                                           "ended", "teleports", "collisions")}
            el.clear()
    return last


def phase_intervals(switches, names):
    """[(name, start, end)] for the phases whose name is in `names`."""
    out = []
    for i, (t, ph, nm, st) in enumerate(switches):
        if nm in names:
            end = switches[i + 1][0] if i + 1 < len(switches) else None
            if end is not None:
                out.append((nm, t, end))
    return out


# ----------------------------------------------------- HCM Chapter 19 model --

# HCM incremental-delay calibration term k_min as a function of the actuated
# controller's unit extension (HCM 2000 Exhibit 16-13 / HCM 6th Ed Ch.19).
K_MIN_BY_UNIT_EXTENSION = {2.0: 0.04, 2.5: 0.08, 3.0: 0.11, 3.5: 0.13,
                           4.0: 0.15, 4.5: 0.19, 5.0: 0.23}

LOS_THRESHOLDS = [(10.0, "A"), (20.0, "B"), (35.0, "C"),
                  (55.0, "D"), (80.0, "E"), (math.inf, "F")]


def k_factor(control, X, unit_extension=3.0):
    """HCM incremental-delay factor k.  0.5 for pretimed; for actuated it is
    interpolated between k_min and 0.5 over 0.5 <= X <= 1.0."""
    if control == "pretimed":
        return 0.5
    kmin = K_MIN_BY_UNIT_EXTENSION.get(round(unit_extension, 1), 0.11)
    k = (1.0 - 2.0 * kmin) * (X - 0.5) + kmin
    return min(0.5, max(kmin, k))


def uniform_delay(C, g, X):
    """HCM Eq. 19-18  d1 = 0.5*C*(1-g/C)^2 / (1 - min(1,X)*g/C)"""
    lam = g / C
    return 0.5 * C * (1.0 - lam) ** 2 / (1.0 - min(1.0, X) * lam)


def incremental_delay(X, c, T, k, I=1.0):
    """HCM Eq. 19-26  d2 = 900*T*[(X-1) + sqrt((X-1)^2 + 8*k*I*X/(c*T))]"""
    return 900.0 * T * ((X - 1.0) + math.sqrt((X - 1.0) ** 2 + 8.0 * k * I * X / (c * T)))


def initial_queue_delay(Qb, c, T, X):
    """HCM initial-queue delay d3 (HCM 2000 Eq. 16-12 / HCM 6th Ed Ch.19
    'initial queue delay'):
        t = duration of unmet demand inside T (h)
        u = delay parameter
        d3 = 1800*Qb*(1+u)*t / (c*T)
    """
    if Qb <= 0 or c <= 0:
        return 0.0
    if X < 1.0:
        t = min(T, Qb / (c * (1.0 - X)))
    else:
        t = T
    u = 0.0 if t < T else max(0.0, 1.0 - (c * T / Qb) * (1.0 - min(1.0, X)))
    return 1800.0 * Qb * (1.0 + u) * t / (c * T)


def progression_factor(P, g, C, fPA=1.0):
    """HCM Eq. 19-... PF = (1-P)*fPA/(1-g/C).  P = proportion arriving on green.
    For an isolated intersection with random arrivals P == g/C and PF == 1."""
    lam = g / C
    if lam >= 1.0:
        return 1.0
    return (1.0 - P) * fPA / (1.0 - lam)


def los_letter(d, X=None, los_f_on_oversat=True):
    if los_f_on_oversat and X is not None and X > 1.0:
        return "F"
    for thr, letter in LOS_THRESHOLDS:
        if d <= thr:
            return letter
    return "F"


def back_of_queue(v, c, N, C, g, T, control, PF2=1.0, kB=None):
    """HCM back-of-queue (HCM 2000 Ch.16 App. G / HCM 6th Ed Ch.31), per lane.

    Q1 = PF2 * vL*C*(1-g/C) / (3600*(1-min(1,X)*g/C))
    Q2 = 0.25*cL*T*[(X-1) + sqrt((X-1)^2 + 8*kB*X/(cL*T))]
    Q  = Q1 + Q2                                (average back of queue, veh/ln)

    The HCM's 95th-percentile back-of-queue factor f_B95 is a tabulated
    function of Q that is NOT reproduced here; instead the standard Poisson
    approximation Q95 = Q + 1.65*sqrt(Q) is used and reported as such.
    """
    if kB is None:
        kB = 0.12 if control == "pretimed" else 0.10
    lam = g / C
    vL = v / N
    cL = c / N
    X = v / c if c > 0 else float("inf")
    Q1 = PF2 * vL * C * (1.0 - lam) / (3600.0 * (1.0 - min(1.0, X) * lam))
    Q2 = 0.25 * cL * T * ((X - 1.0) + math.sqrt((X - 1.0) ** 2 + 8.0 * kB * X / (cL * T)))
    Q = Q1 + Q2
    return dict(Q1=Q1, Q2=Q2, Q=Q, Q95=Q + 1.65 * math.sqrt(max(Q, 0.0)))


def lane_group(v, s_per_lane, N, g, C, T, control, Qb=0.0, PF=1.0, I=1.0,
               unit_extension=3.0, label=""):
    """Full HCM Chapter 19 lane-group result."""
    c = N * s_per_lane * g / C
    X = v / c if c > 0 else float("inf")
    k = k_factor(control, X, unit_extension)
    d1 = uniform_delay(C, g, X)
    d2 = incremental_delay(X, c, T, k, I)
    d3 = initial_queue_delay(Qb, c, T, X)
    d = d1 * PF + d2 + d3
    q = back_of_queue(v, c, N, C, g, T, control)
    return dict(label=label, v=v, s=s_per_lane, N=N, g=g, C=C, T=T, c=c, X=X,
                k=k, d1=d1, d2=d2, d3=d3, PF=PF, delay=d, los=los_letter(d, X),
                **{("Q_" + kk): vv for kk, vv in q.items()})


def intersection_aggregate(groups):
    """Volume-weighted intersection control delay and LOS (HCM Eq. 19-... )."""
    V = sum(g["v"] for g in groups)
    if V <= 0:
        return dict(delay=0.0, los="A", V=0.0)
    d = sum(g["v"] * g["delay"] for g in groups) / V
    return dict(delay=d, los=los_letter(d), V=V)


def percentile(xs, p):
    if not xs:
        return float("nan")
    xs = sorted(xs)
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * p
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)
