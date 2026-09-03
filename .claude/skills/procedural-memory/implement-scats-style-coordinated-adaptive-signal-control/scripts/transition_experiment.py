#!/usr/bin/env python3
"""Sub-goal 3 (core contribution), part A: measure transition cost directly.

A controlled, isolated experiment: run the 5-junction system under a CONSTANT
demand level, holding Plan A (a short cycle, tuned for a lighter condition)
for 900 s, then at t=900 command a step change to Plan B (a longer cycle with
different progression offsets, tuned for the heavier condition this
experiment's constant demand actually represents) -- applied via each of the
four standard controller transition methods:

  dwell/hold   -- hold Plan A fixed for DWELL_CYCLES cycles, then jump the
                  ENTIRE remaining delta (cycle length + every junction's
                  offset) in one step.
  add-only     -- cycle length may only ever INCREASE, capped at
                  +MAX_STEP_C s/cycle; offset corrections only ever ADD
                  seconds to the subordinate (CROSS) stage (delaying the next
                  ART_MAIN onset), going the long way around if a shortening
                  correction would otherwise be shorter.
  subtract-only-- the mirror image (only ever decreases / only ever removes
                  seconds). Since THIS experiment's transition is an INCREASE
                  (A -> B, short cycle to long), subtract-only is structurally
                  the wrong tool and is expected to get stuck -- reported
                  honestly as the diagnostic the real controller taxonomy
                  predicts, not hidden.
  spread-N     -- the signed delta (cycle length and each junction's own
                  signed offset correction, shortest path) split into N equal
                  per-cycle increments.

Measures directly, per method:
  * excess delay  = mean per-vehicle timeLoss for trips departing in the
                    POST-SWITCH window, in EXCESS of the (separately measured)
                    Plan-B steady-state timeLoss (a run held on Plan B from
                    t=0, i.e. no transition at all -- the best-case ceiling).
  * lost %AoG     = drop in %arrival-on-green (from advance-detector arrivals
                    vs each cycle's realized green window, same measurement
                    as build-atspm-pipeline-and-retime-arterial) during the
                    transition window vs the Plan-B steady-state run.
  * cycles to re-establish coordination = first cycle, counting from the
                    switch, at which EVERY junction's realized C is within
                    2 s of C_B AND stays there for 3 consecutive cycles.
"""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CTRL = os.path.join(ROOT, "controller")
sys.path.insert(0, CTRL)
sys.path.insert(0, os.path.join(ROOT, "demand"))
sys.path.insert(0, os.path.join(ROOT, "det"))
SUMO_HOME = os.environ.get("SUMO_HOME") or \
    "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo"
os.environ.setdefault("SUMO_HOME", SUMO_HOME)
sys.path.append(os.path.join(SUMO_HOME, "tools"))
import traci  # noqa: E402
from controller_core import JunctionPlant  # noqa: E402
from live_detectors import E1EntryCounter  # noqa: E402

SUMO_BIN = os.path.join(os.path.dirname(os.path.dirname(SUMO_HOME.rstrip("/"))), "bin", "sumo")
NET = os.path.join(ROOT, "net", "arterial_static.net.xml")
DET = os.path.join(ROOT, "det", "detectors.add.xml")
N_INT = 5
PROG_SPEED = 13.89 * 0.9
SPACING = 400.0

PLAN_A = dict(C=70.0, art_main=32.0, art_left=8.0, cross=21.0)   # lighter-condition plan
PLAN_B = dict(C=110.0, art_main=58.0, art_left=8.0, cross=35.0)  # heavier-condition plan
T_SWITCH = 900.0
T_END = 2100.0

DWELL_CYCLES = 3
MAX_STEP_C = 6.0
MAX_STEP_OFF = 6.0


def progression_offsets(C):
    return [((i * SPACING) / PROG_SPEED) % C for i in range(N_INT)]


