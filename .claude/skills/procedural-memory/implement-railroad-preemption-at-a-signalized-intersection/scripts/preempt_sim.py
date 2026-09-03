#!/usr/bin/env python3
"""
MUTCD/ITE railroad preemption of a nearby signalized intersection, in SUMO.

Runs ONE configuration (demand level x train headway x advance preemption time
x preemption on/off) and writes everything needed to re-derive every number:

  fsm_log.json      every controller state transition with timestamp + the
                    actual TLS state string that was written
  events.json       one record per gate-down event: track occupancy at the
                    gate-down instant, trapped-vehicle durations, queues,
                    predicted-vs-actual gate-down time
  timeseries.csv    per-second X state, J state, controller state, occupancy,
                    per-approach halting counts
  tripinfo.xml      per-vehicle delay (SUMO)
  detector.out.xml  E1 stop-bar detector on the EB approach (saturation
                    headway / discharge measurement)
  edgedata.out.xml  aggregated per-edge delay

CONTROLLER -- the full ITE preemption sequence as a state machine:

  NORMAL
    -> (preempt call, APT seconds before predicted gate-down)
  PED_HOLD        truncate the concurrent pedestrian interval DOWN TO its legal
                  minimum (WALK 7 s + FDW 6 s = 13 s), never below
  ROW_YELLOW      right-of-way transfer: terminate only the movements that must
                  lose green, honouring the minimum yellow (3 s).  A movement
                  that is green in the target state KEEPS its green.
  ROW_ALLRED      minimum red clearance (2 s) for the terminated movements
  TRACK_CLEAR     track clearance green: EB only -- the approach lying across
                  the tracks -- discharging toward the downstream signal.
                  Held for at least tcg_min AND until the gate is actually down.
  TC_YELLOW / TC_ALLRED     clearance out of the track clearance green
  DWELL           limited service: NS through only.  These movements do NOT
                  feed any vehicle back toward the crossing.  Held for the
                  whole gate-down period.
  EXIT_YELLOW / EXIT_ALLRED -> NORMAL (setProgram back to the native plan)
"""
import argparse
import csv
import json
import os
import sys

sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import traci  # noqa: E402
import common as C  # noqa: E402

APPROACHES = {"EB_across_tracks": "X_J", "WB_feeds_crossing": "E_J",
              "NB_cross_street": "JS_J", "SB_cross_street": "JN_J",
              "EB_upstream_of_crossing": "W_X"}


