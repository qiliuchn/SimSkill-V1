#!/usr/bin/env python3
"""
Hypothesis testing + figures + tables for the urban-freight study.

All comparisons are seed-paired (Common Random Numbers): the reported interval is a
95% t-interval on the PER-SEED DIFFERENCE, not on two independent means.
"""
import os, sys, json, math, glob, csv, statistics as st
from collections import defaultdict
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from common import *   # noqa
import build_network as bn
import sumolib

T95 = {2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776, 6: 2.571, 7: 2.447, 8: 2.365,
       9: 2.306, 10: 2.262, 12: 2.201, 16: 2.131, 20: 2.093, 24: 2.069}


def tcrit(n):
    return T95.get(n, 1.96 if n > 30 else 2.2)


def ci(xs):
    xs = [x for x in xs if x == x]
    n = len(xs)
    if n < 2:
        return (float("nan"),) * 3
    m = st.mean(xs); sd = st.stdev(xs)
    h = tcrit(n) * sd / math.sqrt(n)
    return m, m - h, m + h


def paired(a_by_seed, b_by_seed, key):
    """b - a, per seed."""
    out = []
    for s in sorted(set(a_by_seed) & set(b_by_seed)):
        av, bv = a_by_seed[s].get(key), b_by_seed[s].get(key)
        if isinstance(av, (int, float)) and isinstance(bv, (int, float)):
            out.append(bv - av)
    return out


def pct(a_by_seed, b_by_seed, key):
    out = []
    for s in sorted(set(a_by_seed) & set(b_by_seed)):
        av, bv = a_by_seed[s].get(key), b_by_seed[s].get(key)
        if isinstance(av, (int, float)) and isinstance(bv, (int, float)) and av:
            out.append(100.0 * (bv - av) / av)
    return out


# ---------------------------------------------------------------- loading ----
def load_all():
    rows = []
    for f in glob.glob(os.path.join(RUNS, "*", "metrics.json")):
        try:
            rows.append(json.load(open(f)))
        except Exception:
            pass
    return rows


def index(rows, pred):
    return {r["seed"]: r for r in rows if pred(r)}


FIGDPI = 130
REPORT = {}


def sec(name, obj):
    REPORT[name] = obj
    return obj


# ------------------------------------------------------------------ H1 -------
def h1(rows):
    tour = index(rows, lambda r: r.get("arm", "").startswith("E1_tour"))
    trip = index(rows, lambda r: r.get("arm", "").startswith("E1_trip"))
    nof = index(rows, lambda r: "E7_nofreight" in r.get("arm", ""))
    res = {"n_seeds": len(set(tour) & set(trip))}
    for k, lab in (("frt_vkt_km", "freight VKT (km)"),
                   ("trk_vkm_local", "freight veh-km on LOCAL streets"),
                   ("hvy_vkm_local", "HEAVY veh-km on LOCAL streets"),
                   ("trk_vkm_arterial", "freight veh-km on ARTERIALS"),
                   ("car_total_timeloss_h", "total car time loss (h)"),
                   ("noise_local_dB", "mean local-street noise dB(A)"),
                   ("emis_frt_CO2_kg", "freight CO2 (kg)"),
                   ("emis_frt_NOx_kg", "freight NOx (kg)"),
                   ("frt_n", "freight vehicles"),
                   ("parcels_delivered", "parcels delivered")):
        d = paired(tour, trip, k)
        p = pct(tour, trip, k)
        m, lo, hi = ci(d)
        pm, plo, phi = ci(p)
        res[k] = dict(label=lab,
                      tour=ci([tour[s][k] for s in tour if k in tour[s]])[0],
                      trip=ci([trip[s][k] for s in trip if k in trip[s]])[0],
                      diff=m, diff_lo=lo, diff_hi=hi,
                      pct=pm, pct_lo=plo, pct_hi=phi)
    # freight-attributable car delay: each arm minus its own zero-freight control.
    #
    # CONVENTION (fixed in attempt 2).  This metric is a DIFFERENCE OF DIFFERENCES, so
    # its per-seed denominator (the tour arm's own freight-attributable delay) is small
    # and noisy; the mean of per-seed ratios is therefore unstable -- one seed alone
    # pushes it past 400% and its 95% CI straddles zero.  The HEADLINE percentage
    # quoted for this row is the RATIO OF MEANS, which is the convention every other
    # H1 row effectively uses (for VKT/CO2 the two agree to <1 point because their
    # denominators are large and stable) and the one `fig_h1` draws.  The unstable
    # mean-of-per-seed-ratios is retained and DISCLOSED below, never quoted alone.
    dt = {s: tour[s]["car_total_timeloss_h"] - nof[s]["car_total_timeloss_h"] for s in tour if s in nof}
    dp = {s: trip[s]["car_total_timeloss_h"] - nof[s]["car_total_timeloss_h"] for s in trip if s in nof}
    d = [dp[s] - dt[s] for s in sorted(set(dt) & set(dp))]
    rel = [100.0 * (dp[s] - dt[s]) / dt[s] for s in sorted(set(dt) & set(dp)) if dt[s]]
    m_tour, m_trip = st.mean(dt.values()), st.mean(dp.values())
    res["freight_attributable_car_delay_h"] = dict(
        tour=m_tour, trip=m_trip,
        diff=ci(d),
        # --- headline, used in FINDINGS.md and in fig_h1 ---
        pct_ratio_of_means=100.0 * (m_trip - m_tour) / m_tour,
        ratio_of_means=m_trip / m_tour,
        convention="ratio_of_means",
        # --- disclosed, NOT quoted as a headline (CI straddles zero) ---
        pct_mean_of_per_seed_ratios=ci(rel),
        per_seed_ratios_pct=sorted(round(x, 1) for x in rel),
        note=("per-seed ratios are unstable (small, noisy denominator); the paired "
              "DIFFERENCE +%.1f h [%.1f, %.1f] is what is statistically supported"
              % ci(d)))
    # spatial concentration: Gini of freight veh-km over local edges
    def gini(vals):
        v = sorted(x for x in vals if x >= 0)
        n = len(v); s = sum(v)
        if n == 0 or s == 0:
            return float("nan")
        return (2 * sum((i + 1) * x for i, x in enumerate(v)) / (n * s)) - (n + 1) / n
    locs = set(bn.local_edges())
    gt = [gini([v for k, v in r["_trk_vkm_by_edge"].items() if k in locs]) for r in tour.values()]
    gp = [gini([v for k, v in r["_trk_vkm_by_edge"].items() if k in locs]) for r in trip.values()]
    res["gini_local_truck_presence"] = dict(tour=ci(gt), trip=ci(gp),
                                            diff=ci([b - a for a, b in zip(gt, gp)]))
    et = [sum(1 for k, v in r["_trk_vkm_by_edge"].items() if k in locs and v > 0.01) for r in tour.values()]
    ep = [sum(1 for k, v in r["_trk_vkm_by_edge"].items() if k in locs and v > 0.01) for r in trip.values()]
    res["local_edges_with_truck_presence"] = dict(tour=ci(et), trip=ci(ep),
                                                  diff=ci([b - a for a, b in zip(et, ep)]))
    return sec("H1", res)


