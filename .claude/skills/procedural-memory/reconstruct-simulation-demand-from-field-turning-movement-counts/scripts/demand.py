#!/usr/bin/env python3
"""
GROUND-TRUTH demand definition for the corridor.

Demand is specified as PATH flows (fringe -> fringe), not as free-floating
per-movement flows, so that (a) every vehicle is physically continuous through
the corridor and (b) the TRUE turning-movement volume at every intersection is
an exact, closed-form sum over the paths that traverse it.  That exact table is
what the round-trip test's "demand recovery" level compares against.

Temporal shape: 16 x 15-minute bins over 4 h.
  bins  0-3   off-peak warm-up
  bins  4-11  shoulder / peak / shoulder, with the TRUE peak hour at bins 7-10
              (t = 6300-9900 s -- deliberately NOT clock-aligned)
  bins 12-15  recovery
The four peak-hour bin shares are chosen so PHF = V/(4*V15max) = 0.87 exactly.
"""
import json
import os

from common import SCEN, JUNCTIONS, BIN, N_BINS

# ---------------------------------------------------------------- bin shares
PHF_TRUE = 0.87
_TOP = 1.0 / (4.0 * PHF_TRUE)                  # 0.28735632...
PEAK_SHARES = [1.0 - _TOP - 0.24 - 0.26, 0.2400000, _TOP, 0.2600000]  # bins 7,8,9,10
assert abs(sum(PEAK_SHARES) - 1.0) < 1e-12
assert abs(1.0 / (4.0 * max(PEAK_SHARES)) - PHF_TRUE) < 1e-12

SHARES = ([0.155] * 4 +
          [0.18, 0.19, 0.20] + PEAK_SHARES + [0.19] +
          [0.150] * 4)
assert len(SHARES) == N_BINS
TRUE_PEAK_BINS = (7, 8, 9, 10)

# ---------------------------------------------------------------- path table
# name: (origin edge, destination edge, [(junction, approach, movement), ...],
#        peak-hour veh/h, group)
ART, SIDE, DWY = "art", "side", "dwy"

PATHS = {}


def _p(name, o, d, mv, v, g):
    PATHS[name] = dict(o=o, d=d, mv=mv, v=float(v), g=g)


# ---- eastbound entries at the west fringe
_p("EB_THRU", "eb_WF_J1_feed", "eb_J3_EF",
   [("J1", "EB", "T"), ("J2", "EB", "T"), ("J3", "EB", "T")], 699, ART)
_p("EB_L1", "eb_WF_J1_feed", "sN1_out", [("J1", "EB", "L")], 140, ART)
_p("EB_R1", "eb_WF_J1_feed", "sS1_out", [("J1", "EB", "R")], 90, ART)
_p("EB_DW", "eb_WF_J1_feed", "dw_out", [("J1", "EB", "T")], 60, ART)
_p("EB_L2", "eb_WF_J1_feed", "sN2_out", [("J1", "EB", "T"), ("J2", "EB", "L")], 130, ART)
_p("EB_R2", "eb_WF_J1_feed", "sS2_out", [("J1", "EB", "T"), ("J2", "EB", "R")], 85, ART)
_p("EB_L3", "eb_WF_J1_feed", "sN3_out",
   [("J1", "EB", "T"), ("J2", "EB", "T"), ("J3", "EB", "L")], 120, ART)
_p("EB_R3", "eb_WF_J1_feed", "sS3_out",
   [("J1", "EB", "T"), ("J2", "EB", "T"), ("J3", "EB", "R")], 80, ART)

# ---- westbound entries at the east fringe
_p("WB_THRU", "wb_EF_J3_feed", "wb_J1_WF",
   [("J3", "WB", "T"), ("J2", "WB", "T"), ("J1", "WB", "T")], 450, ART)
