"""
GLOSA (Green Light Optimal Speed Advisory) eco-driving controller, driven live
via TraCI, plus a scenario runner that emits tripinfo (with emissions), a
per-step summary, per-edge emissions/traffic edgeData, aggregate smoothness
stats, and per-vehicle speed trajectories.

Controller pattern (the reusable GLOSA core)
--------------------------------------------
For each EQUIPPED vehicle every step:
  1. nxt = traci.vehicle.getNextTLS(veh) -> [(tlsID, linkIndex, dist, state), ...].
     Take the nearest upcoming traffic light (nxt[0]). linkIndex is the vehicle's
     own link position within that TLS's RYG state string.
  2. If there is no TLS ahead, or the nearest one is beyond the advisory horizon,
     or the vehicle is right at the stop line (dist < clear_dist), RELEASE control
     with setSpeed(-1) so normal car-following resumes (and so it clears the
     junction naturally).
  3. Otherwise, build the upcoming green schedule for THIS vehicle's link:
     getNextSwitch(tls) gives when the current phase ends; getAllProgramLogics
     gives every phase's state+duration, so we walk phases forward (~2 cycles),
     reading char[linkIndex] of each phase state to know when this movement is
     GREEN. getNextTLS/getNextSwitch alone do NOT tell you "when it turns green" --
     that is derived here from the phase list.
  4. Decision rule -> a target approach speed:
       - Search green windows in arrival order. A green window [gs,ge] is
         *catchable* if a constant speed in [v_min, v_max] lands the vehicle
         inside it: the reachable arrival interval [now+dist/v_max, now+dist/v_min]
         must overlap [gs,ge]. For the earliest catchable window, aim to arrive as
         early as physically possible but not before green (target_arr =
         max(gs+margin, now+dist/v_max)); advise speed = dist/(target_arr-now),
         clamped to [v_min, v_max]. This one rule covers BOTH cases GLOSA needs:
         if the current phase is green but will end before arrival, the earliest
         catchable window forces a *higher* speed (up to v_max) to catch it; if
         red, the earliest catchable window is the next green and the rule yields
         a *lower glide* speed so the vehicle arrives as it turns green instead of
         stopping.
       - If NO green is catchable within the lookahead (green is too far to reach
         even at v_min without arriving early, or unreachable even at v_max), the
         vehicle must stop, so advise a COMFORTABLE glide-to-stop:
         v = sqrt(2 * a_comf * max(dist - stop_buffer, 0)), capped by current speed
         -- a smooth deceleration profile that reaches ~0 at the stop line rather
         than a hard brake.
  5. Apply with traci.vehicle.setSpeed(veh, target). Speed mode is left at SUMO's
     DEFAULT (bitset 31 = all safety checks ON): car-following safe-speed and
     red-light braking still cap the commanded speed, so the advisory can never
     cause a collision or run a red -- it only ever lowers the effective speed, or
     raises the *target* up to the limit while safety still governs the realized
     speed. No safety bit needs to be disabled for this controller to work.

Usage:
    python glosa_controller.py --net NET --routes ROU --outdir DIR \
        --penetration 1.0 --seed 1 [--track-file ids.txt]
    penetration 0.0 == baseline (no vehicle is ever equipped) -- use this to run
    a fair control scenario through the identical stepping loop.
"""
import argparse
import csv
import json
import math
import os
import sys

SUMO_HOME = os.environ["SUMO_HOME"]
sys.path.append(os.path.join(SUMO_HOME, "tools"))
import traci  # noqa: E402


def hash_equipped(veh_id, penetration):
    """Deterministic per-vehicle equip decision (stable across runs at the same penetration)."""
    if penetration >= 1.0:
        return True
    if penetration <= 0.0:
        return False
    h = abs(hash(("glosa", veh_id))) % 1000
    return h < penetration * 1000