# ------------------------------------------------------------------ H2/H7 ----
def h2(rows):
    out = {"families": {}}
    for fam in ("strict", "hgv"):
        by_cov = {}
        for cov in (0, 25, 50, 75, 100):
            by_cov[cov] = index(rows, lambda r, f=fam, c=cov:
                                r.get("exp") == "E2" and r.get("family") == f and r.get("coverage") == c)
        base = by_cov[0]
        rec = {}
        for cov in (0, 25, 50, 75, 100):
            cur = by_cov[cov]
            if not cur:
                continue
            e = {}
            for k in ("trk_vkm_local", "trk_vkm_arterial", "trk_vkm_total", "frt_vkt_km",
                      "hvy_vkm_local", "hvy_vkm_arterial", "hvy_vkm_total",
                      "van_vkm_local", "van_vkm_total", "edge_hvyCO2_kg_local",
                      "edge_hvyCO2_kg_total", "n_van", "n_rigid", "n_semi",
                      "noise_local_dB", "noise_arterial_dB", "noise_exposure_local",
                      "emis_frt_CO2_kg", "emis_frt_NOx_kg", "emis_CO2_kg", "emis_NOx_kg",
                      "car_total_timeloss_h", "parcels_delivered", "parcels_undelivered",
                      "addresses_unservable", "tours_emitted", "tours_not_emitted",
                      "tours_completed", "tours_still_running", "teleports", "collisions",
                      "frt_total_duration_h", "edge_frtCO2_kg_local"):
                vals = [cur[s].get(k) for s in cur if isinstance(cur[s].get(k), (int, float))]
                m, lo, hi = ci(vals)
                dm, dlo, dhi = ci(paired(base, cur, k))
                pm, plo, phi = ci(pct(base, cur, k))
                e[k] = dict(mean=m, lo=lo, hi=hi, diff=dm, diff_lo=dlo, diff_hi=dhi,
                            pct=pm, pct_lo=plo, pct_hi=phi)
            rec[cov] = e
        out["families"][fam] = rec
    # exchange rate: local truck-veh-km avoided per extra total truck-veh-km
    out["exchange_rate"] = {}
    for fam, rec in out["families"].items():
        er = {}
        for cov, e in rec.items():
            if cov == 0:
                continue
            d_local = e["trk_vkm_local"]["diff"]
            d_total = e["trk_vkm_total"]["diff"]
            d_co2 = e["emis_frt_CO2_kg"]["diff"]
            er[cov] = dict(delta_local_vkm=d_local, delta_total_vkm=d_total,
                           delta_frt_CO2_kg=d_co2,
                           local_vkm_saved_per_extra_total_vkm=(-d_local / d_total) if d_total else None,
                           local_vkm_saved_per_kg_CO2=(-d_local / d_co2) if d_co2 else None,
                           parcels_undelivered=e["parcels_undelivered"]["mean"])
        out["exchange_rate"][fam] = er
    return sec("H2", out)


