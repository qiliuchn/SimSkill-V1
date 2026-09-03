"""Sharper test of the two open mechanism questions:

  (a) does a parking="true" bus's dwell disappear from the lane's traffic stream?
      -> clean-room test with ZERO car traffic, so laneData's sampledSeconds on the
         stop lane is attributable to the bus alone.
  (b) what governs a bay bus's RE-ENTRY? -> time from stop `ended` to first motion
      (speed > 0.1 m/s) and to 2 m/s, swept across car flow up to saturation on a
      single-lane section, plus stop-output's own `blockedDuration`.
  (c) is there any yield-to-bus rule? -> look for cars decelerating for a bus that
      is still parked, and scan SUMO's vType/junction-model parameter surface.
"""
import os
import sys
import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from scenario import Cfg, build_scenario, SUMO  # noqa: E402

ROOT = os.path.dirname(HERE)
RUNS = os.path.join(ROOT, "runs", "verify_reentry")
RES = os.path.join(ROOT, "results")


def run(cfg, outdir, seed):
    if os.path.isdir(outdir):
        shutil.rmtree(outdir)
    os.makedirs(outdir)
    sc = build_scenario(cfg, outdir, seed)
    ld = os.path.join(outdir, "meas.add.xml")
    open(ld, "w").write(
        '<additional>\n'
        f'  <laneData id="ld" file="{os.path.join(outdir, "lanedata.xml")}" '
        f'begin="0" end="{cfg.sim_end}" excludeEmpty="false"/>\n'
        '</additional>\n')
    opts = [SUMO, "-n", sc["net"], "-a", f'{sc["busstops"]},{ld}',
            "-r", f'{sc["cars"]},{sc["buses"]},{sc["persons"]}',
            "--tripinfo-output", os.path.join(outdir, "tripinfo.xml"),
            "--stop-output", os.path.join(outdir, "stopinfo.xml"),
            "--fcd-output", os.path.join(outdir, "fcd.xml"),
            "--fcd-output.attributes", "id,x,speed,lane,type",
            "--tripinfo-output.write-unfinished", "true",
            "--no-step-log", "true", "--time-to-teleport", "300",
            "--seed", str(seed), "-e", str(int(cfg.sim_end))]
    with open(os.path.join(outdir, "err.txt"), "w") as fe:
        r = subprocess.run(opts, stdout=subprocess.DEVNULL, stderr=fe)
    assert r.returncode == 0, open(os.path.join(outdir, "err.txt")).read()[-2000:]
    return sc


def read_fcd(outdir):
    prof = defaultdict(list)
    for _, el in ET.iterparse(os.path.join(outdir, "fcd.xml"), events=("end",)):
        if el.tag == "timestep":
            t = float(el.get("time"))
            for v in el:
                prof[v.get("id")].append((t, float(v.get("speed")),
                                          float(v.get("x")), v.get("lane"), v.get("type")))
            el.clear()
    return prof


def lane_seconds(outdir, lane_id):
    root = ET.parse(os.path.join(outdir, "lanedata.xml")).getroot()
    for iv in root.findall("interval"):
        for e in iv.findall("edge"):
            for ln in e.findall("lane"):
                if ln.get("id") == lane_id:
                    return float(ln.get("sampledSeconds"))
    return None


def analyse(outdir, stop_id, cfg):
    rows = [s.attrib for s in ET.parse(os.path.join(outdir, "stopinfo.xml")).getroot()
            if s.attrib.get("busStop") == stop_id]
    prof = read_fcd(outdir)
    ev = []
    for r in rows:
        bid, te = r["id"], float(r["ended"])
        seq = [(t, s) for t, s, *_ in prof.get(bid, []) if te - 2 <= t <= te + 120]
        t_move = next((t - te for t, s in seq if t >= te and s > 0.1), None)
        t_2 = next((t - te for t, s in seq if t >= te and s > 2.0), None)
        ev.append({"bus": bid, "ended": te, "dwell": float(r["ended"]) - float(r["started"]),
                   "blockedDuration": float(r.get("blockedDuration", 0) or 0),
                   "t_first_move": t_move, "t_to_2ms": t_2, "parking": r["parking"]})
    mv = [e["t_first_move"] for e in ev if e["t_first_move"] is not None]
    return {"n": len(ev), "mean_t_first_move": sum(mv) / len(mv) if mv else None,
            "max_t_first_move": max(mv) if mv else None,
            "p90_t_first_move": sorted(mv)[int(0.9 * (len(mv) - 1))] if mv else None,
            "mean_blocked": sum(e["blockedDuration"] for e in ev) / max(len(ev), 1),
            "events": ev}


