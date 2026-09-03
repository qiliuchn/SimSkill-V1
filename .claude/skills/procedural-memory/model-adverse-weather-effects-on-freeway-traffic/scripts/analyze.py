"""
Weather study analyzer. For each scenario, from RAW output files:
  - discharge capacity  = sum over the 2 downstream E1 lanes of nVehContrib in the
                          saturated window, /window*3600  [veh/h]
  - efficiency (tripinfo): throughput, mean speed (routeLength/duration),
                          mean travel time (duration), total & mean time loss
  - safety (SSM): total conflicts, rear-end (following) conflicts, worst(min) TTC,
                  #conflicts with TTC<1.5, max DRAC, #collisions(type 111)
  - queue (E2): max jam length (m), mean occupancy in window
  - teleports (summary, last step -- cumulative field)
Emits a comparison table (CSV + printed) and a JSON blob.
"""
import csv
import json
import os
import xml.etree.ElementTree as ET

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outputs")
WARMUP, WIN_END = 600.0, 1800.0   # saturated measurement window (flow runs 0..1800)
FOLLOWING = {2, 3, 18}
COLLISION = {111}

MAIN = ["dry", "wet", "snow"]
MECH = ["dry", "fric_only_snow", "vtype_only_snow", "snow"]
MOD = ["dry_mod", "wet_mod", "snow_mod"]
SAFETY_C = ["dry", "snow", "snow_underadapted"]
ALL = ["dry", "wet", "snow", "fric_only_snow", "vtype_only_snow",
       "dry_mod", "wet_mod", "snow_mod", "snow_underadapted"]


def fnum(x):
    if x is None or x == "NA":
        return None
    try:
        return float(x)
    except ValueError:
        return None


def discharge(e1_path):
    """Sum per-lane E1 flow in the window -> station discharge veh/h; also per-interval station flow."""
    root = ET.parse(e1_path).getroot()
    per_interval = {}  # begin -> summed nVehContrib across lanes
    n_total = 0
    for iv in root.findall("interval"):
        b = float(iv.get("begin"))
        if b < WARMUP or float(iv.get("end")) > WIN_END:
            continue
        n = int(iv.get("nVehContrib"))
        per_interval[b] = per_interval.get(b, 0) + n
        n_total += n
    dur = WIN_END - WARMUP
    q = n_total / dur * 3600.0
    # station flow per interval (veh/h) for steadiness check
    series = {b: cnt / 60.0 * 3600.0 for b, cnt in sorted(per_interval.items())}
    return q, series


def efficiency(tripinfo_path):
    root = ET.parse(tripinfo_path).getroot()
    durs, losses, speeds = [], [], []
    for ti in root.findall("tripinfo"):
        d = float(ti.get("duration"))
        rl = float(ti.get("routeLength"))
        durs.append(d)
        losses.append(float(ti.get("timeLoss")))
        speeds.append(rl / d if d > 0 else 0.0)
    n = len(durs)
    return {
        "throughput_completed": n,
        "mean_travel_time_s": round(sum(durs) / n, 1),
        "mean_speed_ms": round(sum(speeds) / n, 2),
        "mean_speed_kmh": round(sum(speeds) / n * 3.6, 1),
        "total_timeloss_s": round(sum(losses), 0),
        "mean_timeloss_s": round(sum(losses) / n, 1),
    }


def safety(ssm_path):
    root = ET.parse(ssm_path).getroot()
    ttcs, dracs = [], []
    n_conf = n_follow = n_coll = 0
    for c in root.findall("conflict"):
        n_conf += 1
        t = c.find("minTTC")
        if t is not None:
            v = fnum(t.get("value"))
            tc = t.get("type")
            if v is not None:
                ttcs.append(v)
            if tc is not None and tc != "NA" and int(tc) in FOLLOWING:
                n_follow += 1
            if tc is not None and tc != "NA" and int(tc) in COLLISION:
                n_coll += 1
        dr = c.find("maxDRAC")
        if dr is not None:
            v = fnum(dr.get("value"))
            if v is not None:
                dracs.append(v)
    return {
        "total_conflicts": n_conf,
        "rear_end_conflicts": n_follow,
        "collisions_type111": n_coll,
        "min_TTC_s": round(min(ttcs), 2) if ttcs else None,
        "conflicts_TTC_lt_1.5": sum(1 for x in ttcs if x < 1.5),
        "max_DRAC_ms2": round(max(dracs), 2) if dracs else None,
    }