# ------------------------------------------------------------------ H3 -------
def h3(rows):
    out = {}
    p = os.path.join(TAB, "pce_results.json")
    if os.path.exists(p):
        out["pce_testbed"] = json.load(open(p))["table"]
        out["pce_base_sat_flow"] = json.load(open(p))["base_sat_flow"]
    # network-level: does car delay rise with coverage, at 1x and 3x freight?
    nof = index(rows, lambda r: "E7_nofreight" in r.get("arm", ""))
    for scale, exp in ((1, "E2"), (3, "E2b")):
        for fam in ("strict", "hgv"):
            key = "scale%d_%s" % (scale, fam)
            covs = sorted({r["coverage"] for r in rows
                           if r.get("exp") == exp and r.get("family") == fam})
            rec = {}
            base = index(rows, lambda r, f=fam, e=exp: r.get("exp") == e and r.get("family") == f
                         and r.get("coverage") == 0)
            for cov in covs:
                cur = index(rows, lambda r, f=fam, c=cov, e=exp:
                            r.get("exp") == e and r.get("family") == f and r.get("coverage") == c)
                if not cur:
                    continue
                attr = {s: cur[s]["car_total_timeloss_h"] - nof[s]["car_total_timeloss_h"]
                        for s in cur if s in nof}
                rec[cov] = dict(
                    car_timeloss_h=ci([cur[s]["car_total_timeloss_h"] for s in cur]),
                    car_timeloss_diff_vs_cov0=ci(paired(base, cur, "car_total_timeloss_h")),
                    car_timeloss_pct_vs_cov0=ci(pct(base, cur, "car_total_timeloss_h")),
                    freight_attributable_car_delay_h=ci(list(attr.values())),
                    trk_vkm_arterial=ci([cur[s]["trk_vkm_arterial"] for s in cur]),
                    trk_share_of_arterial_vkm=ci(
                        [100.0 * cur[s]["trk_vkm_arterial"] /
                         max(1e-9, cur[s]["car_vkt_km"]) for s in cur]),
                    car_edge_timeloss_arterial_h=ci(
                        [cur[s]["car_edge_timeloss_h_arterial"] for s in cur]),
                    teleports=ci([cur[s]["teleports"] for s in cur]))
            out[key] = rec
    return sec("H3", out)


# ------------------------------------------------------------------ H4 -------
def h4(rows):
    out = {"primary": {}, "scale": {}}
    base = index(rows, lambda r: r.get("arm", "").startswith("E3_bay100_"))
    nof = index(rows, lambda r: "E7_nofreight" in r.get("arm", ""))
    for bf in (100, 75, 50, 25, 0):
        cur = index(rows, lambda r, b=bf: r.get("arm", "").startswith("E3_bay%d_" % b))
        if not cur:
            continue
        attr = {s: cur[s]["car_total_timeloss_h"] - nof[s]["car_total_timeloss_h"]
                for s in cur if s in nof}
        nblock = ci([cur[s]["n_blocking_stops"] for s in cur])
        out["primary"][bf] = dict(
            bay_supply_pct=bf,
            deficit_pct=100 - bf,
            n_blocking_stops=nblock,
            blocking_stop_hours=ci([cur[s]["blocking_stop_seconds"] / 3600.0 for s in cur]),
            car_timeloss_h=ci([cur[s]["car_total_timeloss_h"] for s in cur]),
            freight_attributable_car_delay_h=ci(list(attr.values())),
            delay_vs_full_bay_h=ci(paired(base, cur, "car_total_timeloss_h")),
            delay_per_double_park_s=ci([3600.0 * (cur[s]["car_total_timeloss_h"] -
                                                  base[s]["car_total_timeloss_h"]) /
                                        max(1, cur[s]["n_blocking_stops"]) for s in cur if s in base]),
            frt_total_duration_h=ci([cur[s]["frt_total_duration_h"] for s in cur]),
            teleports=ci([cur[s]["teleports"] for s in cur]),
            collisions=ci([cur[s]["collisions"] for s in cur]))
    # convexity test: under a LINEAR delay-vs-deficit law, delay(50% deficit) would be
    # exactly half of delay(100% deficit).  Convex <=> delay(50) < 0.5*delay(100).
    b100 = index(rows, lambda r: r.get("arm", "").startswith("E3_bay100_"))
    b50 = index(rows, lambda r: r.get("arm", "").startswith("E3_bay50_"))
    b0 = index(rows, lambda r: r.get("arm", "").startswith("E3_bay0_"))
    if b100 and b50 and b0:
        seeds = sorted(set(b100) & set(b50) & set(b0))
        d50 = [b50[s]["car_total_timeloss_h"] - b100[s]["car_total_timeloss_h"] for s in seeds]
        d100 = [b0[s]["car_total_timeloss_h"] - b100[s]["car_total_timeloss_h"] for s in seeds]
        gap = [a - 0.5 * b for a, b in zip(d50, d100)]
        ratio = [a / b for a, b in zip(d50, d100) if b]
        out["convexity_test"] = dict(
            delay_at_50pct_deficit=ci(d50), delay_at_100pct_deficit=ci(d100),
            gap_vs_linear=ci(gap),
            ratio_d50_over_d100=ci(ratio),
            convex_if_ratio_below_0p5=True,
            n_seeds=len(seeds))
    for sc in (2, 3, 4):
        for bf in (100, 0):
            cur = index(rows, lambda r, b=bf, c=sc: r.get("arm", "") .startswith("E3b_bay%d_x%d_" % (b, c)))
            if not cur:
                continue
            out["scale"]["x%d_bay%d" % (sc, bf)] = dict(
                scale=sc, bay=bf,
                n_blocking_stops=ci([cur[s]["n_blocking_stops"] for s in cur]),
                car_timeloss_h=ci([cur[s]["car_total_timeloss_h"] for s in cur]),
                teleports=ci([cur[s]["teleports"] for s in cur]),
                tours_still_running=ci([cur[s]["tours_still_running"] for s in cur]),
                parcels_undelivered=ci([cur[s]["parcels_undelivered"] for s in cur]))
        a = index(rows, lambda r, c=sc: r.get("arm", "").startswith("E3b_bay100_x%d_" % c))
        b = index(rows, lambda r, c=sc: r.get("arm", "").startswith("E3b_bay0_x%d_" % c))
        if a and b:
            out["scale"]["x%d_delta" % sc] = dict(
                delay_h=ci(paired(a, b, "car_total_timeloss_h")),
                per_double_park_s=ci([3600.0 * (b[s]["car_total_timeloss_h"] -
                                                a[s]["car_total_timeloss_h"]) /
                                      max(1, b[s]["n_blocking_stops"])
                                      for s in sorted(set(a) & set(b))]))
    return sec("H4", out)


