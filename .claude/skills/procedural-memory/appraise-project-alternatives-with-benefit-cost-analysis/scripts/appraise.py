#!/usr/bin/env python3
"""
Economic appraisal (benefit-cost analysis) layer for the SUMO arterial corridor.

Turns per-run microsimulation measures into PV of benefits by component, PV of
costs, NPV, BCR, FYRR, and the INCREMENTAL BCR between the two non-base
alternatives (the correct decision rule for mutually exclusive options).

Everything monetary is driven by the PARAMS table below. Each parameter carries a
`source` string that is either a real citation or the literal word PLACEHOLDER, and
the provenance is printed and written out with the results, so an assumption can
never be mistaken for a measurement.

Inputs : a directory of per-run measures JSONs named  alt<A|B|C>_y<K>_s<SEED>.json
         (K = demand-growth exponent in years since opening)
Outputs: appraisal_summary.csv, benefit_components.csv, per_seed_npv.csv,
         sensitivity.csv, switching_values.csv, tornado.png, engineering_measures.csv
"""
import argparse
import csv
import glob
import json
import math
import os
import re
from collections import defaultdict

import numpy as np
from scipy import stats

# ---------------------------------------------------------------------------
# PARAMETERS.  `source` is either a citation or the literal string PLACEHOLDER.
# ---------------------------------------------------------------------------
PARAMS = {
    'vot_car': dict(
        value=24.01, unit='USD per vehicle-hour',
        source='CITED: Texas A&M Transportation Institute Urban Mobility Report, '
               '2024 value of travel time = $24.01 per person-hour. Applied here '
               'PER VEHICLE with occupancy assumed = 1.0, which UNDERSTATES car '
               'time benefits (real AM-peak occupancy is ~1.1-1.2).'),
    'vot_truck': dict(
        value=80.16, unit='USD per vehicle-hour',
        source='CITED: TTI Urban Mobility Report 2024 commercial-vehicle value of '
               'time = $80.16 per truck-hour (includes driver wage + cargo '
               'inventory + vehicle capital).'),
    'voc_per_km': dict(
        value=0.20, unit='USD per vehicle-km (non-fuel operating cost)',
        source='PLACEHOLDER: illustrative order-of-magnitude value for non-fuel '
               'running costs (tyres, maintenance, depreciation). Not taken from '
               'an authoritative schedule in this run.'),
    'fuel_price': dict(
        value=1.00, unit='USD per litre',
        source='PLACEHOLDER: illustrative pump price net of tax. Not sourced.'),
    'scc_co2': dict(
        value=190.0, unit='USD per tonne CO2',
        source='CITED: US EPA (2023) Report on the Social Cost of Greenhouse Gases, '
               'SC-CO2 = $190/metric ton for a 2020 emission at a 2.0% near-term '
               'Ramsey discount rate (2020 USD). '
               'https://www.epa.gov/system/files/documents/2023-12/epa_scghg_2023_report_final.pdf'),
    'cost_nox': dict(
        value=14700.0, unit='USD per tonne NOx',
        source='CITED BUT TRANSFERRED ACROSS SECTORS: US EPA sector-based '
               'benefit-per-ton estimates (2016 USD, 2% discount rate); the '
               '$14,700/ton NOx figure is the CEMENT KILN sector value. No '
               'on-road mobile-source value was retrieved, so this is a sector '
               'transfer and the true mobile-source value (urban, near-roadway '
               'exposure) is plausibly HIGHER. https://epa.gov/benmap/'
               'sector-based-pm25-and-ozone-benefit-ton-estimates'),
    'cost_pm': dict(
        value=158000.0, unit='USD per tonne PM',
        source='CITED BUT TRANSFERRED AND UNIT-MISMATCHED: EPA sector-based '
               'benefit-per-ton, cement-kiln directly-emitted PM2.5 = $158,000/ton '
               '(2016 USD). Two caveats: (a) sector transfer as above; (b) SUMO/'
               'HBEFA3 reports PMx (total exhaust PM), NOT PM2.5, so applying a '
               'PM2.5 damage cost to a PMx mass slightly OVERSTATES this term.'),
    'crash_cost': dict(
        value=150000.0, unit='USD per crash (severity-weighted average)',
        source='PLACEHOLDER: illustrative KABCO-weighted average cost of a '
               'reported urban-arterial crash. Not sourced in this run.'),
    'base_crashes_per_year': dict(
        value=18.0, unit='reported crashes per year on the whole corridor',
        source='PLACEHOLDER (stated assumption): 18 reported crashes/yr across the '
               'five signalised intersections, i.e. ~3.6 per intersection-year, a '
               'plausible order of magnitude for urban signalised intersections. '
               'This is NOT observed data for any real corridor.'),
    'peak_share_of_crashes': dict(
        value=0.25, unit='fraction of annual crashes occurring in the appraised peak hours',
        source='PLACEHOLDER (stated assumption): 25% of annual crashes fall inside '
               'the 500 appraised peak-hours. Peak hours are only ~12% of annual '
               'traffic, so this embeds an assumed higher crash RATE in peak.'),
    'conflicts_per_crash': dict(
        value=None, unit='severe conflicts (TTC<1.5 s) per crash -- DERIVED, not assumed',
        source='DERIVED BY CALIBRATION, AND STILL THE WEAKEST LINK IN THE CHAIN. '
               'Rather than inventing a conflict-to-crash ratio, the factor is '
               'back-calculated so that the DO-NOTHING BASE reproduces the assumed '
               'crash frequency above: '
               'conflicts_per_crash = (base severe conflicts per peak hour) x '
               '(peak hours per year) / (base crashes per year x peak share). '
               'The alternatives\' crash-cost changes then follow from applying '
               'that same LINEAR factor to their conflict-count changes. Three '
               'weaknesses remain and are NOT resolved: (1) crash risk is assumed '
               'strictly LINEAR in severe-conflict count, which the surrogate-safety '
               'literature does not establish; (2) the calibration inherits whatever '
               'error is in the assumed base crash frequency; (3) this memory has '
               'already verified that absolute SSM severe-conflict counts move by a '
               'factor of ~7 purely with simulation time-discretisation settings '
               '(semantic-memory/sumo-time-discretization.md) -- the CALIBRATION '
               'absorbs a uniform scale error of that kind, but not a differential '
               'one between alternatives. Treat the safety term as ORDINAL.'),
    'peak_hours_per_year': dict(
        value=500.0, unit='equivalent simulated peak-hours per year',
        source='STATED ASSUMPTION: 2 peak periods/day (AM + PM, PM assumed to '
               'carry the same benefit as the simulated AM peak) x 250 weekdays '
               '= 500 h/yr. Off-peak and weekend benefits are set to ZERO. This '
               'is CONSERVATIVE for the congestion-relief terms (which are '
               'largest in peak) but UNDERSTATES the VOC/fuel/emissions terms, '
               'which accrue in every hour of operation. Cross-check: at an '
               'urban-arterial K-factor of ~0.09, one peak hour is ~9% of AADT, '
               'so 500 peak-hours/yr represents ~45 AADT-equivalents out of 365, '
               'i.e. this annualisation books benefits on ~12% of annual traffic.'),
    'discount_rate': dict(
        value=0.07, unit='real, per year',
        source='STATED ASSUMPTION: 7% real, the legacy US OMB Circular A-94 rate '
               'long used in US transport BCA. Current USDOT BCA guidance uses a '
               'considerably lower rate (~3.1%), which would RAISE all NPVs; the '
               'discount rate is carried through the sensitivity analysis.'),
    'demand_growth': dict(
        value=0.015, unit='per year, compound',
        source='STATED ASSUMPTION: 1.5%/yr compound traffic growth, giving a '
               'x1.347 demand factor after 20 years. Not derived from any '
               'observed count series.'),
    'appraisal_years': dict(
        value=20, unit='years of benefit stream after opening',
        source='STATED ASSUMPTION: 20-year appraisal period, benefits accruing in '
               'years 1..20, capital spent at year 0.'),
    'free_flow_kmh': dict(
        value=50.0, unit='km/h',
        source='MODEL FACT: arterial free-flow speed set in the network '
               '(13.89 m/s). Used only for the network-geometry correction.'),
}