def queue(e2_path):
    root = ET.parse(e2_path).getroot()
    maxjam, occs = 0.0, []
    for iv in root.findall("interval"):
        b = float(iv.get("begin"))
        if b < WARMUP or float(iv.get("end")) > WIN_END:
            continue
        mj = fnum(iv.get("maxJamLengthInMeters")) or 0.0
        maxjam = max(maxjam, mj)
        oc = fnum(iv.get("meanOccupancy"))
        if oc is not None and oc >= 0:
            occs.append(oc)
    return {
        "max_jam_len_m": round(maxjam, 1),
        "mean_occupancy_pct": round(sum(occs) / len(occs), 1) if occs else None,
    }


def teleports(summary_path):
    root = ET.parse(summary_path).getroot()
    tp = 0
    maxv = 0
    for step in root.findall("step"):
        tp = int(step.get("teleports", "0"))
        maxv = max(maxv, int(step.get("running", "0")))
    return tp, maxv


def analyze(name):
    d = os.path.join(OUT, name)
    q, series = discharge(os.path.join(d, "e1.xml"))
    eff = efficiency(os.path.join(d, "tripinfo.xml"))
    saf = safety(os.path.join(d, "ssm.xml"))
    qu = queue(os.path.join(d, "e2.xml"))
    tp, maxv = teleports(os.path.join(d, "summary.xml"))
    row = {"scenario": name, "discharge_capacity_vph": round(q)}
    row.update(eff); row.update(saf); row.update(qu)
    row["teleports"] = tp
    row["max_running_veh"] = maxv
    return row, series


def main():
    rows = {}
    series_all = {}
    for name in ALL:
        rows[name], series_all[name] = analyze(name)

    # write full table
    fields = list(rows["dry"].keys())
    with open(os.path.join(OUT, "comparison_table.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for name in ALL:
            w.writerow(rows[name])

    with open(os.path.join(OUT, "metrics.json"), "w") as f:
        json.dump(rows, f, indent=2)

    # capacity-drop percentages relative to dry
    capd = rows["dry"]["discharge_capacity_vph"]
    drops = {}
    for name in MAIN:
        c = rows[name]["discharge_capacity_vph"]
        drops[name] = round(100 * (capd - c) / capd, 1)

    print("=== SATURATED-WINDOW STATION DISCHARGE FLOW (veh/h) per 60s interval ===")
    for name in MAIN:
        s = series_all[name]
        vals = " ".join(f"{int(v)}" for v in s.values())
        print(f"  {name:16s}: {vals}")

    print("\n=== COMPARISON TABLE ===")
    hdr = ["scenario", "discharge_capacity_vph", "throughput_completed", "mean_speed_kmh",
           "mean_travel_time_s", "total_timeloss_s", "min_TTC_s", "total_conflicts",
           "rear_end_conflicts", "conflicts_TTC_lt_1.5", "max_DRAC_ms2", "max_jam_len_m", "teleports"]
    print("  " + " | ".join(hdr))
    for name in ALL:
        print("  " + " | ".join(str(rows[name][h]) for h in hdr))

    print("\n=== CAPACITY DROP vs DRY ===")
    for name in MAIN:
        print(f"  {name}: discharge={rows[name]['discharge_capacity_vph']} veh/h, drop={drops[name]}%")

    print("\n=== MECHANISM CHECK (identical => that mechanism drove the effect) ===")
    keycols = ["discharge_capacity_vph", "throughput_completed", "mean_travel_time_s",
               "total_conflicts", "min_TTC_s"]
    for name in MECH:
        print(f"  {name:16s}: " + ", ".join(f"{k}={rows[name][k]}" for k in keycols))

    print("\n=== (b) MODERATE UNDERSATURATED DEMAND (1500 vph): clean absolute speed/TT ===")
    for name in MOD:
        r = rows[name]
        print(f"  {name:9s}: mean_speed={r['mean_speed_kmh']} km/h, "
              f"travel_time={r['mean_travel_time_s']} s, mean_timeloss={r['mean_timeloss_s']} s, "
              f"throughput={r['throughput_completed']}")

    print("\n=== (c) SAFETY: full-adaptation snow vs UNDER-ADAPTED snow (dry gaps, snow braking) ===")
    for name in SAFETY_C:
        r = rows[name]
        print(f"  {name:18s}: min_TTC={r['min_TTC_s']} s, conflicts={r['total_conflicts']}, "
              f"TTC<1.5={r['conflicts_TTC_lt_1.5']}, max_DRAC={r['max_DRAC_ms2']}, "
              f"collisions={r['collisions_type111']}, throughput={r['throughput_completed']}")

    print(json.dumps({"drops_pct_vs_dry": drops}, indent=2))


if __name__ == "__main__":
    main()
