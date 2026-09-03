"""Shared definitions for the heavy-vehicle Passenger-Car-Equivalent (PCE / E_T)
measurement study.

Two testbeds
------------
A. SIGNAL  : isolated 4-way signalised intersection, 1 through lane per approach,
             300 m arms, 13.89 m/s (50 km/h).  Only the four THROUGH movements
             ever get green or demand.  Loaded far above capacity so every green
             discharges a permanently spilled-back standing queue.
             (rig + method reused from `measure-saturation-flow-and-validate-webster-method`)

B. FREEWAY : 3-lane mainline -> 1-lane bottleneck (lane drop), 33.33 m/s
             (120 km/h), loaded above the bottleneck capacity so the drop binds
             and the E1 station just downstream of the drop measures genuine
             QUEUE-DISCHARGE capacity.
             (bottleneck discipline reused from `build-macroscopic-fundamental-diagram`)

vTypes
------
`car`  is SUMO's own default passenger vType (values read back from SUMO via
TraCI in probe_defaults.py, not taken from documentation).
`truck` is SUMO's own default vClass="truck" vType, likewise read back.
All decomposition variants differ from `car` in EXACTLY ONE attribute.
sigma=0 / speedDev=0 / speedFactor=1 throughout, so the ONLY stochastic input is
which queue positions the heavy vehicles land in (controlled by our own demand
RNG seed) -- this is the variance source the replication CIs describe.
"""
import os
import subprocess
import math

SUMO_BIN = "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/bin"
SUMO = os.path.join(SUMO_BIN, "sumo")
NETCONVERT = os.path.join(SUMO_BIN, "netconvert")

EP = "/Users/liuqi/Desktop/simskill/episodic-memory/2026-08-01_09-30-00"
ATT = os.path.join(EP, "attempts/attempt-1")
WORK = os.path.join(ATT, "work")
OUT = os.path.join(EP, "outputs")
NETS = os.path.join(WORK, "nets")
for d in (WORK, OUT, NETS):
    os.makedirs(d, exist_ok=True)

# ---------------------------------------------------------------- testbed A --
SIG_SPEED = 13.89          # m/s  (50 km/h) urban approach
SIG_ARM = 300.0            # m
STEP = 0.1                 # s -- 1 s cannot resolve ~1.5-2 s saturation headways
YELLOW = 4.0
ALLRED = 0.0
SIG_NET = os.path.join(NETS, "cross.net.xml")
SIG_LANE_LEN = None        # filled in by build_networks (exact compiled length)

# 9 green durations.  The window-free green-duration regression is quantisation-
# limited when the fleet is deterministic (sigma=0): vehicles-per-cycle is an
# INTEGER, so a 4-point fit over a 24 s green span can be off by ~6% in slope.
# A denser, wider grid samples the integer staircase well enough to be usable as
# a secondary cross-check.  The PRIMARY signal estimator is now the asymptotic
# discharge headway (continuous-valued) -- see analyze.py.
GREENS = [16.0, 20.0, 24.0, 28.0, 32.0, 36.0, 40.0, 44.0, 48.0]
G_EW = 30.0
SIG_TEND = 2600.0
SIG_WARMUP = 600.0
# ~1.7x the average per-approach throughput: enough to keep the 292.8 m lane
# permanently spilled back, but NOT so much that the insertion backlog explodes.
# max-depart-delay is deliberately NOT set (default = wait forever, FIFO), because
# discarding un-insertable vehicles removes HEAVY vehicles preferentially (they
# need a bigger insertion gap) and silently biases the realised truck share DOWN
# -- measured 10.9% realised at a nominal 20% in a pilot run.
SIG_DEMAND = 2000.0

# ---------------------------------------------------------------- testbed B --
FWY_SPEED = 33.33          # m/s (120 km/h)
FWY_NLANES = 3
FWY_TEND = 3600.0
FWY_WARMUP = 900.0
FWY_DEMAND = 4800.0        # veh/h total over 3 lanes, >> 1-lane capacity (~2900)
DET_POS = 600.0            # m into the 1-lane bottleneck edge
GRADES = [0.0, 2.0, 4.0, 6.0]

