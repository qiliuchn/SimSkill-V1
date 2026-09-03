#!/usr/bin/env python3
"""
Empirical probe of SUMO's container / transport / tranship / containerStop semantics.

This answers, from raw output files rather than from documentation assumptions:
  Q1  Does a <container> with a <transport> stage actually get loaded onto a vehicle?
  Q2  Does loading/unloading BLOCK the vehicle (i.e. extend its stop beyond `duration`)?
  Q3  What governs loading duration -- vType@loadingDuration? stop@duration? both?
  Q4  What happens when a container cannot be loaded (vehicle already gone / no such line)?
  Q5  Do containers appear in tripinfo-output? In stop-output? Under which element/attrs?
  Q6  Can TraCI count containers on a vehicle (traci.container domain, getContainerNumber)?
  Q7  Does <stop containerStop=... parking="true"> take the vehicle out of the traffic stream
      (verified via laneData occupancy), vs parking="false"?

Writes: outputs/probe/PROBE_RESULTS.json  and the raw SUMO output files next to it.
"""
import os, sys, json, subprocess, shutil
import xml.etree.ElementTree as ET

SUMO_HOME = os.environ.get("SUMO_HOME")
sys.path.append(os.path.join(SUMO_HOME, "tools"))
import sumolib  # noqa
import traci    # noqa

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(os.path.join(HERE, "..", "probe"))
os.makedirs(OUT, exist_ok=True)
BIN = os.path.dirname(shutil.which("sumo") or os.path.join(SUMO_HOME, "bin", "sumo"))


def sh(cmd, **kw):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, **kw)
    return r


def build_net():
    nod = """<nodes>
  <node id="n0" x="0"    y="0" type="priority"/>
  <node id="n1" x="500"  y="0" type="priority"/>
  <node id="n2" x="1000" y="0" type="priority"/>
  <node id="n3" x="1500" y="0" type="priority"/>
</nodes>"""
    edg = """<edges>
  <edge id="e0" from="n0" to="n1" numLanes="2" speed="13.89"/>
  <edge id="e1" from="n1" to="n2" numLanes="2" speed="13.89"/>
  <edge id="e2" from="n2" to="n3" numLanes="2" speed="13.89"/>
</edges>"""
    open(f"{OUT}/probe.nod.xml", "w").write(nod)
    open(f"{OUT}/probe.edg.xml", "w").write(edg)
    r = sh(f'"{BIN}/netconvert" -n {OUT}/probe.nod.xml -e {OUT}/probe.edg.xml -o {OUT}/probe.net.xml --no-turnarounds')
    return r.returncode == 0, r.stderr


def write_additionals():
    add = """<additional>
  <containerStop id="cs_load"   lane="e0_0" startPos="100" endPos="140" name="depot"/>
  <containerStop id="cs_drop"   lane="e1_0" startPos="100" endPos="140" name="customer_block"/>
  <containerStop id="cs_drop2"  lane="e2_0" startPos="100" endPos="140" name="customer2"/>
  <edgeData id="ed" file="probe_edgedata.xml" period="100000" excludeEmpty="false"/>
  <laneData id="ld" file="probe_lanedata.xml" period="100000" excludeEmpty="false"/>
</additional>"""
    open(f"{OUT}/probe.add.xml", "w").write(add)


