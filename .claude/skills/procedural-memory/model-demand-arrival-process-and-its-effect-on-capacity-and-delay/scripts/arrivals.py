#!/usr/bin/env python3
"""
Arrival-process specifications: samplers + their intended (theoretical) headway CDFs.

Six specifications of the SAME hourly volume V:

  det      deterministic equidistant     headway h = 3600/V exactly            CV = 0
  poi      Poisson                       h ~ Exp(q),  q = V/3600               CV = 1
  bin      Bernoulli / binomial          one insertion attempt per 1-s slot
                                         with p = V/3600  ->  h ~ Geom(p) on
                                         {1,2,3,...} SECONDS                   CV = sqrt(1-p)
  cowan30  Cowan M3, 30 % bunched        h = D w.p. phi, else D + Exp(lam)
  cowan75  Cowan M3, 75 % bunched        lam = (1-phi)/(1/q - D)
  phf      15-min stepwise PHF profile   piecewise-Poisson, PHF = 0.85

`bin` is deliberately specified the way SUMO/randomTrips actually implements it
(`randomTrips --binomial N`, or equivalently `<flow probability="p">`): at most N
insertions per whole second.  Its intended headway law is therefore GEOMETRIC, not
exponential -- which is exactly the kind of silent spec/intent mismatch this study
is meant to expose.
"""
import math

import numpy as np

COWAN_DELTA = 1.8          # bunched (minimum) headway, s
PHF = 0.85
# 15-min volume fractions of the hour; max fraction = 1/(4*PHF) => PHF = 0.85 exactly
PHF_FRACTIONS = [0.235, 1.0 / (4 * PHF), 0.256, 0.0]
PHF_FRACTIONS[3] = 1.0 - sum(PHF_FRACTIONS[:3])

SPECS = ["det", "poi", "bin", "cowan30", "cowan75", "phf"]


# --------------------------------------------------------------------------- #
# samplers                                                                     #
# --------------------------------------------------------------------------- #
def _cowan_lambda(q, phi, delta=COWAN_DELTA):
    mean = 1.0 / q
    if mean <= delta:
        raise ValueError("Cowan M3 requires mean headway > delta (q*delta < 1)")
    return (1.0 - phi) / (mean - delta)


def sample_departs(spec, V, t0, t1, rng, warmup_end=None):
    """Return a sorted numpy array of intended departure times in [t0, t1).

    For `phf` the stepwise profile is applied over [warmup_end, t1) and the
    warm-up window [t0, warmup_end) is generated Poisson at the mean rate V.
    """
    q = V / 3600.0
    if spec == "det":
        h = 1.0 / q
        return np.arange(t0 + h, t1, h)
    if spec == "poi":
        return _poisson_stream(q, t0, t1, rng)
    if spec == "bin":
        p = q  # per 1-second slot
        slots = np.arange(math.ceil(t0), math.ceil(t1))
        hit = rng.random(len(slots)) < p
        return slots[hit].astype(float)
    if spec.startswith("cowan"):
        phi = int(spec[5:]) / 100.0
        lam = _cowan_lambda(q, phi)
        return _cowan_stream(q, phi, lam, t0, t1, rng)
    if spec == "phf":
        we = warmup_end if warmup_end is not None else t0
        out = [_poisson_stream(q, t0, we, rng)] if we > t0 else []
        span = (t1 - we) / len(PHF_FRACTIONS)
        for i, f in enumerate(PHF_FRACTIONS):
            a, b = we + i * span, we + (i + 1) * span
            qi = (V * f) / (t1 - we) * (t1 - we) / span   # veh per second in bin i
            qi = V * f / span
            out.append(_poisson_stream(qi, a, b, rng))
        return np.concatenate(out) if out else np.array([])
    raise ValueError("unknown spec " + spec)


def _poisson_stream(q, t0, t1, rng):
    if q <= 0 or t1 <= t0:
        return np.array([])
    n = int((t1 - t0) * q * 1.4) + 60
    while True:
        h = rng.exponential(1.0 / q, n)
        t = t0 + np.cumsum(h)
        if t[-1] >= t1:
            break
        n *= 2
    return t[t < t1]


def _cowan_stream(q, phi, lam, t0, t1, rng):
    n = int((t1 - t0) * q * 1.4) + 60
    while True:
        u = rng.random(n)
        h = np.where(u < phi, COWAN_DELTA,
                     COWAN_DELTA + rng.exponential(1.0 / lam, n))
        t = t0 + np.cumsum(h)
        if t[-1] >= t1:
            break
        n *= 2
    return t[t < t1]


# --------------------------------------------------------------------------- #
# intended CDFs (for the KS test) and intended moments                         #
# --------------------------------------------------------------------------- #
def intended_cdf(spec, V, window=3600.0):
    """Return f(h)->F(h), the intended headway CDF for this specification."""
    q = V / 3600.0
    if spec == "det":
        h0 = 1.0 / q
        return lambda x: (np.asarray(x, float) >= h0).astype(float)
    if spec == "poi":
        return lambda x: 1.0 - np.exp(-q * np.asarray(x, float))
    if spec == "bin":
        p = q
        # Geometric on {1,2,...}: F(x) = 1 - (1-p)^floor(x)
        return lambda x: np.where(np.asarray(x, float) < 1.0, 0.0,
                                  1.0 - (1.0 - p) ** np.floor(np.asarray(x, float)))
    if spec.startswith("cowan"):
        phi = int(spec[5:]) / 100.0
        lam = _cowan_lambda(q, phi)
        d = COWAN_DELTA
        return lambda x: np.where(np.asarray(x, float) < d, 0.0,
                                  phi + (1 - phi) * (1 - np.exp(-lam * (np.asarray(x, float) - d))))
    if spec == "phf":
        rates = [V * f / (window / len(PHF_FRACTIONS)) for f in PHF_FRACTIONS]
        w = list(PHF_FRACTIONS)  # a random headway belongs to bin i w.p. f_i

        def F(x):
            x = np.asarray(x, float)
            out = np.zeros_like(x)
            for wi, qi in zip(w, rates):
                out += wi * (1.0 - np.exp(-qi * x))
            return out
        return F
    raise ValueError(spec)


def intended_moments(spec, V, window=3600.0):
    """Analytic mean and CV of the intended headway distribution."""
    q = V / 3600.0
    if spec == "det":
        return 1.0 / q, 0.0
    if spec == "poi":
        return 1.0 / q, 1.0
    if spec == "bin":
        p = q
        return 1.0 / p, math.sqrt(1.0 - p)
    if spec.startswith("cowan"):
        phi = int(spec[5:]) / 100.0
        lam = _cowan_lambda(q, phi)
        mean = 1.0 / q
        var = ((1 - phi) * (2 - (1 - phi))) / lam ** 2
        return mean, math.sqrt(var) / mean
    if spec == "phf":
        span = window / len(PHF_FRACTIONS)
        rates = [V * f / span for f in PHF_FRACTIONS]
        w = PHF_FRACTIONS
        m1 = sum(wi / qi for wi, qi in zip(w, rates))
        m2 = sum(wi * 2.0 / qi ** 2 for wi, qi in zip(w, rates))
        var = m2 - m1 ** 2
        return m1, math.sqrt(var) / m1
    raise ValueError(spec)


if __name__ == "__main__":
    import json
    tbl = {}
    for V in (400, 800, 1200):
        for s in SPECS:
            m, cv = intended_moments(s, V)
            tbl[f"{s}@{V}"] = {"intended_mean_headway_s": round(m, 4),
                               "intended_CV": round(cv, 4)}
    print(json.dumps(tbl, indent=1))