# --- capital / recurring costs (all PLACEHOLDER unit costs) -----------------
COSTS = {
    'B': dict(
        capital=180_000.0,
        capital_source='PLACEHOLDER: ~$36k per intersection x 5 for a corridor '
                       'retiming study plus detection/communications upgrade.',
        recurring=30_000.0,
        recurring_source='PLACEHOLDER: annual signal-retiming maintenance, '
                         'monitoring and periodic re-optimisation.',
        life=10, renew=True,
        residual_note='10-year life, renewed in full at year 10; zero residual '
                      'value at the end of the 20-year appraisal period.'),
    'C': dict(
        capital=4_600_000.0,
        capital_source='PLACEHOLDER: ~$2.3M per intersection x 2 for widening to '
                       'add exclusive left-turn bays on all four approaches '
                       '(pavement, drainage, right-of-way, signal reconstruction '
                       'for protected left-turn phasing).',
        recurring=30_000.0,
        recurring_source='C is retimed and coordinated as well as rebuilt, so it '
                         'carries the SAME recurring retiming cost as B.',
        life=30, renew=False,
        extra_capital=180_000.0,
        extra_capital_source='C also includes B operational package (retiming + '
                             'detection), since the rebuilt intersections are '
                             'retimed and the corridor coordinated.',
        residual_note='30-year life; straight-line residual value of (30-20)/30 = '
                      '1/3 of the civil capital credited at year 20 and discounted '
                      'back.'),
}