# ------------------------------------------------------------------ H5 -------
def h5(rows):
    out = {}
    nof = index(rows, lambda r: "E7_nofreight" in r.get("arm", ""))
    for mix in ("allvan", "van_rigid", "allrigid", "rigid_semi", "allsemi"):
        cur = index(rows, lambda r, m=mix: r.get("arm", "").startswith("E4_%s_" % m))
        if not cur:
            continue
        attr = {s: cur[s]["car_total_timeloss_h"] - nof[s]["car_total_timeloss_h"]
                for s in cur if s in nof}
        out[mix] = dict(
            n_tours=ci([cur[s]["frt_n"] for s in cur]),
            n_van=ci([cur[s].get("n_van", 0) for s in cur]),
            n_rigid=ci([cur[s].get("n_rigid", 0) for s in cur]),
            n_semi=ci([cur[s].get("n_semi", 0) for s in cur]),
            hvy_vkm_local=ci([cur[s].get("hvy_vkm_local", 0) for s in cur]),
            frt_dwell_h=ci([cur[s]["frt_total_stop_h"] for s in cur]),
            frt_vkt_km=ci([cur[s]["frt_vkt_km"] for s in cur]),
            frt_CO2_kg=ci([cur[s]["emis_frt_CO2_kg"] for s in cur]),
            frt_NOx_kg=ci([cur[s]["emis_frt_NOx_kg"] for s in cur]),
            car_timeloss_h=ci([cur[s]["car_total_timeloss_h"] for s in cur]),
            freight_attributable_car_delay_h=ci(list(attr.values())),
            blocking_stop_hours=ci([cur[s]["blocking_stop_seconds"] / 3600.0 for s in cur]),
            n_blocking_stops=ci([cur[s]["n_blocking_stops"] for s in cur]),
            parcels_delivered=ci([cur[s]["parcels_delivered"] for s in cur]),
            parcels_undelivered=ci([cur[s]["parcels_undelivered"] for s in cur]),
            noise_local_dB=ci([cur[s]["noise_local_dB"] for s in cur]),
            total_CO2_kg=ci([cur[s]["emis_CO2_kg"] for s in cur]))
    base = index(rows, lambda r: r.get("arm", "").startswith("E4_allvan_"))
    out["_vs_allvan"] = {}
    for mix in ("van_rigid", "allrigid", "rigid_semi", "allsemi"):
        cur = index(rows, lambda r, m=mix: r.get("arm", "").startswith("E4_%s_" % m))
        if cur:
            out["_vs_allvan"][mix] = {k: ci(paired(base, cur, k)) for k in
                                      ("frt_n", "frt_vkt_km", "emis_frt_CO2_kg",
                                       "emis_frt_NOx_kg", "car_total_timeloss_h",
                                       "emis_CO2_kg", "parcels_delivered",
                                       "blocking_stop_seconds", "n_blocking_stops",
                                       "frt_total_stop_h", "noise_local_dB")}
    return sec("H5", out)


# ------------------------------------------------------------------ H6 -------
def h6(rows):
    out = {}
    base = index(rows, lambda r: r.get("arm", "").startswith("E5_night0_"))
    for nf in (0, 25, 50, 75, 100):
        cur = index(rows, lambda r, n=nf: r.get("arm", "").startswith("E5_night%d_" % n))
        if not cur:
            continue
        # person-hours: car time loss + freight vehicle-hours in the network
        ph = {s: cur[s]["car_total_timeloss_h"] + cur[s]["frt_total_duration_h"] for s in cur}
        out[nf] = dict(
            night_fraction=nf / 100.0,
            car_timeloss_h=ci([cur[s]["car_total_timeloss_h"] for s in cur]),
            frt_duration_h=ci([cur[s]["frt_total_duration_h"] for s in cur]),
            person_hours=ci(list(ph.values())),
            car_timeloss_saved_h=ci(paired(cur, base, "car_total_timeloss_h")),
            noise_local_dB=ci([cur[s]["noise_local_dB"] for s in cur]),
            noise_local_night_dB=ci([cur[s].get("noise_local_night_dB", float("nan")) for s in cur]),
            noise_local_day_dB=ci([cur[s].get("noise_local_day_dB", float("nan")) for s in cur]),
            noise_local_night_weighted_dB=ci([cur[s].get("noise_local_night_weighted_dB", float("nan")) for s in cur]),
            noise_exposure_local_night=ci([cur[s].get("noise_exposure_local_night", float("nan")) for s in cur]),
            night_noise_penalty_vs_0=ci([cur[s].get("noise_local_night_dB", 0) -
                                         base[s].get("noise_local_night_dB", 0) for s in cur if s in base]),
            frt_vkt_km_=ci([cur[s]["frt_vkt_km"] for s in cur]),
            hvy_vkm_local=ci([cur[s].get("hvy_vkm_local", 0) for s in cur]),
            parcels_delivered=ci([cur[s]["parcels_delivered"] for s in cur]),
            frt_vkt_km=ci([cur[s]["frt_vkt_km"] for s in cur]),
            teleports=ci([cur[s]["teleports"] for s in cur]))
    return sec("H6", out)


