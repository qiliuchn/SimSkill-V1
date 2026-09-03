#!/usr/bin/env python3
"""
Run-validity accounting + measured saturation flow + measured v/c.

Every number printed here is parsed from raw SUMO output in the run directory:
  summary.xml   loaded / inserted / running / waiting / teleports / collisions
  stats.xml     SUMO's own vehicle accounting
  tripinfo.xml  arrivals
  pending.csv   TraCI insertion backlog at every 15-min bin boundary
  e2_queue.xml  peak back of queue (checked against the ATR station setback)
  e1_instant.xml  per-vehicle stop-bar crossing times -> saturation headway
"""
import csv
import json
import os
import statistics
import sys
import xml.etree.ElementTree as ET

from common import (RUNS, OUT, JUNCTIONS, BIN, N_BINS, CYCLE, PH_ART_G,
                    parse_summary, parse_tripinfo, parse_e1, parse_e2, parse_instant)
import build_detectors

ATR_SETBACK_M = 1900.0 - 100.0     # detector at 100 m into a 2000 m feed


def validity(run_dir):
    s = parse_summary(os.path.join(run_dir, "summary.xml"))
    last = s[-1]
    running = [(float(r["time"]), int(r["running"])) for r in s]
    # freeze check: any 600 s window after the demand ends with a constant, non-zero
    # running count and no arrivals
    frozen = False
    for i in range(len(running)):
        t, n = running[i]
        if t < 14400 or n == 0:
            continue
        j = i
        while j < len(running) and running[j][0] - t < 600:
            j += 1
        if j < len(running) and all(running[k][1] == n for k in range(i, j)):
            frozen = True
            break
    tri = parse_tripinfo(os.path.join(run_dir, "tripinfo.xml"))
    st = ET.parse(os.path.join(run_dir, "stats.xml")).getroot()
    veh = st.find("vehicles")
    pend = list(csv.DictReader(open(os.path.join(run_dir, "pending.csv"))))
    return dict(
        loaded=int(last["loaded"]), inserted=int(last["inserted"]),
        running_end=int(last["running"]), waiting_end=int(last["waiting"]),
        teleports=int(last["teleports"]), collisions=int(last["collisions"]),
        arrived=len(tri),
        stats_loaded=int(veh.get("loaded")), stats_inserted=int(veh.get("inserted")),
        stats_running=int(veh.get("running")), stats_waiting=int(veh.get("waiting")),
        max_pending=max(int(p["n_pending_insertion"]) for p in pend),
        max_pending_bin=max(pend, key=lambda p: int(p["n_pending_insertion"]))["time"],
        pending_profile=[(float(p["time"]), int(p["n_pending_insertion"])) for p in pend],
        running_frozen=frozen,
        max_running=max(n for _, n in running))


def peak_queues(run_dir):
    e2 = parse_e2(os.path.join(run_dir, "e2_queue.xml"))
    out = {}
    for det, rows in e2.items():
        out[det] = dict(maxJamM=max(r["maxJamM"] for r in rows),
                        maxJamVeh=max(r["maxJamVeh"] for r in rows))
    return out


