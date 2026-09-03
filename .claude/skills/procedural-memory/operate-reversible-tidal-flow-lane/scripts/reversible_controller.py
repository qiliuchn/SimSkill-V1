#!/usr/bin/env python3
"""Reversible (tidal-flow / contraflow) lane controller for SUMO, encoding B.

Implements a REAL changeover transition rather than an instantaneous permission
flip, and instruments it well enough to prove the transition is sound:

  1  STOP ADMITTING  close the losing direction's representation of the
                     reversible lane on the UPSTREAM-MOST facility edge, so no
                     vehicle can enter the lane at the facility entrance.
  2  SWEEP           cascade the closure downstream edge by edge: as soon as
                     level k is verifiably empty (including the internal
                     junction connector lanes it feeds), close level k+1.  A
                     closed level cannot be re-entered laterally, so the swept
                     region only grows.
  3  GRANT           when every level of the losing direction is empty AND the
                     nominal dead time has elapsed, open the gaining direction's
                     representation of the same physical lane.

Policies
  A        static 3+3, no reversal
  B        fixed time-of-day schedule (--schedule t:config,...)
  C        demand-responsive, E2 directional occupancy + hysteresis + min dwell
  broken   DELIBERATELY BROKEN positive control: instantaneous flip, no sweep

Verification instruments written for every run
  <out>/changeover_log.json   one record per changeover: t_request, t_grant,
                              measured clearance, per-level occupancy at grant
  <out>/headon_scan.json      whole-run scan for opposing-direction vehicles
                              simultaneously on the same PHYSICAL lane
  <out>/config_trace.csv      configuration + directional occupancy every 10 s
"""
import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (TOOLS, DIR_EDGES, PHYS_LANES, REVERSIBLE, PERMANENT, CONFIGS,
                    assignment, lane_id, OPEN_CLASSES, CLOSED_CLASSES, n_lanes)

sys.path.append(TOOLS)
import traci  # noqa: E402

OTHER = {"EB": "WB", "WB": "EB"}


# --------------------------------------------------------------------------
def net_internal_lanes(netfile):
    """(direction, phys) -> list of internal lane ids carrying that physical
    lane through the two terminal junctions."""
    root = ET.parse(netfile).getroot()
    conns = [c.attrib for c in root.findall("connection")]
    out = {}
    for d in ("EB", "WB"):
        edges = DIR_EDGES[d]
        for phys in PHYS_LANES:
            vias = []
            for a, b in zip(edges[:-1], edges[1:]):
                lid = lane_id(d, a, phys)
                fe, fi = lid.rsplit("_", 1)
                for c in conns:
                    if c.get("from") == fe and c.get("fromLane") == fi and c.get("to") == b:
                        if c.get("via"):
                            vias.append(c["via"])
            out[(d, phys)] = vias
    return out


class Facility:
    """Lane bookkeeping + the permission primitives."""

    def __init__(self, netfile):
        self.internal = net_internal_lanes(netfile)

    def levels(self, direction, phys):
        """Cascade levels, upstream -> downstream.  Each level is
        (normal_lane_id, [internal lane ids fed by it])."""
        edges = DIR_EDGES[direction]
        vias = self.internal[(direction, phys)]
        lv = []
        for i, e in enumerate(edges):
            lv.append((lane_id(direction, e, phys),
                       [vias[i]] if i < len(vias) else []))
        return lv

    def all_lane_ids(self, direction, phys):
        lv = self.levels(direction, phys)
        ids = []
        for n, iv in lv:
            ids.append(n)
            ids.extend(iv)
        return ids

    @staticmethod
    def open_lane(lid):
        traci.lane.setAllowed(lid, OPEN_CLASSES)

    @staticmethod
    def close_lane(lid):
        traci.lane.setAllowed(lid, CLOSED_CLASSES)

    def set_direction_lane(self, direction, phys, open_it):
        for lid in self.all_lane_ids(direction, phys):
            (self.open_lane if open_it else self.close_lane)(lid)

    @staticmethod
    def count_on(lids):
        return sum(traci.lane.getLastStepVehicleNumber(l) for l in lids)

    @staticmethod
    def veh_on(lids):
        out = []
        for l in lids:
            out.extend(traci.lane.getLastStepVehicleIDs(l))
        return out


