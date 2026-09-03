# Illustrative placeholder -- attempt 1's approach (superseded by attempt 2).
# Generates a uniform grid, then attempts to hand-edit two corridors' lane
# counts directly in the output XML. Critic-agent flagged this as producing
# an inconsistent/invalid network -- see ../critic-agent-feedback.json.

import xml.etree.ElementTree as ET

NET_FILE = "network.net.xml"
CENTRAL_EDGES = ["A1A2", "A2A1", "B0B1", "B1B0"]  # illustrative edge ids

tree = ET.parse(NET_FILE)
root = tree.getroot()
for edge in root.findall("edge"):
    if edge.get("id") in CENTRAL_EDGES:
        for lane in edge.findall("lane"):
            lane.set("width", "3.5")  # does not add lanes or fix connections -- the actual bug
tree.write(NET_FILE)
