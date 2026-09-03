"""Flatten duaIterate.py's final iteration into a plain one-route-per-vehicle
file that the online sweep can re-type and load (and that is byte-comparable
across penetration levels)."""
import glob
import gzip
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import WORK  # noqa: E402
import simlib  # noqa: E402
import assign_loop as al  # noqa: E402


def flatten(seed, last_iter=24):
    d = os.path.join(WORK, "duaiter_s%d" % seed, "%03d" % last_iter)
    gz = glob.glob(os.path.join(d, "*_%03d.rou.xml.gz" % last_iter))
    src = gz[0][:-3] if gz else glob.glob(os.path.join(d, "*_%03d.rou.xml" % last_iter))[0]
    if gz and not os.path.exists(src):
        with gzip.open(gz[0], "rb") as f, open(src, "wb") as o:
            shutil.copyfileobj(f, o)
    vr = simlib.parse_routes(src)
    trips = al.read_trips(os.path.join(WORK, "demand_s%d.trips.xml" % seed))
    out = os.path.join(WORK, "baseline_ue_s%d.rou.xml" % seed)
    al.write_routes(out, trips, {v: e for v, (t, e) in vr.items()})
    sh, cnt, tot = simlib.route_shares({v: ("", e) for v, (t, e) in vr.items()})
    print("seed %d -> %s  (%d veh, main share %s)" % (seed, out, len(vr),
                                                      {k: round(v, 3) for k, v in sh.items()}))
    return out


if __name__ == "__main__":
    for s in (0, 1, 2):
        flatten(s)
