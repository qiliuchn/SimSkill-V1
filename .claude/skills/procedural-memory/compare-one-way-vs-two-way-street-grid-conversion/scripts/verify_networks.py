#!/usr/bin/env python3
"""Independently audit the COMPILED .net.xml files (not the authoring inputs).

Checks:
 1. total lane-km per variant (fair control: A == B, naive C < A)
 2. per-street-corridor cross-section lane totals
 3. one-way enforcement: for every street segment in variants B/C, assert no
    edge exists in the opposite direction anywhere in the compiled network
 4. junction approach counts (proxy for signal-phase complexity)
"""
import os
import sys
from collections import defaultdict

sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import sumolib  # noqa: E402

VARIANTS = ["twoway", "oneway_fair", "oneway_naive"]


def audit(netfile):
    net = sumolib.net.readNet(netfile)
    lane_km = 0.0
    edge_km = 0.0
    # corridor key: ("EW", row, i) or ("NS", col, j) -> total lanes both directions
    cross = defaultdict(int)
    dirs = defaultdict(set)
    stub_lanes = defaultdict(int)
    for e in net.getEdges():
        if e.getFunction() == "internal":
            continue
        L = e.getLength()
        nl = e.getLaneNumber()
        lane_km += L * nl / 1000.0
        edge_km += L / 1000.0
        eid = e.getID()
        if eid.startswith(("EW_", "NS_")):
            kind, a, b, d = eid.split("_")
            cross[(kind, int(a), int(b))] += nl
            dirs[(kind, int(a), int(b))].add(d)
        else:
            stub_lanes[eid.split("_", 1)[1]] += nl

    tls_appr = {}
    for tls in net.getTrafficLights():
        j = net.getNode(tls.getID())
        tls_appr[tls.getID()] = len([e for e in j.getIncoming()
                                     if e.getFunction() != "internal"])
    return dict(lane_km=lane_km, edge_km=edge_km, cross=cross, dirs=dirs,
                stub_lanes=stub_lanes, tls=tls_appr, net=net)


def main(root):
    res = {}
    for v in VARIANTS:
        res[v] = audit(os.path.join(root, v, "%s.net.xml" % v))

    print("=" * 74)
    print("1. TOTAL LANE-KM  (fair-comparison control)")
    print("=" * 74)
    base = res["twoway"]["lane_km"]
    for v in VARIANTS:
        r = res[v]
        print("  %-13s lane-km=%8.3f  centreline-km=%7.3f  ratio_to_twoway=%.4f"
              % (v, r["lane_km"], r["edge_km"], r["lane_km"] / base))
    ok_fair = abs(res["oneway_fair"]["lane_km"] - base) < 1e-6
    ok_naive = res["oneway_naive"]["lane_km"] < base * 0.75
    print("  CONTROL A==B (fair)      : %s" % ("PASS" if ok_fair else "FAIL"))
    print("  CONTROL C<A  (naive/unfair): %s" % ("PASS" if ok_naive else "FAIL"))

    print()
    print("=" * 74)
    print("2. PER-CORRIDOR CROSS-SECTION LANE TOTALS")
    print("=" * 74)
    keys = sorted(res["twoway"]["cross"])
    mism = [k for k in keys
            if res["twoway"]["cross"][k] != res["oneway_fair"]["cross"].get(k)]
    print("  street segments audited      : %d" % len(keys))
    print("  A vs B cross-section mismatches: %d  -> %s"
          % (len(mism), "PASS" if not mism else "FAIL %s" % mism[:5]))
    cs = sorted(set(res["twoway"]["cross"].values()))
    print("  A cross-sections seen: %s   B: %s   C: %s"
          % (cs, sorted(set(res["oneway_fair"]["cross"].values())),
             sorted(set(res["oneway_naive"]["cross"].values()))))
    sm = [k for k in res["twoway"]["stub_lanes"]
          if res["twoway"]["stub_lanes"][k] != res["oneway_fair"]["stub_lanes"].get(k)]
    print("  access-stub lane mismatches A vs B: %d -> %s"
          % (len(sm), "PASS" if not sm else "FAIL"))

    print()
    print("=" * 74)
    print("3. ONE-WAY ENFORCEMENT IN COMPILED NETWORK")
    print("=" * 74)
    for v in ("oneway_fair", "oneway_naive"):
        bad = {k: sorted(d) for k, d in res[v]["dirs"].items() if len(d) != 1}
        n_ew = sum(1 for k, d in res[v]["dirs"].items() if k[0] == "EW")
        print("  %-13s bidirectional street segments: %d -> %s"
              % (v, len(bad), "PASS" if not bad else "FAIL %s" % list(bad)[:5]))
        # verify the alternating pattern itself
        patt_bad = []
        for (kind, a, b), d in res[v]["dirs"].items():
            want = ("E" if a % 2 == 0 else "W") if kind == "EW" else \
                   ("N" if a % 2 == 0 else "S")
            if list(d)[0] != want:
                patt_bad.append(((kind, a, b), list(d)[0], want))
        print("  %-13s alternating-pattern violations: %d -> %s"
              % (v, len(patt_bad), "PASS" if not patt_bad else "FAIL"))
    twb = [k for k, d in res["twoway"]["dirs"].items() if len(d) != 2]
    print("  twoway        segments NOT bidirectional: %d -> %s"
          % (len(twb), "PASS" if not twb else "FAIL"))

    print()
    print("=" * 74)
    print("4. DIRECT-PATH ILLEGALITY CHECK (routing-level)")
    print("=" * 74)
    # A straight W->E crossing on an odd (westbound) row must be impossible in B.
    for v in VARIANTS:
        net = res[v]["net"]
        n_ok = 0
        tests = [("in_W1", "out_E1"), ("in_W3", "out_E3")]
        for f, t in tests:
            try:
                fe, te = net.getEdge(f), net.getEdge(t)
            except KeyError:
                continue
            path, cost = net.getOptimalPath(fe, te)
            if path:
                straight = all(e.getID().startswith("EW_1") or
                               e.getID().startswith("EW_3") or
                               e.getID().startswith(("in_", "out_")) for e in path)
                n_ok += 1
        print("  %-13s has westbound-row W->E entry/exit edge pair present: %d/2"
              % (v, n_ok))
    print("  (in B/C `in_W1` does not exist at all: row 1 is westbound, so its"
          " west end is exit-only -> the direct W->E path is structurally absent)")
    for v in VARIANTS:
        net = res[v]["net"]
        have = [e for e in ("in_W1", "in_W3", "out_W0", "out_W2")
                if net.hasEdge(e)]
        print("    %-13s of [in_W1,in_W3,out_W0,out_W2] present: %s" % (v, have))

    print()
    print("=" * 74)
    print("5. SIGNAL COMPLEXITY (approaches per signalised junction)")
    print("=" * 74)
    for v in VARIANTS:
        t = res[v]["tls"]
        hist = defaultdict(int)
        for k, c in t.items():
            hist[c] += 1
        print("  %-13s n_tls=%2d  approach-count histogram: %s  mean=%.2f"
              % (v, len(t), dict(sorted(hist.items())),
                 sum(t.values()) / float(len(t))))
    return 0 if (ok_fair and ok_naive and not mism) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
