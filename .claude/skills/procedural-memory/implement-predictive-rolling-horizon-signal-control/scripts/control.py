#!/usr/bin/env python3
"""
Predictive rolling-horizon signal control: the arrival-prediction module and
the two controllers, plus the myopic/passive reference controllers.

Structure (deliberately separable, so the prediction model and the optimiser
can be swapped independently):

    Predictor            abstract: profile(now, H, dt) -> {group: [veh per bin]}
      DetectorPredictor  upstream E1 actuations + travel time + historical tail
      OraclePredictor    perfect knowledge of every vehicle on the approach
    JunctionController   GREEN/YELLOW/ALLRED state machine, min green, clearance,
                         via-lane emptiness -- lifted from
                         `implement-maxpressure-traci-controller`
      MaxPressureCtl     myopic state feedback (baseline arm)
      PassiveCtl         observe-only (fixed-time / native actuated arms)
      DPCtl              Controller A: forward DP over a finite horizon against
                         a predicted arrival profile (OPAC / ALLONS-D class)
      RolloutCtl         Controller B: simulation-rollout MPC on a shadow SUMO
                         instance driven by saveState/loadState
"""
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import SUMO_HOME, is_green, has_yellow, is_allred  # noqa: E402

sys.path.append(os.path.join(SUMO_HOME, "tools"))

HOLD = 100000.0
ALLRED_CAP = 12.0
VEH_SPACE = 7.5          # m per queued vehicle (length + min gap)
V_FREE = 13.89

# Deceleration + re-acceleration lost time for one vehicle forced to stop,
# from the demand's own vType (accel 2.6, decel 4.5, maxSpeed 13.89):
#   v/(2a) + v/(2b) = 13.89/5.2 + 13.89/9.0 = 2.67 + 1.54 s
STOP_PENALTY = V_FREE / (2 * 2.6) + V_FREE / (2 * 4.5)     # 4.21 s
TERMINAL_T = 30.0        # fixed reference time for the terminal queue cost, so
                         # that changing H changes the LOOKAHEAD DEPTH and not
                         # the shape of the objective


# =========================================================== predictors ======
class Predictor:
    def update(self, now):
        pass

    def profile(self, now, H, dt):
        raise NotImplementedError

    def queues(self, now):
        raise NotImplementedError


