#!/usr/bin/env python3
"""Calibrate the corridor's CRITICAL OCCUPANCY from its own data (never assume the
textbook 15-25%, per `implement-alinea-ramp-metering` / [[ramp-metering-with-alinea]]).

Runs a mainline-only (all ramps closed) steady-demand sweep and traces, at every
mainline E1 station, the flow-vs-occupancy relation; the occupancy at which flow
peaks is that station's critical occupancy.  Also measures the bottleneck's
free-flow discharge vs its congested discharge -- the CAPACITY DROP check that H6
depends on (see the [[variable-speed-limits-and-e2-detectors]] caveat that SUMO's
merge/lane-drop model may not reproduce one).
"""
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gen_additional import build as build_add  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
NET = os.path.join(ROOT, "outputs", "net", "base", "corridor.net.xml")
OUT = os.path.join(ROOT, "outputs", "calib")
LEVELS = [1800, 2400, 3000, 3600, 4000, 4300, 4600, 5000, 5400, 6000]
WARM, DUR = 600, 2400


def routes(rate, path):
    n = int(rate * DUR / 3600)
    L = ['<routes>',
         '  <vType id="car" vClass="passenger" length="5.0" minGap="2.5" accel="2.6" '
         'decel="4.5" sigma="0.5" tau="1.0" maxSpeed="40.0" speedDev="0.0" carFollowModel="Krauss"/>',
         '  <route id="ml" edges="ml_0 ml_1 ml_2 ml_3 ml_4 ml_5 ml_6"/>',
         f'  <flow id="f" route="ml" type="car" begin="0" end="{DUR}" number="{n}" '
         f'departLane="best" departSpeed="max"/>',
         '</routes>']
    open(path, "w").write("\n".join(L))


def main():
    os.makedirs(OUT, exist_ok=True)
    rows = []
    for lv in LEVELS:
        d = os.path.join(OUT, f"lv{lv}")
        os.makedirs(d, exist_ok=True)
        add = build_add(NET, d, period=60)
        rf = os.path.join(d, "r.rou.xml")
        routes(lv, rf)
        cmd = ["sumo", "-n", NET, "-r", rf, "-a", add, "--begin", "0",
               "--end", str(DUR + 900), "--seed", "1", "--no-step-log", "true",
               "--duration-log.disable", "true", "--xml-validation", "never",
               "--time-to-teleport", "300", "--default.speeddev", "0.1"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stderr[-2000:])
            raise SystemExit(1)
        agg = defaultdict(lambda: defaultdict(list))
        nint = (DUR - WARM) / 60.0
        for iv in ET.parse(os.path.join(d, "det_e1.xml")).getroot():
            t0 = float(iv.get("begin"))
            if t0 < WARM or t0 >= DUR:
                continue
            did = iv.get("id")
            if not did.startswith("e1_s"):
                continue
            st = did.split("_")[1]
            agg[st]["flow"].append(float(iv.get("nVehContrib")) * 3600.0 / 60.0)
            agg[st]["occ"].append(float(iv.get("occupancy")))
            sp = float(iv.get("speed"))
            if sp >= 0:
                agg[st]["spd"].append(sp)
        row = dict(level=lv)
        for st in agg:
            row[st] = dict(flow=sum(agg[st]["flow"]) / nint,
                           occ=sum(agg[st]["occ"]) / len(agg[st]["occ"]),
                           spd=(sum(agg[st]["spd"]) / len(agg[st]["spd"])) if agg[st]["spd"] else None,
                           nlanes=round(len(agg[st]["flow"]) / nint))
        rows.append(row)
        s10, s11 = row["s10"], row["s11"]
        print(f"demand={lv:5d}  s10 flow={s10['flow']:7.0f} occ={s10['occ']:5.2f} v={s10['spd']:5.1f}"
              f" | s11 flow={s11['flow']:7.0f} occ={s11['occ']:5.2f} v={s11['spd']:5.1f}", flush=True)

    json.dump(rows, open(os.path.join(OUT, "calib.json"), "w"), indent=1)
    print("\n--- critical occupancy (flow peak) per station ---")
    for st in [f"s{i:02d}" for i in (3, 6, 9, 10, 11)]:
        best = max(rows, key=lambda r: r[st]["flow"])
        print(f"  {st}: peak flow {best[st]['flow']:.0f} veh/h at occ {best[st]['occ']:.2f}% "
              f"(demand {best['level']}), speed {best[st]['spd']:.1f} m/s")
    print("\n--- bottleneck discharge (s11) free-flow vs congested ---")
    for r in rows:
        print(f"  demand {r['level']:5d}: s11 flow={r['s11']['flow']:7.0f} "
              f"({r['s11']['flow']/2:6.0f}/lane) occ={r['s11']['occ']:5.2f} "
              f"| s10 occ={r['s10']['occ']:5.2f} v={r['s10']['spd']:5.1f}")


if __name__ == "__main__":
    main()
