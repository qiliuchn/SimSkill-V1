#!/usr/bin/env python3
"""
Shared machinery for the predictive rolling-horizon signal-control study.

Everything here is derived by *introspection* of a compiled SUMO network -- no
per-network hard-coding -- so the same controller code runs on the isolated
junction and on either corridor junction.

Contents
  PhaseModel        phase <-> movement-group mapping, clearance chains, lane sets
  detector files    E1 induction loops at a chosen setback on every approach lane
  switch-log audit  verify realised timings respect min green / yellow / all-red
  output parsing    tripinfo / summary + censoring-robust delay
"""
import math
import os
import shutil
import sys
import xml.etree.ElementTree as ET

SUMO_HOME = os.environ["SUMO_HOME"]
sys.path.append(os.path.join(SUMO_HOME, "tools"))
import sumolib  # noqa: E402


def find_bin(name):
    p = shutil.which(name)
    if p:
        return p
    s = shutil.which("sumo")
    if s:
        c = os.path.join(os.path.dirname(s), name)
        if os.path.isfile(c):
            return c
    c = os.path.join(SUMO_HOME, "bin", name)
    if os.path.isfile(c):
        return c
    raise RuntimeError("cannot find " + name)


SUMO = find_bin("sumo")

# ---------------------------------------------------------------- geometry ---
def edge_dir(edge):
    shp = edge.getShape()
    dx = shp[-1][0] - shp[0][0]
    dy = shp[-1][1] - shp[0][1]
    n = math.hypot(dx, dy) or 1.0
    return (dx / n, dy / n)


def turn_role(invec, outvec):
    ang = math.degrees(math.atan2(outvec[1], outvec[0]) - math.atan2(invec[1], invec[0]))
    ang = (ang + 180.0) % 360.0 - 180.0
    if abs(ang) < 30:
        return "s"
    if abs(ang) > 150:
        return "u"
    return "l" if ang > 0 else "r"


AXES = ((90, "NB"), (0, "EB"), (270, "SB"), (180, "WB"))


def approach_axis(invec):
    head = math.degrees(math.atan2(invec[1], invec[0])) % 360.0
    return min(((abs(((head - a + 180) % 360) - 180), nm) for a, nm in AXES))[1]


def is_green(state):
    return ("G" in state or "g" in state) and "y" not in state


def has_yellow(state):
    return "y" in state


def is_allred(state):
    return ("G" not in state) and ("g" not in state) and ("y" not in state)


