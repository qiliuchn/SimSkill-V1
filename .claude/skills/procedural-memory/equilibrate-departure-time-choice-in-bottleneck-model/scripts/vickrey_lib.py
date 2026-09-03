"""
Shared library for the Vickrey morning-commute departure-time-equilibrium study in SUMO.

Everything is expressed in "seconds of travel-time equivalent" cost units, i.e. alpha == 1.0.
A monetary reading is obtained by multiplying by a value of time (see VOT_USD_PER_SEC).
"""
import os
import subprocess
import xml.etree.ElementTree as ET
import numpy as np

BASE = "/Users/liuqi/Desktop/simskill/episodic-memory/2026-07-31_19-30-00/attempts/attempt-1"
SCRIPTS = os.path.join(BASE, "scripts")
WORK = os.path.join(BASE, "work")
NET = os.environ.get("VICKREY_NET", os.path.join(WORK, "vickrey_zip.net.xml"))
NET_PRIORITY = os.path.join(WORK, "vickrey.net.xml")   # kept for the merge-type comparison
VTYPES = os.path.join(SCRIPTS, "vtypes.add.xml")

SUMO = "sumo"

# ---------------------------------------------------------------- scenario constants
N_COMMUTERS = 600
T_STAR = 3600.0            # common desired arrival time (s), "08:00"
SLOT = 20.0                # departure-slot width (s)
SLOT0 = 1600.0             # first slot start
NSLOT = 150                # slots -> window [1600, 4600)
SIM_END = 7200.0

ALPHA = 1.0                # value of travel time
BETA = 0.5                 # earliness penalty
GAMMA = 2.0                # lateness penalty

VOT_USD_PER_SEC = 18.0 / 3600.0   # $18/h value of time, for the monetary reading


def slot_starts():
    return SLOT0 + SLOT * np.arange(NSLOT)


def delta(beta=BETA, gamma=GAMMA):
    return beta * gamma / (beta + gamma)


# ---------------------------------------------------------------- demand writing
def counts_to_departs(counts, jitter=False, rng=None):
    """Turn an integer per-slot count vector into a sorted list of departure times.

    Vehicles inside a slot are spread deterministically and evenly across the slot,
    so the realised departure profile is a faithful rendering of `counts`.
    """
    starts = slot_starts()
    out = []
    for k, n in enumerate(counts):
        n = int(n)
        if n <= 0:
            continue
        # evenly spaced strictly inside the slot
        offs = (np.arange(n) + 0.5) * (SLOT / n)
        for o in offs:
            out.append((starts[k] + o, k))
    out.sort()
    return out


def write_routes(counts, path, vtype="commuter"):
    """Write one <vehicle> per commuter with an explicit depart time. Returns slot map."""
    departs = counts_to_departs(counts)
    slot_of = {}
    with open(path, "w") as f:
        f.write('<routes>\n')
        f.write('    <route id="r" edges="E0 E1 E2 E3"/>\n')
        for i, (t, k) in enumerate(departs):
            vid = "c%04d" % i
            slot_of[vid] = k
            f.write('    <vehicle id="%s" type="%s" route="r" depart="%.2f" '
                    'departLane="free" departSpeed="max"/>\n' % (vid, vtype, t))
        f.write('</routes>\n')
    return slot_of


def write_edgedata_add(path, out_xml, freq=60):
    """edgeData additional file. NOTE: SUMO resolves `file` relative to the ADDITIONAL
    file's own directory, so we always write an absolute path here."""
    with open(path, "w") as f:
        f.write('<additional>\n')
        f.write('    <edgeData id="ed" freq="%d" file="%s" excludeEmpty="false"/>\n'
                % (freq, os.path.abspath(out_xml)))
        f.write('</additional>\n')


