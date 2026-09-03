#!/usr/bin/env python3
"""Analyze diamond-interchange offset scenarios: internal-link E2 spillback,
E1 exit throughput, tripinfo delay/throughput, teleports. Emits a comparison
table (CSV + markdown) and a time-series plot of internal-link occupancy/jam."""
import os, sys, csv
import xml.etree.ElementTree as ET
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

RUN = "/Users/liuqi/Desktop/simskill/episodic-memory/2026-07-29_15-03-02/attempts/attempt-1/runs"
OUT = "/Users/liuqi/Desktop/simskill/episodic-memory/2026-07-29_15-03-02/outputs"
INTERNAL_LEN = 99.0   # E2 covers ~99 m of the 110 m link (stop-line to stop-line)
SCEN = [("coordinated", "Coordinated (offset E=7)"),
        ("uncoordinated", "Uncoordinated (offset E=52)")]

def parse_e2(path):
    """Return dict edge-group -> list of (time, meanOcc%, maxJamLen_m, meanVehNum)."""
    # group the two EB lanes (w_e_*) and two WB lanes (e_w_*)
    root = ET.parse(path).getroot()
    eb, wb = {}, {}   # time -> [jam vals], we aggregate per interval across the 2 lanes
    rows = {"EB": {}, "WB": {}}
    for iv in root.findall("interval"):
        det = iv.get("id"); t = float(iv.get("begin"))
        grp = "EB" if det.startswith("e2_we") else "WB"
        occ = float(iv.get("meanOccupancy", 0))
        jam = float(iv.get("jamLengthInMeters", iv.get("maxJamLengthInMeters", 0)))
        jam = max(jam, float(iv.get("maxJamLengthInMeters", 0)))
        veh = float(iv.get("nVehSeen", iv.get("meanVehicleNumber", 0)))
        d = rows[grp].setdefault(t, {"occ": [], "jam": [], "veh": []})
        d["occ"].append(occ); d["jam"].append(jam); d["veh"].append(veh)
    series = {}
    for grp in ("EB", "WB"):
        ts = sorted(rows[grp])
        series[grp] = {
            "t": ts,
            "occ": [sum(rows[grp][t]["occ"]) / len(rows[grp][t]["occ"]) for t in ts],
            "jam": [max(rows[grp][t]["jam"]) for t in ts],   # worst of the 2 lanes
            "veh": [sum(rows[grp][t]["veh"]) for t in ts],
        }
    return series

def parse_e1(path):
    root = ET.parse(path).getroot()
    tot = {}
    for iv in root.findall("interval"):
        det = iv.get("id")  # e1_exit_EB_0 etc
        key = det.replace("e1_exit_", "")[:-2]  # EB/WB/NB/SB
        tot[key] = tot.get(key, 0) + int(float(iv.get("nVehEntered", iv.get("entered", 0))))
    tot["ALL"] = sum(v for k, v in tot.items() if k != "ALL")
    return tot

def parse_tripinfo(path):
    root = ET.parse(path).getroot()
    n = 0; dur = wait = tl = 0.0
    for t in root.findall("tripinfo"):
        n += 1
        dur += float(t.get("duration")); wait += float(t.get("waitingTime"))
        tl += float(t.get("timeLoss"))
    return {"arrived": n, "mean_dur": dur / n, "mean_wait": wait / n, "mean_timeloss": tl / n}

def parse_summary(path):
    root = ET.parse(path).getroot()
    steps = root.findall("step")
    last = steps[-1]
    loaded = int(last.get("loaded")); inserted = int(last.get("inserted"))
    ended = int(last.get("ended")); tele = max(int(s.get("teleports")) for s in steps)
    running_peak = max(int(s.get("running")) for s in steps)
    return {"loaded": loaded, "inserted": inserted, "ended": ended,
            "teleports": tele, "running_peak": running_peak}

results = {}
for key, label in SCEN:
    d = os.path.join(RUN, key)
    e2 = parse_e2(os.path.join(d, "e2_internal.xml"))
    e1 = parse_e1(os.path.join(d, "e1_exits.xml"))
    ti = parse_tripinfo(os.path.join(d, "tripinfo.xml"))
    sm = parse_summary(os.path.join(d, "summary.xml"))
    # spillback metric (AUTHORITATIVE): frac of timesteps where the WORST of the 2 lanes
    # (per timestep) has jam >= link length - 5m (>=94m). Worst-of-2-lanes is used because a
    # queue filling EITHER lane blocks the upstream junction. (A per-lane-sample variant would
    # halve these values to 0.128/0.307 but understates junction blockage; not used.)
    spill_eb = max(e2["EB"]["jam"]); spill_wb = max(e2["WB"]["jam"])
    frac_eb_full = sum(1 for j in e2["EB"]["jam"] if j >= INTERNAL_LEN - 5) / len(e2["EB"]["jam"])
    frac_wb_full = sum(1 for j in e2["WB"]["jam"] if j >= INTERNAL_LEN - 5) / len(e2["WB"]["jam"])
    mean_occ_eb = sum(e2["EB"]["occ"]) / len(e2["EB"]["occ"])
    mean_occ_wb = sum(e2["WB"]["occ"]) / len(e2["WB"]["occ"])
    results[key] = dict(label=label, e2=e2, e1=e1, ti=ti, sm=sm,
                        spill_eb=spill_eb, spill_wb=spill_wb,
                        frac_eb_full=frac_eb_full, frac_wb_full=frac_wb_full,
                        mean_occ_eb=mean_occ_eb, mean_occ_wb=mean_occ_wb)

