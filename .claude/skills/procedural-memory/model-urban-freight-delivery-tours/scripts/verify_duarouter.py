#!/usr/bin/env python3
"""
Independent cross-check of the reachability verification, using duarouter WITHOUT
--ignore-errors (the method [[vehicle-class-lane-permissions]] recommends: a now-illegal
route fails loudly rather than being silently dropped).

For every network variant we ask duarouter to route one truck trip and one delivery-van
trip from each depot to each of the 120 delivery addresses, and count hard failures.
"""
import os, json, csv, re
from common import *   # noqa
import gen_freight as gf

addrs = json.load(open(os.path.join(DEMAND, "addresses.json")))
manifest = json.load(open(os.path.join(NET, "net_manifest.json")))
rows = []
for tag, meta in sorted(manifest.items()):
    r = dict(tag=tag, family=meta["family"], coverage=meta["coverage"])
    for vt, vc in (("rigid", "truck"), ("van", "delivery")):
        trips = os.path.join(DEMAND, "_chk_%s_%s.trips.xml" % (tag, vt))
        with open(trips, "w") as f:
            f.write("<routes>\n")
            for k, de in enumerate(gf.DEPOT_EDGES):
                for a in addrs:
                    f.write('  <trip id="t%d_%s" type="%s" depart="0" from="%s" to="%s"/>\n'
                            % (k, a["id"], vt, de, a["edge"]))
            f.write("</routes>\n")
        out = os.path.join(DEMAND, "_chk_%s_%s.rou.xml" % (tag, vt))
        res = sh([DUAROUTER, "-n", os.path.join(NET, "%s.net.xml" % tag), "-r", trips,
                  "-o", out, "--additional-files", os.path.join(DEMAND, "vtypes.add.xml"),
                  "--no-step-log", "true", "--ignore-errors", "false"])
        err = res.stderr or ""
        n_fail = len(re.findall(r"Error: .*(?:has no valid route|not known|No connection between)", err))
        n_fail += err.count("Warning: No connection between")
        n_written = 0
        if os.path.exists(out):
            n_written = open(out).read().count("<vehicle ")
        r["%s_offered" % vt] = 2 * len(addrs)
        r["%s_routed" % vt] = n_written
        r["%s_failed" % vt] = 2 * len(addrs) - n_written
        r["%s_returncode" % vt] = res.returncode
    rows.append(r)
    print("%-14s truck routed %3d/%d  van routed %3d/%d"
          % (tag, r["rigid_routed"], r["rigid_offered"], r["van_routed"], r["van_offered"]))
with open(os.path.join(TAB, "duarouter_reachability.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader()
    for x in rows: w.writerow(x)
print("wrote", os.path.join(TAB, "duarouter_reachability.csv"))