def write_const_demand(path, seed, rate_eb=800.0, rate_wb=1650.0, cross_rate=220.0, end=T_END + 300.0):
    # rate_wb=1550 veh/h is chosen to EXCEED Plan A's WB through capacity
    # ((32/70)*1604*2 = 1466 veh/h -> DoS~1.06, genuinely oversaturated) while
    # sitting comfortably under Plan B's ((58/110)*1604*2 = 1694 veh/h ->
    # DoS~0.92) -- so the A->B transition tested here is one the network
    # actually NEEDS, and "excess delay vs the Plan-B ceiling" is a meaningful
    # measure of transition cost rather than an artifact of a mismatched plan.
    import random
    rng = random.Random(seed)
    trips = []

    def draw(prefix, fr, to, rate):
        if rate <= 0:
            return
        lam = rate / 3600.0
        t = rng.expovariate(lam)
        k = 0
        while t < end:
            trips.append((t, "%s.%d" % (prefix, k), fr, to))
            k += 1
            t += rng.expovariate(lam)

    draw("thruE", "WtoJ0", "J4toE", rate_eb)
    draw("thruW", "EtoJ4", "J0toW", rate_wb)
    for i in range(N_INT):
        j = "J%d" % i
        up = "W" if i == 0 else "J%d" % (i - 1)
        dn = "E" if i == N_INT - 1 else "J%d" % (i + 1)
        draw("crossR.%d" % i, "S%dtoJ%d" % (i, i), "%sto%s" % (j, dn), cross_rate * 0.5)
        draw("crossL.%d" % i, "S%dtoJ%d" % (i, i), "%sto%s" % (j, up), cross_rate * 0.5)
    trips.sort()
    with open(path, "w") as f:
        f.write('<routes>\n  <vType id="car" accel="2.6" decel="4.5" sigma="0.5" length="4.8" '
                'minGap="2.5" maxSpeed="16.7" speedDev="0.1" tau="1.2" carFollowModel="Krauss"/>\n')
        for t, vid, fr, to in trips:
            f.write('  <trip id="%s" type="car" depart="%.2f" from="%s" to="%s" '
                    'departLane="best" departSpeed="max"/>\n' % (vid, t, fr, to))
        f.write('</routes>\n')
    return path


