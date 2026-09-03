"""
Downs-Thomson corridor: scenario builder + single-run simulator + raw-output parser.

One O-D corridor, two alternatives:
  ROAD    : feed -> r1 -> r2(bottleneck) -> r3 -> exit   (vClass passenger)
  TRANSIT : t1 -> t2 -> exit                             (bus-only right-of-way)

Mode choice is endogenous: an outer loop (dt_equilibrium.py) picks the car share p,
this module realises that share as concrete SUMO demand, applies the OPERATOR HEADWAY
RULE, runs SUMO and measures the generalized cost of each mode from raw output.

OPERATOR HEADWAY RULE (farebox-recovery / Mohring feedback)
-----------------------------------------------------------
    H = clamp( K / Q_transit , H_MIN , H_MAX )          [seconds]

    Q_transit = number of transit riders in the analysis period.
    Rationale: fare revenue is proportional to ridership and pays for vehicle-hours,
    so service frequency f = 1/H scales linearly with patronage.  Mean wait is H/2,
    so wait time FALLS as ridership rises -- the Mohring effect.  Reversing the
    causality (fewer riders -> longer headway -> longer wait -> even fewer riders)
    is the supply-side feedback that Downs-Thomson needs.

    Control condition ("feedback OFF"): H is frozen at H_FIXED regardless of Q.

COST DEFINITIONS (both door-to-door, from the traveller's intended departure)
----------------------------------------------------------------------------
    car     cost_i = tripinfo/@duration + tripinfo/@departDelay
                     (departDelay matters: when the bottleneck queue reaches the
                      insertion point SUMO holds vehicles back, and that waiting is
                      NOT inside @duration.  Ignoring it would hide the congestion.)
    transit cost_i = personinfo/@duration
                     = ride/@waitingTime + ride/@duration
                     (wait at the origin stop + in-vehicle time to the destination stop)

    Access/egress walking is deliberately omitted and assumed identical for both
    modes (travellers are placed directly at the origin bus stop).  This is a
    simplification -- see FINDINGS.md.
"""

import math
import os
import random
import subprocess
from xml.etree import ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(os.path.join(HERE, ".."))
NET_BASE = os.path.join(OUT, "net", "corridor_base.net.xml")
NET_EXPANDED = os.path.join(OUT, "net", "corridor_expanded.net.xml")

# ----------------------------------------------------------------------------- params
T_DEMAND = 1200.0          # seconds; travellers depart uniformly over [0, T_DEMAND)
SCHED_T0 = 60.0           # first scheduled bus departure from the origin stop
BUS_LEAD = 25.0           # bus is inserted this many s before its scheduled stop departure
BUS_IVT_SCHED = 185.0     # scheduled running time origin stop -> destination stop
SCHED_TAIL = 2.0          # keep dispatching buses for SCHED_TAIL * H past the demand window

# Operator headway rule parameters (calibrated in calib_curves.py so that BOTH road
# variants have an INTERIOR mode-choice equilibrium; neither clamp binds in that range).
K_BUDGET = 841500.0       # rider-seconds of service the farebox buys (rule numerator)
H_MIN = 60.0              # never run more often than every 60 s
H_MAX = 3600.0            # never run less often than hourly
H_FIXED = 374.0           # frozen headway used in the feedback-OFF control
                          # (= the headway the rule itself picks at the BASE equilibrium,
                          #  so the control is anchored at the same operating point)


def headway_rule(q_transit, feedback=True, K=K_BUDGET, h_min=H_MIN, h_max=H_MAX,
                 h_fixed=H_FIXED):
    """The operator headway rule.  Returns headway in seconds."""
    if not feedback:
        return float(h_fixed)
    if q_transit <= 0:
        return float(h_max)
    return float(min(h_max, max(h_min, K / float(q_transit))))


# ------------------------------------------------------------------ demand realisation
def draw_population(n_total, seed):
    """Common Random Numbers: fix each traveller's departure time and its mode-priority
    rank ONCE per (n_total, seed).  Changing p then only moves the mode boundary, it
    does not resample departure times -- so BASE vs EXPANDED and feedback ON vs OFF at
    the same seed face literally the same travellers."""
    rng = random.Random(seed * 100003 + n_total)
    dep = [rng.uniform(0.0, T_DEMAND) for _ in range(n_total)]
    prio = list(range(n_total))
    rng.shuffle(prio)          # prio[j] = rank of traveller j in the "becomes a car user" order
    return dep, prio


