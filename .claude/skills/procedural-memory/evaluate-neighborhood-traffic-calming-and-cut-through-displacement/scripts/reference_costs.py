#!/usr/bin/env python3
"""Per-OD-pair reference generalized cost C_A(p) from variant A's own DUE equilibrium.
Cost = mean (duration + departDelay) -- the TOTAL experienced cost, not just the
in-network duration (see `compute-dynamic-user-equilibrium`'s dual-cost rule)."""
import collections
import json
import os
import statistics as st
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NET, DEM, RUNS, ANA = (os.path.join(ROOT, x) for x in ("net", "demand", "runs", "analysis"))

edge2zone = {}
for taz in ET.parse(os.path.join(DEM, "zones.taz.xml")).getroot().findall("taz"):
    for tag in ("tazSource", "tazSink"):
        for e in taz.findall(tag):
            edge2zone.setdefault(e.get("id"), taz.get("id"))

PAIR = {}
for t in ET.parse(os.path.join(DEM, "all.trips.xml")).getroot().findall("trip"):
    PAIR[t.get("id")] = "%s>%s" % (edge2zone.get(t.get("from"), "?"),
                                   edge2zone.get(t.get("to"), "?"))

# use the SAME iteration that select_equilibrium.py chose as A's equilibrium of record
sel = json.load(open(os.path.join(ANA, "equilibrium_selection.json")))["A"]["selected_iteration"]
lastdir = "%03d" % sel
ti = os.path.join(RUNS, "due", "A", lastdir, "tripinfo_%s.xml" % lastdir)
by = collections.defaultdict(list)
for t in ET.parse(ti).getroot().findall("tripinfo"):
    by[PAIR[t.get("id")]].append(float(t.get("duration")) + float(t.get("departDelay")))
ref = {p: round(st.mean(v), 3) for p, v in by.items()}
json.dump(ref, open(os.path.join(ANA, "reference_costs_A.json"), "w"), indent=1)
print("reference costs from %s : %d OD pairs, mean %.1f s, range %.0f-%.0f s"
      % (ti, len(ref), st.mean(list(ref.values())), min(ref.values()), max(ref.values())))