# ---------------------------------------------------------------- running
def run_sumo(rou, tripinfo, seed=1, extra_add=None, end=SIM_END, quiet=True):
    adds = [VTYPES]
    if extra_add:
        adds += list(extra_add)
    cmd = [SUMO, "-n", NET, "-r", rou, "-a", ",".join(adds),
           "--tripinfo-output", tripinfo,
           "--begin", "0", "--end", "%.0f" % end,
           "--seed", str(seed), "--no-step-log", "--time-to-teleport", "-1",
           "--no-warnings", "true"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("sumo failed:\n" + r.stderr[-3000:])
    return r


# ---------------------------------------------------------------- parsing
def parse_tripinfo(path):
    """Returns dict vid -> record. `tt` is the FULL experienced travel time:
    in-network duration PLUS departDelay (time spent queued at the origin waiting
    to be inserted), so no experienced delay is invisible to the cost function."""
    root = ET.parse(path).getroot()
    recs = {}
    for t in root.findall("tripinfo"):
        dep = float(t.get("depart"))
        dd = float(t.get("departDelay"))
        arr = float(t.get("arrival"))
        recs[t.get("id")] = dict(
            id=t.get("id"),
            depart_actual=dep,
            depart_intended=dep - dd,
            depart_delay=dd,
            arrival=arr,
            duration=float(t.get("duration")),
            tt=(arr - (dep - dd)),
            time_loss=float(t.get("timeLoss")),
        )
    return recs


def parse_edgedata(path):
    """Returns list of (begin, end, {edge: {attr: val}})."""
    root = ET.parse(path).getroot()
    out = []
    for iv in root.findall("interval"):
        d = {}
        for e in iv.findall("edge"):
            d[e.get("id")] = {k: v for k, v in e.attrib.items()}
        out.append((float(iv.get("begin")), float(iv.get("end")), d))
    return out


# ---------------------------------------------------------------- costs
def vehicle_costs(recs, slot_of, tf_free, toll_by_slot,
                  alpha=ALPHA, beta=BETA, gamma=GAMMA, t_star=T_STAR):
    """Per-vehicle cost decomposition. toll_by_slot is an array over slots (cost units)."""
    rows = []
    for vid, r in recs.items():
        k = slot_of[vid]
        tt = r["tt"]
        q = max(0.0, tt - tf_free)                      # queueing delay
        sde = max(0.0, t_star - r["arrival"])           # schedule delay early
        sdl = max(0.0, r["arrival"] - t_star)           # schedule delay late
        toll = float(toll_by_slot[k])
        rows.append(dict(
            id=vid, slot=k, depart=r["depart_intended"], arrival=r["arrival"],
            tt=tt, depart_delay=r["depart_delay"], queue=q, sde=sde, sdl=sdl, toll=toll,
            c_time=alpha * tt, c_early=beta * sde, c_late=gamma * sdl,
            cost=alpha * tt + beta * sde + gamma * sdl + toll,
            # "excess" cost = everything above the unavoidable free-flow travel time
            excess=alpha * q + beta * sde + gamma * sdl + toll,
        ))
    return rows


def slot_stats(rows, nslot=NSLOT):
    """Per-slot mean cost / count / mean queueing delay."""
    cnt = np.zeros(nslot)
    csum = np.zeros(nslot)
    qsum = np.zeros(nslot)
    for r in rows:
        cnt[r["slot"]] += 1
        csum[r["slot"]] += r["cost"]
        qsum[r["slot"]] += r["queue"]
    mean_c = np.where(cnt > 0, csum / np.maximum(cnt, 1), np.nan)
    mean_q = np.where(cnt > 0, qsum / np.maximum(cnt, 1), np.nan)
    return cnt, mean_c, mean_q


def counterfactual_costs(cnt, mean_q, tf_free, toll_by_slot,
                         alpha=ALPHA, beta=BETA, gamma=GAMMA, t_star=T_STAR):
    """Estimated cost of a MARGINAL traveller in EVERY slot, used slots included.

    For a used slot we take the measured mean queueing delay. For an unused slot we
    interpolate the queueing-delay profile from the used slots (and use Q=0 outside
    the queued window, which is the textbook marginal-traveller argument: a lone
    traveller departing before the queue forms or after it clears meets no queue).
    Cost = alpha*(Tf + Q) + beta*SDE + gamma*SDL + toll.
    """
    starts = slot_starts()
    used = np.where(cnt > 0)[0]
    q_hat = np.zeros(NSLOT)
    if len(used) > 0:
        q_hat = np.interp(starts, starts[used], mean_q[used], left=0.0, right=0.0)
        lo, hi = starts[used[0]], starts[used[-1]]
        q_hat[(starts < lo) | (starts > hi)] = 0.0
    mid = starts + SLOT / 2.0
    arr = mid + tf_free + q_hat
    sde = np.maximum(0.0, t_star - arr)
    sdl = np.maximum(0.0, arr - t_star)
    return alpha * (tf_free + q_hat) + beta * sde + gamma * sdl + np.asarray(toll_by_slot), q_hat


# ---------------------------------------------------------------- analytic Vickrey
def vickrey_analytic(N, s, tf, alpha=ALPHA, beta=BETA, gamma=GAMMA, t_star=T_STAR):
    """Closed-form no-toll Vickrey bottleneck equilibrium."""
    d = beta * gamma / (beta + gamma)
    peak = N / s
    A = gamma / (beta + gamma) * peak      # earliness of the very first arrival
    B = beta / (beta + gamma) * peak       # lateness of the very last arrival
    t_s = t_star - tf - A                  # first departure
    t_e = t_star - tf + B                  # last departure
    excess_cost = d * peak                 # per traveller, excl. free-flow tt
    t_max_queue = d * peak / alpha         # max queueing delay
    total_queue_delay = 0.5 * N * t_max_queue
    return dict(
        delta=d, peak_len=peak, t_first_depart=t_s, t_last_depart=t_e,
        first_earliness=A, last_lateness=B,
        excess_cost_per_traveller=excess_cost,
        total_cost=excess_cost * N,
        max_queue_delay=t_max_queue,
        total_queue_delay=total_queue_delay,
        mean_queue_delay=total_queue_delay / N,
        queue_cost_share=0.5, schedule_cost_share=0.5,
        rate_early=alpha * s / (alpha - beta),
        rate_late=alpha * s / (alpha + gamma),
        frac_early=gamma / (beta + gamma),
        toll_max=d * peak,
        total_revenue=0.5 * N * d * peak,
    )


def analytic_toll_profile(N, s, tf, alpha=ALPHA, beta=BETA, gamma=GAMMA, t_star=T_STAR):
    """Optimal time-varying toll as a function of DEPARTURE slot (queue-free optimum,
    so arrival = departure + tf). Triangular: rises at rate beta, falls at rate gamma."""
    a = vickrey_analytic(N, s, tf, alpha, beta, gamma, t_star)
    mid = slot_starts() + SLOT / 2.0
    arr = mid + tf
    tau = np.where(arr <= t_star,
                   a["toll_max"] - beta * (t_star - arr),
                   a["toll_max"] - gamma * (arr - t_star))
    return np.maximum(0.0, tau), a


# ---------------------------------------------------------------- stats helpers
def mean_ci(x, conf=0.95):
    x = np.asarray(x, dtype=float)
    n = len(x)
    m = x.mean()
    if n < 2:
        return m, 0.0, (m, m)
    sd = x.std(ddof=1)
    from scipy import stats
    h = stats.t.ppf(0.5 + conf / 2.0, n - 1) * sd / np.sqrt(n)
    return m, h, (m - h, m + h)
