#!/usr/bin/env python3
"""Replication design: rebuild the car skim from EACH seed's edgeData separately
(and the PT skim from each seed's personinfo), recompute the headline measures,
and report the seed spread so that scenario-ranking claims can be separated from
Monte-Carlo noise.  Also runs the MAUP test (25 fine zones vs 13 coarse zones)."""
import os
import sys
import json
import math
import statistics
import subprocess
import xml.etree.ElementTree as ET

WORK = sys.argv[1]
SCNS = ["base", "altA", "altB"]
SEEDS = ["1", "2", "3"]
INF = float("inf")

AC = json.load(open(os.path.join(WORK, "accessibility.json")))
D = json.load(open(os.path.join(WORK, "demand.json")))
DEM = D["demographics"]
ZINFO = json.load(open(os.path.join(WORK, "zones.json")))["zones"]
ZONES = sorted(ZINFO)
POP = {z: DEM[z]["pop"] for z in ZONES}
CAR = {z: DEM[z]["car_ownership"] for z in ZONES}
BETA0 = AC["results"]["base"]["beta_car_per_s"]
CONN = {z: ZINFO[z]["connector"] for z in ZONES}
pairs = [(i, j) for i in ZONES for j in ZONES if i != j]


def add_intra(T):
    o = dict(T)
    for z in ZONES:
        near = [T[(z, j)] for j in ZONES if j != z and T.get((z, j), INF) < INF]
        o[(z, z)] = 0.5 * min(near) if near else INF
    return o


def gravity(T, beta):
    return {i: sum(DEM[j]["jobs"] * math.exp(-beta * T[(i, j)])
                   for j in ZONES if T.get((i, j), INF) < INF) for i in ZONES}


def cumulative(T, ts):
    return {i: sum(DEM[j]["jobs"] for j in ZONES if T.get((i, j), INF) <= ts)
            for i in ZONES}


def wmean(a, w=POP):
    return sum(a[z] * w[z] for z in a) / sum(w[z] for z in a)


def gini(v, w):
    order = sorted(v, key=lambda z: v[z])
    W = sum(w[z] for z in order); A = sum(w[z] * v[z] for z in order)
    cw = ca = 0.0; pts = [(0.0, 0.0)]
    for z in order:
        cw += w[z]; ca += w[z] * v[z]; pts.append((cw / W, ca / A))
    area = sum((pts[k][0] - pts[k - 1][0]) * (pts[k][1] + pts[k - 1][1]) / 2.0
               for k in range(1, len(pts)))
    return 1 - 2 * area


def qshare(v, w, lo, hi):
    order = sorted(v, key=lambda z: v[z])
    W = sum(w.values()); A = sum(w[z] * v[z] for z in order)
    acc = cum = 0.0
    for z in order:
        w0, w1 = cum / W, (cum + w[z]) / W
        cum += w[z]
        ov = max(0.0, min(w1, hi) - max(w0, lo))
        if ov > 0:
            acc += ov / (w1 - w0) * w[z] * v[z]
    return acc / A


def palma(v, w):
    return qshare(v, w, .9, 1.) / qshare(v, w, 0., .4)


trips = os.path.join(WORK, "skimvar.trips.xml")
with open(trips, "w") as f:
    f.write("<routes>\n")
    for i, j in pairs:
        f.write('    <trip id="S#%s#%s" depart="900" from="%s" to="%s"/>\n'
                % (i, j, CONN[i], CONN[j]))
    f.write("</routes>\n")