_p("WB_L3", "wb_EF_J3_feed", "sS3_out", [("J3", "WB", "L")], 95, ART)
_p("WB_R3", "wb_EF_J3_feed", "sN3_out", [("J3", "WB", "R")], 60, ART)
_p("WB_L2", "wb_EF_J3_feed", "sS2_out", [("J3", "WB", "T"), ("J2", "WB", "L")], 90, ART)
_p("WB_R2", "wb_EF_J3_feed", "sN2_out", [("J3", "WB", "T"), ("J2", "WB", "R")], 55, ART)
_p("WB_L1", "wb_EF_J3_feed", "sS1_out",
   [("J3", "WB", "T"), ("J2", "WB", "T"), ("J1", "WB", "L")], 85, ART)
_p("WB_R1", "wb_EF_J3_feed", "sN1_out",
   [("J3", "WB", "T"), ("J2", "WB", "T"), ("J1", "WB", "R")], 50, ART)

# ---- side streets:  SB = from the north leg, NB = from the south leg
SIDE_VOL = {
    ("J1", "SB"): dict(L=50, T=110, R=40),
    ("J1", "NB"): dict(L=45, T=105, R=40),
    ("J2", "SB"): dict(L=40, T=95, R=35),
    ("J2", "NB"): dict(L=45, T=100, R=35),
    ("J3", "SB"): dict(L=38, T=90, R=32),
    ("J3", "NB"): dict(L=35, T=85, R=30),
}
_EB_DOWN = {"J1": ["J2", "J3"], "J2": ["J3"], "J3": []}
_WB_DOWN = {"J3": ["J2", "J1"], "J2": ["J1"], "J1": []}

for (j, app), vols in SIDE_VOL.items():
    i = j[-1]
    o = ("sN%s_in" % i) if app == "SB" else ("sS%s_in" % i)
    # left turn
    if app == "SB":        # southbound left goes EAST
        mv = [(j, app, "L")] + [(k, "EB", "T") for k in _EB_DOWN[j]]
        _p("%s_%s_L" % (j, app), o, "eb_J3_EF", mv, vols["L"], SIDE)
        mv = [(j, app, "R")] + [(k, "WB", "T") for k in _WB_DOWN[j]]
        _p("%s_%s_R" % (j, app), o, "wb_J1_WF", mv, vols["R"], SIDE)
        _p("%s_%s_T" % (j, app), o, "sS%s_out" % i, [(j, app, "T")], vols["T"], SIDE)
    else:                  # northbound left goes WEST
        mv = [(j, app, "L")] + [(k, "WB", "T") for k in _WB_DOWN[j]]
        _p("%s_%s_L" % (j, app), o, "wb_J1_WF", mv, vols["L"], SIDE)
        mv = [(j, app, "R")] + [(k, "EB", "T") for k in _EB_DOWN[j]]
        _p("%s_%s_R" % (j, app), o, "eb_J3_EF", mv, vols["R"], SIDE)
        _p("%s_%s_T" % (j, app), o, "sN%s_out" % i, [(j, app, "T")], vols["T"], SIDE)

# ---- mid-block driveway right-out (a real mid-block SOURCE between J1 and J2)
_p("DW_OUT", "dw_in", "eb_J3_EF", [("J2", "EB", "T"), ("J3", "EB", "T")], 45, DWY)

# ---------------------------------------------------------- heavy vehicles
HV_SHARE = {ART: 0.05, SIDE: 0.03, DWY: 0.08}

# arms:  scale applied to ARTERIAL fringe demand only (side streets and the
# driveway are held identical between arms, so they act as a control group)
ARMS = {"under": 1.0, "over": 1.533}


def scale_for(arm, group):
    return ARMS[arm] if group == ART else 1.0


def true_movement_volumes(arm):
    """{(J, approach, movement): [veh in bin 0..15]} -- exact nominal demand."""
    out = {}
    for name, p in PATHS.items():
        s = scale_for(arm, p["g"])
        for (j, app, m) in p["mv"]:
            arr = out.setdefault((j, app, m), [0.0] * N_BINS)
            for b in range(N_BINS):
                arr[b] += p["v"] * SHARES[b] * s
    return out