class PreemptFSM:
    def __init__(self, tr, apt, tcg_min, enabled, log):
        self.tr, self.apt, self.tcg_min, self.enabled, self.log = tr, apt, tcg_min, enabled, log
        self.st = "NORMAL"
        self.t_end = 0.0
        self.armed_for = None       # train id this cycle belongs to
        self.done_trains = set()
        self.t_call = None
        self.tc_start = None
        self.n_preempts = 0
        self.gate_seen_down = False   # has the gate actually dropped since the call?
        self.tcg_cap = 90.0           # hard cap so a mispredicted call cannot hang

    def _set(self, s):
        self.tr.trafficlight.setRedYellowGreenState("J", s)

    def _go(self, now, newst, state_str, hold=None, **kw):
        if state_str is not None:
            self._set(state_str)
        self.st = newst
        if hold is not None:
            self.t_end = now + hold
        rec = {"t": now, "state": newst, "tls_state": state_str}
        rec.update(kw)
        self.log.append(rec)

    @staticmethod
    def _terminating(cur, target):
        return [i for i in range(len(cur))
                if cur[i] in ("G", "g") and target[i] == "r"]

    def _yellow_state(self, cur, target):
        out = []
        for i, c in enumerate(cur):
            if c in ("G", "g") and target[i] == "r":
                out.append("y")
            elif c in ("G", "g"):
                out.append(c)          # continuing green is NOT dropped
            elif c == "y":
                out.append("y")
            else:
                out.append("r")
        return "".join(out)

    @staticmethod
    def _clearance_state(cur_yellow, target):
        """Terminated movements go red; movements green in the target and
        already green keep their green (no unnecessary all-red)."""
        return "".join(target[i] if cur_yellow[i] not in ("G", "g") else cur_yellow[i]
                       for i in range(len(cur_yellow)))

    def step(self, now, pred_gd, train_id, gate_down):
        tr = self.tr
        if not self.enabled:
            return
        if gate_down:
            self.gate_seen_down = True
        if self.st == "NORMAL":
            if train_id is None or train_id in self.done_trains or pred_gd is None:
                return
            if pred_gd - now > self.apt:
                return
            # ---- (i) PREEMPT CALL -------------------------------------------
            self.armed_for = train_id
            self.t_call = now
            self.gate_seen_down = False
            self.n_preempts += 1
            cur = tr.trafficlight.getRedYellowGreenState("J")
            ph = tr.trafficlight.getPhase("J")
            spent = tr.trafficlight.getSpentDuration("J")
            ped_rem = 0.0
            if ph in (C.PH_EW_G, C.PH_NS_G):
                ped_rem = max(0.0, C.PED_MIN_TOTAL - spent)
            self.log.append({"t": now, "state": "PREEMPT_CALL", "tls_state": cur,
                             "train": train_id, "predicted_gate_down": round(pred_gd, 2),
                             "advance_time_requested": self.apt,
                             "native_phase": ph, "spent_in_phase": round(spent, 2),
                             "ped_min_total": C.PED_MIN_TOTAL,
                             "ped_hold_remaining": round(ped_rem, 2)})
            if ped_rem > 0:
                self._go(now, "PED_HOLD", cur, hold=ped_rem,
                         note="pedestrian interval truncated to its legal minimum, not below")
            else:
                self._begin_row(now)
            return

        if self.st == "PED_HOLD":
            if now >= self.t_end:
                self._begin_row(now)
            return

        if self.st == "ROW_YELLOW":
            if now >= self.t_end:
                cur = tr.trafficlight.getRedYellowGreenState("J")
                s = self._clearance_state(cur, C.TRACK_CLEAR_STATE)
                self._go(now, "ROW_ALLRED", s, hold=C.ALLRED_MIN,
                         note="minimum red clearance for terminated movements")
            return

        if self.st == "ROW_ALLRED":
            if now >= self.t_end:
                self._go(now, "TRACK_CLEAR", C.TRACK_CLEAR_STATE,
                         note="track clearance green: EB discharges the approach lying "
                              "across the tracks")
                self.tc_start = now
            return

        if self.st == "TRACK_CLEAR":
            # Hold the track clearance green for at least tcg_min AND until the
            # gate has actually dropped.  gate_seen_down (not gate_down) is used
            # so a short gate-down that ends before tcg_min elapses does not
            # strand the FSM; tcg_cap bounds a mispredicted call.
            elapsed = now - self.tc_start
            if elapsed >= self.tcg_min and (gate_down or self.gate_seen_down):
                self._go(now, "TC_YELLOW", C.state({"EB": "y"}), hold=C.YELLOW_MIN,
                         track_clear_duration=round(elapsed, 2))
            elif elapsed >= self.tcg_cap:
                self._go(now, "TC_YELLOW", C.state({"EB": "y"}), hold=C.YELLOW_MIN,
                         track_clear_duration=round(elapsed, 2),
                         note="track clearance green capped: gate never dropped "
                              "(preempt call was mispredicted)")
            return

        if self.st == "TC_YELLOW":
            if now >= self.t_end:
                self._go(now, "TC_ALLRED", "r" * C.NLINKS, hold=C.ALLRED_MIN)
            return

        if self.st == "TC_ALLRED":
            if now >= self.t_end:
                self._go(now, "DWELL", C.DWELL_STATE,
                         note="limited service: only movements that do NOT feed the crossing")
            return

        if self.st == "DWELL":
            if not gate_down:  # gate up -> exit
                self._go(now, "EXIT_YELLOW", C.state({"NB": "y", "SB": "y"}),
                         hold=C.YELLOW_MIN, note="gate up, begin exit")
            return

        if self.st == "EXIT_YELLOW":
            if now >= self.t_end:
                self._go(now, "EXIT_ALLRED", "r" * C.NLINKS, hold=C.ALLRED_MIN)
            return

        if self.st == "EXIT_ALLRED":
            if now >= self.t_end:
                tr.trafficlight.setProgram("J", "0")
                tr.trafficlight.setPhase("J", C.PH_EW_G)
                self.done_trains.add(self.armed_for)
                self.log.append({"t": now, "state": "EXIT_DONE",
                                 "tls_state": tr.trafficlight.getRedYellowGreenState("J"),
                                 "train": self.armed_for,
                                 "note": "native program resumed at EW green"})
                self.st = "NORMAL"
                self.armed_for = None
            return

    def _begin_row(self, now):
        cur = self.tr.trafficlight.getRedYellowGreenState("J")
        term = self._terminating(cur, C.TRACK_CLEAR_STATE)
        if term:
            self._go(now, "ROW_YELLOW", self._yellow_state(cur, C.TRACK_CLEAR_STATE),
                     hold=C.YELLOW_MIN, terminating_links=term,
                     note="right-of-way transfer, minimum yellow honoured; "
                          "movements green in the target keep their green")
        elif "y" in cur:
            self._go(now, "ROW_ALLRED", self._clearance_state(cur, C.TRACK_CLEAR_STATE),
                     hold=C.ALLRED_MIN, note="already yellow, go straight to red clearance")
        else:
            self._go(now, "TRACK_CLEAR", C.TRACK_CLEAR_STATE,
                     note="no conflicting green to terminate")
            self.tc_start = now


def write_additional(path, det_out, ed_out):
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<additional>
    <inductionLoop id="eb_stopbar" lane="X_J_0" pos="38.0" period="100000"
                   file="{det_out}"/>
    <edgeData id="ed" file="{ed_out}" begin="0" end="100000"
              excludeEmpty="true"/>