# ------------------------------------------------------------------ H7 -------
def h7(rows):
    out = {"by_arm": {}}
    for fam in ("strict", "hgv"):
        for cov in (0, 25, 50, 75, 100):
            cur = index(rows, lambda r, f=fam, c=cov: r.get("exp") == "E2"
                        and r.get("family") == f and r.get("coverage") == c)
            if not cur:
                continue
            lg = []
            for s in cur:
                p = os.path.join(DEMAND, "f_%s.ledger.json" % cur[s]["arm"])
                if os.path.exists(p):
                    lg.append(json.load(open(p)))
            fails = defaultdict(list)
            for l in lg:
                c = defaultdict(int)
                for u in l["unservable"]:
                    c[u.get("reason", "?")] += 1
                for k in ("banned", "no-path", "trap"):
                    fails[k].append(c.get(k, 0))
            out["by_arm"]["%s_%d" % (fam, cov)] = dict(
                fail_banned=ci(fails["banned"]) if lg else None,
                fail_no_path=ci(fails["no-path"]) if lg else None,
                fail_trap=ci(fails["trap"]) if lg else None,
                addresses_unservable=ci([cur[s]["addresses_unservable"] for s in cur]),
                parcels_unservable=ci([sum(u["parcels"] for u in l["unservable"]) for l in lg]) if lg else None,
                tours_not_emitted=ci([cur[s]["tours_not_emitted"] for s in cur]),
                unroutable_legs=ci([len(l["unroutable_legs"]) for l in lg]) if lg else None,
                parcels_delivered=ci([cur[s]["parcels_delivered"] for s in cur]),
                parcels_undelivered=ci([cur[s]["parcels_undelivered"] for s in cur]),
                parcels_by_design=ci([cur[s]["parcels_by_design"] for s in cur]),
                tours_still_running=ci([cur[s]["tours_still_running"] for s in cur]),
                frt_n=ci([cur[s]["frt_n"] for s in cur]),
                frt_unfinished=ci([cur[s]["frt_unfinished"] for s in cur]))
    return sec("H7", out)