def saturation_flow(run_dir, min_queue_pos=4, tls="J1"):
    """Measured saturation flow on the J1 EB through lanes, from the per-vehicle
    stop-bar crossing times of the instant loops.  Headways are taken between
    consecutive vehicles from the 4th queue position onward within each green."""
    rows = parse_instant(os.path.join(run_dir, "e1_instant.xml"))
    cross = {}
    for det, t, state, veh in rows:
        if state != "leave":
            continue
        cross.setdefault(det, []).append(t)
    out = {}
    for det, ts in cross.items():
        ts.sort()
        # green windows for the arterial through phase at J1: offset 0
        hs = []
        for t in ts:
            pass
        # group crossings by cycle, position within the green
        by_cycle = {}
        for t in ts:
            c = int(t // CYCLE)
            ph = t % CYCLE
            if 0 <= ph <= PH_ART_G + 3:          # green + yellow
                by_cycle.setdefault(c, []).append(t)
        for c, v in by_cycle.items():
            v.sort()
            for i in range(min_queue_pos, len(v)):
                h = v[i] - v[i - 1]
                if 0.3 < h < 6.0:
                    hs.append(h)
        if len(hs) >= 30:
            out[det] = dict(n=len(hs), mean_headway=statistics.mean(hs),
                            s_veh_h=3600.0 / statistics.mean(hs))
    return out


def atr_validity(run_dir, arm):
    """Is the mid-block ATR station really beyond the peak back of queue?
    Tested empirically: its per-bin count is compared against the REALIZED
    generated demand of the paths that pass it.  A metered station would flatten
    at capacity; an unmetered one tracks demand up to Poisson noise."""
    import collections
    import demand as Dm
    from common import BIN, N_BINS
    tri = parse_tripinfo(os.path.join(run_dir, "tripinfo.xml"))
    gen = collections.Counter()
    for t in tri:
        gen[(t["id"].split(".")[0],
             int((t["depart"] - t["departDelay"]) // BIN))] += 1
    e1 = parse_e1(os.path.join(run_dir, "e1_atr.xml"))
    out = {}
    for d, origin in (("EB", "eb_WF_J1_feed"), ("WB", "wb_EF_J3_feed")):
        real = [0.0] * N_BINS
        for name, p in Dm.PATHS.items():
            if p["o"] != origin:
                continue
            for b in range(N_BINS):
                real[b] += gen.get((name, b), 0)
        cnt = [0] * N_BINS
        for det, rows in e1.items():
            if not det.startswith("atr_%s" % d):
                continue
            for (b0, b1, n, _f, _o) in rows:
                b = int(b0 // BIN)
                if b < N_BINS:
                    cnt[b] += n
        out[d] = dict(realized=real, atr=cnt,
                      ratio=[cnt[b] / real[b] if real[b] else None for b in range(N_BINS)],
                      total_ratio=sum(cnt) / sum(real))
    return out


def main():
    report = {}
    for name in sys.argv[1:] or ["gt_under", "gt_over"]:
        d = os.path.join(RUNS, name)
        v = validity(d)
        q = peak_queues(d)
        report[name] = dict(validity={k: val for k, val in v.items()
                                     if k != "pending_profile"},
                            pending_profile=v["pending_profile"],
                            peak_queue_m={k: val["maxJamM"] for k, val in q.items()},
                            peak_queue_veh={k: val["maxJamVeh"] for k, val in q.items()})
        print("=" * 70)
        print(name)
        for k in ("loaded", "inserted", "arrived", "running_end", "waiting_end",
                  "teleports", "collisions", "max_pending", "max_pending_bin",
                  "running_frozen", "max_running"):
            print("   %-16s %s" % (k, v[k]))
        worst = sorted(q.items(), key=lambda kv: -kv[1]["maxJamM"])[:6]
        for det, val in worst:
            flag = "  <-- EXCEEDS ATR SETBACK" if val["maxJamM"] > ATR_SETBACK_M else ""
            print("   peak queue %-14s %8.1f m  %4d veh%s"
                  % (det, val["maxJamM"], val["maxJamVeh"], flag))
    for name in sys.argv[1:] or ["gt_under", "gt_over"]:
        arm = name.replace("gt_", "")
        av = atr_validity(os.path.join(RUNS, name), arm)
        report.setdefault(name, {})["atr_validity"] = av
        print("-- %s ATR station vs realized generated demand (per 15-min bin)" % name)
        for d, v in av.items():
            print("   %s total ratio %.4f  min/max bin ratio %.3f / %.3f"
                  % (d, v["total_ratio"],
                     min(x for x in v["ratio"] if x), max(x for x in v["ratio"] if x)))
    sat = saturation_flow(os.path.join(RUNS, "gt_over"))
    report["saturation_flow_gt_over_J1EB"] = sat
    print("=" * 70)
    print("measured saturation flow, J1 EB stop bar (gt_over run):")
    for det, val in sorted(sat.items()):
        print("   %-14s n=%4d  mean headway=%.3f s  s=%.0f veh/h/ln"
              % (det, val["n"], val["mean_headway"], val["s_veh_h"]))
    with open(os.path.join(OUT, "run_validity.json"), "w") as f:
        json.dump(report, f, indent=1)


if __name__ == "__main__":
    main()
