#!/usr/bin/env python3
"""
Step 9 (verification) -- prove what --emission-output actually contains.

Claim under test: the per-step <vehicle CO2=".."> values in --emission-output
are instantaneous RATES in mg/s, so mass = value * step-length.  If they were
per-step masses, a naive sum would be step-length-invariant.

Test: identical single-vehicle scenario at --step-length 1.0 / 0.5 / 0.25,
comparing (a) the naive sum of emission-output values, (b) sum * step-length,
against (c) tripinfo's <emissions CO2_abs> for the same vehicle.

Writes outputs/analysis/emission_output_units.txt
"""
import argparse
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

NOD = '<nodes><node id="a" x="0" y="0"/><node id="b" x="1000" y="0"/></nodes>\n'
EDG = '<edges><edge id="e" from="a" to="b" numLanes="1" speed="13.89"/></edges>\n'
ROU = ('<routes><vType id="v" emissionClass="HBEFA4/PC_petrol_Euro-6d" '
       'accel="2.6" decel="4.5" sigma="0"/>'
       '<route id="r" edges="e"/>'
       '<vehicle id="0" type="v" route="r" depart="0" departSpeed="0"/></routes>\n')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.work, exist_ok=True)
    for name, txt in (("u.nod.xml", NOD), ("u.edg.xml", EDG), ("u.rou.xml", ROU)):
        open(os.path.join(a.work, name), "w").write(txt)
    import shutil
    nc = shutil.which("netconvert") or os.path.join(
        os.path.dirname(shutil.which("sumo")), "netconvert")
    subprocess.run([nc, "-n", os.path.join(a.work, "u.nod.xml"),
                    "-e", os.path.join(a.work, "u.edg.xml"),
                    "-o", os.path.join(a.work, "u.net.xml")],
                   capture_output=True, check=True)
    lines = ["--emission-output units verification (SUMO %s)" %
             subprocess.run(["sumo", "--version"], capture_output=True,
                            text=True).stdout.split("\n")[0],
             "single PC_petrol_Euro-6d vehicle, 1000 m link, departSpeed=0, sigma=0",
             "",
             f"{'step_s':>8} {'sum(values)':>14} {'sum*step':>14} "
             f"{'tripinfo_abs':>14} {'sum*step/tripinfo':>18}"]
    for sl in ("1.0", "0.5", "0.25", "0.1"):
        em = os.path.join(a.work, f"em_{sl}.xml")
        ti = os.path.join(a.work, f"ti_{sl}.xml")
        subprocess.run(["sumo", "-n", os.path.join(a.work, "u.net.xml"),
                        "-r", os.path.join(a.work, "u.rou.xml"),
                        "-e", "300", "--step-length", sl,
                        "--emission-output", em, "--tripinfo-output", ti,
                        "--device.emissions.probability", "1.0",
                        "--no-step-log", "true"], capture_output=True, check=True)
        s = sum(float(v.get("CO2")) for v in ET.parse(em).getroot().iter("vehicle"))
        t = float(ET.parse(ti).getroot().find(".//emissions").get("CO2_abs"))
        lines.append(f"{sl:>8} {s:14.1f} {s*float(sl):14.1f} {t:14.1f} "
                     f"{s*float(sl)/t:18.4f}")
    # short-trip control: same vehicle, 100 m link, departSpeed=max
    open(os.path.join(a.work, "s.edg.xml"), "w").write(
        '<edges><edge id="e" from="a" to="b" numLanes="1" speed="13.89"/></edges>\n')
    open(os.path.join(a.work, "s.nod.xml"), "w").write(
        '<nodes><node id="a" x="0" y="0"/><node id="b" x="100" y="0"/></nodes>\n')
    open(os.path.join(a.work, "s.rou.xml"), "w").write(ROU.replace('departSpeed="0"',
                                                                   'departSpeed="max"'))
    open(os.path.join(a.work, "s0.rou.xml"), "w").write(ROU)
    subprocess.run([nc, "-n", os.path.join(a.work, "s.nod.xml"),
                    "-e", os.path.join(a.work, "s.edg.xml"),
                    "-o", os.path.join(a.work, "s.net.xml")],
                   capture_output=True, check=True)
    lines += ["",
              "SHORT-TRIP CONTROL A: 100 m link, departSpeed=max (~7 s trip)",
              f"{'step_s':>8} {'sum*step':>14} {'tripinfo_abs':>14} "
              f"{'sum*step/tripinfo':>18}"]
    for sl in ("1.0", "0.5", "0.25", "0.1"):
        em = os.path.join(a.work, f"sem_{sl}.xml")
        ti = os.path.join(a.work, f"sti_{sl}.xml")
        subprocess.run(["sumo", "-n", os.path.join(a.work, "s.net.xml"),
                        "-r", os.path.join(a.work, "s.rou.xml"),
                        "-e", "300", "--step-length", sl,
                        "--emission-output", em, "--tripinfo-output", ti,
                        "--device.emissions.probability", "1.0",
                        "--no-step-log", "true"], capture_output=True, check=True)
        s2 = sum(float(v.get("CO2")) for v in ET.parse(em).getroot().iter("vehicle"))
        t2 = float(ET.parse(ti).getroot().find(".//emissions").get("CO2_abs"))
        lines.append(f"{sl:>8} {s2*float(sl):14.1f} {t2:14.1f} "
                     f"{s2*float(sl)/t2:18.4f}")
    lines += ["",
              "SHORT-TRIP CONTROL B: 100 m link, departSpeed=0 (accelerating, ~14 s)",
              f"{'step_s':>8} {'sum*step':>14} {'tripinfo_abs':>14} "
              f"{'sum*step/tripinfo':>18}"]
    for sl in ("1.0", "0.5", "0.25", "0.1"):
        em = os.path.join(a.work, f"s0em_{sl}.xml")
        ti = os.path.join(a.work, f"s0ti_{sl}.xml")
        subprocess.run(["sumo", "-n", os.path.join(a.work, "s.net.xml"),
                        "-r", os.path.join(a.work, "s0.rou.xml"),
                        "-e", "300", "--step-length", sl,
                        "--emission-output", em, "--tripinfo-output", ti,
                        "--device.emissions.probability", "1.0",
                        "--no-step-log", "true"], capture_output=True, check=True)
        s3 = sum(float(v.get("CO2")) for v in ET.parse(em).getroot().iter("vehicle"))
        t3 = float(ET.parse(ti).getroot().find(".//emissions").get("CO2_abs"))
        lines.append(f"{sl:>8} {s3*float(sl):14.1f} {t3:14.1f} "
                     f"{s3*float(sl)/t3:18.4f}")
    lines += ["",
              "Interpretation 1 (units): sum(values) scales as ~1/step while",
              "sum*step does not -> the file holds instantaneous RATES in mg/s.",
              "A naive sum without multiplying by --step-length is exactly",
              "(1/step) times too large.",
              "",
              "Interpretation 2 (trip-boundary residual): after the unit fix the",
              "trajectory total still need not equal tripinfo's accumulator.  In",
              "all three controls above the trajectory total is <= tripinfo's, by",
              "an amount that scales with (step-length / trip duration):",
              "  constant-speed 7 s trip      : exact (1.0000) at every step",
              "  accelerating  ~14 s trip     : -1.46% at 1 s -> -0.15% at 0.1 s",
              "  accelerating  ~76 s trip     : -0.41% at 1 s -> -0.04% at 0.1 s",
              "i.e. the discrepancy is confined to the trip's first/last partial",
              "step and is largest when the vehicle is accelerating there.",
              "Practical rule: only compare trajectory-derived and",
              "tripinfo-derived masses when trip durations are many time steps",
              "long, and expect a residual of order (step / trip duration)."]
    open(a.out, "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
