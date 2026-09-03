"""Shared helpers: vType definitions, demand generation, SUMO invocation, metrics."""
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

ARMS = ["N", "E", "S", "W"]
# CCW ring order: entering at X, the exits encountered are 1st, 2nd, 3rd
EXIT_ORDER = {"N": ["W", "S", "E"], "W": ["S", "E", "N"], "S": ["E", "N", "W"], "E": ["N", "W", "S"]}
# on the SIGNALIZED junction the same three destinations are right / through / left
MOVEMENT = {"1st": "right", "2nd": "through", "3rd": "left"}


def sumo_bin(name="sumo"):
    f = shutil.which(name)
    if f:
        return f
    sh = os.environ.get("SUMO_HOME")
    if sh:
        c = os.path.join(sh, "bin", name)
        if os.path.isfile(c):
            return c
    sys.exit("cannot find " + name)


VTYPE_ATTRS = dict(vClass="passenger", length="4.5", minGap="2.5", accel="2.6",
                   decel="4.5", sigma="0.5", tau="1.0", maxSpeed="16.0", speedDev="0.1")


def vtype_xml(ssm=False, overrides=None, indent="    "):
    a = dict(VTYPE_ATTRS)
    a.update(overrides or {})
    attrs = " ".join(f'{k}="{v}"' for k, v in a.items())
    if not ssm:
        return f'{indent}<vType id="car" {attrs}/>'
    return (f'{indent}<vType id="car" {attrs}>\n'
            f'{indent}    <param key="has.ssm.device" value="true"/>\n'
            f'{indent}    <param key="device.ssm.measures" value="TTC DRAC PET BR MDRAC"/>\n'
            f'{indent}    <param key="device.ssm.thresholds" value="3.0 3.0 2.0 0.0 3.4"/>\n'
            f'{indent}    <param key="device.ssm.range" value="60.0"/>\n'
            f'{indent}    <param key="device.ssm.extratime" value="5.0"/>\n'
            f'{indent}    <param key="device.ssm.mdrac.prt" value="1.0"/>\n'
            f'{indent}</vType>')


def write_flows(path, volumes, begin, end, ssm=False, vtype_overrides=None,
                depart_lane="best", depart_speed="max", headway="exp",
                poisson_keys=None):
    """volumes: {(origin_arm, dest_arm): veh/h}. One demand file routes on every
    variant because all variants use the same in_X / out_X fringe edge ids.

    headway="exp"      -> period="exp(rate)", i.e. Poisson (negative-exponential)
                          arrivals.  REQUIRED for any gap-acceptance / capacity
                          measurement: SUMO's plain `vehsPerHour` emits vehicles
                          at EXACTLY equal spacing, and a deterministic
                          circulating stream with headway just below the entry's
                          critical gap blocks the entry almost completely, which
                          is a rig artifact, not roundabout physics.
    headway="uniform"  -> plain vehsPerHour (deterministic spacing).
    poisson_keys       -> if given, only these (o,d) keys get exponential
                          headways; the rest stay deterministic.
    """
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<routes>',
             vtype_xml(ssm=ssm, overrides=vtype_overrides)]
    for (o, d), v in sorted(volumes.items()):
        if v <= 0:
            continue
        use_exp = (headway == "exp") and (poisson_keys is None or (o, d) in poisson_keys)
        rate = f'period="exp({v/3600.0:.6f})"' if use_exp else f'vehsPerHour="{v}"'
        lines.append(f'    <flow id="f_{o}{d}" type="car" from="in_{o}" to="out_{d}" '
                     f'begin="{begin}" end="{end}" {rate} '
                     f'departLane="{depart_lane}" departSpeed="{depart_speed}" departPos="last"/>')
    lines.append('</routes>')
    open(path, "w").write("\n".join(lines) + "\n")
    return path


def run_sumo(net, routes, outdir, end, seed=42, step=0.5, ttt=300,
             additional=None, tripinfo=True, summary=True, ssm_file=None,
             lanechange=None, extra=None, quiet=True, max_depart_delay=-1):
    os.makedirs(outdir, exist_ok=True)
    cmd = [sumo_bin(), "-n", os.path.abspath(net), "-r", os.path.abspath(routes),
           "--begin", "0", "--end", str(end), "--step-length", str(step),
           "--seed", str(seed), "--time-to-teleport", str(ttt),
           "--no-step-log", "true", "--duration-log.statistics", "true",
           "--max-depart-delay", str(max_depart_delay),
           "--xml-validation", "never", "--no-warnings", "true"]
    if tripinfo:
        cmd += ["--tripinfo-output", os.path.join(outdir, "tripinfo.xml"),
                "--tripinfo-output.write-unfinished", "true"]
    if summary:
        cmd += ["--summary-output", os.path.join(outdir, "summary.xml")]
    if ssm_file:
        cmd += ["--device.ssm.file", os.path.abspath(ssm_file)]
    if lanechange:
        cmd += ["--lanechange-output", os.path.abspath(lanechange)]
    if additional:
        cmd += ["-a", ",".join(os.path.abspath(x) for x in additional)]
    if extra:
        cmd += list(extra)
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=outdir)
    open(os.path.join(outdir, "sumo_stderr.txt"), "w").write(r.stderr)
    open(os.path.join(outdir, "sumo_stdout.txt"), "w").write(r.stdout)
    if r.returncode != 0 and not quiet:
        print(r.stderr[:3000], file=sys.stderr)
    return r


# ---------------- output parsing ----------------

def parse_tripinfo(path):
    trips = []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "tripinfo":
            trips.append(dict(id=el.get("id"),
                              depart=float(el.get("depart")),
                              arrival=float(el.get("arrival")),
                              duration=float(el.get("duration")),
                              waitingTime=float(el.get("waitingTime")),
                              timeLoss=float(el.get("timeLoss")),
                              routeLength=float(el.get("routeLength")),
                              departDelay=float(el.get("departDelay"))))
            el.clear()
    return trips


def parse_summary(path):
    """returns (loaded, inserted, arrived, teleports_final, running_series)"""
    loaded = inserted = arrived = 0
    tel = 0
    running = []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "step":
            loaded = int(float(el.get("loaded")))
            inserted = int(float(el.get("inserted")))
            arrived = int(float(el.get("ended", el.get("arrived", 0))))
            tel = max(tel, int(float(el.get("teleports", 0))))
            running.append((float(el.get("time")), int(float(el.get("running")))))
            el.clear()
    return loaded, inserted, arrived, tel, running


def arm_of(vid):
    """flow ids are f_<O><D> so the vehicle id f_NE.12 -> origin N, dest E"""
    core = vid.split(".")[0]
    if core.startswith("f_") and len(core) >= 4:
        return core[2], core[3]
    return None, None