# ---- comparison table ----
metrics = [
    ("Internal EB mean occupancy %", lambda r: r["mean_occ_eb"], 2),
    ("Internal WB mean occupancy %", lambda r: r["mean_occ_wb"], 2),
    ("Internal EB max jam length m", lambda r: r["spill_eb"], 1),
    ("Internal WB max jam length m", lambda r: r["spill_wb"], 1),
    ("Frac time EB internal-link jam >= 94m, worst-of-2-lanes per timestep (spillback)", lambda r: r["frac_eb_full"], 3),
    ("Frac time WB internal-link jam >= 94m, worst-of-2-lanes per timestep (spillback)", lambda r: r["frac_wb_full"], 3),
    ("Exit throughput ALL (E1 nVehEntered)", lambda r: r["e1"]["ALL"], 0),
    ("Exit EB (E1)", lambda r: r["e1"].get("EB", 0), 0),
    ("Exit WB (E1)", lambda r: r["e1"].get("WB", 0), 0),
    ("Exit NB (E1)", lambda r: r["e1"].get("NB", 0), 0),
    ("Exit SB (E1)", lambda r: r["e1"].get("SB", 0), 0),
    ("Arrived vehicles (tripinfo)", lambda r: r["ti"]["arrived"], 0),
    ("Loaded (summary)", lambda r: r["sm"]["loaded"], 0),
    ("Inserted (summary)", lambda r: r["sm"]["inserted"], 0),
    ("Never-inserted (loaded-inserted)", lambda r: r["sm"]["loaded"] - r["sm"]["inserted"], 0),
    ("Incomplete (loaded-arrived)", lambda r: r["sm"]["loaded"] - r["ti"]["arrived"], 0),
    ("Mean duration s", lambda r: r["ti"]["mean_dur"], 1),
    ("Mean waiting time s", lambda r: r["ti"]["mean_wait"], 1),
    ("Mean time loss s (delay)", lambda r: r["ti"]["mean_timeloss"], 1),
    ("Teleports", lambda r: r["sm"]["teleports"], 0),
    ("Peak running vehicles", lambda r: r["sm"]["running_peak"], 0),
]
keys = [k for k, _ in SCEN]
lines = ["| Metric | " + " | ".join(results[k]["label"] for k in keys) + " |",
         "|" + "---|" * (len(keys) + 1)]
csv_rows = [["Metric"] + [results[k]["label"] for k in keys]]
for name, fn, nd in metrics:
    vals = [fn(results[k]) for k in keys]
    fmt = [f"{v:.{nd}f}" if isinstance(v, float) else str(v) for v in vals]
    lines.append(f"| {name} | " + " | ".join(fmt) + " |")
    csv_rows.append([name] + fmt)
table_md = "\n".join(lines)
print(table_md)
with open(os.path.join(OUT, "comparison_table.csv"), "w", newline="") as f:
    csv.writer(f).writerows(csv_rows)
with open(os.path.join(OUT, "comparison_table.md"), "w") as f:
    f.write(table_md + "\n")

# ---- plot internal-link occupancy + jam length over time ----
fig, ax = plt.subplots(2, 2, figsize=(13, 8), sharex=True)
colors = {"coordinated": "#1b9e77", "uncoordinated": "#d95f02"}
for key, label in SCEN:
    e2 = results[key]["e2"]; c = colors[key]
    ax[0][0].plot(e2["EB"]["t"], e2["EB"]["occ"], color=c, label=label, lw=1.2)
    ax[0][1].plot(e2["EB"]["t"], e2["EB"]["jam"], color=c, label=label, lw=1.2)
    ax[1][0].plot(e2["WB"]["t"], e2["WB"]["occ"], color=c, label=label, lw=1.2)
    ax[1][1].plot(e2["WB"]["t"], e2["WB"]["jam"], color=c, label=label, lw=1.2)
for a in (ax[0][1], ax[1][1]):
    a.axhline(INTERNAL_LEN, color="k", ls="--", lw=0.8, label="link length (spillback threshold)")
ax[0][0].set_title("Internal link EB (W->E): mean occupancy %")
ax[0][1].set_title("Internal link EB (W->E): max jam length (m)")
ax[1][0].set_title("Internal link WB (E->W): mean occupancy %")
ax[1][1].set_title("Internal link WB (E->W): max jam length (m)")
ax[1][0].set_xlabel("time (s)"); ax[1][1].set_xlabel("time (s)")
for row in ax:
    for a in row:
        a.grid(alpha=0.3); a.legend(fontsize=7)
fig.suptitle("Diamond interchange: short internal-link spillback vs signal offset", fontweight="bold")
fig.tight_layout()
fig.savefig(os.path.join(OUT, "internal_link_spillback.png"), dpi=130)
print("\nSaved plot -> internal_link_spillback.png")
print("Saved table -> comparison_table.csv / .md")
