#!/usr/bin/env python3
"""Shared definitions for the car-following CALIBRATION & VALIDATION pipeline.

Three facilities
----------------
  ring     : single-lane closed ring, 1000 m, 16 nodes, 120 km/h.  EXACT density
             (k = 1000*N/L).  This is the fast FD *instrument* used inside the
             sensitivity screening and the calibration inner loop.
             (methodology reused from `validate-kinematic-wave-theory-across-car-following-models`)
  freeway  : 3-lane, 4.5 km mainline, on-ramp merge at x=3000 m and a 3->2 lane
             drop at x=3500 m (fixed-capacity bottleneck), E1 station at x=2500 m.
             This is the *validation* facility (open road, lane changing, merge).
             (methodology reused from `build-macroscopic-fundamental-diagram`)
  signal   : isolated 4-way, 1 through lane/approach, 50 km/h, hand-written
             tlLogic.  HELD OUT facility for saturation-headway transferability.
             (methodology reused from `measure-saturation-flow-and-validate-webster-method`)

Everything is per-lane so the empirical targets (pc/h/ln, veh/km/ln) apply directly.
"""
import os, sys, math, json, subprocess, shutil, tempfile
import xml.etree.ElementTree as ET

SUMO_BIN = "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/bin"
SUMO = os.path.join(SUMO_BIN, "sumo")
NETCONVERT = os.path.join(SUMO_BIN, "netconvert")

EP = "/Users/liuqi/Desktop/simskill/episodic-memory/2026-08-03_17-00-00"
SCRIPTS = os.path.join(EP, "attempts/attempt-1/scripts")
OUT = os.path.join(EP, "outputs")
NETDIR = os.path.join(OUT, "net")
RUNS = ("/private/tmp/claude-501/-Users-liuqi-Desktop-simskill/"
        "73c4d241-de1e-411f-9fbf-eda6b9d3b094/scratchpad/runs")

RING_NET = os.path.join(NETDIR, "ring2.net.xml")   # 2-lane ring (see note below)
RING_NET_1L = os.path.join(NETDIR, "ring.net.xml")
FWY_NET = os.path.join(NETDIR, "fwy.net.xml")
SIG_NET = os.path.join(NETDIR, "sig.net.xml")

RING_L = 1000.0          # m circumference
RING_LANES = 2           # per-lane density k = 1000*N/(L*RING_LANES)
RING_N_EDGES = 16
# WHY 2 LANES, not the 1-lane ring of `validate-kinematic-wave-theory-...`:
# with a heterogeneous desired-speed distribution (speedFactor dev > 0) a SINGLE
# lane admits no overtaking, so the measured "free-flow speed" collapses to the
# MINIMUM desired speed in the sample (a moving-bottleneck artifact) instead of
# the fleet mean that the empirical FFS target refers to.  Two lanes restore
# overtaking, so v_free is the fleet mean, and the instrument is also closer to
# the multi-lane freeway facility it must transfer to.
FREE_SPEED = 33.33       # m/s = 120 km/h posted limit on ring + freeway
SIG_SPEED = 13.89        # m/s = 50 km/h on the signalised approach

# --------------------------------------------------------------------------
#  EMPIRICAL TARGET VECTOR  (published field values, per lane, passenger cars)
# --------------------------------------------------------------------------
# Sources for the numbers: HCM 6th ed. basic freeway segment (FFS 110-120 km/h,
# capacity 2200-2400 pc/h/ln, breakdown density ~ 26-28 pc/km/ln), Chiabaut/
# Leclercq wave-speed observations (15-20 km/h), classic jam-density range
# 125-140 veh/km/ln, HCM saturation headway ~1.9 s (s ~ 1900 pc/h/gr/ln).
TARGETS = {
    "v_free_kmh": dict(target=110.0, tol=5.0,  weight=1.0, unit="km/h"),
    "q_max":      dict(target=2200.0, tol=150.0, weight=1.5, unit="veh/h/ln"),
    "k_crit":     dict(target=25.0,  tol=4.0,  weight=1.0, unit="veh/km/ln"),
    "k_jam":      dict(target=130.0, tol=10.0, weight=1.0, unit="veh/km/ln"),
    "w_kmh":      dict(target=17.5,  tol=2.5,  weight=1.0, unit="km/h"),
}
# held out from the freeway objective; used only for H4 transferability
TARGET_SAT_HEADWAY = dict(target=1.90, tol=0.15, unit="s")


