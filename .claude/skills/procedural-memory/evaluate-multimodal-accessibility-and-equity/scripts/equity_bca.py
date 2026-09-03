#!/usr/bin/env python3
"""Equity metrics (Lorenz / Gini / Palma / carless gap), benefit-cost appraisal,
and the four hypothesis tests (H1-H4)."""
import os
import sys
import json
import csv
import math
import statistics
import xml.etree.ElementTree as ET

WORK = sys.argv[1]
SCNS = ["base", "altA", "altB"]
SEEDS = ["1", "2", "3"]
INF = float("inf")

AC = json.load(open(os.path.join(WORK, "accessibility.json")))
RES = AC["results"]
D = json.load(open(os.path.join(WORK, "demand.json")))
DEM = D["demographics"]
OD = {tuple(k.split("|")): v for k, v in D["od"].items()}
ZINFO = json.load(open(os.path.join(WORK, "zones.json")))
ZONES = AC["zones"]
POP = {z: DEM[z]["pop"] for z in ZONES}
CAR = {z: DEM[z]["car_ownership"] for z in ZONES}
LOW = [z for z in ZONES if DEM[z]["low_income"]]
Q_PT = {(i, j): OD[(i, j)] * (1 - CAR[i]) / CAR[i]
        for i in ZONES for j in ZONES if i != j}

# ---------------- stipulated appraisal parameters (provenance recorded) ----------
P = dict(
    vot_car_usd_per_h=18.00,
    vot_transit_usd_per_h=12.00,
    bus_operating_usd_per_bus_h=110.00,
    widening_usd_per_lane_km=9.0e6,
    road_maint_usd_per_lane_km_yr=60000.0,
    bus_capital_usd_per_peak_vehicle=550000.0,
    bus_life_years=15,
    peak_hours_per_year=500.0,          # 250 weekday-equivalents x 2 peak hours
    discount_rate=0.04,
    appraisal_years=30,
    car_occupancy=1.15,
)
PROV = {k: "STIPULATED placeholder (not measured, not sourced)" for k in P}
PROV["peak_hours_per_year"] = "STIPULATED convention: 250 weekday-equivalents x 2 h"


# ------------------------------------------------------------ equity primitives
def lorenz(values, weights):
    """values: dict z->accessibility, weights: dict z->population"""
    order = sorted(values, key=lambda z: values[z])
    cw = ca = 0.0
    W = sum(weights[z] for z in order)
    A = sum(weights[z] * values[z] for z in order)
    pts = [(0.0, 0.0)]
    for z in order:
        cw += weights[z]
        ca += weights[z] * values[z]
        pts.append((cw / W, ca / A))
    return pts, order


def gini(values, weights):
    pts, _ = lorenz(values, weights)
    area = 0.0
    for k in range(1, len(pts)):
        x0, y0 = pts[k - 1]
        x1, y1 = pts[k]
        area += (x1 - x0) * (y0 + y1) / 2.0
    return 1.0 - 2.0 * area


def quantile_share(values, weights, lo, hi):
    """population share [lo,hi) of the accessibility-ranked distribution:
    returns its share of total population-weighted accessibility"""
    order = sorted(values, key=lambda z: values[z])
    W = sum(weights.values())
    A = sum(weights[z] * values[z] for z in order)
    acc, cum = 0.0, 0.0
    for z in order:
        w0, w1 = cum / W, (cum + weights[z]) / W
        cum += weights[z]
        ov = max(0.0, min(w1, hi) - max(w0, lo))
        if ov > 0:
            frac = ov / (w1 - w0)
            acc += frac * weights[z] * values[z]
    return acc / A


def palma(values, weights):
    top10 = quantile_share(values, weights, 0.90, 1.0)
    bot40 = quantile_share(values, weights, 0.0, 0.40)
    return top10 / bot40 if bot40 > 0 else float("inf")


