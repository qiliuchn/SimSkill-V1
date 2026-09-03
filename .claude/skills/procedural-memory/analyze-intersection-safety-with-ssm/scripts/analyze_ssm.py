"""
Parse SUMO SSM-device output plus tripinfo/summary for one or more scenario variants and produce
a combined SAFETY + EFFICIENCY comparison.

Usage:
    python analyze_ssm.py --variant "priority=outputs/priority/ssm.xml,outputs/priority/tripinfo.xml,outputs/priority/summary.xml" \
        --variant "signalized=outputs/signalized/ssm.xml,outputs/signalized/tripinfo.xml,outputs/signalized/summary.xml" \
        --out-dir analysis/

Each --variant is "<name>=<ssm.xml>,<tripinfo.xml>,<summary.xml>", repeatable for any number of
variants (not just 2).

SSM output schema (verified against https://sumo.dlr.de/docs/Simulation/Output/SSM_Device.html):
    <SSMLog>
      <conflict begin= end= ego= foe=>
          <minTTC   value= time= type= .../>   # min Time-To-Collision  (s)  ("NA" if undefined)
          <maxDRAC  value= time= type= .../>   # max Deceleration Rate to Avoid Crash (m/s^2)
          <PET      value= time= type= .../>   # Post-Encroachment Time (s)  ("NA" for pure following)
          <maxMDRAC value= time= type= .../>   # max Modified DRAC (m/s^2), accounts for reaction time
      </conflict>
      <globalMeasures ego=...>                 # per-vehicle, not per-pair
          <maxBR value= time= .../>            # max Brake Rate (m/s^2)
          <minSGAP .../> <minTGAP .../>
      </globalMeasures>
    </SSMLog>

Encounter type codes (the `type` attribute on each measure): 2,3,18 FOLLOWING (rear-end);
6,7,8,19 MERGING; 10-17 CROSSING (angle); 111 COLLISION.
"""

import argparse
import csv
import json
import xml.etree.ElementTree as ET

FOLLOWING = {2, 3, 18}
MERGING = {6, 7, 8, 19}
CROSSING = {10, 11, 12, 13, 14, 15, 16, 17}
COLLISION = {111}


def parse_args():
    p = argparse.ArgumentParser(description="Compare SSM safety + tripinfo/summary efficiency metrics across scenario variants.")
    p.add_argument(
        "--variant",
        action="append",
        required=True,
        dest="variants",
        help='"<name>=<ssm.xml>,<tripinfo.xml>,<summary.xml>", repeatable',
    )
    p.add_argument("--ttc-threshold", type=float, default=1.5, help="TTC (s) below which a conflict counts as severe (default: 1.5)")
    p.add_argument("--pet-threshold", type=float, default=1.0, help="PET (s) below which a conflict counts as severe (default: 1.0)")
    p.add_argument("--out-dir", default="analysis", help="Output directory (default: analysis/)")
    return p.parse_args()


def fnum(x):
    if x is None or x == "NA":
        return None
    try:
        return float(x)
    except ValueError:
        return None


def classify(type_code):
    if type_code in COLLISION:
        return "collision"
    if type_code in CROSSING:
        return "crossing"
    if type_code in MERGING:
        return "merging"
    if type_code in FOLLOWING:
        return "following"
    return "other"


def parse_ssm(path):
    root = ET.parse(path).getroot()
    conflicts = []
    max_br = 0.0
    for el in root:
        if el.tag == "conflict":
            c = {"begin": fnum(el.get("begin")), "end": fnum(el.get("end")), "ego": el.get("ego"), "foe": el.get("foe")}
            for m in el:
                if m.tag in ("minTTC", "maxDRAC", "PET", "maxMDRAC"):
                    c[m.tag] = fnum(m.get("value"))
                    c[f"{m.tag}_type"] = int(m.get("type")) if m.get("type") not in (None, "NA") else None
            conflicts.append(c)
        elif el.tag == "globalMeasures":
            for m in el:
                if m.tag == "maxBR":
                    v = fnum(m.get("value"))
                    if v is not None and v > max_br:
                        max_br = v
    return conflicts, max_br


