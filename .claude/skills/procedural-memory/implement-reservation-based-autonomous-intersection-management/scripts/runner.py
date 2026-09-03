#!/usr/bin/env python3
"""
Single entry point for one simulation run of the AIM study.

Controllers
-----------
  fixed       : static Webster-sized fixed-time plan (tlLogic from an additional file)
  actuated    : SUMO native gap-based actuated logic (net rebuilt with
                --tls.default-type actuated; `control-signals-with-actuated-tls`)
  maxpressure : the max-pressure TraCI controller from
                `implement-maxpressure-traci-controller` (imported, not re-implemented)
  aim         : the reservation-based AIM infrastructure agent (aim.py)
  allwaystop  : all-way-stop network variant (negative-control reference target)

Every run writes tripinfo / summary / collisions / a SUMO log (for teleport
reasons) / statistic-output into --outdir, plus stats.json with the controller's
own instrumentation.  Zero-collision claims are only meaningful with
--collision.check-junctions enabled, which this runner always sets.
"""
import argparse
import glob
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

SUMO_HOME = os.environ["SUMO_HOME"]
sys.path.append(os.path.join(SUMO_HOME, "tools"))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
# project root is 5 levels up: scripts/ -> outputs/ -> <episode>/ -> episodic-memory/ -> root
_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "..", "..", "..", ".."))
sys.path.append(os.path.join(_ROOT, ".claude", "skills", "procedural-memory",
                             "implement-maxpressure-traci-controller", "scripts"))

import traci  # noqa: E402
SUMO_BIN = os.path.join(SUMO_HOME, "bin", "sumo")
if not os.path.exists(SUMO_BIN):
    import shutil
    SUMO_BIN = shutil.which("sumo")


def base_args(net, routes, outdir, seed, end, step, tts, extra=None):
    a = [SUMO_BIN,
         "-n", net, "-r", routes,
         "--tripinfo-output", os.path.join(outdir, "tripinfo.xml"),
         "--summary-output", os.path.join(outdir, "summary.xml"),
         "--statistic-output", os.path.join(outdir, "stat.xml"),
         "--collision-output", os.path.join(outdir, "collisions.xml"),
         "--collision.action", "warn",
         "--collision.check-junctions", "true",
         "--collision.mingap-factor", "0",
         "--log", os.path.join(outdir, "sumo.log"),
         "--seed", str(seed),
         "--step-length", str(step),
         "--time-to-teleport", str(tts),
         "--begin", "0", "--end", str(end),
         "--no-step-log", "true",
         "--duration-log.statistics", "true",
         "--xml-validation", "never",
         "--default.speeddev", "0",
         ]
    if extra:
        a += extra
    return a


def parse_teleports(logpath):
    """tripinfo has no teleport field -- teleport info must come from the log
    (`validate-congested-scenario-results-against-teleport-artifacts`).

    BUG FIX (episode 75 / AIM critic review): an earlier version of this function
    counted every log line CONTAINING the substring "teleport", which double-counts
    each teleport event (SUMO logs both a "Teleporting vehicle '...'" begin line and
    an "...ends teleporting" end line for the same event) and ALSO separately matches
    SUMO's own authoritative end-of-run summary line
    ("Teleports: N (Jam: X, Yield: Y, ...)"), inflating jam/yield roughly 2x. Parse
    ONLY that single authoritative summary line instead -- it is SUMO's own final
    tally and is not subject to double-counting."""
    res = {"total": 0, "jam": 0, "yield": 0, "wrongLane": 0, "vehicles": []}
    if not os.path.exists(logpath):
        return res
    summary_pat = re.compile(
        r"Teleports:\s*(\d+)\s*\(Jam:\s*(\d+),\s*Yield:\s*(\d+),\s*Wrong Lane:\s*(\d+)\)",
        re.I,
    )
    vehicle_pat = re.compile(r"Vehicle '([^']+)'.*teleport", re.I)
    with open(logpath, errors="ignore") as f:
        for line in f:
            m = summary_pat.search(line)
            if m:
                res["total"] = int(m.group(1))
                res["jam"] = int(m.group(2))
                res["yield"] = int(m.group(3))
                res["wrongLane"] = int(m.group(4))
                continue
            # still collect vehicle ids for diagnostics, but never use this loop
            # to increment any of the count fields above
            vm = vehicle_pat.search(line)
            if vm and "teleport" in line.lower():
                res["vehicles"].append(vm.group(1))
    return res


def parse_collisions(path):
    if not os.path.exists(path):
        return {"n": 0, "junction": 0, "records": []}
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return {"n": -1, "junction": -1, "records": []}
    recs = []
    for c in root.findall("collision"):
        recs.append({k: c.get(k) for k in
                     ("time", "type", "lane", "pos", "collider", "victim")})
    nj = sum(1 for r in recs if (r.get("lane") or "").startswith(":"))
    return {"n": len(recs), "junction": nj, "records": recs[:200]}


