#!/usr/bin/env python3
"""Consolidate every roundtrip.json into one fidelity CSV/JSON + a markdown table
classifying each attribute as PRESERVED / APPROXIMATE / LOST per network."""
import csv
import json
import os
import sys

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
NETS = ["grid", "roundabout", "osm"]
# variant reported as the representative OpenDRIVE result per network
BEST = {"grid": "default", "roundabout": "default", "osm": "all-lanes"}


def classify(a, b, rel_tol=0.02, abs_tol=1e-9):
    if a == b:
        return "PRESERVED"
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if a and abs(b - a) / abs(a) <= rel_tol:
            return "APPROXIMATE"
        if abs(b - a) <= abs_tol:
            return "PRESERVED"
    return "LOST/CHANGED"


rows = []
allj = {}
for n in NETS:
    p = os.path.join(BASE, "convert", n + "_roundtrip.json")
    if not os.path.exists(p):
        continue
    d = json.load(open(p))
    allj[n] = d
    for vname, rec in d["variants"].items():
        if "diff" not in rec:
            continue
        di = rec["diff"]
        o, r, m, t = di["orig"], di["roundtrip"], di["matching"], di["tls"]
        rows.append({
            "network": n, "variant": vname, "score": rec.get("score"),
            "opts": " ".join(rec["opts"]),
            "edges_o": o["edges"], "edges_r": r["edges"],
            "lanes_o": o["lanes"], "lanes_r": r["lanes"],
            "conns_o": o["connections"], "conns_r": r["connections"],
            "junc_o": o["junctions_total"], "junc_r": r["junctions_total"],
            "tls_o": o["tlLogic"], "tls_r": r["tlLogic"],
            "tls_phasestrings_identical": t["state_strings_identical"],
            "roundabout_o": o["roundabout_decls"], "roundabout_r": r["roundabout_decls"],
            "lane_km_o": o["lane_km"], "lane_km_r": r["lane_km"],
            "car_lane_km_o": o["lane_km_by_role"]["car"],
            "car_lane_km_r": r["lane_km_by_role"]["car"],
            "pedbike_lane_km_o": round(o["lane_km_by_role"]["ped_only"] +
                                       o["lane_km_by_role"]["bike_only"] +
                                       o["lane_km_by_role"]["ped_or_bike_only"], 4),
            "pedbike_lane_km_r": round(r["lane_km_by_role"]["ped_only"] +
                                       r["lane_km_by_role"]["bike_only"] +
                                       r["lane_km_by_role"]["ped_or_bike_only"], 4),
            "blocked_lane_km_r": r["lane_km_by_role"]["blocked"],
            "edge_match_rate": m["edge_match_rate"],
            "junction_match_rate": m["junction_match_rate"],
            "junction_offset_mean_m": m["junction_offset_m"].get("mean"),
            "junction_offset_max_m": m["junction_offset_m"].get("max"),
            "edge_len_median_pct": m["edge_len_diff_pct"].get("median"),
            "edge_len_p90_pct": m["edge_len_diff_pct"].get("p90"),
            "edges_len_exact": m["edge_len_exact_(<0.01m)"],
            "speed_exact": m["edge_speed_exact"],
            "warnings": sum(rec.get("messages", {}).values()),
        })

out_csv = os.path.join(BASE, "results", "fidelity_table.csv")
os.makedirs(os.path.dirname(out_csv), exist_ok=True)
with open(out_csv, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

# per-attribute PRESERVED/APPROXIMATE/LOST verdict for the representative variant
ATTRS = [
    ("edge count", lambda o, r, m, t: (o["edges"], r["edges"])),
    ("lane count", lambda o, r, m, t: (o["lanes"], r["lanes"])),
    ("connection count", lambda o, r, m, t: (o["connections"], r["connections"])),
    ("junction count", lambda o, r, m, t: (o["junctions_total"], r["junctions_total"])),
    ("total lane-km", lambda o, r, m, t: (o["lane_km"], r["lane_km"])),
    ("car-usable lane-km", lambda o, r, m, t: (o["lane_km_by_role"]["car"], r["lane_km_by_role"]["car"])),
    ("ped/bike lane-km", lambda o, r, m, t: (
        round(o["lane_km_by_role"]["ped_only"] + o["lane_km_by_role"]["bike_only"] +
              o["lane_km_by_role"]["ped_or_bike_only"], 3),
        round(r["lane_km_by_role"]["ped_only"] + r["lane_km_by_role"]["bike_only"] +
              r["lane_km_by_role"]["ped_or_bike_only"], 3))),
    ("edge speed limits", lambda o, r, m, t: (m["edges_matched"], m["edge_speed_exact"])),
    ("edge priority", lambda o, r, m, t: (len(o["edge_priority_hist"]), len(r["edge_priority_hist"]))),
    ("street names", lambda o, r, m, t: (o["edges_with_name"], r["edges_with_name"])),
    ("roundabout declarations", lambda o, r, m, t: (o["roundabout_decls"], r["roundabout_decls"])),
    ("tlLogic count", lambda o, r, m, t: (o["tlLogic"], r["tlLogic"])),
    ("tlLogic phase strings", lambda o, r, m, t: (o["tlLogic"], t["state_strings_identical"])),
]
md = ["| network | attribute | original | round-trip | verdict |", "|---|---|---|---|---|"]
verdicts = {}
for n in NETS:
    if n not in allj:
        continue
    rec = allj[n]["variants"][BEST[n]]
    di = rec["diff"]
    o, r, m, t = di["orig"], di["roundtrip"], di["matching"], di["tls"]
    for label, fn in ATTRS:
        a, b = fn(o, r, m, t)
        v = classify(a, b)
        md.append(f"| {n} | {label} | {a} | {b} | {v} |")
        verdicts.setdefault(n, {})[label] = [a, b, v]

json.dump({"per_variant": rows, "verdicts": verdicts, "representative_variant": BEST},
          open(os.path.join(BASE, "results", "fidelity.json"), "w"), indent=1)
print("\n".join(md))
print("\nwrote", out_csv, "and results/fidelity.json")