class DetectorPredictor(Predictor):
    """Per-movement predicted arrival profile from upstream E1 actuations.

    An actuation at t_det on a lane of group m is projected forward to the
    stop line with the measured travel time (setback / EWMA detector speed),
    shortened by the current standing queue so a detection lands at the BACK
    of the queue rather than at the stop bar.  The part of the horizon beyond
    the detectors' reach (lead time > D / v) is filled from a historical-mean
    (Poisson) tail rate estimated by an exponentially-weighted moving average
    of the detector count rate.
    """

    def __init__(self, conn, pm, det_map, setback, tail_window=300.0, vmin=2.0,
                 tail_mode="hist", use_events=True, scale=1.0, shuffle=False,
                 rng_seed=0):
        self.c = conn
        self.pm = pm
        self.det_map = det_map                     # laneID -> detID
        self.D = setback
        self.vmin = vmin
        self.tail_window = tail_window
        self.tail_mode = tail_mode
        self.use_events = use_events   # False -> historical mean rate only, the
                                       # ablation that isolates the value of
                                       # knowing WHEN individual vehicles arrive
        # level-sensitivity controls: `scale` multiplies the whole profile
        # (adds NO information, changes only its level); `shuffle` permutes the
        # bins (destroys all timing information, preserves the horizon total).
        self.scale = scale
        self.shuffle = shuffle
        self._rng = __import__("random").Random(12345 + rng_seed)
        self.group_dets = {}
        for g in pm.groups:
            self.group_dets[g] = [det_map[l] for l in pm.group_in_lanes[g] if l in det_map]
        self.pending = {g: [] for g in pm.groups}   # list of predicted arrival times
        self.det_times = {}                          # vid -> detection time (diagnostics)
        self.seen = set()
        self.vspeed = {g: V_FREE for g in pm.groups}
        self.rate = {g: 0.0 for g in pm.groups}     # veh/s EWMA
        self.count = {g: 0 for g in pm.groups}
        self.hist = {g: 0.0 for g in pm.groups}
        self._t0 = None
        self.log_pred = []                          # (issue_time, group, bin_idx, pred)

    def update(self, now):
        if self._t0 is None:
            self._t0 = now
        alpha = 0.02
        for g, dets in self.group_dets.items():
            newn = 0
            sp = []
            for d in dets:
                for rec in self.c.inductionloop.getVehicleData(d):
                    vid, _, entry, leave = rec[0], rec[1], rec[2], rec[3]
                    key = (d, vid, round(entry, 1))
                    if entry >= 0 and key not in self.seen:
                        self.seen.add(key)
                        newn += 1
                        te = entry if entry > 0 else now
                        self.pending[g].append(te)
                        self.det_times.setdefault(vid, te)
                v = self.c.inductionloop.getLastStepMeanSpeed(d)
                if v > 0:
                    sp.append(v)
            if sp:
                self.vspeed[g] = (1 - 0.05) * self.vspeed[g] + 0.05 * max(self.vmin, sum(sp) / len(sp))
            self.count[g] += newn
            inst = newn / max(1e-9, self.dt)
            self.rate[g] = (1 - alpha) * self.rate[g] + alpha * inst
            self.hist[g] = self.count[g] / max(1.0, now - self._t0)

    def set_dt(self, dt):
        self.dt = dt

    def queues(self, now):
        q = {}
        for g in self.pm.groups:
            q[g] = sum(self.c.lane.getLastStepHaltingNumber(l) for l in self.pm.group_in_lanes[g])
        return q

    def profile(self, now, H, dt, q0=None):
        nb = int(round(H / dt))
        out = {}
        q0 = q0 or self.queues(now)
        for g in self.pm.groups:
            nl = max(1, self.pm.n_lanes(g))
            qlen = (q0[g] / nl) * VEH_SPACE
            v = max(self.vmin, self.vspeed[g])
            tt = max(0.0, (self.D - qlen)) / v          # detector -> back of queue
            if not self.use_events:
                out[g] = [self.hist[g] * dt] * nb
                self.pending[g] = []
                continue
            bins = [0.0] * nb
            keep = []
            for t_det in self.pending[g]:
                t_arr = t_det + tt
                if t_arr < now - 1.0:
                    continue                             # already joined the queue
                keep.append(t_det)
                k = int((t_arr - now) / dt)
                if 0 <= k < nb:
                    bins[k] += 1.0
            self.pending[g] = keep
            # historical-mean tail beyond the detectors' ACTUAL reach.  The
            # cut-off is tt = (D - queue)/v, not D/v: once a queue stands
            # between the loop and the stop line, a detection lands at the back
            # of the queue sooner, so the last instant covered by real
            # detections moves CLOSER, and using D/v leaves a widening band of
            # the horizon covered by neither detections nor the tail model.
            reach = tt
            for k in range(nb):
                lead0 = k * dt
                lead1 = (k + 1) * dt
                if lead1 <= reach:
                    continue
                frac = min(1.0, (lead1 - max(lead0, reach)) / dt)
                tail = self.hist[g] if self.tail_mode == "hist" else self.rate[g]
                bins[k] += tail * dt * frac
            out[g] = bins
        if self.shuffle:
            for g in out:
                self._rng.shuffle(out[g])
        if self.scale != 1.0:
            for g in out:
                out[g] = [x * self.scale for x in out[g]]
        return out


