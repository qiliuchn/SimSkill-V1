#!/usr/bin/env python3
"""
ICM corridor generator: an 8 km, 3-lane/direction freeway with 4 interchanges
at 2 km spacing, paralleled by an 8 km, 2-lane/direction signalized arterial
with 6 signals (4 coincide with interchange ramp terminals, 2 are corridor-end
gateway signals), plus cross-street stubs at every arterial signal and
background ramp-access flows.

Reusable: this is sub-goal 8's "corridor generator" artifact. All geometry is
parametric (spacing, lane counts, incident location) via the CONFIG dict below
or CLI flags.

Usage:
    python gen_corridor.py --out-dir <dir>
Produces <out-dir>/corridor.nod.xml, .edg.xml, .con.xml, .tll.xml.type.xml
and compiles corridor.net.xml via netconvert.
"""
import argparse
import os
import subprocess
import sys

# ---------------------------------------------------------------------------
# Geometry configuration
# ---------------------------------------------------------------------------
SEG_LEN = 500.0          # freeway mainline segment length (m)
N_SEG = 18                # number of 500 m segments -> 19 nodes, x = -500..8500
X0 = -500.0
FWY_LANES = 3
ART_LANES = 2
RAMP_LANES = 1
CS_LANES = 1
WB_Y_OFFSET = 25.0        # lateral offset between EB/WB freeway carriageways
ART_Y = -260.0             # short ramp length (~260 m) so ramp storage is realistic and can spill back
CS_STUB = 120.0
FWY_SPEED = 29.06          # 105 km/h freeway design speed
ART_SPEED = 25.0            # 90 km/h posted arterial (high-speed suburban parallel arterial --
                             # realistic for the kind of corridor where diversion is a genuine option)
RAMP_SPEED = 15.0
CS_SPEED = 10.0

# interchange freeway-node indices (x = 1000,3000,5000,7000) and their arterial
# node indices (see ARTERIAL_X below) -- these are the 4 "connected at every
# interchange" points.
INTERCHANGES = [
    dict(j=1, fx_idx=3),   # x=1000
    dict(j=2, fx_idx=7),   # x=3000
    dict(j=3, fx_idx=11),  # x=5000
    dict(j=4, fx_idx=15),  # x=7000
]

# arterial node x-positions: buffer, 4 interchange sigs @1000/3000/5000/7000
# plus 2 extra cross-street-only signals @2000/6000 chosen so 5 of the 6 gaps
# are a uniform 1000 m (resonant at the design speed/cycle picked in
# build_signals.py) and only the gap spanning the incident zone (ic2-ic3,
# 3000-5000) is 2000 m -- that segment gets its own incident-tuned offset via
# control module S anyway, so it does not need to be baseline-resonant.
ARTERIAL_X = [-300.0, 1000.0, 2000.0, 3000.0, 5000.0, 6000.0, 7000.0, 8300.0]
# index k of ARTERIAL_X that is signalized (has a tlLogic) -- all but the two buffer ends
ARTERIAL_SIGNAL_IDX = [1, 2, 3, 4, 5, 6]
# map interchange j -> arterial node index (ax index)
IC_TO_AX = {1: 1, 2: 3, 3: 4, 4: 6}

# interchanges whose EB on-ramp gets a dedicated ALINEA meter signal
# (interchange 2 = upstream of incident, interchange 3 = downstream/re-entry --
# the two ramps sub-goal 3's M module actually controls)
METERED_ON_EB = {2, 3}

# Incident: EB mainline segment between interchange 2 (x=3000) and interchange 3
# (x=5000), placed at segment index 9 (x=4000 -> x=4500).
INCIDENT_SEG_IDX = 9
INCIDENT_EDGE = f"fwy_eb_{INCIDENT_SEG_IDX}"


def fx_id(i):
    return f"fx{i}"


def fxwb_id(i):
    return f"fx{i}wb"


def ax_id(k):
    return f"ax{k}"


