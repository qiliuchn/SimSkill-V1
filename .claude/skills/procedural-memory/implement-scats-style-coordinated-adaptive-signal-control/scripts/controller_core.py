"""Generic per-junction TraCI signal state machine shared by every controller
arm in this study (fixed/WAUT-plan holder, actuated-coordinated, and the new
3-layer adaptive controller).

Directly extends the phase-introspection / min-green / yellow+all-red clearance
pattern from `implement-maxpressure-traci-controller`'s `JunctionController`
(see that skill's `scripts/maxpressure_controller.py`): this module reuses the
exact same "never hand-guess the phase-to-movement mapping" discipline
(`getControlledLinks`, searching the program's OWN phase list for the
clearance yellow / all-red rather than assuming a fixed layout) but replaces
max-pressure's per-step *decision rule* with an externally-supplied *plan*
(cycle length C, a duration for every green "stage", and a per-junction
offset) that upstream layers (fixed-time, WAUT, or the adaptive controller)
update from time to time.

STAGE CLASSIFICATION (generic, derived from geometry -- verified against the
compiled net's auto-generated tlLogic for this study's 5x identical junctions):
netconvert's default TLS builder produces exactly 3 green "stages" per
junction on this network's geometry (2 through lanes + 1 exclusive left per
arterial direction, 1 lane each way on the minor/frontage legs):
    stage ART_MAIN  -- both arterial through movements together, permissive
                       left turns riding along (lowercase g)
    stage ART_LEFT  -- both arterial left turns, now protected (uppercase G)
    stage CROSS     -- both minor-street/frontage approaches (through+left+
                       right), fully protected
each followed by its own programmed yellow (and, only where the program
actually contains one, an all-red) phase. A stage is classified CROSS if any
of its green links' FROM edge touches a node whose id starts with "N" or "S"
(this network's cross/frontage legs); otherwise it is ART_MAIN if it contains
any lowercase ('g', permissive) link, else ART_LEFT. This uses only the
compiled net's own connection data -- nothing about a specific junction id is
hardcoded, so the same code drives all 5 (or any future re-spacing).
"""
import os
import sys

SUMO_HOME = os.environ.get("SUMO_HOME") or \
    "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo"
os.environ.setdefault("SUMO_HOME", SUMO_HOME)
sys.path.append(os.path.join(SUMO_HOME, "tools"))
import traci  # noqa: E402

HOLD = 100000.0
ALLRED_CAP = 12.0


def is_green(state):
    return ("G" in state or "g" in state) and "y" not in state


def has_yellow(state):
    return "y" in state


def is_allred(state):
    return ("G" not in state) and ("g" not in state) and ("y" not in state)


class Stage(object):
    __slots__ = ("phase_idx", "kind", "green_links", "in_lanes", "out_lanes",
                 "via_lanes", "base_duration", "yellow_idx", "allred_idx",
                 "min_green", "max_green")

    def __repr__(self):
        return "Stage(phase=%d kind=%s base=%.1f)" % (
            self.phase_idx, self.kind, self.base_duration)


