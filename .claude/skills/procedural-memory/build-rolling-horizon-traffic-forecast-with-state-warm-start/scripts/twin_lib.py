"""Shared machinery for the rolling-horizon digital twin: run wrappers, sensor
emulation, metric extraction."""
import gzip
import os
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import *  # noqa

def xparse(path):
    """ET.parse that transparently accepts a gzip-compressed sibling.
    (Bulky raw evidence XML in outputs/ is stored gzipped.)"""
    if os.path.exists(path):
        return ET.parse(path)
    if os.path.exists(path + ".gz"):
        return ET.parse(gzip.open(path + ".gz"))
    raise FileNotFoundError(path)


def xexists(path):
    return os.path.exists(path) or os.path.exists(path + ".gz")


NET = os.path.join(SCEN, "corridor.net.xml")
BASE_ROU = os.path.join(SCEN, "base.rou.xml")
INC_ROU = os.path.join(SCEN, "incident.rou.xml")

# state-file options used EVERYWHERE: precision 6 and --save-state.rng, because
# the Part-1 probes showed the default precision 2 alone perturbs trip outcomes
STATE_OPTS = ["--save-state.rng", "--save-state.precision", "6"]


def add_edgedata(d, period, ident="sc", fname=None):
    """Per-run edgeData additional file with an ABSOLUTE output path.
    (An edgeData file= path resolves relative to the additional file's own
    directory, so a shared additional file makes parallel runs clobber one file.)"""
    fname = fname or f"edge{period}.xml"
    p = os.path.join(d, f"edge{period}.add.xml")
    with open(p, "w") as f:
        f.write('<additional><edgeData id="%s" period="%d" file="%s" '
                'excludeEmpty="false"/></additional>'
                % (ident, period, os.path.join(d, fname)))
    return p, os.path.join(d, fname)


def run(d, args, clean=True):
    if clean and os.path.exists(d):
        shutil.rmtree(d)
    os.makedirs(d, exist_ok=True)
    t0 = time.perf_counter()
    p = subprocess.run([SUMO] + args, capture_output=True, text=True, cwd=d)
    wall = time.perf_counter() - t0
    with open(os.path.join(d, "cmd.txt"), "w") as f:
        f.write(" ".join([SUMO] + args) + "\n")
    with open(os.path.join(d, "stderr.txt"), "w") as f:
        f.write(p.stderr)
    if p.returncode != 0:
        raise RuntimeError(f"sumo failed in {d}: {p.stderr[:800]}")
    return wall, p


# ------------------------------------------------------------------ metrics
def read_edgedata(path):
    """-> {begin: {edge_id: (speed_or_None, sampledSeconds)}}"""
    out = {}
    if not os.path.exists(path):
        return out
    root = xparse(path).getroot()
    for iv in root:
        b = float(iv.get("begin"))
        d = {}
        for e in iv:
            sp = e.get("speed")
            d[e.get("id")] = (float(sp) if sp is not None else None,
                              float(e.get("sampledSeconds", 0)))
        out[b] = d
    return out


def metrics_from_bin(binmap):
    """Corridor metrics from ONE edgeData interval.

    tt_corridor    instantaneous corridor travel time (s) = sum over the 20
                   mainline edges of EDGE_LEN / space-mean-speed; an edge with no
                   vehicles in the bin contributes its free-flow travel time.
    cong_extent_m  total length (m) of mainline edges whose bin mean speed is
                   BELOW CONGESTED_SPEED (= 0.4 * V_FREE = 11.112 m/s).  An empty
                   edge is NOT congested.  Signed direction double-checked: lower
                   speed => congested => larger extent.
    seg_speed      per-station-edge mean speed (m/s), free-flow if empty.
    """
    tt = 0.0
    ext = 0.0
    for e in MAIN_EDGES:
        sp, ss = binmap.get(e, (None, 0.0))
        v = sp if (sp is not None and ss > 0 and sp > 0.1) else V_FREE
        tt += EDGE_LEN / v
        if sp is not None and ss > 0 and sp < CONGESTED_SPEED:
            ext += EDGE_LEN
    seg = {}
    for e in STATION_EDGES:
        sp, ss = binmap.get(e, (None, 0.0))
        seg[e] = sp if (sp is not None and ss > 0 and sp > 0.1) else V_FREE
    return {"tt_corridor": tt, "cong_extent_m": ext,
            **{f"speed_{e}": seg[e] for e in STATION_EDGES}}


METRIC_KEYS = ["tt_corridor", "cong_extent_m"] + [f"speed_{e}" for e in STATION_EDGES]


def metrics_series(edgedata_path):
    """-> {bin_begin: {metric: value}}"""
    return {b: metrics_from_bin(m) for b, m in read_edgedata(edgedata_path).items()}


# ------------------------------------------------------------------ sensors
def read_e1(path):
    """E1 output -> {(det_id, begin): dict}"""
    out = {}
    root = xparse(path).getroot()
    for iv in root:
        out[(iv.get("id"), float(iv.get("begin")))] = dict(iv.attrib)
    return out