# --------------------------------------------------------------- PhaseModel ---
class PhaseModel:
    """Introspects one traffic light of a compiled net.

    Movement groups: (axis, kind) with kind in {'TR','L'} -- 'TR' lumps the
    through and right movements that share the two curb lanes, 'L' is the
    exclusive left-turn lane.  Groups are the unit the DP queue model tracks.
    """

    def __init__(self, netfile, tls_id, net=None):
        self.net = net if net is not None else sumolib.net.readNet(netfile, withPrograms=True)
        self.tls_id = tls_id
        tl = self.net.getTLS(tls_id)
        prog = list(tl.getPrograms().values())[0]
        self.phases = [(p.state, float(p.duration)) for p in prog.getPhases()]
        self.n = len(self.phases)

        self.link_meta = {}
        for inLane, outLane, idx in tl.getConnections():
            iv = edge_dir(inLane.getEdge())
            ov = edge_dir(outLane.getEdge())
            self.link_meta[idx] = dict(
                inLane=inLane.getID(), outLane=outLane.getID(),
                role=turn_role(iv, ov), axis=approach_axis(iv))

        # movement groups
        self.groups = []            # ordered list of (axis, kind)
        self.group_in_lanes = {}
        self.group_out_lanes = {}
        self.group_links = {}
        for idx, m in sorted(self.link_meta.items()):
            kind = "L" if m["role"] == "l" else "TR"
            g = (m["axis"], kind)
            if g not in self.group_in_lanes:
                self.groups.append(g)
                self.group_in_lanes[g] = set()
                self.group_out_lanes[g] = set()
                self.group_links[g] = []
            self.group_in_lanes[g].add(m["inLane"])
            self.group_out_lanes[g].add(m["outLane"])
            self.group_links[g].append(idx)
        self.groups.sort()
        for g in self.groups:
            self.group_in_lanes[g] = sorted(self.group_in_lanes[g])
            self.group_out_lanes[g] = sorted(self.group_out_lanes[g])

        # green phases, the groups each serves, and the clearance chain
        self.green_phases = [i for i, (st, _) in enumerate(self.phases) if is_green(st)]
        self.phase_groups = {}
        self.phase_in_lanes = {}
        self.phase_via_lanes = {}
        for gi in self.green_phases:
            st = self.phases[gi][0]
            served, inl, via = set(), set(), set()
            for i, ch in enumerate(st):
                if ch in "Gg" and i in self.link_meta:
                    m = self.link_meta[i]
                    kind = "L" if m["role"] == "l" else "TR"
                    served.add((m["axis"], kind))
                    inl.add(m["inLane"])
            self.phase_groups[gi] = sorted(served)
            self.phase_in_lanes[gi] = sorted(inl)
            self.phase_via_lanes[gi] = sorted(self._via_lanes(gi))

        self.clearance = {}   # green -> (yellow idx or None, allred idx or None)
        for gi in self.green_phases:
            self.clearance[gi] = self._following_clearance(gi)

        # cyclic ring order of green phases (program order)
        self.ring = list(self.green_phases)
        self.ring_pos = {p: k for k, p in enumerate(self.ring)}

        # lanes of each approach edge, and each approach edge's length
        self.lane_len = {}
        for e in self.net.getEdges():
            for l in e.getLanes():
                self.lane_len[l.getID()] = l.getLength()

    def _via_lanes(self, gi):
        tl = self.net.getTLS(self.tls_id)
        st = self.phases[gi][0]
        out = set()
        for conn in self.net.getNode(self.tls_id).getConnections() if False else []:
            pass
        # via lanes come from the net's connection objects
        for e in self.net.getEdges():
            for conn in e.getConnections(None) if False else []:
                pass
        # simpler: internal lanes are named ':<node>_<linkIndex>_<i>'
        for i, ch in enumerate(st):
            if ch in "Gg":
                pref = f":{self.tls_id}_{i}_"
                for lid in self.lane_len_keys():
                    if lid.startswith(pref):
                        out.add(lid)
        return out

    def lane_len_keys(self):
        if not hasattr(self, "_lk"):
            self._lk = [l.getID() for e in self.net.getEdges(withInternal=True) for l in e.getLanes()]
        return self._lk

    def _following_clearance(self, gi):
        yellow = None
        allred = None
        for step in range(1, self.n + 1):
            j = (gi + step) % self.n
            st = self.phases[j][0]
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

    def clearance_time(self, gi):
        y, r = self.clearance[gi]
        t = 0.0
        if y is not None:
            t += self.phases[y][1]
        if r is not None:
            t += self.phases[r][1]
        return t

    def n_lanes(self, g):
        return len(self.group_in_lanes[g])

    def approach_len(self, g):
        return max(self.lane_len[l] for l in self.group_in_lanes[g])

    def describe(self):
        out = [f"tls {self.tls_id}: {self.n} phases, greens {self.green_phases}"]
        for gi in self.green_phases:
            y, r = self.clearance[gi]
            out.append(f"  phase {gi} serves {self.phase_groups[gi]} clearance y={y} r={r} "
                       f"({self.clearance_time(gi):g}s)")
        for g in self.groups:
            out.append(f"  group {g}: in={self.group_in_lanes[g]} out={self.group_out_lanes[g]}")
        return "\n".join(out)


# ----------------------------------------------------------------- detectors ---
def write_detectors(netfile, path, setback, period=1e6, tls_ids=None):
    """One E1 induction loop per *incoming signalised lane*, `setback` metres
    upstream of the stop line.  Returns {laneID: detID}."""
    net = sumolib.net.readNet(netfile, withPrograms=True)
    mapping = {}
    lines = ['<additional>']
    for tl in net.getTrafficLights():
        if tls_ids and tl.getID() not in tls_ids:
            continue
        lanes = sorted({inLane.getID() for inLane, _, _ in tl.getConnections()})
        for lid in lanes:
            L = net.getLane(lid).getLength()
            pos = max(0.5, L - setback)
            did = f"d{int(setback)}_{lid.replace(':', '_')}"
            mapping[lid] = did
            lines.append(f'    <inductionLoop id="{did}" lane="{lid}" pos="{pos:.2f}" '
                         f'friendlyPos="true" period="{period:g}" file="NUL"/>')
    lines.append('</additional>')
    with open(path, "w") as f:
        f.write("\n".join(lines))
    return mapping


def write_actuated_binding(netfile, out_net, mapping):
    """Copy `netfile` to `out_net`, converting its tlLogic(s) to type=actuated
    and adding <param key="<laneID>" value="<detID>"/> children.

    The lane-ID key form (not a 'detector:' prefix) is the syntax verified in
    `design-actuated-signal-detector-placement-and-fault-tolerance`.
    """
    with open(netfile) as f:
        txt = f.read()
    net = sumolib.net.readNet(netfile, withPrograms=True)
    for tl in net.getTrafficLights():
        tid = tl.getID()
        start = txt.index(f'<tlLogic id="{tid}"')
        ls = txt.rfind("\n", 0, start) + 1
        end = txt.index("</tlLogic>", start)
        block = txt[ls:end]
        lanes = sorted({inLane.getID() for inLane, _, _ in tl.getConnections()})
        params = "".join(f'        <param key="{l}" value="{mapping[l]}"/>\n'
                         for l in lanes if l in mapping)
        txt = txt[:ls] + block + params + txt[end:]
    with open(out_net, "w") as f:
        f.write(txt)


