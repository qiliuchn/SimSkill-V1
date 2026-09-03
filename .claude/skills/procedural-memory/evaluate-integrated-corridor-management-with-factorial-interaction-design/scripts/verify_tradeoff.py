#!/usr/bin/env python3
"""
Sub-goal 1 verification: under no-incident, light-traffic conditions, confirm
the arterial path (x=1000 to x=7000, via ax1..ax6, 6 km) is 15-30% slower
than the matched freeway path (x=1000 to x=7000, via fx3..fx15, 6 km) -- a
genuine tradeoff, not a dominated/dominant alternative.

Uses a *cohort* of probe vehicles departing every 5 s across one full signal
cycle (not a single arbitrarily-timed probe), since a single probe's result
depends on luck relative to the signal phase -- reports mean/median travel
time and the zero-stop fraction, per the three-measurement-layer discipline
in design-arterial-signal-progression-and-verify-bandwidth.
"""
import argparse
import json
import os
import sys

SUMO_HOME = os.environ.get("SUMO_HOME", "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo")
sys.path.append(os.path.join(SUMO_HOME, "tools"))
import traci  # noqa: E402

CYCLE = 90.0
N_PROBES = 18
GAP = CYCLE / N_PROBES


def build_routes(out_path):
    fwy_edges = " ".join(f"fwy_eb_{i}" for i in range(3, 15))  # x=1000 -> x=7000, 6 km
    art_edges = " ".join(f"art_eb_{i}" for i in range(1, 6))    # ax1(1000) -> ax6(7000), 6 km
    lines = ['<routes>',
             '    <vType id="car" length="4.5" minGap="2.5" accel="2.6" decel="4.5" sigma="0.5" maxSpeed="40"/>',
             f'    <route id="fwy_probe_route" edges="{fwy_edges}"/>',
             f'    <route id="art_probe_route" edges="{art_edges}"/>']
    t = 200.0
    for i in range(N_PROBES):
        dep = t + i * GAP
        lines.append(f'    <vehicle id="fwy_probe_{i}" type="car" route="fwy_probe_route" depart="{dep:.1f}"/>')
        lines.append(f'    <vehicle id="art_probe_{i}" type="car" route="art_probe_route" depart="{dep:.1f}"/>')
    lines.append('    <flow id="art_bg" type="car" route="art_probe_route" begin="0" end="1800" vehsPerHour="120"/>')
    lines.append('</routes>')
    with open(out_path, "w") as f:
        f.write("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", required=True)
    ap.add_argument("--tls", required=True)
    ap.add_argument("--workdir", required=True)
    args = ap.parse_args()
    os.makedirs(args.workdir, exist_ok=True)
    rou = os.path.join(args.workdir, "probe.rou.xml")
    build_routes(rou)

    cmd = ["sumo", "-n", args.net, "-r", rou, "-a", args.tls,
           "--begin", "0", "--end", "2400", "--step-length", "0.5",
           "--no-step-log", "true", "--time-to-teleport", "-1"]
    traci.start(cmd)
    depart = {}
    arrive = {}
    stops = {}
    prev_speed = {}
    while traci.simulation.getMinExpectedNumber() > 0:
        traci.simulationStep()
        for vid in traci.simulation.getDepartedIDList():
            depart[vid] = traci.simulation.getTime()
            stops[vid] = 0
            prev_speed[vid] = None
        for vid in list(prev_speed.keys()):
            if vid in traci.vehicle.getIDList():
                sp = traci.vehicle.getSpeed(vid)
                if prev_speed[vid] is not None and prev_speed[vid] > 0.5 and sp < 0.3:
                    stops[vid] += 1
                prev_speed[vid] = sp
        for vid in traci.simulation.getArrivedIDList():
            arrive[vid] = traci.simulation.getTime()
    traci.close()

    def summarize(prefix):
        tts = []
        zero_stop = 0
        n = 0
        for vid in depart:
            if not vid.startswith(prefix):
                continue
            if vid not in arrive:
                continue
            n += 1
            tt = arrive[vid] - depart[vid]
            tts.append(tt)
            if stops.get(vid, 0) == 0:
                zero_stop += 1
        tts.sort()
        mean_tt = sum(tts) / len(tts)
        median_tt = tts[len(tts) // 2]
        return dict(n=n, mean_s=mean_tt, median_s=median_tt, min_s=tts[0], max_s=tts[-1],
                    zero_stop_frac=zero_stop / n if n else None)

    fwy_stats = summarize("fwy_probe")
    art_stats = summarize("art_probe")
    ratio_mean = art_stats["mean_s"] / fwy_stats["mean_s"]
    ratio_median = art_stats["median_s"] / fwy_stats["median_s"]

    result = dict(freeway=fwy_stats, arterial=art_stats,
                  ratio_mean=ratio_mean, pct_slower_mean=(ratio_mean - 1) * 100,
                  ratio_median=ratio_median, pct_slower_median=(ratio_median - 1) * 100)
    print(json.dumps(result, indent=2))
    with open(os.path.join(args.workdir, "tradeoff_result.json"), "w") as f:
        json.dump(result, f, indent=2)


if __name__ == "__main__":
    main()