# ------------------------------------------------------------ measures per scenario
BETA0 = RES["base"]["beta_car_per_s"]
EQ = {}
for scn in SCNS:
    A = RES[scn]["A"]
    a_car = A["grav_car_basebeta"]                 # common beta -> modes comparable
    a_pt = A["grav_pt_carbeta_basebeta"]
    a_person = {z: CAR[z] * a_car[z] + (1 - CAR[z]) * a_pt[z] for z in ZONES}
    carown_w = {z: POP[z] * CAR[z] for z in ZONES}
    carless_w = {z: POP[z] * (1 - CAR[z]) for z in ZONES}
    mean_carowner = sum(carown_w[z] * a_car[z] for z in ZONES) / sum(carown_w.values())
    mean_carless = sum(carless_w[z] * a_pt[z] for z in ZONES) / sum(carless_w.values())
    EQ[scn] = dict(
        mean_pop_car=sum(POP[z] * a_car[z] for z in ZONES) / sum(POP.values()),
        mean_pop_pt=sum(POP[z] * a_pt[z] for z in ZONES) / sum(POP.values()),
        mean_pop_person=sum(POP[z] * a_person[z] for z in ZONES) / sum(POP.values()),
        gini_car=gini(a_car, POP), gini_pt=gini(a_pt, POP),
        gini_person=gini(a_person, POP),
        palma_car=palma(a_car, POP), palma_pt=palma(a_pt, POP),
        palma_person=palma(a_person, POP),
        mean_carowner=mean_carowner, mean_carless=mean_carless,
        carless_gap_abs=mean_carowner - mean_carless,
        carless_gap_ratio=mean_carowner / mean_carless,
        lorenz_person=lorenz(a_person, POP)[0],
        lorenz_car=lorenz(a_car, POP)[0],
        lorenz_pt=lorenz(a_pt, POP)[0],
        mean_lowincome_person=sum(POP[z] * a_person[z] for z in LOW) /
                              sum(POP[z] for z in LOW),
        A_person=a_person, A_car=a_car, A_pt=a_pt,
        # cumulative-opportunity based equity, as a robustness check
        gini_cum_car15=gini(A["cum_car_15"], POP),
        gini_cum_pt45=gini(A["cum_pt_45"], POP),
        palma_cum_car15=palma(A["cum_car_15"], POP),
        palma_cum_pt45=palma(A["cum_pt_45"], POP),
    )

# ------------------------------------------------------------ simulation totals
def totals(scn):
    """per-seed totals for demand vehicles and buses"""
    rf = os.path.join(WORK, "routes_%s.rou.xml" % ("base" if scn == "altB" else scn))
    demand_ids = set()
    for _, el in ET.iterparse(rf, events=("end",)):
        if el.tag == "vehicle":
            demand_ids.add(el.get("id"))
            el.clear()
    out = []
    for s in SEEDS:
        vh = bh = 0.0
        n = nb = 0
        for _, el in ET.iterparse(os.path.join(WORK, "tripinfo_%s_s%s.xml" % (scn, s)),
                                  events=("end",)):
            if el.tag == "tripinfo":
                vid = el.get("id")
                t = float(el.get("duration")) + float(el.get("departDelay"))
                if vid in demand_ids:
                    vh += t / 3600.0
                    n += 1
                elif el.get("vType") == "bus" or vid.startswith(("L1", "L3", "L7", "LC", "LF")):
                    bh += t / 3600.0
                    nb += 1
            if el.tag in ("tripinfo", "personinfo"):
                el.clear()
        out.append(dict(seed=s, veh_hours=vh, n_veh=n, bus_hours=bh, n_bus=nb))
    return out


TOT = {scn: totals(scn) for scn in SCNS}

# ------------------------------------------------------------ capital quantities
sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import sumolib  # noqa: E402
netb = sumolib.net.readNet(os.path.join(WORK, "base.net.xml"))
neta = sumolib.net.readNet(os.path.join(WORK, "altA.net.xml"))
added_lane_km = 0.0
changed = []
for e in neta.getEdges():
    if e.getID().startswith(":"):
        continue
    try:
        b = netb.getEdge(e.getID())
    except KeyError:
        continue
    d = e.getLaneNumber() - b.getLaneNumber()
    if d > 0:
        added_lane_km += d * e.getLength() / 1000.0
        changed.append((e.getID(), b.getLaneNumber(), e.getLaneNumber(),
                        round(e.getLength(), 1)))
pt = json.load(open(os.path.join(WORK, "pt_lines.json")))


