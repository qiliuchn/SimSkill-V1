#!/usr/bin/env python3
"""Generate a single-lane CLOSED RING network in SUMO.

Adapted from the `demonstrate-and-stabilize-phantom-traffic-jams` skill's
scripts/gen_ring.py (SimSkill procedural memory).  Differences here:
  * circumference is a CLI arg and defaults to 1000 m (so 1 vehicle == 1 veh/km),
  * speed limit is a CLI arg,
  * a machine-readable verification report is emitted so the "no bottleneck"
    property (zero TLS, zero internal links, uniform speed, single lane,
    perimeter == requested L) is provable from the compiled net.

Usage: gen_ring.py <N_nodes> <circumference_m> <speed_ms> <out_prefix>
"""
import sys, math, subprocess, os, json
sys.path.insert(0, os.path.join(os.environ['SUMO_HOME'], 'tools'))
import sumolib

N = int(sys.argv[1])
L = float(sys.argv[2])
SPEED = float(sys.argv[3])
prefix = sys.argv[4]
os.makedirs(os.path.dirname(prefix) or '.', exist_ok=True)

c = L / N
R = c / (2.0 * math.sin(math.pi / N))

nod = ['<nodes>']
for k in range(N):
    th = 2.0 * math.pi * k / N
    nod.append(f'  <node id="n{k}" x="{R*math.cos(th):.6f}" y="{R*math.sin(th):.6f}" type="priority"/>')
nod.append('</nodes>')

edg = ['<edges>']
for k in range(N):
    edg.append(f'  <edge id="e{k}" from="n{k}" to="n{(k+1)%N}" numLanes="1" '
               f'speed="{SPEED}" priority="1"/>')
edg.append('</edges>')

con = ['<connections>']
for k in range(N):
    con.append(f'  <connection from="e{k}" to="e{(k+1)%N}" fromLane="0" toLane="0"/>')
con.append('</connections>')

for ext, body in (('.nod.xml', nod), ('.edg.xml', edg), ('.con.xml', con)):
    with open(prefix + ext, 'w') as f:
        f.write('\n'.join(body))

cmd = ['netconvert',
       '--node-files', prefix + '.nod.xml',
       '--edge-files', prefix + '.edg.xml',
       '--connection-files', prefix + '.con.xml',
       '--no-internal-links', 'true',
       '--no-turnarounds', 'true',
       '--offset.disable-normalization', 'true',
       '--output-file', prefix + '.net.xml']
r = subprocess.run(cmd, capture_output=True, text=True)
if r.returncode != 0:
    print(r.stdout); print(r.stderr); sys.exit('netconvert FAILED')

# ---- verification straight off the COMPILED net ----------------------------
net = sumolib.net.readNet(prefix + '.net.xml')
edges = [e for e in net.getEdges()]
lane_lengths = {}
report = {
    'requested_circumference_m': L,
    'n_edges': len(edges),
    'n_internal_edges': len([e for e in net.getEdges(withInternal=True) if e.isSpecial()]),
    'n_traffic_lights': len(net.getTrafficLights()),
    'lane_counts': sorted(set(e.getLaneNumber() for e in edges)),
    'speed_limits_ms': sorted(set(round(e.getSpeed(), 6) for e in edges)),
    'perimeter_lane_length_m': round(sum(e.getLane(0).getLength() for e in edges), 6),
}
# circularity: from every edge, exactly one outgoing, and following them returns home
succ = {}
ok_circular = True
for e in edges:
    outs = list(e.getOutgoing().keys())
    succ[e.getID()] = [o.getID() for o in outs]
    if len(outs) != 1:
        ok_circular = False
seen, cur = [], 'e0'
for _ in range(len(edges) + 2):
    seen.append(cur)
    cur = succ[cur][0]
    if cur == 'e0':
        break
report['circular_walk_len'] = len(seen)
report['circular'] = ok_circular and len(seen) == len(edges) and cur == 'e0'
report['bottleneck_free'] = (report['circular'] and report['n_traffic_lights'] == 0
                             and report['n_internal_edges'] == 0
                             and report['lane_counts'] == [1]
                             and len(report['speed_limits_ms']) == 1)
with open(prefix + '.verify.json', 'w') as f:
    json.dump(report, f, indent=2)
print(json.dumps(report, indent=2))