SEEDS = [11, 23, 37]       # demand-composition replication seeds (CRN across arms)

# ------------------------------------------------------------------ vTypes ---
# SUMO's own defaults, verified by TraCI read-back (work/probe/probe_defaults.json)
CAR = dict(vClass="passenger", length=5.0, minGap=2.5, accel=2.6, decel=4.5,
           tau=1.0, maxSpeed=55.56)
TRUCK_DEFAULT = dict(vClass="truck", length=7.1, minGap=2.5, accel=1.3, decel=4.0,
                     tau=1.0, maxSpeed=36.11)

def _var(**kw):
    d = dict(CAR)
    d["vClass"] = "truck"          # a heavy vehicle by class in every variant
    d.update(kw)
    return d

# single-parameter decomposition variants -- each differs from `car` in ONE
# attribute only (vClass is held at "truck" for all of them, which has no
# dynamic effect here because no lane restricts vClass).
HV_VARIANTS = {
    "hv_full":     dict(TRUCK_DEFAULT),                 # SUMO default truck (all at once)
    "hv_len":      _var(length=7.1),                    # truck LENGTH only
    "hv_accel":    _var(accel=1.3),                     # truck ACCEL only
    "hv_decel":    _var(decel=4.0),                     # truck DECEL only
    "hv_vmax130":  _var(maxSpeed=36.11),                # truck default maxSpeed only
    "hv_vmax90":   _var(maxSpeed=25.0),                 # governed 90 km/h HGV, maxSpeed only
    "hv_tau14":    _var(tau=1.4),                       # larger time gap only
}


def vtype_xml(vid, attrs, net_speed):
    a = dict(attrs)
    a["maxSpeed"] = min(a["maxSpeed"], 1e9)
    s = " ".join('%s="%s"' % (k, v) for k, v in a.items())
    return ('    <vType id="%s" carFollowModel="Krauss" sigma="0" speedDev="0" '
            'speedFactor="1" %s/>\n' % (vid, s))


# ------------------------------------------------------------------ helpers --
def run_sumo(args, label="", cwd=None):
    p = subprocess.run([SUMO] + args, capture_output=True, text=True, cwd=cwd)
    if p.returncode != 0:
        raise RuntimeError("SUMO failed (%s)\nCMD: %s\nSTDERR:\n%s"
                           % (label, " ".join([SUMO] + args), p.stderr[-4000:]))
    return p.stdout, p.stderr


def ols(xs, ys):
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    b = sxy / sxx
    a = my - b * mx
    ssr = sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys))
    sst = sum((y - my) ** 2 for y in ys)
    r2 = 1 - ssr / sst if sst > 0 else float("nan")
    return a, b, r2


# t_{n-1, .975}
_TCRIT = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447,
          7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228, 14: 2.145, 19: 2.093,
          29: 2.045}


def tcrit(df):
    if df <= 0:
        return float("nan")
    ks = sorted(_TCRIT)
    for k in ks:
        if df <= k:
            return _TCRIT[k]
    return 1.96


def mean_ci(vals):
    """mean, sd, 95% t-CI half-width, n"""
    n = len(vals)
    if n == 0:
        return None, None, None, 0
    m = sum(vals) / n
    if n == 1:
        return m, 0.0, 0.0, 1
    sd = math.sqrt(sum((v - m) ** 2 for v in vals) / (n - 1))
    hw = tcrit(n - 1) * sd / math.sqrt(n)
    return m, sd, hw, n


def et_from_capacity_ratio(c_mix, c_car, p):
    """HCM heavy-vehicle adjustment factor inverted for E_T.

        f_HV = C_mix / C_car   (capacity ratio, mixed vs pure-car)
        f_HV = 1 / (1 + p*(E_T - 1))     =>   E_T = 1 + (1/f_HV - 1)/p
    """
    if p <= 0:
        return None
    f_hv = c_mix / c_car
    return 1.0 + (1.0 / f_hv - 1.0) / p


def theoretical_lane_capacity(v, attrs):
    """v_free / (v_free*tau + length + minGap) * 3600 -- single-lane bound."""
    return v / (v * attrs["tau"] + attrs["length"] + attrs["minGap"]) * 3600.0
