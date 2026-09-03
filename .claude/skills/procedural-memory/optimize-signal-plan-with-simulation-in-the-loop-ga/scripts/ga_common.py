#!/usr/bin/env python3
"""Shared genome decoder + SUMO fitness evaluation for the arterial GA.

Genome (dict): C (cycle length s), splits [g1,g2,g3] main-green fraction per intersection,
offsets [o1,o2,o3] in [0,C). Decoder writes a valid tlLogic .add.xml reusing the
netconvert-generated state strings (fixed yellows, enforced minimum greens)."""
import os, subprocess, uuid
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
NET = os.path.join(HERE, "corridor.net.xml")
ROU = os.path.join(HERE, "corridor.rou.xml")

YELLOW = 3          # matches netconvert-generated yellow duration
MIN_GREEN = int(os.environ.get("GA_MINGREEN", "6"))   # minimum green per movement group (s)
N_VEH = 308         # vehicles in corridor.rou.xml
TELE_PENALTY = 1000.0   # per vehicle that fails to complete

# Bounds (C_MIN overridable via env for a matched-range experiment)
C_MIN, C_MAX = float(os.environ.get("GA_CMIN", "40")), 120.0
SPLIT_MIN, SPLIT_MAX = 0.30, 0.70   # main-green fraction of usable green time

TLS = ["I1", "I2", "I3"]


def _load_states():
    """Return dict tl_id -> (main_green_state, y_after_main, side_green_state, y_after_side).
    Detected by which green phase's green links originate from main ('m_') edges."""
    root = ET.parse(NET).getroot()
    # map (tl,linkIndex) -> from edge
    fromedge = {}
    for c in root.findall("connection"):
        tl = c.get("tl")
        if tl:
            fromedge[(tl, int(c.get("linkIndex")))] = c.get("from")
    out = {}
    for tl in root.findall("tlLogic"):
        tid = tl.get("id")
        phases = [(p.get("state"), float(p.get("duration"))) for p in tl.findall("phase")]
        greens = [i for i, (s, d) in enumerate(phases) if "G" in s or "g" in s]
        yellows = [i for i, (s, d) in enumerate(phases) if "y" in s and "G" not in s]
        # classify each green phase as main or side
        def is_main(pidx):
            s = phases[pidx][0]
            mains = sides = 0
            for li, ch in enumerate(s):
                if ch in "Gg":
                    fe = fromedge.get((tid, li), "")
                    if fe.startswith("m_"):
                        mains += 1
                    else:
                        sides += 1
            return mains > sides
        main_g = next(i for i in greens if is_main(i))
        side_g = next(i for i in greens if not is_main(i))
        # yellow following main green (next index), yellow following side green
        y_after_main = phases[(main_g + 1) % len(phases)][0]
        y_after_side = phases[(side_g + 1) % len(phases)][0]
        out[tid] = (phases[main_g][0], y_after_main, phases[side_g][0], y_after_side)
    return out


STATES = _load_states()


def decode(genome):
    """Return list of (tl_id, offset, [(state,dur),...]) with enforced constraints.
    Also returns clamped genome (constraints applied)."""
    C = min(max(genome["C"], C_MIN), C_MAX)
    plans = []
    clamped_splits, clamped_offsets = [], []
    for i, tl in enumerate(TLS):
        g = min(max(genome["splits"][i], SPLIT_MIN), SPLIT_MAX)
        usable = C - 2 * YELLOW
        gm = g * usable
        gs = usable - gm
        # enforce minimum greens
        if gm < MIN_GREEN:
            gm = MIN_GREEN
            gs = usable - gm
        if gs < MIN_GREEN:
            gs = MIN_GREEN
            gm = usable - gs
        gm, gs = round(gm), round(gs)
        # recompute effective cycle after rounding so offset math stays exact
        eff_C = gm + gs + 2 * YELLOW
        off = round(genome["offsets"][i]) % eff_C
        mg, ym, sg, ys = STATES[tl]
        phases = [(mg, gm), (ym, YELLOW), (sg, gs), (ys, YELLOW)]
        plans.append((tl, off, phases, eff_C))
        clamped_splits.append(gm / usable)
        clamped_offsets.append(off)
    return C, plans, clamped_splits, clamped_offsets


def write_tls_add(genome, path):
    C, plans, cs, co = decode(genome)
    with open(path, "w") as f:
        f.write('<additional>\n')
        for tl, off, phases, eff_C in plans:
            f.write(f'    <tlLogic id="{tl}" type="static" programID="ga" offset="{off}">\n')
            for state, dur in phases:
                f.write(f'        <phase duration="{dur}" state="{state}"/>\n')
            f.write('    </tlLogic>\n')
        f.write('</additional>\n')
    return C, plans


def parse_tripinfo(path):
    root = ET.parse(path).getroot()
    infos = root.findall("tripinfo")
    n = len(infos)
    tot_timeloss = sum(float(t.get("timeLoss")) for t in infos)
    tot_wait = sum(float(t.get("waitingTime")) for t in infos)
    tot_dur = sum(float(t.get("duration")) for t in infos)
    tot_stops = sum(float(t.get("waitingCount")) for t in infos)
    return {
        "n": n,
        "total_timeLoss": tot_timeloss,
        "total_waiting": tot_wait,
        "total_duration": tot_dur,
        "total_stops": tot_stops,
        "mean_timeLoss": tot_timeloss / n if n else 0,
        "mean_waiting": tot_wait / n if n else 0,
        "mean_stops": tot_stops / n if n else 0,
    }


def run_sim(add_file, tripinfo_out, extra_add=None, summary_out=None):
    adds = [add_file] if isinstance(add_file, str) else list(add_file)
    if extra_add:
        adds += extra_add if isinstance(extra_add, list) else [extra_add]
    cmd = ["sumo", "-n", NET, "-r", ROU]
    if adds:
        cmd += ["-a", ",".join(adds)]
    cmd += [
        "--tripinfo-output", tripinfo_out,
        "--seed", "42",
        "--time-to-teleport", "120",
        "--no-step-log", "true", "--no-warnings", "true",
        "--duration-log.statistics", "true",
        "--end", "3600",
    ]
    if summary_out:
        cmd += ["--summary-output", summary_out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("sumo failed: " + r.stderr[-800:])
    return r


def fitness(genome, workdir):
    """Objective = total timeLoss + penalty*(uncompleted vehicles). Lower is better."""
    tag = uuid.uuid4().hex[:8]
    add_file = os.path.join(workdir, f"tls_{tag}.add.xml")
    trip_out = os.path.join(workdir, f"trip_{tag}.xml")
    write_tls_add(genome, add_file)
    run_sim(add_file, trip_out)
    m = parse_tripinfo(trip_out)
    incomplete = max(0, N_VEH - m["n"])
    obj = m["total_timeLoss"] + TELE_PENALTY * incomplete
    os.remove(add_file)
    os.remove(trip_out)
    m["objective"] = obj
    m["incomplete"] = incomplete
    return obj, m