# --------------------------------------------------------- switch-log audit ---
def audit_switch_log(path, pm_by_tls, min_green, tol=0.51):
    """Parse a switch log (csv: t,tls,from_phase,to_phase) and verify:
       * no green -> green transition
       * every green interval >= min_green (minus one step tolerance)
       * every yellow interval >= its programmed duration
       * every all-red interval >= its programmed duration
    Returns dict of violation counts + worst offenders."""
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("t,"):
                continue
            t, tls, fr, to = line.split(",")
            rows.append((float(t), tls, int(fr), int(to)))
    res = {"green_to_green": 0, "short_green": 0, "short_yellow": 0, "short_allred": 0,
           "n_switch": len(rows), "min_green_seen": None, "min_yellow_seen": None,
           "min_allred_seen": None}
    greens = []
    by_tls = {}
    for r in rows:
        by_tls.setdefault(r[1], []).append(r)
    for tls, rs in by_tls.items():
        pm = pm_by_tls[tls]
        for k in range(len(rs) - 1):
            t0, _, _, ph = rs[k]
            t1 = rs[k + 1][0]
            dur = t1 - t0
            st = pm.phases[ph][0]
            if is_green(st):
                nxt = rs[k + 1][3]
                if is_green(pm.phases[nxt][0]):
                    res["green_to_green"] += 1
                if dur < min_green - tol:
                    res["short_green"] += 1
                res["min_green_seen"] = dur if res["min_green_seen"] is None else min(res["min_green_seen"], dur)
                greens.append(dur)
            elif has_yellow(st):
                if dur < pm.phases[ph][1] - tol:
                    res["short_yellow"] += 1
                res["min_yellow_seen"] = dur if res["min_yellow_seen"] is None else min(res["min_yellow_seen"], dur)
            elif is_allred(st):
                if dur < pm.phases[ph][1] - tol:
                    res["short_allred"] += 1
                res["min_allred_seen"] = dur if res["min_allred_seen"] is None else min(res["min_allred_seen"], dur)
    if greens:
        gs = sorted(greens)
        res["green_median"] = gs[len(gs) // 2]
        res["green_mean"] = sum(gs) / len(gs)
        res["green_p90"] = gs[min(len(gs) - 1, int(0.90 * len(gs)))]
        res["green_max"] = gs[-1]
        # the diagnostic that exposed attempt 1's min-green pinning: what
        # fraction of realised greens sit exactly on the min-green bound?
        res["green_at_min_frac"] = sum(1 for x in gs if x <= min_green + tol) / len(gs)
        res["n_green_intervals"] = len(gs)
    return res


# ------------------------------------------------------------ output parsing ---
def parse_tripinfo(path):
    n, dur, loss, wait, depdelay, stops, rl = 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
    ids = set()
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag != "tripinfo":
            continue
        n += 1
        ids.add(el.get("id"))
        dur += float(el.get("duration"))
        loss += float(el.get("timeLoss"))
        wait += float(el.get("waitingTime"))
        depdelay += float(el.get("departDelay"))
        stops += float(el.get("waitingCount"))
        rl += float(el.get("routeLength"))
        el.clear()
    if n == 0:
        return dict(n=0)
    return dict(n=n, mean_duration=dur / n, mean_timeloss=loss / n, mean_waiting=wait / n,
                mean_departdelay=depdelay / n, mean_stops=stops / n,
                mean_routelen=rl / n, ids=ids)


def parse_summary(path):
    last = None
    tele = 0
    maxrun = 0
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag != "step":
            continue
        last = dict(el.attrib)
        tele = max(tele, int(el.get("teleports", 0)))
        maxrun = max(maxrun, int(el.get("running", 0)))
        el.clear()
    if last is None:
        return {}
    return dict(inserted=int(last.get("inserted", 0)), ended=int(last.get("ended", 0)),
                loaded=int(last.get("loaded", 0)), teleports=tele,
                end_time=float(last.get("time", 0)), max_running=maxrun)


def censoring_robust_delay(tripinfo, summary, n_scheduled, sim_end, penalty=None):
    """Charge never-completed vehicles a penalty, per the survivorship-censoring
    correction in `design-actuated-signal-detector-placement-and-fault-tolerance`."""
    ti = parse_tripinfo(tripinfo)
    su = parse_summary(summary)
    n_done = ti.get("n", 0)
    missing = max(0, n_scheduled - n_done)
    if n_done == 0:
        return dict(n_done=0, n_missing=missing, censor_frac=1.0, robust_timeloss=float("nan"))
    pen = penalty if penalty is not None else sim_end
    tot = ti["mean_timeloss"] * n_done + missing * pen
    return dict(n_done=n_done, n_missing=missing,
                censor_frac=missing / max(1, n_scheduled),
                naive_timeloss=ti["mean_timeloss"],
                robust_timeloss=tot / max(1, n_scheduled),
                teleports=su.get("teleports", 0))
