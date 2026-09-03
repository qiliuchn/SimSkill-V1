#!/usr/bin/env python3
"""Emit the markdown tables used verbatim in FINDINGS.md, straight from the analysis
artifacts, so no number in the report is hand-transcribed."""
import csv
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ANA = os.path.abspath(os.path.join(HERE, "..", "analysis"))
VARIANTS = list("ABCDEF")
LABEL = {"A": "A baseline", "B": "B 20 km/h", "C": "C modal filter",
         "D": "D diverters", "E": "E one-way cells", "F": "F filter+20"}

agg = json.load(open(os.path.join(ANA, "variant_aggregate.json")))
out = []


def tbl(title, rows, header):
    out.append("### " + title + "\n")
    out.append("| " + " | ".join(header) + " |")
    out.append("|" + "|".join(["---"] * len(header)) + "|")
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    out.append("")


def row(metric, fmt="%.1f", pct=True, label=None):
    base = agg["A"][metric]
    cells = []
    for v in VARIANTS:
        x = agg[v][metric]
        s = fmt % x
        if pct and v != "A" and base:
            s += " (%+.1f%%)" % (100.0 * (x - base) / base)
        cells.append(s)
    return [label or metric] + cells


HDR = ["metric"] + [LABEL[v] for v in VARIANTS]

sel = json.load(open(os.path.join(ANA, "equilibrium_selection.json")))
tbl("Equilibrium of record and the DUE assignment plateau "
    "(cut-through veh-km over DUE iterations 12-24)",
    [[LABEL[v], sel[v]["cutthrough_vehkm_tail_mean"], sel[v]["cutthrough_vehkm_tail_sd"],
      "%.1f%%" % sel[v]["cv_pct"],
      "%.0f - %.0f" % (sel[v]["cutthrough_vehkm_tail_min"], sel[v]["cutthrough_vehkm_tail_max"]),
      sel[v]["selected_iteration"], sel[v]["selected_cutthrough_vehkm"],
      "" if v == "A" else "%+.1f%%" % (100 * (sel[v]["cutthrough_vehkm_tail_mean"] -
                                              sel["A"]["cutthrough_vehkm_tail_mean"]) /
                                       sel["A"]["cutthrough_vehkm_tail_mean"])]
     for v in VARIANTS],
    ["variant", "tail mean", "tail sd", "tail CV", "tail range", "selected iteration",
     "selected value", "tail mean vs A"])

tbl("Primary objective and interior exposure", [
    row("cutthrough_vehkm", "%.1f", True, "**cut-through veh-km on interior streets**"),
    row("cut_share_ee", "%.1f", True, "cut-through share of EE through-trips (%)"),
    row("cut_share_bg", "%.1f", True, "cut-through share of BG arterial trips (%)"),
    row("interior_vehkm_total", "%.1f", True, "total interior veh-km (all classes)"),
    row("resident_interior_vehkm", "%.1f", True, "resident/local interior veh-km"),
    row("interior_edge_vehkm_edgedata", "%.1f", True, "interior veh-km (edgeData cross-check)"),
    row("interior_mean_speed_ms", "%.2f", True, "interior mean speed (m/s)"),
    row("interior_max_street_vol", "%.0f", True, "busiest interior street (veh/h)"),
    row("interior_streets_used", "%.0f", True, "interior street-directions carrying >0 veh"),
    row("interior_volume_gini", "%.3f", True, "Gini of interior volume concentration"),
], HDR)

tbl("Boundary arterial burden and signal degradation", [
    row("ring_vehkm", "%.0f", True, "ring veh-km"),
    row("ring_vehh", "%.1f", True, "ring veh-hours"),
    row("ring_mean_speed_ms", "%.2f", True, "ring mean speed (m/s)"),
    row("ring_timeloss_vehh", "%.1f", True, "ring time loss (veh-h)"),
    row("signal_approach_waiting_vehh", "%.1f", True, "waiting time on signal approaches (veh-h)"),
    row("ring_max_edge_flow", "%.0f", True, "busiest ring link (veh/h)"),
], HDR)

tbl("System totals", [
    row("VKT_km", "%.0f", True, "total VKT (km)"),
    row("VHT_h", "%.1f", True, "total VHT (h, in-network)"),
    row("VHT_incl_departdelay_h", "%.1f", True, "total VHT incl. departure delay (h)"),
    row("net_CO2_kg", "%.1f", True, "network CO2 (kg)"),
    row("interior_CO2_kg", "%.1f", True, "interior-street CO2 (kg)"),
    row("net_NOx_g", "%.0f", True, "network NOx (g)"),
    row("interior_NOx_g", "%.0f", True, "interior-street NOx (g)"),
], HDR)

eq = []
for c, name in (("ee", "EE through (rat-runners)"), ("bg", "BG arterial background"),
                ("ei", "EI resident inbound"), ("ie", "IE resident outbound"),
                ("ii", "II local")):
    eq.append(row("dur_%s" % c, "%.0f", True, "%s - mean time (s)" % name))
    eq.append(row("dist_%s" % c, "%.0f", True, "%s - mean distance (m)" % name))
tbl("Equity: mean trip time AND distance by OD class", eq, HDR)

