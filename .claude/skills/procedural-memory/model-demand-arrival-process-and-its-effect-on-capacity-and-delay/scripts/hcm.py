#!/usr/bin/env python3
"""
Analytical gap-acceptance capacity models used as the comparison basis.

1. HCM 6th Ed. Ch. 20 (TWSC) potential capacity -- assumes RANDOM (exponential)
   conflicting headways:
       c = v_c * exp(-v_c*t_c/3600) / (1 - exp(-v_c*t_f/3600))
   Minor-street THROUGH movement base values: t_c = 6.5 s, t_f = 4.0 s.

2. HCM 6th Ed. Ch. 22 (single-lane roundabout entry, single-lane circulating):
       c = 1130 * exp(-0.001 * v_c)
   which is the same gap-acceptance form with t_f = 3600/1130 = 3.186 s and
   t_c = 3.6 + t_f/2 = 5.19 s.

3. Tanner (1962) with a Cowan M3 conflicting stream -- the SAME gap-acceptance
   behaviour but with an explicitly BUNCHED conflicting headway distribution:
       lam = alpha*q / (1 - Delta*q),   alpha = free (unbunched) proportion
       c   = 3600 * alpha * q * exp(-lam*(t_c - Delta)) / (1 - exp(-lam*t_f))
   Setting Delta = 0, alpha = 1 recovers form (1) exactly.

4. Regular (deterministic, equidistant) conflicting stream -- a step function:
       n = floor((h0 - t_c)/t_f) + 1  minor vehicles per gap, 0 if h0 < t_c
       c = q * n * 3600
"""
import math

TWSC_TC, TWSC_TF = 6.5, 4.0          # HCM minor-street through movement
RAB_A, RAB_B = 1130.0, 0.001         # HCM single-lane roundabout
RAB_TF = 3600.0 / RAB_A
RAB_TC = 3.6 + RAB_TF / 2.0


def c_random(v_c, t_c, t_f):
    """HCM / Siegloch potential capacity with exponential conflicting headways."""
    if v_c <= 0:
        return 3600.0 / t_f
    q = v_c / 3600.0
    return v_c * math.exp(-q * t_c) / (1.0 - math.exp(-q * t_f))


def c_hcm_twsc(v_c, t_c=TWSC_TC, t_f=TWSC_TF):
    return c_random(v_c, t_c, t_f)


def c_hcm_roundabout(v_c):
    return RAB_A * math.exp(-RAB_B * v_c)


def c_tanner(v_c, t_c, t_f, delta, alpha):
    """Tanner/Cowan-M3 capacity: alpha = free proportion, delta = bunched headway."""
    q = v_c / 3600.0
    if q * delta >= 1.0:
        return 0.0
    lam = alpha * q / (1.0 - delta * q)
    if lam <= 0:
        return 3600.0 / t_f
    return 3600.0 * alpha * q * math.exp(-lam * max(t_c - delta, 0.0)) / (1.0 - math.exp(-lam * t_f))


def c_regular(v_c, t_c, t_f):
    """Deterministic equidistant conflicting stream."""
    if v_c <= 0:
        return 3600.0 / t_f
    h0 = 3600.0 / v_c
    if h0 < t_c:
        return 0.0
    n = math.floor((h0 - t_c) / t_f) + 1
    return v_c * n


def c_geometric(v_c, t_c, t_f, slot=1.0):
    """Bernoulli/binomial insertion: conflicting headways are GEOMETRIC on
    multiples of `slot` seconds.  Capacity by direct expectation:
        E[n per gap] = sum_k P(h = k*slot) * max(0, floor((k*slot - t_c)/t_f) + 1)
        c = (E[n] / E[h]) * 3600
    """
    q = v_c / 3600.0
    p = q * slot
    if p <= 0 or p >= 1:
        return 0.0
    en, k = 0.0, 1
    while k < 4000:
        pk = p * (1 - p) ** (k - 1)
        h = k * slot
        if h >= t_c:
            en += pk * (math.floor((h - t_c) / t_f) + 1)
        if pk < 1e-14 and k * slot > 10 * t_c:
            break
        k += 1
    return en * q * 3600.0


def cowan_params(spec, V, delta=1.8):
    """(delta, alpha) of the Cowan M3 stream this spec name encodes."""
    if spec.startswith("cowan"):
        phi = int(spec[5:]) / 100.0
        return delta, 1.0 - phi
    if spec in ("poi", "phf"):
        return 0.0, 1.0
    return None


def predict(spec, V, control):
    """Best analytical prediction for this arrival spec and control type."""
    t_c, t_f = (TWSC_TC, TWSC_TF) if control == "twsc" else (RAB_TC, RAB_TF)
    if spec == "det":
        return {"model": "regular", "c": c_regular(V, t_c, t_f)}
    if spec == "bin":
        return {"model": "geometric", "c": c_geometric(V, t_c, t_f, 1.0)}
    if spec.startswith("cowan"):
        d, a = cowan_params(spec, V)
        return {"model": "tanner_cowanM3", "c": c_tanner(V, t_c, t_f, d, a)}
    return {"model": "hcm_random", "c": c_random(V, t_c, t_f)}


if __name__ == "__main__":
    import json
    tbl = {}
    for V in (200, 400, 600, 800, 1000, 1200, 1400):
        tbl[V] = {
            "hcm_twsc_random": round(c_hcm_twsc(V), 1),
            "hcm_rab_random": round(c_hcm_roundabout(V), 1),
            "twsc_regular": round(c_regular(V, TWSC_TC, TWSC_TF), 1),
            "rab_regular": round(c_regular(V, RAB_TC, RAB_TF), 1),
            "twsc_geom": round(c_geometric(V, TWSC_TC, TWSC_TF), 1),
            "rab_geom": round(c_geometric(V, RAB_TC, RAB_TF), 1),
            "twsc_cowan30": round(c_tanner(V, TWSC_TC, TWSC_TF, 1.8, 0.7), 1),
            "twsc_cowan75": round(c_tanner(V, TWSC_TC, TWSC_TF, 1.8, 0.25), 1),
            "rab_cowan30": round(c_tanner(V, RAB_TC, RAB_TF, 1.8, 0.7), 1),
            "rab_cowan75": round(c_tanner(V, RAB_TC, RAB_TF, 1.8, 0.25), 1),
        }
    print("HCM roundabout implied t_c=%.3f t_f=%.3f" % (RAB_TC, RAB_TF))
    print(json.dumps(tbl, indent=1))