# ------------------------------------------------------------ validity -------
def validity(rows):
    out = {}
    groups = defaultdict(list)
    for r in rows:
        groups[r.get("arm", "").rsplit("_s", 1)[0]].append(r)
    tab = []
    for g, rs in sorted(groups.items()):
        tel = [r["teleports"] for r in rs]
        col = [r["collisions"] for r in rs]
        eb = [r.get("emergency_braking", 0) for r in rs]
        carn = st.mean([r["car_n"] for r in rs])
        carun = st.mean([r["car_unfinished"] for r in rs])
        tab.append(dict(arm_group=g, n_seeds=len(rs),
                        teleports_mean=st.mean(tel), teleports_max=max(tel),
                        teleport_share_pct=100.0 * st.mean(tel) / max(1.0, carn),
                        collisions_mean=st.mean(col), collisions_max=max(col),
                        emergency_braking_mean=st.mean(eb),
                        car_veh=carn, car_unfinished=carun,
                        car_unfinished_pct=100.0 * carun / max(1.0, carn),
                        freight_veh=st.mean([r.get("frt_n", 0) for r in rs]),
                        freight_unfinished=st.mean([r.get("frt_unfinished", 0) for r in rs]),
                        parcels_delivered=st.mean([r.get("parcels_delivered", 0) or 0 for r in rs]),
                        parcels_undelivered=st.mean([r.get("parcels_undelivered", 0) or 0 for r in rs]),
                        teleport_contaminated=bool(100.0 * st.mean(tel) / max(1.0, carn) > 2.0)))
    out["per_arm_group"] = tab
    with open(os.path.join(TAB, "validity_table.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(tab[0].keys()))
        w.writeheader()
        for t in tab:
            w.writerow(t)
    # negative control
    nf = index(rows, lambda r: "E7_nofreight" in r.get("arm", ""))
    co = index(rows, lambda r: "E7_caronly" in r.get("arm", ""))
    keys = ("car_n", "car_arrived", "car_total_timeloss_h", "car_vkt_km",
            "emis_CO2_kg", "teleports", "collisions", "noise_arterial_dB")
    ident = all(all(abs((nf[s].get(k) or 0) - (co[s].get(k) or 0)) < 1e-9 for k in keys)
                for s in sorted(set(nf) & set(co)))
    out["negative_control"] = dict(seeds=sorted(set(nf) & set(co)), identical=ident,
                                   keys_checked=list(keys),
                                   car_timeloss_h=ci([nf[s]["car_total_timeloss_h"] for s in nf]))
    return sec("VALIDITY", out)


# ------------------------------------------------------------- ledger --------
def tour_ledger(rows):
    """Deliverable (c): per-tour ledger for a representative arm set."""
    want = [("E1_tour_s1", "tour paradigm, no restriction"),
            ("E1_trip_s1", "trip shortcut, no restriction"),
            ("E2_strict75_s1", "strict ban, 75% coverage"),
            ("E2_hgv100_s1", "HGV ban, 100% coverage"),
            ("E3_bay0_s1", "zero loading bays")]
    allrows = []
    for arm, desc in want:
        p = os.path.join(RUNS, arm, "metrics.json")
        if not os.path.exists(p):
            continue
        m = json.load(open(p))
        for t in m.get("_tour_rows", []):
            allrows.append(dict(arm=arm, scenario=desc, **t))
    if allrows:
        keys = list(allrows[0].keys())
        with open(os.path.join(TAB, "tour_ledger.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            for r in allrows:
                w.writerow({k: r.get(k) for k in keys})
    return len(allrows)


# ------------------------------------------------------------- figures -------
def fig_h1(rows):
    tour = index(rows, lambda r: r.get("arm", "").startswith("E1_tour"))
    trip = index(rows, lambda r: r.get("arm", "").startswith("E1_trip"))
    nof = index(rows, lambda r: "E7_nofreight" in r.get("arm", ""))
    labs = ["freight VKT\n(km)", "freight veh-km\non local streets",
            "freight-attributable\ncar delay (h)", "local noise\ndB(A)"]
    def vals(idx):
        return [st.mean([idx[s]["frt_vkt_km"] for s in idx]),
                st.mean([idx[s]["trk_vkm_local"] for s in idx]),
                st.mean([idx[s]["car_total_timeloss_h"] - nof[s]["car_total_timeloss_h"]
                         for s in idx if s in nof]),
                st.mean([idx[s]["noise_local_dB"] for s in idx])]
    a, b = vals(tour), vals(trip)
    # per-seed paired difference on the delay panel, for the disclosed caveat
    dsd = [(trip[s]["car_total_timeloss_h"] - nof[s]["car_total_timeloss_h"]) -
           (tour[s]["car_total_timeloss_h"] - nof[s]["car_total_timeloss_h"])
           for s in sorted(set(tour) & set(trip) & set(nof))]
    dm, dlo, dhi = ci(dsd)
    fig, axes = plt.subplots(1, 4, figsize=(12, 3.8))
    for i, (ax, l, x, y) in enumerate(zip(axes, labs, a, b)):
        ax.bar(["tour", "trip\nshortcut"], [x, y], color=["#2b7bba", "#d1495b"])
        ax.set_title(l, fontsize=9)
        # every panel uses the SAME convention: ratio of the two arm means
        ax.text(1, y, " %+.0f%%" % (100 * (y - x) / x), ha="center", va="bottom", fontsize=9)
        ax.grid(axis="y", alpha=.3)
        if i == 2:
            ax.set_xlabel("paired diff %+.1f h [%.1f, %.1f]\n"
                          "(ratio unstable: per-seed CI straddles 0)" % (dm, dlo, dhi),
                          fontsize=7.5)
    fig.suptitle("H1  tour-vs-trip modelling bias (8 seeds, CRN)\n"
                 "all % labels = ratio of the two arm means", fontsize=11)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "h1_tour_vs_trip.png"), dpi=FIGDPI)
    plt.close(fig)


def fig_pareto(rows):
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    cols = {"strict": "#d1495b", "hgv": "#2b7bba"}
    for ax, xkey, xlab in ((axes[0], "trk_vkm_local",
                            "residential exposure: ALL freight veh-km on local streets"),
                           (axes[1], "hvy_vkm_local",
                            "residential exposure: HEAVY (rigid+semi) veh-km on local streets")):
      for fam in ("strict", "hgv"):
        xs, ys, ls, und = [], [], [], []
        for cov in (0, 25, 50, 75, 100):
            cur = index(rows, lambda r, f=fam, c=cov: r.get("exp") == "E2"
                        and r.get("family") == f and r.get("coverage") == c)
            if not cur:
                continue
            xs.append(st.mean([cur[s].get(xkey, 0) for s in cur]))
            ys.append(st.mean([cur[s]["emis_frt_CO2_kg"] for s in cur]))
            ls.append(cov)
            und.append(st.mean([cur[s]["parcels_undelivered"] for s in cur]))
        ax.plot(xs, ys, "o-", color=cols[fam], label={"strict": "all-freight ban",
                                                      "hgv": "HGV ban (van exempt)"}[fam])
        for x, y, l, u in zip(xs, ys, ls, und):
            ax.annotate("%d%%%s" % (l, "" if u < 1 else "\n(%.0f parcels lost)" % u),
                        (x, y), textcoords="offset points", xytext=(6, 4), fontsize=8,
                        color=cols[fam])
      ax.set_xlabel(xlab, fontsize=9)
      ax.set_ylabel("total freight CO2 (kg)")
      ax.grid(alpha=.3); ax.legend(fontsize=9)
    fig.suptitle("H2  Pareto frontier: residential exposure vs freight emissions "
                 "(labels = ban coverage of local streets)", fontsize=11)
    fig.tight_layout(); fig.savefig(os.path.join(FIG, "h2_pareto.png"), dpi=FIGDPI)
    plt.close(fig)


def fig_bay(rows):
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.2))
    xs, ys, los, his, nb = [], [], [], [], []
    base = index(rows, lambda r: r.get("arm", "").startswith("E3_bay100_"))
    for bf in (100, 75, 50, 25, 0):
        cur = index(rows, lambda r, b=bf: r.get("arm", "").startswith("E3_bay%d_" % b))
        if not cur:
            continue
        d = paired(base, cur, "car_total_timeloss_h")
        m, lo, hi = ci(d)
        xs.append(100 - bf); ys.append(m); los.append(lo); his.append(hi)
        nb.append(st.mean([cur[s]["n_blocking_stops"] for s in cur]))
    ax = axes[0]
    ax.errorbar(xs, ys, yerr=[[y - l for y, l in zip(ys, los)],
                              [h - y for y, h in zip(ys, his)]],
                fmt="o-", color="#d1495b", capsize=4)
    ax.set_xlabel("loading-bay DEFICIT (% of delivery addresses without a bay)")
    ax.set_ylabel("extra total car time loss vs full bay supply (h)")
    ax.set_title("H4  network delay vs bay deficit", fontsize=10)
    ax.grid(alpha=.3)
    if len(xs) >= 3:
        import numpy as np
        c = np.polyfit(xs, ys, 2)
        gx = np.linspace(min(xs), max(xs), 60)
        ax.plot(gx, np.polyval(c, gx), "--", color="#333", lw=1,
                label="quadratic fit: %.3g x^2 %+.3g x %+.3g" % tuple(c))
        ax.legend(fontsize=8)
    ax = axes[1]
    per = [1000 * y / n if n else 0 for y, n in zip(ys, nb)]
    ax.plot(nb, per, "s-", color="#2b7bba")
    ax.set_xlabel("number of double-parking events in the run")
    ax.set_ylabel("marginal delay per double-park (10^-3 h)")
    ax.set_title("H4  marginal cost per double-park", fontsize=10)
    ax.grid(alpha=.3)
    # third panel: escalation with freight intensity at zero bay supply
    ax = axes[2]
    sx, sy, slo, shi = [], [], [], []
    for sc, pre in ((1, "E3_bay"), (2, "E3b_bay"), (3, "E3b_bay"), (4, "E3b_bay")):
        if sc == 1:
            a = index(rows, lambda r: r.get("arm", "").startswith("E3_bay100_"))
            b = index(rows, lambda r: r.get("arm", "").startswith("E3_bay0_"))
        else:
            a = index(rows, lambda r, c=sc: r.get("arm", "").startswith("E3b_bay100_x%d_" % c))
            b = index(rows, lambda r, c=sc: r.get("arm", "").startswith("E3b_bay0_x%d_" % c))
        if not (a and b):
            continue
        seeds = sorted(set(a) & set(b))
        v = [3600.0 * (b[s2]["car_total_timeloss_h"] - a[s2]["car_total_timeloss_h"]) /
             max(1, b[s2]["n_blocking_stops"]) for s2 in seeds]
        m, lo, hi = ci(v)
        sx.append(sc); sy.append(m); slo.append(lo); shi.append(hi)
    if sx:
        ax.errorbar(sx, sy, yerr=[[a2 - b2 for a2, b2 in zip(sy, slo)],
                                  [b2 - a2 for a2, b2 in zip(sy, shi)]],
                    fmt="o-", color="#6a4c93", capsize=4)
    ax.set_xlabel("freight intensity (x baseline parcel demand)")
    ax.set_ylabel("marginal car delay per double-park (s)")
    ax.set_title("H4  cost per double-park vs freight intensity\n(zero bay supply)", fontsize=10)
    ax.grid(alpha=.3)
    fig.tight_layout(); fig.savefig(os.path.join(FIG, "h4_bay_deficit.png"), dpi=FIGDPI)
    plt.close(fig)


