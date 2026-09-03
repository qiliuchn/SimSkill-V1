"""Causal, online automatic-incident-detection (AID) algorithms operating strictly on the
E1 detector time series.

Every algorithm is a generator over intervals j = j0..j1-1 that, at interval j, may use ONLY
data with index <= j. Each returns a list of alarm ONSET events (t_end_of_interval, loc_idx),
where loc_idx indexes into the station subset (for pair-based algorithms it is the UPSTREAM
station of the pair).
"""
import numpy as np

EPS = 1e-6


# --------------------------------------------------------------------------- California #8
def california8(occ, j0, j1, T1=8.0, T2=0.25, T3=0.20, T4=20.0, persist=2):
    """Payne/Tignor California algorithm #8 on adjacent station pairs.

    occ : (n_stations, n_intervals) station-aggregated occupancy (%), stations ordered
          upstream -> downstream.
      OCCDF   = OCC(up,t) - OCC(dn,t)                        spatial difference
      OCCRDF  = [OCC(up,t) - OCC(dn,t)] / OCC(up,t)          relative spatial difference
      DOCCTD  = [OCC(dn,t-2) - OCC(dn,t)] / OCC(dn,t-2)      relative temporal difference
    #8's extra test -- OCC(dn,t) < T4 -- is the compression-wave discriminator: a bulk
    queue moving through raises BOTH stations' occupancy, so a genuine lane blockage is
    distinguished by the downstream station staying uncongested while the upstream one fills.
    State machine: 0 free -> 1 tentative -> 2 alarm after `persist` consecutive confirmations.
    """
    n = occ.shape[0]
    events = []
    state = np.zeros(n - 1, dtype=int)
    cnt = np.zeros(n - 1, dtype=int)
    for j in range(j0, j1):
        for i in range(n - 1):
            up, dn = occ[i, j], occ[i + 1, j]
            dn2 = occ[i + 1, j - 2] if j - 2 >= 0 else dn
            occdf = up - dn
            occrdf = occdf / max(up, EPS)
            docctd = (dn2 - dn) / max(dn2, EPS)
            hit = (occdf >= T1) and (occrdf >= T2) and (docctd >= T3) and (dn < T4)
            if hit:
                cnt[i] += 1
                if cnt[i] >= persist and state[i] != 2:
                    state[i] = 2
                    events.append(((j + 1) * 30.0, i))
                elif cnt[i] < persist:
                    state[i] = 1
            else:
                cnt[i] = 0
                state[i] = 0
    return events


def california8b(occ, j0, j1, T1=8.0, T2=0.25, T3=0.20, T4=20.0, T5=4.0):
    """Canonical Payne/Tignor #8 TWO-STAGE state machine (fairness check on `california8`,
    whose strict per-interval conjunction could under-detect):
        0 free       -- all three tests pass -> 1 tentative
        1 tentative  -- OCC(dn) < T4 -> 2 ALARM (incident); else -> 3 (compression wave)
        2 incident   -- persists while OCCDF >= T5
        3 comp.wave  -- persists while OCCDF >= T5, never alarms
    Confirmation therefore always costs exactly one extra interval (min TTD = 2 intervals).
    """
    n = occ.shape[0]
    events = []
    state = np.zeros(n - 1, dtype=int)
    for j in range(j0, j1):
        for i in range(n - 1):
            up, dn = occ[i, j], occ[i + 1, j]
            dn2 = occ[i + 1, j - 2] if j - 2 >= 0 else dn
            occdf = up - dn
            s = state[i]
            if s == 0:
                if (occdf >= T1 and occdf / max(up, EPS) >= T2
                        and (dn2 - dn) / max(dn2, EPS) >= T3):
                    state[i] = 1
            elif s == 1:
                if dn < T4:
                    state[i] = 2
                    events.append(((j + 1) * 30.0, i))
                else:
                    state[i] = 3
            else:                       # 2 or 3
                if occdf < T5:
                    state[i] = 0
    return events


# --------------------------------------------------------------------------- SND
def snd(occ, j0, j1, T=3.5, window=10, persist=2):
    """Standard Normal Deviate, single station: SND(t) = (x_t - mu_{t-w..t-1}) / sd_{t-w..t-1}.
    Baseline statistics are computed from the trailing window only (strictly causal)."""
    n = occ.shape[0]
    events = []
    cnt = np.zeros(n, dtype=int)
    alarm = np.zeros(n, dtype=bool)
    for j in range(j0, j1):
        lo = max(0, j - window)
        hist = occ[:, lo:j]
        mu = hist.mean(axis=1)
        sd = np.maximum(hist.std(axis=1, ddof=1) if hist.shape[1] > 1 else np.ones(n), 0.5)
        z = (occ[:, j] - mu) / sd
        for i in range(n):
            if z[i] >= T:
                cnt[i] += 1
                if cnt[i] >= persist and not alarm[i]:
                    alarm[i] = True
                    events.append(((j + 1) * 30.0, i))
            else:
                cnt[i] = 0
                alarm[i] = False
    return events