def build_run(run_dir, net, n_total, p_car, seed, feedback=True, **rule_kw):
    """Write stops.add.xml + demand.rou.xml for one simulation run.  Returns a dict of
    the realised supply/demand quantities (n_car, n_transit, headway, bus departures)."""
    os.makedirs(run_dir, exist_ok=True)
    dep, prio = draw_population(n_total, seed)
    n_car = int(round(p_car * n_total))
    n_car = max(0, min(n_total, n_car))
    n_tr = n_total - n_car
    is_car = [prio[j] < n_car for j in range(n_total)]

    H = headway_rule(n_tr, feedback=feedback, **rule_kw)

    with open(os.path.join(run_dir, "stops.add.xml"), "w") as f:
        f.write('<additional>\n'
                '  <busStop id="S_O" lane="t1_0" startPos="40" endPos="70" lines="L1" friendlyPos="true"/>\n'
                '  <busStop id="S_D" lane="t2_0" startPos="1370" endPos="1400" lines="L1" friendlyPos="true"/>\n'
                '</additional>\n')

    # --- scheduled bus departures from the origin stop
    bus_sched = []
    t = SCHED_T0
    horizon = T_DEMAND + SCHED_TAIL * H
    while t <= horizon:
        bus_sched.append(t)
        t += H
    if not bus_sched:
        bus_sched = [SCHED_T0]

    # --- assemble every loaded element with its insertion time, then SORT (SUMO
    #     silently DROPS elements that appear out of departure order).
    items = []
    for i, T in enumerate(bus_sched):
        d = max(0.0, T - BUS_LEAD)
        xml = (f'  <vehicle id="bus_{i}" type="bus" line="L1" route="BUSR" depart="{d:.2f}" departPos="0">\n'
               f'    <stop busStop="S_O" duration="1" until="{T:.2f}"/>\n'
               f'    <stop busStop="S_D" duration="1" until="{T + BUS_IVT_SCHED:.2f}"/>\n'
               f'  </vehicle>\n')
        items.append((d, xml))
    for j in range(n_total):
        d = dep[j]
        if is_car[j]:
            items.append((d, f'  <vehicle id="car_{j}" type="car" route="ROAD" depart="{d:.2f}"/>\n'))
        else:
            items.append((d, f'  <person id="pax_{j}" depart="{d:.2f}" departPos="55">\n'
                             f'    <ride from="t1" busStop="S_D" lines="L1"/>\n'
                             f'  </person>\n'))
    items.sort(key=lambda x: x[0])

    with open(os.path.join(run_dir, "demand.rou.xml"), "w") as f:
        f.write('<routes>\n')
        f.write('  <vType id="bus" vClass="bus" length="12" personCapacity="4000" '
                'boardingDuration="0.02" color="1,0.5,0"/>\n')
        f.write('  <vType id="car" vClass="passenger" color="0,0.6,1"/>\n')
        f.write('  <route id="ROAD" edges="feed r1 r2 r3 exit"/>\n')
        f.write('  <route id="BUSR" edges="t1 t2 exit"/>\n')
        for _, xml in items:
            f.write(xml)
        f.write('</routes>\n')

    return dict(n_car=n_car, n_transit=n_tr, headway=H, n_buses=len(bus_sched),
                bus_sched=bus_sched, net=net, seed=seed)


def expected_wait_from_schedule(bus_sched, t_demand=None):
    """EXACT expected wait implied by an emitted timetable for travellers arriving
    uniformly on [0, t_demand): E[W] = (1/T) * int_0^T (next_departure(t) - t) dt.

    This is the right verification target for the realised waiting time.  The textbook
    H/2 is only its infinite-horizon limit: with a finite demand window that is not an
    exact multiple of H, and a first departure at SCHED_T0 > 0, E[W] deviates from H/2
    by a schedule-phase term.  We report both."""
    T = t_demand if t_demand is not None else T_DEMAND
    s = sorted(bus_sched)
    total, t = 0.0, 0.0
    for dep in s:
        if dep <= t:
            continue
        hi = min(dep, T)
        if hi > t:                      # travellers in [t, hi) all catch this departure
            total += (dep - t) * (hi - t) - 0.5 * (hi - t) ** 2
            t = hi
        if t >= T:
            break
    if t < T:                           # no departure left: unserved tail
        return float("inf")
    return total / T


