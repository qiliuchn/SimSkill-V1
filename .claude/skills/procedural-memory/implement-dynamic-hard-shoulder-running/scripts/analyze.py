#!/usr/bin/env python3
"""Compare the three HSR scenarios from raw SUMO output files (attempt-2 corrected bottleneck)."""
import xml.etree.ElementTree as ET
import os, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODES = ["closed", "open", "dynamic"]
EXIT_IDS = {"e1_exit_s", "e1_exit_0"}  # w_0 (shoulder) + w_1 (through) at pos 1050


def parse_tripinfo(path):
    root = ET.parse(path).getroot()
    n = 0
    tot_dur = tot_loss = tot_len = tot_wait = tot_depdelay = 0.0
    for tp in root.findall("tripinfo"):
        n += 1
        tot_dur += float(tp.get("duration"))
        tot_loss += float(tp.get("timeLoss"))
        tot_len += float(tp.get("routeLength"))
        tot_wait += float(tp.get("waitingTime"))
        tot_depdelay += float(tp.get("departDelay"))
    return {
        "completed": n,
        "mean_duration": tot_dur / n if n else 0,
        "mean_timeloss": tot_loss / n if n else 0,
        "total_timeloss_h": tot_loss / 3600.0,
        "mean_waiting": tot_wait / n if n else 0,
        "mean_departdelay": tot_depdelay / n if n else 0,
        "net_mean_speed": tot_len / tot_dur if tot_dur else 0,
        "total_veh_hours": tot_dur / 3600.0,
    }


def sum_e1(path, det_ids=None):
    root = ET.parse(path).getroot()
    total = 0.0
    per_interval = {}
    for iv in root.findall("interval"):
        if det_ids and iv.get("id") not in det_ids:
            continue
        v = float(iv.get("nVehContrib", 0) or 0)
        total += v
        b = float(iv.get("begin"))
        per_interval[b] = per_interval.get(b, 0.0) + v
    return total, per_interval


def count_teleports(path):
    # tripinfo doesn't hold teleports; check summary for 'teleports' if present
    return None


def main():
    rows = {}
    for m in MODES:
        od = os.path.join(BASE, "outputs", m)
        rows[m] = parse_tripinfo(os.path.join(od, "tripinfo.xml"))

    print("=" * 92)
    print("SCENARIO COMPARISON (identical demand, seed=42, real 2->1 merge lane-drop bottleneck)")
    print("=" * 92)
    hdr = f"{'metric':<26}{'closed':>16}{'open':>16}{'dynamic':>16}"
    print(hdr)
    print("-" * 92)
    def line(label, key, fmt="{:.2f}", pct=False):
        base = rows["closed"][key]
        cells = []
        for m in MODES:
            v = rows[m][key]
            s = fmt.format(v)
            if pct and m != "closed" and base:
                s += f" ({(v-base)/base*100:+.1f}%)"
            cells.append(s)
        print(f"{label:<26}" + "".join(f"{c:>16}" for c in cells))
    line("completed vehicles", "completed", "{:.0f}", pct=True)
    line("net mean speed (m/s)", "net_mean_speed", "{:.2f}", pct=True)
    line("mean duration (s)", "mean_duration", "{:.1f}", pct=True)
    line("mean timeLoss (s)", "mean_timeloss", "{:.1f}", pct=True)
    line("total timeLoss (veh-h)", "total_timeloss_h", "{:.1f}", pct=True)
    line("mean departDelay (s)", "mean_departdelay", "{:.1f}", pct=True)
    line("total veh-hours", "total_veh_hours", "{:.1f}", pct=True)
    print("-" * 92)

    print("\nSHOULDER-LANE E1 DETECTOR (id=e1_shoulder, lane w_0, pos 500):")
    for m in MODES:
        path = os.path.join(BASE, "outputs", m, "det_shoulder.xml")
        total, per = sum_e1(path, {"e1_shoulder"})
        active = sorted(b for b, v in per.items() if v > 0)
        span = f"{active[0]:.0f}-{active[-1]+60:.0f}s" if active else "none"
        print(f"  {m:<9} total shoulder vehicles = {total:.0f} ; flow-active window = {span}")
        if m == "dynamic":
            nz = [(int(b), int(v)) for b, v in sorted(per.items()) if v > 0]
            print(f"           dynamic per-interval (begin,veh): {nz}")

    print("\nBOTTLENECK EXIT E1 DISCHARGE (ids e1_exit_s/0, lanes w_0/w_1 at pos 1050):")
    for m in MODES:
        path = os.path.join(BASE, "outputs", m, "det_exit.xml")
        total, per = sum_e1(path, EXIT_IDS)
        peak = sum(v for b, v in per.items() if 600 <= b < 1800)
        peak_rate = peak / 1200.0 * 3600.0
        print(f"  {m:<9} total exit veh = {total:.0f} ; mean peak-window discharge = {peak_rate:.0f} veh/h")


if __name__ == "__main__":
    main()
