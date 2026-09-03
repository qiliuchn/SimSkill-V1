#!/usr/bin/env python3
"""
Quantify SUMO's keep-right lane-change bias on a 2-lane arterial approach.

Runs the identical build_high / TWSC scenario twice: once with the study's
vType (`lcKeepRight="0"`) and once with SUMO's default keep-right behaviour,
and compares the stop-bar E1 counts lane by lane.  This makes the "94% of an
approach's traffic ends up in one lane" claim reproducible from a raw file
rather than from an anecdote.
"""
import csv
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import RUNS, SCEN, TABLES, DRAIN_END, STEP_LENGTH, find_bin, run, write

SRC_ROU = os.path.join(SCEN, "demand", "build_high_std.rou.xml")
NET = os.path.join(SCEN, "net", "twsc.net.xml")
DET = os.path.join(SCEN, "detectors", "det_std.add.xml")
OUTRUN = os.path.join(RUNS, "lanebalance_keepright_default")


def main():
    if os.path.isdir(OUTRUN):
        shutil.rmtree(OUTRUN)
    os.makedirs(OUTRUN)
    rou = open(SRC_ROU).read().replace(' lcKeepRight="0"', "")
    assert 'lcKeepRight' not in rou
    write(os.path.join(OUTRUN, "routes.rou.xml"), rou)
    write(os.path.join(OUTRUN, "det.add.xml"),
          open(DET).read().replace("@OUTDIR@/", ""))
    cmd = [find_bin("sumo"), "-n", NET, "-r", "routes.rou.xml", "-a", "det.add.xml",
           "--begin", "0", "--end", str(DRAIN_END),
           "--step-length", str(STEP_LENGTH), "--step-method.ballistic",
           "--seed", "11", "--time-to-teleport", "300",
           "--statistic-output", "statistics.xml", "--duration-log.statistics", "true",
           "--no-warnings", "true", "--no-step-log", "true",
           "--xml-validation", "never"]
    r = run(cmd, cwd=OUTRUN)
    write(os.path.join(OUTRUN, "cmd.txt"), " ".join(cmd) + "\n")
    if r.returncode != 0:
        sys.exit(r.stderr[-2000:])

    def counts(d):
        out = {}
        for iv in ET.parse(os.path.join(d, "e1_stopbar.xml")).getroot().findall("interval"):
            h = int(float(iv.get("begin")) // 3600)
            out.setdefault(h, {})[iv.get("id")] = int(iv.get("nVehContrib"))
        return out

    a = counts(os.path.join(RUNS, "build_high__twsc__s11"))   # lcKeepRight="0"
    b = counts(OUTRUN)                                        # SUMO default
    rows = []
    for h in range(12):
        for appr, lanes in (("EB", ["e1_EB_maj_W_bay_0", "e1_EB_maj_W_bay_1"]),
                            ("WB", ["e1_WB_maj_E_bay_0", "e1_WB_maj_E_bay_1"])):
            for tag, src in (("lcKeepRight=0", a), ("SUMO default", b)):
                l0, l1 = (src[h][lanes[0]], src[h][lanes[1]])
                tot = l0 + l1
                rows.append({"hour": f"{7+h:02d}:00", "approach": appr,
                             "lane_change_setting": tag,
                             "lane0_vph": l0, "lane1_vph": l1,
                             "through_group_total_vph": tot,
                             "max_lane_share_pct": round(100 * max(l0, l1) / tot, 1)
                             if tot else ""})
    with open(os.path.join(TABLES, "lane_balance_keepright.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print("[lane] wrote lane_balance_keepright.csv")
    print(f"{'hour':7s}{'appr':5s}{'setting':16s}{'lane0':>7s}{'lane1':>7s}{'total':>7s}{'maxshare%':>10s}")
    for r_ in rows:
        if r_["hour"] in ("07:00", "12:00", "17:00"):
            print(f"{r_['hour']:7s}{r_['approach']:5s}{r_['lane_change_setting']:16s}"
                  f"{r_['lane0_vph']:7d}{r_['lane1_vph']:7d}"
                  f"{r_['through_group_total_vph']:7d}{r_['max_lane_share_pct']:10.1f}")
    sh_def = [r_["max_lane_share_pct"] for r_ in rows
              if r_["lane_change_setting"] == "SUMO default" and r_["max_lane_share_pct"]]
    sh_off = [r_["max_lane_share_pct"] for r_ in rows
              if r_["lane_change_setting"] == "lcKeepRight=0" and r_["max_lane_share_pct"]]
    print(f"\nmax-lane share over all 24 approach-hours: "
          f"SUMO default {min(sh_def):.1f}-{max(sh_def):.1f}%  "
          f"(mean {sum(sh_def)/len(sh_def):.1f}%)  |  "
          f"lcKeepRight=0 {min(sh_off):.1f}-{max(sh_off):.1f}%  "
          f"(mean {sum(sh_off)/len(sh_off):.1f}%)")


if __name__ == "__main__":
    main()
