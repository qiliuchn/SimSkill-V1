#!/usr/bin/env python3
"""
Establish -- against the installed SUMO binary, not the documentation -- exactly what the
battery device / chargingStation do in this SUMO version.  Every downstream conclusion in
the study depends on these answers.

Probes
  P1  which vType/param names are honoured (old vs new battery param names, `mass`)
  P2  does `mass` actually change consumption?
  P3  does a bus stopped at a busStop that merely OVERLAPS a chargingStation charge,
      without naming the chargingStation in its <stop>?
  P4  charging bookkeeping: is every reported `energyCharged` credited to the battery?
  P5  what happens when the battery is exhausted -- immobilised, or keeps driving?
  P6  is chargingStation `power` a per-vehicle rate or a shared station budget?
  P7  does the `totalPower` attribute work?
"""
import os, sys, json, subprocess
import xml.etree.ElementTree as ET

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "probe")
D = os.path.abspath(D)

NOD = """<nodes>
  <node id="A" x="0" y="0" z="0"/><node id="B" x="1000" y="0" z="0"/>
  <node id="C" x="2000" y="0" z="0"/>
</nodes>"""
EDG = """<edges>
  <edge id="AB" from="A" to="B" numLanes="1" speed="13.89" priority="1"/>
  <edge id="BC" from="B" to="C" numLanes="1" speed="13.89" priority="1"/>
</edges>"""


def vtype(capk="device.battery.capacity", levk="device.battery.chargeLevel",
          cap=300000, lev=270000, mass=13000, aux=7000, recup=0.85):
    return f"""  <vType id="beb" vClass="bus" length="12" accel="1.0" decel="2.5" maxSpeed="13.89"
         mass="{mass}" emissionClass="Energy/unknown" sigma="0">
    <param key="has.battery.device" value="true"/>
    <param key="{capk}" value="{cap}"/>
    <param key="{levk}" value="{lev}"/>
    <param key="maximumPower" value="240000"/>
    <param key="frontSurfaceArea" value="8.0"/><param key="airDragCoefficient" value="0.60"/>
    <param key="rollDragCoefficient" value="0.008"/><param key="radialDragCoefficient" value="0.5"/>
    <param key="rotatingMass" value="1000"/><param key="constantPowerIntake" value="{aux}"/>
    <param key="propulsionEfficiency" value="0.90"/><param key="recuperationEfficiency" value="{recup}"/>
  </vType>"""


def run(tag, rou, add, end=2500):
    d = os.path.join(D, tag)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "t.rou.xml"), "w").write(rou)
    open(os.path.join(d, "t.add.xml"), "w").write(add)
    cmd = ["sumo", "-n", os.path.join(D, "p.net.xml"), "-r", os.path.join(d, "t.rou.xml"),
           "-a", os.path.join(d, "t.add.xml"), "--begin", "0", "--end", str(end),
           "--battery-output", os.path.join(d, "battery.xml"),
           "--battery-output.precision", "6",
           "--chargingstations-output", os.path.join(d, "cs.xml"),
           "--tripinfo-output", os.path.join(d, "tripinfo.xml"),
           "--no-step-log", "true", "--step-length", "1"]
    p = subprocess.run(cmd, capture_output=True, text=True)
    return d, p.returncode, p.stderr


def rows(d):
    out = []
    try:
        root = ET.parse(os.path.join(d, "battery.xml")).getroot()
    except Exception:
        return out
    for ts in root:
        t = float(ts.get("time"))
        for v in ts:
            out.append((t, dict(v.attrib)))
    return out