def fig_heat(rows):
    """(e) freight-presence heat map, restricted vs unrestricted.

    Colour scale is shared across panels and clipped at the 95th percentile of the
    pooled non-zero edge values, so one hot depot approach cannot wash out the map.
    Row 1 = all freight vehicles; row 2 = HEAVY (rigid+semi) only."""
    import numpy as np
    net = sumolib.net.readNet(os.path.join(NET, "d_strict_0.net.xml"))
    panels = [("E2_hgv0_s1", "tours, unrestricted"),
              ("E2_strict50_s1", "all-freight ban, 50% coverage"),
              ("E2_hgv100_s1", "HGV ban, 100% coverage"),
              ("E1_trip_s1", "trip shortcut, unrestricted")]
    panels = [(a, t) for a, t in panels
              if os.path.exists(os.path.join(RUNS, a, "metrics.json"))]
    rowkeys = [("_trk_vkm_by_edge", "all freight veh-km"),
               ("_hvy_vkm_by_edge", "HEAVY (rigid+semi) veh-km")]
    fig, axes = plt.subplots(len(rowkeys), len(panels),
                             figsize=(3.6 * len(panels), 3.9 * len(rowkeys)))
    axes = np.atleast_2d(axes)
    for ri, (key, rowlab) in enumerate(rowkeys):
        data = []
        pool = []
        for arm, title in panels:
            m = json.load(open(os.path.join(RUNS, arm, "metrics.json")))
            d = {k: float(v) for k, v in (m.get(key) or {}).items()}
            data.append((d, title))
            pool += [v for v in d.values() if v > 1e-6]
        vmax = float(np.percentile(pool, 95)) if pool else 1.0
        for ci_, (ax, (d, title)) in enumerate(zip(axes[ri], data)):
            for e in net.getEdges():
                if e.getID().startswith(":"):
                    continue
                xs = [q[0] for q in e.getShape()]
                ys = [q[1] for q in e.getShape()]
                v = d.get(e.getID(), 0.0)
                fr = min(1.0, v / vmax) if vmax else 0.0
                if v <= 1e-6:
                    ax.plot(xs, ys, color="#dddddd", lw=0.9, solid_capstyle="round")
                else:
                    ax.plot(xs, ys, color=plt.cm.inferno(fr), lw=1.2 + 4.0 * fr,
                            solid_capstyle="round")
            ax.set_aspect("equal"); ax.axis("off")
            if ri == 0:
                ax.set_title(title, fontsize=9)
            if ci_ == 0:
                ax.text(-0.06, 0.5, rowlab, transform=ax.transAxes, rotation=90,
                        va="center", ha="center", fontsize=9)
        sm = plt.cm.ScalarMappable(cmap="inferno", norm=plt.Normalize(0, vmax))
        fig.colorbar(sm, ax=list(axes[ri]), shrink=0.8,
                     label="veh-km on edge (clipped at p95=%.1f)" % vmax)
    fig.suptitle("(e) freight-presence heat map -- 6x6 district, seed 1", fontsize=12)
    fig.savefig(os.path.join(FIG, "e_truck_heatmap.png"), dpi=FIGDPI, bbox_inches="tight")
    plt.close(fig)