class FreeFlowProjPredictor(Predictor):
    """State-perfect, dynamics-approximate reference.

    It reads the simulator's TRUE vehicle set (every vehicle on an approach
    lane, plus every not-yet-departed vehicle from the route file's departure
    schedule) and projects each one forward kinematically.  Attempt 1 called
    this arm `dp_oracle`; it is NOT an oracle -- the *state* is perfect but the
    *dynamics* are a free-flow projection, so it carries a real forecast error,
    measured in the prediction study alongside the detector predictors.

    Three biases present in attempt 1 are removed here:
      * the `max(speed, 2.0)` floor, which capped the projected travel time of
        a slow-moving vehicle and pulled its arrival forward;
      * the `sched[i] < now - 1.0` pointer, which left the previous second of
        the departure schedule eligible to be re-binned into bin 0 on the next
        call (a double count at the head of the horizon);
      * the flat `approach_len / V_FREE` run-up, which ignored the standing
        queue that a not-yet-departed vehicle will actually meet.
    """

    def __init__(self, conn, pm, schedule=None, approach_len=400.0,
                 legacy_bias=False):
        self.c = conn
        self.pm = pm
        self.schedule = schedule or {}      # group -> sorted times of entering the approach
        # per-group approach length; a scalar is accepted for backwards
        # compatibility but a corridor's two junctions do NOT share one
        self.approach_len = (approach_len if isinstance(approach_len, dict)
                             else {g: approach_len for g in pm.groups})
        self.legacy_bias = legacy_bias      # reproduce attempt 1 for the ablation
        self._ptr = {g: 0 for g in pm.groups}

    def set_dt(self, dt):
        self.dt = dt

    def queues(self, now):
        return {g: sum(self.c.lane.getLastStepHaltingNumber(l)
                       for l in self.pm.group_in_lanes[g]) for g in self.pm.groups}

    def profile(self, now, H, dt, q0=None):
        nb = int(round(H / dt))
        out = {}
        q0 = q0 or self.queues(now)
        for g in self.pm.groups:
            bins = [0.0] * nb
            nl = max(1, self.pm.n_lanes(g))
            qlen = (q0[g] / nl) * VEH_SPACE
            for lid in self.pm.group_in_lanes[g]:
                L = self.pm.lane_len[lid]
                for vid in self.c.lane.getLastStepVehicleIDs(lid):
                    sp = self.c.vehicle.getSpeed(vid)
                    if sp < 0.1:
                        continue                       # already counted in q0
                    pos = self.c.vehicle.getLanePosition(vid)
                    dist = (L - pos) - qlen
                    if dist <= 0.0:
                        continue          # already inside the queue -> counted in q0
                    v = max(sp, 2.0) if self.legacy_bias else max(sp, 0.5)
                    k = int((dist / v) / dt)
                    if 0 <= k < nb:
                        bins[k] += 1.0
            # not-yet-departed vehicles from the true schedule
            sched = self.schedule.get(g, [])
            i = self._ptr[g]
            cut = (now - 1.0) if self.legacy_bias else now
            while i < len(sched) and sched[i] < cut:
                i += 1
            self._ptr[g] = i
            j = i
            AL = self.approach_len.get(g, 400.0)
            runup = AL / V_FREE
            if not self.legacy_bias:
                runup = max(0.0, AL - qlen) / V_FREE
            while j < len(sched) and sched[j] <= now + H:
                t_arr = sched[j] + runup
                k = int((t_arr - now) / dt)
                if 0 <= k < nb:
                    bins[k] += 1.0
                j += 1
            out[g] = bins
        return out


OraclePredictor = FreeFlowProjPredictor      # backwards-compatible alias


