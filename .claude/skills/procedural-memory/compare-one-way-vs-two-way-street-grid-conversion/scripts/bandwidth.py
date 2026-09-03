#!/usr/bin/env python3
"""Classic green-wave THROUGH-BAND width for the test arterial, per direction.

For a direction, a vehicle that clears junction 0 at time t reaches junction i
at t + T_i (T_i = cumulative corridor distance / design speed).  It passes the
whole corridor without stopping iff (t + T_i) mod C lies inside a green window
of the arterial through movement at every junction i.  The bandwidth is the
measure of the set of feasible t within one cycle -- computed here by fine
discretisation of t over [0, C).

This is a purely geometric property of the signal plan (offsets + splits +
cycle) and the corridor geometry.  It contains no simulation noise at all, so
it is a clean, independently checkable test of the claim that a one-way pair
can serve both directions with full bands while a two-way street cannot.
"""
import argparse
import os
import sys
import xml.etree.ElementTree as ET

sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import sumolib  # noqa: E402

N = 5


def load_programs(netfile, addfiles):
    progs = {}
    for f in [netfile] + list(addfiles):
        if not f or not os.path.exists(f):
            continue
        for tl in ET.parse(f).getroot().iter("tlLogic"):
            ph = [(float(p.get("duration")), p.get("state"))
                  for p in tl.findall("phase")]
            off = float(tl.get("offset", 0))
            if not ph and tl.get("id") in progs:
                progs[tl.get("id")] = (off, progs[tl.get("id")][1])
            else:
                progs[tl.get("id")] = (off, ph)
    return progs


def through_links(net, row, direction):
    out = {}
    for i in range(N):
        jid = "J%d_%d" % (i, row)
        if direction == "E":
            inc = "EW_%d_%d_E" % (row, i - 1) if i > 0 else "in_W%d" % row
            outg = "EW_%d_%d_E" % (row, i) if i < N - 1 else "out_E%d" % row
        else:
            inc = "EW_%d_%d_W" % (row, i) if i < N - 1 else "in_E%d" % row
            outg = "EW_%d_%d_W" % (row, i - 1) if i > 0 else "out_W%d" % row
        if not (net.hasEdge(inc) and net.hasEdge(outg)):
            continue
        idxs = sorted(set(c.getTLLinkIndex() for c in
                          net.getEdge(inc).getOutgoing().get(net.getEdge(outg), [])
                          if c.getTLLinkIndex() >= 0))
        if idxs:
            out[jid] = idxs
    return out


def green_at(progs, jid, idxs, t):
    off, ph = progs[jid]
    cyc = sum(d for d, _ in ph)
    # SUMO semantics (verified against TraCI): the program position at
    # simulation time t is (t - offset) mod cycle, NOT (t + offset).
    x = (t - off) % cyc
    acc = 0.0
    for d, st in ph:
        if acc <= x < acc + d:
            return all(st[i] in "gG" for i in idxs if i < len(st))
        acc += d
    return False


def band(net, progs, row, direction, speed, step=0.1):
    tl = through_links(net, row, direction)
    order = ["J%d_%d" % (i, row) for i in range(N)]
    if direction == "W":
        order = order[::-1]
    order = [j for j in order if j in tl and j in progs]
    if len(order) < 2:
        # this carriageway does not exist in this variant (e.g. the westbound
        # side of a one-way street): NOT the same thing as "zero bandwidth"
        return None, 0.0, []
    xs = [net.getNode(j).getCoord()[0] for j in order]
    T = [abs(x - xs[0]) / speed for x in xs]
    cyc = sum(d for d, _ in progs[order[0]][1])
    n = int(cyc / step)
    good = 0
    for k in range(n):
        t = k * step
        if all(green_at(progs, order[i], tl[order[i]], t + T[i])
               for i in range(len(order))):
            good += 1
    return good * step, cyc, order


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--nets", required=True)
    p.add_argument("--offsets-dir", default=None)
    p.add_argument("--speed-factor", type=float, default=0.8)
    p.add_argument("--free-speed", type=float, default=13.89)
    p.add_argument("-o", "--out", required=True)
    a = p.parse_args()
    v = a.speed_factor * a.free_speed

    rows = []
    for variant in ("twoway", "oneway_fair", "oneway_naive"):
        net = sumolib.net.readNet(os.path.join(a.nets, variant,
                                               "%s.net.xml" % variant))
        for plan in ("uncoordinated", "coordinated"):
            adds = []
            if plan == "coordinated":
                if not a.offsets_dir:
                    continue
                adds = [os.path.join(a.offsets_dir, "%s.offsets.add.xml" % variant)]
            progs = load_programs(os.path.join(a.nets, variant,
                                               "%s.net.xml" % variant), adds)
            # PAIR view: EB on row 2, WB on row 3 (identical edges in every
            # variant) -- this is the corridor the arterial demand actually uses.
            bE, cyc, _ = band(net, progs, 2, "E", v)
            bW, _, _ = band(net, progs, 3, "W", v)
            # SAME-STREET view: both directions of row 2.  The WB carriageway of
            # row 2 exists only in the two-way network -- that is the whole
            # point: a two-way street must fit two bands into one offset budget.
            b2E, _, _ = band(net, progs, 2, "E", v)
            b2W, _, _ = band(net, progs, 2, "W", v)
            na = lambda x: "NA" if x is None else round(x, 2)
            rows.append(dict(variant=variant, plan=plan, cycle_s=cyc,
                             band_EB_s=na(bE), band_WB_s=na(bW),
                             band_total_s=na(None if bE is None or bW is None
                                             else bE + bW),
                             eff_EB=na(None if bE is None else bE / cyc),
                             eff_WB=na(None if bW is None else bW / cyc),
                             row2_EB_s=na(b2E), row2_WB_s=na(b2W),
                             row2_WB_exists=(b2W is not None)))
    import csv
    with open(a.out, "w") as f:
        w = csv.DictWriter(f, list(rows[0]))
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print("PAIR view: EB=row2, WB=row3 (the corridor arterial demand uses)")
    print("%-14s %-14s %6s %8s %8s %8s | %s" % ("variant", "plan", "cycle",
          "band_EB", "band_WB", "total", "row2 EB/WB (same street)"))
    for r in rows:
        print("%-14s %-14s %6.0f %8s %8s %8s | %6s /%6s"
              % (r["variant"], r["plan"], r["cycle_s"], r["band_EB_s"],
                 r["band_WB_s"], r["band_total_s"], r["row2_EB_s"],
                 r["row2_WB_s"]))


if __name__ == "__main__":
    main()
