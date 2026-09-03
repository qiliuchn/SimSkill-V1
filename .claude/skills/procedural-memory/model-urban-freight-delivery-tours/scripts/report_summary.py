#!/usr/bin/env python3
"""Print the hypothesis results in a compact, transcribable form."""
import json, os, sys
from common import TAB

R = json.load(open(os.path.join(TAB, "hypothesis_results.json")))


def f(x, n=2):
    try:
        return ("%%.%df" % n) % float(x)
    except Exception:
        return str(x)


def civ(t, n=2):
    if isinstance(t, (list, tuple)) and len(t) == 3:
        return "%s [%s, %s]" % (f(t[0], n), f(t[1], n), f(t[2], n))
    return f(t, n)


print("=" * 100)
print("H1  TOUR vs TRIP")
h = R["H1"]
print("  n_seeds", h["n_seeds"])
for k, v in h.items():
    if isinstance(v, dict) and "label" in v:
        print("  %-42s tour=%9s trip=%9s  diff=%9s [%s,%s]  %+.1f%% [%.1f,%.1f]"
              % (v["label"], f(v["tour"]), f(v["trip"]), f(v["diff"]),
                 f(v["diff_lo"]), f(v["diff_hi"]), v["pct"] or 0, v["pct_lo"] or 0, v["pct_hi"] or 0))
d = h["freight_attributable_car_delay_h"]
print("  freight-attributable car delay (h): tour=%s trip=%s  diff=%s  pct=%s"
      % (f(d["tour"]), f(d["trip"]), civ(d["diff"]), civ(d["pct"], 1)))
print("  Gini of local truck presence: tour=%s trip=%s diff=%s"
      % (civ(h["gini_local_truck_presence"]["tour"], 3),
         civ(h["gini_local_truck_presence"]["trip"], 3),
         civ(h["gini_local_truck_presence"]["diff"], 3)))
print("  local edges with any truck presence: tour=%s trip=%s diff=%s"
      % (civ(h["local_edges_with_truck_presence"]["tour"], 1),
         civ(h["local_edges_with_truck_presence"]["trip"], 1),
         civ(h["local_edges_with_truck_presence"]["diff"], 1)))

print("=" * 100)
print("H2  RESTRICTION SWEEP")
for fam, rec in R["H2"]["families"].items():
    print(" family=%s" % fam)
    hdr = ("cov", "frtVKT", "hvyLocal", "vanLocal", "allLocal", "arterial", "frtCO2",
           "noiseLoc", "carTL_h", "parcDel", "parcUndel")
    print("   " + " ".join("%9s" % x for x in hdr))
    for cov in ("0", "25", "50", "75", "100", 0, 25, 50, 75, 100):
        if cov not in rec:
            continue
        e = rec[cov]
        g = lambda k: f(e[k]["mean"], 1) if k in e else "-"
        print("   " + " ".join("%9s" % x for x in
                               (cov, g("frt_vkt_km"), g("hvy_vkm_local"), g("van_vkm_local"),
                                g("trk_vkm_local"), g("trk_vkm_arterial"), g("emis_frt_CO2_kg"),
                                g("noise_local_dB"), g("car_total_timeloss_h"),
                                g("parcels_delivered"), g("parcels_undelivered"))))
    print("   paired diffs vs coverage 0 (mean [95% CI]):")
    for cov in list(rec):
        if str(cov) == "0":
            continue
        e = rec[cov]
        for k in ("hvy_vkm_local", "trk_vkm_local", "trk_vkm_total", "emis_frt_CO2_kg",
                  "noise_local_dB", "car_total_timeloss_h", "parcels_delivered"):
            if k in e:
                print("     cov=%-4s %-22s %8s [%8s, %8s]"
                      % (cov, k, f(e[k]["diff"]), f(e[k]["diff_lo"]), f(e[k]["diff_hi"])))
print(" exchange rates:", json.dumps(R["H2"]["exchange_rate"], indent=1, default=str)[:1800])

print("=" * 100)
print("H3  PCE + CONCENTRATION")
for t in R["H3"].get("pce_testbed", []):
    print("  P_HV=%s  s_mix=%s (base %s)  f_HV=%s  E_T=%s  CI=%s"
          % (f(t["realized_share"], 3), f(t["sat_flow"], 0), f(t["sat_flow_base"], 0),
             f(t["f_HV"], 4), f(t["E_T"], 3), t.get("E_T_ci")))
for k, rec in R["H3"].items():
    if not k.startswith("scale"):
        continue
    print("  %s:" % k)
    for cov, e in rec.items():
        print("    cov=%-4s carTL=%s  d_vs_cov0=%s  pct=%s  frtArtVKT=%s  attribDelay=%s tel=%s"
              % (cov, civ(e["car_timeloss_h"], 1), civ(e["car_timeloss_diff_vs_cov0"], 2),
                 civ(e["car_timeloss_pct_vs_cov0"], 2), civ(e["trk_vkm_arterial"], 1),
                 civ(e["freight_attributable_car_delay_h"], 2), civ(e["teleports"], 1)))