# ================================================== junction state machine ===
class JunctionController:
    """GREEN -> YELLOW -> ALLRED -> GREEN, with min green, programmed clearance
    durations and a physical internal-lane emptiness check before opening a
    conflicting phase (the collision defect documented in
    `implement-maxpressure-traci-controller`)."""

    def __init__(self, conn, pm, min_green=8.0, log=None, max_green=1e9):
        self.c = conn
        self.pm = pm
        self.tls = pm.tls_id
        self.min_green = min_green
        self.max_green = max_green
        self.log = log
        self.mode = "GREEN"
        self.cur_green = pm.green_phases[0]
        self.target_green = self.cur_green
        self.vacating = self.cur_green
        self.green_since = 0.0
        self.yellow_until = 0.0
        self.allred_min_until = 0.0
        self.allred_cap_until = 0.0
        self.solve_ms = []       # optimiser work only
        self.sense_ms = []       # TraCI state-reading work only
        self.n_decisions = 0
        self.n_maxgreen_forced = 0

    def start(self, now):
        self.c.trafficlight.setPhase(self.tls, self.cur_green)
        self.c.trafficlight.setPhaseDuration(self.tls, HOLD)
        self.green_since = now
        self._log(now, -1, self.cur_green)

    def _log(self, now, fr, to):
        if self.log is not None:
            self.log.write(f"{now:.2f},{self.tls},{fr},{to}\n")

    def choose_target(self, now):
        return None

    def step(self, now):
        pm = self.pm
        if self.mode == "YELLOW":
            if now >= self.yellow_until - 1e-9:
                _, ar = pm.clearance[self.vacating]
                if ar is not None:
                    self.c.trafficlight.setPhase(self.tls, ar)
                    self.c.trafficlight.setPhaseDuration(self.tls, HOLD)
                    self._log(now, pm.clearance[self.vacating][0], ar)
                    self.mode = "ALLRED"
                    self.allred_min_until = now + pm.phases[ar][1]
                    self.allred_cap_until = now + ALLRED_CAP
                else:
                    self._commit(now)
            return
        if self.mode == "ALLRED":
            past_min = now >= self.allred_min_until - 1e-9
            past_cap = now >= self.allred_cap_until
            via = pm.phase_via_lanes.get(self.vacating, [])
            clear = all(self.c.lane.getLastStepVehicleNumber(l) == 0 for l in via)
            if past_cap or (past_min and clear):
                self._commit(now)
            return
        # GREEN
        if now - self.green_since < self.min_green - 1e-9:
            return
        # max green is a HARD constraint of the actuation layer, not just of the
        # optimiser's internal model -- attempt 1 enforced it only inside the DP
        # and inside RolloutCtl, so a DPCtl green that the DP never chose to end
        # could run unbounded.
        if now - self.green_since >= self.max_green - 1e-9:
            tgt = self.pm.ring[(self.pm.ring_pos[self.cur_green] + 1) % len(self.pm.ring)]
            self.n_maxgreen_forced += 1
        else:
            tgt = self.choose_target(now)
        if tgt is None or tgt == self.cur_green:
            return
        y, _ = pm.clearance[self.cur_green]
        self.vacating = self.cur_green
        self.target_green = tgt
        if y is None:
            self._commit(now)
            return
        self.c.trafficlight.setPhase(self.tls, y)
        self.c.trafficlight.setPhaseDuration(self.tls, HOLD)
        self._log(now, self.cur_green, y)
        self.mode = "YELLOW"
        self.yellow_until = now + pm.phases[y][1]

    def _commit(self, now):
        prev = self.c.trafficlight.getPhase(self.tls)
        self.c.trafficlight.setPhase(self.tls, self.target_green)
        self.c.trafficlight.setPhaseDuration(self.tls, HOLD)
        self._log(now, prev, self.target_green)
        self.cur_green = self.target_green
        self.mode = "GREEN"
        self.green_since = now


class PassiveCtl(JunctionController):
    """Observe-only: SUMO's own tlLogic (fixed-time or native actuated) drives
    the signal; this just records phase transitions for the switch-log audit."""

    def __init__(self, conn, pm, log=None):
        self.c = conn
        self.pm = pm
        self.tls = pm.tls_id
        self.log = log
        self.last = None
        self.solve_ms = []
        self.sense_ms = []
        self.n_decisions = 0
        self.n_maxgreen_forced = 0

    def start(self, now):
        self.last = self.c.trafficlight.getPhase(self.tls)
        self._log(now, -1, self.last)

    def step(self, now):
        p = self.c.trafficlight.getPhase(self.tls)
        if p != self.last:
            self._log(now, self.last, p)
            self.last = p


