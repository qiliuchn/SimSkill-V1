#!/usr/bin/env python3
"""
Leg-level energy decomposition from raw battery-output, used for
  * H1's "auxiliary share grows with congestion" claim (aux share vs realised leg speed)
  * the corrected auxiliary accounting

Corrected auxiliary accounting (established empirically, see outputs/aux_accounting.json):
SUMO charges `constantPowerIntake` to the battery on every step EXCEPT steps on which the
vehicle is actively taking charge at a chargingStation -- on those steps the auxiliary load
is implicitly covered by the charger and `energyConsumed` is unchanged.  So
    aux_energy_from_battery = P_aux * (steps - steps_charging_with_energy_flow)
NOT P_aux * time_in_network.
"""
import os, sys, json, statistics, collections
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))


def legs(battery_xml, aux_w, bus_prefix="bus_"):
    """Split each bus's per-step battery record into directional legs."""
    cur = {}
    out = []
    t = 0.0
    for ev, el in ET.iterparse(battery_xml, events=("start", "end")):
        if ev == "start" and el.tag == "timestep":
            t = float(el.get("time"))
            continue
        if ev == "end" and el.tag == "vehicle":
            vid = el.get("id")
            if vid.startswith(bus_prefix):
                a = el.attrib
                lane = a.get("lane", "")
                edge = lane.rsplit("_", 1)[0] if lane else ""
                seg = ("EB" if (edge.startswith("EB_") or edge == "TW_OUT") else
                       "WB" if (edge.startswith("WB_") or edge == "TE_OUT") else "TERM")
                cons = float(a["energyConsumed"])
                spd = float(a["speed"])
                chg = float(a["energyCharged"])
                d = cur.get(vid)
                if d is None or d["seg"] != seg:
                    if d is not None and d["seg"] in ("EB", "WB") and d["n"] > 60:
                        out.append(d)
                    d = cur[vid] = dict(veh=vid, seg=seg, t0=t, t1=t, n=0, dist=0.0,
                                        cons=0.0, regen=0.0, chg_steps=0)
                d["t1"] = t
                d["n"] += 1
                d["dist"] += spd
                if cons > 0:
                    d["cons"] += cons
                else:
                    d["regen"] += -cons
                if chg > 0:
                    d["chg_steps"] += 1
            el.clear()
        elif ev == "end" and el.tag == "timestep":
            el.clear()
    for d in cur.values():
        if d["seg"] in ("EB", "WB") and d["n"] > 60:
            out.append(d)
    for d in out:
        d["dur_s"] = d["n"]
        d["dist_km"] = d["dist"] / 1000.0
        d["net_wh"] = d["cons"] - d["regen"]
        d["aux_wh"] = aux_w * (d["n"] - d["chg_steps"]) / 3600.0
        d["mean_speed_kmh"] = 3.6 * d["dist"] / max(d["n"], 1)
        d["kwh_per_km"] = d["net_wh"] / 1000.0 / max(d["dist_km"], 1e-9)
        d["aux_share"] = d["aux_wh"] / d["net_wh"] if d["net_wh"] > 0 else None
    return out


