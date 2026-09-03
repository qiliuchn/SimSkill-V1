#!/usr/bin/env python3
"""Analyze DDI vs conventional-diamond runs (ATTEMPT-2, corrected).

Same analysis as attempt-1, with ONE bug fixed: parse_tripinfo() now distinguishes
COMPLETED trips (arrival >= 0) from STILL-RUNNING / INCOMPLETE trips
(arrival == -1, present in tripinfo.xml only because run_sims.py passed
--tripinfo-output.write-unfinished true). Attempt-1 counted every record as
"arrived", silently inflating throughput. This version reports completed vs
incomplete separately for both the overall population and the heavy-left subset.

DELAY numbers are intentionally left as attempt-1 computed them (over ALL records,
which include the partial time-loss accrued by unfinished vehicles up to the
1200 s cutoff). Those figures were independently verified correct by the critic
(overall 60.3/70.6 s, heavy-left 34.9/171.0 s) and are NOT re-derived here. For
transparency the script ALSO reports the completed-subset heavy-left delay so the
reader can confirm the DDI advantage holds on genuinely-arrived vehicles too.

Reads RAW simulation outputs from attempt-1 (never re-runs SUMO); writes corrected
comparison_table.csv/.md into attempt-2/outputs/.

Control-delay proxy = tripinfo timeLoss (s). HEAVY LEFT vehicles identified BY ROUTE:
flow ids 'WB_left' (west terminal, WB->SB on-ramp) and 'EB_left' (east terminal, EB->NB on-ramp)."""
import os, csv
import xml.etree.ElementTree as ET

A1 = "/Users/liuqi/Desktop/simskill/episodic-memory/2026-07-30_09-43-42/attempts/attempt-1"
A2 = "/Users/liuqi/Desktop/simskill/episodic-memory/2026-07-30_09-43-42/attempts/attempt-2"
RUNS = os.path.join(A1, "runs")          # raw sim data (verified, reused unchanged)
IN_OUT = os.path.join(A1, "outputs")     # tll files to read
OUT = os.path.join(A2, "outputs")        # corrected deliverables written here
SCEN = [("ddi", "DDI (2-phase, unopposed lefts)"),
        ("conv", "Conventional diamond (3-phase, protected left)")]
LEFT_FLOWS = {"WB_left", "EB_left"}
THROUGH_FLOWS = {"EB_through", "WB_through"}


def flow_of(vid):
    return vid.rsplit(".", 1)[0]


def parse_tripinfo(path):
    """Return per-flow and overall stats.

    A tripinfo record is COMPLETED iff arrival >= 0; arrival == -1 marks a vehicle
    still en route at the simulation cutoff (written only because of
    --tripinfo-output.write-unfinished). Delay stats are kept over ALL records to
    preserve the verified attempt-1 delay figures; completion counts filter on arrival.
    """
    root = ET.parse(path).getroot()
    groups = {}   # flow -> dict of lists / counts
    overall = {"timeloss": [], "dur": [], "wait": []}
    left = {"timeloss": [], "dur": [], "wait": []}
    left_completed = {"timeloss": [], "wait": []}   # arrival >= 0 subset (transparency)
    n_records = 0
    n_completed = 0            # overall arrival >= 0
    left_records = 0
    left_completed_n = 0       # heavy-left arrival >= 0
    for t in root.findall("tripinfo"):
        fl = flow_of(t.get("id"))
        tl = float(t.get("timeLoss")); dur = float(t.get("duration")); w = float(t.get("waitingTime"))
        arrival = float(t.get("arrival"))
        completed = arrival >= 0.0
        n_records += 1
        if completed:
            n_completed += 1
        g = groups.setdefault(fl, {"timeloss": [], "dur": [], "wait": [], "n": 0, "completed": 0})
        g["timeloss"].append(tl); g["dur"].append(dur); g["wait"].append(w); g["n"] += 1
        if completed:
            g["completed"] += 1
        overall["timeloss"].append(tl); overall["dur"].append(dur); overall["wait"].append(w)
        if fl in LEFT_FLOWS:
            left["timeloss"].append(tl); left["dur"].append(dur); left["wait"].append(w)
            left_records += 1
            if completed:
                left_completed_n += 1
                left_completed["timeloss"].append(tl); left_completed["wait"].append(w)

    def m(x):
        return sum(x) / len(x) if x else 0.0
    per_flow = {fl: {"n": g["n"], "completed": g["completed"],
                     "mean_timeloss": m(g["timeloss"]),
                     "mean_dur": m(g["dur"]), "mean_wait": m(g["wait"])}
                for fl, g in groups.items()}
    return {
        "per_flow": per_flow,
        # ---- delay (over all records, matches verified attempt-1 numbers) ----
        "overall_mean_timeloss": m(overall["timeloss"]),
        "overall_mean_dur": m(overall["dur"]),
        "overall_mean_wait": m(overall["wait"]),
        "left_mean_timeloss": m(left["timeloss"]),
        "left_mean_dur": m(left["dur"]),
        "left_mean_wait": m(left["wait"]),
        # ---- completion counts (FIXED: filter arrival >= 0) ----
        "records": n_records,                 # all tripinfo records (incl. unfinished)
        "arrived": n_completed,               # genuinely completed (arrival >= 0)
        "incomplete": n_records - n_completed,  # still running at cutoff (arrival == -1)
        "left_records": left_records,         # heavy-left records total
        "left_arrived": left_completed_n,     # heavy-left completed (arrival >= 0)
        "left_incomplete": left_records - left_completed_n,
        # ---- heavy-left delay on completed subset (transparency check) ----
        "left_completed_mean_timeloss": m(left_completed["timeloss"]),
        "left_completed_mean_wait": m(left_completed["wait"]),
    }


