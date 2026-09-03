#!/usr/bin/env python3
"""
Reservation-based Autonomous Intersection Management (AIM) as a TraCI
infrastructure agent.

TWO LAYERS, deliberately separated so that SAFETY DOES NOT DEPEND ON THE
OPTIMALITY (OR EVEN THE CORRECTNESS) OF THE SCHEDULE.

1. SCHEDULER (efficiency layer)
   A CAV entering the control zone sends a request. The agent computes the
   vehicle's earliest kinematically feasible arrival time at the stop line, then
   finds the earliest slot [t_in - buf, t_out + buf] that overlaps no already
   granted slot on a CONFLICTING internal lane (conflict relation decoded from
   the compiled net's junction request/foes bitstrings -- conflicts.py) and that
   respects the minimum time headway on its own internal lane.  t_in becomes a
   speed advisory (setSpeed every step) so the vehicle arrives inside its slot
   instead of stopping, and it also defines PRIORITY in the safety layer.
      policy=fcfs  : earliest feasible slot, requests served in request order.
      policy=batch : group / platoon forming.  A request compatible with the
                     currently active (mutually non-conflicting) movement group
                     is appended to that group back-to-back at minimum headway;
                     the group is switched only when it empties or hits a size /
                     duration cap.

2. SAFETY SUPERVISOR (interlock)
   The physical resources are the junction's 52 geometric CONFLICT POINTS
   (conflict_points.py): for each conflicting movement pair (i,j), the arclength
   along each internal path where the paths actually meet.  A vehicle must
   acquire ALL conflict points of its movement BEFORE crossing the stop line
   (all-or-nothing, so it can never stall inside the junction holding a subset),
   and releases each individually as soon as its rear bumper clears that point --
   which is what lets conflicting streams be pipelined through the junction
   instead of being serialised over the whole internal lane.  Acquisition is only
   attempted while the vehicle can still stop under comfortable deceleration, so
   a DENIED acquisition always degrades to a stop at the stop line, never to an
   unsafe entry.  A released point stays blocked for `buffer` seconds against a
   vehicle of a DIFFERENT movement (no penalty for a same-movement follower, so
   platoons are not broken).  Only the front-most non-holding vehicle of an
   approach lane may acquire (prevents a follower from locking out its own
   blocked leader).  Anti-starvation: a movement that has been yielding for more
   than `starve_time` gets absolute priority on the points it needs.

Vehicle enforcement: setSpeed + setSpeedMode=7 inside the zone (bits 0,1,2 kept
= car-following safe speed + max accel + max decel; bit 3 junction right-of-way
and bit 4 red-light braking DISABLED), restored to 31 on exit (`set-vehicle-state`).

Mixed autonomy: HDVs obey the real traffic light.  The agent holds it all-red by
default and issues a "virtual signal phase" (green on one of four protected,
internally conflict-free movement groups) when HDVs accumulate wait; CAV
acquisition is suppressed for any point involving an HDV-green movement for the
whole window plus a clearance time, and an HDV physically inside the junction
blocks every point of its own movement.

Communication realism:
  latency   -- delays (a) request handling and (b) ACTUATION: the speed command
               computed at t only reaches the vehicle at t + latency.  (b) is the
               mechanism that can genuinely break the guarantee: a yield command
               arrives too late and the vehicle overshoots into the junction.
  pos_noise -- Gaussian error on the measured distance-to-stop-line the agent
               uses (the true simulation state is untouched), so the agent can
               believe a vehicle still has room to stop when it does not.
"""
import json
import math
import os
import random
import sys
from collections import defaultdict, deque

SUMO_HOME = os.environ["SUMO_HOME"]
sys.path.append(os.path.join(SUMO_HOME, "tools"))
import traci  # noqa: E402
import traci.constants as tc  # noqa: E402

SPEED_MODE_AIM = 7
SPEED_MODE_DEFAULT = 31
ARMS = ["N", "E", "S", "W"]
INF = float("inf")

LINK_GROUPS = {
    "NS_TR":  [0, 1, 2, 8, 9, 10],
    "NS_L":   [0, 3, 8, 11],
    "EW_TR":  [4, 5, 6, 12, 13, 14],
    "EW_L":   [4, 7, 12, 15],
}

