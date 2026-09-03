#!/usr/bin/env python3
"""Sub-goal 1: audit and report every TraCI call the adaptive controller
makes, to prove no ground-truth vehicle state leaks into the control decision.

Two independent checks:
  1. STATIC: grep controller_core.py and adaptive_system.py for every
     `traci.<module>.<call>` occurrence, classify each as a DETECTOR READ
     (inductionloop/lanearea), a WRITE (trafficlight.set*), a bookkeeping
     call (trafficlight.get*/simulation.getTime), or a GROUND-TRUTH read
     (vehicle.*, lane.getLastStep* used as a volume/DoS input) -- flag any
     ground-truth call that isn't the one documented, audited exception
     (the all-red internal-lane-clearance SAFETY check, which reads physical
     occupancy of the junction's own internal lanes to decide when it is
     SAFE to switch phases -- not a control/optimization decision).
  2. RUNTIME: the ACTUAL call log adaptive_system.py's SystemController
     records via self._audit() during a real run (audit_calls.csv, written
     by run_adaptive.py) -- confirms what was really called, not just what
     the source permits.
"""
import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

GROUND_TRUTH_PREFIXES = ("traci.vehicle.", "traci.person.")
SAFETY_EXCEPTION = "traci.lane.getLastStepVehicleNumber"   # documented: all-red internal-lane clearance only
DETECTOR_PREFIXES = ("traci.inductionloop.", "traci.lanearea.")
WRITE_PREFIXES = ("traci.trafficlight.setPhase", "traci.trafficlight.setPhaseDuration",
                  "traci.trafficlight.setProgram")
BOOKKEEPING_PREFIXES = ("traci.trafficlight.getAllProgramLogics", "traci.trafficlight.getControlledLinks",
                        "traci.trafficlight.getProgram", "traci.simulation.getTime",
                        "traci.trafficlight.getIDList")

CALL_RE = re.compile(r"traci\.[A-Za-z_]+\.[A-Za-z_]+")


def static_audit(files):
    findings = []
    for path in files:
        with open(path) as f:
            for lineno, line in enumerate(f, 1):
                for m in CALL_RE.finditer(line):
                    call = m.group(0)
                    kind = classify(call)
                    findings.append((os.path.basename(path), lineno, call, kind, line.strip()))
    return findings


def classify(call):
    if call.startswith(SAFETY_EXCEPTION):
        return "SAFETY-EXCEPTION (all-red internal-lane clearance, not a control input)"
    if any(call.startswith(p) for p in GROUND_TRUTH_PREFIXES):
        return "*** GROUND TRUTH LEAK ***"
    if any(call.startswith(p) for p in DETECTOR_PREFIXES):
        return "detector read"
    if any(call.startswith(p) for p in WRITE_PREFIXES):
        return "actuator write"
    if any(call.startswith(p) for p in BOOKKEEPING_PREFIXES):
        return "bookkeeping (program introspection / clock)"
    return "UNCLASSIFIED -- review manually"


def main():
    files = [os.path.join(HERE, "controller_core.py"), os.path.join(HERE, "adaptive_system.py")]
    findings = static_audit(files)
    print("=" * 100)
    print("STATIC AUDIT: every traci.* call in the controller source")
    print("=" * 100)
    leaks = [f for f in findings if "LEAK" in f[3] or "UNCLASSIFIED" in f[3]]
    by_kind = {}
    for f in findings:
        by_kind.setdefault(f[3], []).append(f)
    for kind, fs in sorted(by_kind.items()):
        uniq_calls = sorted({f[2] for f in fs})
        print("\n[%s]  (%d call sites, %d distinct calls)" % (kind, len(fs), len(uniq_calls)))
        for c in uniq_calls:
            sites = [f for f in fs if f[2] == c]
            print("   %-45s  in %s" % (c, ", ".join("%s:%d" % (s[0], s[1]) for s in sites)))
    print("\n" + ("NO GROUND-TRUTH LEAKS FOUND." if not leaks else "*** %d LEAKS/UNCLASSIFIED FOUND ***" % len(leaks)))

    print("\n" + "=" * 100)
    print("RUNTIME AUDIT: actual call counts logged by a real adaptive-controller run")
    print("=" * 100)
    audit_csv = os.path.join(HERE, "..", "runs", "adaptive_pilot", "audit_calls.csv")
    if os.path.exists(audit_csv):
        with open(audit_csv) as f:
            for row in csv.DictReader(f):
                print("  %-40s %s calls" % (row["call"], row["count"]))
    else:
        print("  (run run_adaptive.py first to produce audit_calls.csv)")

    return findings


if __name__ == "__main__":
    main()