BENEFIT_COMPONENTS = ['time_car', 'time_truck', 'voc', 'fuel', 'co2', 'nox', 'pm', 'safety']

# The compound growth rate that was actually SIMULATED (run_batch.py GROWTH). The
# simulated points k = 0, 10, 20 are demand LEVELS S0*(1+SIM_GROWTH)^k, not calendar
# years. When the appraisal is re-run with a different assumed growth rate, an
# appraisal year must therefore be mapped onto the equivalent simulated demand
# LEVEL, not onto the same year index -- otherwise the growth-rate sensitivity
# silently does nothing at all.
SIM_GROWTH = 0.015


# ---------------------------------------------------------------------------
def load_runs(d):
    """runs[alt][k][seed] = measures dict"""
    runs = defaultdict(lambda: defaultdict(dict))
    for f in sorted(glob.glob(os.path.join(d, 'alt*_y*_s*.json'))):
        m = re.match(r'alt([ABC])_y(\d+)_s(\d+)\.json', os.path.basename(f))
        if not m:
            continue
        alt, k, seed = m.group(1), int(m.group(2)), int(m.group(3))
        runs[alt][k][seed] = json.load(open(f))
    return runs


def calibrate_conflict_factor(runs, p):
    """Back-calculate severe-conflicts-per-crash so the DO-NOTHING base reproduces
    the assumed corridor crash frequency. Returns (factor, base_conflicts_per_hour)."""
    k = min(runs['A'])
    base_conf = float(np.mean([r['conf_severe_ttc'] for r in runs['A'][k].values()]))
    crashes_in_peak = p['base_crashes_per_year'] * p['peak_share_of_crashes']
    return base_conf * p['peak_hours_per_year'] / crashes_in_peak, base_conf


def geometry_correction(runs, p):
    """Alternative C's network compiles ~1.5% shorter through the rebuilt
    junctions (a wider intersection footprint eats edge length in netconvert).
    Left uncorrected this books a spurious distance AND travel-time benefit for C.
    Correction factor is measured from the runs themselves at k=0."""
    k = min(runs['A'].keys())
    seeds = sorted(set(runs['A'][k]) & set(runs['C'][k]))
    va = np.mean([runs['A'][k][s]['vkt_total_km'] for s in seeds])
    vc = np.mean([runs['C'][k][s]['vkt_total_km'] for s in seeds])
    vb = np.mean([runs['B'][k][s]['vkt_total_km'] for s in seeds])
    return {'A': 1.0, 'B': va / vb, 'C': va / vc}


def benefits_one(base, alt, p, gfac):
    """Monetised benefit components (USD per simulated peak hour) of `alt` vs `base`.

    `gfac` rescales the alternative's distance-driven quantities onto the base
    network's route length, removing the netconvert geometry artefact; the
    travel-time term gets the free-flow time of the removed distance added back.
    """
    ff = p['free_flow_kmh']
    dkm = base['vkt_total_km'] - alt['vkt_total_km'] * gfac      # ~0 after correction
    # travel-time benefit, with the geometry distance credited back at free flow
    geom_h = (base['vkt_total_km'] - alt['vkt_total_km']) / ff
    share_truck = (alt['vht_truck_h'] / alt['vht_total_h']) if alt['vht_total_h'] else 0.0
    dt_car = (base['vht_car_h'] - alt['vht_car_h']) - geom_h * (1 - share_truck)
    dt_trk = (base['vht_truck_h'] - alt['vht_truck_h']) - geom_h * share_truck
    return {
        'time_car': dt_car * p['vot_car'],
        'time_truck': dt_trk * p['vot_truck'],
        'voc': dkm * p['voc_per_km'],
        'fuel': (base['fuel_l'] - alt['fuel_l'] * gfac) * p['fuel_price'],
        'co2': (base['co2_t'] - alt['co2_t'] * gfac) * p['scc_co2'],
        'nox': (base['nox_kg'] - alt['nox_kg'] * gfac) / 1000.0 * p['cost_nox'],
        'pm': (base['pmx_kg'] - alt['pmx_kg'] * gfac) / 1000.0 * p['cost_pm'],
        'safety': ((base['conf_severe_ttc'] - alt['conf_severe_ttc'])
                   / p['conflicts_per_crash'] * p['crash_cost']),
    }


def hourly_benefits(runs, p, gfacs, seed=None):
    """out[alt][k][component] = USD per simulated peak hour (mean over seeds, or
    for one specific seed if `seed` given)."""
    out = defaultdict(dict)
    for alt in ('B', 'C'):
        for k in sorted(runs[alt]):
            seeds = sorted(set(runs['A'][k]) & set(runs[alt][k]))
            if seed is not None:
                seeds = [seed] if seed in seeds else []
                if not seeds:
                    continue
            acc = defaultdict(list)
            for s in seeds:
                b = benefits_one(runs['A'][k][s], runs[alt][k][s], p, gfacs[alt])
                for c, v in b.items():
                    acc[c].append(v)
            out[alt][k] = {c: float(np.mean(v)) for c, v in acc.items()}
    return out


