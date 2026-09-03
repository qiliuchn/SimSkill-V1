#!/usr/bin/env python3
"""
STEP 5/6 -- Price of Anarchy, and the departure-ordering confound diagnostic.

On the LINK network at a paradox-level demand, re-simulate the *same* vehicles with the
*same* scheduled departure times taken from duaIterate's converged route file, but with route
choice imposed externally instead of chosen selfishly:

  * share_zigzag = 0            -> the "coordinated" assignment that simply forbids the
                                   zig-zag route (i.e. behaves as if the cross link were not
                                   there, but on the network that HAS it)
  * share_zigzag = 0.1 ... 0.9  -> a one-parameter sweep to locate the best achievable
                                   (system-optimal-style) split on this network
  * share_zigzag = DUE's own converged share, but with route labels assigned round-robin in
    departure order -> the ORDERING-ARTIFACT diagnostic recommended by the
    compute-dynamic-user-equilibrium skill: same split, cleanly interleaved departures.

Assignment is done with a deterministic largest-remainder round-robin over vehicles sorted by
departure time, so every variant has identical demand, identical departure schedule and no
same-route departure bursts.
"""
import argparse
import csv
import json
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET

SUMO = shutil.which("sumo")
ROUTE_EDGES = {
    "upper_SAT": "S_in SA_a SA_b AT T_out",
    "lower_SBT": "S_in SB BT_a BT_b T_out",
    "zigzag": "S_in SA_a SA_b AB BT_a BT_b T_out",
}


def read_schedule(rou_xml):
    veh = []
    for v in ET.parse(rou_xml).getroot().iter("vehicle"):
        veh.append((v.get("id"), float(v.get("depart"))))
    veh.sort(key=lambda x: (x[1], x[0]))
    return veh


def interleave(n, shares):
    """Round-robin assignment of n items to labels with the given proportions (Bresenham)."""
    labels = list(shares)
    acc = {l: 0.0 for l in labels}
    out = []
    for _ in range(n):
        for l in labels:
            acc[l] += shares[l]
        pick = max(labels, key=lambda l: (acc[l], l))
        acc[pick] -= 1.0
        out.append(pick)
    return out


def write_routes(path, schedule, labels):
    with open(path, "w") as f:
        f.write('<routes>\n')
        for name in sorted(set(labels)):      # only routes actually used -- the NOLINK
            f.write(f'  <route id="{name}" '   # network has no AB edge, so the zig-zag
                    f'edges="{ROUTE_EDGES[name]}"/>\n')   # route must not be declared there
        for (vid, dep), lab in zip(schedule, labels):
            f.write(f'  <vehicle id="{vid}" depart="{dep:.2f}" route="{lab}" '
                    f'departLane="best" departSpeed="max"/>\n')
        f.write('</routes>\n')


