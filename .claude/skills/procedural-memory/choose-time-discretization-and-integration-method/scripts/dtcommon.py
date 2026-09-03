"""Shared infrastructure for the SUMO time-discretization factorial study.

Design contract
---------------
* A "cell" is (step_length dt, integration method, actionStepLength policy).
* Full factorial: dt in {1.0,0.5,0.25,0.1} x {euler,ballistic} x {tied,pinned1.0} = 16 cells.
* CRN: the SAME seed list and the SAME pre-written route/demand files are used in
  every cell, so any cell-to-cell difference is attributable to discretization only.
* Reference cell = dt=0.1s, ballistic, actionStepLength pinned at 1.0s ("ref").
  A second reference ("ref_tied") = dt=0.1 ballistic asl tied is also reported,
  because the two answer different questions (Q2).
"""
import os
import re
import sys
import math
import time
import json
import subprocess
import xml.etree.ElementTree as ET

SUMO_HOME = os.environ.get(
    "SUMO_HOME",
    "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo")
sys.path.insert(0, os.path.join(SUMO_HOME, "tools"))
BIN = os.path.join(os.path.dirname(SUMO_HOME.rstrip("/")), "bin") \
    if os.path.isdir(os.path.join(os.path.dirname(SUMO_HOME.rstrip("/")), "bin")) else None
SUMO = "sumo"
NETCONVERT = "netconvert"

HERE = os.path.dirname(os.path.abspath(__file__))
EP = os.path.abspath(os.path.join(HERE, "..", "..", ".."))   # episode root
OUT = os.path.join(EP, "outputs")
NET = os.path.join(OUT, "net")
TAB = os.path.join(OUT, "tables")
FIG = os.path.join(OUT, "figs")
LOG = os.path.join(OUT, "logs")
RUNS = os.path.join(OUT, "runs")
for d in (OUT, NET, TAB, FIG, LOG, RUNS):
    os.makedirs(d, exist_ok=True)

# ----------------------------------------------------------------- factorial
DTS = [1.0, 0.5, 0.25, 0.1]
METHODS = ["euler", "ballistic"]
ASL = ["tied", "pin1"]          # tied -> actionStepLength = dt ; pin1 -> 1.0 s
SEEDS = [1001, 1002, 1003, 1004, 1005]      # CRN seed list, identical everywhere
REF = ("0.1", "ballistic", "pin1")


def cells():
    for dt in DTS:
        for m in METHODS:
            for a in ASL:
                yield (fmt_dt(dt), m, a)


def fmt_dt(dt):
    return ("%g" % dt)


def cell_id(c):
    return "dt%s_%s_%s" % (c[0], c[1], c[2])


def asl_value(c):
    """actionStepLength that this cell puts on the vType (None => leave default)."""
    dt, m, a = c
    if a == "pin1":
        return 1.0
    return None          # tied: SUMO default actionStepLength == step-length


def cell_args(c):
    """sumo CLI args implied by the cell (integration method + step length)."""
    dt, m, a = c
    args = ["--step-length", dt]
    if m == "ballistic":
        args += ["--step-method.ballistic", "true"]
    return args


# ----------------------------------------------------------------- run sumo
class RunResult(dict):
    pass


def run_sumo(args, cwd=None, timeout=1800, tag=""):
    cmd = [SUMO] + [str(a) for a in args]
    t0 = time.perf_counter()
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout)
    wall = time.perf_counter() - t0
    return RunResult(rc=p.returncode, out=p.stdout, err=p.stderr, wall=wall,
                     cmd=" ".join(cmd), tag=tag)


BASE_ARGS = ["--no-step-log", "true", "--xml-validation", "never",
             "--duration-log.disable", "true"]


# ----------------------------------------------------------------- parsing
def read_tripinfo(path):
    if not os.path.exists(path):
        return []
    rows = []
    try:
        for _, el in ET.iterparse(path, events=("end",)):
            if el.tag == "tripinfo":
                d = dict(el.attrib)
                em = el.find("emissions")
                if em is not None:
                    d.update({("em_" + k): v for k, v in em.attrib.items()})
                rows.append(d)
                el.clear()
    except ET.ParseError:
        pass
    return rows


def read_summary(path):
    if not os.path.exists(path):
        return []
    rows = []
    try:
        for _, el in ET.iterparse(path, events=("end",)):
            if el.tag == "step":
                rows.append({k: float(v) for k, v in el.attrib.items()})
                el.clear()
    except ET.ParseError:
        pass
    return rows


def summary_totals(path):
    """Correct handling: teleports/collisions in <summary> are CUMULATIVE ->
    take the LAST step's value, never the sum (documented gotcha)."""
    rows = read_summary(path)
    if not rows:
        return dict(teleports=0, collisions=0, running=0, inserted=0, ended=0, loaded=0)
    last = rows[-1]
    return dict(teleports=int(last.get("teleports", 0)),
                collisions=int(last.get("collisions", 0)),
                running=int(last.get("running", 0)),
                inserted=int(last.get("inserted", 0)),
                ended=int(last.get("ended", 0)),
                loaded=int(last.get("loaded", 0)),
                halting=int(last.get("halting", 0)))


def read_instant(path):
    """instantInductionLoop output -> list of dicts."""
    if not os.path.exists(path):
        return []
    rows = []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "instantOut":
            rows.append(dict(el.attrib))
            el.clear()
    return rows