def sensor_observations(e1_path, agg=300):
    """Aggregate the raw 60 s E1 output into `agg`-second station observations.

    Per station: total flow (veh) over all lanes, and the SPACE-MEAN (harmonic)
    speed pooled across lanes and sub-intervals:
        v_harm = sum(n_i) / sum(n_i / v_i)
    using SUMO's own per-lane harmonicMeanSpeed (never the arithmetic `speed`
    field, which is time-mean and structurally biased high).
    """
    raw = read_e1(e1_path)
    bins = {}
    for (did, b), a in raw.items():
        st = did.rsplit("_", 1)[0]
        bb = (int(b) // agg) * agg
        rec = bins.setdefault((st, bb), {"n": 0.0, "inv": 0.0, "occ": [], "nlane": 0})
        n = float(a.get("nVehContrib", 0))
        hv = float(a.get("harmonicMeanSpeed", -1))
        rec["n"] += n
        if n > 0 and hv > 0:
            rec["inv"] += n / hv
        rec["occ"].append(float(a.get("occupancy", 0)))
        rec["nlane"] += 1
    out = {}
    for (st, bb), r in bins.items():
        v = (r["n"] / r["inv"]) if r["inv"] > 0 else V_FREE
        out[(st, float(bb))] = {"count": r["n"],
                                "flow_vph": r["n"] * 3600.0 / agg,
                                "v_harm": v,
                                "occupancy": sum(r["occ"]) / max(1, len(r["occ"]))}
    return out


def sensor_metrics(obs, b):
    """Corridor metrics as a SENSOR-ONLY estimator would report them for bin b.

    Each of the 5 stations represents the 1 km of corridor centred on it
    (m0-m3 -> m1, m4-m7 -> m5, m8-m11 -> m9, m12-m15 -> m13, m16-m19 -> m17),
    so tt = sum over stations of 1000 / v_harm and the sensor congested-extent
    estimate is 1000 m per station whose harmonic speed is below the threshold.
    """
    tt = 0.0
    ext = 0.0
    seg = {}
    for st in STATION_EDGES:
        r = obs.get((st, b))
        v = r["v_harm"] if r else V_FREE
        v = max(v, 0.5)
        tt += 1000.0 / v
        if r and r["count"] > 0 and v < CONGESTED_SPEED:
            ext += 1000.0
        seg[st] = v
    return {"tt_corridor": tt, "cong_extent_m": ext,
            **{f"speed_{e}": seg[e] for e in STATION_EDGES}}


# ------------------------------------------------------------------ demand
VTYPE = ('  <vType id="car" vClass="passenger" length="5.0" minGap="2.5" '
         'accel="2.6" decel="4.5" sigma="0.5" tau="1.0" '
         'speedFactor="normc(1.0,0.10,0.7,1.3)" carFollowModel="Krauss"/>')


def write_flows(path, intervals, prefix):
    """intervals = [(begin, end, veh_per_hour)] -> exponential-headway flows."""
    r = ['<routes>', VTYPE]
    for (b, e, q) in intervals:
        if q <= 0:
            continue
        r.append(f'  <flow id="{prefix}_{int(b)}" type="car" begin="{b}" end="{e}" '
                 f'from="src" to="sink" period="exp({q/3600.0:.6f})" '
                 f'departLane="free" departSpeed="max"/>')
    r.append('</routes>')
    with open(path, "w") as f:
        f.write("\n".join(r))
    return path


def write_flows_count(path, intervals, prefix):
    """intervals = [(begin, end, n_vehicles)] -> exact-count flows (assimilation)."""
    r = ['<routes>', VTYPE]
    for (b, e, n) in intervals:
        if n <= 0:
            continue
        r.append(f'  <flow id="{prefix}_{int(b)}" type="car" begin="{b}" end="{e}" '
                 f'number="{int(round(n))}" from="src" to="sink" '
                 f'departLane="free" departSpeed="max"/>')
    r.append('</routes>')
    with open(path, "w") as f:
        f.write("\n".join(r))
    return path


# --------------------------------------------------- forking a forecast state
def strip_flowstate(src, dst):
    """Write `src` state to `dst` with every <flowState> element removed.

    REQUIRED before forking a forecast from a saved state with a DIFFERENT route
    file.  A state snapshot stores the pending emission schedule of every
    currently-active <flow> as <flowState>; --load-state restores those flow
    objects and they keep emitting.  If the forecast's own route file declares
    new flows (different ids), BOTH sets emit and the forecast silently runs at
    up to ~2x the intended demand for the first interval (verified: src outflow
    449 veh/300 s vs 310 in ground truth for the s11 t=1200 fork).  When the ids
    MATCH (as in the twin's own advance chain, which reuses one route file), the
    restored flowState is what provides continuity and must be kept.
    """
    op = gzip.open if src.endswith(".gz") else open
    with op(src, "rb") as f:
        tree = ET.parse(f)
    root = tree.getroot()
    n = 0
    for c in [c for c in root if c.tag == "flowState"]:
        root.remove(c)
        n += 1
    ow = gzip.open if dst.endswith(".gz") else open
    with ow(dst, "wb") as f:
        tree.write(f)
    return n