def true_path_volumes(arm):
    return {n: [p["v"] * SHARES[b] * scale_for(arm, p["g"]) for b in range(N_BINS)]
            for n, p in PATHS.items()}


# ------------------------------------------------------------- route writing
VTYPES = """  <vType id="car" vClass="passenger" length="5.0" minGap="2.5" accel="2.6"
         decel="4.5" sigma="0.5" tau="1.0" speedFactor="normc(1.00,0.10,0.85,1.15)"
         lcKeepRight="0"/>
  <vType id="hgv" vClass="truck" length="12.0" minGap="3.0" accel="1.3"
         decel="3.5" sigma="0.5" tau="1.2" maxSpeed="25.0"
         speedFactor="normc(0.95,0.08,0.80,1.10)" lcKeepRight="0"/>
"""


def find_routes(net_path):
    """origin edge -> destination edge shortest path (unique in this corridor)."""
    import sumolib
    net = sumolib.net.readNet(net_path)
    routes = {}
    for name, p in PATHS.items():
        o = net.getEdge(p["o"])
        d = net.getEdge(p["d"])
        path, cost = net.getShortestPath(o, d)
        if path is None:
            raise RuntimeError("no path for %s: %s -> %s" % (name, p["o"], p["d"]))
        routes[name] = [e.getID() for e in path]
    return routes


def write_route_file(path_out, volumes, routes, tag):
    """volumes: {path_name: [veh in each of N_BINS bins]}  -> Poisson <flow>s."""
    lines = ['<routes>', VTYPES]
    for name in sorted(routes):
        lines.append('  <route id="r_%s" edges="%s"/>' % (name, " ".join(routes[name])))
    rows = []
    for name in sorted(volumes):
        hv = HV_SHARE[PATHS[name]["g"]]
        for b in range(N_BINS):
            v = volumes[name][b]
            if v <= 0:
                continue
            rate = v * 4.0 / 3600.0          # veh/s over the 900 s bin
            for vt, frac in (("car", 1.0 - hv), ("hgv", hv)):
                r = rate * frac
                if r <= 0:
                    continue
                rows.append((b * BIN, '  <flow id="%s.%s.%d" type="%s" route="r_%s" '
                                      'begin="%d" end="%d" period="exp(%.6f)" '
                                      'departLane="free" departSpeed="max"/>'
                                      % (name, vt, b, vt, name, b * BIN, (b + 1) * BIN, r)))
    rows.sort(key=lambda x: x[0])             # SUMO drops out-of-order flow begins
    lines.extend(r[1] for r in rows)
    lines.append('</routes>')
    with open(path_out, "w") as f:
        f.write("\n".join(lines) + "\n")
    return len(rows)


if __name__ == "__main__":
    from common import NET
    routes = find_routes(NET)
    manifest = dict(phf_true=PHF_TRUE, shares=SHARES, true_peak_bins=list(TRUE_PEAK_BINS),
                    arms=ARMS, hv_share=HV_SHARE,
                    paths={k: dict(v) for k, v in PATHS.items()},
                    routes=routes)
    with open(os.path.join(SCEN, "demand_manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    for arm in ARMS:
        vol = true_path_volumes(arm)
        n = write_route_file(os.path.join(SCEN, "gt_%s.rou.xml" % arm), vol, routes, arm)
        tot = sum(sum(v) for v in vol.values())
        print("arm=%-5s flows=%4d  total nominal vehicles=%.0f" % (arm, n, tot))
        tm = true_movement_volumes(arm)
        for j in JUNCTIONS:
            for app in ("EB", "WB"):
                pk = {m: sum(tm[(j, app, m)][b] for b in TRUE_PEAK_BINS) for m in "LTR"}
                print("   %s %s peak-hour L/T/R = %6.1f %7.1f %6.1f   T+R=%7.1f"
                      % (j, app, pk["L"], pk["T"], pk["R"], pk["T"] + pk["R"]))
    print("routes:")
    for k in sorted(routes):
        print("   %-10s %s" % (k, " ".join(routes[k])))