def peak_fleet(scn, seed="1"):
    """max number of PT vehicles simultaneously in service, from tripinfo"""
    ev = []
    for _, el in ET.iterparse(os.path.join(WORK, "tripinfo_%s_s%s.xml" % (scn, seed)),
                              events=("end",)):
        if el.tag == "tripinfo" and el.get("vType") == "bus":
            ev.append((float(el.get("depart")), 1))
            ev.append((float(el.get("arrival")), -1))
        if el.tag in ("tripinfo", "personinfo"):
            el.clear()
    ev.sort()
    cur = mx = 0
    for _, dlt in ev:
        cur += dlt
        mx = max(mx, cur)
    return mx


FLEET = {s: peak_fleet(s) for s in SCNS}
n_bus_base = len(ET.parse(os.path.join(WORK, "base_ptvehicles.rou.xml"))
                 .getroot().findall("vehicle"))
n_bus_altB = len(ET.parse(os.path.join(WORK, "altB_ptvehicles.rou.xml"))
                 .getroot().findall("vehicle"))

# ------------------------------------------------------------ appraisal
def pv(annual, rate, years):
    return sum(annual / (1 + rate) ** t for t in range(1, years + 1))


r_, N = P["discount_rate"], P["appraisal_years"]
ann = P["peak_hours_per_year"]
res_bca = {}
for scn in ("altA", "altB"):
    d_vh = statistics.fmean([t["veh_hours"] for t in TOT["base"]]) - \
           statistics.fmean([t["veh_hours"] for t in TOT[scn]])
    per_seed_dvh = [TOT["base"][k]["veh_hours"] - TOT[scn][k]["veh_hours"]
                    for k in range(len(SEEDS))]
    car_benefit_h = d_vh * P["car_occupancy"]
    # transit user time: only OD pairs served in BOTH cases (rule-of-half omitted)
    Tb = RES["base"]["A"]  # placeholder, real skims below
    skb = json.load(open(os.path.join(WORK, "skims_base.json")))["T_pt"]
    ska = json.load(open(os.path.join(WORK, "skims_%s.json" % scn)))["T_pt"]
    pt_h = 0.0
    common = newly = lost = 0
    newly_Q = 0.0
    for k, v in skb.items():
        i, j = k.split("|")
        w = ska.get(k)
        if v is not None and w is not None:
            pt_h += Q_PT[(i, j)] * (v - w) / 3600.0
            common += 1
        elif v is None and w is not None:
            newly += 1
            newly_Q += Q_PT[(i, j)]
        elif v is not None and w is None:
            lost += 1
    d_bus_h = statistics.fmean([t["bus_hours"] for t in TOT[scn]]) - \
              statistics.fmean([t["bus_hours"] for t in TOT["base"]])

    ben_annual = (car_benefit_h * P["vot_car_usd_per_h"] +
                  pt_h * P["vot_transit_usd_per_h"]) * ann
    if scn == "altA":
        capital = added_lane_km * P["widening_usd_per_lane_km"]
        op_annual = added_lane_km * P["road_maint_usd_per_lane_km_yr"]
        fleet = 0.0
    else:
        # peak fleet requirement from concurrent bus vehicles
        capital = 0.0
        extra_peak_buses = FLEET["altB"] - FLEET["base"]
        fleet = extra_peak_buses * P["bus_capital_usd_per_peak_vehicle"]
        op_annual = d_bus_h * ann * P["bus_operating_usd_per_bus_h"]
    cost_capital = capital + fleet
    pv_ben = pv(ben_annual, r_, N)
    pv_cost = cost_capital + pv(op_annual, r_, N)
    res_bca[scn] = dict(
        delta_veh_hours_peak=d_vh, per_seed_delta_veh_hours=per_seed_dvh,
        car_person_hours_saved_peak=car_benefit_h,
        transit_person_hours_saved_peak=pt_h,
        pt_pairs_common=common, pt_pairs_newly_served=newly, pt_pairs_lost=lost,
        newly_served_transit_trips_per_peak_hour=newly_Q,
        delta_bus_hours_peak=d_bus_h,
        annual_benefit_usd=ben_annual, annual_op_cost_usd=op_annual,
        capital_usd=cost_capital, pv_benefits_usd=pv_ben, pv_costs_usd=pv_cost,
        npv_usd=pv_ben - pv_cost, bcr=pv_ben / pv_cost if pv_cost else None,
        added_lane_km=added_lane_km if scn == "altA" else 0.0,
    )

