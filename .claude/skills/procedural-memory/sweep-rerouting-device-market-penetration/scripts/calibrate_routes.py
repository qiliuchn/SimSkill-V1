#!/usr/bin/env python3
"""Step 1 of the study: measure BOTH routes' travel times empirically before any treatment.

Runs the corridor with a low-demand, no-incident load in which vehicles are split
50/50 between the static main route and the static alternate route (no rerouting
device at all), and reports the measured O->D duration of each.  Then repeats at
the study's real demand with the incident active and NO rerouting, to measure the
congested main-route time the alternate has to beat.

Usage:
  python calibrate_routes.py --net NET --outdir DIR
"""
import argparse
import os
import subprocess
import statistics
import xml.etree.ElementTree as ET

MAIN = "OA AC CB BD"
ALT = "OA AP PB BD"


def write_routes(path, vph, horizon, alt_share):
    n = int(round(vph * horizon / 3600.0))
    h = horizon / float(n)
    with open(path, "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<routes>\n')
        f.write('    <vType id="car" vClass="passenger" accel="2.6" decel="4.5" sigma="0.5" '
                'length="5.0" minGap="2.5" maxSpeed="45" speedDev="0.1"/>\n')
        f.write('    <route id="main" edges="%s"/>\n' % MAIN)
        f.write('    <route id="alt" edges="%s"/>\n' % ALT)
        for i in range(n):
            r = "alt" if (alt_share > 0 and (i % max(1, int(round(1.0 / alt_share)))) == 0) else "main"
            f.write('    <vehicle id="v%04d" type="car" route="%s" depart="%.2f" '
                    'departLane="best" departSpeed="max"/>\n' % (i, r, (i + 0.5) * h))
        f.write('</routes>\n')
    return n


def run(net, rou, add, out, end):
    cmd = ["sumo", "-n", net, "-r", rou,
           "--tripinfo-output", out + "/tripinfo.xml",
           "--vehroute-output", out + "/vehroutes.xml",
           "--begin", "0", "--end", str(end), "--time-to-teleport", "300",
           "--no-step-log", "true", "--seed", "1", "--duration-log.statistics", "true"]
    if add:
        cmd += ["-a", add]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("sumo failed: " + r.stderr[-3000:])
    return r.stderr


def route_of(vehroutes):
    """route id actually driven, per vehicle (LAST <route> of a routeDistribution)."""
    out = {}
    for v in ET.parse(vehroutes).getroot().findall("vehicle"):
        rd = v.find("routeDistribution")
        if rd is not None:
            edges = rd.findall("route")[-1].get("edges")
        else:
            edges = v.find("route").get("edges")
        out[v.get("id")] = "alt" if " AP " in " " + edges + " " else "main"
    return out


def durations_by_route(outdir, t0=None, t1=None):
    rt = route_of(os.path.join(outdir, "vehroutes.xml"))
    d = {"main": [], "alt": []}
    for ti in ET.parse(os.path.join(outdir, "tripinfo.xml")).getroot().findall("tripinfo"):
        dep = float(ti.get("depart"))
        if t0 is not None and not (t0 <= dep < t1):
            continue
        d[rt[ti.get("id")]].append(float(ti.get("duration")))
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--incident-add", required=True)
    ap.add_argument("--vph", type=float, default=2800.0)
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    lines = []

    # --- A: free flow, both routes used, no incident ---
    ffdir = os.path.join(a.outdir, "freeflow")
    os.makedirs(ffdir, exist_ok=True)
    rou = os.path.join(ffdir, "cal.rou.xml")
    write_routes(rou, 300, 1800, 0.5)
    run(a.net, rou, None, ffdir, 4000)
    d = durations_by_route(ffdir)
    ffm, ffa = statistics.mean(d["main"]), statistics.mean(d["alt"])
    lines.append("FREE FLOW (300 veh/h, no incident, static routes, no device)")
    lines.append("  main  n=%d  mean O->D duration = %.1f s" % (len(d["main"]), ffm))
    lines.append("  alt   n=%d  mean O->D duration = %.1f s" % (len(d["alt"]), ffa))
    lines.append("  alternate penalty at free flow = %+.1f s (%+.1f%%)" % (ffa - ffm, 100 * (ffa / ffm - 1)))

    # --- B: study demand, incident active, everyone on main, no device ---
    cgdir = os.path.join(a.outdir, "congested_main")
    os.makedirs(cgdir, exist_ok=True)
    rou = os.path.join(cgdir, "cal.rou.xml")
    write_routes(rou, a.vph, 3600, 0.0)
    run(a.net, rou, a.incident_add, cgdir, 9000)
    d = durations_by_route(cgdir, 900, 2400)
    dall = durations_by_route(cgdir)
    lines.append("")
    lines.append("INCIDENT, 100%% ON MAIN, NO DEVICE (%.0f veh/h)" % a.vph)
    lines.append("  main, departing inside incident window 900-2400 s: n=%d mean = %.1f s"
                 % (len(d["main"]), statistics.mean(d["main"])))
    lines.append("  main, worst single trip = %.1f s" % max(dall["main"]))
    lines.append("  main, whole-run mean = %.1f s" % statistics.mean(dall["main"]))
    lines.append("")
    lines.append("  => congested main time to beat = %.1f s vs free-flow alternate = %.1f s"
                 % (statistics.mean(d["main"]), ffa))
    lines.append("  => diversion is worth up to %.1f s per vehicle at the peak of the incident"
                 % (statistics.mean(d["main"]) - ffa))

    txt = "\n".join(lines)
    print(txt)
    with open(os.path.join(a.outdir, "route_calibration.txt"), "w") as f:
        f.write(txt + "\n")


if __name__ == "__main__":
    main()