def interp_year(hb_alt, k):
    """Linear interpolation of the benefit vector between simulated growth years."""
    ks = sorted(hb_alt)
    if k <= ks[0]:
        return hb_alt[ks[0]]
    if k >= ks[-1]:
        return hb_alt[ks[-1]]
    lo = max(x for x in ks if x <= k)
    hi = min(x for x in ks if x >= k)
    if lo == hi:
        return hb_alt[lo]
    w = (k - lo) / (hi - lo)
    return {c: hb_alt[lo][c] * (1 - w) + hb_alt[hi][c] * w for c in hb_alt[lo]}


def appraise_alt(alt, hb_alt, p, costs):
    """PV of benefits by component, PV of costs, NPV, BCR, FYRR for one alternative."""
    r = p['discount_rate']
    N = int(p['appraisal_years'])
    H = p['peak_hours_per_year']
    c = costs[alt]

    pv_b = {comp: 0.0 for comp in BENEFIT_COMPONENTS}
    first_year_benefit = 0.0
    # map appraisal year -> equivalent SIMULATED growth exponent at the assumed rate
    ratio = math.log1p(p['demand_growth']) / math.log1p(SIM_GROWTH)
    for t in range(1, N + 1):
        yr = interp_year(hb_alt, (t - 1) * ratio)   # year 1 == opening == exponent 0
        df = 1.0 / (1.0 + r) ** t
        for comp in BENEFIT_COMPONENTS:
            pv_b[comp] += yr[comp] * H * df
        if t == 1:
            first_year_benefit = sum(yr[comp] for comp in BENEFIT_COMPONENTS) * H

    capital = c['capital'] + c.get('extra_capital', 0.0)
    pv_c = capital                                # spent at t=0
    for t in range(1, N + 1):
        pv_c += c['recurring'] / (1.0 + r) ** t
    if c.get('renew') and c['life'] < N:          # renewal part-way through
        pv_c += c['capital'] / (1.0 + r) ** c['life']
    residual = 0.0
    if c['life'] > N and not c.get('renew'):
        residual = c['capital'] * (c['life'] - N) / c['life'] / (1.0 + r) ** N
        pv_c -= residual

    tot_b = sum(pv_b.values())
    return dict(alt=alt, pv_benefits=tot_b, pv_costs=pv_c,
                npv=tot_b - pv_c, bcr=(tot_b / pv_c if pv_c else float('nan')),
                fyrr=first_year_benefit / capital if capital else float('nan'),
                capital=capital, residual_pv=residual,
                first_year_benefit=first_year_benefit, **{f'pv_{k2}': v for k2, v in pv_b.items()})


def full_appraisal(runs, p, costs, gfacs, seed=None):
    hb = hourly_benefits(runs, p, gfacs, seed=seed)
    res = {alt: appraise_alt(alt, hb[alt], p, costs) for alt in ('B', 'C')}
    # incremental analysis: C over B (the correct rule for mutually exclusive options)
    db = res['C']['pv_benefits'] - res['B']['pv_benefits']
    dc = res['C']['pv_costs'] - res['B']['pv_costs']
    res['incremental'] = dict(delta_pv_benefits=db, delta_pv_costs=dc,
                              incremental_bcr=db / dc if dc else float('nan'),
                              delta_npv=db - dc)
    return res, hb


# ---------------------------------------------------------------------------
# statistics: propagate simulation stochasticity into the economics
# ---------------------------------------------------------------------------
def paired_stats(runs, key, alt, base, k, conf=0.95):
    """Paired (Common Random Numbers) comparison of `key` between two alternatives
    at growth year k. Returns mean difference (base - alt), CI, p, and the number
    of replications that would be needed for the CI half-width to be < |mean|."""
    seeds = sorted(set(runs[base][k]) & set(runs[alt][k]))
    d = np.array([runs[base][k][s][key] - runs[alt][k][s][key] for s in seeds])
    n = len(d)
    md, sd = float(d.mean()), float(d.std(ddof=1)) if n > 1 else 0.0
    if n < 2 or sd == 0:
        return dict(n=n, mean=md, sd=sd, ci_lo=md, ci_hi=md, p=float('nan'),
                    significant=bool(md != 0), n_required=n, seeds=seeds)
    tcrit = stats.t.ppf(0.5 + conf / 2, n - 1)
    half = tcrit * sd / math.sqrt(n)
    t, pv = stats.ttest_1samp(d, 0.0)
    # replications needed for the half-width to fall below |mean difference|
    n_req = n
    if md != 0:
        n_req = max(2, int(math.ceil((stats.norm.ppf(0.5 + conf / 2) * sd / abs(md)) ** 2)))
    return dict(n=n, mean=md, sd=sd, ci_lo=md - half, ci_hi=md + half, p=float(pv),
                significant=bool(pv < 1 - conf), n_required=n_req, seeds=seeds,
                cv=sd / abs(md) if md else float('nan'))