if __name__ == "__main__":
    os.makedirs(RES, exist_ok=True)
    out = {}

    # ---- (a) clean room: no cars at all -------------------------------------
    clean = {}
    for stype in ("inlane", "bay"):
        cfg = Cfg(stop_placement="midblock", lanes_art=1, stop_type=stype,
                  q_art=0.0, q_cross=0.0, pax_rate=700.0, headway=180.0,
                  warmup=0.0, demand_end=1800.0, sim_end=3600.0)
        d = os.path.join(RUNS, f"clean_{stype}")
        sc = run(cfg, d, 5)
        st = sc["stops"][2]
        rows = [s.attrib for s in ET.parse(os.path.join(d, "stopinfo.xml")).getroot()
                if s.attrib.get("busStop") == st["id"]]
        dwell = sum(float(r["ended"]) - float(r["started"]) for r in rows)
        clean[stype] = {"lane": st["lane"], "lane_sampledSeconds": lane_seconds(d, st["lane"]),
                        "n_stop_events": len(rows), "total_dwell_at_stop": dwell,
                        "parking_attr": sorted({r["parking"] for r in rows})}
        os.remove(os.path.join(d, "fcd.xml"))
    clean["interpretation_delta"] = (clean["inlane"]["lane_sampledSeconds"]
                                     - clean["bay"]["lane_sampledSeconds"])
    clean["inlane_total_dwell"] = clean["inlane"]["total_dwell_at_stop"]
    out["clean_room"] = clean
    print("CLEAN ROOM (no cars):")
    for k in ("inlane", "bay"):
        print(f"  {k:7s} laneSec={clean[k]['lane_sampledSeconds']:.1f} "
              f"totalDwell={clean[k]['total_dwell_at_stop']:.1f} n={clean[k]['n_stop_events']}")
    print(f"  delta(laneSec) = {clean['interpretation_delta']:.1f} vs in-lane dwell "
          f"{clean['inlane_total_dwell']:.1f}")

    # ---- (b) re-entry vs car flow (single lane, up to saturation) ------------
    re = []
    for q in (0, 300, 600, 750, 900, 1000):
        for stype in ("bay", "inlane"):
            cfg = Cfg(stop_placement="midblock", lanes_art=1, stop_type=stype,
                      q_art=float(q), q_cross=150.0, pax_rate=700.0, headway=180.0,
                      warmup=600.0, demand_end=2400.0, sim_end=4800.0)
            d = os.path.join(RUNS, f"re_{stype}_{q}")
            sc = run(cfg, d, 5)
            st = sc["stops"][2]
            a = analyse(d, st["id"], cfg)
            os.remove(os.path.join(d, "fcd.xml"))
            re.append({"q_art": q, "type": stype,
                       **{k: v for k, v in a.items() if k != "events"},
                       "events": a["events"]})
            print(f"  q={q:5d} {stype:7s} n={a['n']:3d} meanFirstMove={a['mean_t_first_move']} "
                  f"p90={a['p90_t_first_move']} max={a['max_t_first_move']} "
                  f"meanBlocked={a['mean_blocked']:.2f}")
    out["reentry_sweep"] = re

    # ---- (c) parameter-surface scan for a yield-to-bus rule ------------------
    scan = {}
    h = subprocess.run([SUMO, "--help"], capture_output=True, text=True).stdout
    scan["sumo_help_lines_bus_or_yield"] = [l.strip() for l in h.splitlines()
                                            if "--" in l and ("bus" in l.lower() or "yield" in l.lower())]
    gp = subprocess.run(["grep", "-ril", "yield", os.path.join(os.environ["SUMO_HOME"], "data")],
                        capture_output=True, text=True).stdout.splitlines()
    scan["sumo_data_files_mentioning_yield"] = gp[:10]
    # vType junction-model attributes present in the XSD
    xsd = os.path.join(os.environ["SUMO_HOME"], "data", "xsd", "routeTypes.xsd")
    if os.path.exists(xsd):
        txt = open(xsd).read()
        scan["jm_attributes"] = sorted(set(
            w.split('"')[0] for w in txt.split('name="')[1:] if w.startswith("jm")))
        scan["has_bus_yield_attribute"] = any("bus" in a.lower() for a in scan["jm_attributes"])
    out["yield_rule_scan"] = scan
    print("\nyield-rule scan:", json.dumps(scan, indent=1)[:1200])

    json.dump(out, open(os.path.join(RES, "verify_reentry.json"), "w"), indent=1)