# ------------------------------------------------------------ hypotheses
def d(scn, key):
    return EQ[scn][key] - EQ["base"][key]


H = {}
H["H1"] = dict(
    statement="road project raises mean car accessibility but leaves Gini/Palma "
              "unchanged or worse; transit project raises mean less but improves Palma",
    mean_car_base=EQ["base"]["mean_pop_car"], mean_car_A=EQ["altA"]["mean_pop_car"],
    mean_car_B=EQ["altB"]["mean_pop_car"],
    d_mean_car_A_pct=100 * d("altA", "mean_pop_car") / EQ["base"]["mean_pop_car"],
    d_mean_car_B_pct=100 * d("altB", "mean_pop_car") / EQ["base"]["mean_pop_car"],
    d_mean_person_A_pct=100 * d("altA", "mean_pop_person") / EQ["base"]["mean_pop_person"],
    d_mean_person_B_pct=100 * d("altB", "mean_pop_person") / EQ["base"]["mean_pop_person"],
    gini_person=[EQ[s]["gini_person"] for s in SCNS],
    palma_person=[EQ[s]["palma_person"] for s in SCNS],
    gini_car=[EQ[s]["gini_car"] for s in SCNS],
    palma_car=[EQ[s]["palma_car"] for s in SCNS],
    carless_gap_ratio=[EQ[s]["carless_gap_ratio"] for s in SCNS],
    mean_lowincome=[EQ[s]["mean_lowincome_person"] for s in SCNS],
)
H["H2"] = dict(
    statement="BCA ranking vs equity ranking are opposite",
    npv={s: res_bca[s]["npv_usd"] for s in ("altA", "altB")},
    bcr={s: res_bca[s]["bcr"] for s in ("altA", "altB")},
    bca_rank=sorted(("altA", "altB"), key=lambda s: -res_bca[s]["npv_usd"]),
    equity_rank_by_palma=sorted(("altA", "altB"),
                                key=lambda s: EQ[s]["palma_person"]),
    equity_rank_by_lowincome=sorted(("altA", "altB"),
                                    key=lambda s: -EQ[s]["mean_lowincome_person"]),
    equity_rank_by_carless=sorted(("altA", "altB"),
                                  key=lambda s: -EQ[s]["mean_carless"]),
)
# H3: congested vs free-flow predicted gain of the road project
gA_c = sum(POP[z] * RES["altA"]["A"]["grav_car_basebeta"][z] for z in ZONES) / sum(POP.values())
gB_c = sum(POP[z] * RES["base"]["A"]["grav_car_basebeta"][z] for z in ZONES) / sum(POP.values())
gA_f = sum(POP[z] * RES["altA"]["A"]["grav_carff_basebeta"][z] for z in ZONES) / sum(POP.values())
gB_f = sum(POP[z] * RES["base"]["A"]["grav_carff_basebeta"][z] for z in ZONES) / sum(POP.values())
cum_c = {}
for t in AC["thresholds_min"]:
    ac = sum(POP[z] * RES["altA"]["A"]["cum_car_%d" % t][z] for z in ZONES) / sum(POP.values())
    bc = sum(POP[z] * RES["base"]["A"]["cum_car_%d" % t][z] for z in ZONES) / sum(POP.values())
    af = sum(POP[z] * RES["altA"]["A"]["cum_carff_%d" % t][z] for z in ZONES) / sum(POP.values())
    bf = sum(POP[z] * RES["base"]["A"]["cum_carff_%d" % t][z] for z in ZONES) / sum(POP.values())
    cum_c["cum%d" % t] = dict(congested_gain=ac - bc, freeflow_gain=af - bf,
                              congested_gain_pct=100 * (ac - bc) / bc if bc else None,
                              freeflow_gain_pct=100 * (af - bf) / bf if bf else None,
                              erosion_pct=(100 * (1 - (ac - bc) / (af - bf))
                                           if (af - bf) != 0 else None))