# ------------------------------------------------------------------------------ run
def run_sumo(run_dir, net, seed, sumo_bin="sumo"):
    cmd = [sumo_bin, "-n", net,
           "-a", os.path.join(run_dir, "stops.add.xml"),
           "-r", os.path.join(run_dir, "demand.rou.xml"),
           "--tripinfo-output", os.path.join(run_dir, "tripinfo.xml"),
           "--summary-output", os.path.join(run_dir, "summary.xml"),
           "--summary-output.period", "10",
           "--seed", str(seed),
           "--no-step-log", "true",
           "--time-to-teleport", "-1",     # keep the bottleneck queue physical
           "--end", "20000",
           "--no-warnings", "true"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"sumo failed in {run_dir}:\n{r.stderr[:2000]}")
    return r


# --------------------------------------------------------------------------- parsing
def parse_run(run_dir, expect_car, expect_transit):
    """Measure generalized cost per mode from RAW tripinfo/personinfo output."""
    root = ET.parse(os.path.join(run_dir, "tripinfo.xml")).getroot()
    car_costs, car_dur, car_delay = [], [], []
    bus_ids = set()
    for ti in root.findall("tripinfo"):
        if ti.get("vType") == "car":
            d = float(ti.get("duration")); dd = float(ti.get("departDelay"))
            car_costs.append(d + dd); car_dur.append(d); car_delay.append(dd)
        elif ti.get("vType") == "bus":
            bus_ids.add(ti.get("id"))

    tr_costs, tr_wait, tr_ivt = [], [], []
    n_no_ride = 0
    for pi in root.findall("personinfo"):
        rides = pi.findall("ride")
        if not rides:
            n_no_ride += 1
            continue
        r = rides[0]
        w = float(r.get("waitingTime")); iv = float(r.get("duration"))
        tr_wait.append(w); tr_ivt.append(iv); tr_costs.append(w + iv)

    def mean(x):
        return sum(x) / len(x) if x else float("nan")

    return dict(
        n_car_arrived=len(car_costs), n_transit_arrived=len(tr_costs),
        n_car_expected=expect_car, n_transit_expected=expect_transit,
        n_person_no_ride=n_no_ride, n_buses_run=len(bus_ids),
        car_cost=mean(car_costs), car_duration=mean(car_dur), car_departdelay=mean(car_delay),
        transit_cost=mean(tr_costs), transit_wait=mean(tr_wait), transit_ivt=mean(tr_ivt),
        car_costs=car_costs, transit_costs=tr_costs,
    )


def simulate(run_dir, net, n_total, p_car, seed, feedback=True, **rule_kw):
    info = build_run(run_dir, net, n_total, p_car, seed, feedback=feedback, **rule_kw)
    run_sumo(run_dir, net, seed)
    res = parse_run(run_dir, info["n_car"], info["n_transit"])
    res.update(headway=info["headway"], n_car=info["n_car"], n_transit=info["n_transit"],
               n_buses_sched=info["n_buses"], p_car=p_car, seed=seed, n_total=n_total,
               feedback=feedback, net=os.path.basename(net))
    # realised headway, measured from the emitted schedule (verification of the rule)
    s = info["bus_sched"]
    gaps = [s[i + 1] - s[i] for i in range(len(s) - 1)]
    res["headway_realised"] = gaps[0] if gaps else float("nan")
    res["headway_realised_max_dev"] = max(abs(g - info["headway"]) for g in gaps) if gaps else 0.0
    res["wait_expected_schedule"] = expected_wait_from_schedule(s)
    res["wait_h_over_2"] = info["headway"] / 2.0
    res["gap"] = res["car_cost"] - res["transit_cost"]
    tot = 0.0
    if res["car_costs"]:
        tot += sum(res["car_costs"])
    if res["transit_costs"]:
        tot += sum(res["transit_costs"])
    res["person_hours"] = tot / 3600.0
    return res
