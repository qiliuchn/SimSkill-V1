#!/usr/bin/env python3
"""
Independent verification of the bay geometry and of the two failure-mode
counters, from RAW FCD TRAJECTORIES rather than from the live TraCI queries
that produced the sweep numbers.

Runs one designated cell with `--fcd-output` over a 600 s steady-state window
and then, from the FCD file alone:

  (1) GEOMETRY: checks that every north-approach LEFT-turning vehicle occupies
      only lane in_N_bay_1 (the bay) and never in_N_bay_0, and that every
      through/right vehicle occupies only in_N_bay_0 and never the bay. This is
      a behavioural check on actual trajectories -- complementary to, and
      independent of, the structural check on the compiled net.

  (2) FAILURE MODES: re-derives the bay-overflow and bay-blockage second-counts
      from the trajectory file using the same physical definitions, via a
      completely separate data path, and compares them against the TraCI-
      derived counts for the identical window. Agreement means the headline
      event rates are not an artifact of how TraCI was queried.

Also dumps the compiled net's connection table for the same cell so the
structural claim (left = its own tls link index, sourced only from the bay
lane) can be checked without re-running anything.
"""
import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

WIN_START, WIN_END = 1800.0, 2400.0
STOP_SPEED = 0.1
BAY_ENTRANCE_TOL = 7.5
GAP_TOL = 12.0
VEH_LEN = 5.0


def structural_check(net, out):
    root = ET.parse(net).getroot()
    lines = ["# Compiled-net structural check (bay geometry)", ""]
    lanes = {}
    for ed in root.findall("edge"):
        if ed.get("function") == "internal":
            continue
        for ln in ed.findall("lane"):
            lanes[ln.get("id")] = float(ln.get("length"))
    lines.append("## Non-internal lane lengths")
    for k in sorted(lanes):
        lines.append(f"  {k:<16} {lanes[k]:8.2f} m")
    lines.append("")
    lines.append("## Connections out of the north approach")
    lines.append(f"  {'from':<12}{'fromLane':>9}{'to':>10}{'toLane':>8}"
                 f"{'dir':>5}{'tl':>4}{'linkIndex':>10}")
    ok = {"left_from_bay_lane_only": None, "thru_from_lane0_only": None}
    for c in root.findall("connection"):
        f = c.get("from", "")
        if not f.startswith("in_N"):
            continue
        lines.append(f"  {f:<12}{c.get('fromLane'):>9}{c.get('to'):>10}"
                     f"{c.get('toLane'):>8}{str(c.get('dir')):>5}"
                     f"{str(c.get('tl')):>4}{str(c.get('linkIndex')):>10}")
        if c.get("dir") == "l" and c.get("tl"):
            ok["left_from_bay_lane_only"] = (f == "in_N_bay" and c.get("fromLane") == "1")
        if c.get("dir") == "s" and c.get("tl") and f == "in_N_bay":
            ok["thru_from_lane0_only"] = (c.get("fromLane") == "0")
    lines += ["", "## Verdict",
              f"  LEFT movement (dir='l') is a signal-controlled link sourced ONLY from "
              f"in_N_bay lane 1 (the bay): {ok['left_from_bay_lane_only']}",
              f"  THROUGH movement (dir='s') is sourced from in_N_bay lane 0: "
              f"{ok['thru_from_lane0_only']}", ""]
    open(out, "w").write("\n".join(lines) + "\n")
    return ok


def walk(states, start_ref):
    ref, n = start_ref, 0
    for p, sp, _v in sorted(states, key=lambda t: -t[0]):
        if p > ref:
            continue
        if sp >= STOP_SPEED or (ref - p) > GAP_TOL:
            break
        ref = p - VEH_LEN
        n += 1
    return ref, n


