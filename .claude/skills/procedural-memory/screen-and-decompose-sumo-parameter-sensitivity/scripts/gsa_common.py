#!/usr/bin/env python3
"""Common library for the MULTI-SUBSYSTEM GLOBAL SENSITIVITY ANALYSIS of a
3-intersection signalised arterial.

WHAT IS REUSED (not rewritten):
  * The network builder, SignalPlan / tlLogic writer, trips writer, duarouter
    wrapper, run_sumo, tripinfo/summary parsers and the t-CI helpers all come
    from
      .claude/skills/procedural-memory/design-arterial-signal-progression-and-verify-bandwidth/scripts/arterial_lib.py
    imported as `A` below (build_net, SignalPlan, write_demand, route,
    run_sumo, parse_summary, parse_tripinfo, teleport_ids, tconf, write_e2).
  * The Morris trajectory sampler is imported in screen_morris.py from
      .claude/skills/procedural-memory/calibrate-car-following-parameters-against-field-targets/scripts/morris.py
    exactly as `calibrate-lane-changing-parameters-at-a-freeway-diverge/scripts/screen_morris.py`
    does (sys.argv shim, then retarget CFMORRIS.K / CFMORRIS.rng).

WHAT IS NEW HERE:
  * the 13-factor MULTI-SUBSYSTEM design (car-following + lane-changing +
    junction/driver + fleet composition + demand scale + SIGNAL TIMING),
  * the network-total, censoring-free MOE extraction (edgeData timeLoss/CO2,
    E2 jam length, teleports),
  * the noise-floor-normalised screening decision gate,
  * the Saltelli/Sobol variance-based estimators in sobol.py.
"""
import os, sys, json, math, shutil, subprocess, hashlib, tempfile
import xml.etree.ElementTree as ET
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
EPI = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
OUT = os.path.join(EPI, "outputs")
TBL = os.path.join(OUT, "tables")
FIG = os.path.join(OUT, "figures")
SCN = os.path.join(OUT, "scenario")
RAW = os.path.join(OUT, "raw")
LOG = os.path.join(OUT, "logs")
for d in (OUT, TBL, FIG, SCN, RAW, LOG):
    os.makedirs(d, exist_ok=True)

# ---- REUSED library from the arterial-progression skill --------------------
ART = ("/Users/liuqi/Desktop/simskill/.claude/skills/procedural-memory/"
       "design-arterial-signal-progression-and-verify-bandwidth/scripts")
sys.path.insert(0, ART)
import arterial_lib as A  # noqa: E402
import sumolib  # noqa: E402

SUMO = A.SUMO
NPROC = int(os.environ.get("GSA_NPROC", "10"))

# ------------------------------------------------------------- scenario -----
N_INT = 3
BLOCK = 400.0          # m between signals
ART_LANES = 3          # leftmost = exclusive left bay -> 2 through lanes
CROSS_LANES = 2
ART_SPEED = 13.89      # m/s (50 km/h)
V_PROG = ART_SPEED
WARM = 600.0           # s warm-up discarded from every MOE
END = 3600.0           # s total simulated
NET = os.path.join(SCN, "art.net.xml")

# base signal plan (the un-perturbed baseline)
BASE_C = 90.0
BASE_XFRAC = 0.30      # cross-street green as a fraction of C
BASE_GL = 10.0         # arterial protected-left green (fixed, not a factor)

# demand levels per regime, chosen so the arterial through movement runs at
# ~v/c 0.60 and ~v/c 1.05 (see build_scenario.py, which reports the arithmetic
# and the empirical confirmation).
REGIMES = {
    "under": dict(thru=990.0, art_side=70.0, cross=280.0),
    "over":  dict(thru=1740.0, art_side=120.0, cross=430.0),
}

