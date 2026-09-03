#!/usr/bin/env python3
"""
Extract per-run engineering measures from one SUMO run's outputs, restricted to a
documented analysis window (vehicles whose DEPARTURE falls in [t0, t1)).

Measures produced (one JSON per run):
  vht_car_h, vht_truck_h      vehicle-hours of travel, split by vehicle class
  vkt_car_km, vkt_truck_km    vehicle-kilometres
  timeloss_*_h                vehicle-hours of delay (duration - free-flow time)
  waiting_*_h                 vehicle-hours of standing waiting time
  stops                       total stop events (tripinfo waitingCount)
  fuel_l, co2_t, nox_kg, pmx_kg   emissions (tripinfo <emissions> child, mg -> SI)
  conflicts_*                 SSM conflict counts, by encounter-type category
  teleports, collisions       validity checks
Also reports the vehicles that never departed (insertion backlog).
"""
import argparse
import json
import os
import xml.etree.ElementTree as ET

# encounter-type codes, per semantic-memory/surrogate-safety-measures.md
FOLLOW = {2, 3, 18}
MERGE = {6, 7, 8, 19}
CROSS = set(range(10, 18))
COLLISION_CODE = 111
TRUCK_TYPES = {'truck_hdv', 'van_ldv'}     # "heavy vehicles" for VOT purposes


def parse_tripinfo(path, t0, t1):
    """Window on INTENDED departure (depart - departDelay), which is fixed by the
    trips file and therefore identical across alternatives -> every alternative is
    scored on exactly the same set of trips (a Common Random Numbers requirement).
    Windowing on ACTUAL departure would silently change the vehicle set whenever an
    alternative queues vehicles at the insertion point.

    VHT includes departDelay: time spent queued waiting to be inserted is real
    delay to the traveller and must not be discarded, or a congested alternative
    looks artificially good."""
    agg = dict(n_car=0, n_truck=0, vht_car_h=0.0, vht_truck_h=0.0,
               vkt_car_km=0.0, vkt_truck_km=0.0,
               timeloss_car_h=0.0, timeloss_truck_h=0.0,
               waiting_car_h=0.0, waiting_truck_h=0.0,
               stops=0, depart_delay_h=0.0, arrivals_in_window=0,
               fuel_mg=0.0, co2_mg=0.0, nox_mg=0.0, pmx_mg=0.0, hc_mg=0.0, co_mg=0.0)
    for _, el in ET.iterparse(path, events=('end',)):
        if el.tag != 'tripinfo':
            continue
        dd = float(el.get('departDelay'))
        if t0 <= float(el.get('arrival')) < t1:
            agg['arrivals_in_window'] += 1
        dep = float(el.get('depart')) - dd
        if not (t0 <= dep < t1):
            el.clear()
            continue
        heavy = el.get('vType') in TRUCK_TYPES
        k = 'truck' if heavy else 'car'
        agg[f'n_{k}'] += 1
        agg[f'vht_{k}_h'] += (float(el.get('duration')) + dd) / 3600.0
        agg[f'vkt_{k}_km'] += float(el.get('routeLength')) / 1000.0
        agg[f'timeloss_{k}_h'] += (float(el.get('timeLoss')) + dd) / 3600.0
        agg[f'waiting_{k}_h'] += float(el.get('waitingTime')) / 3600.0
        agg['stops'] += int(el.get('waitingCount'))
        agg['depart_delay_h'] += float(el.get('departDelay')) / 3600.0
        em = el.find('emissions')
        if em is not None:
            agg['fuel_mg'] += float(em.get('fuel_abs'))
            agg['co2_mg'] += float(em.get('CO2_abs'))
            agg['nox_mg'] += float(em.get('NOx_abs'))
            agg['pmx_mg'] += float(em.get('PMx_abs'))
            agg['hc_mg'] += float(em.get('HC_abs'))
            agg['co_mg'] += float(em.get('CO_abs'))
        el.clear()
    return agg


def parse_summary(path):
    """teleports/collisions are CUMULATIVE running counts: read the LAST step, do
    not sum across steps (documented gotcha in analyze-simulation-outputs)."""
    last = {}
    peak_running = 0
    for _, el in ET.iterparse(path, events=('end',)):
        if el.tag == 'step':
            last = dict(el.attrib)
            peak_running = max(peak_running, int(el.get('running')))
        el.clear()
    return dict(teleports=int(last.get('teleports', 0)),
                collisions=int(last.get('collisions', 0)),
                loaded=int(last.get('loaded', 0)),
                inserted=int(last.get('inserted', 0)),
                ended=int(last.get('ended', 0)),
                peak_running=peak_running)


def parse_ssm(path, t0, t1, ttc_severe=1.5):
    out = dict(conf_total=0, conf_follow=0, conf_merge=0, conf_cross=0,
               conf_type111=0, conf_severe_ttc=0, min_ttc=None)
    if not path or not os.path.exists(path):
        return out
    for _, el in ET.iterparse(path, events=('end',)):
        if el.tag != 'conflict':
            continue
        b = float(el.get('begin'))
        if not (t0 <= b < t1):
            el.clear()
            continue
        ttc_el = el.find('minTTC')
        code = None
        for m in ('minTTC', 'maxDRAC', 'PET'):
            sub = el.find(m)
            if sub is not None and sub.get('type') not in (None, 'NA'):
                try:
                    code = int(sub.get('type'))
                    break
                except ValueError:
                    pass
        out['conf_total'] += 1
        if code in FOLLOW:
            out['conf_follow'] += 1
        elif code in MERGE:
            out['conf_merge'] += 1
        elif code in CROSS:
            out['conf_cross'] += 1
        elif code == COLLISION_CODE:
            out['conf_type111'] += 1
        if ttc_el is not None and ttc_el.get('value') not in (None, 'NA'):
            v = float(ttc_el.get('value'))
            if v < ttc_severe:
                out['conf_severe_ttc'] += 1
            out['min_ttc'] = v if out['min_ttc'] is None else min(out['min_ttc'], v)
        el.clear()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tripinfo', required=True)
    ap.add_argument('--summary', required=True)
    ap.add_argument('--ssm', default=None)
    ap.add_argument('--t0', type=float, default=1800.0)
    ap.add_argument('--t1', type=float, default=5400.0)
    ap.add_argument('--label', default='run')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    r = {'label': args.label, 't0': args.t0, 't1': args.t1}
    r.update(parse_tripinfo(args.tripinfo, args.t0, args.t1))
    r.update(parse_summary(args.summary))
    r.update(parse_ssm(args.ssm, args.t0, args.t1))
    r['n_veh'] = r['n_car'] + r['n_truck']
    r['vht_total_h'] = r['vht_car_h'] + r['vht_truck_h']
    r['vkt_total_km'] = r['vkt_car_km'] + r['vkt_truck_km']
    r['timeloss_total_h'] = r['timeloss_car_h'] + r['timeloss_truck_h']
    r['fuel_l'] = r['fuel_mg'] / 1e6 / 0.74      # mg -> kg -> litres (petrol 0.74 kg/L)
    r['co2_t'] = r['co2_mg'] / 1e9               # mg -> tonnes
    r['nox_kg'] = r['nox_mg'] / 1e6
    r['pmx_kg'] = r['pmx_mg'] / 1e6
    r['never_departed'] = r['loaded'] - r['inserted']
    with open(args.out, 'w') as f:
        json.dump(r, f, indent=1)
    print(json.dumps({k: (round(v, 4) if isinstance(v, float) else v)
                      for k, v in r.items()}, indent=1))


if __name__ == '__main__':
    main()
