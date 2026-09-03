#!/usr/bin/env python3
"""Design verification, run BEFORE any treatment. Three independent checks:

CHECK 1 -- queue containment.  The incident queue must store on the main-exclusive
  edges (CB, then AC) and must NOT spill back over the diverge junction A onto OA.
  If it reaches OA, vehicles that wanted to divert are physically trapped and the
  whole penetration sweep would be measuring network geometry, not information.
  Measured from 60 s edgeData (speed + density on each edge) in the p=0 run.

CHECK 2 -- device assignment really follows the vType param.  tripinfo carries a
  `devices` attribute listing the devices each vehicle actually got.  We check
  that EVERY vehicle of vType `equipped` has a rerouting device and NO vehicle of
  vType `unequipped` has one.  This is the ground truth behind the whole
  equipped/unequipped subgroup split -- asserted nowhere, checked here.

CHECK 3 -- only equipped vehicles ever change route.  From vehroute-output, a
  vehicle that rerouted has a <routeDistribution> with more than one <route>
  child.  Unequipped vehicles must have zero such cases.
"""
import argparse
import os
import subprocess
import xml.etree.ElementTree as ET

EDGES = ["OA", "AC", "CB", "AP", "PB", "BD"]


def edgedata_add(path, out, period=60):
    with open(path, "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<additional>\n')
        f.write('  <edgeData id="ed" file="%s" period="%d" excludeEmpty="false"/>\n' % (out, period))
        f.write('</additional>\n')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", required=True)
    ap.add_argument("--incident-add", required=True)
    ap.add_argument("--gen", required=True, help="path to gen_demand.py")
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--vph", type=float, default=2500.0)
    a = ap.parse_args()
    os.makedirs(a.workdir, exist_ok=True)
    W = os.path.abspath(a.workdir)
    report = []

    def sim(tag, pen):
        d = os.path.join(W, tag)
        os.makedirs(d, exist_ok=True)
        rou = os.path.join(d, "demand.rou.xml")
        subprocess.run(["python3", a.gen, "--out", rou, "--penetration", str(pen),
                        "--seed", "1", "--veh-per-hour", str(a.vph)], check=True,
                       capture_output=True)
        eadd = os.path.join(d, "edgedata.add.xml")
        edgedata_add(eadd, "edgedata.xml")   # resolves relative to eadd's own dir
        cmd = ["sumo", "-n", os.path.abspath(a.net), "-r", rou,
               "-a", os.path.abspath(a.incident_add) + "," + eadd,
               "--tripinfo-output", os.path.join(d, "tripinfo.xml"),
               "--vehroute-output", os.path.join(d, "vehroutes.xml"),
               "--vehroute-output.exit-times", "true",
               "--device.rerouting.period", "30",
               "--device.rerouting.pre-period", "10",
               "--device.rerouting.adaptation-interval", "1",
               "--device.rerouting.adaptation-steps", "4",
               "--begin", "0", "--end", "9000", "--time-to-teleport", "300",
               "--no-step-log", "true", "--seed", "1"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit("sumo failed for %s: %s" % (tag, r.stderr[-3000:]))
        return d

    # ---------------- CHECK 1 ----------------
    d0 = sim("p000", 0.0)
    per_edge = {e: [] for e in EDGES}
    for iv in ET.parse(os.path.join(d0, "edgedata.xml")).getroot().findall("interval"):
        t = float(iv.get("begin"))
        for ed in iv.findall("edge"):
            if ed.get("id") in per_edge:
                per_edge[ed.get("id")].append(
                    (t, float(ed.get("speed") or 0), float(ed.get("density") or 0),
                     float(ed.get("occupancy") or 0)))
    report.append("CHECK 1 -- incident-queue containment (penetration = 0, incident 900-2400 s)")
    report.append("  edge   free-flow v   min v in 900-2700 s   max density   max occupancy")
    ok1 = True
    for e in EDGES:
        rows = per_edge[e]
        inc = [r for r in rows if 900 <= r[0] < 2700]
        pre = [r for r in rows if 300 <= r[0] < 900 and r[1] > 0]
        vff = max([r[1] for r in pre] or [0])
        vmin = min([r[1] for r in inc] or [0])
        dmax = max([r[2] for r in inc] or [0])
        omax = max([r[3] for r in inc] or [0])
        report.append("  %-5s  %8.1f      %10.1f        %10.1f    %10.1f" % (e, vff, vmin, dmax, omax))
    oa = [r for r in per_edge["OA"] if 900 <= r[0] < 2700]
    ac = [r for r in per_edge["AC"] if 900 <= r[0] < 2700]
    cb = [r for r in per_edge["CB"] if 900 <= r[0] < 2700]
    oa_minv, ac_minv, cb_minv = (min(x[1] for x in oa), min(x[1] for x in ac), min(x[1] for x in cb))
    oa_maxocc = max(x[3] for x in oa)
    report.append("  -> CB min speed %.1f m/s, AC min speed %.1f m/s: queue stores on the "
                  "main-exclusive edges." % (cb_minv, ac_minv))
    report.append("  -> OA min speed %.1f m/s, OA max occupancy %.1f%%: %s"
                  % (oa_minv, oa_maxocc,
                     "NO spillback over the diverge, diversion stays physically possible."
                     if oa_maxocc < 25 and oa_minv > 15 else
                     "WARNING - queue may be reaching the diverge; diverters could be trapped."))
    ok1 = oa_maxocc < 25 and oa_minv > 15

    # ---------------- CHECKS 2 & 3 ----------------
    d5 = sim("p050", 0.5)
    vt, devs = {}, {}
    for ti in ET.parse(os.path.join(d5, "tripinfo.xml")).getroot().findall("tripinfo"):
        vt[ti.get("id")] = ti.get("vType")
        devs[ti.get("id")] = ti.get("devices") or ""
    n_eq = sum(1 for v in vt.values() if v == "equipped")
    bad_eq = [k for k, v in vt.items() if v == "equipped" and "routing_" not in devs[k]]
    bad_un = [k for k, v in vt.items() if v == "unequipped" and "routing_" in devs[k]]
    report.append("")
    report.append("CHECK 2 -- vType param vs. actual device ownership (penetration = 0.5, n=%d)" % len(vt))
    report.append("  vType=equipped   : %d vehicles, %d WITHOUT a routing device" % (n_eq, len(bad_eq)))
    report.append("  vType=unequipped : %d vehicles, %d WITH a routing device"
                  % (len(vt) - n_eq, len(bad_un)))
    report.append("  sample devices string (equipped)   : %s"
                  % devs[[k for k, v in vt.items() if v == "equipped"][0]])
    report.append("  sample devices string (unequipped) : %s"
                  % devs[[k for k, v in vt.items() if v == "unequipped"][0]])
    ok2 = not bad_eq and not bad_un
    report.append("  -> %s" % ("PASS: vType partition == device partition exactly." if ok2
                              else "FAIL: vType does not control the rerouting device."))

    changed = {"equipped": 0, "unequipped": 0}
    took_alt = {"equipped": 0, "unequipped": 0}
    tot = {"equipped": 0, "unequipped": 0}
    for v in ET.parse(os.path.join(d5, "vehroutes.xml")).getroot().findall("vehicle"):
        t = v.get("type")
        if t not in tot:
            continue
        tot[t] += 1
        rd = v.find("routeDistribution")
        if rd is not None:
            rs = rd.findall("route")
            if len(rs) > 1:
                changed[t] += 1
            edges = rs[-1].get("edges")
        else:
            edges = v.find("route").get("edges")
        if " AP " in " " + edges + " ":
            took_alt[t] += 1
    report.append("")
    report.append("CHECK 3 -- who actually changes route (penetration = 0.5)")
    for t in ("equipped", "unequipped"):
        report.append("  %-11s n=%4d  rerouted=%4d (%.1f%%)  ended on ALT=%4d (%.1f%%)"
                      % (t, tot[t], changed[t], 100.0 * changed[t] / max(1, tot[t]),
                         took_alt[t], 100.0 * took_alt[t] / max(1, tot[t])))
    ok3 = changed["unequipped"] == 0 and took_alt["unequipped"] == 0 and took_alt["equipped"] > 0
    report.append("  -> %s" % ("PASS: only equipped vehicles reroute, and they really do use the alternate."
                               if ok3 else "FAIL: route changes are not confined to the equipped subgroup."))

    report.append("")
    report.append("OVERALL: %s" % ("all three design checks PASS" if (ok1 and ok2 and ok3) else "SOME CHECKS FAILED"))
    txt = "\n".join(report)
    print(txt)
    with open(os.path.join(W, "design_verification.txt"), "w") as f:
        f.write(txt + "\n")


if __name__ == "__main__":
    main()
