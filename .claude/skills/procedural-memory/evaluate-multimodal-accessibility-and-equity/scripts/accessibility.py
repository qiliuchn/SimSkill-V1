#!/usr/bin/env python3
"""Cumulative-opportunity and gravity accessibility from the skims.

beta is CALIBRATED per mode by bisection so that the gravity model's mean trip
time reproduces the mean trip time actually observed in the simulation:
  * car: mean (duration + departDelay) of the od2trips demand vehicles, restricted
    to INTERZONAL trips (each vehicle's OD zone recovered from the first/last edge
    of its route), weighted in the model by car-owning population P_i*c_i;
  * transit: mean realised <personinfo> door-to-door duration of the intermodal
    probe set weighted by the assumed transit trip table Q_pt = OD*(1-c_i)/c_i,
    weighted in the model by carless population P_i*(1-c_i).
Model and observation use the SAME support (interzonal, finite-impedance pairs).

Intrazonal impedance uses the standard half-nearest-neighbour rule
T_ii = 0.5*min_{j!=i} T_ij, applied identically to every skim and scenario.
"""
import os
import sys
import json
import math
import statistics
import xml.etree.ElementTree as ET

WORK = sys.argv[1]
SCNS = ["base", "altA", "altB"]
SEEDS = ["1", "2", "3"]
THRESHOLDS = [t * 60 for t in (5, 10, 15, 20, 30, 45)]
THR_MIN = [5, 10, 15, 20, 30, 45]
INF = float("inf")

D = json.load(open(os.path.join(WORK, "demand.json")))
DEM = D["demographics"]
OD = {tuple(k.split("|")): v for k, v in D["od"].items()}
ZINFO = json.load(open(os.path.join(WORK, "zones.json")))["zones"]
ZONES = sorted(ZINFO)
E2Z = {e: z for z in ZONES for e in ZINFO[z]["edges"]}
OUTER = [z for z in ZONES if z.startswith("OUTER")]
INTERIOR = [z for z in ZONES if not z.startswith("OUTER")]
SUPPORT = [(i, j) for i in ZONES for j in ZONES if i != j]
Q_PT = {(i, j): OD[(i, j)] * (1 - DEM[i]["car_ownership"]) / DEM[i]["car_ownership"]
        for (i, j) in SUPPORT}


def dec(d):
    return {tuple(k.split("|")): (INF if v is None else v) for k, v in d.items()}


def add_intrazonal(T):
    out = dict(T)
    for z in ZONES:
        near = [T[(z, j)] for j in ZONES if j != z and T.get((z, j), INF) < INF]
        out[(z, z)] = 0.5 * min(near) if near else INF
    return out


# --------------------------------------------------------- observations
def car_od_zone_map(scn):
    rf = os.path.join(WORK, "routes_%s.rou.xml" % ("base" if scn == "altB" else scn))
    veh = {}
    for _, el in ET.iterparse(rf, events=("end",)):
        if el.tag == "vehicle":
            eds = el.find("route").get("edges").split()
            veh[el.get("id")] = (E2Z.get(eds[0]), E2Z.get(eds[-1]))
            el.clear()
    return veh


def observed_car(scn):
    veh = car_od_zone_map(scn)
    inter, intra, cells = [], [], {}
    for s in SEEDS:
        for _, el in ET.iterparse(os.path.join(WORK, "tripinfo_%s_s%s.xml" % (scn, s)),
                                  events=("end",)):
            if el.tag == "tripinfo" and el.get("id") in veh:
                o, d = veh[el.get("id")]
                t = float(el.get("duration")) + float(el.get("departDelay"))
                if o == d:
                    intra.append(t)
                else:
                    inter.append(t)
                    cells.setdefault((o, d), []).append(t)
            if el.tag in ("tripinfo", "personinfo"):
                el.clear()
    return statistics.fmean(inter), len(inter), inter, cells, \
        (statistics.fmean(intra) if intra else None), len(intra)