def run(args):
    os.makedirs(args.outdir, exist_ok=True)
    meta = {}
    if args.meta:
        with open(args.meta) as f:
            meta = json.load(f)

    extra = []
    if args.additional:
        extra += ["-a", args.additional]
    if args.ssm_out:
        # SSM output path must be per-run: a relative device.ssm.file resolves
        # against the invoking cwd, so parallel runs would overwrite each other
        extra += ["--device.ssm.file", os.path.abspath(
            os.path.join(args.outdir, "ssm.xml"))]
    cmd = base_args(args.net, args.routes, args.outdir, args.seed,
                    args.end, args.step, args.tts, extra)

    stats = {"controller": args.controller}

    if args.controller in ("fixed", "actuated", "allwaystop"):
        import subprocess
        p = subprocess.run(cmd, capture_output=True, text=True)
        stats["returncode"] = p.returncode
        if p.returncode != 0:
            stats["stderr"] = p.stderr[-4000:]
            sys.stderr.write(p.stderr[-4000:])
            raise SystemExit("sumo returned %d" % p.returncode)
    else:
        traci.start(cmd, label=os.path.basename(args.outdir))
        try:
            if args.controller == "maxpressure":
                # the skill's pressure rule, but with the program's ALL-RED
                # clearance restored -- without it the baseline itself produces
                # junction collisions on this permissive-left program (mp_allred)
                from mp_allred import JunctionControllerAllRed as JunctionController
                ctrls = [JunctionController(t, args.mp_min_green, args.mp_interval)
                         for t in traci.trafficlight.getIDList()]
                now = traci.simulation.getTime()
                for c in ctrls:
                    c.start(now)
                while traci.simulation.getMinExpectedNumber() > 0:
                    traci.simulationStep()
                    now = traci.simulation.getTime()
                    if now >= args.end:
                        break
                    for c in ctrls:
                        c.step(now)
            elif args.controller == "aim":
                from aim import AIMController
                params = dict(
                    zone=args.zone, buffer=args.buffer, hmin=args.hmin,
                    policy=args.policy, latency=args.latency,
                    pos_noise=args.pos_noise, penetration=args.penetration,
                    dt=args.step, noise_seed=args.seed * 7919 + 13,
                    batch_max_n=args.batch_max_n, batch_max_t=args.batch_max_t,
                    unsafe=args.unsafe, lat_comp=args.lat_comp,
                )
                A = AIMController(args.conflicts, meta, params)
                bad = A.verify_groups()
                if bad:
                    raise RuntimeError("HDV virtual-phase groups are not "
                                       "conflict-free: %s" % bad[:5])
                A.start()
                while traci.simulation.getMinExpectedNumber() > 0:
                    traci.simulationStep()
                    now = traci.simulation.getTime()
                    if now >= args.end:
                        break
                    for vid in traci.simulation.getDepartedIDList():
                        A.on_depart(vid)
                    A.step(now, traci.vehicle.getAllSubscriptionResults())
                stats.update({k: v for k, v in A.stats.items()})
                stats["n_cav"] = sum(1 for v in A.is_cav.values() if v)
                stats["n_hdv"] = sum(1 for v in A.is_cav.values() if not v)
            else:
                raise SystemExit("unknown controller %s" % args.controller)
        finally:
            try:
                traci.close()
            except Exception:
                pass

    stats["teleports"] = parse_teleports(os.path.join(args.outdir, "sumo.log"))
    stats["collisions"] = parse_collisions(os.path.join(args.outdir, "collisions.xml"))
    with open(os.path.join(args.outdir, "stats.json"), "w") as f:
        json.dump(stats, f, indent=1)
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", required=True)
    ap.add_argument("--routes", required=True)
    ap.add_argument("--meta", default="")
    ap.add_argument("--conflicts", default="")
    ap.add_argument("--controller", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--additional", default="")
    ap.add_argument("--ssm-out", default="")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--end", type=float, default=3600.0)
    ap.add_argument("--step", type=float, default=0.2)
    ap.add_argument("--tts", type=float, default=300.0)
    ap.add_argument("--mp-min-green", type=float, default=8.0)
    ap.add_argument("--mp-interval", type=float, default=5.0)
    ap.add_argument("--zone", type=float, default=150.0)
    ap.add_argument("--buffer", type=float, default=0.6)
    ap.add_argument("--hmin", type=float, default=1.4)
    ap.add_argument("--policy", default="fcfs")
    ap.add_argument("--latency", type=float, default=0.0)
    ap.add_argument("--pos-noise", type=float, default=0.0)
    ap.add_argument("--penetration", type=float, default=1.0)
    ap.add_argument("--batch-max-n", type=int, default=10)
    ap.add_argument("--batch-max-t", type=float, default=25.0)
    ap.add_argument("--unsafe", type=int, default=0)
    ap.add_argument("--lat-comp", type=int, default=0)
    a = ap.parse_args()
    s = run(a)
    print(json.dumps({k: v for k, v in s.items() if k != "collisions"}, default=str))
    print("collisions:", s["collisions"]["n"], "junction:", s["collisions"]["junction"])


if __name__ == "__main__":
    main()
