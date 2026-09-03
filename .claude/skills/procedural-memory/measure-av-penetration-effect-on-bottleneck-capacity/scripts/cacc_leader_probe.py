#!/usr/bin/env python3
"""
MICROSCOPIC PROBE of the car-following models, isolated from all network effects.

Two questions the mixed-traffic experiment cannot answer on its own:

 (A) STEADY-STATE GAP.  What time gap does each follower model actually settle
     to behind a steadily-cruising leader?  This turns the *nominal* tau into a
     *measured effective* time gap, which is what actually sets capacity, and it
     validates that HUMAN_FAST really is gap-matched to ACC/CACC.

 (B) LEADER AWARENESS.  Does SUMO's CACC behave differently when its leader is
     CACC-equipped versus a plain Krauss HUMAN?  If the settled gap and the
     disturbance response are identical either way, then SUMO's CACC does NOT
     cooperate in mixed traffic - it is just another single-leader controller,
     and any "cooperation" claim about a mixed fleet is unsupported.

Setup: single lane, no lane changing, no other traffic.  The leader is a
speed-capped copy of the tested leader type (maxSpeed 22 m/s) so the follower
genuinely closes in and settles.  speedFactor is pinned to 1.0 for everything so
desired-speed dispersion cannot contaminate the gap measurement.
At t=200 s a variable speed sign drops the lane to 14 m/s for 30 s: the
follower's minimum gap and speed undershoot measure disturbance response.
"""
import os
import sys
import subprocess
import shutil
import json
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scenario as S  # noqa: E402

OUT = os.path.join(os.path.dirname(HERE), "probe")
SUMO = shutil.which("sumo")

NOD = '<nodes><node id="a" x="0" y="0"/><node id="b" x="12000" y="0"/></nodes>'
EDG = '<edges><edge id="L" from="a" to="b" numLanes="1" speed="30.0"/></edges>'

PAIRS = [("CACC", "CACC"), ("HUMAN", "CACC"),
         ("ACC", "ACC"), ("HUMAN", "ACC"),
         ("HUMAN_FAST", "HUMAN_FAST"), ("HUMAN", "HUMAN_FAST"),
         ("HUMAN", "HUMAN"),
         ("CACC_TIGHT", "CACC_TIGHT"), ("HUMAN", "CACC_TIGHT")]

V_CRUISE = 22.0
V_DIP = 14.0
T_DIP, T_DIP_END = 200.0, 230.0


def probe_vtypes():
    """Copies of the study vTypes with speedFactor pinned to 1.0, plus
    speed-capped '<name>_LEAD' variants used as the leader."""
    lines = []
    for name, d in S.VTYPES.items():
        a = dict(d)
        a["speedFactor"] = "1.0"
        a.pop("id")
        col = a.pop("color")
        attrs = " ".join('%s="%s"' % (k, v) for k, v in a.items())
        lines.append('  <vType id="%s" color="%s" %s/>' % (name, col, attrs))
        a2 = dict(a)
        a2["maxSpeed"] = str(V_CRUISE)
        attrs2 = " ".join('%s="%s"' % (k, v) for k, v in a2.items())
        lines.append('  <vType id="%s_LEAD" color="%s" %s/>' % (name, col, attrs2))
    return "\n".join(lines)


