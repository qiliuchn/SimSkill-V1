#!/usr/bin/env python3
"""
Analyze default-merge vs zipper-merge at an oversaturated 2->1 lane drop.

Metrics (recomputed from raw SUMO output; nothing hard-coded):
  1. Sustained bottleneck discharge throughput (veh/h) past the merge,
     measured on the single-lane 'bott' edge during the established-queue
     phase (transient startup excluded).
  2. Mean time loss / delay per vehicle (tripinfo timeLoss, plus duration,
     departDelay, and total delay = timeLoss+departDelay).
  3. Max upstream queue length (m), from per-interval edgeData speeds on the
     approach edges app3/app2/app1 (contiguous congested run from the merge).

Usage: python analyze.py <attempt_dir> <out_dir>
"""
import sys, csv, os
import xml.etree.ElementTree as ET

ATTEMPT = sys.argv[1]
OUTDIR  = sys.argv[2]
os.makedirs(OUTDIR, exist_ok=True)

# approach edges ordered from the merge going UPSTREAM, with compiled lengths
# (read from net.xml: app3=346, app2=350, app1=350 m)
APPROACH = [("app3", 346.0), ("app2", 350.0), ("app1", 350.0)]
CONG_SPEED = 8.0   # m/s; free-flow is 27.78, so <8 m/s (<~29 km/h) = in queue

def parse_edgedata(path):
    """Return list of dicts per interval: {begin, end, edges:{id:attribs}}."""
    tree = ET.parse(path); root = tree.getroot()
    out = []
    for iv in root.findall("interval"):
        edges = {}
        for e in iv.findall("edge"):
            edges[e.get("id")] = e.attrib
        out.append({"begin": float(iv.get("begin")),
                    "end": float(iv.get("end")), "edges": edges})
    return out

def discharge_series(ed):
    """Per-interval discharge veh/h past merge = vehicles ENTERING bott edge."""
    series = []
    for iv in ed:
        b = iv["edges"].get("bott")
        if b is None:
            series.append((iv["begin"], 0.0)); continue
        entered = float(b.get("entered", 0))
        dt = iv["end"] - iv["begin"]
        series.append((iv["begin"], entered * 3600.0 / dt))
    return series

def queue_series(ed):
    """Per-interval upstream queue length (m): contiguous congested approach
    edges starting at the merge. An edge counts as congested if its mean
    speed < CONG_SPEED. Stops at first non-congested edge (must be contiguous
    from the bottleneck)."""
    series = []
    for iv in ed:
        qlen = 0.0
        for eid, length in APPROACH:
            e = iv["edges"].get(eid)
            if e is None:
                break
            spd = float(e.get("speed", 999))
            samp = float(e.get("sampledSeconds", 0))
            if samp > 0 and spd < CONG_SPEED:
                qlen += length
            else:
                break
        series.append((iv["begin"], qlen))
    return series

def sustained_discharge(ed, qseries):
    """Mean discharge over the established-queue phase: intervals where the
    queue has backed up past the merge junction onto the approach (queue>0)
    AND inflow is still active (begin < 3600). Excludes startup ramp and the
    post-inflow drain-down so we measure true bottleneck capacity."""
    dser = discharge_series(ed)
    qmap = dict(qseries)
    vals = []
    detail = []
    for (t, q) in dser:
        if t < 3600 and qmap.get(t, 0) > 0 and t >= 300:  # queue present, inflow on, skip first 5 min
            vals.append(q if False else None)  # placeholder
    # collect discharge values on the sustained set
    disch = []
    for (t, d) in dser:
        if 300 <= t < 3600 and qmap.get(t, 0) > 0:
            disch.append(d)
            detail.append((t, d))
    mean = sum(disch)/len(disch) if disch else 0.0
    return mean, detail

def parse_tripinfo(path):
    tree = ET.parse(path); root = tree.getroot()
    tl, dur, dd, wt, n = 0.0, 0.0, 0.0, 0.0, 0
    for t in root.findall("tripinfo"):
        tl  += float(t.get("timeLoss"))
        dur += float(t.get("duration"))
        dd  += float(t.get("departDelay"))
        wt  += float(t.get("waitingTime"))
        n   += 1
    return {"n": n, "mean_timeLoss": tl/n, "mean_duration": dur/n,
            "mean_departDelay": dd/n, "mean_waitingTime": wt/n,
            "mean_total_delay": (tl+dd)/n}

runs = {}
for name in ("default", "zipper"):
    ed = parse_edgedata(os.path.join(ATTEMPT, f"edgedata_{name}.xml"))
    ti = parse_tripinfo(os.path.join(ATTEMPT, f"tripinfo_{name}.xml"))
    qser = queue_series(ed)
    dser = discharge_series(ed)
    sus_disch, sus_detail = sustained_discharge(ed, qser)
    max_q = max(q for _, q in qser)
    runs[name] = {"ti": ti, "qser": qser, "dser": dser,
                  "sus_disch": sus_disch, "max_q": max_q,
                  "n_sustained": len(sus_detail)}