# ------------------------------------------------------------- factors ------
# (lo, hi, default, subsystem, note)
FACTORS = [
    # tau's lower bound is the SIMULATION STEP LENGTH, not the low end of the
    # empirically plausible range.  VERIFIED (outputs/tables/
    # tau_step_collision_probe.json): with --step-length 1.0 s, tau < 1.0 s
    # breaks the Krauss safe-velocity guarantee and the run fills with genuine
    # collisions, every one of which SUMO silently resolves by teleporting the
    # vehicle (--collision.action defaults to "teleport").  At the oversaturated
    # regime's worst design point: tau=0.70 -> 11402 collisions, 0.80 -> 10300,
    # 0.90 -> 4528, 1.00 -> 0, 1.10/1.40/1.80 -> 0.  Holding tau at 0.70 and
    # shrinking the step instead: 1.0 s -> 11402, 0.7 s -> 0, 0.5/0.25/0.1 s -> 0.
    # sigma is NOT the cause (tau=0.70, sigma=0.00 still gives 10540).
    # The first screening pass used 0.70-1.80 and had to be discarded: 50/140
    # design points fell below the step length and 100% of them were
    # contaminated (archived in outputs/raw/CONTAMINATED_tau_below_steplength/).
    ("tau",            1.00,  1.80, 1.00, "car-following",
     "desired time headway (s); lower bound = --step-length (1.0 s), below "
     "which Krauss is not collision-free"),
    ("minGap",         1.50,  3.50, 2.50, "car-following",
     "standstill gap (m)"),
    ("sigma",          0.00,  0.90, 0.50, "car-following",
     "Krauss driver imperfection (dawdling)"),
    ("accel",          1.50,  3.50, 2.60, "car-following",
     "max acceleration (m/s2); controls signal start-up lost time"),
    ("lcAssertive",    0.50,  3.00, 1.00, "lane-changing",
     "willingness to accept smaller gaps (LC2013)"),
    ("lcSpeedGain",    0.20,  5.00, 1.00, "lane-changing",
     "eagerness for discretionary speed-gain changes"),
    ("lcCooperative",  0.00,  1.00, 1.00, "lane-changing",
     "willingness to make room for others"),
    ("impatience",     0.00,  1.00, 0.00, "junction/driver",
     "vType impatience: growth of gap-acceptance aggressiveness when waiting"),
    ("jmTimegapMinor", 1.00,  5.00, 1.00, "junction/driver",
     "minimum time gap accepted on a minor link (s)"),
    ("hgvShare",       0.00,  0.25, 0.05, "fleet composition",
     "heavy-goods-vehicle fraction of the fleet (vTypeDistribution)"),
    ("demandScale",    0.85,  1.15, 1.00, "demand",
     "multiplier on the whole demand matrix (sumo --scale)"),
    ("cycleLength",   60.00,140.00, 90.00, "signal control",
     "common cycle length (s); offsets held fixed in seconds"),
    ("crossGreenFrac", 0.20,  0.40, 0.30, "signal control",
     "cross-street green as a fraction of the cycle (green split)"),
]
NAMES = [f[0] for f in FACTORS]
SPACE = {f[0]: (f[1], f[2]) for f in FACTORS}
DEFAULTS = {f[0]: f[3] for f in FACTORS}
SUBSYS = {f[0]: f[4] for f in FACTORS}
K = len(NAMES)

# MOEs. 'sign' = +1 if larger is worse (a "cost"), used only for reporting.
MOES = ["arrived", "timeloss_per_km", "queue_mean_m", "queue_max_m",
        "co2_kg", "teleports", "fuel_l", "mean_speed"]
PRIMARY_MOES = ["arrived", "timeloss_per_km", "queue_mean_m", "queue_max_m",
                "co2_kg"]


def unit_to_params(u, names=None):
    names = names or NAMES
    p = dict(DEFAULTS)
    for n, x in zip(names, u):
        lo, hi = SPACE[n]
        p[n] = lo + float(x) * (hi - lo)
    return p


def params_to_unit(p, names=None):
    names = names or NAMES
    return [(p[n] - SPACE[n][0]) / (SPACE[n][1] - SPACE[n][0]) for n in names]


# ---------------------------------------------------- per-run input files ---
TRUCK = dict(vClass="truck", length=12.0, width=2.5, maxSpeed=25.0,
             accel=1.3, decel=3.5, tau=1.4, minGap=3.0, sigma=0.5,
             emissionClass="HBEFA4/RT_le7.5t_Euro-VI_D-E",
             guiShape="truck")


def write_vtypes(path, p):
    """vTypeDistribution 'drv' -> car (carries the perturbed parameters) +
    hgv (FIXED realistic truck).  hgvShare is therefore a pure fleet-mix
    factor and, by construction, DILUTES the car parameters -> a genuine
    interaction we can test for."""
    hgv = max(0.0, min(0.95, p["hgvShare"]))
    car = 1.0 - hgv
    L = ['<additional>', '  <vTypeDistribution id="drv">']
    L.append('    <vType id="car" vClass="passenger" probability="%.6f" '
             'accel="%.4f" decel="4.5" sigma="%.4f" tau="%.4f" minGap="%.4f" '
             'impatience="%.4f" jmTimegapMinor="%.4f" '
             'lcAssertive="%.4f" lcSpeedGain="%.4f" lcCooperative="%.4f" '
             'speedDev="0.10" emissionClass="HBEFA4/PC_petrol_Euro-6ab"/>'
             % (car, p["accel"], p["sigma"], p["tau"], p["minGap"],
                p["impatience"], p["jmTimegapMinor"], p["lcAssertive"],
                p["lcSpeedGain"], p["lcCooperative"]))
    L.append('    <vType id="hgv" probability="%.6f" vClass="truck" '
             'length="12.0" maxSpeed="25.0" accel="1.3" decel="3.5" tau="1.4" '
             'minGap="3.0" sigma="0.5" speedDev="0.05" '
             'emissionClass="HBEFA4/RT_le7.5t_Euro-VI_D-E"/>' % hgv)
    L += ['  </vTypeDistribution>', '</additional>']
    open(path, "w").write("\n".join(L))
    return path


