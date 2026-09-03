"""
Compare a baseline (no charge-aware rerouting) vs a stationfinder-enabled EV-charging scenario.

Usage:
    python analyze_ev_charging.py --baseline scenario_baseline/ --stationfinder scenario_stationfinder/

Each scenario directory is expected to contain battery.xml (--battery-output), chargingstations.xml
(--chargingstations-output), and optionally stderr.txt (sumo's own stderr, used to count
"battery depleted" warnings and "removed after breaking down" rescue events -- these appear in
the log rather than any output XML).

Parses battery-output with a streaming iterparse (it records one entry per vehicle per step, so
even a modest scenario can produce tens of megabytes) and reports: how many vehicles ran out of
charge, the final state-of-charge distribution, energy delivered per charging station, and how
many charging sessions were triggered.
"""

import argparse
import os
import re
import xml.etree.ElementTree as ET

DEPLETE_WH = 0.01  # actualBatteryCapacity at/below this Wh counts as "ran out of charge"


def parse_battery(path):
    """Stream battery-output; return {veh_id: {min, final, max}} in Wh."""
    veh = {}
    for _ev, el in ET.iterparse(path, events=("end",)):
        if el.tag != "vehicle":
            continue
        vid = el.get("id")
        act = float(el.get("actualBatteryCapacity"))
        mx = float(el.get("maximumBatteryCapacity"))
        d = veh.get(vid)
        if d is None:
            veh[vid] = {"min": act, "final": act, "max": mx}
        else:
            if act < d["min"]:
                d["min"] = act
            d["final"] = act
            d["max"] = mx
        el.clear()
    return veh


def parse_charging(path):
    """Return (per-station totals, list of (station, vehicle, energy_Wh, begin, end) sessions)."""
    root = ET.parse(path).getroot()
    stations = {}
    sessions = []
    for cs in root.findall("chargingStation"):
        sid = cs.get("id")
        stations[sid] = {
            "totalEnergyCharged_Wh": float(cs.get("totalEnergyCharged", 0.0)),
            "chargingSteps": int(cs.get("chargingSteps", 0)),
            "n_vehicle_records": len(cs.findall("vehicle")),
        }
        for v in cs.findall("vehicle"):
            sessions.append(
                (
                    sid, v.get("id"),
                    float(v.get("totalEnergyChargedIntoVehicle", 0.0)),
                    float(v.get("chargingBegin", -1)),
                    float(v.get("chargingEnd", -1)),
                )
            )
    return stations, sessions


def count_breakdowns(stderr_path):
    if not os.path.exists(stderr_path):
        return 0, 0
    txt = open(stderr_path).read()
    broke = len(re.findall(r"after breaking down", txt))
    depl = len(re.findall(r"is depleted", txt))
    return broke, depl


def soc_hist(vehmap):
    bins = [0, 0.05, 0.10, 0.20, 0.40, 0.60, 0.80, 1.01]
    labels = ["0-5%", "5-10%", "10-20%", "20-40%", "40-60%", "60-80%", "80-100%"]
    counts = [0] * len(labels)
    for d in vehmap.values():
        soc = d["final"] / d["max"] if d["max"] else 0
        for i in range(len(labels)):
            if bins[i] <= soc < bins[i + 1]:
                counts[i] += 1
                break
    return labels, counts


def analyze(name, sdir):
    bat = parse_battery(os.path.join(sdir, "battery.xml"))
    stations, sessions = parse_charging(os.path.join(sdir, "chargingstations.xml"))
    broke, depl_warn = count_breakdowns(os.path.join(sdir, "stderr.txt"))

    n = len(bat)
    ran_out = sum(1 for d in bat.values() if d["min"] <= DEPLETE_WH)
    below_safety = sum(1 for d in bat.values() if d["min"] / d["max"] <= 0.05)
    charged_vehicles = set(s[1] for s in sessions)
    labels, counts = soc_hist(bat)

    print(f"\n===== {name} =====")
    print(f"vehicles tracked in battery-output : {n}")
    print(f"ran out of charge (min <= {DEPLETE_WH} Wh): {ran_out}")
    print(f"reached <= 5% SoC at some point      : {below_safety}")
    print(f"'battery depleted' warnings          : {depl_warn}")
    print(f"removed after breaking down          : {broke}")
    print(f"distinct vehicles that charged        : {len(charged_vehicles)}")
    print(f"total charging sessions               : {len(sessions)}")
    print("energy delivered per station (kWh):")
    tot = 0.0
    for sid, s in stations.items():
        kwh = s["totalEnergyCharged_Wh"] / 1000.0
        tot += kwh
        print(f"    {sid}: {kwh:8.2f} kWh  ({s['n_vehicle_records']} veh records, {s['chargingSteps']} charging steps)")
    print(f"    TOTAL delivered: {tot:8.2f} kWh")
    print("final SoC distribution:")
    for lab, c in zip(labels, counts):
        print(f"    {lab:>8}: {c:4d}  {'#' * (c // 3)}")
    return {
        "n": n, "ran_out": ran_out, "below_safety": below_safety,
        "broke": broke, "depl_warn": depl_warn,
        "charged_vehicles": len(charged_vehicles), "sessions": len(sessions),
        "total_kwh": tot,
    }


def main():
    ap = argparse.ArgumentParser(description="Compare baseline vs stationfinder EV-charging scenarios.")
    ap.add_argument("--baseline", required=True, help="Directory with battery.xml/chargingstations.xml/stderr.txt for the no-rerouting run")
    ap.add_argument("--stationfinder", required=True, help="Same, for the charge-aware-rerouting run")
    args = ap.parse_args()
    b = analyze("BASELINE (no stationfinder)", args.baseline)
    s = analyze("STATIONFINDER (charge-aware reroute)", args.stationfinder)

    print("\n===== COMPARISON =====")
    print(f"stranded (ran-out/broken-down):  baseline={b['ran_out']}  stationfinder={s['broke']}")
    reduced = b["ran_out"] - s["broke"]
    pct = 100.0 * reduced / b["ran_out"] if b["ran_out"] else 0
    print(f"reduction in stranded vehicles:  {reduced}  ({pct:.1f}% fewer)")
    print(f"charging events triggered:       baseline={b['sessions']}  stationfinder={s['sessions']}")
    print(f"energy delivered total:          baseline={b['total_kwh']:.1f} kWh  stationfinder={s['total_kwh']:.1f} kWh")


if __name__ == "__main__":
    main()