H["H3"] = dict(
    statement="induced congestion erodes the road project's accessibility gain",
    gravity_congested_gain=gA_c - gB_c,
    gravity_congested_gain_pct=100 * (gA_c - gB_c) / gB_c,
    gravity_freeflow_gain=gA_f - gB_f,
    gravity_freeflow_gain_pct=100 * (gA_f - gB_f) / gB_f,
    erosion_pct=100 * (1 - (gA_c - gB_c) / (gA_f - gB_f)) if (gA_f - gB_f) else None,
    cumulative=cum_c)
# H4: PT time decomposition
dec4 = {}
for scn in SCNS:
    dz = RES[scn]["pt_decomp_by_origin"]
    agg = {}
    for grp, zs in (("low_income_peripheral", LOW),
                    ("all_zones", ZONES),
                    ("core_and_inner", [z for z in ZONES
                                        if z == "CORE" or z.startswith("INNER")])):
        f = {k: statistics.fmean([dz[z][k] for z in zs if z in dz])
             for k in ("access", "wait", "invehicle", "transfer", "egress", "n_rides")}
        tot = sum(f[k] for k in ("access", "wait", "invehicle", "transfer", "egress"))
        agg[grp] = dict(seconds=f, total_s=tot,
                        shares={k: f[k] / tot for k in
                                ("access", "wait", "invehicle", "transfer", "egress")},
                        out_of_vehicle_share=(tot - f["invehicle"]) / tot)
    dec4[scn] = agg
H["H4"] = dict(statement="transfer+wait, not in-vehicle time, dominate the peripheral "
                         "transit deficit", decomposition=dec4)


# ------------------------------------------------------------ benefit incidence,
# distributional weights, switching values, equal-budget control
INCOME = {}
for z in ZONES:
    lab = DEM[z]["label"]
    INCOME[z] = {"job core": 1.00, "affluent inner ring": 1.45, "inner ring": 1.05,
                 "middle (east)": 0.90, "middle (west)": 0.75,
                 "peripheral (east)": 0.85, "peripheral low-income": 0.55}[lab]

SKIM = {s: json.load(open(os.path.join(WORK, "skims_%s.json" % s))) for s in SCNS}


def incidence(scn):
    """peak-hour user-time benefit (person-hours) by ORIGIN zone, car and transit,
    computed from the skim change x the mode-specific trip table"""
    car_b, pt_b = {z: 0.0 for z in ZONES}, {z: 0.0 for z in ZONES}
    for i in ZONES:
        for j in ZONES:
            if i == j:
                continue
            k = "%s|%s" % (i, j)
            b0, b1 = SKIM["base"]["T_car_cong"][k], SKIM[scn]["T_car_cong"][k]
            if b0 is not None and b1 is not None:
                car_b[i] += OD[(i, j)] * (b0 - b1) / 3600.0 * P["car_occupancy"]
            p0, p1 = SKIM["base"]["T_pt"][k], SKIM[scn]["T_pt"][k]
            if p0 is not None and p1 is not None:
                pt_b[i] += Q_PT[(i, j)] * (p0 - p1) / 3600.0
    return car_b, pt_b


INC = {}
for scn in ("altA", "altB"):
    cb, pb = incidence(scn)
    tot_usd = {z: cb[z] * P["vot_car_usd_per_h"] + pb[z] * P["vot_transit_usd_per_h"]
               for z in ZONES}
    T = sum(tot_usd.values())
    grp = {}
    for name, zs in (("low_income_peripheral", LOW),
                     ("affluent_inner", [z for z in ZONES if DEM[z]["affluent"]]),
                     ("core", ["CORE"]),
                     ("rest", [z for z in ZONES if not DEM[z]["low_income"]
                               and not DEM[z]["affluent"] and z != "CORE"])):
        grp[name] = dict(usd_per_peak_hour=sum(tot_usd[z] for z in zs),
                         share_of_total=sum(tot_usd[z] for z in zs) / T if T else None,
                         pop=sum(POP[z] for z in zs),
                         usd_per_capita=sum(tot_usd[z] for z in zs) /
                                        sum(POP[z] for z in zs))
    # distributionally weighted benefit, weight = (median income index)^-e
    dw = {}
    for e_ in (0.0, 0.5, 1.0, 2.0):
        wsum = sum(POP[z] for z in ZONES)
        wz = {z: INCOME[z] ** (-e_) for z in ZONES}
        norm = sum(POP[z] * wz[z] for z in ZONES) / wsum
        dw["e=%.1f" % e_] = sum(tot_usd[z] * wz[z] / norm for z in ZONES)
    INC[scn] = dict(by_zone_usd=tot_usd, by_group=grp, weighted_benefit_usd=dw,
                    car_person_h=cb, transit_person_h=pb,
                    total_car_h=sum(cb.values()), total_pt_h=sum(pb.values()))

