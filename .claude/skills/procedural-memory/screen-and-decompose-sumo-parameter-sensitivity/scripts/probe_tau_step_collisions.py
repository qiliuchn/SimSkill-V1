#!/usr/bin/env python3
"""ROOT-CAUSE PROBE -- why the low-tau corner of the factor box produces
thousands of genuine collisions, and what the collision-free region actually is.

Hypothesis: SUMO's Krauss safe-velocity guarantee only holds when the desired
time headway `tau` is at least the integration step (and the actionStepLength).
With the default 1 s step, tau = 0.7 s is OUTSIDE the model's collision-free
region, so every low-tau design point is contaminated by
`--collision.action teleport` (the default) removing vehicles.

Three orthogonal sweeps, all at the SAME otherwise-worst design point:
  A. tau sweep at step-length 1.0 s
  B. step-length sweep at tau = 0.7 s
  C. sigma sweep at tau = 0.7 s and at tau = 1.0 s (to check sigma is not the
     independent cause)

Everything is read from --statistic-output (safety/@collisions and
teleports/@total), which is the authoritative counter.
"""
import os, sys, json, subprocess
import xml.etree.ElementTree as ET
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gsa_common as G
import sumolib

WORK = os.path.join(G.RAW, "tau_step_probe")
NET = sumolib.net.readNet(G.NET)


def run(p, regime, seed, tag, step=1.0):
    root = os.path.join(WORK, tag)
    os.makedirs(root, exist_ok=True)
    vt = G.write_vtypes(os.path.join(root, "vtypes.add.xml"), p)
    tls = G.make_plan(p).write_add(NET, os.path.join(root, "tls.add.xml"))
    st = os.path.join(root, "stats.xml")
    cmd = [G.SUMO, "-n", G.NET, "-r", os.path.join(G.SCN, "routes_%s.rou.xml" % regime),
           "-a", ",".join([vt, tls]), "--begin", "0", "--end", "%.1f" % G.END,
           "--seed", str(seed), "--no-step-log", "true", "--time-to-teleport", "300",
           "--scale", "%.6f" % p["demandScale"], "--step-length", "%.3f" % step,
           "--statistic-output", st, "--duration-log.statistics", "true",
           "--xml-validation", "never", "--no-warnings", "true"]
    pr = subprocess.run(cmd, capture_output=True, text=True, cwd=root)
    assert pr.returncode == 0, pr.stderr[-1500:]
    t = ET.parse(st).getroot()
    saf = t.find("safety"); tel = t.find("teleports"); veh = t.find("vehicles")
    vts = t.find("vehicleTripStatistics")
    return dict(step=step, tau=p["tau"], sigma=p["sigma"],
                collisions=int(saf.get("collisions")),
                emergencyBraking=int(saf.get("emergencyBraking", 0)),
                teleports_total=int(tel.get("total")),
                teleports_jam=int(tel.get("jam")), teleports_yield=int(tel.get("yield")),
                teleports_wrongLane=int(tel.get("wrongLane")),
                inserted=int(veh.get("inserted")), loaded=int(veh.get("loaded")),
                duration=float(vts.get("duration")),
                timeLoss=float(vts.get("timeLoss")),
                speed=float(vts.get("speed")))


def main():
    RAWP = json.load(open(os.path.join(G.TBL, "morris_raw_points.json")))
    base = max(RAWP["over"], key=lambda r: r["teleports"])["params"]
    out = {"anchor_point": base}

    print("anchor = the OVER regime's worst Morris design point:")
    print(" ", json.dumps({k: round(v, 4) for k, v in base.items()}))

    print("\nA. tau sweep, step-length 1.0 s (all other factors at the anchor)")
    A = []
    for tau in (0.70, 0.80, 0.90, 1.00, 1.10, 1.40, 1.80):
        p = dict(base); p["tau"] = tau
        r = run(p, "over", 1001, "A_tau%.2f" % tau, step=1.0)
        A.append(r)
        print("   tau=%.2f  collisions=%6d  teleports(total/jam/yield/wrong)="
              "%6d/%d/%d/%d  meanDuration=%.1f" %
              (tau, r["collisions"], r["teleports_total"], r["teleports_jam"],
               r["teleports_yield"], r["teleports_wrongLane"], r["duration"]))

    print("\nB. step-length sweep at tau = 0.70 s")
    B = []
    for step in (1.0, 0.7, 0.5, 0.25, 0.1):
        p = dict(base); p["tau"] = 0.70
        r = run(p, "over", 1001, "B_step%.2f" % step, step=step)
        B.append(r)
        print("   step=%.2f s  collisions=%6d  teleports=%6d  meanDuration=%.1f"
              % (step, r["collisions"], r["teleports_total"], r["duration"]))

    print("\nC. sigma sweep, to check sigma is not the independent cause")
    C = []
    for tau in (0.70, 1.00):
        for sg in (0.0, 0.45, 0.90):
            p = dict(base); p["tau"] = tau; p["sigma"] = sg
            r = run(p, "over", 1001, "C_t%.2f_s%.2f" % (tau, sg), step=1.0)
            C.append(r)
            print("   tau=%.2f sigma=%.2f  collisions=%6d  teleports=%6d"
                  % (tau, sg, r["collisions"], r["teleports_total"]))

    # how much of the Morris design is inside vs outside the safe region
    RAWD = {}
    for reg in ("under", "over"):
        rows = RAWP[reg]
        lo, hi = G.SPACE["tau"]
        under1 = [r for r in rows if r["params"]["tau"] < 1.0 - 1e-9]
        over1 = [r for r in rows if r["params"]["tau"] >= 1.0 - 1e-9]
        def frac(rs):
            return (sum(1 for r in rs if r["teleports"] > 0) / len(rs)) if rs else float("nan")
        def mx(rs):
            return max((r["teleports"] for r in rs), default=0.0)
        RAWD[reg] = dict(n_points_tau_lt_1=len(under1), n_points_tau_ge_1=len(over1),
                         frac_with_teleports_tau_lt_1=frac(under1),
                         frac_with_teleports_tau_ge_1=frac(over1),
                         max_teleports_tau_lt_1=mx(under1),
                         max_teleports_tau_ge_1=mx(over1))
        print("\n%s regime, Morris design points split at tau = step length "
              "(1.0 s):" % reg)
        print("   tau <  1.0 s : %3d points, %.1f%% have teleports, max %.0f"
              % (RAWD[reg]["n_points_tau_lt_1"],
                 100 * RAWD[reg]["frac_with_teleports_tau_lt_1"],
                 RAWD[reg]["max_teleports_tau_lt_1"]))
        print("   tau >= 1.0 s : %3d points, %.1f%% have teleports, max %.0f"
              % (RAWD[reg]["n_points_tau_ge_1"],
                 100 * RAWD[reg]["frac_with_teleports_tau_ge_1"],
                 RAWD[reg]["max_teleports_tau_ge_1"]))

    json.dump(dict(anchor=base, tau_sweep_step1=A, step_sweep_tau070=B,
                   sigma_sweep=C, morris_design_split=RAWD),
              open(os.path.join(G.TBL, "tau_step_collision_probe.json"), "w"),
              indent=2)
    print("\nwrote", os.path.join(G.TBL, "tau_step_collision_probe.json"))


if __name__ == "__main__":
    main()