def fcd_analysis(fcd, bay_len, up_lane, bay_lane, tls_phase_by_time):
    """Re-derive lane usage and the two failure modes from raw trajectories."""
    lane_use = defaultdict(set)
    overflow_s = blockage_s = bay_full_s = 0.0
    thru_blocked_vs = 0.0
    nsteps = 0
    for _, ts in ET.iterparse(fcd, events=("end",)):
        if ts.tag != "timestep":
            continue
        t = float(ts.get("time"))
        if not (WIN_START <= t < WIN_END):
            ts.clear()
            continue
        nsteps += 1
        bay, up = [], []
        for v in ts.findall("vehicle"):
            vid = v.get("id")
            ln = v.get("lane")
            if not vid.startswith("N_"):
                continue
            if ln.startswith("in_N_bay_"):
                lane_use[vid].add(ln)
            p, sp = float(v.get("pos")), float(v.get("speed"))
            if ln == bay_lane:
                bay.append((p, sp, vid))
            elif ln == up_lane:
                up.append((p, sp, vid))

        bay_full = False
        if bay:
            tmin = min(p - VEH_LEN for p, _, _ in bay)
            slow = min(s for _, s, _ in bay) < 1.0
            bay_full = (tmin < BAY_ENTRANCE_TOL) and slow
        if bay_full:
            bay_full_s += 1.0
        sl = [(p, v) for p, sp, v in up if sp < STOP_SPEED and v.startswith("N_L")]
        st = [(p, v) for p, sp, v in up if sp < STOP_SPEED and not v.startswith("N_L")]
        if sl:
            head = max(p for p, _ in sl)
            if bay_full:
                overflow_s += 1.0
                thru_blocked_vs += sum(1 for p, _ in st if p < head)
            elif any(p > head for p, _ in st):
                blockage_s += 1.0
        ts.clear()
    return dict(fcd_steps=nsteps, overflow_s=overflow_s, blockage_s=blockage_s,
                bay_full_s=bay_full_s, overflow_thru_blocked_vs=thru_blocked_vs,
                lane_use={k: sorted(v) for k, v in lane_use.items()})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--bay", default="30")
    ap.add_argument("--share", default="40")
    ap.add_argument("--sig", default="split16")
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)

    net = os.path.join(a.work, "nets", f"bay_{a.bay}.net.xml")
    rou = os.path.join(a.work, f"rou_s{a.share}.rou.xml")
    tls = os.path.join(a.work, "tls", a.bay, f"tl_{a.sig}.add.xml")

    ok = structural_check(net, os.path.join(a.outdir, "geometry_structural_check.txt"))
    print("structural check:", ok)

    import run_cell
    run_cell.WARMUP = WIN_START
    run_cell.DEMAND_END = WIN_END
    run_cell.SIM_END = WIN_END
    rundir = os.path.join(a.outdir, f"raw_bay{a.bay}_s{a.share}_{a.sig}_seed1")
    res = run_cell.run(net, rou, tls, a.sig, 1, rundir, ttt=300, fcd=True,
                       label="verify", keep_raw=True)
    print("traci events:", {k: res[k] for k in
                            ("overflow_s", "blockage_s", "bay_full_s",
                             "overflow_thru_blocked_vs")})

    bay_len = res["bay_len"]
    fa = fcd_analysis(os.path.join(rundir, "fcd.xml"), bay_len,
                      "in_N_up_0", "in_N_bay_1", None)

    # --- geometry from trajectories ---
    left_bad = sorted(v for v, s in fa["lane_use"].items()
                      if v.startswith("N_L") and "in_N_bay_0" in s)
    thru_bad = sorted(v for v, s in fa["lane_use"].items()
                      if not v.startswith("N_L") and "in_N_bay_1" in s)
    nl = sum(1 for v in fa["lane_use"] if v.startswith("N_L"))
    no = sum(1 for v in fa["lane_use"] if not v.startswith("N_L"))

    report = {
        "cell": dict(bay_m=bay_len, left_share_pct=int(a.share), signal=a.sig,
                     window_s=[WIN_START, WIN_END], seed=1),
        "structural_check_compiled_net": ok,
        "trajectory_geometry_check": {
            "left_turning_vehicles_seen_on_bay_section": nl,
            "left_turning_vehicles_that_touched_the_through_lane": len(left_bad),
            "through_right_vehicles_seen_on_bay_section": no,
            "through_right_vehicles_that_touched_the_bay_lane": len(thru_bad),
            "violating_ids": (left_bad + thru_bad)[:20],
            "verdict": "PASS" if not left_bad and not thru_bad else "FAIL"},
        "failure_mode_cross_check": {
            "window_s": [WIN_START, WIN_END],
            "traci_live_query": {k: res[k] for k in
                                 ("overflow_s", "blockage_s", "bay_full_s",
                                  "overflow_thru_blocked_vs")},
            "fcd_trajectory_rederivation": {k: fa[k] for k in
                                            ("overflow_s", "blockage_s", "bay_full_s",
                                             "overflow_thru_blocked_vs")},
            "fcd_steps_in_window": fa["fcd_steps"]},
    }
    d1 = report["failure_mode_cross_check"]["traci_live_query"]
    d2 = report["failure_mode_cross_check"]["fcd_trajectory_rederivation"]
    report["failure_mode_cross_check"]["agreement"] = {
        k: ("EXACT" if d1[k] == d2[k] else
            f"differs by {d2[k]-d1[k]:+g} ({abs(d2[k]-d1[k])/max(d1[k],1)*100:.2f}%)")
        for k in d1}
    p = os.path.join(a.outdir, "trace_verification.json")
    json.dump(report, open(p, "w"), indent=1)
    print(json.dumps(report["trajectory_geometry_check"], indent=1))
    print(json.dumps(report["failure_mode_cross_check"]["agreement"], indent=1))
    print("wrote", p)


if __name__ == "__main__":
    main()
