#!/usr/bin/env python3
"""Couple duarouter's P+R car legs to real parkingArea spaces.

WHY THIS EXISTS (verified, SUMO 1.27.1):
`duarouter --persontrip.transfer.car-walk parkingAreas` only uses parkingAreas
as *permitted transfer geometry*. It ends the car leg at the lot's position but
writes NO `<stop parkingArea=... parking="true"/>` into the generated
`<vehicle>`. At simulation time the car simply arrives and is removed, so the
lot's occupancy stays 0 and `roadsideCapacity` is never enforced. This script
injects the missing stop so the space is genuinely held.

It also snaps the person's ride arrivalPos onto the parkingArea endPos so the
rider disembarks exactly where the car parks.
"""
import argparse
import xml.etree.ElementTree as ET


def load_lots(path):
    lots = []
    for pa in ET.parse(path).getroot().iter("parkingArea"):
        lane = pa.get("lane")
        edge = lane.rsplit("_", 1)[0]
        lots.append({"id": pa.get("id"), "edge": edge,
                     "start": float(pa.get("startPos", 0)),
                     "end": float(pa.get("endPos", 1e9))})
    return lots


def find_lot(lots, edge, pos, tol=25.0):
    for l in lots:
        if l["edge"] == edge and (l["start"] - tol) <= pos <= (l["end"] + tol):
            return l
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--routes", required=True, help="duarouter output .rou.xml")
    ap.add_argument("--parking", required=True, help="parkingArea additional file")
    ap.add_argument("--out", required=True)
    ap.add_argument("--duration", type=int, default=100000,
                    help="how long the space is held (AM-only: longer than the run)")
    ap.add_argument("--pm-prefix", default=None,
                    help="if set, persons whose id starts with this are PM-return "
                         "trips and their inbound counterpart releases the space")
    ap.add_argument("--release-at", type=int, default=None,
                    help="absolute time the AM car leaves the lot (models the PM return)")
    a = ap.parse_args()

    lots = load_lots(a.parking)
    tree = ET.parse(a.routes)
    root = tree.getroot()
    veh = {v.get("id"): v for v in root.iter("vehicle")}

    n_pr, n_kissride, n_drive, n_unmatched = 0, 0, 0, 0
    per_lot = {}
    for person in root.iter("person"):
        legs = list(person)
        if len(legs) < 2:
            n_drive += 1
            continue
        first = legs[0]
        if first.tag != "ride":
            continue
        vid = first.get("lines")
        if vid is None or vid not in veh:
            continue
        v = veh[vid]
        route = v.find("route")
        last_edge = route.get("edges").split()[-1]
        if first.get("busStop") is not None:
            # ptStops transfer: car leg terminates at a PT stop, not a lot
            n_kissride += 1
            continue
        pos = first.get("arrivalPos")
        if pos is None:
            n_unmatched += 1
            continue
        lot = find_lot(lots, last_edge, float(pos))
        if lot is None:
            n_unmatched += 1
            continue
        # NB: a SUMO stop ends at max(until, arrival+duration) -- leaving the
        # long `duration` in place would make `until` a no-op, so drop it to 1s
        # whenever an absolute release time is requested.
        dur = 1 if a.release_at is not None else a.duration
        st = ET.SubElement(v, "stop")
        st.set("parkingArea", lot["id"])
        if a.release_at is not None:
            st.set("until", str(a.release_at))
        st.set("duration", str(dur))
        st.set("parking", "true")
        first.set("arrivalPos", "%.2f" % lot["end"])
        n_pr += 1
        per_lot[lot["id"]] = per_lot.get(lot["id"], 0) + 1

    tree.write(a.out, encoding="UTF-8", xml_declaration=True)
    print("P+R car legs coupled to a lot : %d  %s" % (n_pr, per_lot))
    print("car leg ended at a PT stop    : %d (kiss&ride, no lot)" % n_kissride)
    print("drive-all-the-way persons     : %d" % n_drive)
    print("unmatched multi-leg car trips : %d" % n_unmatched)


if __name__ == "__main__":
    main()