OUT = {}
for scn in SCNS:
    per_seed = []
    for s in SEEDS:
        # --- car skim from this seed alone
        w = os.path.join(WORK, "w_%s_s%s.xml" % (scn, s))
        root = ET.parse(os.path.join(WORK, "edgedata_%s_s%s.xml" % (scn, s))).getroot()
        with open(w, "w") as f:
            f.write('<meandata>\n  <interval begin="0" end="3600" id="ed">\n')
            for iv in root.findall("interval"):
                for e in iv.findall("edge"):
                    if e.get("traveltime"):
                        f.write('    <edge id="%s" traveltime="%s"/>\n'
                                % (e.get("id"), e.get("traveltime")))
            f.write("  </interval>\n</meandata>\n")
        out = os.path.join(WORK, "skimvar_%s_s%s.rou.xml" % (scn, s))
        subprocess.run(["duarouter", "-n", os.path.join(WORK, "%s.net.xml" % scn),
                        "-r", trips, "-o", out, "--write-costs", "--ignore-errors",
                        "--weight-files", w, "--weight-attribute", "traveltime",
                        "--weights.expand", "--seed", "42", "-b", "0", "-e", "3600"],
                       check=True, capture_output=True)
        Tc = {}
        for v in ET.parse(out).getroot().findall("vehicle"):
            _, i, j = v.get("id").split("#")
            Tc[(i, j)] = float(v.find("route").get("cost"))
        Tc = add_intra(Tc)
        # --- PT skim from this seed alone
        acc = {}
        for _, el in ET.iterparse(os.path.join(WORK, "tripinfo_%s_s%s.xml" % (scn, s)),
                                  events=("end",)):
            if el.tag == "personinfo" and el.get("id", "").startswith("P#"):
                if any(c.tag == "ride" for c in el):
                    _, i, j, t = el.get("id").split("#")
                    acc.setdefault((i, j), []).append(float(el.get("duration")))
            if el.tag in ("tripinfo", "personinfo"):
                el.clear()
        Tp = add_intra({k: statistics.fmean(v) for k, v in acc.items()})
        gc, gp = gravity(Tc, BETA0), gravity(Tp, BETA0)
        person = {z: CAR[z] * gc[z] + (1 - CAR[z]) * gp[z] for z in ZONES}
        per_seed.append(dict(
            seed=s, mean_car=wmean(gc), mean_pt=wmean(gp), mean_person=wmean(person),
            gini_person=gini(person, POP), palma_person=palma(person, POP),
            cum_car_10=wmean(cumulative(Tc, 600)),
            cum_car_15=wmean(cumulative(Tc, 900)),
            cum_pt_45=wmean(cumulative(Tp, 2700)),
            n_pt_pairs=sum(1 for p in pairs if Tp.get(p, INF) < INF),
            A_person=person))
    OUT[scn] = per_seed


def spread(scn, key):
    v = [x[key] for x in OUT[scn]]
    return dict(mean=statistics.fmean(v), sd=statistics.stdev(v),
                cv_pct=100 * statistics.stdev(v) / statistics.fmean(v), values=v)


SUM = {scn: {k: spread(scn, k) for k in
             ("mean_car", "mean_pt", "mean_person", "gini_person", "palma_person",
              "cum_car_10", "cum_car_15", "cum_pt_45")} for scn in SCNS}

# paired (common-random-number) differences per seed
PAIR = {}
for scn in ("altA", "altB"):
    for k in ("mean_car", "mean_person", "gini_person", "palma_person"):
        d = [OUT[scn][i][k] - OUT["base"][i][k] for i in range(len(SEEDS))]
        m, sd = statistics.fmean(d), statistics.stdev(d)
        se = sd / math.sqrt(len(d))
        PAIR["%s_%s" % (scn, k)] = dict(mean=m, sd=sd, se=se,
                                        t=m / se if se else float("inf"),
                                        ci95=[m - 4.303 * se, m + 4.303 * se],
                                        values=d,
                                        sign_consistent=all(x > 0 for x in d) or
                                        all(x < 0 for x in d))

# ------------------------------------------------------------------ MAUP test
# coarse zoning: merge the 8 sectors of each ring band into 4 quadrants
def coarse(z):
    if z == "CORE":
        return "CORE"
    band, sec = z.split("_")
    return "%s_Q%d" % (band, (int(sec) - 1) // 2 + 1)


CZ = sorted({coarse(z) for z in ZONES})
CPOP = {c: sum(POP[z] for z in ZONES if coarse(z) == c) for c in CZ}
MAUP = {}
for scn in SCNS:
    fine = OUT[scn][0]["A_person"]
    cz = {c: sum(fine[z] * POP[z] for z in ZONES if coarse(z) == c) / CPOP[c]
          for c in CZ}
    MAUP[scn] = dict(n_fine=len(ZONES), n_coarse=len(CZ),
                     gini_fine=gini(fine, POP), gini_coarse=gini(cz, CPOP),
                     palma_fine=palma(fine, POP), palma_coarse=palma(cz, CPOP),
                     mean_fine=wmean(fine), mean_coarse=wmean(cz, CPOP))

json.dump(dict(per_seed=OUT, summary=SUM, paired=PAIR, maup=MAUP, beta=BETA0),
          open(os.path.join(WORK, "seed_variability.json"), "w"), indent=1)

for scn in SCNS:
    s = SUM[scn]
    print("%-5s meanPerson %.0f (sd %.1f, CV %.3f%%)  Gini %.4f (sd %.5f)  "
          "Palma %.4f (sd %.5f)"
          % (scn, s["mean_person"]["mean"], s["mean_person"]["sd"],
             s["mean_person"]["cv_pct"], s["gini_person"]["mean"],
             s["gini_person"]["sd"], s["palma_person"]["mean"], s["palma_person"]["sd"]))
for k, v in PAIR.items():
    print("paired %-24s mean %+.4g  sd %.4g  t=%.2f  consistent=%s"
          % (k, v["mean"], v["sd"], v["t"], v["sign_consistent"]))
print("MAUP:", json.dumps(MAUP, indent=1))
