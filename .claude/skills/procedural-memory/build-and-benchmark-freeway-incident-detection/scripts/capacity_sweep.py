"""Calibrate the demand->served-flow curve so demand levels can be placed as a % of capacity.

Runs plain SUMO (no TraCI) with the E1 detector file, and reports served flow at a
mid-mainline station (x=3000 m, downstream of the merge bottleneck) plus teleports/collisions.
"""
import os, sys, subprocess, shutil, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import *
from build_detectors import build
import xml.etree.ElementTree as ET

WORK = os.path.join(RUNS_DIR, "_capsweep")


def read_e1(path):
    """-> {station_idx: list of (begin, volume, occ_pct, harmonic_speed)}"""
    t = ET.parse(path)
    per = {}
    for iv in t.getroot().findall("interval"):
        sid = iv.get("id")            # st{kk}_l{li}
        k = int(sid[2:4])
        b = float(iv.get("begin"))
        n = float(iv.get("nVehContrib"))
        occ = float(iv.get("occupancy"))
        hs = float(iv.get("harmonicMeanSpeed"))
        per.setdefault((k, b), []).append((n, occ, hs))
    out = {}
    for (k, b), lanes in per.items():
        vol = sum(l[0] for l in lanes)
        occm = sum(l[1] for l in lanes) / len(lanes)
        num = sum(l[0] for l in lanes if l[2] > 0)
        sp = (sum(l[0] / l[2] for l in lanes if l[2] > 0) and
              num / sum(l[0] / l[2] for l in lanes if l[2] > 0)) if num > 0 else -1.0
        out.setdefault(k, []).append((b, vol, occm, sp))
    for k in out:
        out[k].sort()
    return out


def run(level, seed=1):
    d = os.path.join(WORK, level)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
    e1 = os.path.join(d, "e1.xml")
    add = os.path.join(d, "det.add.xml")
    with open(add, "w") as f:
        f.write(build(e1))
    cmd = [SUMO_BIN, "-n", os.path.join(NET_DIR, "freeway.net.xml"),
           "-r", os.path.join(DEMAND_DIR, f"demand_{level}.rou.xml"),
           "-a", add, "--begin", "0", "--end", str(SIM_END),
           "--seed", str(seed), "--time-to-teleport", "300",
           "--collision.action", "warn", "--no-step-log", "true",
           "--statistic-output", os.path.join(d, "stats.xml"),
           "--summary-output", os.path.join(d, "summary.xml"),
           "--tripinfo-output", os.path.join(d, "tripinfo.xml"),
           "--xml-validation", "never"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    tele = len(re.findall(r"teleporting", r.stderr))
    coll = len(re.findall(r"[Cc]ollision", r.stderr))
    dat = read_e1(e1)
    st = ET.parse(os.path.join(d, "stats.xml")).getroot()
    veh = st.find("vehicles")
    res = {"level": level, "teleport_warn_lines": tele, "collision_warn_lines": coll,
           "inserted": int(veh.get("inserted")), "loaded": int(veh.get("loaded")),
           "running": int(veh.get("running"))}
    for k, x in (("upstream_x0", 0), ("post_merge_x1250", 5), ("mid_x3000", 12), ("end_x5750", 23)):
        rows = [r_ for r_ in dat[x] if 900 <= r_[0] < 3300]
        res[k + "_flow_vph"] = sum(r_[1] for r_ in rows) / (len(rows) * DET_PERIOD) * 3600
        res[k + "_occ"] = sum(r_[2] for r_ in rows) / len(rows)
        sp = [r_[3] for r_ in rows if r_[3] > 0]
        res[k + "_speed"] = sum(sp) / len(sp) if sp else -1
    return res


if __name__ == "__main__":
    levels = ["cap3000", "cap3600", "cap4200", "cap4500", "cap5100", "cap5400", "cap6000"]
    hdr = None
    rows = []
    for lv in levels:
        r = run(lv)
        rows.append(r)
        print(f"{lv:9s} inserted={r['inserted']:5d} running_at_end={r['running']:4d} "
              f"tele={r['teleport_warn_lines']:3d} coll={r['collision_warn_lines']:3d} | "
              f"x0 {r['upstream_x0_flow_vph']:6.0f}vph {r['upstream_x0_speed']:5.1f}m/s | "
              f"x1250 {r['post_merge_x1250_flow_vph']:6.0f}vph occ{r['post_merge_x1250_occ']:5.1f} "
              f"{r['post_merge_x1250_speed']:5.1f}m/s | "
              f"x3000 {r['mid_x3000_flow_vph']:6.0f}vph occ{r['mid_x3000_occ']:5.1f} "
              f"{r['mid_x3000_speed']:5.1f}m/s")