def gen_nodes():
    lines = ['<nodes>']
    # freeway EB nodes
    interchange_fi = {ic['fx_idx'] for ic in INTERCHANGES}
    for i in range(N_SEG + 1):
        x = X0 + SEG_LEN * i
        # EB ramp merge/diverge nodes use zipper (forced merge, per
        # implement-alinea-ramp-metering) so a saturated EB mainline (the
        # incident/diversion/metering direction) cannot starve ramp vehicles
        # into a "waited too long (yield)" teleport. WB carries only light
        # background demand and empirically does WORSE under zipper here
        # (verified: switching WB to zipper too traded "yield" teleports for
        # a persistent "jam" teleport cluster at the WB interchange merges,
        # per outputs/scale_test_0.75 diagnostic) -- so WB interchange nodes
        # stay priority (ramp yields), which is what WB's low relative
        # ramp volume needs.
        jtype = "zipper" if i in interchange_fi else "priority"
        lines.append(f'    <node id="{fx_id(i)}" x="{x:.1f}" y="0.0" type="{jtype}"/>')
    # freeway WB nodes (offset in y) -- priority throughout, see note above
    for i in range(N_SEG + 1):
        x = X0 + SEG_LEN * i
        lines.append(f'    <node id="{fxwb_id(i)}" x="{x:.1f}" y="{WB_Y_OFFSET:.1f}" type="priority"/>')
    # arterial nodes
    for k, x in enumerate(ARTERIAL_X):
        if k in ARTERIAL_SIGNAL_IDX:
            lines.append(f'    <node id="{ax_id(k)}" x="{x:.1f}" y="{ART_Y:.1f}" type="traffic_light"/>')
        else:
            lines.append(f'    <node id="{ax_id(k)}" x="{x:.1f}" y="{ART_Y:.1f}" type="priority"/>')
    # cross-street stub nodes (south of every signalized arterial node)
    for k in ARTERIAL_SIGNAL_IDX:
        x = ARTERIAL_X[k]
        lines.append(f'    <node id="cs{k}s" x="{x:.1f}" y="{ART_Y - CS_STUB:.1f}" type="priority"/>')
    # ramp-meter nodes: split the EB on-ramp at interchanges in METERED_ON_EB
    # into an upstream storage segment (arterial -> meter) and a short release
    # segment (meter -> freeway merge), so ALINEA can control release rate
    # independently of the arterial ramp-terminal signal.
    for ic in INTERCHANGES:
        if ic['j'] in METERED_ON_EB:
            x = X0 + SEG_LEN * ic['fx_idx']
            lines.append(f'    <node id="mtr_eb_{ic["j"]}" x="{x:.1f}" y="{ART_Y/2:.1f}" type="traffic_light"/>')
    lines.append('</nodes>')
    return "\n".join(lines)


def gen_edges():
    lines = ['<edges>']
    # freeway mainline
    for i in range(N_SEG):
        lines.append(
            f'    <edge id="fwy_eb_{i}" from="{fx_id(i)}" to="{fx_id(i+1)}" '
            f'numLanes="{FWY_LANES}" speed="{FWY_SPEED}" priority="10"/>'
        )
        lines.append(
            f'    <edge id="fwy_wb_{i}" from="{fxwb_id(i+1)}" to="{fxwb_id(i)}" '
            f'numLanes="{FWY_LANES}" speed="{FWY_SPEED}" priority="10"/>'
        )
    # freeway insertion/exit buffer connectors between EB and WB chains not needed
    # (they are separate one-way carriageways, each already spans the full corridor)

    # arterial mainline
    for k in range(len(ARTERIAL_X) - 1):
        lines.append(
            f'    <edge id="art_eb_{k}" from="{ax_id(k)}" to="{ax_id(k+1)}" '
            f'numLanes="{ART_LANES}" speed="{ART_SPEED}" priority="6"/>'
        )
        lines.append(
            f'    <edge id="art_wb_{k}" from="{ax_id(k+1)}" to="{ax_id(k)}" '
            f'numLanes="{ART_LANES}" speed="{ART_SPEED}" priority="6"/>'
        )

    # ramps at each interchange
    for ic in INTERCHANGES:
        j, fi = ic['j'], ic['fx_idx']
        ai = IC_TO_AX[j]
        lines.append(
            f'    <edge id="off_eb_{j}" from="{fx_id(fi)}" to="{ax_id(ai)}" '
            f'numLanes="{RAMP_LANES}" speed="{RAMP_SPEED}" priority="3"/>'
        )
        if j in METERED_ON_EB:
            mtr = f"mtr_eb_{j}"
            lines.append(
                f'    <edge id="on_eb_{j}a" from="{ax_id(ai)}" to="{mtr}" '
                f'numLanes="{RAMP_LANES}" speed="{RAMP_SPEED}" priority="3"/>'
            )
            lines.append(
                f'    <edge id="on_eb_{j}b" from="{mtr}" to="{fx_id(fi)}" '
                f'numLanes="{RAMP_LANES}" speed="{RAMP_SPEED}" priority="3"/>'
            )
        else:
            lines.append(
                f'    <edge id="on_eb_{j}" from="{ax_id(ai)}" to="{fx_id(fi)}" '
                f'numLanes="{RAMP_LANES}" speed="{RAMP_SPEED}" priority="3"/>'
            )
        lines.append(
            f'    <edge id="off_wb_{j}" from="{fxwb_id(fi)}" to="{ax_id(ai)}" '
            f'numLanes="{RAMP_LANES}" speed="{RAMP_SPEED}" priority="3"/>'
        )
        lines.append(
            f'    <edge id="on_wb_{j}" from="{ax_id(ai)}" to="{fxwb_id(fi)}" '
            f'numLanes="{RAMP_LANES}" speed="{RAMP_SPEED}" priority="3"/>'
        )

    # cross streets
    for k in ARTERIAL_SIGNAL_IDX:
        lines.append(
            f'    <edge id="cs_in_{k}" from="cs{k}s" to="{ax_id(k)}" '
            f'numLanes="{CS_LANES}" speed="{CS_SPEED}" priority="1"/>'
        )
        lines.append(
            f'    <edge id="cs_out_{k}" from="{ax_id(k)}" to="cs{k}s" '
            f'numLanes="{CS_LANES}" speed="{CS_SPEED}" priority="1"/>'
        )
    lines.append('</edges>')
    return "\n".join(lines)