# --------------------------------------------------------------------------
#  PARAMETER SPACE
# --------------------------------------------------------------------------
# name -> (low, high, default, applies-to-models)
PARAM_SPACE = {
    "tau":            (0.5,  2.0,  1.0,  ("Krauss", "IDM")),
    "accel":          (1.0,  4.0,  2.6,  ("Krauss", "IDM")),
    "decel":          (2.0,  6.0,  4.5,  ("Krauss", "IDM")),
    "sigma":          (0.0,  1.0,  0.5,  ("Krauss",)),   # verified INERT for SUMO IDM
    "minGap":         (1.0,  5.0,  2.5,  ("Krauss", "IDM")),
    "length":         (4.0,  7.0,  5.0,  ("Krauss", "IDM")),
    "speedFactor":    (0.80, 1.20, 1.0,  ("Krauss", "IDM")),   # mean
    "speedDev":       (0.0,  0.20, 0.1,  ("Krauss", "IDM")),   # deviation
    "apparentDecel":  (2.0,  9.0,  4.5,  ("Krauss",)),
    "emergencyDecel": (4.5,  12.0, 9.0,  ("Krauss",)),
    "delta":          (1.0,  8.0,  4.0,  ("IDM",)),
}

# SUMO's *actual* defaults for a plain <vType vClass="passenger"> (v1.27.1).
# apparentDecel/emergencyDecel default to decel / max(decel,4.5) respectively.
SUMO_DEFAULTS = dict(tau=1.0, accel=2.6, decel=4.5, sigma=0.5, minGap=2.5,
                     length=5.0, speedFactor=1.0, speedDev=0.1,
                     apparentDecel=4.5, emergencyDecel=9.0, delta=4.0)


def params_for(model):
    return [k for k, v in PARAM_SPACE.items() if model in v[3]]


def vtype_xml(vid, model, p, vclass="passenger", maxspeed=55.55):
    """Render a vType. speedFactor/speedDev go into SUMO's normc distribution."""
    a = {
        "id": vid, "vClass": vclass, "carFollowModel": model,
        "length": "%.4f" % p["length"], "minGap": "%.4f" % p["minGap"],
        "accel": "%.4f" % p["accel"], "decel": "%.4f" % p["decel"],
        "tau": "%.4f" % p["tau"], "sigma": "%.4f" % p.get("sigma", 0.5),
        "maxSpeed": "%.3f" % maxspeed,
        "speedFactor": "normc(%.4f,%.4f,0.20,2.00)" % (p["speedFactor"],
                                                       max(p["speedDev"], 1e-6)),
    }
    if model == "Krauss":
        a["apparentDecel"] = "%.4f" % p.get("apparentDecel", p["decel"])
        a["emergencyDecel"] = "%.4f" % max(p.get("emergencyDecel", 9.0), p["decel"])
    else:
        a["emergencyDecel"] = "%.4f" % max(9.0, p["decel"])
        # GOTCHA (verified 1.27.1): IDM's `delta` is honoured ONLY as a vType
        # ATTRIBUTE.  Written as <param key="delta"> it is silently ignored --
        # no warning, no error, and delta=1 vs delta=8 give byte-identical
        # output.  Screening it as a <param> child measures a no-op.
        a["delta"] = "%.4f" % p.get("delta", 4.0)
        a.pop("sigma", None)     # verified inert for SUMO's IDM (mu* == 0 exactly)
    return "<vType " + " ".join('%s="%s"' % kv for kv in a.items()) + "/>"