# --------------------------------------------------------------------------- EWMA
def ewma(occ, j0, j1, L=3.0, lam=0.3, persist=1, warm=10):
    """EWMA change detector, single station. The in-control mean/variance are updated only
    while NOT alarming, so an ongoing incident cannot walk the baseline up to itself."""
    n = occ.shape[0]
    events = []
    mu = occ[:, :warm].mean(axis=1)
    var = np.maximum(occ[:, :warm].var(axis=1, ddof=1), 0.25)
    z = mu.copy()
    cnt = np.zeros(n, dtype=int)
    alarm = np.zeros(n, dtype=bool)
    a = 0.02   # slow baseline adaptation while in control
    for j in range(j0, j1):
        x = occ[:, j]
        z = lam * x + (1 - lam) * z
        lim = L * np.sqrt(var * lam / (2 - lam))
        for i in range(n):
            if z[i] - mu[i] >= lim[i]:
                cnt[i] += 1
                if cnt[i] >= persist and not alarm[i]:
                    alarm[i] = True
                    events.append(((j + 1) * 30.0, i))
            else:
                cnt[i] = 0
                alarm[i] = False
                mu[i] = (1 - a) * mu[i] + a * x[i]
                var[i] = max((1 - a) * var[i] + a * (x[i] - mu[i]) ** 2, 0.25)
    return events


# --------------------------------------------------------------------------- naive baselines
def fixed_occ(occ, j0, j1, T=20.0, persist=2):
    """Trivial baseline: alarm when a single station's occupancy exceeds a fixed threshold."""
    n = occ.shape[0]
    events = []
    cnt = np.zeros(n, dtype=int)
    alarm = np.zeros(n, dtype=bool)
    for j in range(j0, j1):
        for i in range(n):
            if occ[i, j] >= T:
                cnt[i] += 1
                if cnt[i] >= persist and not alarm[i]:
                    alarm[i] = True
                    events.append(((j + 1) * 30.0, i))
            else:
                cnt[i] = 0
                alarm[i] = False
    return events


def fixed_speed(spd, j0, j1, T=15.0, persist=2):
    """Second trivial baseline: alarm when a single station's space-mean speed drops below T."""
    n = spd.shape[0]
    events = []
    cnt = np.zeros(n, dtype=int)
    alarm = np.zeros(n, dtype=bool)
    s = np.nan_to_num(spd, nan=33.33)
    for j in range(j0, j1):
        for i in range(n):
            if s[i, j] <= T:
                cnt[i] += 1
                if cnt[i] >= persist and not alarm[i]:
                    alarm[i] = True
                    events.append(((j + 1) * 30.0, i))
            else:
                cnt[i] = 0
                alarm[i] = False
    return events


# --------------------------------------------------------------------------- parameter grids
def grids():
    """Threshold grids swept to trace each algorithm's DR-vs-FAR tradeoff curve."""
    g = {}
    g["california8"] = [dict(T1=t1, T2=t2, T3=t3, T4=t4, persist=p)
                        for t1 in (2, 3, 4, 5, 6, 8, 10, 12, 15, 18, 22, 27, 33)
                        for t2 in (0.15, 0.25, 0.40)
                        for t3 in (0.05, 0.15, 0.30)
                        for t4 in (20.0, 35.0)
                        for p in (1, 2, 3)]
    g["california8b"] = [dict(T1=t1, T2=t2, T3=t3, T4=t4, T5=t5)
                         for t1 in (2, 3, 4, 5, 6, 8, 10, 12, 15, 18, 22, 27, 33)
                         for t2 in (0.15, 0.25, 0.40)
                         for t3 in (0.05, 0.15, 0.30)
                         for t4 in (20.0, 35.0)
                         for t5 in (2.0, 6.0)]
    g["snd"] = [dict(T=t, window=w, persist=p)
                for t in (1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0, 8.0, 10.0, 14.0, 20.0)
                for w in (6, 10, 20)
                for p in (1, 2, 3, 4)]
    g["ewma"] = [dict(L=l, lam=lm, persist=p)
                 for l in (1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 7.0, 10.0, 15.0, 22.0)
                 for lm in (0.2, 0.4, 0.7)
                 for p in (1, 2, 3, 4)]
    # naive grids deliberately extended well past the point of usefulness at low demand, so
    # that any "no feasible operating point" verdict under recurrent congestion is a genuine
    # property of the algorithm and not an artefact of a too-narrow grid
    g["fixed_occ"] = [dict(T=t, persist=p)
                      for t in (9, 10, 11, 12, 13, 14, 16, 18, 20, 24, 28, 32,
                                36, 40, 45, 50, 55, 60, 70)
                      for p in (1, 2, 3, 4, 6)]
    g["fixed_speed"] = [dict(T=t, persist=p)
                        for t in (28, 26, 24, 22, 20, 18, 16, 14, 12, 10, 8, 6, 4, 3, 2, 1)
                        for p in (1, 2, 3, 4, 6)]
    return g


ALGOS = {"california8": california8, "california8b": california8b, "snd": snd, "ewma": ewma,
         "fixed_occ": fixed_occ, "fixed_speed": fixed_speed}
PAIRWISE = {"california8", "california8b"}          # location index refers to the UPSTREAM station of a pair
SPEED_BASED = {"fixed_speed"}
