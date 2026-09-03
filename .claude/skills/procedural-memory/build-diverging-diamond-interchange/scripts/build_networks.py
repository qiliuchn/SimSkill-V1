#!/usr/bin/env python3
"""Build the DDI and conventional-diamond plain-XML networks and compile with netconvert.

Design (freeway N-S under, arterial E-W over, z-grade-separated):
  - Two signalized ramp terminals W(-55,0) and E(55,0), 110 m apart, z=6.
  - Freeway N-S at x=0, z=0, passes UNDER the arterial (distinct z, no shared node).
  - SB ramps (SB off + SB on) at the West terminal; NB ramps at the East terminal.

The DDI and the conventional network share IDENTICAL nodes, ramp edges, freeway edges,
AND an IDENTICAL connection list. The ONLY difference is the SIDE (shape) of the two
internal arterial edges between the terminals:
  - Conventional: EB internal on the SOUTH, WB internal on the NORTH (normal driving).
  - DDI: EB internal on the NORTH, WB internal on the SOUTH (crossed over).

Because the internal edges swap sides, the SAME connection (e.g. WB-internal -> SB-on-ramp
left turn) physically crosses the opposing EB-through in the conventional net but NOT in the
DDI net -> netconvert computes different foe matrices. That isolates geometry as the sole
difference, exactly as the DDI vs conventional-diamond comparison requires.
"""
import os, subprocess

BASE = "/Users/liuqi/Desktop/simskill/episodic-memory/2026-07-30_09-43-42/attempts/attempt-1"
OUT = os.path.join(BASE, "outputs")
os.makedirs(OUT, exist_ok=True)

ART_SPEED = 13.89   # 50 km/h
FW_SPEED = 27.78    # 100 km/h
RAMP_SPEED = 13.89
ART_LANES = 2       # lane0 = through/right, lane1 = left (dedicated turn lane)
FW_LANES = 2
OFF = 6.0           # lateral offset (m) for the two arterial directions

# ---------------------------------------------------------------- nodes (shared)
NODES = f"""<?xml version="1.0" encoding="UTF-8"?>
<!-- Shared nodes for DDI and conventional diamond.
     Arterial z=6 (over); freeway z=0 (under). No node at the (0,0) crossing point:
     the freeway is grade-separated and only ever meets the arterial via ramp edges. -->
<nodes>
    <!-- Arterial ramp terminals (signalized), 110 m apart -->
    <node id="W" x="-55" y="0" z="6.0" type="traffic_light"/>
    <node id="E" x="55"  y="0" z="6.0" type="traffic_light"/>
    <!-- Arterial outer approach/exit nodes (EB south side, WB north side = normal driving) -->
    <node id="WA_s" x="-450" y="{-OFF}" z="6.0" type="priority"/>   <!-- EB source (west) -->
    <node id="WA_n" x="-450" y="{OFF}"  z="6.0" type="priority"/>   <!-- WB sink   (west) -->
    <node id="EA_s" x="450"  y="{-OFF}" z="6.0" type="priority"/>   <!-- EB sink   (east) -->
    <node id="EA_n" x="450"  y="{OFF}"  z="6.0" type="priority"/>   <!-- WB source (east) -->
    <!-- Freeway mainline (z=0), centerline x=0, passing UNDER the arterial -->
    <node id="FN" x="0" y="500"  z="0.0" type="priority"/>
    <node id="Fn" x="0" y="130"  z="0.0" type="priority"/>          <!-- north junction (SB off diverge / NB on merge) -->
    <node id="Fn2" x="0" y="250" z="0.0" type="priority"/>          <!-- NB on-ramp accel-lane drop -->
    <node id="Fs" x="0" y="-130" z="0.0" type="priority"/>          <!-- south junction (SB on merge / NB off diverge) -->
    <node id="Fs2" x="0" y="-250" z="0.0" type="priority"/>         <!-- SB on-ramp accel-lane drop -->
    <node id="FS" x="0" y="-500" z="0.0" type="priority"/>
</nodes>
"""