def make_plan(p):
    """Fixed-time coordinated plan for the perturbed (cycleLength,
    crossGreenFrac) pair.  Phasing is ALWAYS 'lead-lead' here.

    GOTCHA (verified): `arterial_lib.SignalPlan.__init__` rejects a split whose
    `gB` (the both-through overlap that ONLY the lead-lag / lag-lead phasings
    consume) drops below 3 s -- even when the plan is lead-lead and therefore
    never uses gB.  The corner C=60 s with crossGreenFrac=0.40 gives
    gT=14.0, gB=0.0 and raised `infeasible split`, which silently killed
    9 of 140 Morris design points on the first pass.  The check is bypassed
    here (fields set directly) and replaced by the constraint that actually
    binds a lead-lead plan, gT >= 5 s, which holds over the whole factor box
    (min gT = 14.0 s at C=60, crossGreenFrac=0.40)."""
    C = float(p["cycleLength"])
    gX = C * float(p["crossGreenFrac"])
    offs = [i * BLOCK / V_PROG for i in range(N_INT)]   # fixed in SECONDS
    pl = A.SignalPlan.__new__(A.SignalPlan)
    pl.C, pl.gX, pl.gL, pl.n = C, gX, BASE_GL, N_INT
    pl.gT = C - 12.0 - BASE_GL - gX
    pl.gB = pl.gT - BASE_GL - A.YELLOW - A.ALLRED
    if pl.gT < 5.0:
        raise ValueError("infeasible lead-lead split C=%.2f gX=%.2f gT=%.2f"
                         % (C, gX, pl.gT))
    pl.modes = ["lead-lead"] * N_INT
    pl.offs = list(offs)
    pl.delta = BASE_GL + A.YELLOW + A.ALLRED
    pl._wcache = {}
    pl._gcache = {}
    return pl


def write_meandata(path, edge_out, emi_out):
    L = ['<additional>',
         '  <edgeData id="ed" type="performance" file="%s" begin="%.1f" '
         'end="%.1f" excludeEmpty="false" withInternal="true"/>'
         % (edge_out, WARM, END),
         '  <edgeData id="em" type="emissions" file="%s" begin="%.1f" '
         'end="%.1f" excludeEmpty="false" withInternal="true"/>'
         % (emi_out, WARM, END),
         '</additional>']
    open(path, "w").write("\n".join(L))
    return path


def write_e2(net, path, out_xml):
    """E2 lane-area detectors over EVERY arterial approach lane (both
    directions, including the two boundary stubs), one interval covering the
    whole analysis window so jamLength statistics are window-exact."""
    seq = ["W"] + ["J%d" % i for i in range(N_INT)] + ["E"]
    eids = []
    for a, b in zip(seq, seq[1:]):
        eids += ["%sto%s" % (a, b), "%sto%s" % (b, a)]
    L = ['<additional>']
    n = 0
    for eid in eids:
        e = net.getEdge(eid)
        # only APPROACH edges matter for queueing: an edge is an approach if
        # its destination node is a traffic light
        if e.getToNode().getType() != "traffic_light":
            continue
        for ln in e.getLanes():
            L.append('<laneAreaDetector id="e2_%s" lane="%s" pos="0" '
                     'endPos="%.2f" period="%.1f" file="%s" '
                     'timeThreshold="1.0" speedThreshold="1.39" '
                     'jamThreshold="10.0"/>'
                     % (ln.getID(), ln.getID(), ln.getLength() - 0.1,
                        60.0, out_xml))
            n += 1
    L.append('</additional>')
    open(path, "w").write("\n".join(L))
    return path, n


