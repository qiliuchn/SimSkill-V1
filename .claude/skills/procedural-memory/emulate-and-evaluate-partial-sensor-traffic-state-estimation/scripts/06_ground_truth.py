#!/usr/bin/env python3
"""
06_ground_truth.py -- establish GROUND TRUTH from the master run's 100% / 1 Hz FCD.

Produces (into outputs/results/):
  gt_links.csv     per-vehicle per-EB-link experienced traversal time
                   (link + its downstream junction, so link times sum exactly to
                    the corridor travel time)
  gt_corridor.csv  per-vehicle EB corridor entry/exit/travel time, completed flag
  gt_queue.csv     per-second TRUE maximum queue length per EB approach, measured
                   from vehicle positions (NOT from any detector)
  gt_linkstate.csv per-link per-30s TRUE space-mean speed and TRUE mean
                   experienced link travel time (by entry time)
  gt_presence.csv  per-vehicle presence interval on the corridor (for the
                   presence-vs-departure probe-sampling bias test)

Queue definition (documented, not implicit): on an approach edge, per lane, a
vehicle is "stopped" if speed < thr (thr swept over 0.3 / 1.39 / 2.0 m/s; 1.39 m/s
= 5 km/h is the HCM-style threshold and is used for headline numbers).  The queue
is the contiguous chain of stopped vehicles extended upstream while the gap to the
next stopped vehicle is < 20 m.  TWO definitions are reported:
  Q_anchored -- chain head must be within 25 m of the stop bar (classic
                "max queue at end of red")
  Q_extent   -- back-of-queue distance from the stop bar regardless of head
                position; this is what determines whether a queue physically
                covers an advance detector, so it is the truth used for the
                detector blind-spot hypothesis.
The reported approach queue is the MAX over the approach's lanes.
"""
import csv
import gzip
import os
import re
import xml.etree.ElementTree as ET
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
SCEN = os.path.abspath(os.path.join(HERE, "..", "scenario"))
RUNS = os.path.abspath(os.path.join(HERE, "..", "..", "runs"))
RES = os.path.abspath(os.path.join(HERE, "..", "results"))
os.makedirs(RES, exist_ok=True)

FCD = os.path.join(RUNS, "master", "fcd.xml.gz")
EB_EDGES = [f"eb_{i}" for i in range(6)]
APPROACH = {i: f"eb_{i-1}" for i in range(1, 6)}   # EB approach edge to Ji
STOP_SPEEDS = [0.3, 1.39, 2.0]   # m/s; 1.39 m/s = 5 km/h is the HCM-style "queued" threshold
PRIMARY_THR_IDX = 1              # 1.39 m/s used for all headline queue numbers
CHAIN_GAP = 20.0
HEAD_TOL = 25.0
VEH_LEN = 5.0
CYCLE = 90
OFFSETS = {1: 0, 2: 29, 3: 58, 4: 86, 5: 25}
BIN = 30

RE_T = re.compile(r'<timestep time="([\d.]+)"')
RE_V = re.compile(r'<vehicle id="([^"]+)" speed="([-\d.]+)" pos="([-\d.]+)" lane="([^"]+)"')


def lane_lengths():
    tree = ET.parse(os.path.join(SCEN, "arterial.net.xml"))
    out = {}
    for e in tree.getroot().findall("edge"):
        if e.get("function") == "internal":
            continue
        ls = e.findall("lane")
        out[e.get("id")] = (len(ls), float(ls[0].get("length")))
    return out