def read_fcd(path):
    """FCD -> {time: {vid: (x, speed, pos_on_lane_unknown)}} minimal."""
    out = []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "timestep":
            t = float(el.attrib["time"])
            for v in el:
                out.append((t, v.attrib["id"], float(v.attrib["x"]),
                            float(v.attrib["y"]), float(v.attrib["speed"])))
            el.clear()
    return out


SSM_CAT = {}
for _c in (2, 3, 18):
    SSM_CAT[_c] = "rear_end"
for _c in (6, 7, 8, 19):
    SSM_CAT[_c] = "merging"
for _c in range(10, 18):
    SSM_CAT[_c] = "crossing"
SSM_CAT[111] = "collision"


def read_ssm(path):
    """Parse an SSMLog -> dict of lists."""
    res = dict(conflicts=[], maxBR=[], n=0)
    if not os.path.exists(path):
        return res
    try:
        tree = ET.parse(path)
    except ET.ParseError:
        return res
    root = tree.getroot()
    for cf in root.findall("conflict"):
        rec = dict(ego=cf.get("ego"), foe=cf.get("foe"))
        for meas in ("minTTC", "maxDRAC", "PET", "maxMDRAC"):
            e = cf.find(meas)
            if e is None:
                continue
            v = e.get("value")
            rec[meas] = None if v in (None, "NA") else float(v)
            ty = e.get("type")
            if ty not in (None, "NA"):
                rec.setdefault("types", []).append(int(float(ty)))
        rec["cats"] = sorted(set(SSM_CAT.get(t, "other") for t in rec.get("types", [])))
        res["conflicts"].append(rec)
    for gm in root.findall("globalMeasures"):
        e = gm.find("maxBR")
        if e is not None and e.get("value") not in (None, "NA"):
            res["maxBR"].append(float(e.get("value")))
    res["n"] = len(res["conflicts"])
    return res


# ----------------------------------------------------------------- stats
def mean(x):
    x = [v for v in x if v is not None and not (isinstance(v, float) and math.isnan(v))]
    return sum(x) / len(x) if x else float("nan")


def sd(x):
    x = [v for v in x if v is not None and not (isinstance(v, float) and math.isnan(v))]
    if len(x) < 2:
        return 0.0
    m = sum(x) / len(x)
    return math.sqrt(sum((v - m) ** 2 for v in x) / (len(x) - 1))


T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
        8: 2.306, 9: 2.262, 10: 2.228, 14: 2.145, 19: 2.093, 29: 2.045}


def tcrit(df):
    if df <= 0:
        return float("nan")
    if df in T975:
        return T975[df]
    ks = sorted(T975)
    for k in ks:
        if df <= k:
            return T975[k]
    return 1.96


def ci95(x):
    """returns (mean, halfwidth)"""
    x = [v for v in x if v is not None and not (isinstance(v, float) and math.isnan(v))]
    n = len(x)
    if n == 0:
        return float("nan"), float("nan")
    if n == 1:
        return x[0], float("nan")
    m = sum(x) / n
    s = sd(x)
    return m, tcrit(n - 1) * s / math.sqrt(n)


def paired_t(a, b):
    """CRN paired t-test on a-b. returns (meandiff, halfwidth, t, significant)"""
    d = [x - y for x, y in zip(a, b)]
    n = len(d)
    if n < 2:
        return (d[0] if d else float("nan")), float("nan"), float("nan"), False
    m = sum(d) / n
    s = sd(d)
    if s == 0:
        return m, 0.0, float("inf") if m != 0 else 0.0, m != 0
    hw = tcrit(n - 1) * s / math.sqrt(n)
    return m, hw, m / (s / math.sqrt(n)), abs(m) > hw


def savejson(name, obj):
    p = os.path.join(TAB, name)
    with open(p, "w") as f:
        json.dump(obj, f, indent=1, default=str)
    return p


# ----------------------------------------------------------------- vType xml
DEFAULT_CAR = dict(accel="2.6", decel="4.5", sigma="0.5", length="5.0",
                   minGap="2.5", maxSpeed="55.55", tau="1.0",
                   emissionClass="HBEFA3/PC_G_EU4", speedDev="0.1",
                   carFollowModel="Krauss")


def vtype_xml(vid, params, asl=None, ssm=False, extra_params=None):
    p = dict(params)
    p["id"] = vid
    if asl is not None:
        p["actionStepLength"] = "%g" % asl
    attrs = " ".join('%s="%s"' % (k, v) for k, v in p.items())
    kids = ""
    if ssm:
        kids = ('<param key="has.ssm.device" value="true"/>'
                '<param key="device.ssm.measures" value="TTC DRAC PET BR MDRAC"/>'
                '<param key="device.ssm.thresholds" value="3.0 3.0 2.0 0.0 3.4"/>'
                '<param key="device.ssm.range" value="60.0"/>'
                '<param key="device.ssm.extratime" value="5.0"/>')
    for k, v in (extra_params or {}).items():
        kids += '<param key="%s" value="%s"/>' % (k, v)
    if kids:
        return "<vType %s>%s</vType>" % (attrs, kids)
    return "<vType %s/>" % attrs


def netconvert(prefix, out, extra=()):
    cmd = [NETCONVERT, "-n", prefix + ".nod.xml", "-e", prefix + ".edg.xml",
           "-x", prefix + ".con.xml", "-o", out] + list(extra)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stdout + r.stderr)
        raise SystemExit("netconvert failed: " + out)
    return r