def fig_h5_h6(rows):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    ax = axes[0]
    mixes = ["allvan", "van_rigid", "allrigid", "rigid_semi", "allsemi"]
    nof = index(rows, lambda r: "E7_nofreight" in r.get("arm", ""))
    vk, dl, lbl = [], [], []
    for m in mixes:
        cur = index(rows, lambda r, mm=m: r.get("arm", "").startswith("E4_%s_" % mm))
        if not cur:
            continue
        vk.append(st.mean([cur[s]["frt_vkt_km"] for s in cur]))
        dl.append(st.mean([cur[s]["car_total_timeloss_h"] - nof[s]["car_total_timeloss_h"]
                           for s in cur if s in nof]))
        lbl.append(m)
    ax2 = ax.twinx()
    ax.bar(range(len(lbl)), vk, color="#2b7bba", alpha=.7, label="freight VKT")
    ax2.plot(range(len(lbl)), dl, "o-", color="#d1495b", label="freight-attributable car delay")
    ax.set_xticks(range(len(lbl))); ax.set_xticklabels(lbl, rotation=20, fontsize=8)
    ax.set_ylabel("freight VKT (km)"); ax2.set_ylabel("car delay attributable to freight (h)")
    ax.set_title("H5  consolidation: VKT down, delay?", fontsize=10)
    ax = axes[1]
    xs, ph, lo, hi = [], [], [], []
    for nf_ in (0, 25, 50, 75, 100):
        cur = index(rows, lambda r, n=nf_: r.get("arm", "").startswith("E5_night%d_" % n))
        if not cur:
            continue
        v = [cur[s]["car_total_timeloss_h"] + cur[s]["frt_total_duration_h"] for s in cur]
        m, l, h = ci(v)
        xs.append(nf_); ph.append(m); lo.append(l); hi.append(h)
    if xs:
        ax.errorbar(xs, ph, yerr=[[a - b for a, b in zip(ph, lo)],
                                  [b - a for a, b in zip(ph, hi)]], fmt="o-",
                    color="#457b9d", capsize=4)
    ax.set_xlabel("% of tours shifted to the night window")
    ax.set_ylabel("total person-hours (car time loss + freight veh-h)")
    ax.set_title("H6  off-peak window shifting", fontsize=10)
    ax.grid(alpha=.3)
    fig.tight_layout(); fig.savefig(os.path.join(FIG, "h5_h6.png"), dpi=FIGDPI)
    plt.close(fig)


def main():
    rows = load_all()
    print("loaded %d runs" % len(rows))
    h1(rows); h2(rows); h3(rows); h4(rows); h5(rows); h6(rows); h7(rows); validity(rows)
    n = tour_ledger(rows)
    print("tour ledger rows:", n)
    for f in (fig_h1, fig_pareto, fig_bay, fig_heat, fig_h5_h6):
        try:
            f(rows)
        except Exception as e:
            print("FIGURE FAILED", f.__name__, e)
    json.dump(REPORT, open(os.path.join(TAB, "hypothesis_results.json"), "w"),
              indent=1, default=str)
    print("wrote", os.path.join(TAB, "hypothesis_results.json"))


if __name__ == "__main__":
    main()