def summarise(L, peak=(3600.0, 10800.0)):
    R = {}
    for seg in ("EB", "WB"):
        s = [d for d in L if d["seg"] == seg]
        pk = [d for d in s if peak[0] <= d["t0"] < peak[1]]
        op = [d for d in s if not (peak[0] <= d["t0"] < peak[1])]
        def blk(v):
            if not v:
                return None
            return dict(n=len(v),
                        dur_s=round(statistics.mean(d["dur_s"] for d in v), 1),
                        speed_kmh=round(statistics.mean(d["mean_speed_kmh"] for d in v), 2),
                        kwh_per_km=round(statistics.mean(d["kwh_per_km"] for d in v), 4),
                        net_kwh=round(statistics.mean(d["net_wh"] for d in v) / 1000, 3),
                        aux_kwh=round(statistics.mean(d["aux_wh"] for d in v) / 1000, 3),
                        aux_share=round(statistics.mean([d["aux_share"] for d in v
                                                         if d["aux_share"] is not None] or [0]), 4))
        R[seg] = dict(all=blk(s), peak=blk(pk), offpeak=blk(op))
    # aux share vs speed, binned
    bins = collections.defaultdict(list)
    for d in L:
        if d["aux_share"] is None:
            continue
        b = int(d["mean_speed_kmh"] // 3) * 3
        bins[b].append(d)
    R["aux_share_by_speed_bin"] = {
        f"{b}-{b+3} km/h": dict(n=len(v),
                                aux_share=round(statistics.mean(x["aux_share"] for x in v), 4),
                                kwh_per_km=round(statistics.mean(x["kwh_per_km"] for x in v), 4))
        for b, v in sorted(bins.items())}
    return R


if __name__ == "__main__":
    a7 = sys.argv[1]      # run dir with aux=7000 battery.xml
    a0 = sys.argv[2]      # run dir with aux=0    battery.xml
    out = sys.argv[3]
    L7 = legs(os.path.join(a7, "battery.xml"), 7000)
    L0 = legs(os.path.join(a0, "battery.xml"), 0)
    R = dict(aux7000=summarise(L7), aux0=summarise(L0))
    # paired leg-by-leg: same (veh, leg index) -> true aux energy of that leg
    key = lambda d: (d["veh"], d["seg"], round(d["t0"] / 1.0))
    idx7 = {}
    for d in L7:
        idx7.setdefault((d["veh"], d["seg"]), []).append(d)
    idx0 = {}
    for d in L0:
        idx0.setdefault((d["veh"], d["seg"]), []).append(d)
    pairs = []
    for k in idx7:
        a, b = sorted(idx7[k], key=lambda x: x["t0"]), sorted(idx0.get(k, []), key=lambda x: x["t0"])
        for x, y in zip(a, b):
            pairs.append(dict(veh=x["veh"], seg=x["seg"], t0=x["t0"],
                              dur_s=x["dur_s"], speed=x["mean_speed_kmh"],
                              net7=x["net_wh"], net0=y["net_wh"],
                              aux_true=x["net_wh"] - y["net_wh"],
                              aux_pred=x["aux_wh"]))
    for p in pairs:
        p["aux_share_true"] = p["aux_true"] / p["net7"] if p["net7"] > 0 else None
    R["paired_leg_aux"] = dict(
        n=len(pairs),
        mean_aux_true_wh=round(statistics.mean(p["aux_true"] for p in pairs), 2),
        mean_aux_pred_wh=round(statistics.mean(p["aux_pred"] for p in pairs), 2),
        ratio=round(statistics.mean(p["aux_true"] for p in pairs) /
                    statistics.mean(p["aux_pred"] for p in pairs), 4))
    for seg in ("EB", "WB"):
        s = [p for p in pairs if p["seg"] == seg]
        pk = [p for p in s if 3600 <= p["t0"] < 10800]
        op = [p for p in s if not (3600 <= p["t0"] < 10800)]
        R["paired_leg_aux"][seg] = {
            lab: dict(n=len(v), dur_s=round(statistics.mean(p["dur_s"] for p in v), 1),
                      speed_kmh=round(statistics.mean(p["speed"] for p in v), 2),
                      aux_true_kwh=round(statistics.mean(p["aux_true"] for p in v) / 1000, 4),
                      net_kwh=round(statistics.mean(p["net7"] for p in v) / 1000, 4),
                      aux_share_true=round(statistics.mean([p["aux_share_true"] for p in v
                                                           if p["aux_share_true"] is not None] or [0]), 4))
            for lab, v in (("peak", pk), ("offpeak", op)) if v}
    json.dump(R, open(out, "w"), indent=1)
    print(json.dumps(R, indent=1))