# ---- comparison table ----
rows = [
    ("Metric", "default", "zipper", "zipper vs default"),
    ("Completed trips",
     runs["default"]["ti"]["n"], runs["zipper"]["ti"]["n"], "-"),
    ("Sustained discharge past merge (veh/h)",
     f'{runs["default"]["sus_disch"]:.1f}', f'{runs["zipper"]["sus_disch"]:.1f}',
     f'{(runs["zipper"]["sus_disch"]/runs["default"]["sus_disch"]-1)*100:+.1f}%'),
    ("Mean time loss (s/veh)",
     f'{runs["default"]["ti"]["mean_timeLoss"]:.1f}', f'{runs["zipper"]["ti"]["mean_timeLoss"]:.1f}',
     f'{(runs["zipper"]["ti"]["mean_timeLoss"]/runs["default"]["ti"]["mean_timeLoss"]-1)*100:+.1f}%'),
    ("Mean depart delay / insertion wait (s/veh)",
     f'{runs["default"]["ti"]["mean_departDelay"]:.1f}', f'{runs["zipper"]["ti"]["mean_departDelay"]:.1f}',
     f'{(runs["zipper"]["ti"]["mean_departDelay"]/runs["default"]["ti"]["mean_departDelay"]-1)*100:+.1f}%'),
    ("Mean total delay = timeLoss+departDelay (s/veh)",
     f'{runs["default"]["ti"]["mean_total_delay"]:.1f}', f'{runs["zipper"]["ti"]["mean_total_delay"]:.1f}',
     f'{(runs["zipper"]["ti"]["mean_total_delay"]/runs["default"]["ti"]["mean_total_delay"]-1)*100:+.1f}%'),
    ("Mean trip duration (s/veh)",
     f'{runs["default"]["ti"]["mean_duration"]:.1f}', f'{runs["zipper"]["ti"]["mean_duration"]:.1f}',
     f'{(runs["zipper"]["ti"]["mean_duration"]/runs["default"]["ti"]["mean_duration"]-1)*100:+.1f}%'),
    ("Max upstream queue length (m)",
     f'{runs["default"]["max_q"]:.0f}', f'{runs["zipper"]["max_q"]:.0f}',
     f'{(runs["zipper"]["max_q"]/runs["default"]["max_q"]-1)*100:+.1f}%' if runs["default"]["max_q"] else "-"),
]

csv_path = os.path.join(OUTDIR, "comparison_table.csv")
with open(csv_path, "w", newline="") as f:
    w = csv.writer(f); [w.writerow(r) for r in rows]

# markdown
md_path = os.path.join(OUTDIR, "comparison_table.md")
with open(md_path, "w") as f:
    f.write("| " + " | ".join(rows[0]) + " |\n")
    f.write("|" + "|".join(["---"]*len(rows[0])) + "|\n")
    for r in rows[1:]:
        f.write("| " + " | ".join(str(x) for x in r) + " |\n")

print(open(md_path).read())
print("\nSustained-phase intervals used (queue>0, 300<=t<3600):",
      runs["default"]["n_sustained"], "(default),",
      runs["zipper"]["n_sustained"], "(zipper)")

# ---- plot ----
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
    for name, color in (("default", "#d1495b"), ("zipper", "#0077b6")):
        d = runs[name]["dser"]; q = runs[name]["qser"]
        ax1.plot([t/60 for t, _ in d], [v for _, v in d], color=color, label=name, lw=1.5)
        ax2.plot([t/60 for t, _ in q], [v for _, v in q], color=color, label=name, lw=1.5)
    ax1.axhline(2400, ls="--", color="gray", lw=1, label="inflow 2400 veh/h")
    ax1.axvspan(0, 60, color="gray", alpha=0.06)
    ax1.set_ylabel("Discharge past merge (veh/h)")
    ax1.set_title("Bottleneck discharge over time (60 s intervals)")
    ax1.legend(fontsize=8); ax1.grid(alpha=0.3)
    ax2.set_ylabel("Upstream queue length (m)")
    ax2.set_xlabel("Time (min)")
    ax2.set_title("Upstream queue length over time (congested approach, speed<8 m/s)")
    ax2.legend(fontsize=8); ax2.grid(alpha=0.3)
    ax2.axvline(60, ls=":", color="k", lw=1)  # inflow ends at 60 min
    plt.tight_layout()
    png = os.path.join(OUTDIR, "discharge_and_queue.png")
    plt.savefig(png, dpi=110)
    print("\nSaved plot:", png)
except Exception as e:
    print("plot skipped:", e)

print("\nCSV:", csv_path)
