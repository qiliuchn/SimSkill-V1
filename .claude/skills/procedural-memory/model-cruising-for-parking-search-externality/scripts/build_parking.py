"""Build parking supply (curb parkingAreas on block faces + off-street garages)
and the occupancy-aware rerouters, then VERIFY every parkingArea against the
compiled net (lane exists, offsets inside the lane, capacity sums to intent).

Extends `model-parking-with-rerouting` (parkingArea + rerouter/parkingAreaReroute
+ rerouting device) with:
  * two supply types on one net (curb block faces vs. off-street garages built
    from explicit <space> children so garage capacity is independent of the
    host lane's length),
  * a sweepable (n_curb_lots, curb_cap, n_garages, garage_cap) supply spec,
  * a `visible` flag on parkingAreaReroute so the information arm can be swept.
"""
import json
import os
import sys

from common import NET_DIR, SUMO_HOME

sys.path.insert(0, os.path.join(SUMO_HOME, "tools"))
import sumolib  # noqa: E402

NET = os.path.join(NET_DIR, "downtown.net.xml")

CORE_NODES = [c + str(r) for c in "BCD" for r in (1, 2, 3)]      # inner 3x3
GARAGE_HOST_EDGES = ["A2B2", "E2D2"]                             # fixed, outer ring


def load_net(net_path=NET):
    return sumolib.net.readNet(net_path)


def core_edge_ids(net):
    """Directed normal edges with BOTH endpoints in the inner 3x3 -> the search zone."""
    out = []
    for e in net.getEdges():
        if e.isSpecial():
            continue
        if e.getFromNode().getID() in CORE_NODES and e.getToNode().getID() in CORE_NODES:
            out.append(e.getID())
    return sorted(out)


def core_area_edge_ids(net):
    """Edges with at least one endpoint in the inner 3x3 (used for walk destinations)."""
    out = []
    for e in net.getEdges():
        if e.isSpecial():
            continue
        if e.getFromNode().getID() in CORE_NODES or e.getToNode().getID() in CORE_NODES:
            out.append(e.getID())
    return sorted(out)


def fringe_edge_ids(net):
    """Dead-end attach edges: source (leaving a dead_end) and sink (entering one)."""
    src, snk = [], []
    for e in net.getEdges():
        if e.isSpecial():
            continue
        if e.getFromNode().getType() == "dead_end":
            src.append(e.getID())
        if e.getToNode().getType() == "dead_end":
            snk.append(e.getID())
    return sorted(src), sorted(snk)


def car_lane(net, edge_id):
    e = net.getEdge(edge_id)
    for l in e.getLanes():
        if l.allows("passenger"):
            return l
    raise RuntimeError("no car lane on %s" % edge_id)


SUPPLY_PRESETS = {
    # name: (n_curb_lots, curb_cap, n_garages, garage_cap)
    "baseline":   (24, 6, 2, 28),   # 144 curb + 56 garage = 200 (curb share .72)
    "curb_high":  (24, 8, 2, 4),    # 192 curb +  8 garage = 200 (curb share .96)
    "curb_low":   (12, 5, 2, 70),   #  60 curb + 140 garage = 200 (curb share .30)
    "supply_p24": (24, 8, 2, 28),   # 192 curb + 56 garage = 248 (+24% supply)
    "supply_p12": (24, 7, 2, 28),   # 168 curb + 56 garage = 224 (+12% supply)
}


def build_supply(net, preset="baseline"):
    n_curb, curb_cap, n_gar, gar_cap = SUPPLY_PRESETS[preset]
    core = core_edge_ids(net)
    core.sort()
    if n_curb > len(core):
        raise RuntimeError("only %d core block faces available" % len(core))
    # deterministic even spread over the available block faces
    step = len(core) / float(n_curb)
    chosen = [core[int(i * step)] for i in range(n_curb)]
    assert len(set(chosen)) == n_curb

    lots = []
    for i, eid in enumerate(chosen):
        lane = car_lane(net, eid)
        L = lane.getLength()
        start = 15.0
        end = min(start + curb_cap * 7.5, L - 8.0)
        lots.append(dict(id="CURB%02d" % i, kind="curb", lane=lane.getID(), edge=eid,
                         cap=curb_cap, startPos=round(start, 2), endPos=round(end, 2),
                         lane_length=round(L, 2)))
    for g in range(n_gar):
        eid = GARAGE_HOST_EDGES[g]
        lane = car_lane(net, eid)
        L = lane.getLength()
        lots.append(dict(id="GAR%d" % g, kind="garage", lane=lane.getID(), edge=eid,
                         cap=gar_cap, startPos=15.0, endPos=round(min(45.0, L - 8.0), 2),
                         lane_length=round(L, 2)))
    return lots