def main():
    LL = lane_lengths()
    print("parsing FCD:", FCD)

    first_on = defaultdict(dict)      # veh -> edge -> first t
    last_t = {}                       # veh -> last t seen anywhere
    first_t = {}                      # veh -> first t seen anywhere
    dist_time = defaultdict(lambda: [0.0, 0.0])   # (edge,bin) -> [sum speed*dt, veh-seconds]
    queue_rows = []                   # (t, junction, qlen_m, qveh, spillback)

    t = None
    # per-timestep buffer of approach-lane vehicle states
    buf = defaultdict(list)           # laneID -> [(pos, speed)]
    nrec = 0

    def flush_queues(tt):
        """Two ground-truth queue definitions, both from raw vehicle positions:

        Q_anchored : the classic stop-bar-anchored queue -- the contiguous chain of
                     stopped vehicles whose HEAD is within HEAD_TOL of the stop bar.
                     Zero once the head has discharged.  This is the quantity a
                     "max queue at end of red" specification means.
        Q_extent   : the BACK-OF-QUEUE extent -- distance from the stop bar to the
                     rear of the furthest-upstream vehicle of the contiguous
                     stopped chain, regardless of where the chain's head is.  This
                     is the quantity that determines whether a queue physically
                     covers a given advance detector, so it is the correct truth
                     for the detector blind-spot hypothesis.

        Reported per approach as the MAX over the approach's lanes.
        Also computed at three "stopped" speed thresholds for sensitivity.
        """
        for j, ap in APPROACH.items():
            nl, L = LL[ap]
            out_row = [tt, j]
            for thr in STOP_SPEEDS:
                best_a, best_e, best_n, spill = 0.0, 0.0, 0, 0
                for ln in range(nl):
                    v = sorted([p for p in buf.get(f"{ap}_{ln}", []) if p[1] < thr],
                               key=lambda x: -x[0])
                    if not v:
                        continue
                    # walk the contiguous chain from the most downstream stopped veh
                    chain_rear = v[0][0] - VEH_LEN
                    cnt = 1
                    for k in range(1, len(v)):
                        if chain_rear - v[k][0] < CHAIN_GAP:
                            chain_rear = v[k][0] - VEH_LEN
                            cnt += 1
                        else:
                            break
                    extent = L - chain_rear
                    anchored = extent if (L - v[0][0]) <= HEAD_TOL else 0.0
                    best_e = max(best_e, extent)
                    if anchored > best_a:
                        best_a, best_n = anchored, cnt
                    if chain_rear <= 2.0:
                        spill = 1
                out_row += [round(best_a, 2), round(best_e, 2), best_n, spill]
            queue_rows.append(tuple(out_row))

    with gzip.open(FCD, "rt") as f:
        for line in f:
            m = RE_T.search(line)
            if m:
                if t is not None:
                    flush_queues(t)
                t = float(m.group(1))
                buf = defaultdict(list)
                continue
            m = RE_V.search(line)
            if not m:
                continue
            nrec += 1
            vid, spd, pos, lane = m.group(1), float(m.group(2)), float(m.group(3)), m.group(4)
            if vid not in first_t:
                first_t[vid] = t
            last_t[vid] = t
            edge = lane.rsplit("_", 1)[0] if not lane.startswith(":") else lane
            if edge not in first_on[vid]:
                first_on[vid][edge] = t
            if edge in EB_EDGES:
                b = int(t // BIN) * BIN
                dt = dist_time[(edge, b)]
                dt[0] += spd
                dt[1] += 1.0
            if lane in [f"{ap}_{l}" for ap in APPROACH.values() for l in range(2)]:
                buf[lane].append((pos, spd))
    if t is not None:
        flush_queues(t)
    print(f"  {nrec} FCD vehicle-records, last t={t}")

    # ---------------------------------------------------------------- corridor
    tinfo = {}
    for _, el in ET.iterparse(os.path.join(RUNS, "master", "tripinfo.xml"), events=("end",)):
        if el.tag == "tripinfo":
            tinfo[el.get("id")] = (float(el.get("depart")), float(el.get("arrival")))
            el.clear()

    with open(os.path.join(RES, "gt_corridor.csv"), "w", newline="") as fc, \
         open(os.path.join(RES, "gt_links.csv"), "w", newline="") as fl, \
         open(os.path.join(RES, "gt_presence.csv"), "w", newline="") as fp:
        wc = csv.writer(fc); wc.writerow(["veh", "depart", "enter", "exit", "corridor_tt", "completed"])
        wl = csv.writer(fl); wl.writerow(["veh", "link", "enter", "tt"])
        wp = csv.writer(fp); wp.writerow(["veh", "enter", "exit", "corridor_tt", "completed"])
        n_eb = 0
        for vid, fo in first_on.items():
            if not vid.startswith("f_eb"):
                continue
            n_eb += 1
            ent = fo.get("eb_0")
            if ent is None:
                continue
            arr = tinfo.get(vid, (None, -1))[1]
            completed = 1 if arr is not None and arr >= 0 else 0
            ex = (last_t[vid] + 1.0)
            has_all = all(f"eb_{i}" in fo for i in range(6))
            if completed and has_all:
                wc.writerow([vid, tinfo[vid][0], ent, ex, round(ex - ent, 2), 1])
                for i in range(5):
                    wl.writerow([vid, i, fo[f"eb_{i}"], round(fo[f"eb_{i+1}"] - fo[f"eb_{i}"], 2)])
                wl.writerow([vid, 5, fo["eb_5"], round(ex - fo["eb_5"], 2)])
            else:
                wc.writerow([vid, tinfo[vid][0], ent, "", "", 0])
            wp.writerow([vid, ent, ex, round(ex - ent, 2) if completed and has_all else "",
                         completed])
        print(f"  EB vehicles seen in FCD: {n_eb}")

    # ------------------------------------------------------------ link state
    with open(os.path.join(RES, "gt_linkstate.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["bin", "link", "space_mean_speed", "veh_seconds"])
        for (edge, b), (sd, vs) in sorted(dist_time.items(), key=lambda kv: (kv[0][1], kv[0][0])):
            # space-mean speed = total distance / total time  (Edie's definition)
            w.writerow([b, int(edge.split("_")[1]), round(sd / vs, 4) if vs else "", int(vs)])

    # ---------------------------------------------------------------- queues
    hdr = ["t", "junction"]
    for thr in STOP_SPEEDS:
        t = str(thr).replace(".", "p")
        hdr += [f"anchored_{t}", f"extent_{t}", f"qveh_{t}", f"spill_{t}"]
    with open(os.path.join(RES, "gt_queue.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(hdr)
        w.writerows(queue_rows)

    # per-cycle max, for every stopped-speed threshold and both definitions
    agg = defaultdict(lambda: defaultdict(float))
    for row in queue_rows:
        tt, j = row[0], row[1]
        c = int((tt - OFFSETS[j]) // CYCLE)
        for k, thr in enumerate(STOP_SPEEDS):
            a, e, n, sp = row[2 + 4 * k: 6 + 4 * k]
            d = agg[(j, c)]
            d[f"anchored_{k}"] = max(d[f"anchored_{k}"], a)
            d[f"extent_{k}"] = max(d[f"extent_{k}"], e)
            d[f"qveh_{k}"] = max(d[f"qveh_{k}"], n)
            d[f"spill_{k}"] = max(d[f"spill_{k}"], sp)
    cols = ["junction", "cycle", "cycle_start"]
    for k, thr in enumerate(STOP_SPEEDS):
        t = str(thr).replace(".", "p")
        cols += [f"max_anchored_{t}", f"max_extent_{t}", f"max_qveh_{t}", f"spill_{t}"]
    with open(os.path.join(RES, "gt_queue_percycle.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for (j, c) in sorted(agg):
            d = agg[(j, c)]
            row = [j, c, OFFSETS[j] + c * CYCLE]
            for k, thr in enumerate(STOP_SPEEDS):
                row += [round(d[f"anchored_{k}"], 2), round(d[f"extent_{k}"], 2),
                        int(d[f"qveh_{k}"]), int(d[f"spill_{k}"])]
            w.writerow(row)
    print("  wrote ground-truth CSVs to", RES)

    for k, thr in enumerate(STOP_SPEEDS):
        a3 = [d[f"anchored_{k}"] for (j, c), d in agg.items() if j == 3]
        e3 = [d[f"extent_{k}"] for (j, c), d in agg.items() if j == 3]
        s3 = sum(1 for (j, c), d in agg.items() if j == 3 and d[f"spill_{k}"])
        print(f"  J3 EB thr={thr} m/s: anchored peak={max(a3):6.1f} m, "
              f"extent peak={max(e3):6.1f} m, extent>250m in {sum(1 for x in e3 if x>250)}/{len(e3)} "
              f"cycles, spillback cycles={s3}")


if __name__ == "__main__":
    main()
