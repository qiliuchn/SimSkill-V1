"""
PART 4 -- roundabout METERING: a part-time actuated signal on the DOMINANT entry
only, triggered by a queue detector on the STARVED approach.

Network `slm` = the single-lane roundabout with all four approaches split 60 m
upstream by a one-link traffic_light node mN/mE/mS/mW.  All four are split so the
geometry stays symmetric across metered and unmetered runs; mN/mS/mW are held
permanently green and only mE is ever red.  The unmetered control run uses the
SAME network with mE also held permanently green, so the metering effect is
isolated from the geometry change of splitting the approach.

Detector -> controller binding is done in TraCI rather than through the
`<param key="<laneID>" value="<detID>"/>` binding of
`design-actuated-signal-detector-placement-and-fault-tolerance`, because that
binding drives SUMO's own gap-based extension logic on the detector's OWN
approach; roundabout metering needs the opposite wiring -- a detector on approach
N controlling the signal on approach E -- which SUMO's native actuated logic
cannot express.

Controller (1 s decision interval):
    q = jam length (vehicles) on the starved approach (ap_N + in_N)
    idle -> metering      when q >= thr_on
    metering -> idle      when q <= thr_off (= thr_on - 2, a deadband)
    while metering: cycle  [yellow 2 s | red (R-2) s | green G s]  on mE
"""
import os
import sys

sys.path.insert(0, os.path.join(os.environ.get("SUMO_HOME", ""), "tools"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import traci  # noqa: E402
from common import sumo_bin  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NET = os.path.join(HERE, "networks")
METER_TLS = ["mN", "mE", "mS", "mW"]


def detector_add(path, starved="N"):
    open(path, "w").write(
        '<?xml version="1.0" encoding="UTF-8"?>\n<additional>\n'
        f'    <laneAreaDetector id="q_ap" lane="ap_{starved}_0" pos="0" endPos="-1" '
        f'friendlyPos="true" period="100000" file="qdet.xml"/>\n'
        f'    <laneAreaDetector id="q_in" lane="in_{starved}_0" pos="0" endPos="-1" '
        f'friendlyPos="true" period="100000" file="qdet.xml"/>\n'
        "</additional>\n")
    return path


def run(net, routes, outdir, end, seed=1, step=0.5, ttt=300,
        meter=True, thr_on=5, red=8.0, green=12.0, yellow=2.0,
        dominant="E", starved="N", ssm_file=None, extra_add=None,
        max_depart_delay=-1):
    os.makedirs(outdir, exist_ok=True)
    add = [detector_add(os.path.join(outdir, "qdet.add.xml"), starved)]
    if extra_add:
        add += list(extra_add)
    cmd = [sumo_bin("sumo"), "-n", os.path.abspath(net), "-r", os.path.abspath(routes),
           "-a", ",".join(os.path.abspath(x) for x in add),
           "--begin", "0", "--end", str(end), "--step-length", str(step),
           "--seed", str(seed), "--time-to-teleport", str(ttt),
           "--max-depart-delay", str(max_depart_delay),
           "--tripinfo-output", os.path.join(outdir, "tripinfo.xml"),
           "--tripinfo-output.write-unfinished", "true",
           "--summary-output", os.path.join(outdir, "summary.xml"),
           "--no-step-log", "true", "--xml-validation", "never", "--no-warnings", "true",
           "--duration-log.statistics", "true"]
    if ssm_file:
        cmd += ["--device.ssm.file", os.path.abspath(ssm_file)]
    label = f"m{os.path.basename(outdir)}_{seed}"
    traci.start(cmd, label=label)
    c = traci.getConnection(label)

    thr_off = max(1, thr_on - 2)
    active = False
    sub = "green"
    timer = 0.0
    n_activations = 0
    red_time = 0.0
    active_time = 0.0
    qmax = 0
    t = 0.0
    next_ctrl = 0.0
    for tl in METER_TLS:
        c.trafficlight.setRedYellowGreenState(tl, "G")
    while t < end:
        c.simulationStep()
        t += step
        if t < next_ctrl:
            continue
        next_ctrl = t + 1.0
        if not meter:
            continue
        q = (c.lanearea.getJamLengthVehicle("q_ap") + c.lanearea.getJamLengthVehicle("q_in"))
        qmax = max(qmax, q)
        if not active and q >= thr_on:
            active = True
            n_activations += 1
            sub, timer = "yellow", yellow
        elif active and q <= thr_off and sub == "green":
            active = False
            c.trafficlight.setRedYellowGreenState(dominant_tls(dominant), "G")
        if active:
            active_time += 1.0
            timer -= 1.0
            if timer <= 0:
                sub = {"yellow": "red", "red": "green", "green": "yellow"}[sub]
                timer = {"yellow": yellow, "red": max(1.0, red - yellow), "green": green}[sub]
            st = {"yellow": "y", "red": "r", "green": "G"}[sub]
            if st == "r":
                red_time += 1.0
            c.trafficlight.setRedYellowGreenState(dominant_tls(dominant), st)
    c.close()
    return dict(meter=meter, thr_on=thr_on, red=red, green=green,
                activations=n_activations, red_time_s=red_time,
                metering_active_s=active_time,
                metering_duty_cycle=round(active_time / end, 4),
                red_share_of_horizon=round(red_time / end, 4),
                max_starved_queue_veh=qmax)


def dominant_tls(arm):
    return "m" + arm