def write_routes():
    """
    Scenario design:
      veh_A : loadingDuration=30 per container, stop duration=10  -> Q2/Q3 (does loading extend the stop?)
      veh_B : loadingDuration=5,  stop duration=120               -> does duration dominate?
      veh_C : parking="true" stop at containerStop                -> Q7 off-lane check
      c1,c2,c3 -> transported by veh_A  (2 containers at load stop, dropped at cs_drop)
      c_orphan -> <transport lines="veh_GHOST"> a vehicle that never exists -> Q4
      c_late   -> departs at t=2000, after veh_A already left     -> Q4 (missed vehicle)
      c_tranship -> a <tranship> stage (container moves by itself) -> semantics of tranship
    """
    rou = """<routes>
  <vType id="van"   vClass="delivery" length="7.5"  accel="2.0" decel="4.0" maxSpeed="22" emissionClass="HBEFA3/LDV_D_EU4" loadingDuration="30" containerCapacity="4"/>
  <vType id="vanB"  vClass="delivery" length="7.5"  accel="2.0" decel="4.0" maxSpeed="22" emissionClass="HBEFA3/LDV_D_EU4" loadingDuration="5"  containerCapacity="4"/>
  <vType id="vanC"  vClass="delivery" length="7.5"  accel="2.0" decel="4.0" maxSpeed="22" emissionClass="HBEFA3/LDV_D_EU4" loadingDuration="20" containerCapacity="4"/>

  <route id="r_all" edges="e0 e1 e2"/>

  <container id="c1" depart="0">
    <transport from="e0" containerStop="cs_drop" lines="veh_A"/>
  </container>
  <container id="c2" depart="0">
    <transport from="e0" containerStop="cs_drop" lines="veh_A"/>
  </container>
  <container id="c3" depart="0">
    <transport from="e0" containerStop="cs_drop" lines="veh_A"/>
  </container>

  <container id="c_orphan" depart="0">
    <transport from="e0" containerStop="cs_drop" lines="veh_GHOST"/>
  </container>

  <container id="c_tranship" depart="0">
    <tranship from="e0" to="e1" speed="1.2"/>
  </container>

  <vehicle id="veh_A" type="van" route="r_all" depart="0">
    <stop containerStop="cs_load" duration="10"/>
    <stop containerStop="cs_drop" duration="10"/>
  </vehicle>

  <container id="c_B1" depart="290">
    <transport from="e0" containerStop="cs_drop" lines="veh_B"/>
  </container>

  <vehicle id="veh_B" type="vanB" route="r_all" depart="300">
    <stop containerStop="cs_load" duration="120"/>
    <stop containerStop="cs_drop" duration="120"/>
  </vehicle>

  <container id="c_C1" depart="590">
    <transport from="e0" containerStop="cs_drop2" lines="veh_C"/>
  </container>

  <vehicle id="veh_C" type="vanC" route="r_all" depart="600">
    <stop containerStop="cs_load" duration="60" parking="true"/>
    <stop containerStop="cs_drop2" duration="60" parking="false"/>
  </vehicle>

  <container id="c_late" depart="2000">
    <transport from="e0" containerStop="cs_drop" lines="veh_A"/>
  </container>
</routes>"""
    open(f"{OUT}/probe.rou.xml", "w").write(rou)


def run_sumo():
    cfg = f"""<configuration>
  <input>
    <net-file value="probe.net.xml"/>
    <route-files value="probe.rou.xml"/>
    <additional-files value="probe.add.xml"/>
  </input>
  <time><begin value="0"/><end value="3000"/><step-length value="1"/></time>
  <report><no-step-log value="true"/><duration-log.statistics value="true"/></report>
</configuration>"""
    open(f"{OUT}/probe.sumocfg", "w").write(cfg)
    r = sh(f'"{BIN}/sumo" -c {OUT}/probe.sumocfg '
           f'--tripinfo-output {OUT}/probe_tripinfo.xml '
           f'--stop-output {OUT}/probe_stopout.xml '
           f'--summary-output {OUT}/probe_summary.xml '
           f'--vehroute-output {OUT}/probe_vehroute.xml '
           f'--device.emissions.probability 1.0 '
           f'--tripinfo-output.write-unfinished true '
           f'--log {OUT}/probe_sumo.log', cwd=OUT)
    return r


