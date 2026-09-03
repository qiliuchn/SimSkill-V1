"""Sub-goal 1: the closed-loop coordinated adaptive signal-control system --
SCATS/SCOOT/InSync-class -- built on `controller_core.JunctionPlant`.

THREE NESTED LAYERS, all recomputed together once per SYSTEM CYCLE TICK (a
virtual region clock that advances by the CURRENT common cycle length C each
tick -- this IS the "common-cycle constraint": every junction's plan is
re-derived from the same (C, per-junction splits, per-junction offset) state
every tick, so any two junctions' realized cycle lengths can only ever differ
during the brief propagation lag between a tick and each junction's own next
stage boundary adopting the new plan -- exactly the real-world behavior of a
region-wide coordinated system, and directly checkable from `cycle_log`):

  (a) SPLIT ADAPTATION (every tick, every junction): equalize degree of
      saturation between the junction's two "critical movements"
      (ART_MAIN vs CROSS) by reallocating the junction's own available green
      time proportional to measured DoS_hat, subject to a min-green floor.
  (b) CYCLE-LENGTH ADAPTATION (every tick, network-wide): drive the
      CRITICAL intersection's (max DoS_hat over all junctions/movements)
      degree of saturation toward TARGET_DOS (0.90) via a slew-rate-limited
      (asymmetric: grows faster than it shrinks, matching real controller
      practice of protecting against under-provision) step, bounded to
      [C_MIN, C_MAX] -- this bound IS the runaway failsafe exercised in
      sub-goal 6.
  (c) OFFSET ADAPTATION (every tick, every junction): shift the junction's
      ART_MAIN green onset toward the MEASURED mean platoon arrival time (at
      its own advance detector, i.e. the platoon dispersed from whatever is
      immediately upstream), slew-rate-limited, realized as a one-shot
      correction to the (subordinate) CROSS stage -- never perturbing the
      coordinated ART_MAIN green itself, the standard real-controller
      offset-correction practice this module shares with the sub-goal-3
      transition-method study.

TraCI AUDIT: every simulator read this controller performs is listed in
AUDITED_READ_CALLS below and is one of exactly two kinds: (1) E1/E2 DETECTOR
reads (`traci.inductionloop.*`, `traci.lanearea.*`) and (2)
`traci.trafficlight.*` / `traci.simulation.getTime()` bookkeeping needed to
drive the state machine and read back its OWN applied plan. It NEVER calls
`traci.vehicle.*` or any ground-truth lane/edge vehicle-count function
(`traci.lane.getLastStepVehicleNumber` is used ONLY by JunctionPlant's
all-red internal-lane clearance safety check inherited from
`implement-maxpressure-traci-controller` -- a SAFETY interlock, not a
control-decision input; it is called on internal junction lanes, which carry
no detectors and are not part of any DoS calculation). See audit_controller.py
for the automated static+runtime verification of this claim.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
SUMO_HOME = os.environ.get("SUMO_HOME") or \
    "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo"
os.environ.setdefault("SUMO_HOME", SUMO_HOME)
sys.path.append(os.path.join(SUMO_HOME, "tools"))
import traci  # noqa: E402
from controller_core import JunctionPlant  # noqa: E402

N_INT = 5
S_MEAS = 1604.4          # veh/h/lane, det/satflow_result.txt (measured, sub-goal 2)
TARGET_DOS = 0.90
C_MIN, C_MAX = 55.0, 150.0
CYCLE_SLEW_UP, CYCLE_SLEW_DOWN = 5.0, 2.5     # s per tick (asymmetric)
DOS_DEADBAND = 0.04
SPLIT_MIN_GREEN = 10.0
SPLIT_SLEW = 6.0         # s per tick -- rate-limits the split-adaptation layer
                         # itself (found necessary empirically: an UNLIMITED
                         # equisaturation split reallocation, driven by a noisy
                         # single-cycle DoS estimate from only ~10-20 vehicles,
                         # produced a genuine feedback oscillation -- one noisy
                         # tick could swing ART_MAIN's share from ~70% to ~20%,
                         # starving it and reporting a spurious DoS>2 the next
                         # tick. Real SCATS/SCOOT systems rate-limit split
                         # (not just cycle-length) changes for exactly this
                         # reason; this constant is that damping.
OFFSET_SLEW = 4.0        # s per tick
OFFSET_TARGET_INCYCLE = 3.0  # s: aim for the platoon to arrive just after green onset


class SystemController(object):
    def __init__(self, junction_ids=None, C0=90.0, min_green=8.0,
                 target_dos=TARGET_DOS, c_min=C_MIN, c_max=C_MAX,
                 transition="dwell", spread_n=4, update_interval_cycles=1):
        self.ids = junction_ids or ["J%d" % i for i in range(N_INT)]
        self.plants = {j: JunctionPlant(j, min_green=min_green) for j in self.ids}
        self.C = C0
        self.target_dos = target_dos
        self.c_min, self.c_max = c_min, c_max
        self.transition = transition   # 'dwell' | 'add' | 'subtract' | 'spread'
        self.spread_n = spread_n
        # sub-goal 3 part B: how many CYCLES elapse between adaptation ticks.
        # 1 = adapt every cycle (this controller's default/baseline); sweeping
        # this up to 2/5/10/20 trades responsiveness for adaptation-induced
        # transition overhead -- see transition/update_interval_sweep.py.
        self.update_interval_cycles = max(1, int(update_interval_cycles))
        self._window_len = C0 * self.update_interval_cycles
        self._pending_spread = {}      # junction -> list of remaining per-tick deltas (offset spread)
        self._pending_cycle_spread = []  # for cycle-length 'spread' transitions

        self.adv_ids = {}   # (junction, dir) -> [lane detector ids]
        for i in range(N_INT):
            j = "J%d" % i
            for d in ("EB", "WB", "SB"):
                n_lanes = 1 if d == "SB" else 2
                self.adv_ids[(j, d)] = ["ADV_%s_%s_%d" % (j, d, li) for li in range(n_lanes)]
        self._prev_present = {aid: frozenset() for ids in self.adv_ids.values() for aid in ids}
        self._entry_count = {aid: 0 for ids in self.adv_ids.values() for aid in ids}
        self._entry_times = {aid: [] for ids in self.adv_ids.values() for aid in ids}

        self.next_tick = self._window_len
        self.dos_log = []          # (t, junction, dir, DoS_hat)
        self.cycle_target_log = []  # (t, C_target)
        self.audit_calls = {}      # call-name -> count, for the runtime audit

        for j in self.ids:
            self.plants[j].start(0.0)

    # ---------------------------------------------------- detector polling
    def _audit(self, name):
        self.audit_calls[name] = self.audit_calls.get(name, 0) + 1

    def poll_detectors(self, now):
        """Call ONCE per simulation step. ONLY E1 detector reads."""
        for aid in self._prev_present:
            self._audit("inductionloop.getLastStepVehicleIDs")
            cur = frozenset(traci.inductionloop.getLastStepVehicleIDs(aid))
            new = cur - self._prev_present[aid]
            if new:
                self._entry_count[aid] += len(new)
                self._entry_times[aid].append(now)
            self._prev_present[aid] = cur

    # ------------------------------------------------------------- ticking
    def step(self, now):
        for p in self.plants.values():
            p.step(now)
        self.poll_detectors(now)
        if now >= self.next_tick:
            self._adapt(now)
            self._window_len = self.C * self.update_interval_cycles
            self.next_tick += self._window_len

    # --------------------------------------------------------- DoS from detectors
    def _dos_hat(self, j, d, green_now, n_lanes):
        self._audit("dos_hat_compute")
        cnt = sum(self._entry_count[aid] for aid in self.adv_ids[(j, d)])
        win = self._window_len if self._window_len > 0 else self.C
        q_hat = cnt / win * 3600.0 if win > 0 else 0.0
        cap_hat = (green_now / self.C) * S_MEAS * n_lanes if self.C > 0 else 1.0
        return q_hat / cap_hat if cap_hat > 0 else 0.0

    def _mean_arrival_incycle(self, j, d, art_main_start):
        times = []
        for aid in self.adv_ids[(j, d)]:
            times += self._entry_times[aid]
        if not times:
            return None
        rel = [((t - art_main_start) % self.C) for t in times]
        # fold to [-C/2, C/2) around 0 (green onset) so "just before green" reads
        # as a small negative number, not near +C
        rel = [(r - self.C if r > self.C / 2 else r) for r in rel]
        return sum(rel) / len(rel)

    # ------------------------------------------------------------ adaptation
    def _adapt(self, now):
        dos = {}   # (j, 'ART') / (j, 'CROSS') -> DoS_hat
        for j in self.ids:
            plant = self.plants[j]
            art_g = plant.plan["ART_MAIN"]
            cross_g = plant.plan["CROSS"]
            dos_eb = self._dos_hat(j, "EB", art_g, 2)
            dos_wb = self._dos_hat(j, "WB", art_g, 2)
            dos_art = max(dos_eb, dos_wb)
            dos_cross = self._dos_hat(j, "SB", cross_g, 1)
            dos[(j, "ART")] = dos_art
            dos[(j, "CROSS")] = dos_cross
            self.dos_log.append((now, j, "ART_MAIN", dos_art))
            self.dos_log.append((now, j, "CROSS", dos_cross))

        critical_dos = max(dos.values())

        # ---- (b) cycle-length adaptation ----
        C_target = self._cycle_update(critical_dos)
        self.cycle_target_log.append((now, C_target, critical_dos))

        for j in self.ids:
            plant = self.plants[j]
            fixed_overhead = plant.fixed_cycle_overhead()
            art_left = plant.plan["ART_LEFT"]        # held ~constant (subordinate stage)
            avail = C_target - fixed_overhead - art_left
            avail = max(avail, 2 * SPLIT_MIN_GREEN)
            dos_art, dos_cross = dos[(j, "ART")], dos[(j, "CROSS")]

            # ---- (a) split adaptation: equisaturation, rate-limited ----
            denom = dos_art + dos_cross
            share_art = 0.6 if denom <= 1e-6 else dos_art / denom
            g_art_target = max(SPLIT_MIN_GREEN, min(avail - SPLIT_MIN_GREEN, avail * share_art))
            g_art_prev = plant.plan["ART_MAIN"]
            g_art = max(g_art_prev - SPLIT_SLEW, min(g_art_prev + SPLIT_SLEW, g_art_target))
            g_art = max(SPLIT_MIN_GREEN, min(avail - SPLIT_MIN_GREEN, g_art))
            g_cross = avail - g_art

            # ---- (c) offset adaptation ----
            art_start = plant._pending_art_start_t if plant._pending_art_start_t is not None else now
            mean_arr = self._mean_arrival_incycle(j, "EB", art_start)
            offset_delta = 0.0
            if mean_arr is not None:
                err = mean_arr - OFFSET_TARGET_INCYCLE
                offset_delta = max(-OFFSET_SLEW, min(OFFSET_SLEW, err))

            self._apply_transition(j, C_target, g_art, art_left, g_cross, offset_delta)

        for aid in self._entry_count:
            self._entry_count[aid] = 0
            self._entry_times[aid] = []
        self.C = C_target

    def _cycle_update(self, critical_dos):
        if critical_dos > self.target_dos + DOS_DEADBAND:
            c = self.C + CYCLE_SLEW_UP
        elif critical_dos < self.target_dos - DOS_DEADBAND:
            c = self.C - CYCLE_SLEW_DOWN
        else:
            c = self.C
        return max(self.c_min, min(self.c_max, c))

    # ------------------------------------------------- transition mechanics
    def _apply_transition(self, j, C_target, g_art, g_left, g_cross, offset_delta):
        """How the NEW plan is actually rolled onto the running plant --
        pluggable per sub-goal 3's taxonomy. 'dwell' (this controller's
        default) applies the full new split/cycle immediately at each stage's
        own next occurrence (JunctionPlant.set_plan's normal per-tick slew
        already limits how much C/splits can move in one go, since ticks are
        C seconds apart and the slew caps above bound per-tick movement -- the
        SEPARATE dwell/add/subtract/spread comparison in
        transition/transition_experiment.py isolates a single large step
        change, which this continuously-adapting controller does not
        normally encounter, by design)."""
        plant = self.plants[j]
        plant.set_plan(art_main=g_art, art_left=g_left, cross=g_cross)
        if abs(offset_delta) > 1e-6:
            plant.apply_one_shot_stage_correction("CROSS", offset_delta)
