#!/usr/bin/env python3
"""Detector-free adaptive signal control from sparse connected-vehicle (CV) data.

Layers, deliberately separated so the information available to each controller is
a structural property of the code rather than a promise:

  CVAssignment   -- who is connected.  A seeded per-vehicle-ID hash draw; NOT a
                    function of route, OD, departure order or vehicle class.
                    Nested in p (the p=2% fleet is a subset of the p=5% fleet),
                    which makes the penetration sweep a Common-Random-Numbers
                    design across p.

  ObservationLayer -- the ONLY channel through which a CV controller sees
                    traffic.  It subscribes ONLY connected vehicles to TraCI
                    (VAR_LANE_ID, VAR_LANEPOSITION, VAR_SPEED) and returns their
                    (id, lane, pos, speed) tuples.  A non-connected vehicle is
                    never subscribed, so its state is never fetched from SUMO at
                    all — the controller cannot read what was never retrieved.

  GroundTruth    -- traci.lane.getLastStepHaltingNumber per lane.  Used by (i)
                    the perfect-information max-pressure controller and (ii) the
                    evaluation/logging layer.  A runtime Guard makes any call
                    into this layer from inside a CV controller's decision
                    function a hard error.

  *JunctionController -- phase-to-movement mapping via getControlledLinks,
                    minimum green, yellow + all-red clearance (holding all-red
                    until the vacated phase's internal lanes are physically
                    empty).  This machinery is taken from the
                    `implement-maxpressure-traci-controller` skill's
                    maxpressure_controller.py; only the queue-estimation and
                    phase-selection rules are new.
"""
import hashlib
import os
import struct
import sys

SUMO_HOME = os.environ.get("SUMO_HOME") or \
    "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo"
os.environ["SUMO_HOME"] = SUMO_HOME
sys.path.append(os.path.join(SUMO_HOME, "tools"))
import traci  # noqa: E402
import traci.constants as tc  # noqa: E402

HOLD = 100000.0
ALLRED_CAP = 12.0
MIN_GREEN_FLOOR = 6.0   # s — absolute lower bound on any green
HALT_SPEED = 0.1        # m/s — SUMO's own halting threshold
SPACING = 7.5           # m — vType default length 5.0 + minGap 2.5


# ------------------------------------------------------------------- guard --

class Guard(object):
    """Raises if a ground-truth TraCI getter is called while a CV controller is
    deciding.  Internal (':'-prefixed) lanes are exempt and counted separately:
    they are read only by the all-red clearance check, which is a junction
    safety interlock, not traffic-state information about an approach."""

    def __init__(self):
        self.active = False
        self.violations = []
        self.internal_reads = 0
        self.installed = False

    def check(self, fname, laneid):
        if not self.active:
            return
        if isinstance(laneid, str) and laneid.startswith(":"):
            self.internal_reads += 1
            return
        self.violations.append((fname, laneid))
        raise RuntimeError("INFORMATION LEAK: %s(%r) called inside a CV "
                           "controller decision" % (fname, laneid))

    def install(self):
        if self.installed:
            return
        self.installed = True
        names = ["getLastStepHaltingNumber", "getLastStepVehicleNumber",
                 "getLastStepVehicleIDs", "getLastStepOccupancy",
                 "getLastStepMeanSpeed", "getLastStepLength", "getWaitingTime"]
        for n in names:
            orig = getattr(traci.lane, n)

            def make(n=n, orig=orig):
                def wrapped(laneID, *a, **k):
                    self.check("lane." + n, laneID)
                    return orig(laneID, *a, **k)
                return wrapped
            setattr(traci.lane, n, make())
        for mod, n in (("edge", "getLastStepHaltingNumber"),
                       ("edge", "getLastStepVehicleIDs"),
                       ("edge", "getLastStepVehicleNumber")):
            m = getattr(traci, mod)
            orig = getattr(m, n)

            def make2(mod=mod, n=n, orig=orig):
                def wrapped(eid, *a, **k):
                    self.check(mod + "." + n, eid)
                    return orig(eid, *a, **k)
                return wrapped
            setattr(m, n, make2())


GUARD = Guard()


# ------------------------------------------------------------ CV assignment --