# ------------------------------------------------------------- MOE parse ----
def parse_edgedata(path):
    tot_tl = 0.0; tot_vs = 0.0; tot_vm = 0.0; tot_wait = 0.0
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "edge":
            ss = float(el.get("sampledSeconds", 0) or 0)
            if ss > 0:
                sp = float(el.get("speed", 0) or 0)
                tot_vs += ss
                tot_vm += ss * sp
                tot_tl += float(el.get("timeLoss", 0) or 0)
                tot_wait += float(el.get("waitingTime", 0) or 0)
        el.clear()
    return dict(veh_s=tot_vs, veh_m=tot_vm, timeloss_s=tot_tl,
                waiting_s=tot_wait)


def parse_emissions(path):
    co2 = 0.0; fuel = 0.0; nox = 0.0
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "edge":
            co2 += float(el.get("CO2_abs", 0) or 0)
            fuel += float(el.get("fuel_abs", 0) or 0)
            nox += float(el.get("NOx_abs", 0) or 0)
        el.clear()
    return dict(co2_mg=co2, fuel_mg=fuel, nox_mg=nox)


def parse_e2(path):
    """Queue MOEs from the E2 laneAreaDetector stream, INSIDE the analysis
    window only.

    TRAP (verified, see outputs/tables/e2_queue_attribute_trap.json):
    `jamLengthInMetersSum` is a SUM OVER SIMULATION STEPS inside the interval,
    i.e. a time-integral in metre-steps, NOT a mean queue length.  With a 1 s
    step and a 60 s interval it is ~60x `meanMaxJamLengthInMeters`.  The
    time-average queue is `meanMaxJamLengthInMeters`.

    Definitions used here (stated explicitly because a "max queue" can be any
    of three different order statistics):
      queue_mean_m       = mean over (detector x interval) of
                           meanMaxJamLengthInMeters      -- average queue
      queue_max_m        = mean over intervals of
                           max-over-detectors(maxJamLengthInMeters)
                           -- the TYPICAL peak approach queue in a minute
      queue_max_global_m = single max over every detector x interval
                           -- an extreme order statistic, reported but not
                              used as a screening MOE (very noisy)
      queue_sum_raw      = mean of jamLengthInMetersSum, kept only to document
                           the trap above
    """
    means, sums = [], []
    per_iv = {}
    gmax = 0.0
    n = 0
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "interval":
            b = float(el.get("begin")); e = float(el.get("end"))
            if b >= WARM - 1e-6 and e <= END + 1e-6:
                means.append(float(el.get("meanMaxJamLengthInMeters", 0) or 0))
                sums.append(float(el.get("jamLengthInMetersSum", 0) or 0))
                mx = float(el.get("maxJamLengthInMeters", 0) or 0)
                per_iv[b] = max(per_iv.get(b, 0.0), mx)
                gmax = max(gmax, mx)
                n += 1
        el.clear()
    return dict(queue_mean_m=(sum(means) / n if n else 0.0),
                queue_max_m=(sum(per_iv.values()) / len(per_iv) if per_iv else 0.0),
                queue_max_global_m=gmax,
                queue_sum_raw=(sum(sums) / n if n else 0.0),
                n_e2_intervals=n)


def parse_summary_window(path):
    """cumulative counters at WARM and at END -> window-local arrivals."""
    a0 = i0 = l0 = t0 = None
    a1 = i1 = l1 = t1 = None
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "step":
            t = float(el.get("time"))
            if a0 is None and t >= WARM - 1e-6:
                a0 = float(el.get("ended", el.get("arrived", 0)))
                i0 = float(el.get("inserted", 0))
                l0 = float(el.get("loaded", 0))
                t0 = float(el.get("teleports", 0) or 0)
            a1 = float(el.get("ended", el.get("arrived", 0)))
            i1 = float(el.get("inserted", 0))
            l1 = float(el.get("loaded", 0))
            t1 = float(el.get("teleports", 0) or 0)
            running = float(el.get("running", 0))
            coll = float(el.get("collisions", 0) or 0)
        el.clear()
    return dict(arrived=(a1 - a0), inserted=(i1 - i0), loaded=(l1 - l0),
                teleports=(t1 - t0), arrived_total=a1, loaded_total=l1,
                inserted_total=i1, teleports_total=t1, running_end=running,
                collisions=coll, not_inserted=(l1 - i1))