def category_of(c):
    for key in ("minTTC_type", "PET_type", "maxDRAC_type"):
        t = c.get(key)
        if t is not None:
            cat = classify(t)
            if cat != "other":
                return cat
    return "other"


def safety_metrics(path, ttc_threshold, pet_threshold):
    conflicts, max_br = parse_ssm(path)
    ttcs = [c["minTTC"] for c in conflicts if c.get("minTTC") is not None]
    pets = [c["PET"] for c in conflicts if c.get("PET") is not None]
    dracs = [c["maxDRAC"] for c in conflicts if c.get("maxDRAC") is not None]
    cats = {"following": 0, "merging": 0, "crossing": 0, "collision": 0, "other": 0}
    for c in conflicts:
        cats[category_of(c)] += 1
    return {
        "total_conflicts": len(conflicts),
        "cat_following": cats["following"],
        "cat_merging": cats["merging"],
        "cat_crossing": cats["crossing"],
        "cat_collision": cats["collision"],
        "n_with_TTC": len(ttcs),
        f"TTC_lt_{ttc_threshold}": sum(1 for x in ttcs if x < ttc_threshold),
        "worst_TTC": round(min(ttcs), 2) if ttcs else None,
        "n_with_PET": len(pets),
        f"PET_lt_{pet_threshold}": sum(1 for x in pets if x < pet_threshold),
        "worst_PET": round(min(pets), 2) if pets else None,
        "max_DRAC": round(max(dracs), 2) if dracs else None,
        "max_BR": round(max_br, 2),
    }


def efficiency_metrics(tripinfo_path, summary_path):
    root = ET.parse(tripinfo_path).getroot()
    durs, waits, losses, speeds = [], [], [], []
    for ti in root.findall("tripinfo"):
        d = float(ti.get("duration"))
        rl = float(ti.get("routeLength"))
        durs.append(d)
        waits.append(float(ti.get("waitingTime")))
        losses.append(float(ti.get("timeLoss")))
        speeds.append(rl / d if d > 0 else 0.0)
    n = len(durs)
    if n == 0:
        raise SystemExit(f"{tripinfo_path}: no <tripinfo> elements found -- check the run for gridlock/config errors.")

    # summary.xml's "teleports" attribute is a CUMULATIVE running count, not a
    # per-step delta -- take the last step's value, don't sum across steps
    # (summing would wildly over-count; verified against raw output).
    teleports = 0
    sroot = ET.parse(summary_path).getroot()
    for step in sroot.findall("step"):
        teleports = int(step.get("teleports", "0"))

    mean = lambda a: round(sum(a) / len(a), 2) if a else None
    return {
        "throughput_completed": n,
        "mean_duration_s": mean(durs),
        "mean_waiting_s": mean(waits),
        "mean_timeloss_s": mean(losses),
        "mean_speed_ms": mean(speeds),
        "teleports": teleports,
    }


def main():
    args = parse_args()
    import os
    os.makedirs(args.out_dir, exist_ok=True)

    variants = {}
    for spec in args.variants:
        name, files = spec.split("=", 1)
        ssm, trip, summ = files.split(",")
        variants[name] = {
            "safety": safety_metrics(ssm, args.ttc_threshold, args.pet_threshold),
            "efficiency": efficiency_metrics(trip, summ),
        }

    with open(os.path.join(args.out_dir, "metrics.json"), "w") as f:
        json.dump(variants, f, indent=2)

    fieldnames = ["variant"] + list(next(iter(variants.values()))["safety"].keys()) + list(next(iter(variants.values()))["efficiency"].keys())
    with open(os.path.join(args.out_dir, "comparison.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for name, m in variants.items():
            row = {"variant": name}
            row.update(m["safety"])
            row.update(m["efficiency"])
            w.writerow(row)

    print(json.dumps(variants, indent=2))
    print(f"\nSaved: {os.path.join(args.out_dir, 'metrics.json')}, {os.path.join(args.out_dir, 'comparison.csv')}")


if __name__ == "__main__":
    main()