def per_seed_npv(runs, p, costs, gfacs):
    """Re-run the whole appraisal once per seed so the seed-to-seed spread of the
    NPV / BCR / incremental BCR can be reported, rather than only a point estimate
    built from seed-averaged inputs."""
    k0 = min(runs['A'])
    seeds = sorted(set.intersection(*[set(runs[a][k].keys())
                                      for a in ('A', 'B', 'C') for k in runs[a]]))
    rows = []
    for s in seeds:
        res, _ = full_appraisal(runs, p, costs, gfacs, seed=s)
        rows.append(dict(seed=s,
                         npv_B=res['B']['npv'], bcr_B=res['B']['bcr'],
                         npv_C=res['C']['npv'], bcr_C=res['C']['bcr'],
                         incr_bcr=res['incremental']['incremental_bcr'],
                         pvb_B=res['B']['pv_benefits'], pvb_C=res['C']['pv_benefits']))
    return rows, seeds


def ci(vals, conf=0.95):
    a = np.asarray(vals, dtype=float)
    n = len(a)
    if n < 2:
        return float(a.mean()), float(a.mean()), float(a.mean())
    h = stats.t.ppf(0.5 + conf / 2, n - 1) * a.std(ddof=1) / math.sqrt(n)
    return float(a.mean()), float(a.mean() - h), float(a.mean() + h)


# ---------------------------------------------------------------------------
# one-way sensitivity + switching values
# ---------------------------------------------------------------------------
SENS = [
    ('vot',                 'Value of time (car & truck)', 0.60, 1.40),
    ('discount_rate',       'Discount rate',               0.03, 0.10),
    ('demand_growth',       'Demand growth rate',          0.005, 0.025),
    ('capital_cost',        'Capital cost (alt C)',        0.70, 1.30),
    ('conflicts_per_crash', 'Conflict-to-crash factor',    0.20, 5.00),
    ('peak_hours_per_year', 'Annualisation (peak-h/yr)',   350.0, 650.0),
]


def apply_param(p, costs, name, val):
    p2, c2 = dict(p), {k: dict(v) for k, v in costs.items()}
    if name == 'vot':
        p2['vot_car'] *= val
        p2['vot_truck'] *= val
    elif name == 'capital_cost':
        c2['C']['capital'] *= val
    elif name == 'conflicts_per_crash':
        # a LARGER conflicts-per-crash divisor means FEWER crashes per conflict,
        # i.e. a SMALLER safety benefit; the multiplier is applied to the divisor
        p2['conflicts_per_crash'] *= val
    else:
        p2[name] = val
    return p2, c2


def metric_of(res, which):
    if which == 'npv_C':
        return res['C']['npv']
    if which == 'npv_B':
        return res['B']['npv']
    if which == 'incr_bcr':
        return res['incremental']['incremental_bcr']
    if which == 'npv_C_minus_B':
        return res['C']['npv'] - res['B']['npv']
    raise KeyError(which)


def sensitivity(runs, p, costs, gfacs):
    base_res, _ = full_appraisal(runs, p, costs, gfacs)
    rows = []
    for name, label, lo, hi in SENS:
        out = {'param': name, 'label': label, 'low': lo, 'high': hi}
        for tag, v in (('lo', lo), ('hi', hi)):
            p2, c2 = apply_param(p, costs, name, v)
            r2, _ = full_appraisal(runs, p2, c2, gfacs)
            out[f'npv_B_{tag}'] = r2['B']['npv']
            out[f'npv_C_{tag}'] = r2['C']['npv']
            out[f'incr_bcr_{tag}'] = r2['incremental']['incremental_bcr']
        rows.append(out)
    return base_res, rows


def switching_value(runs, p, costs, gfacs, name, which, target=0.0,
                    span=(1e-4, 1e4), tol=1e-6):
    """Bisect for the parameter multiplier/value at which `which` hits `target`."""
    def f(v):
        p2, c2 = apply_param(p, costs, name, v)
        r2, _ = full_appraisal(runs, p2, c2, gfacs)
        return metric_of(r2, which) - target
    lo, hi = span
    flo, fhi = f(lo), f(hi)
    if flo * fhi > 0:
        return None
    for _ in range(200):
        mid = math.sqrt(lo * hi) if lo > 0 and hi > 0 else 0.5 * (lo + hi)
        fm = f(mid)
        if abs(fm) < tol or (hi - lo) < tol * max(1.0, hi):
            return mid
        if flo * fm <= 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    return mid