def run(method, seed, workdir, plan_a=PLAN_A, plan_b=PLAN_B, no_switch_plan=None):
    """no_switch_plan: if set, run this single plan for the WHOLE horizon (no
    transition at all) -- used to build the Plan-A / Plan-B steady-state
    references."""
    os.makedirs(workdir, exist_ok=True)
    trips_path = os.path.join(workdir, "trips.rou.xml")
    write_const_demand(trips_path, seed)
    tripinfo = os.path.join(workdir, "tripinfo.xml")
    cmd = [SUMO_BIN, "-n", NET, "-r", trips_path, "-a", DET,
           "--no-step-log", "true", "--time-to-teleport", "300",
           "--tripinfo-output", tripinfo, "--end", str(int(T_END)),
           "--seed", str(seed)]
    traci.start(cmd)
    plants = {}
    adv_ids = {}
    for i in range(N_INT):
        j = "J%d" % i
        for d in ("EB", "WB"):
            adv_ids[(j, d)] = ["ADV_%s_%s_%d" % (j, d, li) for li in (0, 1)]
    counter = E1EntryCounter([a for ids in adv_ids.values() for a in ids])
    arrivals = []   # (t, junction, dir) every new entry, for %AoG
    try:
        start_plan = no_switch_plan or plan_a
        offs0 = progression_offsets(start_plan["C"])
        for i in range(N_INT):
            j = "J%d" % i
            p = JunctionPlant(j, min_green=8.0)
            p.set_plan(art_main=start_plan["art_main"], art_left=start_plan["art_left"],
                      cross=start_plan["cross"])
            p.start(0.0, warm_start_elapsed=offs0[i])
            plants[j] = p

        cur_C = {j: start_plan["C"] for j in plants}
        cur_off_state = {j: 0.0 for j in plants}   # cumulative applied offset delta so far
        target_off_delta = {j: (progression_offsets(plan_b["C"])[i] - offs0[i]) if no_switch_plan is None else 0.0
                            for i, j in enumerate(plants)}
        remaining_C = {j: (plan_b["C"] - start_plan["C"]) if no_switch_plan is None else 0.0 for j in plants}
        remaining_off = dict(target_off_delta)
        spread_left = {j: None for j in plants}
        dwell_left = {j: DWELL_CYCLES for j in plants}
        switched = {j: (no_switch_plan is not None) for j in plants}
        last_cyc = {j: 0 for j in plants}

        t = 0.0
        while t < T_END:
            traci.simulationStep()
            t = traci.simulation.getTime()
            counter.step()
            for j in plants:
                for d in ("EB", "WB"):
                    for aid in adv_ids[(j, d)]:
                        n = counter.pop(aid)
                        for _ in range(n):
                            arrivals.append((t, j, d))
            for j, p in plants.items():
                p.step(t)
                if p.n_cycles_completed > last_cyc[j]:
                    last_cyc[j] = p.n_cycles_completed
                    if t >= T_SWITCH and no_switch_plan is None:
                        if not switched[j] and remaining_C[j] == 0 and remaining_off[j] == 0:
                            switched[j] = True
                        _apply_step(method, p, j, cur_C, remaining_C, remaining_off,
                                   dwell_left, plan_b, MAX_STEP_C, MAX_STEP_OFF)
        cycles = {j: list(plants[j].cycle_log) for j in plants}
    finally:
        traci.close()
    return dict(tripinfo=tripinfo, cycles=cycles, arrivals=arrivals, adv_ids=adv_ids)


def _apply_step(method, plant, j, cur_C, remaining_C, remaining_off, dwell_left, plan_b,
                max_step_c, max_step_off):
    rc = remaining_C[j]
    ro = remaining_off[j]
    if abs(rc) < 1e-6 and abs(ro) < 1e-6:
        return  # already converged
    if method == "dwell":
        if dwell_left[j] > 0:
            dwell_left[j] -= 1
            return
        step_c, step_o = rc, ro
    elif method == "add":
        step_c = min(max_step_c, rc) if rc > 0 else 0.0
        step_o = min(max_step_off, ro) if ro > 0 else max(-max_step_off, ro) if ro < 0 else 0.0
        # add-only for offset: if a shortening is needed, go the long way (add C_target instead)
        if ro < 0:
            step_o = min(max_step_off, ro + plan_b["C"]) if (ro + plan_b["C"]) > 0 else ro
    elif method == "subtract":
        step_c = max(-max_step_c, rc) if rc < 0 else 0.0
        step_o = max(-max_step_off, ro) if ro < 0 else 0.0
        if ro > 0:
            step_o = max(-max_step_off, ro - plan_b["C"])
    elif method == "spread":
        n_left = max(1, round(max(abs(rc) / max_step_c, abs(ro) / max_step_off, 1)))
        step_c = rc / n_left
        step_o = ro / n_left
    else:
        raise ValueError(method)
    new_C = cur_C[j] + step_c
    cur_C[j] = new_C
    remaining_C[j] = rc - step_c
    remaining_off[j] = ro - step_o
    avail = new_C - plant.fixed_cycle_overhead() - plan_b["art_left"]
    ratio_art = plan_b["art_main"] / (plan_b["art_main"] + plan_b["cross"])
    g_art = max(10.0, avail * ratio_art)
    g_cross = avail - g_art
    plant.set_plan(art_main=g_art, art_left=plan_b["art_left"], cross=g_cross)
    if abs(step_o) > 1e-6:
        plant.apply_one_shot_stage_correction("CROSS", step_o)


if __name__ == "__main__":
    print("see run_all.py")