def parse_summary(path):
    root = ET.parse(path).getroot()
    steps = root.findall("step")
    last = steps[-1]
    loaded = int(last.get("loaded")); inserted = int(last.get("inserted"))
    arrived = int(last.get("arrived")); running = int(last.get("running"))
    teleports = max(int(s.get("teleports")) for s in steps)
    running_peak = max(int(s.get("running")) for s in steps)
    return {"loaded": loaded, "inserted": inserted, "arrived": arrived,
            "running_final": running, "teleports": teleports, "running_peak": running_peak}


def parse_e1(path):
    """Sum nVehEntered over all intervals, grouped by detector name (strip lane suffix)."""
    root = ET.parse(path).getroot()
    tot = {}
    for iv in root.findall("interval"):
        did = iv.get("id")            # e1_onramp_SB_0 / e1_exit_EB_1 ...
        name = did.rsplit("_", 1)[0]  # e1_onramp_SB / e1_exit_EB
        tot[name] = tot.get(name, 0) + int(float(iv.get("nVehEntered", 0)))
    return tot


results = {}
for key, label in SCEN:
    d = os.path.join(RUNS, key)
    ti = parse_tripinfo(os.path.join(d, "tripinfo.xml"))
    sm = parse_summary(os.path.join(d, "summary.xml"))
    e1 = parse_e1(os.path.join(d, "e1_out.xml"))
    results[key] = {"label": label, "ti": ti, "sm": sm, "e1": e1}

# ---------------- comparison table ----------------
keys = [k for k, _ in SCEN]

def onramp_total(e1):
    return e1.get("e1_onramp_SB", 0) + e1.get("e1_onramp_NB", 0)

def pct(a, b):
    return 100.0 * a / b if b else 0.0

metrics = [
    ("Signal phases per terminal (green intervals)", lambda r: PHASES[r["_k"]], 0),
    ("-- DELAY (control-delay proxy = tripinfo timeLoss, s; over all records) --", None, None),
    ("Overall mean delay (timeLoss) s", lambda r: r["ti"]["overall_mean_timeloss"], 1),
    ("HEAVY-LEFT mean delay (timeLoss) s", lambda r: r["ti"]["left_mean_timeloss"], 1),
    ("HEAVY-LEFT mean waiting time s", lambda r: r["ti"]["left_mean_wait"], 1),
    ("Overall mean waiting time s", lambda r: r["ti"]["overall_mean_wait"], 1),
    ("HEAVY-LEFT mean delay, COMPLETED subset only s", lambda r: r["ti"]["left_completed_mean_timeloss"], 1),
    ("WB_left (west term) mean delay s", lambda r: r["ti"]["per_flow"].get("WB_left", {}).get("mean_timeloss", 0), 1),
    ("EB_left (east term) mean delay s", lambda r: r["ti"]["per_flow"].get("EB_left", {}).get("mean_timeloss", 0), 1),
    ("EB_through mean delay s", lambda r: r["ti"]["per_flow"].get("EB_through", {}).get("mean_timeloss", 0), 1),
    ("WB_through mean delay s", lambda r: r["ti"]["per_flow"].get("WB_through", {}).get("mean_timeloss", 0), 1),
    ("-- THROUGHPUT / COMPLETION (arrival >= 0 = completed; arrival == -1 = still running at cutoff) --", None, None),
    ("Loaded (summary)", lambda r: r["sm"]["loaded"], 0),
    ("Arrived / completed (arrival >= 0)", lambda r: r["ti"]["arrived"], 0),
    ("Still running / incomplete at cutoff (arrival == -1)", lambda r: r["ti"]["incomplete"], 0),
    ("Overall completion rate %", lambda r: pct(r["ti"]["arrived"], r["sm"]["loaded"]), 1),
    ("HEAVY-LEFT loaded (WB_left+EB_left records)", lambda r: r["ti"]["left_records"], 0),
    ("HEAVY-LEFT completed (arrival >= 0)", lambda r: r["ti"]["left_arrived"], 0),
    ("HEAVY-LEFT still running at cutoff (arrival == -1)", lambda r: r["ti"]["left_incomplete"], 0),
    ("HEAVY-LEFT completion rate %", lambda r: pct(r["ti"]["left_arrived"], r["ti"]["left_records"]), 1),
    ("  WB_left completed", lambda r: r["ti"]["per_flow"].get("WB_left", {}).get("completed", 0), 0),
    ("  EB_left completed", lambda r: r["ti"]["per_flow"].get("EB_left", {}).get("completed", 0), 0),
    ("E1 on-ramp throughput SB+NB (nVehEntered)", lambda r: onramp_total(r["e1"]), 0),
    ("  E1 on-ramp SB", lambda r: r["e1"].get("e1_onramp_SB", 0), 0),
    ("  E1 on-ramp NB", lambda r: r["e1"].get("e1_onramp_NB", 0), 0),
    ("E1 exit EB", lambda r: r["e1"].get("e1_exit_EB", 0), 0),
    ("E1 exit WB", lambda r: r["e1"].get("e1_exit_WB", 0), 0),
    ("E1 exit SB freeway", lambda r: r["e1"].get("e1_exit_SB", 0), 0),
    ("E1 exit NB freeway", lambda r: r["e1"].get("e1_exit_NB", 0), 0),
    ("-- LOADING / FAILURE --", None, None),
    ("Inserted (summary)", lambda r: r["sm"]["inserted"], 0),
    ("Never-inserted (loaded-inserted)", lambda r: r["sm"]["loaded"] - r["sm"]["inserted"], 0),
    ("Teleports", lambda r: r["sm"]["teleports"], 0),
    ("Peak running vehicles", lambda r: r["sm"]["running_peak"], 0),
]

