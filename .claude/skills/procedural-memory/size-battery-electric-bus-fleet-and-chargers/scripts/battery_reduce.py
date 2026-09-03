#!/usr/bin/env python3
"""
Streaming reducer for SUMO --battery-output.

Produces, per bus:
  * SOC trace (Wh) at 10 s resolution + every terminal event
  * cumulative traction / auxiliary / regenerated / charged energy
  * per-direction (EB / WB) energy and distance -> kWh/km by direction
  * an explicit energy-balance residual

Verified SUMO 1.27.1 semantics (see scripts/probe_battery_semantics.py):
  - actualBatteryCapacity_i = actualBatteryCapacity_(i-1) - energyConsumed_i + energyCharged_i
    EXCEPT while the vehicle is moving inside a chargingStation footprint after its
    stop has ended (timeStopped == 0): then energyCharged is reported but NOT credited.
    The credited energy equals the chargingstations-output total.
  - totalEnergyConsumed accumulates only the POSITIVE part of energyConsumed;
    totalEnergyRegenerated accumulates the magnitude of the negative part.
  - actualBatteryCapacity is CLAMPED at 0 -- it never goes negative.  A "virtual"
    unclamped SOC is therefore reconstructed here from the cumulative counters.
"""
import xml.etree.ElementTree as ET
import math, json, os, sys


def reduce_battery(path, bus_prefix="bus_", trace_every=10.0, aux_w=None):
    per = {}
    order = []
    it = ET.iterparse(path, events=("start", "end"))
    t = 0.0
    for ev, el in it:
        if ev == "start" and el.tag == "timestep":
            t = float(el.get("time"))
            continue
        if ev != "end":
            continue
        if el.tag == "vehicle":
            vid = el.get("id")
            if vid.startswith(bus_prefix):
                a = el.attrib
                cap = float(a["actualBatteryCapacity"])
                cons = float(a["energyConsumed"])
                chg = float(a["energyCharged"])
                tcons = float(a["totalEnergyConsumed"])
                treg = float(a["totalEnergyRegenerated"])
                spd = float(a["speed"])
                lane = a.get("lane", "")
                edge = lane.rsplit("_", 1)[0] if lane else ""
                tstop = float(a.get("timeStopped", 0))
                csid = a.get("chargingStationId", "NULL")
                d = per.get(vid)
                if d is None:
                    d = per[vid] = dict(
                        t0=t, cap0=cap + cons - chg, maxcap=float(a["maximumBatteryCapacity"]),
                        trace=[], credited=0.0, reported_chg=0.0, uncredited=0.0,
                        dist={"EB": 0.0, "WB": 0.0, "TERM": 0.0},
                        cons={"EB": 0.0, "WB": 0.0, "TERM": 0.0},
                        regen={"EB": 0.0, "WB": 0.0, "TERM": 0.0},
                        time={"EB": 0.0, "WB": 0.0, "TERM": 0.0},
                        move_time=0.0, stop_time=0.0,
                        last_t=t, last_cap=cap, last_trace=-1e9,
                        tcons=tcons, treg=treg, cap_last=cap,
                        n_zero_soc=0, first_zero_t=None, csids=set(),
                    )
                    order.append(vid)
                dt = t - d["last_t"] if d["trace"] else 1.0
                dt = 1.0
                seg = "EB" if edge.startswith("EB_") else ("WB" if edge.startswith("WB_") else "TERM")
                d["dist"][seg] += spd * dt
                d["time"][seg] += dt
                if cons > 0:
                    d["cons"][seg] += cons
                else:
                    d["regen"][seg] += -cons
                if tstop > 0:
                    d["credited"] += chg
                else:
                    d["uncredited"] += chg
                d["reported_chg"] += chg
                if csid not in ("NULL", ""):
                    d["csids"].add(csid)
                if spd > 0.1:
                    d["move_time"] += dt
                else:
                    d["stop_time"] += dt
                if cap <= 0.0:
                    d["n_zero_soc"] += 1
                    if d["first_zero_t"] is None:
                        d["first_zero_t"] = t
                if t - d["last_trace"] >= trace_every or csid not in ("NULL", ""):
                    d["trace"].append((t, round(cap, 1), round(tcons, 1), round(treg, 1),
                                       round(d["credited"], 1), csid if csid != "NULL" else ""))
                    d["last_trace"] = t
                d["tcons"] = tcons
                d["treg"] = treg
                d["cap_last"] = cap
                d["last_t"] = t
            el.clear()
        elif el.tag == "timestep":
            el.clear()
    out = {}
    for vid in order:
        d = per[vid]
        tot_time = sum(d["time"].values())
        aux = (aux_w * tot_time / 3600.0) if aux_w is not None else None
        # energy balance on the CLAMPED battery
        resid = d["cap0"] - d["tcons"] + d["treg"] + d["credited"] - d["cap_last"]
        virtual_final = d["cap0"] - d["tcons"] + d["treg"] + d["credited"]
        out[vid] = dict(
            t_first=d["t0"], cap0_wh=round(d["cap0"], 2), maxcap_wh=d["maxcap"],
            final_cap_wh=round(d["cap_last"], 2),
            virtual_final_wh=round(virtual_final, 2),
            total_consumed_wh=round(d["tcons"], 2),
            total_regen_wh=round(d["treg"], 2),
            credited_charge_wh=round(d["credited"], 2),
            reported_charge_wh=round(d["reported_chg"], 2),
            uncredited_charge_wh=round(d["uncredited"], 2),
            balance_residual_wh=round(resid, 4),
            dist_m={k: round(v, 1) for k, v in d["dist"].items()},
            cons_wh={k: round(v, 2) for k, v in d["cons"].items()},
            regen_wh={k: round(v, 2) for k, v in d["regen"].items()},
            time_s={k: round(v, 1) for k, v in d["time"].items()},
            move_time_s=d["move_time"], stop_time_s=d["stop_time"],
            aux_energy_wh=(round(aux, 2) if aux is not None else None),
            n_steps_soc_zero=d["n_zero_soc"], first_zero_t=d["first_zero_t"],
            charging_stations_used=sorted(d["csids"]),
            trace=d["trace"],
        )
    return out


def cs_totals(path):
    root = ET.parse(path).getroot()
    tot = {}
    sessions = []
    for st in root:
        tot[st.get("id")] = dict(total_wh=float(st.get("totalEnergyCharged")),
                                 steps=int(st.get("chargingSteps")))
        for v in st:
            sessions.append(dict(station=st.get("id"), veh=v.get("id"),
                                 wh=float(v.get("totalEnergyChargedIntoVehicle")),
                                 begin=float(v.get("chargingBegin")),
                                 end=float(v.get("chargingEnd"))))
    return tot, sessions


if __name__ == "__main__":
    d = sys.argv[1]
    aux = float(sys.argv[2]) if len(sys.argv) > 2 else None
    r = reduce_battery(os.path.join(d, "battery.xml"), aux_w=aux)
    for vid, v in r.items():
        vv = {k: x for k, x in v.items() if k != "trace"}
        print(vid, json.dumps(vv))
