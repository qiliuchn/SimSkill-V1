#!/usr/bin/env python3
"""Threshold-sensitivity sweep for the dynamic HSR controller (attempt-2 corrected bottleneck).

Runs the dynamic controller with several (occ_open, occ_close) pairs and one hold-time
variation, each into its own output dir with its own detector file, and tabulates
open timing, shoulder usage, and delay so the sensitivity can be read off directly.
Runs on the REAL 2->1 merge lane-drop network net/hsr_open.net.xml.
"""
import subprocess, os, sys, xml.etree.ElementTree as ET

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V = sys.executable
NET = os.path.join(BASE, "net/hsr_open.net.xml")
ROU = os.path.join(BASE, "scripts/hsr.rou.xml")
GEN = os.path.join(BASE, "scripts/gen_detectors.py")
RUN = os.path.join(BASE, "scripts/run_hsr.py")
EXIT_IDS = ("e1_exit_s", "e1_exit_0")


def metrics(d, ev):
    r = ET.parse(os.path.join(d, "tripinfo.xml")).getroot()
    n = tl = du = dd = 0
    for t in r.findall("tripinfo"):
        n += 1; tl += float(t.get("timeLoss")); du += float(t.get("duration")); dd += float(t.get("departDelay"))
    sh = ET.parse(os.path.join(d, "det_shoulder.xml")).getroot()
    shv = sum(float(i.get("nVehContrib", 0) or 0) for i in sh.findall("interval") if i.get("id") == "e1_shoulder")
    ex = ET.parse(os.path.join(d, "det_exit.xml")).getroot()
    peak = sum(float(i.get("nVehContrib", 0) or 0) for i in ex.findall("interval")
               if i.get("id", "") in EXIT_IDS and 600 <= float(i.get("begin")) < 1800)
    lines = open(ev).read().splitlines()
    opens = [l for l in lines if "\tOPEN\t" in l]
    closes = [l for l in lines if "\tCLOSE\t" in l]
    first_open = opens[0].split("\t")[0] if opens else "-"
    return dict(n=n, tl=tl / n, du=du / n, dd=dd / n, shv=shv,
                peak=peak / 1200 * 3600, nopen=len(opens), nclose=len(closes), first=first_open)


def run(oo, oc, ho, hc, tag):
    d = os.path.join(BASE, "outputs/sweep", tag)
    ev = os.path.join(BASE, "logs", f"sweep_{tag}.log")
    add = os.path.join(BASE, "detectors", f"det_sweep_{tag}.add.xml")
    subprocess.run([V, GEN, "--outdir", d, "--out", add], check=True, capture_output=True)
    subprocess.run([V, RUN, "--mode", "dynamic", "--net", NET, "--routes", ROU, "--add", add,
                    "--outdir", d, "--eventlog", ev, "--end", "4200",
                    "--occ-open", str(oo), "--hold-open", str(ho),
                    "--occ-close", str(oc), "--hold-close", str(hc)],
                   check=True, capture_output=True)
    return metrics(d, ev)


CONFIGS = [
    (10, 4, 45, 120, "o10_c4"),
    (18, 6, 45, 120, "o18_c6_BASE"),
    (28, 12, 45, 120, "o28_c12"),
    (40, 20, 45, 120, "o40_c20"),
    (55, 30, 45, 120, "o55_c30"),
    (18, 6, 90, 300, "o18_c6_slowhold"),
]

print(f"{'config (open/close, hold_o/hold_c)':<40}{'1stOpen':>8}{'#op/#cl':>9}{'shldVeh':>9}{'peakDisch':>11}{'mTimeLoss':>11}{'mDepDelay':>11}")
print("-" * 99)
for oo, oc, ho, hc, tag in CONFIGS:
    m = run(oo, oc, ho, hc, tag)
    label = f"open{oo}/close{oc}, hold {ho}/{hc}s"
    opcl = f"{m['nopen']}/{m['nclose']}"
    print(f"{label:<40}{str(m['first']):>8}{opcl:>9}{m['shv']:>9.0f}"
          f"{m['peak']:>11.0f}{m['tl']:>11.1f}{m['dd']:>11.1f}")
print("-" * 99)
print("reference: closed peakDisch=1971 mTimeLoss=383.6 mDepDelay=101.7 ; open peakDisch=3393 mTimeLoss=15.8 mDepDelay=0.2")