class GlosaController:
    def __init__(self, horizon, v_min, v_max_cap, a_comf, clear_dist, margin, stop_buffer, penetration):
        self.horizon = horizon
        self.v_min = v_min
        self.v_max_cap = v_max_cap
        self.a_comf = a_comf
        self.clear_dist = clear_dist
        self.margin = margin
        self.stop_buffer = stop_buffer
        self.penetration = penetration
        self._logic_cache = {}  # tlsID -> phases list
        self.controlled = set()  # veh ids currently under setSpeed control
        self.equipped = {}  # veh id -> bool (memoized)

    def _phases(self, tls):
        if tls not in self._logic_cache:
            self._logic_cache[tls] = traci.trafficlight.getAllProgramLogics(tls)[0].phases
        return self._logic_cache[tls]

    def _green_windows(self, tls, link_idx, now):
        phases = self._phases(tls)
        n = len(phases)
        cur = traci.trafficlight.getPhase(tls)
        next_switch = traci.trafficlight.getNextSwitch(tls)
        windows = []
        i = cur
        t0 = now
        t_end = next_switch
        for _ in range(2 * n + 2):  # look ~2 cycles ahead
            state = phases[i].state
            ch = state[link_idx] if link_idx < len(state) else "r"
            windows.append((t0, t_end, ch in ("G", "g")))
            i = (i + 1) % n
            t0 = t_end
            t_end = t0 + phases[i].duration
        return windows

    def _advise(self, veh, tls, link_idx, dist, now):
        v = traci.vehicle.getSpeed(veh)
        lane = traci.vehicle.getLaneID(veh)
        try:
            lane_lim = traci.lane.getMaxSpeed(lane)
        except traci.TraCIException:
            lane_lim = self.v_max_cap
        v_max = min(self.v_max_cap, lane_lim, traci.vehicle.getMaxSpeed(veh))
        v_min = min(self.v_min, v_max)

        windows = self._green_windows(tls, link_idx, now)
        t_fast = now + dist / v_max
        t_slow = now + dist / v_min if v_min > 0.1 else float("inf")
        for gs, ge, is_green in windows:
            if not is_green:
                continue
            lo = max(t_fast, gs)
            hi = min(t_slow, ge)
            if lo <= hi:  # a feasible constant speed catches this green
                target_arr = max(gs + self.margin, t_fast)
                if target_arr > ge:
                    continue
                spd = dist / max(target_arr - now, 1e-3)
                return max(v_min, min(v_max, spd))
        # No catchable green -> comfortable glide to a stop at the line
        glide = math.sqrt(2.0 * self.a_comf * max(dist - self.stop_buffer, 0.0))
        return min(v, glide) if v > 0 else glide

    def step(self, now):
        depart_ids = traci.simulation.getDepartedIDList()
        for vid in depart_ids:
            self.equipped[vid] = hash_equipped(vid, self.penetration)
        for vid in list(self.controlled):  # release any that have left
            if vid not in traci.vehicle.getIDList():
                self.controlled.discard(vid)

        for veh in traci.vehicle.getIDList():
            if not self.equipped.get(veh, False):
                continue
            nxt = traci.vehicle.getNextTLS(veh)
            if not nxt:
                if veh in self.controlled:
                    traci.vehicle.setSpeed(veh, -1)
                    self.controlled.discard(veh)
                continue
            tls, link_idx, dist, _state = nxt[0]
            if dist > self.horizon or dist < self.clear_dist:
                if veh in self.controlled:
                    traci.vehicle.setSpeed(veh, -1)  # release: out of horizon or clearing junction
                    self.controlled.discard(veh)
                continue
            target = self._advise(veh, tls, link_idx, dist, now)
            if veh not in self.controlled:
                traci.vehicle.setSpeedMode(veh, 31)  # explicit: keep ALL safety checks on
                self.controlled.add(veh)
            traci.vehicle.setSpeed(veh, target)


def load_track_ids(path):
    if not path or not os.path.isfile(path):
        return set()
    with open(path) as f:
        return set(line.strip() for line in f if line.strip())