class Changeover:
    """State machine for reversing ONE physical lane."""

    def __init__(self, fac, phys, loser, gainer, t, dead_time, broken=False):
        self.fac, self.phys = fac, phys
        self.loser, self.gainer = loser, gainer
        self.t_request = t
        self.dead_time = dead_time
        self.broken = broken
        self.levels = fac.levels(loser, phys)
        self.level_closed = -1
        self.level_clear_times = {}
        self.done = False
        self.t_grant = None
        self.grant_occupancy = None
        self.max_residual = 0
        if broken:
            # positive control: close the loser and open the gainer in the SAME
            # step, with no sweep at all
            fac.set_direction_lane(loser, phys, False)
            self.residual_at_flip = fac.count_on(fac.all_lane_ids(loser, phys))
            fac.set_direction_lane(gainer, phys, True)
            self.t_grant = t
            self.grant_occupancy = self._occ_snapshot()
            self.done = True
        else:
            # who is on the lane when the sweep starts, and how do they leave?
            self.cohort = set(fac.veh_on(fac.all_lane_ids(loser, phys)))
            self.cohort_n = len(self.cohort)
            self.exit_lateral = 0     # moved sideways onto an adjacent lane
            self.exit_downstream = 0  # drove off the end of the facility
            self.exit_other = 0
            self._close_level(0)
            self.residual_at_flip = None

    def _close_level(self, k):
        lid, ivs = self.levels[k]
        Facility.close_lane(lid)
        for iv in ivs:
            Facility.close_lane(iv)
        self.level_closed = k

    def _level_ids(self, k):
        lid, ivs = self.levels[k]
        return [lid] + ivs

    def _occ_snapshot(self):
        snap = {}
        for d in (self.loser, self.gainer):
            for lid in self.fac.all_lane_ids(d, self.phys):
                snap[lid] = traci.lane.getLastStepVehicleNumber(lid)
        return snap

    def step(self, t):
        if self.done:
            return False
        lane_ids = set(self.fac.all_lane_ids(self.loser, self.phys))
        on_now = set(self.fac.veh_on(list(lane_ids)))
        # classify how each cohort member left the reversible lane
        left = self.cohort - on_now
        if left:
            alive = set(traci.vehicle.getIDList())
            for v in left:
                if v not in alive:
                    self.exit_downstream += 1
                else:
                    ln = traci.vehicle.getLaneID(v)
                    if ln in lane_ids:
                        continue
                    if ln.startswith(":") or ln == "":
                        self.exit_other += 1
                    elif ln.split("_")[0] in DIR_EDGES[self.loser] or \
                            ln.rsplit("_", 1)[0] in DIR_EDGES[self.loser]:
                        self.exit_lateral += 1
                    else:
                        self.exit_downstream += 1
            self.cohort -= left
        resid = len(on_now)
        self.max_residual = max(self.max_residual, resid)
        k = self.level_closed
        if self.fac.count_on(self._level_ids(k)) == 0:
            self.level_clear_times.setdefault(k, t)
            if k + 1 < len(self.levels):
                self._close_level(k + 1)
                return False
            # every level closed and the last one is empty -> full sweep done
            if resid == 0 and (t - self.t_request) >= self.dead_time:
                self.grant_occupancy = self._occ_snapshot()
                self.fac.set_direction_lane(self.gainer, self.phys, True)
                self.t_grant = t
                self.done = True
                return True
        return False

    def record(self):
        return dict(phys=self.phys, loser=self.loser, gainer=self.gainer,
                    t_request=self.t_request, t_grant=self.t_grant,
                    clearance_s=None if self.t_grant is None else self.t_grant - self.t_request,
                    dead_time_setting=self.dead_time,
                    broken=self.broken,
                    max_residual_vehicles_during_sweep=self.max_residual,
                    residual_at_instant_flip=self.residual_at_flip,
                    cohort_on_lane_at_sweep_start=getattr(self, "cohort_n", None),
                    cohort_left_by_lane_change=getattr(self, "exit_lateral", None),
                    cohort_left_downstream_exit=getattr(self, "exit_downstream", None),
                    cohort_left_other=getattr(self, "exit_other", None),
                    level_clear_times=self.level_clear_times,
                    occupancy_at_grant=self.grant_occupancy,
                    occupancy_at_grant_total=None if self.grant_occupancy is None
                    else sum(self.grant_occupancy.values()))