# ---------------------------------------------------------------- edges
# Ramp + freeway + outer-approach edges are identical for both designs.
# Only the two internal edges (I_EB, I_WB) differ in their shape (which side they run on).

def edges_xml(design):
    assert design in ("ddi", "conv")
    # internal-edge shapes: bulge to N (y=+OFF) or S (y=-OFF) in the middle
    if design == "conv":
        i_eb_shape = f"-55,0 -45,{-OFF} 45,{-OFF} 55,0"   # EB south (normal)
        i_wb_shape = f"55,0 45,{OFF} -45,{OFF} -55,0"      # WB north (normal)
    else:
        i_eb_shape = f"-55,0 -45,{OFF} 45,{OFF} 55,0"      # EB north (crossed)
        i_wb_shape = f"55,0 45,{-OFF} -45,{-OFF} -55,0"    # WB south (crossed)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!-- Edges for {design.upper()} design. Internal arterial edges I_EB/I_WB differ in side. -->
<edges>
    <!-- ===== Arterial outer approaches/exits (normal sides, identical both designs) ===== -->
    <edge id="Aw_EB" from="WA_s" to="W" numLanes="{ART_LANES}" speed="{ART_SPEED}" spreadType="center"
          shape="-450,{-OFF} -70,{-OFF} -55,0"/>
    <edge id="Aw_WB" from="W" to="WA_n" numLanes="{ART_LANES}" speed="{ART_SPEED}" spreadType="center"
          shape="-55,0 -70,{OFF} -450,{OFF}"/>
    <edge id="Ae_EB" from="E" to="EA_s" numLanes="{ART_LANES}" speed="{ART_SPEED}" spreadType="center"
          shape="55,0 70,{-OFF} 450,{-OFF}"/>
    <edge id="Ae_WB" from="EA_n" to="E" numLanes="{ART_LANES}" speed="{ART_SPEED}" spreadType="center"
          shape="450,{OFF} 70,{OFF} 55,0"/>

    <!-- ===== Internal arterial edges between terminals (SIDE differs by design) ===== -->
    <edge id="I_EB" from="W" to="E" numLanes="{ART_LANES}" speed="{ART_SPEED}" spreadType="center"
          shape="{i_eb_shape}"/>
    <edge id="I_WB" from="E" to="W" numLanes="{ART_LANES}" speed="{ART_SPEED}" spreadType="center"
          shape="{i_wb_shape}"/>

    <!-- ===== Ramps (single lane, grade-change z 6->0, identical both designs) ===== -->
    <edge id="SBon"  from="W" to="Fs" numLanes="1" speed="{RAMP_SPEED}" spreadType="center"
          shape="-55,0 -40,-40 -10,-100 0,-130"/>
    <edge id="SBoff" from="Fn" to="W" numLanes="1" speed="{RAMP_SPEED}" spreadType="center"
          shape="0,130 -10,100 -40,40 -55,0"/>
    <edge id="NBon"  from="E" to="Fn" numLanes="1" speed="{RAMP_SPEED}" spreadType="center"
          shape="55,0 40,40 10,100 0,130"/>
    <edge id="NBoff" from="Fs" to="E" numLanes="1" speed="{RAMP_SPEED}" spreadType="center"
          shape="0,-130 10,-100 40,-40 55,0"/>

    <!-- ===== Freeway mainline (z=0), SB = north->south, NB = south->north ===== -->
    <!-- On-ramps merge via a 3-lane ACCELERATION segment (fw_*_3) that drops back to 2
         lanes downstream (fw_*_4), so the on-ramp merge is high-capacity and is NOT the
         binding constraint - the terminal SIGNAL is. Identical for both designs. -->
    <edge id="fw_sb_1" from="FN" to="Fn"  numLanes="{FW_LANES}" speed="{FW_SPEED}"/>
    <edge id="fw_sb_2" from="Fn" to="Fs"  numLanes="{FW_LANES}" speed="{FW_SPEED}"/>
    <edge id="fw_sb_3" from="Fs" to="Fs2" numLanes="3" speed="{FW_SPEED}"/>          <!-- SB on-ramp accel lane (lane0) -->
    <edge id="fw_sb_4" from="Fs2" to="FS" numLanes="{FW_LANES}" speed="{FW_SPEED}"/>
    <edge id="fw_nb_1" from="FS" to="Fs"  numLanes="{FW_LANES}" speed="{FW_SPEED}"/>
    <edge id="fw_nb_2" from="Fs" to="Fn"  numLanes="{FW_LANES}" speed="{FW_SPEED}"/>
    <edge id="fw_nb_3" from="Fn" to="Fn2" numLanes="3" speed="{FW_SPEED}"/>          <!-- NB on-ramp accel lane (lane0) -->
    <edge id="fw_nb_4" from="Fn2" to="FN" numLanes="{FW_LANES}" speed="{FW_SPEED}"/>
