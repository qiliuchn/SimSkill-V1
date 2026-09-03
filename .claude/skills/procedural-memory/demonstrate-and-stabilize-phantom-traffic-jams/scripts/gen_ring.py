#!/usr/bin/env python3
"""Generate a single-lane CLOSED RING network in SUMO by hand-authoring plain-XML
nodes placed on a circle + edges + connections, then compile with netconvert.

Usage: gen_ring.py <N_nodes> <circumference_m> <out_prefix>

The ring has N_nodes evenly placed on a circle; edge k goes node k -> node (k+1)%N.
Every edge is single-lane, identical speed, no lane drop / merge / junction conflict.
"""
import sys, math, subprocess, os

N = int(sys.argv[1])            # number of nodes = number of edges
L = float(sys.argv[2])          # ring circumference (polygon perimeter) in metres
prefix = sys.argv[3]            # output path prefix, e.g. net/ring
SPEED = 30.0                    # uniform edge speed limit (m/s) - deliberately high so
                                # vehicles are gap-constrained, never speed-limit-constrained

c = L / N                                   # chord (edge) length
R = c / (2.0 * math.sin(math.pi / N))       # circle radius so polygon perimeter = L

nod = ['<nodes>']
for k in range(N):
    th = 2.0 * math.pi * k / N
    x = R * math.cos(th)
    y = R * math.sin(th)
    # priority junction: with exactly one in + one out edge there is NO conflict,
    # so no vehicle ever has to yield/stop at a node.
    nod.append(f'  <node id="n{k}" x="{x:.4f}" y="{y:.4f}" type="priority"/>')
nod.append('</nodes>')

edg = ['<edges>']
for k in range(N):
    a = k
    b = (k + 1) % N
    edg.append(f'  <edge id="e{k}" from="n{a}" to="n{b}" numLanes="1" '
               f'speed="{SPEED}" priority="1"/>')
edg.append('</edges>')

# explicit connections e_k -> e_{k+1} so the loop is unambiguous
con = ['<connections>']
for k in range(N):
    con.append(f'  <connection from="e{k}" to="e{(k+1)%N}" fromLane="0" toLane="0"/>')
con.append('</connections>')

with open(prefix + '.nod.xml', 'w') as f: f.write('\n'.join(nod))
with open(prefix + '.edg.xml', 'w') as f: f.write('\n'.join(edg))
with open(prefix + '.con.xml', 'w') as f: f.write('\n'.join(con))

# Compile. Options chosen so the loop is genuinely uniform:
#  --no-internal-links true  -> no internal junction lanes, hence NO junction speed
#                               reduction anywhere on the ring (jam must be endogenous)
#  --no-turnarounds true     -> no U-turns
#  --offset.disable-normalization -> keep our coordinates
cmd = [
    'netconvert',
    '--node-files', prefix + '.nod.xml',
    '--edge-files', prefix + '.edg.xml',
    '--connection-files', prefix + '.con.xml',
    '--no-internal-links', 'true',
    '--no-turnarounds', 'true',
    '--offset.disable-normalization', 'true',
    '--output-file', prefix + '.net.xml',
]
print('netconvert:', ' '.join(cmd))
r = subprocess.run(cmd, capture_output=True, text=True)
print(r.stdout)
print(r.stderr)
if r.returncode != 0:
    sys.exit('netconvert FAILED')

print(f'OK: N={N} edges, chord={c:.3f} m, radius={R:.3f} m, perimeter={N*c:.3f} m')