def observed_pt(scn, Tp):
    vals = []
    for s in SEEDS:
        for _, el in ET.iterparse(os.path.join(WORK, "tripinfo_%s_s%s.xml" % (scn, s)),
                                  events=("end",)):
            if el.tag == "personinfo" and el.get("id", "").startswith("P#"):
                if any(c.tag == "ride" for c in el):
                    vals.append(float(el.get("duration")))
            if el.tag in ("tripinfo", "personinfo"):
                el.clear()
    num = den = 0.0
    for p in SUPPORT:
        if Tp.get(p, INF) < INF:
            num += Q_PT[p] * Tp[p]
            den += Q_PT[p]
    return num / den, statistics.fmean(vals), len(vals), vals


# --------------------------------------------------------- measures
def cumulative(T, tstar, zones=None, opp=None):
    zones = zones or ZONES
    opp = opp or ZONES
    return {i: sum(DEM[j]["jobs"] for j in opp if T.get((i, j), INF) <= tstar)
            for i in zones}


def gravity(T, beta, zones=None, opp=None):
    zones = zones or ZONES
    opp = opp or ZONES
    return {i: sum(DEM[j]["jobs"] * math.exp(-beta * T[(i, j)])
                   for j in opp if T.get((i, j), INF) < INF)
            for i in zones}


def model_mean(T, beta, share):
    num = den = 0.0
    for (i, j) in SUPPORT:
        t = T.get((i, j), INF)
        if t == INF:
            continue
        w = DEM[i]["pop"] * share(i) * DEM[j]["jobs"] * math.exp(-beta * t)
        num += w * t
        den += w
    return num / den


def calibrate(T, target, share, lo=0.0, hi=0.05):
    f = lambda b: model_mean(T, b, share) - target
    if f(lo) < 0 or f(hi) > 0:
        return None, dict(model_at_lo=model_mean(T, lo, share),
                          model_at_hi=model_mean(T, hi, share), target=target,
                          bracketed=False)
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if f(mid) > 0:
            lo = mid
        else:
            hi = mid
    b = 0.5 * (lo + hi)
    return b, dict(bracketed=True, target=target, model_mean=model_mean(T, b, share))