</edges>
"""

# ---------------------------------------------------------------- connections (shared)
# Arterial lane1 = dedicated LEFT lane; lane0 = through + right.
# The heavy arterial-to-on-ramp LEFT turns: WB->SBon (at W), EB->NBon (at E).
CONS = f"""<?xml version="1.0" encoding="UTF-8"?>
<!-- Shared connection list (IDENTICAL for DDI and conventional). The DDI vs conventional
     difference comes purely from the internal-edge geometry (which side each runs on),
     which changes whether these same connections physically cross -> different foes. -->
<connections>
    <!-- ============ West terminal (W): SB ramps ============ -->
    <!-- EB through (2 lanes) -->
    <connection from="Aw_EB" to="I_EB" fromLane="0" toLane="0"/>
    <connection from="Aw_EB" to="I_EB" fromLane="1" toLane="1"/>
    <!-- EB -> SB on-ramp (RIGHT turn from EB, uses shared lane0) -->
    <connection from="Aw_EB" to="SBon" fromLane="0" toLane="0"/>
    <!-- WB through (2 lanes) -->
    <connection from="I_WB" to="Aw_WB" fromLane="0" toLane="0"/>
    <connection from="I_WB" to="Aw_WB" fromLane="1" toLane="1"/>
    <!-- WB -> SB on-ramp (LEFT turn, dedicated left lane1) : the HEAVY DDI-unopposed left -->
    <connection from="I_WB" to="SBon" fromLane="1" toLane="0"/>
    <!-- SB off-ramp -> arterial (ramp discharges to EB and WB) -->
    <connection from="SBoff" to="I_EB" fromLane="0" toLane="0"/>
    <connection from="SBoff" to="Aw_WB" fromLane="0" toLane="0"/>

    <!-- ============ East terminal (E): NB ramps ============ -->
    <!-- WB through (2 lanes) -->
    <connection from="Ae_WB" to="I_WB" fromLane="0" toLane="0"/>
    <connection from="Ae_WB" to="I_WB" fromLane="1" toLane="1"/>
    <!-- WB -> NB on-ramp (RIGHT turn from WB, shared lane0) -->
    <connection from="Ae_WB" to="NBon" fromLane="0" toLane="0"/>
    <!-- EB through (2 lanes) -->
    <connection from="I_EB" to="Ae_EB" fromLane="0" toLane="0"/>
    <connection from="I_EB" to="Ae_EB" fromLane="1" toLane="1"/>
    <!-- EB -> NB on-ramp (LEFT turn, dedicated left lane1) : the HEAVY DDI-unopposed left -->
    <connection from="I_EB" to="NBon" fromLane="1" toLane="0"/>
    <!-- NB off-ramp -> arterial (ramp discharges to WB and EB) -->
    <connection from="NBoff" to="I_WB" fromLane="0" toLane="0"/>
    <connection from="NBoff" to="Ae_EB" fromLane="0" toLane="0"/>

    <!-- ============ Freeway junctions (priority, NOT signals; no arterial-at-grade) ============ -->
    <!-- Fn: SB through + SB off diverge ; NB on-ramp merge (accel lane0) + NB through shift up -->
    <connection from="fw_sb_1" to="fw_sb_2" fromLane="0" toLane="0"/>
    <connection from="fw_sb_1" to="fw_sb_2" fromLane="1" toLane="1"/>
    <connection from="fw_sb_1" to="SBoff"  fromLane="0" toLane="0"/>
    <connection from="NBon"    to="fw_nb_3" fromLane="0" toLane="0"/>   <!-- NB on-ramp -> accel lane0 -->
    <connection from="fw_nb_2" to="fw_nb_3" fromLane="0" toLane="1"/>   <!-- NB through shifts up -->
    <connection from="fw_nb_2" to="fw_nb_3" fromLane="1" toLane="2"/>
    <!-- Fn2: NB accel-lane drop (3 -> 2), lane0 merges into lane0 -->
    <connection from="fw_nb_3" to="fw_nb_4" fromLane="0" toLane="0"/>
    <connection from="fw_nb_3" to="fw_nb_4" fromLane="1" toLane="0"/>
    <connection from="fw_nb_3" to="fw_nb_4" fromLane="2" toLane="1"/>
    <!-- Fs: SB on-ramp merge (accel lane0) + SB through shift up ; NB through + NB off diverge -->
    <connection from="SBon"    to="fw_sb_3" fromLane="0" toLane="0"/>   <!-- SB on-ramp -> accel lane0 -->
    <connection from="fw_sb_2" to="fw_sb_3" fromLane="0" toLane="1"/>   <!-- SB through shifts up -->
    <connection from="fw_sb_2" to="fw_sb_3" fromLane="1" toLane="2"/>
    <connection from="fw_nb_1" to="fw_nb_2" fromLane="0" toLane="0"/>
    <connection from="fw_nb_1" to="fw_nb_2" fromLane="1" toLane="1"/>
    <connection from="fw_nb_1" to="NBoff"   fromLane="0" toLane="0"/>
    <!-- Fs2: SB accel-lane drop (3 -> 2), lane0 merges into lane0 -->
    <connection from="fw_sb_3" to="fw_sb_4" fromLane="0" toLane="0"/>
    <connection from="fw_sb_3" to="fw_sb_4" fromLane="1" toLane="0"/>
    <connection from="fw_sb_3" to="fw_sb_4" fromLane="2" toLane="1"/>
</connections>
"""

def write(path, text):
    with open(path, "w") as f:
        f.write(text)

def build():
    write(os.path.join(OUT, "shared.nod.xml"), NODES)
    write(os.path.join(OUT, "shared.con.xml"), CONS)
    for design in ("ddi", "conv"):
        edg = os.path.join(OUT, f"{design}.edg.xml")
        write(edg, edges_xml(design))
        net = os.path.join(OUT, f"{design}.net.xml")
        cmd = ["netconvert",
               "-n", os.path.join(OUT, "shared.nod.xml"),
               "-e", edg,
               "-x", os.path.join(OUT, "shared.con.xml"),
               "-o", net,
               "--no-turnarounds", "true",
               "--no-internal-links", "false",
               "--offset.disable-normalization", "true",
               "--junctions.corner-detail", "5",
               "--tls.guess", "false"]
        print("running:", " ".join(cmd))
        r = subprocess.run(cmd, capture_output=True, text=True)
        print(r.stdout)
        print(r.stderr)
        if r.returncode != 0:
            raise SystemExit(f"netconvert failed for {design}")

if __name__ == "__main__":
    build()
    print("DONE")
