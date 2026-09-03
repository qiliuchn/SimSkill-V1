#!/usr/bin/env python3
"""
Behavioral FCD verification of candidates A and C: force an EB-direction
median user and a WB-direction median user to be in the SAME coincident
median segment at the same time, run with --fcd-output (0.2s resolution)
AND --collision-output side by side, then independently reconstruct a
common chainage and compute the TRUE minimum physical separation --
following the corrected |chain_a - chain_b| method (never a signed gap),
per the verified methodology in
control-one-lane-two-way-alternating-flow-through-a-work-zone /
one-lane-two-way-alternating-flow-and-shared-lane-representation.
"""
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.abspath(__file__))
VTYPE = ('  <vType id="car" vClass="passenger" length="4.5" minGap="2.5" accel="2.6" '
         'decel="4.5" sigma="0.5" maxSpeed="13.89"/>\n')

SCENARIOS = {
    "candA": {
        "netfile": "net.net.xml",
        "vehicles": [
            # EB user: exits W boundary, merges into median at D1, peels into A2 driveway near D2
            ("eb_refuge", 0, "EB_W_D1 MED_EB_D1_D2 IN_A2"),
            # WB user: exits E boundary, merges into median at D2, peels into A1 driveway near D1
            ("wb_refuge", 0, "WB_E_D2 MED_WB_D2_D1 IN_A1"),
            # a second, offset pair to sample a different meeting point
            ("eb_refuge2", 3, "EB_W_D1 MED_EB_D1_D2 IN_B2"),
            ("wb_refuge2", 3, "WB_E_D2 MED_WB_D2_D1 IN_B1"),
        ],
    },
    "candC": {
        "netfile": "net.net.xml",
        "vehicles": [
            # EB user: exits driveway B1 (local pocket), rejoins EB mainline via D1d
            ("eb_pocket", 0, "OUT_B1 MED_EB_D1_D1d EB_D1d_D2u"),
            # WB user: arrives from D2 side, uses the SAME D1-D1d coincident span to reach A1
            ("wb_pocket", 0, "WB_D2u_D1d MED_WB_D1d_D1 IN_A1"),
            ("eb_pocket2", 2, "OUT_A2 MED_EB_D2_D2d EB_D2d_E"),
            ("wb_pocket2", 2, "WB_E_D2d MED_WB_D2d_D2 IN_B2"),
            # SYNCED pair: wb_pocket3 has a 124.5 m lead-in (~9.0s @13.89 m/s)
            # before it ever reaches the pocket; depart it 9.0s BEFORE
            # eb_pocket3 so both genuinely try to occupy the short local
            # pocket at the same time (eb_pocket3 has almost no lead-in).
            ("eb_pocket3", 9, "OUT_B1 MED_EB_D1_D1d EB_D1d_D2u"),
            ("wb_pocket3", 0, "WB_D2u_D1d MED_WB_D1d_D1 IN_A1"),
        ],
    },
}


def build_route_file(cand, outdir):
    spec = SCENARIOS[cand]
    with open(os.path.join(outdir, "routes.rou.xml"), "w") as f:
        f.write("<routes>\n")
        f.write(VTYPE)
        for vid, depart, edges in sorted(spec["vehicles"], key=lambda v: v[1]):
            f.write(f'  <vehicle id="{vid}" type="car" depart="{depart}">\n')
            f.write(f'    <route edges="{edges}"/>\n')
            f.write("  </vehicle>\n")
        f.write("</routes>\n")