class CVAssignment(object):
    """Seeded, per-vehicle-ID random draw.  u(vid) is fixed by (salt, vid); a
    vehicle is connected iff u(vid) < p.  Nested across p by construction."""

    def __init__(self, p, salt):
        self.p = float(p)
        self.salt = str(salt)
        self._cache = {}

    def u(self, vid):
        v = self._cache.get(vid)
        if v is None:
            h = hashlib.blake2b((self.salt + "|" + vid).encode(),
                                digest_size=8).digest()
            v = struct.unpack("<Q", h)[0] / 2.0 ** 64
            self._cache[vid] = v
        return v

    def is_cv(self, vid):
        return self.p > 0.0 and self.u(vid) < self.p


# -------------------------------------------------------- observation layer --

class ObservationLayer(object):
    """Subscribes ONLY connected vehicles; returns only their state."""

    VARS = [tc.VAR_LANE_ID, tc.VAR_LANEPOSITION, tc.VAR_SPEED]

    def __init__(self, assignment):
        self.a = assignment
        self.n_subscribed = 0

    def on_step(self):
        for vid in traci.simulation.getDepartedIDList():
            if self.a.is_cv(vid):
                traci.vehicle.subscribe(vid, self.VARS)
                self.n_subscribed += 1

    def observe(self):
        """-> {lane: [(vid, pos, speed), ...]} for connected vehicles only."""
        res = traci.vehicle.getAllSubscriptionResults()
        out = {}
        for vid, d in res.items():
            ln = d.get(tc.VAR_LANE_ID)
            if not ln:
                continue
            out.setdefault(ln, []).append(
                (vid, d.get(tc.VAR_LANEPOSITION, 0.0), d.get(tc.VAR_SPEED, 0.0)))
        return out


# ------------------------------------------------------------- estimators ---

def est_naive(obs_lane, p, lane_len):
    """1/p scaling of the observed stopped-CV count on the lane."""
    if p <= 0:
        return 0.0
    k = sum(1 for (_, _, s) in obs_lane if s < HALT_SPEED)
    return k / p


def est_shockwave(obs_lane, p, lane_len):
    """Last-probe / shockwave estimator (Comert & Cetin spirit).

    The upstream-most STOPPED connected vehicle at lane position x is d =
    lane_len - x metres back from the stop bar, so at least d/SPACING + 1
    vehicles are queued ahead of and including it.  Behind it, the number of
    unobserved vehicles before the queue ends is Geometric(p) with mean
    (1-p)/p.  Estimate = d/SPACING + 1 + (1-p)/p, capped at the lane's physical
    storage.  Position, not count, carries the information — one probe deep in
    the queue reveals the whole queue behind it."""
    if p <= 0:
        return 0.0
    stopped = [x for (_, x, s) in obs_lane if s < HALT_SPEED]
    if not stopped:
        return 0.0
    d = lane_len - min(stopped)
    q = d / SPACING + 1.0 + (1.0 - p) / p
    return min(q, lane_len / SPACING)


ESTIMATORS = {"naive": est_naive, "shockwave": est_shockwave}


# --------------------------------------------------------- base controller ---

def is_green(state):
    return ("G" in state or "g" in state) and "y" not in state


def has_yellow(state):
    return "y" in state


def is_allred(state):
    return ("G" not in state) and ("g" not in state) and ("y" not in state)