</additional>
"""
    open(path, "w").write(xml)


def run(a):
    os.makedirs(a.outdir, exist_ok=True)
    det_out = os.path.abspath(os.path.join(a.outdir, "detector.out.xml"))
    ed_out = os.path.abspath(os.path.join(a.outdir, "edgedata.out.xml"))
    add = os.path.abspath(os.path.join(a.outdir, "extra.add.xml"))
    write_additional(add, det_out, ed_out)
    rou = os.path.join(C.NET_DIR, f"demand_eb{a.eb}_h{a.headway}.rou.xml")
    cfg = ["sumo", "-n", C.NET_FILE, "-r", rou, "-a", add,
           "--begin", "0", "--end", str(a.end), "--step-length", "1",
           "--seed", str(a.seed), "--no-step-log", "true", "--time-to-teleport", "-1",
           "--tripinfo-output", os.path.abspath(os.path.join(a.outdir, "tripinfo.xml"))]
    traci.start(cfg, label=a.label)
    tr = traci.getConnection(a.label)

    log = []
    fsm = PreemptFSM(tr, a.apt, a.tcg, a.preempt, log)
    rows, events = [], []
    cur_event = None
    prev_gate = False
    trapped = {}          # vid -> first time seen occupying during this gate-down

    while tr.simulation.getTime() < a.end:
        tr.simulationStep()
        now = tr.simulation.getTime()
        gate = C.gate_is_down(tr)
        train = C.nearest_train(tr)
        pred_gd, tid = None, None
        if train and train[2] > 0.1:
            tid = train[0]
            pred_gd = now + train[1] / train[2] - C.RAILCROSSING_TIMEGAP
        fsm.step(now, pred_gd, tid, gate)

        occ = C.occupancy(tr)
        occ_stopped = [v for v, _o, s in occ if s < 0.1]
        occ_m = C.occupancy(tr, C.ENV_LO, C.ENV_HI)
        halts = {k: tr.edge.getLastStepHaltingNumber(e) for k, e in APPROACHES.items()}
        rows.append({"t": now, "X": tr.trafficlight.getRedYellowGreenState("X"),
                     "gate_down": int(gate),
                     "J": tr.trafficlight.getRedYellowGreenState("J"),
                     "ctrl": fsm.st, "occ": len(occ), "occ_stopped": len(occ_stopped),
                     "occ_mutcd": len(occ_m),
                     "occ_ids": " ".join(v for v, _, _ in occ),
                     **{"q_" + k: v for k, v in halts.items()}})

        # ---- gate-down event bookkeeping ----------------------------------
        if gate and not prev_gate:
            cur_event = {
                "t_gate_down": now,
                "occ_at_gate_down": len(occ),
                "occ_stopped_at_gate_down": len(occ_stopped),
                "occ_mutcd_at_gate_down": len(occ_m),
                "occ_ids_at_gate_down": [v for v, _, _ in occ],
                "q_at_gate_down": halts,
                "ctrl_state_at_gate_down": fsm.st,
                "J_state_at_gate_down": tr.trafficlight.getRedYellowGreenState("J"),
                "preempt_call_t": fsm.t_call,
                "achieved_advance_time": (round(now - fsm.t_call, 2)
                                          if fsm.t_call is not None else None),
                "max_q": dict(halts),
            }
            trapped = {v: now for v, _, _ in occ}
        if gate and cur_event is not None:
            for v, _o, _s in occ:
                trapped.setdefault(v, now)
            for k, val in halts.items():
                cur_event["max_q"][k] = max(cur_event["max_q"][k], val)
        if (not gate) and prev_gate and cur_event is not None:
            cur_event["t_gate_up"] = now
            cur_event["gate_down_duration"] = now - cur_event["t_gate_down"]
            still = {v for v, _, _ in occ}
            cur_event["trapped_durations_s"] = {
                v: round((now if v in still else
                          next(r["t"] for r in reversed(rows) if v in r["occ_ids"].split())) - t0, 1)
                for v, t0 in trapped.items()}
            cur_event["n_vehicles_that_occupied_during_gate_down"] = len(trapped)
            events.append(cur_event)
            cur_event = None
            trapped = {}
        prev_gate = gate

    tr.close()

    with open(os.path.join(a.outdir, "fsm_log.json"), "w") as f:
        json.dump(log, f, indent=2)
    with open(os.path.join(a.outdir, "events.json"), "w") as f:
        json.dump(events, f, indent=2)
    with open(os.path.join(a.outdir, "timeseries.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(a.outdir, "config.json"), "w") as f:
        json.dump(vars(a), f, indent=2)
    print(json.dumps({"outdir": a.outdir, "n_gate_events": len(events),
                      "n_preempts": fsm.n_preempts,
                      "occ_at_gate_down": [e["occ_at_gate_down"] for e in events],
                      "occ_stopped_at_gate_down": [e["occ_stopped_at_gate_down"] for e in events]}))
    return events


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--eb", type=int, default=600)
    p.add_argument("--headway", type=int, default=300)
    p.add_argument("--apt", type=float, default=0.0)
    p.add_argument("--tcg", type=float, default=25.0)
    p.add_argument("--preempt", type=int, default=0)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--end", type=int, default=2700)
    p.add_argument("--outdir", required=True)
    p.add_argument("--label", default="default")
    run(p.parse_args())