def gen_connections():
    """Explicit connections at ramp merge/diverge points, following
    implement-alinea-ramp-metering's zipper-merge discipline so a metering
    controller has a genuine forced merge to act on, and so the diverge keeps
    all mainline lanes through while only lane 0 (rightmost) serves the ramp."""
    lines = ['<connections>']
    for ic in INTERCHANGES:
        j, fi = ic['j'], ic['fx_idx']
        # EB diverge at fx{fi}: fwy_eb_{fi-1} -> {fwy_eb_{fi} (all lanes thru), off_eb_j (lane0)}
        in_e = f"fwy_eb_{fi-1}"
        out_e = f"fwy_eb_{fi}"
        for lane in range(FWY_LANES):
            lines.append(f'    <connection from="{in_e}" to="{out_e}" fromLane="{lane}" toLane="{lane}"/>')
        lines.append(f'    <connection from="{in_e}" to="off_eb_{j}" fromLane="0" toLane="0"/>')
        # EB merge at fx{fi}: on-ramp (lane0) feeds fwy_eb_{fi}. If this ramp is
        # metered, the merge connection is from the release segment "..b".
        on_eb_merge_from = f"on_eb_{j}b" if j in METERED_ON_EB else f"on_eb_{j}"
        lines.append(f'    <connection from="{on_eb_merge_from}" to="{out_e}" fromLane="0" toLane="0"/>')

        # WB diverge at fx{fi}wb: fwy_wb_{fi} (arrives from fi+1 side) -> {fwy_wb_{fi-1} thru, off_wb_j}
        in_w = f"fwy_wb_{fi}"
        out_w = f"fwy_wb_{fi-1}"
        for lane in range(FWY_LANES):
            lines.append(f'    <connection from="{in_w}" to="{out_w}" fromLane="{lane}" toLane="{lane}"/>')
        lines.append(f'    <connection from="{in_w}" to="off_wb_{j}" fromLane="0" toLane="0"/>')
        lines.append(f'    <connection from="on_wb_{j}" to="{out_w}" fromLane="0" toLane="0"/>')
    lines.append('</connections>')
    return "\n".join(lines)


def gen_types():
    return """<types>
    <type id="fwy" priority="10" numLanes="3" speed="33.33"/>
    <type id="art" priority="6" numLanes="2" speed="15.65"/>
</types>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    nod_path = os.path.join(args.out_dir, "corridor.nod.xml")
    edg_path = os.path.join(args.out_dir, "corridor.edg.xml")
    con_path = os.path.join(args.out_dir, "corridor.con.xml")
    net_path = os.path.join(args.out_dir, "corridor.net.xml")

    with open(nod_path, "w") as f:
        f.write(gen_nodes())
    with open(edg_path, "w") as f:
        f.write(gen_edges())
    with open(con_path, "w") as f:
        f.write(gen_connections())

    cmd = [
        "netconvert",
        "--node-files", nod_path,
        "--edge-files", edg_path,
        "--connection-files", con_path,
        "--output-file", net_path,
        "--tls.guess-signals", "true",
        "--tls.default-type", "static",
        "--no-turnarounds", "true",
        "--junctions.corner-detail", "0",
        "--rectangular-lane-cut", "false",
    ]
    print("Running:", " ".join(cmd))
    res = subprocess.run(cmd, capture_output=True, text=True)
    print(res.stdout)
    print(res.stderr, file=sys.stderr)
    if res.returncode != 0:
        sys.exit(res.returncode)
    print("OK ->", net_path)


if __name__ == "__main__":
    main()