class BaseJunctionController(object):
    """Phase mapping + min-green + yellow/all-red clearance state machine.
    Subclasses implement choose(now) -> target green phase index."""

    def __init__(self, tls_id, min_green_frac=0.5, decision_interval=5.0,
                 switch_theta=0.0, min_green_floor=MIN_GREEN_FLOOR):
        self.tls = tls_id
        self.min_green_frac = min_green_frac
        self.min_green_floor = min_green_floor
        # Switching threshold: only leave the current green if another phase's
        # pressure exceeds it by more than `switch_theta`.  Plain max-pressure
        # has no notion of the lost time (yellow + all-red + start-up) that each
        # switch costs, so on a 3-phase program it switches far more often than
        # is efficient; theta prices that lost time explicitly.
        self.switch_theta = switch_theta
        self.decision_interval = decision_interval
        logic = traci.trafficlight.getAllProgramLogics(tls_id)[0]
        self.phases = logic.phases
        self.n = len(self.phases)
        links = traci.trafficlight.getControlledLinks(tls_id)
        self.green_phases = [i for i, p in enumerate(self.phases)
                             if is_green(p.state)]
        self.phase_in, self.phase_out, self.phase_via = {}, {}, {}
        self.phase_links = {}
        for gi in self.green_phases:
            st = self.phases[gi].state
            inc, out, via, pl = set(), set(), set(), []
            for idx, ch in enumerate(st):
                if ch in ("G", "g") and idx < len(links):
                    for lk in links[idx]:
                        if lk and lk[0]:
                            inc.add(lk[0])
                        if lk and lk[1]:
                            out.add(lk[1])
                        if lk and len(lk) > 2 and lk[2]:
                            via.add(lk[2])
                        if lk and lk[0] and lk[1]:
                            pl.append((lk[0], lk[1]))
            self.phase_in[gi] = sorted(inc)
            self.phase_out[gi] = sorted(out)
            self.phase_via[gi] = sorted(via)
            self.phase_links[gi] = pl

        self.clearance, self.allred = {}, {}
        for gi in self.green_phases:
            y, r = self._following_clearance(gi)
            self.clearance[gi] = y
            self.allred[gi] = r
        self.lane_len = {}
        for gi in self.green_phases:
            for l in self.phase_in[gi] + self.phase_out[gi]:
                if l not in self.lane_len:
                    self.lane_len[l] = traci.lane.getLength(l)   # static geometry
        self.prog_dur = {gi: float(self.phases[gi].duration)
                         for gi in self.green_phases}
        # Per-phase minimum green.  A single uniform min-green is a bad fit for a
        # 3-phase program whose design greens differ by 4x (11 s left vs 43 s
        # through): it either lets the through phase be cut far too short (lost
        # time explodes) or forces the short left phase to run far too long.
        # min_green_g = max(MIN_GREEN_FLOOR, frac * programmed green).
        self.min_green_g = {gi: max(self.min_green_floor,
                                    min_green_frac * self.prog_dur[gi])
                            for gi in self.green_phases}

        self.mode = "GREEN"
        self.cur_green = self.green_phases[0] if self.green_phases else 0
        self.target_green = self.cur_green
        self.vacating_green = self.cur_green
        self.green_since = 0.0
        self.yellow_until = 0.0
        self.allred_min_until = 0.0
        self.allred_cap_until = 0.0
        self.last_decision = -1e9
        # instrumentation
        self.last_served = {gi: 0.0 for gi in self.green_phases}
        self.service_gaps = {gi: [] for gi in self.green_phases}
        self.phase_seq = []
        self.n_fallback = 0
        self.n_decisions = 0

    def pressure_from(self, q):
        """Varaiya per-MOVEMENT pressure: sum over the phase's green
        lane-to-lane links of (upstream queue - downstream queue).  Summing over
        LINKS rather than over the SET of incoming/outgoing lanes weights each
        phase by how many lanes actually serve it and avoids double-counting a
        shared receiving lane, which otherwise systematically penalises the
        arterial through phase on a corridor (its receiving lane is the next
        intersection's approach and is often queued)."""
        return {gi: sum(q[a] - q[b] for a, b in self.phase_links[gi])
                for gi in self.green_phases}

    def _following_clearance(self, gi):
        yellow = allred = None
        for step in range(1, self.n + 1):
            j = (gi + step) % self.n
            st = self.phases[j].state
            if yellow is None and has_yellow(st):
                yellow = j
                continue
            if yellow is not None:
                if is_allred(st):
                    allred = j
                break
            if j in self.green_phases:
                break
        return yellow, allred

    def start(self, now):
        if not self.green_phases:
            return
        traci.trafficlight.setPhase(self.tls, self.cur_green)
        traci.trafficlight.setPhaseDuration(self.tls, HOLD)
        self.green_since = now
        self.last_served = {gi: now for gi in self.green_phases}
        self.phase_seq.append((now, self.cur_green))

    # --- to be provided by subclasses ---------------------------------------
    def choose(self, now, ctx):
        raise NotImplementedError

    def step(self, now, ctx):
        if len(self.green_phases) < 2:
            return
        if self.mode == "YELLOW":
            if now >= self.yellow_until:
                ar = self.allred[self.vacating_green]
                if ar is not None:
                    traci.trafficlight.setPhase(self.tls, ar)
                    traci.trafficlight.setPhaseDuration(self.tls, HOLD)
                    self.mode = "ALLRED"
                    self.allred_min_until = now + self.phases[ar].duration
                    self.allred_cap_until = now + ALLRED_CAP
                else:
                    self._commit(now)
            return
        if self.mode == "ALLRED":
            past_min = now >= self.allred_min_until
            past_cap = now >= self.allred_cap_until
            via = self.phase_via.get(self.vacating_green, [])
            clear = all(traci.lane.getLastStepVehicleNumber(l) == 0 for l in via)
            if past_cap or (past_min and clear):
                self._commit(now)
            return
        # GREEN
        if now - self.green_since < self.min_green_g[self.cur_green]:
            return
        if now - self.last_decision < self.decision_interval:
            return
        self.last_decision = now
        self.n_decisions += 1
        best = self.choose(now, ctx)
        if best is None or best == self.cur_green:
            return
        self.vacating_green = self.cur_green
        self.target_green = best
        y = self.clearance[self.cur_green]
        if y is None:
            self._commit(now)
            return
        traci.trafficlight.setPhase(self.tls, y)
        traci.trafficlight.setPhaseDuration(self.tls, HOLD)
        self.mode = "YELLOW"
        self.yellow_until = now + self.phases[y].duration

    def _commit(self, now):
        traci.trafficlight.setPhase(self.tls, self.target_green)
        traci.trafficlight.setPhaseDuration(self.tls, HOLD)
        self.service_gaps[self.target_green].append(
            now - self.last_served[self.target_green])
        self.last_served[self.target_green] = now
        self.cur_green = self.target_green
        self.mode = "GREEN"
        self.green_since = now
        self.phase_seq.append((now, self.cur_green))