def main():
    os.makedirs(OUT, exist_ok=True)
    open(os.path.join(OUT, "p.nod.xml"), "w").write(NOD)
    open(os.path.join(OUT, "p.edg.xml"), "w").write(EDG)
    subprocess.run(["netconvert", "--node-files", "p.nod.xml", "--edge-files",
                    "p.edg.xml", "-o", "p.net.xml"], cwd=OUT, check=True,
                   capture_output=True)
    open(os.path.join(OUT, "p.add.xml"), "w").write(
        '<additional>\n' + probe_vtypes() + '\n</additional>\n')
    open(os.path.join(OUT, "p.vss.xml"), "w").write(
        '<additional>\n'
        '  <variableSpeedSign id="vss" lanes="L_0">\n'
        '    <step time="0" speed="30.0"/>\n'
        '    <step time="%.0f" speed="%.1f"/>\n'
        '    <step time="%.0f" speed="30.0"/>\n'
        '  </variableSpeedSign>\n</additional>\n' % (T_DIP, V_DIP, T_DIP_END))

    print("%-26s %9s %10s %9s %11s %9s" %
          ("leader -> follower", "gap[m]", "timegap[s]", "hdwy[s]", "minGapDip", "vminDip"))
    res = {}
    for lead, foll in PAIRS:
        with open(os.path.join(OUT, "p.rou.xml"), "w") as f:
            f.write('<routes>\n  <route id="r" edges="L"/>\n')
            f.write('  <vehicle id="lead" type="%s_LEAD" route="r" depart="0" '
                    'departSpeed="%.1f" departPos="200"/>\n' % (lead, V_CRUISE))
            f.write('  <vehicle id="foll" type="%s" route="r" depart="0" '
                    'departSpeed="%.1f" departPos="20"/>\n' % (foll, V_CRUISE))
            f.write('</routes>\n')
        open(os.path.join(OUT, "p.sumocfg"), "w").write("""<configuration>
 <input><net-file value="p.net.xml"/><route-files value="p.rou.xml"/>
 <additional-files value="p.add.xml,p.vss.xml"/></input>
 <time><begin value="0"/><end value="330"/><step-length value="0.1"/></time>
 <processing><time-to-teleport value="-1"/><default.speeddev value="0"/></processing>
 <report><no-step-log value="true"/><xml-validation value="never"/></report>
 <output><fcd-output value="p.fcd.xml"/><device.fcd.period value="0.5"/></output>
</configuration>""")
        pr = subprocess.run([SUMO, "-c", "p.sumocfg"], cwd=OUT,
                            capture_output=True, text=True)
        if pr.returncode != 0:
            print(lead, foll, "SUMO FAILED", pr.stderr[:300])
            continue
        series = []
        for _, el in ET.iterparse(os.path.join(OUT, "p.fcd.xml"), events=("end",)):
            if el.tag != "timestep":
                continue
            vs = {v.get("id"): v for v in el.findall("vehicle")}
            if "lead" in vs and "foll" in vs:
                series.append((float(el.get("time")),
                               float(vs["lead"].get("pos")), float(vs["lead"].get("speed")),
                               float(vs["foll"].get("pos")), float(vs["foll"].get("speed"))))
            el.clear()
        pre = [s for s in series if 150.0 <= s[0] <= T_DIP - 5.0]
        dip = [s for s in series if T_DIP <= s[0] <= T_DIP_END + 60.0]
        if not pre:
            print("%-26s  (never settled)" % ("%s -> %s" % (lead, foll)))
            continue
        gap = sum(s[1] - s[3] - 5.0 for s in pre) / len(pre)
        v = sum(s[4] for s in pre) / len(pre)
        tg = gap / v
        hdwy = (gap + 5.0) / v          # bumper-to-bumper -> capacity = 3600/headway
        mind = min(s[1] - s[3] - 5.0 for s in dip) if dip else float("nan")
        vmin = min(s[4] for s in dip) if dip else float("nan")
        res["%s->%s" % (lead, foll)] = dict(gap=gap, timegap=tg, headway=hdwy,
                                            min_gap_dip=mind, v_min_dip=vmin,
                                            settled_speed=v, lane_cap=3600.0 / hdwy)
        print("%-26s %9.3f %10.3f %9.3f %11.3f %9.3f" %
              ("%s -> %s" % (lead, foll), gap, tg, hdwy, mind, vmin))

    print("\n--- implied single-lane capacity at %.0f m/s (3600/headway) ---" % V_CRUISE)
    for k, v in res.items():
        print("  %-26s %7.0f veh/h/lane" % (k, v["lane_cap"]))

    print("\n--- LEADER-AWARENESS TEST ---")
    print("NOTE: comparing 'behind own type' vs 'behind HUMAN' also changes the LEADER's")
    print("own dynamics, so only the settled-gap difference is a clean signal; the")
    print("disturbance-response difference is confounded by the leader's own response.")
    for foll in ["CACC", "CACC_TIGHT", "ACC", "HUMAN_FAST"]:
        same, mixed = "%s->%s" % (foll, foll), "HUMAN->%s" % foll
        if same in res and mixed in res:
            dg = res[same]["gap"] - res[mixed]["gap"]
            print("  %-11s settled gap behind own type %.3f m (%.3f s) vs behind HUMAN "
                  "%.3f m (%.3f s):  dGap=%+.3f m -> %s"
                  % (foll, res[same]["gap"], res[same]["timegap"],
                     res[mixed]["gap"], res[mixed]["timegap"], dg,
                     "LEADER-AWARE" if abs(dg) > 0.10 else "NOT leader-aware"))
    print("\n--- DECISIVE TEST: two followers with DIFFERENT tau behind the SAME HUMAN leader ---")
    a, b = "HUMAN->CACC", "HUMAN->CACC_TIGHT"
    if a in res and b in res:
        print("  CACC(tau=%.1f) gap %.3f m | CACC_TIGHT(tau=%.1f) gap %.3f m | difference %.4f m"
              % (S.TAU_FAST, res[a]["gap"], S.TAU_CACC_TIGHT, res[b]["gap"],
                 res[a]["gap"] - res[b]["gap"]))
        print("  -> %s" % ("identical => behind a non-CACC leader the CACC model IGNORES its own "
                           "tau and falls back to a FIXED headway"
                           if abs(res[a]["gap"] - res[b]["gap"]) < 0.05 else
                           "different => tau still takes effect behind a human leader"))
    print("\n--- gap == tau*v + minGap check (v=%.1f m/s, minGap=2.5 m) ---" % V_CRUISE)
    for k, v in res.items():
        implied_tau = (v["gap"] - 2.5) / v["settled_speed"]
        print("  %-26s settled gap implies an EFFECTIVE tau of %.3f s" % (k, implied_tau))
    json.dump(res, open(os.path.join(OUT, "probe_results.json"), "w"), indent=1)
    print("\nwrote", os.path.join(OUT, "probe_results.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