print("=" * 100)
print("H4  BAY SUPPLY")
for bf, e in R["H4"]["primary"].items():
    print("  bay=%3s%% deficit=%3s%%  nDoublePark=%s  blockHrs=%s  carTL=%s  "
          "extraDelay_vs_fullbay=%s  perDoublePark_s=%s"
          % (bf, e["deficit_pct"], civ(e["n_blocking_stops"], 1),
             civ(e["blocking_stop_hours"], 2), civ(e["car_timeloss_h"], 1),
             civ(e["delay_vs_full_bay_h"], 2), civ(e["delay_per_double_park_s"], 2)))
cx = R["H4"].get("convexity_test")
if cx:
    print("  CONVEXITY: delay@50%%deficit=%s  delay@100%%deficit=%s  ratio=%s (linear=0.50, convex<0.50)  gap_vs_linear=%s"
          % (civ(cx["delay_at_50pct_deficit"], 2), civ(cx["delay_at_100pct_deficit"], 2),
             civ(cx["ratio_d50_over_d100"], 3), civ(cx["gap_vs_linear"], 2)))
for k, e in R["H4"]["scale"].items():
    if k.endswith("_delta"):
        print("  %s  extra delay (bay0 - bay100) = %s h ; per double-park = %s s"
              % (k, civ(e["delay_h"], 2), civ(e["per_double_park_s"], 1)))
    else:
        print("  %-12s nDoublePark=%s carTL=%s tel=%s stillRunning=%s parcUndel=%s"
              % (k, civ(e["n_blocking_stops"], 0), civ(e["car_timeloss_h"], 1),
                 civ(e["teleports"], 2), civ(e["tours_still_running"], 2),
                 civ(e["parcels_undelivered"], 1)))

print("=" * 100)
print("H5  CONSOLIDATION")
for mix, e in R["H5"].items():
    if mix.startswith("_"):
        continue
    print("  %-11s nVeh=%s (van %s/rigid %s/semi %s) vkt=%s CO2=%s NOx=%s carTL=%s attribDelay=%s "
          "dwell_h=%s nBlock=%s parcDel=%s noise=%s hvyLoc=%s"
          % (mix, civ(e["n_tours"], 1), civ(e.get("n_van"), 1), civ(e.get("n_rigid"), 1),
             civ(e.get("n_semi"), 1), civ(e["frt_vkt_km"], 1), civ(e["frt_CO2_kg"], 1),
             civ(e["frt_NOx_kg"], 3), civ(e["car_timeloss_h"], 1),
             civ(e["freight_attributable_car_delay_h"], 2), civ(e.get("frt_dwell_h"), 2),
             civ(e["n_blocking_stops"], 1), civ(e["parcels_delivered"], 0),
             civ(e["noise_local_dB"], 2), civ(e.get("hvy_vkm_local"), 1)))
print("  vs allvan (paired):")
for mix, e in R["H5"].get("_vs_allvan", {}).items():
    print("   %-11s " % mix + "  ".join("%s=%s" % (k, civ(v, 2)) for k, v in e.items()))

print("=" * 100)
print("H6  NIGHT SHIFTING")
for nf, e in R["H6"].items():
    print("  night=%3s%%  carTL=%s  frtDur=%s  personHrs=%s  savedVs0=%s  noiseLocDay/Night=%s/%s parcDel=%s"
          % (nf, civ(e["car_timeloss_h"], 1), civ(e["frt_duration_h"], 2),
             civ(e["person_hours"], 1), civ(e["car_timeloss_saved_h"], 2),
             civ(e.get("noise_local_day_dB"), 2), civ(e["noise_local_night_dB"], 2),
             civ(e["parcels_delivered"], 0)))

print("=" * 100)
print("H7  REACHABILITY FAILURE")
for k, e in R["H7"]["by_arm"].items():
    print("  %-12s unservable=%s (banned=%s no-path=%s trap=%s) toursNotEmitted=%s "
          "parcDel=%s parcUndel=%s (design=%s) stillRunning=%s"
          % (k, civ(e["addresses_unservable"], 1), civ(e.get("fail_banned"), 1),
             civ(e.get("fail_no_path"), 1), civ(e.get("fail_trap"), 1),
             civ(e["tours_not_emitted"], 1), civ(e["parcels_delivered"], 0),
             civ(e["parcels_undelivered"], 0), civ(e["parcels_by_design"], 0),
             civ(e["tours_still_running"], 1)))

print("=" * 100)
print("VALIDITY")
v = R["VALIDITY"]
print("  negative control identical:", v["negative_control"]["identical"],
      "seeds", v["negative_control"]["seeds"])
bad = [t for t in v["per_arm_group"] if t["teleport_contaminated"] or t["collisions_max"] > 0]
print("  arm groups with teleport contamination >2%% or any collision: %d" % len(bad))
for t in bad[:20]:
    print("   ", t["arm_group"], "tel=%.1f (%.3f%%)" % (t["teleports_mean"], t["teleport_share_pct"]),
          "coll=%.2f" % t["collisions_mean"])
mx = max(t["teleport_share_pct"] for t in v["per_arm_group"])
print("  max teleport share across all arm groups: %.4f%%" % mx)
print("  max emergency-braking events: %.1f" % max(t["emergency_braking_mean"] for t in v["per_arm_group"]))
print("  arm groups:", len(v["per_arm_group"]))