# --------------------------------------------------------------------------
class HeadOnScanner:
    """Whole-run scan for opposing vehicles on the SAME physical lane.

    The two directional representations of a physical lane are geometrically
    coincident (verified in geometry_verification.json) but belong to different
    SUMO edges, so SUMO itself never treats them as conflicting.  This scan is
    therefore the only instrument that can see a head-on exposure at all.
    """

    def __init__(self, fac):
        self.fac = fac
        self.events = []
        self.n_steps_with_exposure = 0
        self.min_gap = float("inf")
        self.min_ttc = float("inf")
        self.overlap_pairs = 0
        self.max_pairs = 0

    def step(self, t):
        exposure = False
        for phys in PHYS_LANES:
            eb = self.fac.veh_on([lane_id("EB", e, phys) for e in DIR_EDGES["EB"]])
            if not eb:
                continue
            wb = self.fac.veh_on([lane_id("WB", e, phys) for e in DIR_EDGES["WB"]])
            if not wb:
                continue
            exposure = True
            pairs = 0
            worst = dict(gap=float("inf"), ttc=float("inf"), overlap=0)
            for a in eb:
                xa = traci.vehicle.getPosition(a)[0]
                va = traci.vehicle.getSpeed(a)
                for b in wb:
                    xb = traci.vehicle.getPosition(b)[0]
                    vb = traci.vehicle.getSpeed(b)
                    gap = xb - xa            # >0: approaching head-on
                    closing = va + vb
                    if gap <= 0:
                        worst["overlap"] += 1
                        self.overlap_pairs += 1
                        gap_eff = 0.0
                    else:
                        gap_eff = gap
                    pairs += 1
                    self.min_gap = min(self.min_gap, gap)
                    worst["gap"] = min(worst["gap"], gap)
                    if closing > 0.1:
                        ttc = gap_eff / closing
                        self.min_ttc = min(self.min_ttc, ttc)
                        worst["ttc"] = min(worst["ttc"], ttc)
            self.max_pairs = max(self.max_pairs, pairs)
            if len(self.events) < 4000:
                self.events.append(dict(t=t, phys=phys, n_eb=len(eb), n_wb=len(wb),
                                        min_gap_m=round(worst["gap"], 2),
                                        min_ttc_s=(None if worst["ttc"] == float("inf")
                                                   else round(worst["ttc"], 3)),
                                        overlapping_pairs=worst["overlap"]))
        if exposure:
            self.n_steps_with_exposure += 1

    def report(self):
        return dict(
            steps_with_opposing_cooccupancy=self.n_steps_with_exposure,
            total_overlapping_pair_samples=self.overlap_pairs,
            max_simultaneous_opposing_pairs=self.max_pairs,
            min_headon_gap_m=None if self.min_gap == float("inf") else round(self.min_gap, 2),
            min_headon_ttc_s=None if self.min_ttc == float("inf") else round(self.min_ttc, 3),
            n_event_records=len(self.events),
            events_truncated_at=4000,
            events=self.events[:4000],
        )


# --------------------------------------------------------------------------
def build_detectors(path, netfile, det_len=300.0):
    """E2 lane-area detectors on the last det_len m of both corridor edges."""
    root = ET.parse(netfile).getroot()
    lines = ["<additional>"]
    ids = {"EB": [], "WB": []}
    for d, e in (("EB", "COR_EB"), ("WB", "COR_WB")):
        for phys in PHYS_LANES:
            lid = lane_id(d, e, phys)
            did = f"e2_{d}_{phys}"
            lines.append(f'    <laneAreaDetector id="{did}" lane="{lid}" '
                         f'pos="-{det_len}" length="{det_len}" friendlyPos="true" '
                         f'period="100000" file="NUL"/>')
            ids[d].append((phys, did))
    lines.append("</additional>")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return ids