DEFAULTS = dict(
    zone=150.0, buffer=0.6, hmin=1.4, a_max=2.6, d_dec=4.0, v_max=13.89,
    dt=0.2, policy="fcfs", batch_max_n=10, batch_max_t=20.0, latency=0.0,
    pos_noise=0.0, penetration=1.0, stopline_margin=1.0, decision_slack=5.0,
    cp_radius=2.0, veh_len=4.5, starve_time=10.0, lead_gap=25.0,
    switch_gap=2.5, wave_gap=4.0, advisory_horizon=25.0,
    hdv_clear=4.0, hdv_trigger_wait=8.0, hdv_min_green=6.0, hdv_max_green=25.0,
    hdv_gap_dist=40.0, hdv_cycle_ref=30.0, cav_window_max=30.0,
    noise_seed=12345, unsafe=0, lat_comp=0,
)


def rkey(i, j):
    return (i, j) if i < j else (j, i)


class AIMController(object):

    # ------------------------------------------------------------------ setup
    def __init__(self, conflicts_path, veh_meta, params=None):
        C = json.load(open(conflicts_path))
        self.C = C
        self.n = C["n_links"]
        self.foes = {int(k): set(v) for k, v in C["foes"].items()}
        self.mov2link = C["mov2link"]
        self.int_len = {int(k): v for k, v in C["int_len"].items()}
        self.int_speed = {int(k): v for k, v in C["int_speed"].items()}
        self.chain = {int(k): v for k, v in C["int_chain"].items()}
        self.ilane2link = {lane: lst[0] for lane, lst in C["ilane2link"].items()}

        self.cp = defaultdict(dict)
        for k, v in C["conflict_points"].items():
            i, j = (int(x) for x in k.split("|"))
            self.cp[i][j] = v["s_i"]
            self.cp[j][i] = v["s_j"]

        P = dict(DEFAULTS)
        P.update(params or {})
        self.P = P
        for k, v in P.items():
            setattr(self, k, v)
        self.buf = P["buffer"]
        self.meta = veh_meta
        self.rng = random.Random(P["noise_seed"])

        self.v_cross = {i: min(self.v_max, self.int_speed[i]) for i in range(self.n)}
        self.occ_dur = {i: (self.int_len[i] + self.veh_len) / max(0.80 * self.v_cross[i], 1.0)
                        for i in range(self.n)}
        self.keys_of = {i: [rkey(i, j) for j in sorted(self.foes[i])] for i in range(self.n)}

        self.lane_len = {}
        self.chain_off = {}
        self.reservations = defaultdict(list)
        self.veh = {}
        # A conflict point is held by a MOVEMENT (link), not by a single vehicle:
        # successive vehicles of the same movement share it, so a platoon is not
        # forced to wait for its own leader to clear the junction.  Only a
        # vehicle of a CONFLICTING movement has to wait for the holder set to
        # empty (plus the `buffer` clearance).
        self.res_holders = defaultdict(set)
        self.res_link = {}
        self.res_free = defaultdict(float)
        self.last_served = defaultdict(lambda: -1e9)
        self.group = None          # batch policy: active mutually-compatible link set
        self.group_start = 0.0
        self.serve_dem = defaultdict(float)
        self.pending = deque()
        self.cmd_queue = deque()
        self.last_cmd = {}
        self.mode_set = set()
        self.tls = "center"
        self.hdv_phase = None
        self.hdv_phase_start = 0.0
        self.hdv_block_until = defaultdict(float)
        self.hdv_pending = None
        self.hdv_phase_end = -1e9
        self.hdv_in_junction = set()
        self.active_cav_links = set()
        self.is_cav = {}
        self.waiters = {}
        self.stats = defaultdict(float)
        self._group = None
        self._group_start = 0.0
        self._group_until = -1e9
        self._group_n = 0
        for i in range(self.n):
            for k in self.keys_of[i]:
                self.res_link.setdefault(k, None)

    def verify_groups(self):
        bad = []
        for g, ls in LINK_GROUPS.items():
            for i in ls:
                for j in ls:
                    if i != j and j in self.foes[i]:
                        bad.append((g, i, j))
        return bad

    def start(self):
        for arm in ARMS:
            for li in (0, 1):
                lid = "in_%s_%d" % (arm, li)
                self.lane_len[lid] = traci.lane.getLength(lid)
        for i in range(self.n):
            off = 0.0
            for lane in self.chain[i]:
                self.chain_off[lane] = off
                off += traci.lane.getLength(lane)
        self.all_red = "r" * self.n
        traci.trafficlight.setRedYellowGreenState(self.tls, self.all_red)

    def _state_for(self, links, char):
        s = ["r"] * self.n
        for i in links:
            s[i] = char
        return "".join(s)

    # -------------------------------------------------------------- kinematics
    @staticmethod
    def _t_free(d, v0, vmax, a):
        if d <= 0:
            return 0.0
        d_acc = max(0.0, (vmax * vmax - v0 * v0) / (2.0 * a))
        if d <= d_acc:
            return (math.sqrt(max(v0 * v0 + 2 * a * d, 0.0)) - v0) / a
        return (vmax - v0) / a + (d - d_acc) / vmax

    # --------------------------------------------------------------- scheduler
    def _conflict_free_slot(self, link, t_earliest, occ):
        t = t_earliest
        if self.reservations[link]:
            t = max(t, self.reservations[link][-1][0] + self.hmin)
        for _ in range(60):
            clash = None
            for j in self.foes[link]:
                for (a, b, _v) in self.reservations[j]:
                    if (t - self.buf) < (b + self.buf) and (a - self.buf) < (t + occ + self.buf):
                        if clash is None or b > clash:
                            clash = b
            if clash is None:
                return t
            t = clash + 2 * self.buf + 1e-6
        return t

    def _batch_slot(self, link, t_e, occ, now):
        g = self._group
        if g is not None:
            compatible = all(link not in self.foes[i] for i in g)
            expired = (self._group_n >= self.batch_max_n or
                       self._group_until < max(t_e, now) - 1.0 or
                       (self._group_until - self._group_start) > self.batch_max_t)
            if compatible and not expired:
                t_in = max(t_e, self._group_start)
                if self.reservations[link]:
                    t_in = max(t_in, self.reservations[link][-1][0] + self.hmin)
                self._group_until = max(self._group_until, t_in + occ)
                self._group_n += 1
                g.add(link)
                return t_in
        t_start = t_e if g is None else max(t_e, self._group_until + 2 * self.buf)
        t_start = self._conflict_free_slot(link, t_start, occ)
        self._group = set([link])
        self._group_start = t_start
        self._group_until = t_start + occ
        self._group_n = 1
        return t_start

    def _grant(self, vid, link, d, v, now):
        occ = self.occ_dur[link]
        t_e = now + self._t_free(d, v, self.v_max, self.a_max)
        t_in = (self._batch_slot(link, t_e, occ, now) if self.policy == "batch"
                else self._conflict_free_slot(link, t_e, occ))
        # The schedule is an ADVISORY -- the safety supervisor is authoritative and
        # re-sequences anyway.  Under sustained oversaturation the slot search can
        # push t_in tens of seconds into the future, which would make the speed
        # advisory crawl vehicles far more than the junction actually requires, so
        # the advisory horizon is capped.
        t_in = min(t_in, now + self.advisory_horizon)
        self.reservations[link].append([t_in, t_in + occ, vid])
        self.reservations[link].sort()
        if len(self.reservations[link]) > 60:
            del self.reservations[link][:-60]
        self.stats["grants"] += 1
        self.stats["sched_delay_sum"] += max(0.0, t_in - t_e)
        return t_in

    def _purge(self, now):
        for link in list(self.reservations.keys()):
            self.reservations[link] = [r for r in self.reservations[link] if r[1] > now - 5.0]

    # ------------------------------------------------------- safety supervisor
    def _pick_group(self, now, demand, seed=None):
        """Greedy maximal set of mutually NON-conflicting movements, ranked by
        waiting demand.  This is the platoon/batch policy's 'phase', derived
        live from the compiled foe matrix rather than from a phase table."""
        order = sorted(range(self.n), key=lambda i: -demand.get(i, 0.0))
        g = [] if seed is None else [seed]
        for i in order:
            if i in g:
                continue
            if all(i not in self.foes[j] for j in g):
                g.append(i)     # MAXIMAL compatible set: zero-demand movements are
                                # included too, so a vehicle arriving on a quiet
                                # movement is not gated out of an otherwise
                                # compatible group
        self.group = set(g)
        self.group_start = now
        self.group_start = now
        self.stats["group_switches"] += 1
        self.stats["group_size_sum"] += len(g)
        return self.group

    def _group_logic(self, now, demand, starved_link=None):
        """Retire the active group when its demand is exhausted (with a short
        grace) or when it has run for batch_max_t and something else is waiting."""
        if self.group is None:
            if any(v > 0 for v in demand.values()):
                self._pick_group(now, demand, starved_link)
            return
        if starved_link is not None and starved_link not in self.group:
            # hard anti-starvation: rebuild the group around the starved movement
            self.stats["group_time_sum"] += now - self.group_start
            self._pick_group(now, demand, starved_link)
            return
        inside = sum(self.serve_dem.get(i, 0.0) for i in self.group)
        outside = sum(v for i, v in demand.items() if i not in self.group)
        if inside <= 0:
            # group genuinely exhausted (no approaching / holding / in-junction
            # vehicle on any of its movements) -- switch at once
            if outside > 0:
                self.stats["group_time_sum"] += now - self.group_start
                self._pick_group(now, demand, starved_link)
            else:
                self.group = None
        elif now - self.group_start > self.batch_max_t and outside > 0:
            self.stats["group_time_sum"] += now - self.group_start
            self._pick_group(now, demand, starved_link)

    def _try_acquire(self, vid, link, now, prio, starved):
        if self.unsafe:
            # NEGATIVE CONTROL ONLY: interlock disabled, so the reservation
            # schedule alone must keep vehicles apart.  Used to prove that
            # SUMO's junction collision detector really does fire on this
            # network when the safety layer is removed.
            self.stats["acquires"] += 1
            self.last_served[link] = now
            return True
        """All-or-nothing acquisition of every conflict point of `link`.

        Safety conditions (hard): the point must be unowned, the post-release
        safety `buffer` must have elapsed for a vehicle of a different movement,
        and no HDV green window / in-junction HDV may involve a foe movement.

        Platoon continuation is handled by the ACQUISITION ORDER (see step()),
        not here: a movement that is currently being served is offered the
        conflict points first, so its followers keep them instead of the points
        ping-ponging between conflicting movements once per vehicle."""
        for j in self.foes[link]:
            if self.hdv_block_until[j] > now or j in self.hdv_in_junction:
                return False
        for k in self.keys_of[link]:
            holder = self.res_link.get(k)
            if holder is not None and holder != link:
                return False
            if holder is None and self.res_free[k] > now:
                return False
            w = self.waiters.get(k)
            if w is not None and w[1] != link and w[0] < prio - 1e-6:
                return False
        for k in self.keys_of[link]:
            self.res_link[k] = link
            self.res_holders[k].add(vid)
        self.last_served[link] = now
        self.stats["acquires"] += 1
        return True

    def _release_point(self, k, vid, now):
        h = self.res_holders[k]
        if vid in h:
            h.discard(vid)
            if not h:
                self.res_link[k] = None
                self.res_free[k] = now + self.buf

    def _release_all(self, vid, link, now):
        for k in self.keys_of[link]:
            self._release_point(k, vid, now)

    # ------------------------------------------------------------ HDV fallback
    def _group_hdv_demand(self, g):
        return sum(self.hdv_wait_by_link[i][0] for i in LINK_GROUPS[g])

    def _group_hdv_near(self, g):
        """HDVs close enough to the stop line to be discharged by this phase --
        the gap-out test.  Presence anywhere within the 90 m detection range is
        NOT a gap-out test: at any realistic HDV share it is essentially always
        non-zero, so the phase always runs to max green and re-triggers."""
        return sum(self.hdv_wait_by_link[i][2] for i in LINK_GROUPS[g])

    def _group_hdv_wait(self, g):
        return max([self.hdv_wait_by_link[i][1] for i in LINK_GROUPS[g]] + [0.0])

    def _hdv_logic(self, now, hdv_present, n_cav_wait=0, n_hdv_wait=0):
        if self.hdv_phase is None and not hdv_present:
            return
        if self.hdv_phase is not None:
            g, mode, t_end = self.hdv_phase
            for i in LINK_GROUPS[g]:
                self.hdv_block_until[i] = now + self.hdv_clear
            if mode == "G":
                self.stats["hdv_green_time"] += self.dt
                gap_out = (now - self.hdv_phase_start >= self.hdv_min_green
                           and self._group_hdv_near(g) == 0)
                if now >= t_end or gap_out:
                    traci.trafficlight.setRedYellowGreenState(
                        self.tls, self._state_for(LINK_GROUPS[g], "y"))
                    self.hdv_phase = (g, "Y", now + 3.0)
            elif mode == "Y":
                if now >= t_end:
                    traci.trafficlight.setRedYellowGreenState(self.tls, self.all_red)
                    self.hdv_phase = (g, "R", now + 2.0)
            else:
                if now >= t_end:
                    self.hdv_phase = None
                    self.hdv_phase_end = now
            return

        dem = {g: self._group_hdv_demand(g) for g in LINK_GROUPS}
        wait = {g: self._group_hdv_wait(g) for g in LINK_GROUPS}
        best = max(LINK_GROUPS, key=lambda g: (wait[g], dem[g]))
        if not (wait[best] >= self.hdv_trigger_wait or dem[best] >= 4):
            self.hdv_pending = None
            return
        # ------------------------------------------------------------------
        # BUG FIX 4 -- the two regimes need an explicit, demand-proportional
        # time allocation.  HDV demand within the 90 m detection range is
        # essentially never zero at any realistic HDV share, so the virtual
        # signal re-triggered the instant the previous phase retired: 100% of
        # the simulation was HDV green, the CAV interlock was permanently
        # locked out (132 acquisitions from 284 CAVs in 3600 s) and the
        # approaches gridlocked.  Reserve a CAV window between phases whose
        # length is the CAVs' share of the waiting demand, so neither regime
        # can starve the other.
        # ------------------------------------------------------------------
        if n_cav_wait > 0:
            share = float(n_cav_wait) / max(n_cav_wait + n_hdv_wait, 1)
            w_cav = min(self.cav_window_max, self.hdv_cycle_ref * share)
            if now - self.hdv_phase_end < w_cav:
                self.stats["cav_window_time"] += self.dt
                return
        # ------------------------------------------------------------------
        # BUG FIX 1 (the CAV-interlock / virtual-signal RACE).
        # A virtual signal phase may only OPEN when no CAV is already committed
        # to (or physically inside) a movement that conflicts with the phase's
        # greens.  `hdv_block_until` alone only stops a CAV from ACQUIRING
        # during a window -- it does not stop a window from OPENING on top of
        # an already-committed CAV, which produced a genuine CAV/HDV junction
        # collision (see runs/verify/BUG_hdv_race_*).
        # ------------------------------------------------------------------
        blocked_by_cav = any(
            l in self.active_cav_links
            for i in LINK_GROUPS[best] for l in self.foes[i])
        if blocked_by_cav:
            # BUG FIX 2 (deferral must be self-terminating).  Deferring alone
            # is not enough: under a continuous CAV stream new CAVs keep
            # acquiring the very conflict points we are waiting on, so the
            # phase is deferred forever and the HDVs starve (observed as jam
            # teleports).  Claim the phase NOW as PENDING -- that already sets
            # the acquisition lockout on every movement conflicting with the
            # phase's greens, so the committed CAVs drain and no new ones take
            # their place.  The phase then opens within a bounded time.
            self.hdv_pending = best
            for i in LINK_GROUPS[best]:
                self.hdv_block_until[i] = now + self.hdv_clear
            self.stats["hdv_phase_deferred"] += self.dt
            return
        self.hdv_pending = None
        traci.trafficlight.setRedYellowGreenState(
            self.tls, self._state_for(LINK_GROUPS[best], "G"))
        self.hdv_phase = (best, "G", now + self.hdv_max_green)
        self.hdv_phase_start = now
        self.stats["hdv_phases"] += 1
        for i in LINK_GROUPS[best]:
            self.hdv_block_until[i] = now + self.hdv_clear

    # -------------------------------------------------------------- actuation
    def _cmd(self, now, vid, speed):
        # setSpeed persists until changed, so only re-issue on a real change
        if abs(self.last_cmd.get(vid, -99.0) - speed) < 0.03:
            return
        self.last_cmd[vid] = speed
        if self.latency <= 0:
            traci.vehicle.setSpeed(vid, speed)
        else:
            self.cmd_queue.append((now + self.latency, vid, speed))

    def _flush(self, now, alive):
        while self.cmd_queue and self.cmd_queue[0][0] <= now + 1e-9:
            _t, vid, sp = self.cmd_queue.popleft()
            if vid in alive:
                try:
                    traci.vehicle.setSpeed(vid, sp)
                except traci.TraCIException:
                    pass

    # -------------------------------------------------------------------- step
    def on_depart(self, vid):
        m = self.meta.get(vid)
        cav = (m is not None and m["u"] < self.penetration)
        self.is_cav[vid] = cav
        traci.vehicle.subscribe(vid, [tc.VAR_ROAD_ID, tc.VAR_LANEPOSITION,
                                      tc.VAR_SPEED, tc.VAR_LANE_INDEX,
                                      tc.VAR_LANE_ID])
        if cav:
            traci.vehicle.setType(vid, "cav")
            # departLane already puts every movement on its only legal lane, so
            # no autonomous lane change is ever needed inside the zone; suppress
            # it (256 = no autonomous changes, safety checks still on) to stop
            # speed-gain lane changes from invalidating reservations.
            traci.vehicle.setLaneChangeMode(vid, 256)

    def step(self, now, sub):
        self.hdv_wait_by_link = defaultdict(lambda: [0, 0.0, 0])
        self.hdv_in_junction = set()
        hdv_present = False
        n_hdv_wait = 0
        cavs = []                     # (vid, link, x, v)  x<0 approach, >=0 in junction
        lane_veh = defaultdict(list)    # approach lane -> [(dist, vid, v, is_cav)]

        for vid, d in sub.items():
            road = d[tc.VAR_ROAD_ID]
            cav = self.is_cav.get(vid, False)
            if road.startswith(":"):
                lane = d[tc.VAR_LANE_ID]
                link = self.ilane2link.get(lane)
                if link is None:
                    continue
                if not cav:
                    self.hdv_in_junction.add(link)
                    hdv_present = True
                    continue
                cavs.append((vid, link,
                             self.chain_off.get(lane, 0.0) + d[tc.VAR_LANEPOSITION],
                             d[tc.VAR_SPEED]))
                continue
            if road.startswith("out_"):
                st = self.veh.pop(vid, None)
                if st is not None:
                    self._release_all(vid, st["link"], now)
                    traci.vehicle.setSpeed(vid, -1)
                    traci.vehicle.setSpeedMode(vid, SPEED_MODE_DEFAULT)
                    self.last_cmd.pop(vid, None)
                    self.mode_set.discard(vid)
                continue
            if not road.startswith("in_"):
                continue
            lane_i = d[tc.VAR_LANE_INDEX]
            lid = "%s_%d" % (road, lane_i)
            L = self.lane_len.get(lid)
            if L is None:
                continue
            dist = L - d[tc.VAR_LANEPOSITION]
            lane_veh[lid].append((dist, vid, d[tc.VAR_SPEED], cav))
            link = self.mov2link.get("%s|%d|%s" % (road, lane_i, self.meta[vid]["to"]))
            if cav:
                if dist <= self.zone:
                    if link is None:
                        self.stats["no_link_key"] += 1
                    else:
                        cavs.append((vid, link, -dist, d[tc.VAR_SPEED]))
            else:
                hdv_present = True
                if link is not None and dist < 90.0:
                    e = self.hdv_wait_by_link[link]
                    e[0] += 1
                    n_hdv_wait += 1
                    if dist < self.hdv_gap_dist:
                        e[2] += 1
                    if d[tc.VAR_SPEED] < 0.3:
                        e[1] = max(e[1], traci.vehicle.getWaitingTime(vid))

        # movements a CAV is currently committed to or physically occupying
        self.active_cav_links = set()
        for (vid, link, x, v) in cavs:
            st_ = self.veh.get(vid)
            if x >= 0 or (st_ is not None and st_["holds"]):
                self.active_cav_links.add(link)

        # CAVs still waiting to be served -- the other half of the demand-
        # proportional time allocation between the AIM and virtual-signal regimes
        n_cav_wait = sum(1 for (vid, link, x, v) in cavs
                         if x < 0 and -x < 90.0
                         and not (self.veh.get(vid) or {}).get("holds"))
        self._hdv_logic(now, hdv_present, n_cav_wait, n_hdv_wait)

        # ---- diagnostics: junction utilisation vs. waiting demand
        n_in = sum(1 for c in cavs if c[2] >= 0) + len(self.hdv_in_junction)
        n_wait = sum(1 for (vid, link, x, v) in cavs
                     if x < 0 and v < 0.5 and -x < 12.0)
        held = sum(1 for k, L in self.res_link.items() if L is not None)
        self.stats["t_junction_busy"] += self.dt if n_in > 0 else 0.0
        self.stats["t_idle_with_queue"] += self.dt if (n_in == 0 and n_wait > 0) else 0.0
        self.stats["t_any_hold"] += self.dt if held > 0 else 0.0
        self.stats["veh_in_junction_sum"] += n_in * self.dt
        self.stats["queue_at_stopline_sum"] += n_wait * self.dt

        # batch policy: track the active movement group (diagnostic only; the
        # policy is applied through the acquisition ORDER below, not as a gate)
        if self.policy == "batch":
            dem = defaultdict(float)          # ranking demand: UNSERVED vehicles only
            self.serve_dem = defaultdict(float)  # any vehicle still being served
            worst = (0.0, None)
            for (vid, link, x, v) in cavs:
                st = self.veh.get(vid)
                if x >= 0:
                    self.serve_dem[link] += 1.0     # already inside the junction
                    continue
                if -x > 110.0:
                    continue
                self.serve_dem[link] += 1.0
                if st is not None and st["holds"]:
                    continue                        # served, but not new demand
                bs = st["blocked_since"] if st else None
                w = (now - bs) if bs is not None else 0.0
                dem[link] += 1.0 + 0.5 * w + (1.0 if v < 0.5 else 0.0)
                if w > worst[0]:
                    worst = (w, link)
            self._group_logic(now, dem,
                              worst[1] if worst[0] >= self.starve_time else None)

        # anti-starvation waiter map, from the previous step's blocked states
        self.waiters = {}
        for vid, st in self.veh.items():
            bs = st.get("blocked_since")
            if bs is None or st["holds"] or now - bs < self.starve_time:
                continue
            for k in self.keys_of[st["link"]]:
                w = self.waiters.get(k)
                if w is None or bs < w[0]:
                    self.waiters[k] = (bs, st["link"])

        # eligibility: only the front-most non-holding vehicle of a lane may acquire
        eligible = set()
        for lid, lst in lane_veh.items():
            lst.sort()
            blocker = None
            for (dist, vid, v, cav) in lst:
                st = self.veh.get(vid)
                holding = bool(st and st["holds"])
                if blocker is not None and (dist - blocker) < self.lead_gap:
                    continue
                if holding:
                    continue
                if cav:
                    eligible.add(vid)
                blocker = dist
                break

        # requests (latency-delayed)
        for (vid, link, x, v) in cavs:
            if x < 0 and vid not in self.veh:
                self.veh[vid] = {"link": link, "t_in": None, "holds": False,
                                 "blocked_since": None}
                self.stats["requests"] += 1
                self.pending.append((now + self.latency, vid, link, -x, v))
        while self.pending and self.pending[0][0] <= now + 1e-9:
            _t, vid, link, dist, v = self.pending.popleft()
            st = self.veh.get(vid)
            if st is None or st["t_in"] is not None:
                continue
            st["t_in"] = self._grant(vid, link, dist, v, now)

        # Enforcement order.  Primary key implements PLATOON CONTINUATION: a
        # movement served within the last `switch_gap` seconds is offered the
        # conflict points before a conflicting movement, so a stream is not
        # broken up after every single vehicle (which would force every vehicle
        # to pay the stop-and-start penalty).  A movement that has been yielding
        # for `starve_time` jumps to the front, bounding the wait.  Within a
        # tier the scheduler's granted slot t_in decides -- that is where the
        # fcfs / batch policies actually differ.
        # PLATOON / BATCH FORMING happens here, in the acquisition order.
        #   fcfs : a movement served within `switch_gap` keeps priority -- only
        #          its own followers continue, every other movement is equal.
        #   batch: the whole current WAVE (every movement served within
        #          `wave_gap`) plus every movement COMPATIBLE with all of it gets
        #          priority, so consecutive compatible requests are granted
        #          together as one platoon instead of one vehicle at a time.
        # A movement yielding for `starve_time` jumps ahead of everything.
        if self.policy == "batch":
            wave = set(i for i in range(self.n)
                       if now - self.last_served[i] < self.wave_gap)
            join = set(i for i in range(self.n)
                       if i not in wave and wave
                       and all(i not in self.foes[j] for j in wave))
        else:
            wave = set(i for i in range(self.n)
                       if now - self.last_served[i] < self.switch_gap)
            join = set()

        def order(c):
            vid, link = c[0], c[1]
            st = self.veh.get(vid)
            bs = st["blocked_since"] if st else None
            if bs is not None and now - bs >= self.starve_time:
                tier = -1
            elif link in wave:
                tier = 0
            elif link in join:
                tier = 1
            else:
                tier = 2
            t_in = st["t_in"] if st and st["t_in"] is not None else INF
            return (tier, t_in, vid)
        cavs.sort(key=order)

        for (vid, link, x, v) in cavs:
            st = self.veh.get(vid)
            if st is None:
                self._cmd(now, vid, self.v_cross[link])
                continue
            if st["link"] != link and x < 0:
                self._release_all(vid, st["link"], now)
                st.update(link=link, t_in=None, holds=False, blocked_since=None)
                self.stats["relink"] += 1
                self.pending.append((now + self.latency, vid, link, -x, v))
            if vid not in self.mode_set:
                traci.vehicle.setSpeedMode(vid, SPEED_MODE_AIM)
                self.mode_set.add(vid)

            if st["holds"]:                       # release cleared conflict points
                rel = self.cp_radius + self.veh_len
                for j in self.foes[link]:
                    k = rkey(link, j)
                    if vid in self.res_holders[k] and x > self.cp[link][j] + rel:
                        self._release_point(k, vid, now)

            # ---------------------------------------------------------------
            # BUG FIX 3 -- DEFENCE IN DEPTH against the uncontrollable agent.
            # An HDV is not schedulable: it can be sitting inside the junction
            # on a conflicting path for reasons the agent never authorised (a
            # permissive left waiting for a gap, a vehicle that entered on its
            # own green and stalled, spillback).  A CAV that has ALREADY
            # committed runs with junction right-of-way checks disabled
            # (speedMode bit 3 off) and, once it is on its own internal lane,
            # SUMO applies no foe check at all -- so SUMO will not save it and
            # the reservation cannot be un-granted.  Cap its speed so that it
            # stops SHORT of every conflict point it shares with an occupied
            # HDV movement.  Cannot fire when penetration == 1.0 (no HDVs), so
            # all-CAV results are bit-identical to the pre-fix controller.
            # ---------------------------------------------------------------
            v_lim = INF
            if self.hdv_in_junction:
                s_stop = INF
                for j in self.foes[link]:
                    if j in self.hdv_in_junction:
                        s = self.cp[link].get(j)
                        if s is not None:
                            s_stop = min(s_stop, s - self.cp_radius - 1.0)
                if s_stop < INF:
                    gap = s_stop - x
                    v_lim = math.sqrt(2.0 * self.d_dec * gap) if gap > 0.0 else 0.0
                    self.stats["hdv_guard_active"] += self.dt

            if x >= 0.0 or st["holds"]:
                self._cmd(now, vid, min(self.v_cross[link], v_lim))
                continue

            d_true = -x
            d_meas = d_true if self.pos_noise <= 0 else max(
                0.0, d_true + self.rng.gauss(0.0, self.pos_noise))

            # LATENCY COMPENSATION (off by default).  A speed command computed
            # at t only reaches the vehicle at t + latency, by which time the
            # vehicle has travelled v*latency further -- so a command that was
            # exactly stop-at-the-line when computed is an overshoot when it
            # lands.  Budgeting that distance away restores the guarantee; the
            # default (lat_comp = 0) is the NAIVE controller, which is what the
            # communication-realism sweep is measuring.
            # The same argument applies to position error: the agent may believe
            # the vehicle is further back than it is, by up to ~3 sigma.
            d_meas = max(0.0, d_meas - self.lat_comp * (v * self.latency
                                                        + 3.0 * self.pos_noise))

            brake = v * v / (2.0 * self.d_dec) + v * self.dt * 2.0 + self.stopline_margin
            if d_meas <= brake + self.decision_slack and vid in eligible:
                prio = st["blocked_since"] if st["blocked_since"] is not None else now
                starved = (st["blocked_since"] is not None
                           and now - st["blocked_since"] >= self.starve_time)
                if self._try_acquire(vid, link, now, prio, starved):
                    st["holds"] = True
                    st["blocked_since"] = None
                    if st["t_in"] is not None:
                        self.stats["late_vs_plan_sum"] += now - st["t_in"]
                        self.stats["late_vs_plan_n"] += 1
                    self._cmd(now, vid, min(self.v_cross[link], v_lim))
                    continue
                if st["blocked_since"] is None:
                    st["blocked_since"] = now
                self.stats["interlock_blocks"] += 1

            v_cmd = self.v_max
            if st["t_in"] is not None:
                dt = st["t_in"] - now
                if dt > 0.1:
                    v_cmd = min(self.v_max, max(0.0, d_meas / dt))
            v_cmd = min(v_cmd, math.sqrt(2.0 * self.d_dec *
                                         max(d_meas - self.stopline_margin, 0.0)))
            v_cmd = min(v_cmd, v_lim)
            if v_cmd < 0.15:
                v_cmd = 0.0
                self.stats["denied_stop"] += 1
            self._cmd(now, vid, v_cmd)

        if self.latency > 0:
            self._flush(now, sub)
        if abs(now - round(now)) < 1e-9 and int(round(now)) % 10 == 0:
            self._purge(now)