def full_params(model, overrides=None):
    p = {k: SUMO_DEFAULTS[k] for k in params_for(model)}
    if overrides:
        p.update({k: v for k, v in overrides.items() if k in p})
    return p


# --------------------------------------------------------------------------
#  summary parsing
# --------------------------------------------------------------------------
def read_summary(path):
    rows = []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "step":
            rows.append({k: float(v) for k, v in el.attrib.items()})
            el.clear()
    return rows


def run_sumo(args, cwd=None, timeout=600):
    p = subprocess.run([SUMO] + args, capture_output=True, text=True,
                       cwd=cwd, timeout=timeout)
    return p


# --------------------------------------------------------------------------
#  RING FD PROBE  -- the calibration instrument
# --------------------------------------------------------------------------
RING_CELLS = [4, 7, 11, 15, 19, 22, 25, 28, 32, 37, 44, 55, 70, 90, 110]  # veh/km/LANE


def _n_veh(k_per_lane):
    return int(round(k_per_lane * RING_L * RING_LANES / 1000.0))


def _write_ring_routes(path, n_veh, vtype_line, vtype_id, laps, dep_factor,
                       perturb=True, tau=1.0, length=5.0, mingap=2.5,
                       v_dep_cap=33.33):
    """Place n_veh vehicles evenly over RING_LANES lanes, downstream-most first.

    GOTCHA (verified against the SUMO binary, 1.27.1): if departSpeed exceeds
    what the vehicle's own speedFactor permits, SUMO does NOT clamp the speed --
    it silently REWRITES that vehicle's speedFactor upward, permanently
    ("Choosing new speed factor 1.20 ... to match departure speed"), corrupting
    free-flow speed and capacity for the whole run.  The warning is suppressed
    by --no-warnings.  Hence v_dep is hard-capped by v_dep_cap below the
    slowest plausible desired speed, and the caller greps stderr for the warning.
    """
    c = RING_L / RING_N_EDGES
    per_lane = n_veh // RING_LANES
    extra = n_veh - per_lane * RING_LANES
    lines = ["<routes>", "  " + vtype_line]
    vid = 0
    plan = []
    for ln in range(RING_LANES):
        cnt = per_lane + (1 if ln < extra else 0)
        if cnt == 0:
            continue
        spacing = RING_L / cnt
        off = 0.5 * spacing * ln          # stagger lanes
        s_eq = RING_L * RING_LANES / max(n_veh, 1)   # per-lane spacing
        v_dep = max(0.0, min(v_dep_cap,
                             dep_factor * (s_eq - length - mingap) / max(tau, 1e-3)))
        for i in range(cnt):
            plan.append((ln, (off + i * spacing) % RING_L, v_dep))
    plan.sort(key=lambda t: -t[1])        # descending position -> leader first
    for ln, pos_abs, v_dep in plan:
        j = min(int(pos_abs // c), RING_N_EDGES - 1)
        pos = pos_abs - j * c
        route = " ".join("e%d" % ((j + t) % RING_N_EDGES)
                         for t in range(laps * RING_N_EDGES))
        stop = ""
        if perturb and vid == 0:
            stop = ('\n    <stop lane="e%d_%d" endPos="%.2f" duration="4"/>\n  '
                    % (RING_N_EDGES // 2, ln, c * 0.5))
        lines.append('  <vehicle id="v%d" type="%s" depart="0" departLane="%d" '
                     'departPos="%.3f" departSpeed="%.3f">'
                     '<route edges="%s"/>%s</vehicle>'
                     % (vid, vtype_id, ln, pos, v_dep, route, stop))
        vid += 1
    lines.append("</routes>")
    with open(path, "w") as f:
        f.write("\n".join(lines))


SF_WARN = "Choosing new speed factor"


def ring_cell(workdir, model, p, k_per_lane, seed=42, end=420.0, warmup=180.0,
              step=0.5, perturb=True):
    """Run one ring density cell at a requested PER-LANE density.
    Retries with lower departSpeed until the ring is FULLY loaded
    (running == requested) -- the silent under-fill gotcha."""
    os.makedirs(workdir, exist_ok=True)
    n_veh = _n_veh(k_per_lane)
    vt = vtype_xml("car", model, p)
    rou = os.path.join(workdir, "r.rou.xml")
    smy = os.path.join(workdir, "s.xml")
    laps = max(6, int(math.ceil(end * FREE_SPEED * 1.3 / RING_L)) + 2)
    # hard cap: 95% of the SLOWEST plausible desired speed in the fleet
    v_cap = 0.95 * FREE_SPEED * max(0.25, p["speedFactor"] - 3.0 * p["speedDev"])
    last = None
    for dep in (0.9, 0.6, 0.35, 0.15, 0.0):
        _write_ring_routes(rou, n_veh, vt, "car", laps, dep, perturb=perturb,
                           tau=p["tau"], length=p["length"], mingap=p["minGap"],
                           v_dep_cap=v_cap)
        r = run_sumo(["-n", RING_NET, "-r", rou, "--summary-output", smy,
                      "--step-length", str(step), "--begin", "0", "--end", str(end),
                      "--no-step-log", "true",
                      "--xml-validation", "never",
                      "--time-to-teleport", "-1",
                      "--collision.action", "warn",
                      "--step-method.ballistic", "true",
                      "--default.speeddev", "0",
                      "--seed", str(seed)])
        if r.returncode != 0:
            last = ("sumo rc=%d %s" % (r.returncode, r.stderr[-400:]))
            continue
        if SF_WARN in r.stderr:
            last = "speedFactor silently rewritten by departSpeed"
            continue
        rows = [x for x in read_summary(smy) if x["time"] >= warmup]
        if not rows:
            last = "no rows"
            continue
        if rows[-1]["running"] >= n_veh:
            break
        last = "underfilled %d/%d at dep=%.2f" % (rows[-1]["running"], n_veh, dep)
    else:
        return dict(ok=False, err=last, k=k_per_lane)

    ks, vs, qs = [], [], []
    for x in rows:
        n = x["running"]
        if n <= 0:
            continue
        k = 1000.0 * n / (RING_L * RING_LANES)      # per lane
        v = x["meanSpeed"]
        ks.append(k); vs.append(v); qs.append(k * v * 3.6)
    if not ks:
        return dict(ok=False, err="empty window", k=k_per_lane)
    L = rows[-1]
    mean = lambda a: sum(a) / len(a)
    return dict(ok=True, k=mean(ks), v_ms=mean(vs), v_kmh=mean(vs) * 3.6,
                q=mean(qs), n_req=n_veh, running=L["running"],
                teleports=L["teleports"], collisions=L["collisions"],
                halting=mean([x["halting"] for x in rows]))


def fd_features(cells):
    """Derive the 5 FD features from a list of ring cells (dicts from ring_cell).

    v_free  : MEASURED mean speed at the lowest-density cell (not a fit) --
              a triangular through-origin fit is biased for models with a
              genuinely curved free branch (verified prior finding).
    q_max   : max OBSERVED flow; k_crit : density at that flow.
    w, k_jam: OLS on the congested branch  q = w*(k_jam - k).
    """
    import numpy as np
    good = [c for c in cells if c.get("ok") and c.get("collisions", 0) == 0]
    if len(good) < 5:
        return None
    good = sorted(good, key=lambda c: c["k"])
    kk = np.array([c["k"] for c in good])
    qq = np.array([c["q"] for c in good])
    vv = np.array([c["v_kmh"] for c in good])
    i_pk = int(np.argmax(qq))

    # --- free-flow speed: OLS through the origin over the 3 lowest-density
    # cells (pooling cuts the speedFactor small-sample noise a single cell has).
    nlow = min(3, max(1, i_pk))
    v_free = float((kk[:nlow] * qq[:nlow]).sum() / (kk[:nlow] ** 2).sum() / 1.0)
    v_free_lowcell = float(vv[0])

    # --- capacity / critical density: parabola through the peak cell and its
    # two neighbours, so k_crit is not quantised to the density grid.
    q_max = float(qq[i_pk]); k_crit = float(kk[i_pk])
    if 0 < i_pk < len(kk) - 1:
        x = kk[i_pk - 1:i_pk + 2]; y = qq[i_pk - 1:i_pk + 2]
        try:
            a, b, cc = np.polyfit(x, y, 2)
            if a < 0:
                xv = -b / (2 * a)
                if x[0] <= xv <= x[2]:
                    k_crit = float(xv); q_max = float(a * xv * xv + b * xv + cc)
        except Exception:
            pass
    cong = kk > kk[i_pk] + 1e-9
    if cong.sum() >= 3:
        A = np.vstack([kk[cong], np.ones(int(cong.sum()))]).T
        sl, ic = np.linalg.lstsq(A, qq[cong], rcond=None)[0]
        w = -float(sl); k_jam = float(-ic / sl) if sl < 0 else float("nan")
        pred = A @ np.array([sl, ic])
        ssr = float(((qq[cong] - pred) ** 2).sum())
        sst = float(((qq[cong] - qq[cong].mean()) ** 2).sum())
        r2 = 1 - ssr / sst if sst > 0 else float("nan")
    else:
        w = k_jam = r2 = float("nan")
    return dict(v_free_kmh=v_free, v_free_lowcell_kmh=v_free_lowcell,
                q_max=q_max, k_crit=k_crit,
                q_max_grid=float(qq[i_pk]), k_crit_grid=float(kk[i_pk]),
                k_jam=k_jam, w_kmh=w, cong_r2=r2, n_cells=len(good),
                teleports=sum(c.get("teleports", 0) for c in good),
                collisions=sum(c.get("collisions", 0) for c in cells if c.get("ok")),
                n_failed=len([c for c in cells if not c.get("ok")]))


def fd_probe(tag, model, p, seed=42, cells=None, root=None, end=420.0,
             warmup=180.0, keep=False):
    cells = cells or RING_CELLS
    root = root or os.path.join(RUNS, "probe")
    wd = os.path.join(root, tag)
    res = []
    for n in cells:
        res.append(ring_cell(os.path.join(wd, "k%03d" % n), model, p, n, seed=seed,
                             end=end, warmup=warmup))
    f = fd_features(res)
    if not keep:
        shutil.rmtree(wd, ignore_errors=True)
    return f, res


# --------------------------------------------------------------------------
#  OBJECTIVE
# --------------------------------------------------------------------------
def geh(m, c):
    return math.sqrt((m - c) ** 2 / max((m + c) / 2.0, 1e-9))


def objective(feat, targets=None, micro=None, micro_weight=0.0):
    """Weighted RMSN over the FD feature vector (+ optional microscopic term).

    RMSN here = sqrt( sum_i w_i * ((m_i - t_i)/t_i)^2 / sum_i w_i ), i.e. a
    weighted root-mean-square *normalised* error, reported as a fraction.
    A feature that could not be measured (NaN) is charged a 100% error.
    """
    targets = targets or TARGETS
    num = den = 0.0
    parts = {}
    for k, spec in targets.items():
        t = spec["target"]; w = spec["weight"]
        m = feat.get(k, float("nan")) if feat else float("nan")
        if m != m or not math.isfinite(m):
            e = 1.0
        else:
            e = (m - t) / t
        e = max(min(e, 3.0), -3.0)
        parts[k] = dict(measured=m, target=t, rel_err=e,
                        within_tol=(m == m and abs(m - t) <= spec["tol"]))
        num += w * e * e; den += w
    rmsn = math.sqrt(num / den)
    obj = rmsn
    if micro is not None and micro_weight > 0:
        obj = math.sqrt(((1 - micro_weight) * rmsn ** 2)
                        + micro_weight * micro ** 2)
    return dict(obj=obj, rmsn=rmsn, parts=parts,
                geh_qmax=geh(feat["q_max"], targets["q_max"]["target"])
                if feat and feat.get("q_max") == feat.get("q_max") else float("nan"))