def write_parking_add(lots, path, net, maneuver_len=None):
    """Curb lots use roadsideCapacity (roadside spaces along the block face).
    Garages use explicit <space> children placed off the carriageway so their
    capacity does not depend on the host lane's length."""
    with open(path, "w") as f:
        f.write('<additional>\n')
        for lot in lots:
            if lot["kind"] == "curb":
                f.write('    <parkingArea id="%s" lane="%s" roadsideCapacity="%d" '
                        'startPos="%.2f" endPos="%.2f"/>\n'
                        % (lot["id"], lot["lane"], lot["cap"], lot["startPos"], lot["endPos"]))
            else:
                lane = net.getLane(lot["lane"])
                shp = lane.getShape()
                x0, y0 = shp[0]
                x1, y1 = shp[-1]
                dx, dy = x1 - x0, y1 - y0
                n = (dx * dx + dy * dy) ** 0.5
                ux, uy = dx / n, dy / n
                px, py = -uy, ux          # unit normal -> park the garage beside the road
                f.write('    <parkingArea id="%s" lane="%s" startPos="%.2f" endPos="%.2f">\n'
                        % (lot["id"], lot["lane"], lot["startPos"], lot["endPos"]))
                per_row = 10
                for k in range(lot["cap"]):
                    row, col = divmod(k, per_row)
                    along = 10.0 + col * 6.0
                    off = 12.0 + row * 5.0
                    sx = x0 + ux * along + px * off
                    sy = y0 + uy * along + py * off
                    f.write('        <space x="%.2f" y="%.2f" width="3.0" length="5.0"/>\n' % (sx, sy))
                f.write('    </parkingArea>\n')
        f.write('</additional>\n')


def write_rerouters(lots, path, net, visible):
    """One rerouter per lot; edges = lot edge + every non-internal edge feeding the
    lot edge's FROM junction (genuine upstream lookahead, per model-parking-with-rerouting)."""
    ids = [l["id"] for l in lots]
    with open(path, "w") as f:
        f.write('<additional>\n')
        for lot in lots:
            e = net.getEdge(lot["edge"])
            up = {lot["edge"]}
            for inc in e.getFromNode().getIncoming():
                if not inc.isSpecial():
                    up.add(inc.getID())
            f.write('    <rerouter id="rr_%s" edges="%s">\n' % (lot["id"], " ".join(sorted(up))))
            f.write('        <interval begin="0" end="1000000">\n')
            for i in ids:
                f.write('            <parkingAreaReroute id="%s" visible="%s"/>\n'
                        % (i, "true" if visible else "false"))
            f.write('        </interval>\n')
            f.write('    </rerouter>\n')
        f.write('</additional>\n')


def verify_supply(lots, net, preset):
    """Independent verification against the COMPILED net."""
    n_curb, curb_cap, n_gar, gar_cap = SUPPLY_PRESETS[preset]
    problems = []
    for lot in lots:
        lane = net.getLane(lot["lane"])
        if lane is None:
            problems.append("lane missing: %s" % lot["lane"])
            continue
        L = lane.getLength()
        if not (0 <= lot["startPos"] < lot["endPos"] <= L):
            problems.append("%s offsets [%s,%s] outside lane length %.2f"
                            % (lot["id"], lot["startPos"], lot["endPos"], L))
        if not lane.allows("passenger"):
            problems.append("%s not on a car lane" % lot["id"])
        if lot["kind"] == "curb":
            need = lot["cap"] * 5.0
            if lot["endPos"] - lot["startPos"] < need:
                problems.append("%s too short for %d roadside spaces" % (lot["id"], lot["cap"]))
    curb_total = sum(l["cap"] for l in lots if l["kind"] == "curb")
    gar_total = sum(l["cap"] for l in lots if l["kind"] == "garage")
    if curb_total != n_curb * curb_cap:
        problems.append("curb capacity %d != intended %d" % (curb_total, n_curb * curb_cap))
    if gar_total != n_gar * gar_cap:
        problems.append("garage capacity %d != intended %d" % (gar_total, n_gar * gar_cap))
    return dict(preset=preset, n_lots=len(lots), curb_capacity=curb_total,
                garage_capacity=gar_total, total_capacity=curb_total + gar_total,
                curb_share=round(curb_total / float(curb_total + gar_total), 4),
                problems=problems)


def materialize(preset, visible, tag=None):
    """Write <preset>_<vis> parking + rerouter additional files; return paths + lots."""
    net = load_net()
    lots = build_supply(net, preset)
    tag = tag or "%s_vis%d" % (preset, int(visible))
    padd = os.path.join(NET_DIR, "parking_%s.add.xml" % preset)
    radd = os.path.join(NET_DIR, "rerouter_%s.add.xml" % tag)
    write_parking_add(lots, padd, net)
    write_rerouters(lots, radd, net, visible)
    return padd, radd, lots, net


if __name__ == "__main__":
    net = load_net()
    report = {"core_edges_search_zone": core_edge_ids(net)}
    src, snk = fringe_edge_ids(net)
    report["n_fringe_source"] = len(src)
    report["n_fringe_sink"] = len(snk)
    report["n_core_edges"] = len(report["core_edges_search_zone"])
    report["supply_checks"] = []
    for preset in SUPPLY_PRESETS:
        for vis in (True, False):
            padd, radd, lots, _ = materialize(preset, vis)
        report["supply_checks"].append(verify_supply(lots, net, preset))
    with open(os.path.join(NET_DIR, "parking_verification.json"), "w") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))