# switching value: VOT for transit users at which A and B have equal annual benefit
cA = res_bca["altA"]["car_person_hours_saved_peak"]
pA = res_bca["altA"]["transit_person_hours_saved_peak"]
cB = res_bca["altB"]["car_person_hours_saved_peak"]
pB = res_bca["altB"]["transit_person_hours_saved_peak"]
den = pB - pA
sw_vot_pt = ((cA - cB) * P["vot_car_usd_per_h"]) / den if den else None

# equal-budget control: road unit cost that equalises PV(costs)
pvB = res_bca["altB"]["pv_costs_usd"]
maint_pv = pv(added_lane_km * P["road_maint_usd_per_lane_km_yr"], r_, N)
eq_unit = (pvB - maint_pv) / added_lane_km
res_bca["altA"]["equal_budget_unit_cost_usd_per_lane_km"] = eq_unit
res_bca["altA"]["pv_costs_at_equal_budget"] = eq_unit * added_lane_km + maint_pv
res_bca["altA"]["npv_at_equal_budget"] = (res_bca["altA"]["pv_benefits_usd"] -
                                          (eq_unit * added_lane_km + maint_pv))
res_bca["altA"]["bcr_at_equal_budget"] = (res_bca["altA"]["pv_benefits_usd"] /
                                          (eq_unit * added_lane_km + maint_pv))

# paired statistics on delta vehicle-hours (Common Random Numbers across scenarios)
def paired(dv):
    n = len(dv)
    m = statistics.fmean(dv)
    sd = statistics.stdev(dv) if n > 1 else 0.0
    se = sd / math.sqrt(n) if n > 1 else float("nan")
    return dict(n=n, mean=m, sd=sd, se=se, t=(m / se) if se else float("nan"),
                ci95=[m - 4.303 * se, m + 4.303 * se] if n == 3 else None)


PAIRED = {s: paired(res_bca[s]["per_seed_delta_veh_hours"]) for s in ("altA", "altB")}

json.dump(dict(equity=EQ, bca=res_bca, params=P, provenance=PROV, hypotheses=H,
               incidence=INC, income_index=INCOME, switching_vot_transit=sw_vot_pt,
               paired_delta_vehicle_hours=PAIRED, peak_fleet=FLEET,
               totals=TOT, added_lane_km=added_lane_km, widened_edges=changed,
               n_bus_base=n_bus_base, n_bus_altB=n_bus_altB,
               beta_used_per_min=BETA0 * 60),
          open(os.path.join(WORK, "equity_bca.json"), "w"), indent=1)

print("mean person accessibility (jobs): base %.0f  A %.0f (%+.2f%%)  B %.0f (%+.2f%%)"
      % (EQ["base"]["mean_pop_person"], EQ["altA"]["mean_pop_person"],
         H["H1"]["d_mean_person_A_pct"], EQ["altB"]["mean_pop_person"],
         H["H1"]["d_mean_person_B_pct"]))
print("Gini(person): %.4f / %.4f / %.4f    Palma: %.3f / %.3f / %.3f"
      % tuple([EQ[s]["gini_person"] for s in SCNS] + [EQ[s]["palma_person"] for s in SCNS]))
print("carless gap ratio: %.3f / %.3f / %.3f"
      % tuple(EQ[s]["carless_gap_ratio"] for s in SCNS))
print("NPV: A $%.2fM  B $%.2fM ; BCR A %.2f B %.2f"
      % (res_bca["altA"]["npv_usd"] / 1e6, res_bca["altB"]["npv_usd"] / 1e6,
         res_bca["altA"]["bcr"], res_bca["altB"]["bcr"]))