# ---------------------------------------------------- perfect-information ---

class PerfectMP(BaseJunctionController):
    """Max-pressure on the true per-lane halting counts (information ceiling)."""

    def true_pressures(self):
        q = {}
        for gi in self.green_phases:
            for l in self.phase_in[gi] + self.phase_out[gi]:
                if l not in q:
                    q[l] = traci.lane.getLastStepHaltingNumber(l)
        return self.pressure_from(q), q

    def choose(self, now, ctx):
        pr, _ = self.true_pressures()
        best = max(pr, key=lambda g: pr[g])
        if pr[best] <= pr[self.cur_green] + self.switch_theta:
            return None
        return best


# ------------------------------------------------------------ CV-driven MP ---

class CVMP(BaseJunctionController):
    """Max-pressure driven exclusively by the observation layer's CV records."""

    def __init__(self, tls_id, p, estimator, min_green_frac=0.5,
                 decision_interval=5.0, memory=False, mem_alpha=0.35,
                 force_off=None, switch_theta=0.0,
                 min_green_floor=MIN_GREEN_FLOOR):
        BaseJunctionController.__init__(self, tls_id, min_green_frac,
                                        decision_interval, switch_theta,
                                        min_green_floor)
        self.p = float(p)
        self.est = ESTIMATORS[estimator]
        self.memory = memory
        self.mem_alpha = mem_alpha
        self.force_off = force_off       # seconds; None disables
        self._mem = {}
        self.n_forced = 0
        self.last_est = {}

    def estimate(self, obs):
        """obs: {lane: [(vid,pos,speed)]}, CV records only."""
        q = {}
        for gi in self.green_phases:
            for l in self.phase_in[gi] + self.phase_out[gi]:
                if l in q:
                    continue
                v = self.est(obs.get(l, ()), self.p, self.lane_len[l])
                if self.memory:
                    m = self._mem.get(l, 0.0)
                    m = self.mem_alpha * v + (1.0 - self.mem_alpha) * m
                    self._mem[l] = m
                    v = max(v, m)
                q[l] = v
        return q

    def choose(self, now, ctx):
        obs = ctx["obs"]
        q = self.estimate(obs)
        self.last_est = q
        pr = self.pressure_from(q)
        ctx.setdefault("est_pressure", {})[self.tls] = dict(pr)
        ctx.setdefault("est_queue", {})[self.tls] = dict(q)

        # starvation mitigation: force-off / max-out timer
        if self.force_off is not None:
            overdue = [gi for gi in self.green_phases
                       if gi != self.cur_green
                       and now - self.last_served[gi] >= self.force_off]
            if overdue:
                self.n_forced += 1
                return max(overdue, key=lambda g: now - self.last_served[g])

        # documented fallback: with no information (all estimated pressures
        # equal) degrade to the loaded fixed-time program — advance to the next
        # green phase in program order once its programmed duration has elapsed.
        vals = set(round(v, 9) for v in pr.values())
        if len(vals) <= 1:
            self.n_fallback += 1
            if now - self.green_since >= self.prog_dur[self.cur_green]:
                k = self.green_phases.index(self.cur_green)
                return self.green_phases[(k + 1) % len(self.green_phases)]
            return None

        best = max(pr, key=lambda g: pr[g])
        if pr[best] <= pr[self.cur_green]:
            return None
        return best
