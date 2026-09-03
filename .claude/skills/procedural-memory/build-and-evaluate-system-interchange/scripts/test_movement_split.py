#!/usr/bin/env python3
"""
TEST OF THE DESIGN RULE: a single directional flyover serves exactly ONE of the four
left-turn movements.  The claim that it is the better choice therefore ought to depend on
how CONCENTRATED the left-turn demand is.  This tests that claim instead of asserting it.

Two ODs with identical total volume (14 700 veh/h at scale 1.0) and identical through and
right-turn movements; only the split of the 3 250 veh/h of left-turn demand differs:

  concentrated  the study's OD -- 1300 / 1000 / 500 / 450 across the four loops, i.e. the
                movement the flyover serves is 40% of all left-turn demand and is one half
                of the heavy weaving pair.
  balanced      812/813/812/813 -- the same total left-turn demand spread evenly, so the
                flyover serves only 25% of it and three loaded loops remain.

If the flyover's advantage over the cloverleaf survives the balanced split, the design rule
is "a flyover always helps"; if it collapses, the rule is "a flyover helps in proportion to
how concentrated the left-turn demand is".
"""
import json
import os
import statistics as st
import subprocess
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scenario as S                                        # noqa: E402
import run_sweep as R                                       # noqa: E402

OD_BALANCED = {
    "A-West": {"A-East": 2800, "B-North": 812, "B-South": 500},
    "B-North": {"B-South": 2000, "A-East": 813, "A-West": 450},
    "A-East": {"A-West": 2600, "B-South": 812, "B-North": 550},
    "B-South": {"B-North": 2000, "A-West": 813, "A-East": 550},
}
SCALES = [1.00, 1.20, 1.35]
SEEDS = [11, 23, 37]
VARIANTS = ["clover", "flyover"]


def write_balanced(variant):
    routes = S.build_routes(variant)
    d = os.path.join(S.DEMDIR, variant)
    for sc in SCALES:
        path = os.path.join(d, "demand_%s_bal_%.2f.rou.xml" % (variant, sc))
        with open(path, "w") as fh:
            fh.write("<routes>\n")
            fh.write('  <vType id="car" vClass="passenger" length="5.0" minGap="2.5"\n'
                     '         accel="2.6" decel="4.5" sigma="0.5" tau="1.1" maxSpeed="45"\n'
                     '         speedFactor="normc(1.0,0.10,0.75,1.25)" carFollowModel="Krauss"\n'
                     '         laneChangeModel="LC2013"/>\n')
            for mid, seq in sorted(routes.items()):
                fh.write('  <route id="r_%s" edges="%s"/>\n' % (mid.replace("|", "__"), seq))
            for o, row in sorted(OD_BALANCED.items()):
                for dst, vph in sorted(row.items()):
                    mid = ("%s|%s" % (o, dst)).replace("|", "__")
                    fh.write('  <flow id="f_%s" type="car" route="r_%s" begin="0" end="%d"\n'
                             '        vehsPerHour="%.1f" departLane="free" '
                             'departSpeed="desired"/>\n' % (mid, mid, S.T_END_FLOW, vph * sc))
            fh.write("</routes>\n")


def job(a):
    variant, scale, seed = a
    rd = os.path.join(R.RUNDIR, variant, "bal_s%.2f_seed%d" % (scale, seed))
    os.makedirs(rd, exist_ok=True)
    tmpl = open(os.path.join(S.DEMDIR, variant, "detectors.add.template.xml")).read()
    open(os.path.join(rd, "detectors.add.xml"), "w").write(tmpl % {"out": "det"})
    cmd = ["sumo", "-n", os.path.join(S.NETDIR, variant, "%s.net.xml" % variant),
           "-r", os.path.join(S.DEMDIR, variant, "demand_%s_bal_%.2f.rou.xml" % (variant, scale)),
           "-a", os.path.join(rd, "detectors.add.xml"),
           "--tripinfo-output", os.path.join(rd, "tripinfo.xml"),
           "--summary-output", os.path.join(rd, "summary.xml"),
           "--statistic-output", os.path.join(rd, "stats.xml"),
           "--duration-log.statistics", "true", "--end", str(S.T_END), "--seed", str(seed),
           "--lanechange.duration", str(R.LC_DURATION),
           "--time-to-teleport", str(R.TTT), "--no-step-log", "true",
           "--xml-validation", "never", "--eager-insert", "false"]
    with open(os.path.join(rd, "sumo.log"), "w") as fh:
        try:
            subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, timeout=R.RUN_TIMEOUT)
        except subprocess.TimeoutExpired:
            fh.write("\n*** TIMEOUT ***\n")
    m = R.aggregate(rd, variant, scale, seed, R.LC_DURATION, "bal")
    for f in ("tripinfo.xml", "det_e1.xml", "det_e2.xml", "det_edge.xml"):
        p = os.path.join(rd, f)
        if os.path.exists(p) and seed != SEEDS[0]:
            os.remove(p)
    return m


def main():
    for v in VARIANTS:
        write_balanced(v)
    jobs = [(v, sc, sd) for v in VARIANTS for sc in SCALES for sd in SEEDS]
    res = []
    with ProcessPoolExecutor(max_workers=8) as ex:
        for m in ex.map(job, jobs):
            res.append(m)
    json.dump(res, open(os.path.join(S.EPISODE, "outputs", "tables",
                                     "sweep_bal.json"), "w"), indent=1)

    conc = R.json.load(open(os.path.join(S.EPISODE, "outputs", "tables", "sweep_base.json")))
    conc += R.json.load(open(os.path.join(S.EPISODE, "outputs", "tables", "sweep_high.json")))

    def agg(rows, tagfilter=None):
        by = {}
        for r in rows:
            by.setdefault((r["variant"], r["scale"]), []).append(r)
        return {k: st.mean([x.get("network_throughput_vph") or 0 for x in rs])
                for k, rs in by.items()}
    A, B = agg(conc), agg(res)
    print("Flyover advantage over the full cloverleaf, by left-turn demand split")
    print("(identical total OD volume; only the split of the 3 250 veh/h of lefts differs)\n")
    print("%-7s | %-32s | %-32s" % ("", "CONCENTRATED lefts (1300/1000/500/450)",
                                    "BALANCED lefts (812/813/812/813)"))
    print("%-7s | %10s %10s %8s | %10s %10s %8s"
          % ("demand", "clover", "flyover", "gain", "clover", "flyover", "gain"))
    for sc in SCALES:
        ac, af = A.get(("clover", sc)), A.get(("flyover", sc))
        bc, bf = B.get(("clover", sc)), B.get(("flyover", sc))
        print("%7.0f | %10.0f %10.0f %7.1f%% | %10.0f %10.0f %7.1f%%"
              % (14700 * sc, ac, af, (af - ac) / ac * 100, bc, bf, (bf - bc) / bc * 100))


if __name__ == "__main__":
    main()
