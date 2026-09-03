#!/usr/bin/env python3
"""End-to-end park-and-ride case: build supply -> route -> couple -> simulate -> analyse.

python run_case.py --name cap50 --lots PR_MID,PR_MID2 --cap-mid 50 --cap-mid2 400 \
    --rerouter PR_MID:PR_MID2 --transfer parkingAreas --headway 300
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EP = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
NET = os.path.join(EP, "outputs", "net", "corridor.net.xml")
RUNS = os.path.join(EP, "outputs", "runs")
BASE_WEIGHTS = os.path.join(RUNS, "baseline_drive", "edgedata.xml")
# edges giving the rerouter genuine upstream reach toward PR_MID (on A0_A1)
REROUTER_EDGES = ["SUB21_ST", "ST_A0", "A0_A1"]


def sh(cmd, **kw):
    print("+", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        sys.stderr.write(r.stdout[-3000:] + r.stderr[-3000:])
        raise SystemExit("FAILED: " + " ".join(cmd))
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--lots", default="PR_MAIN,PR_OVER,PR_MID,PR_MID2")
    ap.add_argument("--cap-main", type=int, default=400)
    ap.add_argument("--cap-overflow", type=int, default=400)
    ap.add_argument("--cap-mid", type=int, default=400)
    ap.add_argument("--cap-mid2", type=int, default=400)
    ap.add_argument("--headway", type=int, default=300)
    ap.add_argument("--transfer", default="parkingAreas")
    ap.add_argument("--modes", default="car public")
    ap.add_argument("--persons", type=int, default=1200)
    ap.add_argument("--rerouter", default=None, help="PRIMARY:ALT1,ALT2")
    ap.add_argument("--couple", default="1")
    ap.add_argument("--pm-share", type=float, default=0.0)
    ap.add_argument("--release-at", type=int, default=None)
    ap.add_argument("--use-weights", default="1")
    ap.add_argument("--end", type=int, default=25000)
    ap.add_argument("--pt-end", type=int, default=25200)
    a = ap.parse_args()

    d = os.path.join(RUNS, a.name)
    os.makedirs(d, exist_ok=True)
    bs = [sys.executable, os.path.join(HERE, "build_scenario.py"), "--out-dir", d,
          "--persons", str(a.persons), "--headway", str(a.headway),
          "--cap-main", str(a.cap_main), "--cap-overflow", str(a.cap_overflow),
          "--cap-mid", str(a.cap_mid), "--cap-mid2", str(a.cap_mid2),
          "--only-lots", a.lots, "--modes", a.modes, "--pt-end", str(a.pt_end)]
    if a.pm_share > 0:
        bs += ["--pm-share", str(a.pm_share), "--pm-begin", "18000", "--pm-end", "23400"]
    sh(bs)

    add = [os.path.join(d, "stops.add.xml"), os.path.join(d, "parking.add.xml")]
    # route
    routed = os.path.join(d, "routed.rou.xml")
    du = ["duarouter", "-n", NET, "-a", ",".join(add),
          "-r", ",".join([os.path.join(d, "brt.rou.xml"), os.path.join(d, "persons.trips.xml")]),
          "-o", routed, "--persontrip.transfer.car-walk", a.transfer, "--ignore-errors"]
    if a.use_weights == "1" and os.path.exists(BASE_WEIGHTS):
        du += ["-w", BASE_WEIGHTS]
    sh(du)

    sim_routes = routed
    if a.couple == "1":
        coupled = os.path.join(d, "coupled.rou.xml")
        cc = [sys.executable, os.path.join(HERE, "attach_parking_stops.py"),
              "--routes", routed, "--parking", os.path.join(d, "parking.add.xml"),
              "--out", coupled]
        if a.release_at is not None:
            cc += ["--release-at", str(a.release_at)]
        r = sh(cc)
        print(r.stdout)
        with open(os.path.join(d, "coupling.log"), "w") as fh:
            fh.write(r.stdout)
        sim_routes = coupled

    if a.rerouter:
        prim, alts = a.rerouter.split(":")
        rr = os.path.join(d, "rerouter.add.xml")
        sys.path.insert(0, HERE)
        from build_scenario import write_rerouter
        write_rerouter(rr, prim, alts.split(","), REROUTER_EDGES)
        add.append(rr)

    run = [sys.executable, os.path.join(HERE, "run_pr_scenario.py"), "--net", NET,
           "--routes", ",".join([os.path.join(d, "brt.rou.xml"), sim_routes]),
           "--additional", ",".join(add), "--lots", a.lots,
           "--out-dir", d, "--end", str(a.end), "--time-to-teleport", "300",
           "--label", a.name]
    if a.rerouter:
        run += ["--device-rerouting-probability", "1"]
    sh(run)

    an = [sys.executable, os.path.join(HERE, "analyze_pr.py"), "--run-dir", d,
          "--label", a.name, "--out", os.path.join(d, "analysis.json")]
    r = sh(an)
    print(r.stdout)
    with open(os.path.join(d, "case.json"), "w") as fh:
        json.dump(vars(a), fh, indent=1)


if __name__ == "__main__":
    main()