def run_traci_probe():
    """Query the traci.container domain live to learn what is observable."""
    res = {"container_domain_methods": [], "timeline": [], "errors": []}
    try:
        res["container_domain_methods"] = sorted(
            [m for m in dir(traci.container) if not m.startswith("_")])
    except Exception as e:
        res["errors"].append("dir(traci.container): %s" % e)
    veh_methods = [m for m in dir(traci.vehicle) if "ontainer" in m]
    res["vehicle_container_methods"] = sorted(veh_methods)

    try:
        traci.start([os.path.join(BIN, "sumo"), "-c", f"{OUT}/probe.sumocfg",
                     "--no-step-log", "true"], label="probe")
        t = 0
        while t < 3000 and (traci.simulation.getMinExpectedNumber() > 0):
            traci.simulationStep()
            t = int(traci.simulation.getTime())
            if t % 10 == 0 or t < 200:
                snap = {"t": t,
                        "vehs": {}, "containers": {}}
                for v in traci.vehicle.getIDList():
                    try:
                        n = traci.vehicle.getParameter(v, "device.container.IDList")
                    except Exception:
                        n = None
                    entry = {"speed": round(traci.vehicle.getSpeed(v), 2),
                             "stopstate": traci.vehicle.getStopState(v)}
                    try:
                        entry["nContainers"] = traci.vehicle.getPersonNumber(v)
                    except Exception:
                        pass
                    for meth in veh_methods:
                        try:
                            entry[meth] = getattr(traci.vehicle, meth)(v)
                        except Exception:
                            pass
                    entry["device_container_IDList"] = n
                    snap["vehs"][v] = entry
                for c in traci.container.getIDList():
                    try:
                        snap["containers"][c] = {
                            "vehicle": traci.container.getVehicle(c),
                            "stage_type": traci.container.getStage(c).type,
                            "edge": traci.container.getRoadID(c),
                            "speed": round(traci.container.getSpeed(c), 2),
                        }
                    except Exception as e:
                        snap["containers"][c] = {"err": str(e)}
                # only record snapshots where something interesting happens
                res["timeline"].append(snap)
        res["final_time"] = t
        res["loaded_containers_total"] = traci.simulation.getParameter("", "device.container.count") \
            if False else None
        traci.close()
    except Exception as e:
        res["errors"].append("traci run: %s" % e)
        try:
            traci.close()
        except Exception:
            pass
    return res


def parse_outputs():
    out = {}
    # tripinfo: what elements exist?
    try:
        tree = ET.parse(f"{OUT}/probe_tripinfo.xml")
        root = tree.getroot()
        out["tripinfo_child_tags"] = sorted({c.tag for c in root})
        out["tripinfo_entries"] = []
        for c in root:
            e = {"tag": c.tag}
            e.update(dict(c.attrib))
            e["children"] = [{"tag": g.tag, **dict(g.attrib)} for g in c]
            out["tripinfo_entries"].append(e)
    except Exception as e:
        out["tripinfo_error"] = str(e)
    # stop-output
    try:
        tree = ET.parse(f"{OUT}/probe_stopout.xml")
        out["stopout"] = [dict(c.attrib) for c in tree.getroot()]
        out["stopout_attr_names"] = sorted({k for c in tree.getroot() for k in c.attrib})
    except Exception as e:
        out["stopout_error"] = str(e)
    # lanedata occupancy on the stop lanes
    try:
        tree = ET.parse(f"{OUT}/probe_lanedata.xml")
        lanes = {}
        for iv in tree.getroot():
            for edge in iv:
                for lane in edge:
                    lanes[lane.get("id")] = dict(lane.attrib)
        out["lanedata"] = {k: v for k, v in lanes.items()}
    except Exception as e:
        out["lanedata_error"] = str(e)
    # warnings from log
    try:
        log = open(f"{OUT}/probe_sumo.log").read()
        out["log_warnings"] = [l for l in log.splitlines()
                               if "Warning" in l or "Error" in l or "container" in l.lower()]
    except Exception as e:
        out["log_error"] = str(e)
    return out


def main():
    results = {}
    ok, err = build_net()
    results["netconvert_ok"] = ok
    if not ok:
        results["netconvert_stderr"] = err
        json.dump(results, open(f"{OUT}/PROBE_RESULTS.json", "w"), indent=2)
        print(json.dumps(results, indent=2)[:3000]); return
    write_additionals()
    write_routes()
    r = run_sumo()
    results["sumo_returncode"] = r.returncode
    results["sumo_stderr_tail"] = r.stderr[-4000:]
    results.update(parse_outputs())
    results["traci"] = run_traci_probe()
    json.dump(results, open(f"{OUT}/PROBE_RESULTS.json", "w"), indent=2, default=str)
    print("wrote", f"{OUT}/PROBE_RESULTS.json")


if __name__ == "__main__":
    main()