tbl("Rigor: accounting, teleports, seed noise", [
    row("completed_total", "%.0f", False, "completed vehicles (of 6096 loaded)"),
    row("still_running", "%.1f", False, "still running at sim end"),
    row("teleport_vehicles", "%.1f", False, "vehicles teleported (from sumo log)"),
    row("teleport_share_pct", "%.3f", False, "teleport-affected share of completed (%)"),
    ["seed sd of VHT (h)"] + ["%.2f" % agg[v]["VHT_h_sd"] for v in VARIANTS],
    ["seed sd of cut-through veh-km"] + ["%.2f" % agg[v]["cutthrough_vehkm_sd"] for v in VARIANTS],
], HDR)

ss = []
for v in VARIANTS:
    s = agg[v]["ssm"]
    ss.append([LABEL[v], s["net"]["conflicts"], s["net"]["ttc_lt_1p5"], s["net"]["min_ttc"],
               s["interior"]["conflicts"], s["interior"]["ttc_lt_1p5"],
               s["interior"]["min_ttc"], s["interior"]["pet_lt_1p0"]])
tbl("SSM safety proxy (seed 101, 25% of vehicles equipped)",
    ss, ["variant", "conflicts (net)", "TTC<1.5s (net)", "min TTC (net)",
         "conflicts (interior)", "TTC<1.5s (interior)", "min TTC (interior)",
         "PET<1.0s (interior)"])

# ---- cost-effectiveness: what each interior veh-km removed actually costs ----
ce = []
for v in VARIANTS:
    if v == "A":
        continue
    removed = agg["A"]["cutthrough_vehkm"] - agg[v]["cutthrough_vehkm"]
    d_ring = agg[v]["ring_timeloss_vehh"] - agg["A"]["ring_timeloss_vehh"]
    res_h = lambda vv: sum(agg[vv]["n_%s" % c] * agg[vv]["dur_%s" % c] / 3600.0
                           for c in ("ei", "ie", "ii"))
    thr_h = lambda vv: sum(agg[vv]["n_%s" % c] * agg[vv]["dur_%s" % c] / 3600.0
                           for c in ("ee", "bg"))
    d_res = res_h(v) - res_h("A")
    d_thr = thr_h(v) - thr_h("A")
    d_vht = agg[v]["VHT_h"] - agg["A"]["VHT_h"]
    ce.append([LABEL[v], "%.1f" % removed, "%.1f%%" % (100 * removed / agg["A"]["cutthrough_vehkm"]),
               "%+.1f" % d_ring, "%+.1f" % d_res, "%+.1f" % d_thr, "%+.1f" % d_vht,
               "%.3f" % (d_vht / removed) if removed > 0 else "n/a",
               "%.3f" % (d_res / removed) if removed > 0 else "n/a"])
tbl("Cost-effectiveness: what one interior veh-km of cut-through removed actually costs", ce,
    ["variant", "cut-through veh-km removed", "% removed", "d ring time loss (veh-h)",
     "d RESIDENT travel time (veh-h)", "d THROUGH travel time (veh-h)", "d system VHT (h)",
     "system veh-h per veh-km removed", "resident veh-h per veh-km removed"])

# ---- displacement accounting: where the removed veh-km actually went ----
da = []
for v in VARIANTS:
    if v == "A":
        continue
    d_int = agg[v]["interior_vehkm_total"] - agg["A"]["interior_vehkm_total"]
    d_ring = agg[v]["ring_vehkm"] - agg["A"]["ring_vehkm"]
    d_vkt = agg[v]["VKT_km"] - agg["A"]["VKT_km"]
    da.append([LABEL[v], "%+.1f" % d_int, "%+.1f" % d_ring, "%+.1f" % d_vkt,
               "%.2f" % (-d_ring / d_int) if d_int < 0 else "n/a",
               "%.1f%%" % (100 * agg[v]["completed_total"] / agg["A"]["completed_total"])])
tbl("Displacement accounting: veh-km removed from the interior vs added to the boundary", da,
    ["variant", "d interior veh-km", "d ring veh-km", "d total VKT",
     "ring veh-km ADDED per interior veh-km removed", "trips served vs A"])

acc = json.load(open(os.path.join(ANA, "emergency_access.json")))
ar = []
for v in VARIANTS:
    s = acc[v]
    ar.append([LABEL[v], s["passenger"]["mean_dist_m"], s["passenger"]["mean_ff_s"],
               s["emergency"]["mean_dist_m"], s["emergency"]["mean_ff_s"],
               "%+.2f" % s["paired_car_minus_ems"]["mean_ff_s"],
               s["paired_car_minus_ems"]["n_dest_worse"],
               "%+.2f" % s["passenger_vs_A"]["mean_ff_delta_s"],
               "%+.2f" % s["emergency_vs_A"]["mean_ff_delta_s"]])
tbl("Access cost: external depot -> 76 interior addresses (duarouter, free-flow weights)",
    ar, ["variant", "car dist (m)", "car time (s)", "ems dist (m)", "ems time (s)",
         "car-ems gap (s)", "# addresses where car is slower", "car vs A (s)", "ems vs A (s)"])

txt = "\n".join(out)
open(os.path.join(ANA, "findings_tables.md"), "w").write(txt)
print(txt)
