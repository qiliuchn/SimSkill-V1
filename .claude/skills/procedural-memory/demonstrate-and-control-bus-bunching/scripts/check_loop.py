#!/usr/bin/env python3
"""Verify the compiled net is a genuine single closed loop by following
edge->connection->edge and confirming it forms one cycle covering all edges."""
import sys, xml.etree.ElementTree as ET

net = sys.argv[1]
t = ET.parse(net); root = t.getroot()

# normal edges (function != internal)
edges = {}
for e in root.findall("edge"):
    if e.get("function") == "internal":
        continue
    edges[e.get("id")] = (e.get("from"), e.get("to"))

# connections between normal edges
succ = {}
for c in root.findall("connection"):
    fr, to = c.get("from"), c.get("to")
    if fr in edges and to in edges:
        succ.setdefault(fr, set()).add(to)

print(f"normal edges: {len(edges)}")
print(f"edges with a successor: {len(succ)}")
# each edge should have exactly one successor for a genuine single-lane ring
multi = {k: v for k, v in succ.items() if len(v) != 1}
print(f"edges with !=1 successor: {len(multi)} -> {multi}")

# follow the chain from an arbitrary edge
start = next(iter(edges))
visited = [start]
cur = start
ok = True
for _ in range(len(edges) + 2):
    nxts = succ.get(cur)
    if not nxts:
        ok = False; break
    cur = next(iter(nxts))
    if cur == start:
        break
    visited.append(cur)

print(f"chain length from {start}: {len(visited)}")
cycle = (cur == start and len(visited) == len(edges) and len(multi) == 0)
print(f"SINGLE CLOSED CYCLE covering all edges: {cycle}")
print(f"cycle order: {visited}")
# no turnaround possible: no edge whose 'to' node has an outgoing edge back to its 'from'
print("PASS" if cycle else "FAIL")