def simulate(net, rou, out_dir, end_s, seed):
    os.makedirs(out_dir, exist_ok=True)
    cmd = [SUMO, "-n", os.path.abspath(net), "-r", os.path.abspath(rou),
           "--no-step-log", "true", "--seed", str(seed), "--time-to-teleport", "-1",
           "--end", str(end_s),
           "--tripinfo-output", os.path.join(out_dir, "tripinfo.xml"),
           "--statistic-output", os.path.join(out_dir, "stats.xml"),
           "--duration-log.statistics", "true"]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=out_dir)
    open(os.path.join(out_dir, "sumo.stderr"), "w").write(r.stderr)
    if r.returncode != 0:
        raise SystemExit(r.stderr)
    ts = list(ET.parse(os.path.join(out_dir, "tripinfo.xml")).getroot().iter("tripinfo"))
    dur = [float(t.get("duration")) for t in ts]
    dd = [float(t.get("departDelay", 0)) for t in ts]
    tel = 0
    st = ET.parse(os.path.join(out_dir, "stats.xml")).getroot().find("teleports")
    if st is not None:
        tel = int(st.get("total", 0))
    return {"n": len(ts), "mean_duration_s": round(sum(dur) / len(dur), 2),
            "mean_departDelay_s": round(sum(dd) / len(dd), 2),
            "mean_total_s": round(sum(d + e for d, e in zip(dur, dd)) / len(dur), 2),
            "teleports": tel}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", required=True)
    ap.add_argument("--due-case", required=True, help="work/due/gawron_link_<D> directory")
    ap.add_argument("--work", required=True)
    ap.add_argument("--out-csv", required=True)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--end-s", type=int, default=7200)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--nolink-net", help="NOLINK network, for the matched ordering-artifact control")
    ap.add_argument("--nolink-due-case", help="work/due/gawron_nolink_<D> directory")
    a = ap.parse_args()
    os.makedirs(a.work, exist_ok=True)

    conv_rou = os.path.join(a.due_case, "converged.rou.xml")
    sched = read_schedule(conv_rou)
    n = len(sched)

    # the DUE outcome itself (re-read from its simulation of record)
    due_stats = json.load(open(os.path.join(a.work, "due_stats.json"))) if os.path.exists(
        os.path.join(a.work, "due_stats.json")) else None
    ts = list(ET.parse(os.path.join(a.due_case, "record", "tripinfo.xml")).getroot().iter("tripinfo"))
    dur = [float(t.get("duration")) for t in ts]
    dd = [float(t.get("departDelay", 0)) for t in ts]
    due_stats = {"n": len(ts), "mean_duration_s": round(sum(dur) / len(dur), 2),
                 "mean_departDelay_s": round(sum(dd) / len(dd), 2),
                 "mean_total_s": round(sum(x + y for x, y in zip(dur, dd)) / len(dur), 2)}
    # DUE's own converged share of the zig-zag
    due_labels = {}
    for v in ET.parse(conv_rou).getroot().iter("vehicle"):
        r = v.find("route")
        e = r.get("edges").split() if r is not None else []
        due_labels[v.get("id")] = "zigzag" if "AB" in e else ("upper_SAT" if "AT" in e else "lower_SBT")
    due_zig = sum(1 for x in due_labels.values() if x == "zigzag") / n

    rows = []
    plist = [round(0.1 * i, 2) for i in range(0, 10)] + [round(due_zig, 4)]
    due_row_idx = len(plist) - 1
    for idx, p in enumerate(plist):
        shares = {"zigzag": p, "upper_SAT": (1 - p) / 2, "lower_SBT": (1 - p) / 2}
        labels = interleave(n, shares)
        tag = f"zig{p:.4f}"
        d = os.path.join(a.work, tag)
        rou = os.path.join(d, "forced.rou.xml")
        os.makedirs(d, exist_ok=True)
        write_routes(rou, sched, labels)
        res = simulate(a.net, rou, d, a.end_s, a.seed)
        act = {l: labels.count(l) / n for l in ROUTE_EDGES}
        rows.append({"assignment": ("DUE-share with interleaved departures"
                                    if idx == due_row_idx else f"forced zig-zag share {p:.0%}"),
                     "share_zigzag": round(act["zigzag"], 4),
                     "share_upper": round(act["upper_SAT"], 4),
                     "share_lower": round(act["lower_SBT"], 4), **res})
        print(rows[-1], flush=True)

    best = min(rows[:due_row_idx], key=lambda r: r["mean_total_s"])
    nozig = [r for r in rows if r["share_zigzag"] == 0][0]
    interleaved = rows[due_row_idx]
    out = {
        "demand_case": os.path.basename(a.due_case),
        "n_vehicles": n,
        "due_selfish": due_stats,
        "due_zigzag_share": round(due_zig, 4),
        "best_coordinated": best,
        "forced_no_zigzag": nozig,
        "due_share_but_interleaved_departures": interleaved,
        "price_of_anarchy_total_time": round(due_stats["mean_total_s"] / best["mean_total_s"], 4),
        "price_of_anarchy_innetwork": round(due_stats["mean_duration_s"] / best["mean_duration_s"], 4),
        "due_vs_forced_no_zigzag_pct": round(
            100 * (due_stats["mean_total_s"] - nozig["mean_total_s"]) / nozig["mean_total_s"], 2),
        "ordering_artifact_pct_of_due_total": round(
            100 * (due_stats["mean_total_s"] - interleaved["mean_total_s"]) / due_stats["mean_total_s"], 2),
    }
    with open(a.out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    # ---- matched ordering-artifact control on the NOLINK variant -------------------------
    # Re-simulate the NOLINK equilibrium's own split with the SAME clean interleaving, so that
    # LINK-vs-NOLINK can be compared with the departure-ordering effect removed from BOTH.
    if a.nolink_net and a.nolink_due_case:
        nl_rou = os.path.join(a.nolink_due_case, "converged.rou.xml")
        nl_sched = read_schedule(nl_rou)
        nl_lab = {}
        for v in ET.parse(nl_rou).getroot().iter("vehicle"):
            e = v.find("route").get("edges").split()
            nl_lab[v.get("id")] = "upper_SAT" if "AT" in e else "lower_SBT"
        p_up = sum(1 for x in nl_lab.values() if x == "upper_SAT") / len(nl_lab)
        nl_labels = interleave(len(nl_sched), {"upper_SAT": p_up, "lower_SBT": 1 - p_up})
        d = os.path.join(a.work, "nolink_interleaved")
        os.makedirs(d, exist_ok=True)
        rou = os.path.join(d, "forced.rou.xml")
        write_routes(rou, nl_sched, nl_labels)
        nl_res = simulate(a.nolink_net, rou, d, a.end_s, a.seed)
        ts = list(ET.parse(os.path.join(a.nolink_due_case, "record", "tripinfo.xml")).getroot().iter("tripinfo"))
        dur = [float(t.get("duration")) for t in ts]
        dd = [float(t.get("departDelay", 0)) for t in ts]
        nl_due = {"mean_duration_s": round(sum(dur) / len(dur), 2),
                  "mean_total_s": round(sum(x + y for x, y in zip(dur, dd)) / len(dur), 2)}
        out["nolink_due"] = nl_due
        out["nolink_due_share_interleaved"] = nl_res
        out["paradox_pct_as_simulated"] = round(
            100 * (due_stats["mean_total_s"] - nl_due["mean_total_s"]) / nl_due["mean_total_s"], 2)
        out["paradox_pct_both_interleaved"] = round(
            100 * (interleaved["mean_total_s"] - nl_res["mean_total_s"]) / nl_res["mean_total_s"], 2)

    json.dump(out, open(a.out_json, "w"), indent=2)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
