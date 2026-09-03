#!/usr/bin/env python3
"""
Sub-goal 4 trigger chain, detection half: run a causal, online automatic
incident detection (AID) algorithm on the mainline E1 detector stream and
measure its detection-latency distribution over CRN seeds.

Scope note: a full multi-algorithm AID bake-off (California family vs SND vs
EWMA vs fixed thresholds) is already exhaustively covered in memory
(build-and-benchmark-freeway-incident-detection, whose headline finding is
that a fixed threshold is at least as good as the comparative algorithms in
SUMO's smooth congestion regime). Re-deriving that comparison here would
spend this task's budget on a question memory already answered. This script
reuses that finding directly: a single fixed speed-threshold algorithm at the
station immediately upstream of the incident, run once per seed, to produce
the latency distribution the sub-goal-4 lag-sweep design curve needs.

Algorithm: alarm when the 30s-binned space-mean speed at station e1_m8
(x=3500-4000, immediately upstream of the incident at x=4000-4500) falls
below SPEED_THRESHOLD for >= PERSIST consecutive bins. Detection instant =
END of the alarming interval (the algorithm cannot decide before the interval
is aggregated -- this gives latency a hard floor of PERSIST*BIN_S).

Runs plain `sumo` (no TraCI) per seed for speed -- this measurement needs no
live control, just the detector stream.
"""
import argparse
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from demand.gen_demand import build as build_demand_xml  # noqa: E402

SPEED_THRESHOLD = 14.0   # m/s (~48% of the 29.06 m/s freeway free-flow speed)
PERSIST = 2               # consecutive 30s bins
BIN_S = 30.0
STATION = 8               # segment index (x=3500-4000), immediately upstream of incident


def run_one(net, tls, incident_begin, incident_duration, seed, run_dir, sim_end, demand_end):
    os.makedirs(run_dir, exist_ok=True)
    demand_path = os.path.join(run_dir, "demand.rou.xml")

    class A:
        pass
    a = A()
    a.begin, a.end, a.scale = 0, demand_end, 1.0
    a.fwy_eb_vph, a.fwy_wb_vph = 3650, 2800
    a.art_eb_vph, a.art_wb_vph = 500, 500
    a.cross_vph, a.ramp_vph = 80, 90
    with open(demand_path, "w") as f:
        f.write(build_demand_xml(a))

    incident_path = os.path.join(run_dir, "incident.add.xml")
    end = incident_begin + incident_duration
    with open(incident_path, "w") as f:
        f.write(f"""<additional>
    <rerouter id="incident_rerouter" edges="fwy_eb_9">
        <interval begin="{incident_begin}" end="{end}">
            <closingLaneReroute id="fwy_eb_9_0" disallow="all"/>
            <closingLaneReroute id="fwy_eb_9_1" disallow="all"/>
        </interval>
    </rerouter>
</additional>
""")
    det_path = os.path.join(run_dir, "detectors.add.xml")
    subprocess.run([sys.executable, os.path.join(ROOT, "control", "build_detectors.py"),
                     "--run-dir", run_dir, "--out", det_path], check=True)

    cmd = ["sumo", "-n", net, "-r", demand_path, "-a", f"{tls},{incident_path},{det_path}",
           "--begin", "0", "--end", str(sim_end), "--step-length", "1.0", "--no-step-log", "true",
           "--time-to-teleport", "300", "--seed", str(seed)]
    subprocess.run(cmd, check=True, capture_output=True, text=True)

    e1_path = os.path.join(run_dir, "e1_mainline.xml")
    tree = ET.parse(e1_path)
    root = tree.getroot()
    # collect station STATION's 3-lane mean speed per 30s bin
    bins = {}
    for iv in root.findall("interval"):
        det_id = iv.get("id")
        if not det_id.startswith(f"e1_m{STATION}_"):
            continue
        endt = float(iv.get("end"))
        speed = float(iv.get("speed"))
        nveh = float(iv.get("nVehContrib"))
        bins.setdefault(endt, []).append((speed, nveh))

    series = []
    for endt in sorted(bins.keys()):
        vals = bins[endt]
        total_n = sum(n for s, n in vals)
        if total_n > 0:
            mean_speed = sum(s * n for s, n in vals) / total_n
        else:
            mean_speed = None
        series.append((endt, mean_speed))

    # threshold + persistence detector, restricted to the search window around
    # the incident (start scanning from incident_begin; MTTD would be
    # ill-defined if we allowed pre-incident false alarms to count)
    consec = 0
    alarm_time = None
    for endt, sp in series:
        if endt < incident_begin:
            continue
        if sp is not None and sp < SPEED_THRESHOLD:
            consec += 1
        else:
            consec = 0
        if consec >= PERSIST:
            alarm_time = endt
            break

    latency = (alarm_time - incident_begin) if alarm_time is not None else None
    return dict(seed=seed, incident_begin=incident_begin, alarm_time=alarm_time,
                latency_s=latency, detected=alarm_time is not None,
                series_sample=series[:20])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", required=True)
    ap.add_argument("--tls", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--seeds", type=int, nargs="+", default=list(range(101, 116)))
    ap.add_argument("--incident-begin", type=float, default=1500)
    ap.add_argument("--incident-duration", type=float, default=1800)
    ap.add_argument("--sim-end", type=float, default=3600)
    ap.add_argument("--demand-end", type=float, default=3300)
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    results = []
    for seed in args.seeds:
        rd = os.path.join(args.out_dir, f"seed_{seed}")
        try:
            r = run_one(args.net, args.tls, args.incident_begin, args.incident_duration,
                        seed, rd, args.sim_end, args.demand_end)
        except Exception as e:
            r = dict(seed=seed, error=str(e))
        print(seed, r.get("latency_s"), r.get("detected"))
        results.append(r)

    lat = [r["latency_s"] for r in results if r.get("latency_s") is not None]
    summary = dict(
        n_seeds=len(args.seeds),
        n_detected=len(lat),
        detection_rate=len(lat) / len(args.seeds),
        latencies_s=lat,
        mean_latency_s=sum(lat) / len(lat) if lat else None,
        min_latency_s=min(lat) if lat else None,
        max_latency_s=max(lat) if lat else None,
        median_latency_s=sorted(lat)[len(lat) // 2] if lat else None,
        algorithm=f"fixed speed threshold < {SPEED_THRESHOLD} m/s for >= {PERSIST} x {BIN_S}s bins, station m{STATION}",
        results=results,
    )
    with open(os.path.join(args.out_dir, "aid_latency_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, indent=2))


if __name__ == "__main__":
    main()
