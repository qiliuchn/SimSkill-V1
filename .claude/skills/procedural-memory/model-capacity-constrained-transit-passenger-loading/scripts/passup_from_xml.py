"""Reconstruct transit pass-ups (denied boardings) from raw SUMO output.

SUMO 1.27.1 has NO pass-up observable anywhere -- not in --stop-output, not in
tripinfo <ride>, not in TraCI, and it emits no warning.  A denied boarding must be
reconstructed by joining the two files:

    person p waiting at stop s over [wait_start, board) was passed up by every bus
    whose --stop-output record at s satisfies  wait_start < ended < board

wait_start = ride.depart - ride.waitingTime, which SUMO measures from the END of the
person's <access> walk -- that is what correctly excludes buses the person missed while
still walking to the stop.  ride.depart equals the boarding bus's stopinfo @ended
exactly, so the strict inequality excludes the bus actually boarded.

Do NOT instrument this with traci.busstop.getPersonIDs(): that list also contains
persons who just ALIGHTED there and persons still on the inbound <access> walk, and its
order is not the service order.  Measured, it over-counts pass-ups by ~11%, concentrated
at alighting-heavy stops.

Validate any implementation against a non-binding control (personCapacity raised, all
else identical): it must return exactly 0 pass-ups.

Usage:
    python3 passup_from_xml.py stopinfo.xml[.gz] tripinfo.xml[.gz] [--stop-prefix bs]
"""
import gzip
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict


def _open(path):
    return gzip.open(path, "rt") if str(path).endswith(".gz") else open(path)


def read_stopinfo(path):
    """One record per bus service event: which bus, which stop, when, and loads."""
    recs = []
    with _open(path) as f:
        for _, el in ET.iterparse(f):
            if el.tag != "stopinfo":
                continue
            initial = int(el.get("initialPersons", 0))
            loaded = int(el.get("loadedPersons", 0))
            unloaded = int(el.get("unloadedPersons", 0))
            started, ended = float(el.get("started")), float(el.get("ended"))
            recs.append({"bus": el.get("id"), "stop": el.get("busStop"),
                         "started": started, "ended": ended,
                         "dwell": ended - started,
                         "initial": initial, "loaded": loaded, "unloaded": unloaded,
                         "load_dep": initial - unloaded + loaded})
            el.clear()
    return recs


def read_rides(path):
    """One record per completed <ride>. Guards the depart="-1" quirk (see SKILL.md)."""
    rides = []
    with _open(path) as f:
        for _, el in ET.iterparse(f):
            if el.tag != "personinfo":
                continue
            for r in el.findall("ride"):
                depart = float(r.get("depart"))
                if depart < 0:          # SUMO can emit depart="-1" on a completed ride
                    el.clear()
                    continue
                wait = float(r.get("waitingTime"))
                rides.append({"person": el.get("id"), "board": depart,
                              "wait": wait, "wait_start": depart - wait,
                              "arrival": float(r.get("arrival")),
                              "bus": r.get("vehicle")})
            el.clear()
    return rides


def reconstruct(stopinfo, rides, origin_of=None):
    """Return (per_person_passups, denied_by_event, crowd_by_event).

    origin_of: optional {person_id -> busStop id}. Without it the boarding stop is
    inferred from the record whose `ended` equals the ride's `depart`, which is exact.
    """
    by_stop = defaultdict(list)
    for rec in stopinfo:
        by_stop[rec["stop"]].append(rec)
    for k in by_stop:
        by_stop[k].sort(key=lambda r: r["started"])

    # infer each rider's boarding stop from the exact ended == depart match
    board_lookup = {}
    for rec in stopinfo:
        board_lookup.setdefault((rec["bus"], round(rec["ended"], 2)), rec["stop"])

    passups, denied, crowd = {}, defaultdict(int), defaultdict(int)
    waits = defaultdict(list)
    for r in rides:
        stop = (origin_of or {}).get(r["person"]) or \
            board_lookup.get((r["bus"], round(r["board"], 2)))
        if stop is None:
            continue
        n = 0
        for rec in by_stop[stop]:
            if r["wait_start"] < rec["ended"] < r["board"]:
                n += 1
                denied[(rec["bus"], rec["stop"])] += 1
        passups[r["person"]] = n
        waits[stop].append((r["wait_start"], r["board"]))

    # crowd waiting when each bus ARRIVES -- the x-axis of the dwell-vs-crowd fit
    for rec in stopinfo:
        crowd[(rec["bus"], rec["stop"])] = sum(
            1 for w0, b in waits[rec["stop"]] if w0 <= rec["started"] < b)
    return passups, dict(denied), dict(crowd)


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 1
    stopinfo = read_stopinfo(argv[1])
    rides = read_rides(argv[2])
    passups, denied, _ = reconstruct(stopinfo, rides)
    n = len(passups)
    total = sum(passups.values())
    hist = defaultdict(int)
    for v in passups.values():
        hist[v] += 1
    print(f"riders={n}  total pass-ups={total}  per rider={total / n if n else 0:.3f}")
    print(f"passed up at least once: {sum(1 for v in passups.values() if v) / n:.1%}"
          if n else "")
    by_stop = defaultdict(int)
    for (_, s), c in denied.items():
        by_stop[s] += c
    print("by stop:", dict(sorted(by_stop.items())))
    print("boarded the k-th bus:",
          {k + 1: f"{hist[k] / n:.1%}" for k in sorted(hist)} if n else {})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