# ------------------------------------------------------------- one run ------
def _one(job):
    tag, regime, p, seed, keepdir = job
    root = keepdir or tempfile.mkdtemp(prefix="gsa_", dir="/tmp")
    try:
        os.makedirs(root, exist_ok=True)
        vt = write_vtypes(os.path.join(root, "vtypes.add.xml"), p)
        net = sumolib.net.readNet(NET)
        plan = make_plan(p)
        tls = plan.write_add(net, os.path.join(root, "tls.add.xml"))
        ed = os.path.join(root, "edge.out.xml")
        em = os.path.join(root, "emi.out.xml")
        e2o = os.path.join(root, "e2.out.xml")
        md = write_meandata(os.path.join(root, "md.add.xml"), ed, em)
        e2a, ne2 = write_e2(net, os.path.join(root, "e2.add.xml"), e2o)
        routes = os.path.join(SCN, "routes_%s.rou.xml" % regime)
        sm = os.path.join(root, "summary.xml")
        st = os.path.join(root, "stats.xml")
        cmd = [SUMO, "-n", NET, "-r", routes,
               "-a", ",".join([vt, tls, md, e2a]),
               "--begin", "0", "--end", "%.1f" % END,
               "--seed", str(seed), "--no-step-log", "true",
               "--time-to-teleport", "300",
               "--scale", "%.6f" % p["demandScale"],
               "--summary-output", sm, "--statistic-output", st,
               "--duration-log.statistics", "true",
               "--xml-validation", "never", "--no-warnings", "true",
               "--device.emissions.probability", "1.0"]
        pr = subprocess.run(cmd, capture_output=True, text=True, cwd=root)
        open(os.path.join(root, "stderr.log"), "w").write(pr.stderr)
        if pr.returncode != 0:
            return tag, dict(ok=False, err=pr.stderr[-1500:])
        E = parse_edgedata(ed); M = parse_emissions(em)
        Q = parse_e2(e2o); S = parse_summary_window(sm)
        vkm = E["veh_m"] / 1000.0
        r = dict(ok=True,
                 arrived=S["arrived"],
                 arrived_total=S["arrived_total"],
                 loaded_total=S["loaded_total"],
                 inserted_total=S["inserted_total"],
                 running_end=S["running_end"],
                 not_inserted=S["not_inserted"],
                 collisions=S["collisions"],
                 teleports=S["teleports_total"],
                 veh_km=vkm, veh_h=E["veh_s"] / 3600.0,
                 timeloss_s=E["timeloss_s"],
                 timeloss_per_km=(E["timeloss_s"] / vkm if vkm > 0 else float("nan")),
                 waiting_s=E["waiting_s"],
                 queue_mean_m=Q["queue_mean_m"], queue_max_m=Q["queue_max_m"],
                 queue_max_global_m=Q["queue_max_global_m"],
                 queue_sum_raw=Q["queue_sum_raw"],
                 co2_kg=M["co2_mg"] / 1e6, fuel_l=M["fuel_mg"] / 1e6 / 0.74,
                 nox_g=M["nox_mg"] / 1e3,
                 mean_speed=(E["veh_m"] / E["veh_s"] if E["veh_s"] > 0 else float("nan")),
                 collision_contaminated=float(S["collisions"] > 0),
                 n_e2=ne2)
        return tag, r
    except Exception as e:
        return tag, dict(ok=False, err=repr(e))
    finally:
        if keepdir is None:
            shutil.rmtree(root, ignore_errors=True)


def key_of(regime, p, seed):
    s = regime + "|" + str(seed) + "|" + "|".join(
        "%s=%.8f" % (k, p[k]) for k in sorted(p))
    return hashlib.md5(s.encode()).hexdigest()[:16]


_CACHE = {}


def evaluate(plist, regime, seeds=(1001,), nproc=None, cache=True,
             keeproot=None):
    """plist -> list of dicts, each the CRN-MEAN over `seeds` plus per-seed reps."""
    jobs, idx = [], {}
    for i, p in enumerate(plist):
        for s in seeds:
            k = key_of(regime, p, s)
            if cache and k in _CACHE:
                continue
            if k in idx:
                continue
            idx[k] = (i, s)
            kd = None
            if keeproot:
                kd = os.path.join(keeproot, k)
            jobs.append((k, regime, p, s, kd))
    if jobs:
        with ProcessPoolExecutor(max_workers=nproc or NPROC) as ex:
            for tag, res in ex.map(_one, jobs, chunksize=1):
                _CACHE[tag] = res
    out = []
    for i, p in enumerate(plist):
        reps = [_CACHE[key_of(regime, p, s)] for s in seeds]
        ok = [r for r in reps if r.get("ok")]
        d = dict(ok=bool(ok), n_ok=len(ok), n_rep=len(reps), reps=reps)
        if ok:
            for m in ok[0]:
                if m in ("ok", "err"):
                    continue
                vs = [r[m] for r in ok]
                d[m] = sum(vs) / len(vs)
        else:
            d["err"] = reps[0].get("err", "?")
        out.append(d)
    return out
