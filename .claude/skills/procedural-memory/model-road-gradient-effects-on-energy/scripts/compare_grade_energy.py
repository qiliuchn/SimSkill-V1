"""
Compare ICE emissions and EV net battery energy across grade variants (e.g.
flat/uphill/downhill), from real tripinfo/battery output -- never assumed
from the grade configuration alone. Verifies monotonic grade-vs-energy
ordering and (for EV) whether a downhill variant's net energy goes negative
(genuine regenerative recovery exceeding consumption).

Usage:
    python compare_grade_energy.py \
        --runs-dir runs --variants downhill,flat,uphill \
        --ice-id-prefix ice_flow --ev-id-prefix ev_flow --ev-initial-charge-wh 20000 \
        --out-md analysis/grade_vs_energy.md --out-json analysis/summary_metrics.json
"""

import argparse
import json
import os
import xml.etree.ElementTree as ET


def parse_args():
    p = argparse.ArgumentParser(description="Compare ICE emissions and EV net energy across road-grade variants.")
    p.add_argument("--runs-dir", required=True, help="Directory containing one subdirectory per variant, each with tripinfo.xml and battery.xml")
    p.add_argument("--variants", required=True, help="Comma-separated variant subdirectory names, in the order to display them (e.g. downhill,flat,uphill)")
    p.add_argument("--ice-id-prefix", default="ice_flow")
    p.add_argument("--ev-id-prefix", default="ev_flow")
    p.add_argument("--ev-initial-charge-wh", type=float, required=True, help="EV actualBatteryCapacity at departure, from the demand vType, for computing net = initial - final")
    p.add_argument("--out-md", default="grade_vs_energy.md")
    p.add_argument("--out-json", default="summary_metrics.json")
    return p.parse_args()


def ice_from_tripinfo(path, prefix):
    out = []
    for _, elem in ET.iterparse(path, events=("end",)):
        if elem.tag == "tripinfo" and elem.get("id", "").startswith(prefix):
            em = elem.find("emissions")
            out.append((float(em.get("CO2_abs")) / 1000.0, float(em.get("fuel_abs")) / 1000.0))
            elem.clear()
    return out


def ev_from_battery(path, prefix):
    last = {}
    for _, elem in ET.iterparse(path, events=("end",)):
        if elem.tag == "vehicle":
            vid = elem.get("id", "")
            if vid.startswith(prefix):
                last[vid] = (float(elem.get("actualBatteryCapacity")),
                             float(elem.get("totalEnergyConsumed")),
                             float(elem.get("totalEnergyRegenerated")))
            elem.clear()
    return last


def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def main():
    args = parse_args()
    variants = args.variants.split(",")
    res = {}
    for v in variants:
        ice = ice_from_tripinfo(os.path.join(args.runs_dir, v, "tripinfo.xml"), args.ice_id_prefix)
        ev = ev_from_battery(os.path.join(args.runs_dir, v, "battery.xml"), args.ev_id_prefix)
        co2 = [c for c, _ in ice]
        fuel = [f for _, f in ice]
        net = [args.ev_initial_charge_wh - a for (a, _, _) in ev.values()]
        cons = [c for (_, c, _) in ev.values()]
        regen = [r for (_, _, r) in ev.values()]
        net_alt = [c - r for (_, c, r) in ev.values()]
        res[v] = dict(n_ice=len(ice), n_ev=len(ev), co2_g=mean(co2), fuel_g=mean(fuel),
                       ev_net_wh=mean(net), ev_cons_wh=mean(cons), ev_regen_wh=mean(regen),
                       ev_net_alt_wh=mean(net_alt))

    lines = ["# Grade vs Energy / Emissions\n",
             "| Metric (per vehicle) | " + " | ".join(f"{v.upper()}" for v in variants) + " |",
             "|---|" + "|".join("---:" for _ in variants) + "|"]
    for label, key, fmt in [
        ("ICE completed vehicles", "n_ice", "{:.0f}"), ("ICE CO2 (g)", "co2_g", "{:.1f}"),
        ("ICE fuel (g)", "fuel_g", "{:.1f}"), ("EV completed vehicles", "n_ev", "{:.0f}"),
        ("EV energy consumed (Wh)", "ev_cons_wh", "{:.1f}"), ("EV energy regenerated (Wh)", "ev_regen_wh", "{:.1f}"),
        ("**EV NET battery energy (Wh)**", "ev_net_wh", "**{:.1f}**"),
    ]:
        lines.append(f"| {label} | " + " | ".join(fmt.format(res[v][key]) for v in variants) + " |")

    lines.append("\n## Verified conclusions\n")
    vals = [res[v] for v in variants]
    mono_asc = all(vals[i]["co2_g"] < vals[i + 1]["co2_g"] for i in range(len(vals) - 1))
    mono_asc_evnet = all(vals[i]["ev_net_wh"] < vals[i + 1]["ev_net_wh"] for i in range(len(vals) - 1))
    lines.append(f"1. **Monotonic across variant order ({'->'.join(variants)}):** "
                 f"ICE CO2 {'PASS' if mono_asc else 'FAIL'}; EV net energy {'PASS' if mono_asc_evnet else 'FAIL'}.")
    consist = all(abs(res[v]["ev_net_wh"] - res[v]["ev_net_alt_wh"]) < 0.5 for v in variants)
    lines.append(f"2. **Battery bookkeeping consistency** (init-final capacity == consumed-regenerated, within 0.5 Wh): "
                 f"{'PASS' if consist else 'FAIL'}.")
    for v in variants:
        net = res[v]["ev_net_wh"]
        lines.append(f"3. **{v}**: net battery energy = {net:.1f} Wh "
                     f"({'NET-NEGATIVE (recovered more than consumed)' if net < 0 else 'net consumption'}).")

    md = "\n".join(lines) + "\n"
    os.makedirs(os.path.dirname(args.out_md) or ".", exist_ok=True)
    with open(args.out_md, "w") as f:
        f.write(md)
    with open(args.out_json, "w") as f:
        json.dump(res, f, indent=2)
    print(md)
    print(f"written: {args.out_md}, {args.out_json}")


if __name__ == "__main__":
    main()