def run_sumo(cand, outdir):
    net = os.path.join(ROOT, cand, SCENARIOS[cand]["netfile"])
    rou = os.path.join(outdir, "routes.rou.xml")
    fcd = os.path.join(outdir, "fcd.xml")
    coll = os.path.join(outdir, "collisions.xml")
    cmd = ["sumo", "-n", net, "-r", rou,
           "--fcd-output", fcd, "--fcd-output.geo", "false",
           "--collision-output", coll,
           "--collision.action", "warn",
           "--collision.check-junctions", "true",
           "--step-length", "0.2",
           "--no-step-log", "true",
           "-e", "60"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    with open(os.path.join(outdir, "sumo.log"), "w") as f:
        f.write(" ".join(cmd) + "\n\n" + r.stdout + "\n" + r.stderr)
    return r.returncode, r.stdout + r.stderr


def analyze_fcd(cand, outdir):
    """Reconstruct true physical separation between the EB-direction and
    WB-direction median users using RAW (x,y) positions from FCD (not
    edge-relative chainage, since the two vehicles are on different edge
    IDs) -- this is even more direct than the work-zone skill's chainage
    reconstruction, since we have real x/y here."""
    fcd = os.path.join(outdir, "fcd.xml")
    tree = ET.parse(fcd)
    by_time = {}
    for ts in tree.getroot().findall("timestep"):
        t = float(ts.get("time"))
        vehs = {}
        for v in ts.findall("vehicle"):
            vehs[v.get("id")] = (float(v.get("x")), float(v.get("y")), v.get("lane"))
        by_time[t] = vehs

    if cand == "candA":
        pairs = [("eb_refuge", "MED_EB_D1_D2_0", "wb_refuge", "MED_WB_D2_D1_0"),
                 ("eb_refuge2", "MED_EB_D1_D2_0", "wb_refuge2", "MED_WB_D2_D1_0")]
    else:
        pairs = [("eb_pocket", "MED_EB_D1_D1d_0", "wb_pocket", "MED_WB_D1d_D1_0"),
                 ("eb_pocket2", "MED_EB_D2_D2d_0", "wb_pocket2", "MED_WB_D2d_D2_0"),
                 ("eb_pocket3", "MED_EB_D1_D1d_0", "wb_pocket3", "MED_WB_D1d_D1_0")]

    min_sep = {}
    for a, lane_a, b, lane_b in pairs:
        best = None
        best_t = None
        n_coincident_steps = 0
        for t, vehs in by_time.items():
            if a in vehs and b in vehs:
                xa, ya, la = vehs[a]
                xb, yb, lb = vehs[b]
                # ONLY compare while both are genuinely on the coincident
                # median lane pair (not after either has left it) --
                # otherwise a lateral (different-lane) crossing at a
                # junction gets misread as a same-lane overlap.
                if la == lane_a and lb == lane_b:
                    n_coincident_steps += 1
                    d = ((xa - xb) ** 2 + (ya - yb) ** 2) ** 0.5
                    sep = d - 4.5  # subtract vehicle length (both moving along the same line)
                    if best is None or sep < best:
                        best = sep
                        best_t = t
        min_sep[(a, b)] = (best, best_t, n_coincident_steps)
    return min_sep


if __name__ == "__main__":
    for cand in ["candA", "candC"]:
        outdir = os.path.join(ROOT, cand, "fcdtest")
        os.makedirs(outdir, exist_ok=True)
        build_route_file(cand, outdir)
        rc, log = run_sumo(cand, outdir)
        print(f"\n===== {cand}: sumo returncode={rc} =====")
        for line in log.splitlines():
            if "arning" in line or "rror" in line or "ollision" in line:
                print("   ", line)
        coll_path = os.path.join(outdir, "collisions.xml")
        if os.path.exists(coll_path):
            with open(coll_path) as f:
                content = f.read()
            print(f"   collision-output file content: {content.strip()[:300]!r}")
        sep = analyze_fcd(cand, outdir)
        for pair, (best, best_t, nsteps) in sep.items():
            print(f"   pair {pair}: min TRUE separation on coincident median lane = {best:.2f} m "
                  f"at t={best_t}s (co-present on the SAME coincident lane pair for {nsteps} steps)"
                  if best is not None else f"   pair {pair}: never simultaneously on the coincident lane pair")