def spearman(a, b):
    ks = sorted(set(a) & set(b))
    def rank(d):
        order = sorted(ks, key=lambda k: d[k])
        r, i = {}, 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and d[order[j + 1]] == d[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r
    ra, rb = rank(a), rank(b)
    n = len(ks)
    ma, mb = sum(ra.values()) / n, sum(rb.values()) / n
    num = sum((ra[k] - ma) * (rb[k] - mb) for k in ks)
    da = math.sqrt(sum((ra[k] - ma) ** 2 for k in ks))
    db = math.sqrt(sum((rb[k] - mb) ** 2 for k in ks))
    return num / (da * db) if da and db else float("nan")


def ranks(d):
    order = sorted(d, key=lambda k: -d[k])
    return {z: i + 1 for i, z in enumerate(order)}


def wmean(vals, w):
    return sum(vals[z] * w[z] for z in vals) / sum(w[z] for z in vals)


POP = {z: DEM[z]["pop"] for z in ZONES}

# --------------------------------------------------------- main
RES = {}
for scn in SCNS:
    SK = json.load(open(os.path.join(WORK, "skims_%s.json" % scn)))
    Tc = add_intrazonal(dec(SK["T_car_cong"]))
    Tf = add_intrazonal(dec(SK["T_car_ff"]))
    Tp = add_intrazonal(dec(SK["T_pt"]))

    oc, n_oc, oc_vals, cells, intra_obs, n_intra = observed_car(scn)
    op_w, op_u, n_op, op_vals = observed_pt(scn, Tp)
    b_car, fit_car = calibrate(Tc, oc, lambda i: DEM[i]["car_ownership"])
    b_ff, fit_ff = calibrate(Tf, oc, lambda i: DEM[i]["car_ownership"])
    b_pt, fit_pt = calibrate(Tp, op_w, lambda i: 1 - DEM[i]["car_ownership"])

    unroutable = {}
    for m, T in (("car_cong", Tc), ("car_ff", Tf), ("pt", Tp)):
        unroutable[m] = {i: sum(1 for j in ZONES if i != j and T.get((i, j), INF) == INF)
                         for i in ZONES}

    A = {}
    for mode, T, beta in (("car", Tc, b_car), ("carff", Tf, b_ff or b_car),
                          ("pt", Tp, b_pt)):
        for ts in THRESHOLDS:
            A["cum_%s_%d" % (mode, ts // 60)] = cumulative(T, ts)
        if beta is not None:
            A["grav_%s" % mode] = gravity(T, beta)
            A["grav_%s_halfbeta" % mode] = gravity(T, beta / 2)
            A["grav_%s_2beta" % mode] = gravity(T, beta * 2)
    A["grav_carff_fixedbeta"] = gravity(Tf, b_car)      # same beta, only skim changes
    A["grav_pt_carbeta"] = gravity(Tp, b_car)           # like-for-like mode comparison
    for ts in THRESHOLDS:
        A["cum_car_%d_trunc" % (ts // 60)] = cumulative(Tc, ts, INTERIOR, INTERIOR)
        A["cum_pt_%d_trunc" % (ts // 60)] = cumulative(Tp, ts, INTERIOR, INTERIOR)
    A["saturation"] = {"cum_%s_%d" % (m, t): (max(A["cum_%s_%d" % (m, t)].values())
                                              == min(A["cum_%s_%d" % (m, t)].values()))
                       for m in ("car", "pt") for t in THR_MIN}
    A["grav_car_trunc"] = gravity(Tc, b_car, INTERIOR, INTERIOR)
    A["grav_pt_trunc"] = gravity(Tp, b_pt, INTERIOR, INTERIOR)

    # PT decomposition aggregated to origin zone (population-weighted over dest)
    PTD = SK["pt_decomp"]
    dz = {}
    for k, v in PTD.items():
        i, j = k.split("|")
        d = dz.setdefault(i, dict(access=0., wait=0., invehicle=0., transfer=0.,
                                  egress=0., n=0, n_rides=0.))
        for f in ("access", "wait", "invehicle", "transfer", "egress"):
            d[f] += v[f]
        d["n_rides"] += v["n_rides"]
        d["n"] += 1
    for i, d in dz.items():
        n = d["n"]
        for f in ("access", "wait", "invehicle", "transfer", "egress", "n_rides"):
            d[f] /= n

    RES[scn] = dict(
        observed_car_interzonal_mean_s=oc, n_car_interzonal=n_oc,
        observed_car_intrazonal_mean_s=intra_obs, n_car_intrazonal=n_intra,
        observed_pt_Qweighted_mean_s=op_w, observed_pt_unweighted_mean_s=op_u,
        n_pt_records=n_op,
        beta_car_per_s=b_car, beta_car_per_min=b_car * 60 if b_car else None,
        beta_carff_per_s=b_ff, beta_carff_per_min=b_ff * 60 if b_ff else None,
        beta_pt_per_s=b_pt, beta_pt_per_min=b_pt * 60 if b_pt else None,
        fit_car=fit_car, fit_carff=fit_ff, fit_pt=fit_pt,
        car_obs_deciles=[round(q, 1) for q in statistics.quantiles(oc_vals, n=10)],
        pt_obs_deciles=[round(q, 1) for q in statistics.quantiles(op_vals, n=10)],
        unroutable=unroutable, A=A, pt_decomp_by_origin=dz,
        observed_car_od_cells={"%s|%s" % k: [round(statistics.fmean(v), 1), len(v)]
                               for k, v in cells.items()},
        intrazonal_used={z: Tc[(z, z)] for z in ZONES},
    )

# --- scenario comparison must hold the MEASURE fixed: recompute gravity for every
# --- scenario at the BASE-calibrated beta (a re-calibrated beta changes the
# --- definition of the index and makes base/A/B non-comparable)
B_CAR0 = RES["base"]["beta_car_per_s"]
B_PT0 = RES["base"]["beta_pt_per_s"]
for scn in SCNS:
    SK = json.load(open(os.path.join(WORK, "skims_%s.json" % scn)))
    Tc = add_intrazonal(dec(SK["T_car_cong"]))
    Tf = add_intrazonal(dec(SK["T_car_ff"]))
    Tp = add_intrazonal(dec(SK["T_pt"]))
    RES[scn]["A"]["grav_car_basebeta"] = gravity(Tc, B_CAR0)
    RES[scn]["A"]["grav_carff_basebeta"] = gravity(Tf, B_CAR0)
    RES[scn]["A"]["grav_pt_basebeta"] = gravity(Tp, B_PT0)
    RES[scn]["A"]["grav_pt_carbeta_basebeta"] = gravity(Tp, B_CAR0)

# modelled trip-time deciles for the fit display (base only)
SKb = json.load(open(os.path.join(WORK, "skims_base.json")))
Tcb = add_intrazonal(dec(SKb["T_car_cong"]))
Tpb = add_intrazonal(dec(SKb["T_pt"]))


def model_deciles(T, beta, share):
    w = []
    for (i, j) in SUPPORT:
        t = T.get((i, j), INF)
        if t == INF:
            continue
        w.append((t, DEM[i]["pop"] * share(i) * DEM[j]["jobs"] * math.exp(-beta * t)))
    w.sort()
    tot = sum(x for _, x in w)
    out, acc, k = [], 0.0, 1
    for t, x in w:
        acc += x
        while k <= 9 and acc >= k / 10.0 * tot:
            out.append(round(t, 1)); k += 1
    return out


RES["base"]["car_model_deciles"] = model_deciles(Tcb, RES["base"]["beta_car_per_s"],
                                                 lambda i: DEM[i]["car_ownership"])
RES["base"]["pt_model_deciles"] = model_deciles(Tpb, RES["base"]["beta_pt_per_s"],
                                                lambda i: 1 - DEM[i]["car_ownership"])

# --------------------------------------------------------- sensitivities
b = RES["base"]["A"]
sens = dict(threshold_spearman={}, beta_spearman={},
            cum30_vs_gravity_car=spearman(b["cum_car_30"], b["grav_car"]),
            cum30_vs_gravity_pt=spearman(b["cum_pt_30"], b["grav_pt"]))
for m in ("car", "pt"):
    for a_, b_ in ((5, 10), (10, 15), (15, 20), (15, 30), (15, 45), (30, 45)):
        sens["threshold_spearman"]["%s_%d_vs_%d" % (m, a_, b_)] = \
            spearman(b["cum_%s_%d" % (m, a_)], b["cum_%s_%d" % (m, b_)])
    sens["beta_spearman"]["%s_beta_vs_half" % m] = spearman(b["grav_%s" % m],
                                                            b["grav_%s_halfbeta" % m])
    sens["beta_spearman"]["%s_beta_vs_double" % m] = spearman(b["grav_%s" % m],
                                                              b["grav_%s_2beta" % m])
    # top-5 membership churn
    for var in ("halfbeta", "2beta"):
        t1 = set(sorted(b["grav_%s" % m], key=lambda z: -b["grav_%s" % m][z])[:5])
        t2 = set(sorted(b["grav_%s_%s" % (m, var)],
                        key=lambda z: -b["grav_%s_%s" % (m, var)][z])[:5])
        sens["beta_spearman"]["%s_top5_overlap_%s" % (m, var)] = len(t1 & t2)

# --------------------------------------------------------- free-flow trap
ff = {}
for scn in SCNS:
    a = RES[scn]["A"]
    o = {}
    for ts in THR_MIN:
        c, f = a["cum_car_%d" % ts], a["cum_carff_%d" % ts]
        pc, pf = wmean(c, POP), wmean(f, POP)
        rc, rf = ranks(c), ranks(f)
        o["cum%d" % ts] = dict(popw_congested=pc, popw_freeflow=pf,
                               overstatement_pct=100.0 * (pf - pc) / pc if pc else None,
                               spearman=spearman(c, f),
                               flips=sorted(((z, rc[z], rf[z]) for z in ZONES
                                             if rc[z] != rf[z]),
                                            key=lambda x: -abs(x[1] - x[2]))[:8])
    for key, fkey in (("gravity_recalibrated", "grav_carff"),
                      ("gravity_fixedbeta", "grav_carff_fixedbeta")):
        g, gf = a["grav_car"], a[fkey]
        pc, pf = wmean(g, POP), wmean(gf, POP)
        rc, rf = ranks(g), ranks(gf)
        o[key] = dict(popw_congested=pc, popw_freeflow=pf,
                      overstatement_pct=100.0 * (pf - pc) / pc,
                      spearman=spearman(g, gf),
                      flips=sorted(((z, rc[z], rf[z]) for z in ZONES if rc[z] != rf[z]),
                                   key=lambda x: -abs(x[1] - x[2]))[:8])
    ff[scn] = o

# --------------------------------------------------------- truncation
trunc = {}
for ts in THR_MIN:
    fu = {z: b["cum_car_%d" % ts][z] for z in INTERIOR}
    tr = b["cum_car_%d_trunc" % ts]
    trunc["cum_car_%d" % ts] = dict(
        mean_bias_pct=statistics.fmean([(tr[z] - fu[z]) / fu[z] * 100
                                        for z in INTERIOR if fu[z] > 0]),
        spearman=spearman(fu, tr),
        worst=sorted([(z, fu[z], tr[z], round((tr[z] - fu[z]) / fu[z] * 100, 2))
                      for z in INTERIOR if fu[z] > 0], key=lambda x: x[3])[:5])
for key, fk, tk in (("gravity_car", "grav_car", "grav_car_trunc"),
                    ("gravity_pt", "grav_pt", "grav_pt_trunc")):
    fu = {z: b[fk][z] for z in INTERIOR}
    tr = b[tk]
    trunc[key] = dict(
        mean_bias_pct=statistics.fmean([(tr[z] - fu[z]) / fu[z] * 100
                                        for z in INTERIOR if fu[z] > 0]),
        spearman=spearman(fu, tr),
        worst=sorted([(z, round(fu[z], 1), round(tr[z], 1),
                       round((tr[z] - fu[z]) / fu[z] * 100, 2))
                      for z in INTERIOR if fu[z] > 0], key=lambda x: x[3])[:5])

json.dump(dict(results=RES, sensitivity=sens, freeflow_trap=ff, truncation=trunc,
               zones=ZONES, interior=INTERIOR, thresholds_min=THR_MIN,
               Q_pt_total=sum(Q_PT.values())),
          open(os.path.join(WORK, "accessibility.json"), "w"), indent=1)

for scn in SCNS:
    r = RES[scn]
    print("%-5s car: obs %.1fs (n=%d) beta=%.4f/min fit=%s | pt: obsQw %.1fs (unw %.1f, "
          "n=%d) beta=%.4f/min fit=%s"
          % (scn, r["observed_car_interzonal_mean_s"], r["n_car_interzonal"],
             r["beta_car_per_min"], r["fit_car"]["bracketed"],
             r["observed_pt_Qweighted_mean_s"], r["observed_pt_unweighted_mean_s"],
             r["n_pt_records"], r["beta_pt_per_min"] if r["beta_pt_per_s"] else -1,
             r["fit_pt"]["bracketed"]))
print("wrote accessibility.json")