# --------------------------------------------------------------------------
def config_order(cfg):
    return {"2+4": -1, "3+3": 0, "4+2": 1}[cfg]


def next_config_towards(cur, target):
    """One reversible lane at a time."""
    if cur == target:
        return cur
    return "3+3" if config_order(cur) != 0 else ("4+2" if config_order(target) > 0 else "2+4")


def diff_lane(cur, target):
    a, b = CONFIGS[cur], CONFIGS[target]
    for p in REVERSIBLE:
        if a[p] != b[p]:
            return p, a[p], b[p]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", required=True)
    ap.add_argument("--routes", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--policy", required=True, choices=["A", "B", "C", "broken"])
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--end", type=float, required=True)
    ap.add_argument("--schedule", default="",
                    help="policy B/broken: 't:config,t:config,...'")
    ap.add_argument("--start-config", default="3+3")
    ap.add_argument("--dead-time", type=float, default=60.0,
                    help="nominal minimum dead time (s) held even if the lane "
                         "clears sooner")
    ap.add_argument("--time-to-teleport", type=float, default=300.0)
    ap.add_argument("--fcd", default="")
    ap.add_argument("--fcd-begin", default="")
    ap.add_argument("--fcd-filter", default="")
    ap.add_argument("--ssm", default="")
    ap.add_argument("--extra-add", default="")
    # policy C parameters
    ap.add_argument("--occ-hi", type=float, default=22.0)
    ap.add_argument("--occ-lo", type=float, default=12.0)
    ap.add_argument("--delta-on", type=float, default=10.0)
    ap.add_argument("--delta-off", type=float, default=4.0)
    ap.add_argument("--confirm", type=float, default=300.0)
    ap.add_argument("--min-dwell", type=float, default=900.0)
    a = ap.parse_args()

    os.makedirs(a.outdir, exist_ok=True)
    det_file = os.path.join(a.outdir, "detectors.add.xml")
    det_ids = build_detectors(det_file, a.net)

    adds = [det_file]
    if a.extra_add:
        adds.extend(a.extra_add.split(","))

    cmd = ["sumo", "-n", a.net, "-r", a.routes, "-a", ",".join(adds),
           "--tripinfo-output", os.path.join(a.outdir, "tripinfo.xml"),
           "--tripinfo-output.write-unfinished", "true",
           "--summary-output", os.path.join(a.outdir, "summary.xml"),
           "--statistic-output", os.path.join(a.outdir, "stats.xml"),
           "--seed", str(a.seed), "--begin", "0", "--end", str(a.end),
           "--time-to-teleport", str(a.time_to_teleport),
           "--no-step-log", "true", "--duration-log.statistics", "true",
           "--xml-validation", "never",
           "--error-log", os.path.join(a.outdir, "sumo_errors.log")]
    if a.fcd:
        cmd += ["--fcd-output", a.fcd, "--fcd-output.attributes",
                "x,y,speed,lane,pos,type"]
        if a.fcd_begin:
            cmd += ["--device.fcd.begin", str(a.fcd_begin)]
        if a.fcd_filter:
            cmd += ["--fcd-output.filter-edges.input-file", a.fcd_filter]
    if a.ssm:
        cmd += ["--device.ssm.probability", "1", "--device.ssm.file", a.ssm,
                "--device.ssm.measures", "TTC DRAC PET",
                "--device.ssm.thresholds", "3.0 3.0 2.0",
                "--device.ssm.range", "60", "--device.ssm.geo", "false"]

    traci.start(cmd)
    fac = Facility(a.net)
    scanner = HeadOnScanner(fac)

    # ---- t=0 initial state: everything was compiled OPEN, so close what the
    # ---- starting configuration says must be closed.
    cur = a.start_config
    asg = assignment(cur)
    for phys in PHYS_LANES:
        owner = asg[phys]
        fac.set_direction_lane(owner, phys, True)
        fac.set_direction_lane(OTHER[owner], phys, False)

    schedule = []
    if a.schedule:
        for item in a.schedule.split(","):
            t, c = item.split(":")
            schedule.append((float(t), c))
    schedule.sort()
    sched_i = 0

    target = cur
    active = None
    records = []
    trace = ["time,config,n_lanes_EB,n_lanes_WB,occ_EB,occ_WB,changeover_active"]
    occ_hist = []          # (t, occEB, occWB)
    last_change_t = -1e9
    cand_since = {"EB": None, "WB": None, "rev": None}

    step = 0
    t = 0.0
    while t < a.end:
        traci.simulationStep()
        t = traci.simulation.getTime()
        step += 1

        scanner.step(t)

        # --- advance an active changeover
        if active is not None:
            granted = active.step(t)
            if active.done:
                records.append(active.record())
                cur = _apply(cur, active.phys, active.gainer)
                last_change_t = t
                active = None

        # --- directional occupancy from the E2 detectors (open lanes only)
        if step % 10 == 0:
            asg = assignment(cur)
            occ = {}
            for d in ("EB", "WB"):
                vals = [traci.lanearea.getLastStepOccupancy(did)
                        for phys, did in det_ids[d] if asg[phys] == d]
                occ[d] = sum(vals) / len(vals) if vals else 0.0
            occ_hist.append((t, occ["EB"], occ["WB"]))
            trace.append(f"{t:.0f},{cur},{n_lanes('EB', cur)},{n_lanes('WB', cur)},"
                         f"{occ['EB']:.3f},{occ['WB']:.3f},{int(active is not None)}")

            # --- policy C decision logic
            if a.policy == "C" and active is None and (t - last_change_t) >= a.min_dwell:
                w = [x for x in occ_hist if x[0] > t - a.confirm]
                if w and (t - w[0][0]) >= a.confirm - 20:
                    oe = sum(x[1] for x in w) / len(w)
                    ow = sum(x[2] for x in w) / len(w)
                    want = cur
                    if oe >= a.occ_hi and (oe - ow) >= a.delta_on and config_order(cur) < 1:
                        want = "4+2" if cur == "3+3" else "3+3"
                    elif ow >= a.occ_hi and (ow - oe) >= a.delta_on and config_order(cur) > -1:
                        want = "2+4" if cur == "3+3" else "3+3"
                    elif abs(oe - ow) <= a.delta_off and max(oe, ow) <= a.occ_lo and cur != "3+3":
                        want = "3+3"
                    if want != cur:
                        target = want

        # --- policy B / broken: fixed schedule
        while sched_i < len(schedule) and schedule[sched_i][0] <= t:
            target = schedule[sched_i][1]
            sched_i += 1

        # --- launch the next single-lane changeover if needed
        if active is None and target != cur:
            nxt = next_config_towards(cur, target)
            d = diff_lane(cur, nxt)
            if d is not None:
                phys, loser, gainer = d
                active = Changeover(fac, phys, loser, gainer, t, a.dead_time,
                                    broken=(a.policy == "broken"))
                if active.done:            # broken variant completes instantly
                    records.append(active.record())
                    cur = _apply(cur, phys, gainer)
                    last_change_t = t
                    active = None
            else:
                cur = target

    traci.close()

    with open(os.path.join(a.outdir, "changeover_log.json"), "w") as f:
        json.dump(dict(policy=a.policy, seed=a.seed, dead_time=a.dead_time,
                       n_changeovers=len(records), changeovers=records), f, indent=2)
    with open(os.path.join(a.outdir, "headon_scan.json"), "w") as f:
        json.dump(scanner.report(), f, indent=2)
    with open(os.path.join(a.outdir, "config_trace.csv"), "w") as f:
        f.write("\n".join(trace) + "\n")
    r = scanner.report()
    print(f"[{a.policy} seed={a.seed}] changeovers={len(records)} "
          f"headon_steps={r['steps_with_opposing_cooccupancy']} "
          f"overlap_samples={r['total_overlapping_pair_samples']} "
          f"min_gap={r['min_headon_gap_m']}")


def _apply(cfg, phys, owner):
    a = dict(CONFIGS[cfg])
    a[phys] = owner
    for name, c in CONFIGS.items():
        if c == a:
            return name
    return cfg


if __name__ == "__main__":
    main()