# ---------------------------------------------------------------------------
def write_csv(path, rows, fields=None):
    if not rows:
        return
    fields = fields or list(rows[0].keys())
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def tornado(base_res, sens_rows, out_png, which='npv_C', title=None):
    """Horizontal one-way sensitivity ("tornado") chart.

    Each bar end is labelled with the PARAMETER VALUE that produced it (not with
    whichever value happens to sit on that side), and coloured by the DIRECTION of
    the effect on the metric: red = this parameter value reduces the metric,
    blue = it increases it. Bars are sorted by total swing, widest at the top.
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    base = metric_of(base_res, which)
    items = []
    for r in sens_rows:
        vlo, vhi = r[f'{which}_lo'], r[f'{which}_hi']
        items.append(dict(label=r['label'], plo=r['low'], phi=r['high'],
                          mlo=vlo, mhi=vhi,
                          swing=abs(vhi - vlo)))
    items.sort(key=lambda d: d['swing'])          # widest ends up at the top

    fig, ax = plt.subplots(figsize=(11, 5.6))
    lo_c, hi_c = '#c0504d', '#4f81bd'
    for i, d in enumerate(items):
        for mval, pval in ((d['mlo'], d['plo']), (d['mhi'], d['phi'])):
            colour = hi_c if mval >= base else lo_c
            ax.barh(i, mval - base, left=base, height=0.6, color=colour,
                    edgecolor='white', linewidth=0.6, zorder=3)
            ha = 'left' if mval >= base else 'right'
            pad = (1 if mval >= base else -1) * 0.004 * abs(ax.get_xlim()[1] or 1)
            ax.annotate(f'{pval:g}', (mval, i), xytext=(3 if mval >= base else -3, 0),
                        textcoords='offset points', va='center', ha=ha,
                        fontsize=8, color='#444', zorder=5)
    ax.axvline(base, color='k', lw=1.4, zorder=4)
    ax.axvline(0, color='#777', lw=1.0, ls='--', zorder=2)
    ax.set_yticks(np.arange(len(items)))
    ax.set_yticklabels([d['label'] for d in items], fontsize=9.5)
    ax.set_xlabel('Net present value (USD)')
    ax.set_title(title or f'One-way sensitivity of {which}', fontsize=11)
    ax.xaxis.set_major_formatter(
        matplotlib.ticker.FuncFormatter(lambda v, _: f'{v/1e6:,.1f}M'))
    ax.grid(axis='x', alpha=0.28, zorder=0)
    for sp in ('top', 'right', 'left'):
        ax.spines[sp].set_visible(False)
    ax.legend(handles=[Patch(color=hi_c, label='parameter value raises NPV'),
                       Patch(color=lo_c, label='parameter value lowers NPV'),
                       plt.Line2D([], [], color='k', lw=1.4,
                                  label=f'central case ({base/1e6:,.2f}M)'),
                       plt.Line2D([], [], color='#777', lw=1.0, ls='--',
                                  label='NPV = 0 (switching threshold)')],
              loc='lower right', fontsize=8, framealpha=0.92)
    margin = 0.08 * (max(max(d['mlo'], d['mhi']) for d in items)
                     - min(min(d['mlo'], d['mhi']) for d in items))
    ax.set_xlim(min(0, min(min(d['mlo'], d['mhi']) for d in items)) - margin,
                max(max(d['mlo'], d['mhi']) for d in items) + margin)
    fig.tight_layout()
    fig.savefig(out_png, dpi=150)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--measures-dir', required=True)
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--no-geom-correct', action='store_true')
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    runs = load_runs(args.measures_dir)
    p = {k: v['value'] for k, v in PARAMS.items()}
    p['conflicts_per_crash'], base_conf = calibrate_conflict_factor(runs, p)
    PARAMS['conflicts_per_crash']['value'] = p['conflicts_per_crash']
    print(f'conflict-to-crash calibration: base case has {base_conf:,.0f} severe '
          f'conflicts per peak hour; assuming {p["base_crashes_per_year"]:.0f} '
          f'crashes/yr of which {p["peak_share_of_crashes"]:.0%} fall in the '
          f'{p["peak_hours_per_year"]:.0f} appraised peak-hours '
          f'=> {p["conflicts_per_crash"]:,.0f} severe conflicts per crash')
    gfacs = ({'A': 1.0, 'B': 1.0, 'C': 1.0} if args.no_geom_correct
             else geometry_correction(runs, p))
    print('network-geometry correction factors (VKT_A / VKT_x):',
          {k: round(v, 5) for k, v in gfacs.items()})

    # ---------- 1. raw engineering measures ----------
    eng = []
    for alt in ('A', 'B', 'C'):
        for k in sorted(runs[alt]):
            seeds = sorted(runs[alt][k])
            row = dict(alt=alt, growth_year=k, n_seeds=len(seeds))
            for m in ('n_veh', 'vht_total_h', 'vht_car_h', 'vht_truck_h',
                      'vkt_total_km', 'vkt_car_km', 'vkt_truck_km',
                      'timeloss_total_h', 'waiting_car_h', 'stops', 'fuel_l',
                      'co2_t', 'nox_kg', 'pmx_kg', 'conf_total', 'conf_severe_ttc',
                      'conf_cross', 'conf_follow', 'conf_type111', 'teleports',
                      'collisions', 'collision_records', 'never_departed',
                      'arrivals_in_window', 'depart_delay_h'):
                v = [runs[alt][k][s].get(m, 0) or 0 for s in seeds]
                row[m] = float(np.mean(v))
                if m in ('vht_total_h', 'timeloss_total_h', 'conf_severe_ttc'):
                    row[m + '_sd'] = float(np.std(v, ddof=1)) if len(v) > 1 else 0.0
            eng.append(row)
    write_csv(os.path.join(args.out_dir, 'engineering_measures.csv'), eng)

    # ---------- 2. paired statistics on the delay-savings term ----------
    st = []
    for k in sorted(runs['A']):
        for alt, base in (('B', 'A'), ('C', 'A'), ('C', 'B')):
            for key in ('vht_total_h', 'timeloss_total_h', 'conf_severe_ttc', 'co2_t'):
                s = paired_stats(runs, key, alt, base, k)
                st.append(dict(growth_year=k, comparison=f'{base}->{alt}', metric=key,
                               n_seeds=s['n'], mean_saving=s['mean'], sd=s['sd'],
                               ci95_lo=s['ci_lo'], ci95_hi=s['ci_hi'], p_value=s['p'],
                               significant_at_95=s['significant'],
                               n_reps_for_halfwidth_lt_mean=s['n_required']))
    write_csv(os.path.join(args.out_dir, 'paired_statistics.csv'), st)

    # ---------- 3. central appraisal ----------
    res, hb = full_appraisal(runs, p, COSTS, gfacs)
    comp_rows = []
    for alt in ('B', 'C'):
        for c in BENEFIT_COMPONENTS:
            comp_rows.append(dict(alt=alt, component=c, pv_usd=res[alt][f'pv_{c}'],
                                  share_pct=100 * res[alt][f'pv_{c}'] / res[alt]['pv_benefits']))
    write_csv(os.path.join(args.out_dir, 'benefit_components.csv'), comp_rows)

    summ = []
    for alt in ('B', 'C'):
        r = res[alt]
        summ.append(dict(alternative=alt,
                         pv_benefits=r['pv_benefits'], pv_costs=r['pv_costs'],
                         capital=r['capital'], residual_pv=r['residual_pv'],
                         npv=r['npv'], bcr=r['bcr'], fyrr_pct=100 * r['fyrr'],
                         first_year_benefit=r['first_year_benefit'],
                         **{f'pv_{c}': r[f'pv_{c}'] for c in BENEFIT_COMPONENTS}))
    inc = res['incremental']
    summ.append(dict(alternative='C vs B (incremental)',
                     pv_benefits=inc['delta_pv_benefits'],
                     pv_costs=inc['delta_pv_costs'], npv=inc['delta_npv'],
                     bcr=inc['incremental_bcr']))
    write_csv(os.path.join(args.out_dir, 'appraisal_summary.csv'), summ,
              fields=list(summ[0].keys()))

    # ---------- 4. per-seed NPV spread ----------
    rows, seeds = per_seed_npv(runs, p, COSTS, gfacs)
    write_csv(os.path.join(args.out_dir, 'per_seed_npv.csv'), rows)
    seed_ci = {}
    for kk in ('npv_B', 'npv_C', 'incr_bcr', 'pvb_B', 'pvb_C'):
        seed_ci[kk] = ci([r[kk] for r in rows])
    dnpv = [r['npv_C'] - r['npv_B'] for r in rows]
    seed_ci['npv_C_minus_npv_B'] = ci(dnpv)
    t, pv = (stats.ttest_1samp(dnpv, 0.0) if len(dnpv) > 1 else (float('nan'),) * 2)
    seed_ci['p_C_vs_B_ranking'] = (float(pv), 0, 0)

    # ---------- 5. interpolation validation ----------
    interp_check = []
    ks = sorted(hb['B'])
    if len(ks) >= 3:
        lo, mid, hi = ks[0], ks[len(ks) // 2], ks[-1]
        for alt in ('B', 'C'):
            w = (mid - lo) / (hi - lo)
            for c in BENEFIT_COMPONENTS:
                pass
            pred = {c: hb[alt][lo][c] * (1 - w) + hb[alt][hi][c] * w
                    for c in BENEFIT_COMPONENTS}
            ps, ac = sum(pred.values()), sum(hb[alt][mid].values())
            interp_check.append(dict(alt=alt, mid_growth_year=mid,
                                     linear_predicted_hourly_benefit=ps,
                                     simulated_hourly_benefit=ac,
                                     error_pct=100 * (ps - ac) / ac if ac else float('nan')))
    write_csv(os.path.join(args.out_dir, 'interpolation_validation.csv'), interp_check)

    # ---------- 6. sensitivity + switching values ----------
    base_res, sens_rows = sensitivity(runs, p, COSTS, gfacs)
    write_csv(os.path.join(args.out_dir, 'sensitivity.csv'), sens_rows)
    tornado(base_res, sens_rows, os.path.join(args.out_dir, 'tornado_npv_C.png'),
            which='npv_C', title='One-way sensitivity of NPV, alternative C '
                                 '(capital: left-turn bays at J2/J3 + retiming)')
    tornado(base_res, sens_rows, os.path.join(args.out_dir, 'tornado_npv_B.png'),
            which='npv_B', title='One-way sensitivity of NPV, alternative B '
                                 '(operational: retiming + coordination)')

    sw = []
    for name, label, lo, hi in SENS:
        for which, target, desc in (('npv_C', 0.0, 'NPV of C = 0'),
                                    ('npv_B', 0.0, 'NPV of B = 0'),
                                    ('npv_C_minus_B', 0.0, 'C and B rank equally')):
            span = ((0.001, 1000.0) if name in ('vot', 'capital_cost',
                                                'conflicts_per_crash')
                    else (1e-4, 0.99) if name == 'discount_rate'
                    else (1e-5, 0.5) if name == 'demand_growth'
                    else (1.0, 1e6))
            v = switching_value(runs, p, COSTS, gfacs, name, which, target, span)
            sw.append(dict(param=name, label=label, criterion=desc,
                           central=(1.0 if name in ('vot', 'capital_cost',
                                                    'conflicts_per_crash')
                                    else p.get(name)),
                           switching_value=v,
                           note=('multiplier on central value'
                                 if name in ('vot', 'capital_cost',
                                             'conflicts_per_crash')
                                 else 'absolute value')))
    write_csv(os.path.join(args.out_dir, 'switching_values.csv'), sw)

    # ---------- 7. provenance ----------
    prov = [dict(parameter=k, value=v['value'], unit=v['unit'],
                 provenance=('CITED' if v['source'].startswith('CITED')
                             else 'PLACEHOLDER' if 'PLACEHOLDER' in v['source']
                             else 'STATED ASSUMPTION'),
                 source=v['source']) for k, v in PARAMS.items()]
    for a, c in COSTS.items():
        prov.append(dict(parameter=f'capital_{a}', value=c['capital'], unit='USD',
                         provenance='PLACEHOLDER', source=c['capital_source']))
        prov.append(dict(parameter=f'recurring_{a}', value=c['recurring'],
                         unit='USD/yr', provenance='PLACEHOLDER',
                         source=c['recurring_source']))
    write_csv(os.path.join(args.out_dir, 'parameter_provenance.csv'), prov)

    out = dict(geometry_correction=gfacs,
               central=({a: {k2: v2 for k2, v2 in res[a].items()} for a in ('B', 'C')}
                        | {'incremental': res['incremental']}),
               seed_ci=seed_ci, seeds=seeds, interpolation_check=interp_check)
    with open(os.path.join(args.out_dir, 'appraisal_results.json'), 'w') as f:
        json.dump(out, f, indent=1, default=float)

    print(f"\n{'alt':>4} {'PV benefits':>14} {'PV costs':>13} {'NPV':>14} "
          f"{'BCR':>6} {'FYRR%':>7}")
    for alt in ('B', 'C'):
        r = res[alt]
        print(f'{alt:>4} {r["pv_benefits"]:>14,.0f} {r["pv_costs"]:>13,.0f} '
              f'{r["npv"]:>14,.0f} {r["bcr"]:>6.2f} {100*r["fyrr"]:>7.1f}')
    print(f'  C vs B incremental: dPVB={inc["delta_pv_benefits"]:,.0f} '
          f'dPVC={inc["delta_pv_costs"]:,.0f} '
          f'incremental BCR={inc["incremental_bcr"]:.2f}')
    print(f'  NPV(C)-NPV(B) across seeds: mean={seed_ci["npv_C_minus_npv_B"][0]:,.0f} '
          f'95% CI [{seed_ci["npv_C_minus_npv_B"][1]:,.0f}, '
          f'{seed_ci["npv_C_minus_npv_B"][2]:,.0f}]  p={seed_ci["p_C_vs_B_ranking"][0]:.4f}')
    print(f'\nwrote outputs to {args.out_dir}')


if __name__ == '__main__':
    main()
