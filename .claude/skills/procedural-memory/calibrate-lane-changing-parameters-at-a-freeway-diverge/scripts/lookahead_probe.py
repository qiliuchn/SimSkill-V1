#!/usr/bin/env python3
"""STEP 1b -- "advance guide-sign geometry implied by SUMO's strategic lookahead".

Question: at what distance upstream of the gore does LC2013 actually begin the
mandatory (strategic) exit manoeuvre?  If the answer is "immediately at
insertion, whatever the approach length", then SUMO's strategic pull is
route-global and there is NO finite advance-signing distance to design to --
which is a property of the model, not of the network, and has to be verified by
lengthening the approach rather than asserted.

Builds a 2nd network identical to the calibration facility except that edge A
is 4400 m instead of 600 m (total approach to the gore 7400 m instead of
3600 m) and re-measures the strategic-LC-vs-distance-to-gore profile.
"""
import os, sys, json, subprocess, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lc_common as L
import build_net as BN

LONGNET = os.path.join(L.NETDIR, "diverge_long.net.xml")
A_LONG = 4400.0
SHIFT = A_LONG - 600.0     # 3800 m


def build_long():
    nod = BN.NODES.replace('id="n0" x="0"', 'id="n0" x="%g"' % (-SHIFT))
    d = os.path.join(L.NETDIR, "long")
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "l.nod.xml"), "w").write(nod)
    open(os.path.join(d, "l.edg.xml"), "w").write(BN.EDGES)
    open(os.path.join(d, "l.con.xml"), "w").write(BN.CONN)
    cmd = [L.NETCONVERT, "-n", os.path.join(d, "l.nod.xml"),
           "-e", os.path.join(d, "l.edg.xml"),
           "-x", os.path.join(d, "l.con.xml"), "-o", LONGNET,
           "--no-turnarounds", "true", "--offset.disable-normalization", "true",
           "--default.lanewidth", "3.5", "--junctions.minimal-shape", "true",
           "--xml-validation", "never"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r


def profile(wd, x0_map, gore, t0, t1, bin_m=200.0):
    ev = L.parse_lanechanges(os.path.join(wd, "lanechanges.xml"))
    out = collections.Counter()
    tot = collections.Counter()
    for e in ev:
        if not (t0 <= e["t"] < t1):
            continue
        x = x0_map.get(e["edge"], float("nan")) + e["pos"]
        d = gore - x
        b = int(d // bin_m) * bin_m
        tot[b] += 1
        if L.reason_class(e["reason"]) == "strategic":
            out[b] += 1
    return out, tot


def main():
    build_long()
    p = L.full_params()
    res = {}

    # --- short (calibration) facility
    wd1 = os.path.join(L.RUNS, "look_short")
    L.run_scenario(wd1, p, seed=11)
    s1, t1c = profile(wd1, L.EDGE_X0, L.GORE_X, L.WARMUP, L.T_END_MEAS)

    # --- long facility: A starts at -3800, everything else unchanged
    x0_long = {"A": -SHIFT, "B": 600.0, "C": 2100.0, "D": 3300.0,
               "E": 3600.0, "R": 3600.0}
    wd2 = os.path.join(L.RUNS, "look_long")
    L.run_scenario(wd2, p, seed=11, net=LONGNET)
    s2, t2c = profile(wd2, x0_long, L.GORE_X, L.WARMUP, L.T_END_MEAS)

    def dump(name, s, t, maxd):
        rows = []
        b = 0.0
        while b < maxd:
            rows.append(dict(d_lo=b, d_hi=b + 200.0, strategic=s.get(b, 0),
                             all_lc=t.get(b, 0)))
            b += 200.0
        res[name] = rows
        print("\n%s : strategic / all LC by distance-to-gore bin" % name)
        for r in rows:
            print("  %5.0f-%5.0f m   strat=%5d   all=%6d" %
                  (r["d_lo"], r["d_hi"], r["strategic"], r["all_lc"]))

    dump("short_3600m_approach", s1, t1c, 3600)
    dump("long_7400m_approach", s2, t2c, 7400)

    # onset: the furthest bin that still holds >= 2% of the run's strategic events
    def onset(s):
        tot = sum(s.values())
        far = [b for b, c in s.items() if c >= 0.02 * tot]
        return max(far) if far else float("nan")
    res["strategic_total_short"] = sum(s1.values())
    res["strategic_total_long"] = sum(s2.values())
    res["onset_bin_short_m"] = onset(s1)
    res["onset_bin_long_m"] = onset(s2)
    # fraction of strategic events happening more than 3600 m from the gore
    res["frac_strategic_beyond_3600m_long"] = (
        sum(c for b, c in s2.items() if b >= 3600) / max(sum(s2.values()), 1))
    json.dump(res, open(os.path.join(L.TBL, "strategic_lookahead.json"), "w"),
              indent=2)
    print("\nstrategic events: short=%d long=%d" % (res["strategic_total_short"],
                                                    res["strategic_total_long"]))
    print("furthest bin holding >=2%% of strategic events: short=%s  long=%s"
          % (res["onset_bin_short_m"], res["onset_bin_long_m"]))
    print("fraction of long-facility strategic events beyond 3600 m: %.4f"
          % res["frac_strategic_beyond_3600m_long"])


if __name__ == "__main__":
    main()