# phases per terminal (green intervals), read from tll (2 for ddi, 3 for conv)
PHASES = {}
for k in keys:
    tll = ET.parse(os.path.join(IN_OUT, f"{k}.tll.xml")).getroot()
    logic = tll.find("tlLogic")
    ng = sum(1 for p in logic.findall("phase") if "G" in p.get("state") or "g" in p.get("state"))
    PHASES[k] = ng
for k in keys:
    results[k]["_k"] = k

lines = ["| Metric | " + " | ".join(results[k]["label"] for k in keys) + " | Winner |",
         "|" + "---|" * (len(keys) + 2)]
csv_rows = [["Metric"] + [results[k]["label"] for k in keys] + ["Winner"]]
for name, fn, nd in metrics:
    if fn is None:
        lines.append(f"| **{name}** | | | |")
        csv_rows.append([name, "", "", ""])
        continue
    vals = [fn(results[k]) for k in keys]
    fmt = [f"{v:.{nd}f}" if isinstance(v, float) else str(v) for v in vals]
    # winner heuristic: delay/wait/teleport/incomplete/never-inserted/phases lower better; else higher better
    lower_better = any(w in name.lower() for w in ["delay", "waiting", "teleport", "never-inserted",
                                                   "still running", "incomplete", "phases"])
    try:
        v0, v1 = float(vals[0]), float(vals[1])
        if v0 == v1:
            win = "tie"
        elif lower_better:
            win = "DDI" if v0 < v1 else "Conv"
        else:
            win = "DDI" if v0 > v1 else "Conv"
    except Exception:
        win = ""
    lines.append(f"| {name} | " + " | ".join(fmt) + f" | {win} |")
    csv_rows.append([name] + fmt + [win])

table_md = "\n".join(lines)
print(table_md)
with open(os.path.join(OUT, "comparison_table.csv"), "w", newline="") as f:
    csv.writer(f).writerows(csv_rows)
with open(os.path.join(OUT, "comparison_table.md"), "w") as f:
    f.write("# DDI vs Conventional Diamond - comparison (attempt-2, completion-corrected)\n\n"
            "> Throughput now distinguishes COMPLETED trips (tripinfo arrival >= 0) from vehicles\n"
            "> STILL RUNNING at the 1200 s cutoff (arrival == -1, present only because SUMO was run\n"
            "> with --tripinfo-output.write-unfinished true). Delay figures are unchanged from the\n"
            "> verified attempt-1 analysis (computed over all records).\n\n" + table_md + "\n")

# ---------------- transparency print ----------------
print("\n--- completion / delay reconciliation ---")
for k in keys:
    ti = results[k]["ti"]
    print(f"{k}: overall {ti['arrived']}/{results[k]['sm']['loaded']} completed "
          f"({ti['incomplete']} still running); "
          f"heavy-left {ti['left_arrived']}/{ti['left_records']} completed "
          f"({ti['left_incomplete']} still running); "
          f"heavy-left delay all={ti['left_mean_timeloss']:.1f}s completed-only={ti['left_completed_mean_timeloss']:.1f}s; "
          f"teleports={results[k]['sm']['teleports']}")
print("Saved table -> comparison_table.csv / .md")
