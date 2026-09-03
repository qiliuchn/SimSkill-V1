"""Build the 3-lane freeway mainline (6 km instrumented) with an on-ramp + 4->3 lane drop."""
import os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import *

os.makedirs(NET_DIR, exist_ok=True)

nod = ['<nodes>']
nod.append(f'<node id="S" x="{-SRC_LEN}" y="0" type="priority"/>')
for k in range(N_SEG + 1):
    ntype = "priority"
    nod.append(f'<node id="J{k}" x="{SEG_LEN*k}" y="0" type="{ntype}"/>')
nod.append(f'<node id="E" x="{MAINLINE_LEN + SNK_LEN}" y="0" type="priority"/>')
# on-ramp origin
nod.append(f'<node id="R" x="{SEG_LEN*RAMP_MERGE_SEG - RAMP_LEN}" y="-40" type="priority"/>')
nod.append('</nodes>')

edg = ['<edges>']
edg.append(f'<edge id="src" from="S" to="J0" numLanes="{N_LANES}" speed="{FREE_SPEED}" priority="10"/>')
for k in range(N_SEG):
    nl = N_LANES + 1 if k == RAMP_MERGE_SEG else N_LANES
    edg.append(f'<edge id="m{k:02d}" from="J{k}" to="J{k+1}" numLanes="{nl}" speed="{FREE_SPEED}" priority="10"/>')
# downstream 3->2 lane drop at x = 6000 m: the RECURRENT bottleneck, sited DOWNSTREAM of the
# whole detection zone so that at over-capacity demand its queue propagates upstream through
# the instrumented stations (this is what creates the "incident masked by recurrent
# congestion" regime). Incidents are always drawn upstream of it, mid-segment.
edg.append(f'<edge id="snk" from="J{N_SEG}" to="E" numLanes="{N_LANES-1}" speed="{FREE_SPEED}" priority="10"/>')
edg.append(f'<edge id="ramp" from="R" to="J{RAMP_MERGE_SEG}" numLanes="1" speed="{RAMP_SPEED}" priority="3"/>')
edg.append('</edges>')

# Explicit connections around the merge and the lane drop.
# m03 has 4 lanes: lane 0 is the auxiliary/acceleration lane fed by the ramp.
mm = f"m{RAMP_MERGE_SEG:02d}"          # 4-lane edge, x = 750..1000
up = f"m{RAMP_MERGE_SEG-1:02d}"        # 3-lane edge upstream of the merge
dn = f"m{RAMP_MERGE_SEG+1:02d}"        # 3-lane edge downstream of the lane drop
con = ['<connections>']
# upstream mainline lanes 0,1,2 -> m03 lanes 1,2,3 (shift left, aux lane 0 is ramp-only)
for i in range(N_LANES):
    con.append(f'<connection from="{up}" to="{mm}" fromLane="{i}" toLane="{i+1}"/>')
con.append(f'<connection from="ramp" to="{mm}" fromLane="0" toLane="0"/>')
# lane drop: m03 lanes 1,2,3 -> m04 lanes 0,1,2 ; aux lane 0 must merge into lane 0
for i in range(N_LANES):
    con.append(f'<connection from="{mm}" to="{dn}" fromLane="{i+1}" toLane="{i}"/>')
con.append(f'<connection from="{mm}" to="{dn}" fromLane="0" toLane="0"/>')
# downstream 3->2 drop at J24: keep all three lanes usable to the junction and merge there,
# so the recurrent bottleneck is pinned at a known x rather than smeared over a taper.
last = f"m{N_SEG-1:02d}"
con.append(f'<connection from="{last}" to="snk" fromLane="0" toLane="0"/>')
con.append(f'<connection from="{last}" to="snk" fromLane="1" toLane="0"/>')
con.append(f'<connection from="{last}" to="snk" fromLane="2" toLane="1"/>')
con.append('</connections>')

for name, content in [("freeway.nod.xml", nod), ("freeway.edg.xml", edg), ("freeway.con.xml", con)]:
    with open(os.path.join(NET_DIR, name), "w") as f:
        f.write("\n".join(content) + "\n")

net = os.path.join(NET_DIR, "freeway.net.xml")
cmd = [NETCONVERT,
       "-n", os.path.join(NET_DIR, "freeway.nod.xml"),
       "-e", os.path.join(NET_DIR, "freeway.edg.xml"),
       "-x", os.path.join(NET_DIR, "freeway.con.xml"),
       "-o", net,
       "--no-turnarounds", "true",
       "--junctions.limit-turn-speed", "-1",
       "--default.lanewidth", "3.5"]
r = subprocess.run(cmd, capture_output=True, text=True)
print(r.stdout)
print(r.stderr, file=sys.stderr)
r.check_returncode()
print("network written to", net)
