#!/usr/bin/env python3
"""
12-hour (07:00-19:00) time-sliced demand for the driveway TIA.

Three demand scenarios:
  nobuild     background arterial + existing minor street only (no site trips)
  build       background + 100 ksf GLA shopping centre (ITE LUC 820)
  build_high  background + the same site at 2.0x intensity (stress case)

Structure of the demand
-----------------------
1. BACKGROUND diurnal profile: an explicit hourly two-way arterial volume with
   an hourly directional split (AM peak eastbound-dominant, PM peak westbound-
   dominant) and an hourly minor-street volume.
2. SITE trips: an ITE-style trip-generation calculation, stated numerically in
   the manifest -- daily rate, AM/PM peak-hour rates, hourly distribution,
   in/out directional split that differs between AM and PM, a 65% west /
   35% east trip distribution, and a PASS-BY fraction.  Pass-by trip ends load
   the driveway but are SUBTRACTED from the background arterial through volume
   (they were already on the road); only the remainder are NEW trips.
3. Every clock hour is split into four 15-minute slices with a documented
   PEAK-HOUR FACTOR, so the peak 15 minutes carries a flow rate of V/PHF.
4. Arrivals inside each slice are POISSON  (period="exp(rate)"), not the
   equal-headway `vehsPerHour` form -- see
   generate-hcm-los-report-and-validate-against-microsimulation.

Everything written here is *nominal input demand*.  The warrant analysis
deliberately re-derives the same quantities from DETECTOR output so the two can
be compared (the demand-vs-served-volume trap).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import SCEN, N_HOURS, HOUR, hour_label, write

DEM = os.path.join(SCEN, "demand")
os.makedirs(DEM, exist_ok=True)

# ------------------------------------------------------------ 1. BACKGROUND
# two-way major-street volume (veh/h) and the eastbound share, per clock hour
MAJOR_TWO_WAY = [900, 1400, 1100, 850, 850, 950, 900, 850, 1000, 1300, 1600, 1150]
EB_SHARE      = [0.58, 0.62, 0.58, 0.52, 0.50, 0.50, 0.50, 0.48, 0.45, 0.42, 0.38, 0.40]
# existing minor street (south leg) approach volume (veh/h)
MINOR_S       = [55, 90, 70, 55, 55, 65, 60, 55, 65, 85, 105, 75]
MINOR_S_LEFT  = 0.45     # to the west; the rest turn right to the east

# major-street background turning fractions (of that approach's total)
EB_RIGHT_BG = 0.03       # eastbound right into the existing minor street
WB_LEFT_BG  = 0.04       # westbound left into the existing minor street

# ------------------------------------------------ 2. SITE TRIP GENERATION
# ITE-style inputs, stated explicitly (representative published rates for
# LUC 820 Shopping Centre used as the documented study input).
ITE = {
    "land_use": "ITE Land Use Code 820 - Shopping Centre",
    "size_ksf_GLA": 100.0,
    "daily_rate_per_ksf": 37.75,
    "am_peak_rate_per_ksf": 0.94,
    "pm_peak_rate_per_ksf": 3.81,
    "am_peak_hour": "08:00-09:00",
    "pm_peak_hour": "17:00-18:00",
    "am_in_share": 0.62,
    "pm_in_share": 0.48,
    "passby_am": 0.25,
    "passby_md": 0.30,
    "passby_pm": 0.34,
    "dist_west": 0.65,
    "dist_east": 0.35,
}
# hourly driveway two-way trip ends (veh/h), calibrated so that
#   hour 1 (08:00-09:00) == ITE AM peak-hour rate x size  = 94
#   hour 10 (17:00-18:00) == ITE PM peak-hour rate x size = 381
SITE_HOURLY = [40, 94, 130, 200, 250, 300, 290, 260, 280, 330, 381, 350]
SITE_IN_SHARE = [0.62, 0.62, 0.60, 0.56, 0.54, 0.52, 0.52, 0.52, 0.50, 0.49, 0.48, 0.42]
SITE_PASSBY = [0.25, 0.25, 0.25, 0.30, 0.30, 0.30, 0.30, 0.30, 0.30, 0.34, 0.34, 0.34]

# The three headline scenarios, plus a site-intensity SWEEP used to locate the
# demand level at which the detector-measured warrant check first disagrees
# with the demand-based one.
SCENARIOS = {"nobuild": 0.0, "build": 1.0, "build_high": 2.0}
SWEEP = {f"site{int(round(x*100)):03d}": x
         for x in (0.15, 0.25, 0.40, 0.50, 0.75, 1.50, 3.00)}
SCENARIOS.update(SWEEP)

# ------------------------------------------------------- 3. PHF sub-slices
PHF_PEAK, PHF_OFF = 0.92, 0.95
PEAK_HOURS = {1, 9, 10}          # 08:00, 16:00, 17:00
PEAK_SLICE = 1                   # the 2nd quarter-hour carries the peak rate


def slice_shares(h):
    phf = PHF_PEAK if h in PEAK_HOURS else PHF_OFF
    top = 1.0 / (4.0 * phf)
    rest = (1.0 - top) / 3.0
    return [top if q == PEAK_SLICE else rest for q in range(4)], phf


# --------------------------------------------------------------- routes
ROUTES = {
    # major eastbound (from W)
    "EBT": "maj_W_feed maj_W_bay maj_out_E",
    "EBR": "maj_W_feed maj_W_bay min_S_out",
    "EBL": "maj_W_feed maj_W_bay drw_N_out",          # left into the site (uses the bay)
    # major westbound (from E)
    "WBT": "maj_E_feed maj_E_bay maj_out_W",
    "WBR": "maj_E_feed maj_E_bay drw_N_out",          # right into the site
    "WBL": "maj_E_feed maj_E_bay min_S_out",
    # driveway (north leg) outbound
    "DWL": "drw_N_in maj_out_E",                      # left out, to the east
    "DWR": "drw_N_in maj_out_W",                      # right out, to the west
    # existing minor street (south leg)
    "SBL": "min_S_in maj_out_W",
    "SBR": "min_S_in maj_out_E",
}
# right-in / right-out re-routings: the banned movements are replaced by a
# downstream U-turn at the network fringe (a real median opening 300 m away),
# so the out-of-direction travel penalty is genuinely simulated.
ROUTES_RIRO = dict(ROUTES)
ROUTES_RIRO["EBL"] = "maj_W_feed maj_W_bay maj_out_E maj_E_feed maj_E_bay drw_N_out"
ROUTES_RIRO["DWL"] = "drw_N_in maj_out_W maj_W_feed maj_W_bay maj_out_E"

DEPART_LANE_1LANE = {"EBT": "random", "EBR": "0", "EBL": "1",
                     "WBT": "random", "WBR": "0", "WBL": "1",
                     "DWL": "0", "DWR": "0", "SBL": "0", "SBR": "0"}
DEPART_LANE_RT = dict(DEPART_LANE_1LANE)
DEPART_LANE_RT.update({"DWR": "0", "DWL": "1"})       # exclusive right-turn lane on the driveway

MAJOR_MOVES = ["EBT", "EBR", "EBL", "WBT", "WBR", "WBL"]
DRIVEWAY_MOVES = ["DWL", "DWR"]
MINOR_S_MOVES = ["SBL", "SBR"]


def hourly_movements(scale):
    """Return per-hour dict of movement -> nominal veh/h, plus a bookkeeping trace."""
    out, trace = [], []
    for h in range(N_HOURS):
        maj = MAJOR_TWO_WAY[h]
        eb_tot = maj * EB_SHARE[h]
        wb_tot = maj * (1.0 - EB_SHARE[h])

        site_total = SITE_HOURLY[h] * scale
        in_total = site_total * SITE_IN_SHARE[h]
        out_total = site_total - in_total
        # pass-by VEHICLES: each generates one inbound + one outbound trip end
        P = site_total * SITE_PASSBY[h] / 2.0
        P_w = P * ITE["dist_west"]     # arrived from the west  (EB), leaves east  (DWL)
        P_e = P * ITE["dist_east"]     # arrived from the east  (WB), leaves west  (DWR)
        new_in = max(0.0, in_total - P)
        new_out = max(0.0, out_total - P)

        EBL = new_in * ITE["dist_west"] + P_w
        WBR = new_in * ITE["dist_east"] + P_e
        DWL = new_out * ITE["dist_east"] + P_w
        DWR = new_out * ITE["dist_west"] + P_e

        # background arterial through volumes, with pass-by trips REMOVED
        eb_right = eb_tot * EB_RIGHT_BG
        wb_left = wb_tot * WB_LEFT_BG
        EBT = max(0.0, eb_tot - eb_right - P_w)
        WBT = max(0.0, wb_tot - wb_left - P_e)

        mv = {"EBT": EBT, "EBR": eb_right, "EBL": EBL,
              "WBT": WBT, "WBR": WBR, "WBL": wb_left,
              "DWL": DWL, "DWR": DWR,
              "SBL": MINOR_S[h] * MINOR_S_LEFT,
              "SBR": MINOR_S[h] * (1.0 - MINOR_S_LEFT)}
        out.append(mv)
        trace.append({
            "hour": hour_label(h),
            "background_major_two_way": maj,
            "eb_share": EB_SHARE[h],
            "site_trip_ends_two_way": round(site_total, 1),
            "site_in": round(in_total, 1), "site_out": round(out_total, 1),
            "passby_fraction": SITE_PASSBY[h],
            "passby_vehicles": round(P, 1),
            "new_trips_in": round(new_in, 1), "new_trips_out": round(new_out, 1),
            "major_total_entering": round(EBT + eb_right + EBL + WBT + WBR + wb_left, 1),
            "driveway_approach": round(DWL + DWR, 1),
            "minor_street_approach": round(MINOR_S[h], 1),
            "higher_minor_approach": round(max(DWL + DWR, MINOR_S[h]), 1),
        })
    return out, trace


def write_routes(scenario, variant, path):
    """variant in {std, rt, riro} -- affects departLane and (for riro) routes."""
    scale = SCENARIOS[scenario]
    mv_by_hour, trace = hourly_movements(scale)
    routes = ROUTES_RIRO if variant == "riro" else ROUTES
    dl = DEPART_LANE_RT if variant == "rt" else DEPART_LANE_1LANE

    x = ['<?xml version="1.0" encoding="UTF-8"?>', "<routes>"]
    x.append('  <vType id="car" vClass="passenger" accel="2.6" decel="4.5" sigma="0.5"'
             ' length="5.0" minGap="2.5" tau="1.0" maxSpeed="22.0"'
             ' speedFactor="1.0" speedDev="0" actionStepLength="1.0"'
             ' carFollowModel="Krauss" lcKeepRight="0"/>')
    for rid, edges in routes.items():
        x.append(f'  <route id="r_{rid}" edges="{edges}"/>')
    for h in range(N_HOURS):
        shares, phf = slice_shares(h)
        x.append(f"  <!-- {hour_label(h)}  PHF={phf} -->")
        for q in range(4):
            b = h * HOUR + q * 900
            e = b + 900
            for mvname, vph in sorted(mv_by_hour[h].items()):
                rate_vph = vph * shares[q] * 4.0        # veh/h during this 15-min slice
                if rate_vph < 0.5:
                    continue
                rate_vps = rate_vph / 3600.0
                x.append(f'  <flow id="f_{mvname}_{h}_{q}" type="car" route="r_{mvname}" '
                         f'begin="{b}" end="{e}" period="exp({rate_vps:.6f})" '
                         f'departLane="{dl[mvname]}" departSpeed="max"/>')
    x.append("</routes>")
    write(path, "\n".join(x) + "\n")
    return trace


def main():
    manifest = {"ITE": ITE, "scenarios": {},
                "background": {"major_two_way": MAJOR_TWO_WAY, "eb_share": EB_SHARE,
                               "minor_street_south": MINOR_S},
                "site_hourly_trip_ends_100ksf": SITE_HOURLY,
                "phf": {"peak_hours": sorted(PEAK_HOURS), "phf_peak": PHF_PEAK,
                        "phf_offpeak": PHF_OFF, "peak_slice_index": PEAK_SLICE}}
    for scen in SCENARIOS:
        for variant in ("std", "rt", "riro"):
            p = os.path.join(DEM, f"{scen}_{variant}.rou.xml")
            trace = write_routes(scen, variant, p)
            if variant == "std":
                manifest["scenarios"][scen] = {"scale": SCENARIOS[scen], "hourly": trace}
            print(f"[demand] {scen:11s} {variant:5s} -> {os.path.basename(p)}")
    write(os.path.join(DEM, "demand_manifest.json"), json.dumps(manifest, indent=2))
    print("[demand] wrote demand_manifest.json")
    # console summary of the nominal warrant inputs
    print("\nNOMINAL (demand-basis) warrant inputs:")
    print(f"{'hour':14s}" + "".join(f"{s:>28s}" for s in SCENARIOS))
    print(f"{'':14s}" + "".join(f"{'major / minor(higher)':>28s}" for s in SCENARIOS))
    for h in range(N_HOURS):
        row = f"{hour_label(h):14s}"
        for scen in SCENARIOS:
            t = manifest["scenarios"][scen]["hourly"][h]
            row += f"{t['major_total_entering']:>17.0f} /{t['higher_minor_approach']:>9.0f}"
        print(row)


if __name__ == "__main__":
    main()