class MaxPressureCtl(JunctionController):
    def __init__(self, conn, pm, min_green=8.0, decision_interval=5.0, log=None,
                 max_green=50.0):
        super().__init__(conn, pm, min_green, log, max_green=max_green)
        self.di = decision_interval
        self.last_dec = -1e9

    def choose_target(self, now):
        if now - self.last_dec < self.di:
            return None
        self.last_dec = now
        t0 = time.perf_counter()
        pr = {}
        for gi in self.pm.green_phases:
            up = sum(self.c.lane.getLastStepHaltingNumber(l)
                     for l in self.pm.phase_in_lanes[gi])
            down = 0
            for g in self.pm.phase_groups[gi]:
                down += sum(self.c.lane.getLastStepHaltingNumber(l)
                            for l in self.pm.group_out_lanes[g])
            pr[gi] = up - down
        t1 = time.perf_counter()
        self.sense_ms.append((t1 - t0) * 1000.0)
        self.solve_ms.append(0.0)      # the argmax below is the whole optimiser
        self.n_decisions += 1
        best = max(pr, key=lambda g: pr[g])
        if best == self.cur_green or pr[best] <= pr[self.cur_green]:
            return None
        return best


# ==================================== Controller A: rolling-horizon DP =======
class DPCtl(JunctionController):
    """OPAC / ALLONS-D style forward dynamic program.

    stages   : discrete steps of `stage` seconds out to horizon H
    state    : (ring position of current green, elapsed green in stages)
               with the queue vector carried along the best path to that state
    decision : HOLD or SWITCH (to the next ring phase)
    cost     : trapezoidal vertical-queue delay in veh-seconds, PLUS a
               per-vehicle stop penalty for every predicted arrival that the
               plan forces to stop rather than pass on green
    hard constraints : min green, max green, fixed yellow + all-red as stages in
               which nothing discharges
    Only the first `head` seconds of the optimal plan are implemented before
    re-solving (true rolling horizon).

    Attempt-1 model errors corrected here (both diagnosed by the critic):
      * `_advance` had no free-flow-through term -- every predicted arrival was
        booked into the queue, whether or not the green in force could pass it
        without a stop, so the plan could not see the cost of dropping green in
        front of a moving platoon and systematically undervalued holding.
      * the terminal cost was `terminal_w * sum(q) * H`, so raising H changed
        the SHAPE of the objective (queue weight relative to accumulated delay)
        instead of only the lookahead depth, which made the horizon sweep
        uninterpretable.  It is now scaled by the fixed constant TERMINAL_T.
    """

    def __init__(self, conn, pm, predictor, sat_flow, min_green=8.0, max_green=50.0,
                 H=30.0, head=4.0, stage=2.0, startup_lost=2.0, terminal_w=0.5,
                 log=None, exhaustive_check=0, stop_penalty=STOP_PENALTY,
                 legacy_cost=False):
        super().__init__(conn, pm, min_green, log, max_green=max_green)
        self.pred = predictor
        self.sat = sat_flow                       # {group: veh/s discharge capacity}
        self.H = H
        self.head = head
        self.stage = stage
        self.l1 = startup_lost
        self.terminal_w = terminal_w
        self.stop_pen = stop_penalty
        self.legacy_cost = legacy_cost            # attempt-1 model, for the ablation
        self.last_solve = -1e9
        self.planned_switch_at = None
        self.exhaustive_check = exhaustive_check
        self.gap_records = []
        self.fsw_hist = {}                        # first-switch stage histogram
        self.dec_log = None                       # optional file handle

    # ---- queue model -------------------------------------------------------
    def _advance(self, q, served, arr, k, green_age):
        """One stage of the store-and-forward queue.

        Discharge capacity is spent first on the standing queue (FIFO); only the
        arrivals the remaining capacity can absorb pass through FREELY, at no
        delay and no stop.  Everything else joins the queue and is charged a
        stop penalty once, on the stage in which it is forced to stop.
        """
        cost = 0.0
        nq = {}
        for g in self.pm.groups:
            a = arr[g][k] if k < len(arr[g]) else 0.0
            if g in served:
                eff = self.stage
                if green_age < self.l1:
                    eff = max(0.0, self.stage - (self.l1 - green_age))
                d = self.sat[g] * eff
            else:
                d = 0.0
            if self.legacy_cost:
                q1 = max(0.0, q[g] + a - d)
                nq[g] = q1
                cost += 0.5 * (q[g] + q1) * self.stage
                continue
            cleared = min(q[g], d)               # capacity spent on the queue
            spare = d - cleared                  # capacity left for new arrivals
            through = min(a, spare)              # pass on green, no stop, no delay
            stopped = a - through                # forced to join the queue
            q1 = q[g] - cleared + stopped
            nq[g] = q1
            cost += 0.5 * (q[g] + q1) * self.stage      # queueing delay
            cost += self.stop_pen * stopped             # decel + re-accel loss
        return nq, cost

    def _next_ring(self, p, q=None, arr=None):
        """Next ring position.

        Attempt 1 carried an `allow_skip` branch that skipped a ring phase whose
        whole-horizon demand fell below a hard-coded 0.5 veh.  It never fired
        once in 385 decisions (every movement in this demand always has some
        predicted arrival), so it was dead code and is removed rather than left
        as an untested path.
        """
        return (p + 1) % len(self.pm.ring)

    def solve(self, now, q0, arr):
        K = int(round(self.H / self.stage))
        R = len(self.pm.ring)
        p0 = self.pm.ring_pos[self.cur_green]
        e0 = now - self.green_since
        clear_stages = max(1, int(math.ceil(self.pm.clearance_time(self.cur_green) / self.stage)))
        # label: key (p, e_stages, clr_left) -> (cost, queues, first_switch_stage)
        init = (p0, min(int(e0 / self.stage), 99), 0)
        labels = {init: (0.0, dict(q0), None)}
        for k in range(K):
            nxt = {}
            for (p, e, clr), (cost, q, fsw) in labels.items():
                if clr > 0:                       # inside yellow/all-red
                    nq, c = self._advance(q, set(), arr, k, 0.0)
                    key = (p, 0, clr - 1) if clr > 1 else (p, 0, 0)
                    self._push(nxt, key, cost + c, nq, fsw)
                    continue
                gi = self.pm.ring[p]
                served = set(self.pm.phase_groups[gi])
                age = e * self.stage
                # HOLD
                if age + self.stage <= self.max_green:
                    nq, c = self._advance(q, served, arr, k, age)
                    self._push(nxt, (p, e + 1, 0), cost + c, nq, fsw)
                # SWITCH
                if age >= self.min_green - 1e-9:
                    j = self._next_ring(p, q, arr)
                    nq, c = self._advance(q, set(), arr, k, 0.0)
                    self._push(nxt, (j, 0, clear_stages - 1), cost + c, nq,
                               fsw if fsw is not None else k)
            if not nxt:                            # max green with min green unmet
                for (p, e, clr), (cost, q, fsw) in labels.items():
                    gi = self.pm.ring[p]
                    nq, c = self._advance(q, set(self.pm.phase_groups[gi]), arr, k, e * self.stage)
                    self._push(nxt, (p, e + 1, 0), cost + c, nq, fsw)
            labels = nxt
        best = None
        for key, (cost, q, fsw) in labels.items():
            tot = cost + self.terminal_w * sum(q.values()) * TERMINAL_T
            if best is None or tot < best[0]:
                best = (tot, fsw)
        return best

    @staticmethod
    def _push(d, key, cost, q, fsw):
        old = d.get(key)
        if old is None or cost < old[0]:
            d[key] = (cost, q, fsw)

    def choose_target(self, now):
        if self.planned_switch_at is not None and now >= self.planned_switch_at - 1e-9:
            self.planned_switch_at = None
            p = self.pm.ring_pos[self.cur_green]
            return self.pm.ring[self._next_ring(p)]
        if now - self.last_solve < self.head:
            return None
        self.last_solve = now
        # sensing (TraCI round-trips) and optimising (pure Python) are timed
        # SEPARATELY: attempt 1 reported their sum as `solve_ms` and then drew
        # conclusions about optimiser cost from a number that was ~97% TraCI.
        t0 = time.perf_counter()
        q0 = self.pred.queues(now)
        arr = self.pred.profile(now, self.H, self.stage, q0)
        t1 = time.perf_counter()
        tot, fsw = self.solve(now, q0, arr)
        t2 = time.perf_counter()
        self.sense_ms.append((t1 - t0) * 1000.0)
        self.solve_ms.append((t2 - t1) * 1000.0)
        self.n_decisions += 1
        self.fsw_hist[fsw] = self.fsw_hist.get(fsw, 0) + 1
        if self.dec_log is not None:
            self.dec_log.write(f"{now:.2f},{self.tls},{self.cur_green},"
                               f"{'' if fsw is None else fsw}\n")
        if self.exhaustive_check and self.n_decisions % self.exhaustive_check == 0:
            ex = self.solve_exhaustive(now, q0, arr)
            if ex is not None and ex[0] > 0:
                self.gap_records.append((tot - ex[0]) / max(1e-9, ex[0]))
        if fsw is None:
            return None
        t_sw = now + fsw * self.stage
        if t_sw <= now + 1e-9:
            return self.pm.ring[self._next_ring(self.pm.ring_pos[self.cur_green])]
        if t_sw < now + self.head:
            self.planned_switch_at = t_sw
        return None

    # ---- exhaustive enumeration, to measure the DP dominance approximation ---
    def solve_exhaustive(self, now, q0, arr, cap=200000):
        K = int(round(self.H / self.stage))
        p0 = self.pm.ring_pos[self.cur_green]
        e0 = now - self.green_since
        clear_stages = max(1, int(math.ceil(self.pm.clearance_time(self.cur_green) / self.stage)))
        stack = [(0, p0, min(int(e0 / self.stage), 99), 0, 0.0, dict(q0), None)]
        best = None
        n = 0
        while stack:
            k, p, e, clr, cost, q, fsw = stack.pop()
            n += 1
            if n > cap:
                return None
            if k == K:
                tot = cost + self.terminal_w * sum(q.values()) * TERMINAL_T
                if best is None or tot < best[0]:
                    best = (tot, fsw)
                continue
            if clr > 0:
                nq, c = self._advance(q, set(), arr, k, 0.0)
                stack.append((k + 1, p, 0, clr - 1, cost + c, nq, fsw))
                continue
            gi = self.pm.ring[p]
            age = e * self.stage
            if age + self.stage <= self.max_green:
                nq, c = self._advance(q, set(self.pm.phase_groups[gi]), arr, k, age)
                stack.append((k + 1, p, e + 1, 0, cost + c, nq, fsw))
            if age >= self.min_green - 1e-9:
                j = self._next_ring(p, q, arr)
                nq, c = self._advance(q, set(), arr, k, 0.0)
                stack.append((k + 1, j, 0, clear_stages - 1, cost + c, nq,
                              fsw if fsw is not None else k))
        return best


class MeanRatePredictor(Predictor):
    """Null control for the prediction study: no detector information about WHEN
    individual vehicles arrive, only the group's running mean arrival rate.
    Any real predictive skill has to beat THIS, not beat zero."""

    def __init__(self, conn, pm, alpha=0.02):
        self.c = conn
        self.pm = pm
        self.rate = {g: 0.0 for g in pm.groups}
        self.alpha = alpha
        self.n = {g: 0 for g in pm.groups}
        self.t0 = None

    def set_dt(self, dt):
        self.dt = dt

    def attach_counts(self, counts, now):
        if self.t0 is None:
            self.t0 = 1e-9
        for g, cnt in counts.items():
            self.n[g] = cnt
        self.elapsed = max(1.0, now)

    def queues(self, now):
        return {g: sum(self.c.lane.getLastStepHaltingNumber(l)
                       for l in self.pm.group_in_lanes[g]) for g in self.pm.groups}

    def profile(self, now, H, dt, q0=None):
        nb = int(round(H / dt))
        return {g: [self.n[g] / max(1.0, getattr(self, "elapsed", 1.0)) * dt] * nb
                for g in self.pm.groups}