def run(args):
    outdir = args.outdir
    os.makedirs(outdir, exist_ok=True)
    tripinfo = os.path.join(outdir, "tripinfo.xml")
    summary = os.path.join(outdir, "summary.xml")
    edge_add = os.path.join(outdir, "edgedata.add.xml")
    with open(edge_add, "w") as f:
        f.write(
            "<additional>\n"
            '  <edgeData id="emi" type="emissions" file="edgedata_emissions.xml" period="3600" begin="0"/>\n'
            '  <edgeData id="traf" type="traffic" file="edgedata_traffic.xml" period="3600" begin="0"/>\n'
            "</additional>\n"
        )

    import shutil
    sumo = shutil.which("sumo") or os.path.join(SUMO_HOME, "bin", "sumo")
    if not os.path.isfile(sumo):
        cand = os.path.join(SUMO_HOME, "..", "..", "bin", "sumo")
        if os.path.isfile(cand):
            sumo = cand
    cmd = [
        sumo, "-n", args.net, "-r", args.routes,
        "--additional-files", edge_add,  # NOTE: don't also load a vTypes additional file here --
        # duarouter already embedded the vType (with all its params) into --routes, and loading
        # it again from a separate file raises a duplicate-vType-id error.
        "--tripinfo-output", tripinfo,
        "--tripinfo-output.write-unfinished", "true",
        "--summary-output", summary,
        "--device.emissions.probability", "1.0",
        "--no-step-log", "true",
        "--duration-log.statistics", "true",
        "--time-to-teleport", "300",
        "--seed", str(args.seed),
        "--step-length", str(args.step_length),
    ]
    traci.start(cmd)

    ctrl = GlosaController(
        horizon=args.horizon, v_min=args.v_min, v_max_cap=args.v_max,
        a_comf=args.a_comf, clear_dist=args.clear_dist, margin=args.margin,
        stop_buffer=args.stop_buffer, penetration=args.penetration,
    )

    track_ids = load_track_ids(args.track_file)
    traj_rows = []
    prev_speed = {}
    dt = args.step_length
    hard_decel_count = 0
    sum_v = 0.0
    sum_v2 = 0.0
    n_samples = 0
    hard_thresh = args.hard_decel  # m/s^2 (magnitude)

    steps = 0
    while traci.simulation.getMinExpectedNumber() > 0 and steps < args.max_steps:
        traci.simulationStep()
        steps += 1
        now = traci.simulation.getTime()
        ctrl.step(now)

        veh_ids = traci.vehicle.getIDList()
        for veh in veh_ids:
            v = traci.vehicle.getSpeed(veh)
            sum_v += v
            sum_v2 += v * v
            n_samples += 1
            pv = prev_speed.get(veh)
            if pv is not None:
                a = (v - pv) / dt
                if a < -hard_thresh:
                    hard_decel_count += 1
            prev_speed[veh] = v
            if veh in track_ids:
                traj_rows.append((veh, now, v, traci.vehicle.getDistance(veh), traci.vehicle.getLanePosition(veh)))
        gone = set(prev_speed) - set(veh_ids)
        for g in gone:
            prev_speed.pop(g, None)

    finished_at = traci.simulation.getTime()
    traci.close()

    traj_path = os.path.join(outdir, "trajectories.csv")
    with open(traj_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["veh", "time", "speed", "distance", "lanepos"])
        w.writerows(traj_rows)

    speed_var = (sum_v2 / n_samples) - (sum_v / n_samples) ** 2 if n_samples else 0.0
    stats = {
        "penetration": args.penetration,
        "sim_end_time": finished_at,
        "steps": steps,
        "hard_decel_count": hard_decel_count,
        "hard_decel_threshold_mps2": hard_thresh,
        "network_speed_variance": speed_var,
        "network_mean_speed": (sum_v / n_samples) if n_samples else 0.0,
        "veh_step_samples": n_samples,
        "params": {
            "horizon_m": args.horizon, "v_min": args.v_min, "v_max": args.v_max,
            "a_comf": args.a_comf, "clear_dist": args.clear_dist,
            "margin_s": args.margin, "stop_buffer_m": args.stop_buffer,
            "step_length": args.step_length,
        },
    }
    with open(os.path.join(outdir, "run_stats.json"), "w") as f:
        json.dump(stats, f, indent=2)
    print(f"[penetration={args.penetration}] done: end={finished_at:.0f}s steps={steps} "
          f"hard_decels={hard_decel_count} speed_var={speed_var:.3f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Run one GLOSA (or baseline) scenario and collect stats.")
    ap.add_argument("--net", required=True)
    ap.add_argument("--routes", required=True, help="Routes with the emissions-enabled vType already embedded (e.g. duarouter output)")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--penetration", type=float, default=1.0, help="Fraction of vehicles equipped with GLOSA, 0.0-1.0 (0.0 = baseline)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--step-length", type=float, default=1.0)
    ap.add_argument("--horizon", type=float, default=250.0, help="advisory horizon (m)")
    ap.add_argument("--v-min", type=float, default=5.0, help="min advisory speed (m/s) -- too low a value can clog the corridor at high penetration")
    ap.add_argument("--v-max", type=float, default=13.89, help="max advisory speed cap (m/s)")
    ap.add_argument("--a-comf", type=float, default=1.5, help="comfortable decel (m/s^2)")
    ap.add_argument("--clear-dist", type=float, default=5.0, help="release when within this of stop line (m)")
    ap.add_argument("--margin", type=float, default=2.0, help="arrival margin into green (s)")
    ap.add_argument("--stop-buffer", type=float, default=3.0, help="glide stop buffer before line (m)")
    ap.add_argument("--hard-decel", type=float, default=3.0, help="hard-braking threshold magnitude (m/s^2)")
    ap.add_argument("--max-steps", type=int, default=100000)
    ap.add_argument("--track-file", default=None, help="file with vehicle ids (one per line) to log trajectories for")
    run(ap.parse_args())