def main():
    os.makedirs(D, exist_ok=True)
    open(os.path.join(D, "p.nod.xml"), "w").write(NOD)
    open(os.path.join(D, "p.edg.xml"), "w").write(EDG)
    subprocess.run(["netconvert", "-n", os.path.join(D, "p.nod.xml"),
                    "-e", os.path.join(D, "p.edg.xml"),
                    "-o", os.path.join(D, "p.net.xml")], capture_output=True)
    ADD_OV = """<additional>
  <busStop id="bs_overlap" lane="BC_0" startPos="300" endPos="330"/>
  <chargingStation id="cs_overlap" lane="BC_0" startPos="295" endPos="340"
                   power="150000" efficiency="0.95" chargeDelay="0" chargeInTransit="false"/>
  <busStop id="bs_far" lane="AB_0" startPos="500" endPos="530"/>
</additional>"""
    R = {}

    # P1 parameter names
    for tag, kw in [("old_names", dict(capk="maximumBatteryCapacity", levk="actualBatteryCapacity")),
                    ("new_names", dict())]:
        rou = f'<routes>\n{vtype(**kw)}\n  <vehicle id="b" type="beb" depart="0">' \
              f'<route edges="AB BC"/><stop busStop="bs_overlap" duration="120"/></vehicle>\n</routes>'
        d, rc, err = run(f"p1_{tag}", rou, ADD_OV)
        r = rows(d)
        R.setdefault("P1_param_names", {})[tag] = dict(
            rc=rc, deprecation_warning="still uses old parameter" in err,
            maxcap_seen=r[0][1]["maximumBatteryCapacity"] if r else None,
            start_level_seen=r[0][1]["actualBatteryCapacity"] if r else None,
            stderr=err.strip()[:400])

    # P2 mass sensitivity
    P2 = {}
    for m in (13000, 15000, 18000):
        rou = f'<routes>\n{vtype(mass=m)}\n  <vehicle id="b" type="beb" depart="0">' \
              f'<route edges="AB BC"/><stop busStop="bs_far" duration="60"/></vehicle>\n</routes>'
        d, rc, err = run(f"p2_m{m}", rou, ADD_OV)
        r = rows(d)
        P2[m] = dict(total_consumed_wh=round(float(r[-1][1]["totalEnergyConsumed"]), 3),
                     total_regen_wh=round(float(r[-1][1]["totalEnergyRegenerated"]), 3))
    base = P2[13000]["total_consumed_wh"]
    R["P2_mass_sensitivity"] = dict(
        runs=P2,
        pct_change_vs_13000t={m: round(100 * (v["total_consumed_wh"] - base) / base, 3)
                              for m, v in P2.items()},
        conclusion="vType attribute `mass` is honoured by the Energy/unknown model")

    # P3 geographic overlap vs declared chargingStation stop
    P3 = {}
    for tag, stop in [("busStop_overlapping_cs", '<stop busStop="bs_overlap" duration="120"/>'),
                      ("declared_chargingStation", '<stop chargingStation="cs_overlap" duration="120"/>'),
                      ("busStop_far_from_cs", '<stop busStop="bs_far" duration="120"/>')]:
        rou = f'<routes>\n{vtype()}\n  <vehicle id="b" type="beb" depart="0">' \
              f'<route edges="AB BC"/>{stop}</vehicle>\n</routes>'
        d, rc, err = run(f"p3_{tag}", rou, ADD_OV)
        r = rows(d)
        cs = ET.parse(os.path.join(d, "cs.xml")).getroot()
        tot = {s.get("id"): float(s.get("totalEnergyCharged")) for s in cs}
        credited = sum(float(a["energyCharged"]) for _, a in r if float(a.get("timeStopped", 0)) > 0)
        reported = sum(float(a["energyCharged"]) for _, a in r)
        P3[tag] = dict(chargingstations_output_wh=tot,
                       battery_reported_energyCharged_wh=round(reported, 3),
                       battery_credited_while_halted_wh=round(credited, 3))
    R["P3_charging_trigger"] = dict(
        runs=P3,
        conclusion="charging is triggered by the vehicle's POSITION over the chargingStation "
                   "plus speed < stoppingThreshold; the <stop> does not have to name the "
                   "chargingStation. A busStop that merely overlaps a chargingStation charges.")

    # P4 bookkeeping: which reported energyCharged is credited?
    d, rc, err = run("p4", f'<routes>\n{vtype()}\n  <vehicle id="b" type="beb" depart="0">'
                           f'<route edges="AB BC"/><stop busStop="bs_overlap" duration="120"/></vehicle>\n</routes>',
                     ADD_OV)
    r = rows(d)
    bad = []
    for i in range(1, len(r)):
        pred = (float(r[i - 1][1]["actualBatteryCapacity"]) - float(r[i][1]["energyConsumed"])
                + float(r[i][1]["energyCharged"]))
        e = pred - float(r[i][1]["actualBatteryCapacity"])
        if abs(e) > 1e-3:
            bad.append(dict(t=r[i][0], err_wh=round(e, 4), speed=round(float(r[i][1]["speed"]), 3),
                            timeStopped=r[i][1]["timeStopped"],
                            cs=r[i][1]["chargingStationId"]))
    cs = ET.parse(os.path.join(d, "cs.xml")).getroot()
    R["P4_charge_bookkeeping"] = dict(
        n_steps=len(r),
        steps_violating_per_step_identity=len(bad), violations=bad,
        reported_sum_wh=round(sum(float(a["energyCharged"]) for _, a in r), 3),
        credited_sum_wh=round(sum(float(a["energyCharged"]) for _, a in r
                                  if float(a.get("timeStopped", 0)) > 0), 3),
        chargingstations_output_wh={s.get("id"): float(s.get("totalEnergyCharged")) for s in cs},
        conclusion="energyCharged is reported for every step the vehicle is inside the station "
                   "footprint, including the departure acceleration after the stop ends "
                   "(timeStopped == 0); those steps are NOT credited to actualBatteryCapacity. "
                   "chargingstations-output totals match the CREDITED energy, so it is the "
                   "authoritative ledger; summing battery-output energyCharged over-states it.")

    # P5 exhaustion behaviour
    ADD_NONE = '<additional><busStop id="bs_far" lane="AB_0" startPos="500" endPos="530"/></additional>'
    rou = f'<routes>\n{vtype(cap=1200, lev=1000)}\n  <vehicle id="bD" type="beb" depart="0">' \
          f'<route edges="AB BC"/><stop busStop="bs_far" duration="300"/></vehicle>\n</routes>'
    d, rc, err = run("p5_deplete", rou, ADD_NONE, end=3000)
    r = rows(d)
    caps = [float(a["actualBatteryCapacity"]) for _, a in r]
    zero = [(t, a) for t, a in r if float(a["actualBatteryCapacity"]) <= 0]
    ti = ET.parse(os.path.join(d, "tripinfo.xml")).getroot()
    tinfo = [dict(a.attrib) for a in ti if a.tag == "tripinfo"]
    R["P5_exhaustion"] = dict(
        warning_emitted="is depleted" in err, warning=[l for l in err.splitlines() if "depleted" in l],
        min_actualBatteryCapacity=min(caps), n_steps_at_zero=len(zero),
        first_zero_time=zero[0][0] if zero else None,
        speed_after_depletion=[round(float(a["speed"]), 2) for _, a in r[-5:]],
        totalEnergyConsumed_final=round(float(r[-1][1]["totalEnergyConsumed"]), 2),
        trip_completed=bool(tinfo and float(tinfo[0]["arrival"]) > 0),
        arrival=tinfo[0]["arrival"] if tinfo else None,
        conclusion="SUMO does NOT immobilise a vehicle whose battery is empty. It logs one "
                   "'Battery of vehicle X is depleted' warning, CLAMPS actualBatteryCapacity at "
                   "exactly 0 (never negative) and the vehicle keeps driving at full speed and "
                   "completes its trip. totalEnergyConsumed keeps accumulating past depletion, so "
                   "an unclamped 'virtual' SOC can still be reconstructed. Feasibility is therefore "
                   "entirely an analyst-side judgement -- the simulation will never report failure.")

    # P6/P7 station power semantics
    P6 = {}
    for tag, extra in [("no_totalPower", ""), ("with_totalPower", ' totalPower="150000"')]:
        add = f"""<additional>
  <busStop id="bsA" lane="BC_0" startPos="290" endPos="305"/>
  <busStop id="bsB" lane="BC_0" startPos="320" endPos="335"/>
  <chargingStation id="cs_big" lane="BC_0" startPos="285" endPos="336" power="150000"{extra}
                   efficiency="1.0" chargeDelay="0" chargeInTransit="false"/>
</additional>"""
        rou = f'<routes>\n{vtype(lev=200000)}\n' \
              f'  <vehicle id="b1" type="beb" depart="0"><route edges="AB BC"/><stop busStop="bsB" duration="200"/></vehicle>\n' \
              f'  <vehicle id="b2" type="beb" depart="10"><route edges="AB BC"/><stop busStop="bsA" duration="200"/></vehicle>\n</routes>'
        d, rc, err = run(f"p6_{tag}", rou, add, end=800)
        r = rows(d)
        bytime = {}
        for t, a in r:
            bytime.setdefault(t, {})[a["id"]] = a
        dual = [t for t, x in bytime.items() if sum(1 for v in x.values() if float(v["energyCharged"]) > 0) == 2]
        solo = [t for t, x in bytime.items() if sum(1 for v in x.values() if float(v["energyCharged"]) > 0) == 1]
        P6[tag] = dict(returncode=rc, crashed=(rc != 0),
                       n_steps_two_vehicles_charging=len(dual),
                       per_vehicle_wh_when_two_charge=(
                           {k: v["energyCharged"] for k, v in bytime[dual[len(dual) // 2]].items()}
                           if dual else None),
                       per_vehicle_wh_when_one_charges=(
                           {k: v["energyCharged"] for k, v in bytime[solo[len(solo) // 2]].items()}
                           if solo else None))
    R["P6_station_power_semantics"] = dict(
        runs=P6,
        conclusion="chargingStation `power` is a PER-VEHICLE rate: two vehicles inside the same "
                   "station each receive the full power (150 kW each here), so a single "
                   "chargingStation element cannot represent a limited number of chargers. "
                   "The `totalPower` attribute, which would express a shared budget, makes SUMO "
                   "1.27.1 SEGFAULT as soon as two vehicles charge simultaneously. Charger COUNT "
                   "must therefore be modelled as physically separate berths.")
    return R


if __name__ == "__main__":
    R = main()
    out = (sys.argv[1] if len(sys.argv) > 1 else
           os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "..", "..", "..", "outputs")))
    os.makedirs(out, exist_ok=True)
    json.dump(R, open(os.path.join(out, "battery_semantics_probe.json"), "w"), indent=1)
    print(json.dumps(R, indent=1))