class JunctionPlant(object):
    """Introspects one junction's compiled tlLogic and drives it live via TraCI
    from an externally supplied (cycle, stage-duration, offset) plan, with a
    correct yellow/all-red clearance state machine. Contains NO control
    decision logic itself -- callers (fixed/WAUT/adaptive layers) set the plan;
    this class only guarantees it is applied *safely*.
    """

    def __init__(self, tls_id, min_green=8.0, max_green=None):
        self.tls = tls_id
        logic = traci.trafficlight.getAllProgramLogics(tls_id)[0]
        self.phases = logic.phases
        self.n = len(self.phases)
        links = traci.trafficlight.getControlledLinks(tls_id)

        self.stages = []
        green_idx = [i for i, p in enumerate(self.phases) if is_green(p.state)]
        for gi in green_idx:
            st = Stage()
            st.phase_idx = gi
            st.base_duration = self.phases[gi].duration
            state = self.phases[gi].state
            inc, out, via = set(), set(), set()
            has_lower = False
            cross = False
            for idx, ch in enumerate(state):
                if ch in ("G", "g") and idx < len(links):
                    if ch == "g":
                        has_lower = True
                    for link in links[idx]:
                        if link and link[0]:
                            inc.add(link[0])
                            edge = link[0].rsplit("_", 1)[0]
                            src_node = edge.split("to")[0] if "to" in edge else edge
                            if src_node[:1] in ("N", "S"):
                                cross = True
                        if link and link[1]:
                            out.add(link[1])
                        if link and len(link) > 2 and link[2]:
                            via.add(link[2])
            st.green_links = [idx for idx, ch in enumerate(state) if ch in ("G", "g")]
            st.in_lanes = list(inc)
            st.out_lanes = list(out)
            st.via_lanes = list(via)
            st.kind = "CROSS" if cross else ("ART_MAIN" if has_lower else "ART_LEFT")
            # clearance search (same rule as implement-maxpressure-traci-controller)
            yellow = None
            allred = None
            for step in range(1, self.n + 1):
                j = (gi + step) % self.n
                s2 = self.phases[j].state
                if yellow is None and has_yellow(s2):
                    yellow = j
                    continue
                if yellow is not None:
                    if is_allred(s2):
                        allred = j
                    break
                if j in green_idx:
                    break
            st.yellow_idx = yellow
            st.allred_idx = allred
            st.min_green = min_green
            st.max_green = max_green
            self.stages.append(st)

        self.by_kind = {s.kind: s for s in self.stages}
        assert set(self.by_kind) == {"ART_MAIN", "ART_LEFT", "CROSS"}, \
            "unexpected stage classification at %s: %r" % (tls_id, [s.kind for s in self.stages])
        self.order = sorted(self.stages, key=lambda s: s.phase_idx)

        # runtime state
        self.mode = "GREEN"
        self.cur_i = 0                      # index into self.order
        self.green_since = 0.0
        self.yellow_until = 0.0
        self.allred_min_until = 0.0
        self.allred_cap_until = 0.0
        self.vacating = None
        # the live plan: seconds of GREEN (not incl. its own yellow/allred) per stage
        self.plan = {s.kind: s.base_duration for s in self.stages}
        self.cycle_len = sum(self.plan.values()) + sum(
            (self.phases[s.yellow_idx].duration if s.yellow_idx is not None else 0.0)
            + (self.phases[s.allred_idx].duration if s.allred_idx is not None else 0.0)
            for s in self.stages)
        self.cur_dur_override = None        # this-activation duration (offset warm start / one-shot correction)
        self.n_cycles_completed = 0
        self.cycle_log = []                 # (t_ART_MAIN_green_start, realized_stage_durations dict)
        self._pending_art_start_t = None
        self._stage_open_t = {}

    # ------------------------------------------------------------ lifecycle
    def clearance_time(self, stage):
        t = 0.0
        if stage.yellow_idx is not None:
            t += self.phases[stage.yellow_idx].duration
        if stage.allred_idx is not None:
            t += self.phases[stage.allred_idx].duration
        return t

    def fixed_cycle_overhead(self):
        """Sum of all yellow+allred durations -- these never change."""
        return sum(self.clearance_time(s) for s in self.stages)

    def start(self, now, warm_start_elapsed=0.0):
        """warm_start_elapsed: how far (seconds) into the nominal repeating
        sequence this junction should act as though it already were -- this is
        how per-junction OFFSET is realized (see module docstring): junction j
        is initialised as if its local clock read `-offset_j` at t=0, so its
        first ART_MAIN green begins at `offset_j` (mod C), exactly SUMO's own
        `(t - offset) mod C` tlLogic convention, verified in
        `design-arterial-signal-progression-and-verify-bandwidth`."""
        elapsed = warm_start_elapsed % self.cycle_len
        acc = 0.0
        for i, s in enumerate(self.order):
            g = self.plan[s.kind]
            c = self.clearance_time(s)
            if acc + g + c > elapsed or i == len(self.order) - 1:
                # this is where we land
                self.cur_i = i
                into = elapsed - acc
                if into < g:
                    self.mode = "GREEN"
                    self.green_since = now - into
                    traci.trafficlight.setPhase(self.tls, s.phase_idx)
                elif s.yellow_idx is not None and into < g + self.phases[s.yellow_idx].duration:
                    self.mode = "YELLOW"
                    self.yellow_until = now + (g + self.phases[s.yellow_idx].duration - into)
                    self.vacating = s
                    traci.trafficlight.setPhase(self.tls, s.yellow_idx)
                elif s.allred_idx is not None:
                    self.mode = "ALLRED"
                    left = g + c - into
                    self.allred_min_until = now + left
                    self.allred_cap_until = now + left
                    self.vacating = s
                    traci.trafficlight.setPhase(self.tls, s.allred_idx)
                else:
                    self.mode = "GREEN"
                    self.cur_i = (i + 1) % len(self.order)
                    self.green_since = now
                    traci.trafficlight.setPhase(self.tls, self.order[self.cur_i].phase_idx)
                traci.trafficlight.setPhaseDuration(self.tls, HOLD)
                if self.order[self.cur_i].kind == "ART_MAIN" and self.mode == "GREEN":
                    self._pending_art_start_t = self.green_since
                return
            acc += g + c

    def set_plan(self, art_main=None, art_left=None, cross=None):
        """Update the (green-only) durations that will apply from the NEXT
        occurrence of each stage onward -- takes effect at that stage's own
        next start, matching real coordinated-controller practice (a plan
        change adopted at each stage's own next opportunity, not instantaneous
        network-wide)."""
        if art_main is not None:
            self.plan["ART_MAIN"] = art_main
        if art_left is not None:
            self.plan["ART_LEFT"] = art_left
        if cross is not None:
            self.plan["CROSS"] = cross
        self.cycle_len = sum(self.plan.values()) + self.fixed_cycle_overhead()

    def apply_one_shot_stage_correction(self, kind, delta):
        """Add `delta` seconds (may be negative, floored at min_green) to the
        NEXT single occurrence only of stage `kind` -- the mechanism used by
        offset-adaptation and by the transition-method study (dwell / add-only
        / subtract-only / spread-over-N all reduce to a sequence of these
        one-shot corrections applied to the CROSS stage, which is the
        standard real-controller practice of never perturbing the coordinated
        phase itself, only the subordinate stage, to shift downstream cycle
        timing)."""
        self._one_shot = (kind, delta)

    # ---------------------------------------------------------------- step
    def step(self, now):
        s = self.order[self.cur_i]
        if self.mode == "GREEN":
            g = self.plan[s.kind]
            oneshot = getattr(self, "_one_shot", None)
            extra = 0.0
            if oneshot and oneshot[0] == s.kind:
                extra = oneshot[1]
                self._one_shot = None
            g_eff = max(s.min_green, g + extra)
            if s.max_green is not None:
                g_eff = min(g_eff, s.max_green)
            if now - self.green_since < g_eff:
                return
            # go to yellow
            if s.yellow_idx is not None:
                traci.trafficlight.setPhase(self.tls, s.yellow_idx)
                traci.trafficlight.setPhaseDuration(self.tls, HOLD)
                self.mode = "YELLOW"
                self.yellow_until = now + self.phases[s.yellow_idx].duration
                self.vacating = s
            else:
                self._advance(now)
            return
        if self.mode == "YELLOW":
            if now >= self.yellow_until:
                s2 = self.vacating
                if s2.allred_idx is not None:
                    traci.trafficlight.setPhase(self.tls, s2.allred_idx)
                    traci.trafficlight.setPhaseDuration(self.tls, HOLD)
                    self.mode = "ALLRED"
                    self.allred_min_until = now + self.phases[s2.allred_idx].duration
                    self.allred_cap_until = now + ALLRED_CAP
                else:
                    self._advance(now)
            return
        if self.mode == "ALLRED":
            s2 = self.vacating
            past_min = now >= self.allred_min_until
            past_cap = now >= self.allred_cap_until
            clear = all(traci.lane.getLastStepVehicleNumber(l) == 0 for l in s2.via_lanes) \
                if s2.via_lanes else True
            if past_cap or (past_min and clear):
                self._advance(now)
            return

    def _advance(self, now):
        prev = self.order[self.cur_i]
        if prev.kind == "ART_MAIN" and self._pending_art_start_t is not None:
            self.cycle_log.append((self._pending_art_start_t, now,
                                   dict(self.plan), self.cycle_len))
            self.n_cycles_completed += 1
        self.cur_i = (self.cur_i + 1) % len(self.order)
        nxt = self.order[self.cur_i]
        traci.trafficlight.setPhase(self.tls, nxt.phase_idx)
        traci.trafficlight.setPhaseDuration(self.tls, HOLD)
        self.mode = "GREEN"
        self.green_since = now
        if nxt.kind == "ART_MAIN":
            self._pending_art_start_t = now
