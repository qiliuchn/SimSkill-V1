#!/usr/bin/env python3
"""
PART A -- what SUMO's connection `visibility` attribute actually IS, what its
default actually IS, and what it geometrically means.

A1  DECELERATION-ONSET PROBE.  One minor-street vehicle, completely empty major
    road, YIELD control (junction type `priority`, so nothing forces a stop).
    From FCD we read the speed profile against distance-to-stop-line.  If the
    documented semantics ("distance to the connection below which an approaching
    vehicle has full sight of foes") are literal, the vehicle must behave as if a
    foe might be present until it is within `visibility` of the link, so its
    speed minimum should sit at distance ~= visibility from the stop line, and
    for visibility larger than the braking distance it should not slow at all.

A2  EMPIRICAL IDENTIFICATION OF THE DEFAULT.  Fine visibility sweep; find the
    explicit value whose speed profile / capacity reproduces the no-attribute
    (`vdefault`) net exactly.  The compiled .net.xml simply omits the attribute,
    so the default is otherwise invisible to anyone reading the network.

A3  DOES THE ATTRIBUTE DO ANYTHING ON A MAJOR LINK?  Build an otherwise
    identical net that ALSO puts visibility="7.5" on the two major approaches
    and compare -- the documentation claims "for major links the attribute has
    no effect".

Everything is written to outputs/raw/A_*.json / .csv.
"""
import csv
import json
import os
import shutil
import sys
import xml.etree.ElementTree as ET

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_nets  # noqa: E402
import sim  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NET = os.path.join(BASE, "net")
RAW = os.path.join(BASE, "raw")
WORK = os.path.join(BASE, "work")

FINE = [round(0.5 * i, 2) for i in range(1, 41)] + [25.0, 30.0, 40.0, 60.0, 90.0, 200.0]


def build_calib_nets():
    tags = []
    for v in FINE:
        t = "cal_y_%s" % ("%g" % v).replace(".", "_")
        build_nets.compile_net(t, "priority", v)
        tags.append((t, v))
    build_nets.compile_net("cal_y_default", "priority", None)
    tags.append(("cal_y_default", None))
    for v in FINE:
        t = "cal_s_%s" % ("%g" % v).replace(".", "_")
        build_nets.compile_net(t, "priority_stop", v)
    build_nets.compile_net("cal_s_default", "priority_stop", None)
    return tags


def build_majvis_net():
    """Same geometry, but visibility=7.5 also written on the MAJOR connections."""
    tag = "majvis_7_5"
    nod = os.path.join(NET, tag + ".nod.xml")
    edg = os.path.join(NET, tag + ".edg.xml")
    con = os.path.join(NET, tag + ".con.xml")
    build_nets.write_nodes(nod, "priority_stop")
    build_nets.write_edges(edg, build_nets.MAJ_SPEED)
    L = ['<?xml version="1.0" encoding="UTF-8"?>', "<connections>"]
    for f, t in build_nets.MINOR_CONNS + build_nets.MAJOR_CONNS:
        L.append('    <connection from="%s" to="%s" fromLane="0" toLane="0" '
                 'visibility="7.5000"/>' % (f, t))
    L.append("</connections>")
    open(con, "w").write("\n".join(L) + "\n")
    import subprocess
    cmd = [build_nets.find_bin("netconvert"), "--node-files", nod, "--edge-files", edg,
           "--connection-files", con, "--no-turnarounds", "true", "--tls.guess", "false",
           "--offset.disable-normalization", "true", "-o", os.path.join(NET, tag + ".net.xml")]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return tag


def fcd_profile(netname, cfg_extra=None):
    """Run a single minor probe vehicle on an empty net and return its FCD trace
    on min_in (distance-to-stop-line, speed)."""
    cfg = {"net": netname, "tag": "A_" + netname, "seed": 1, "major_mode": "none",
           "minor_mode": "single", "probe_depart": 20.0, "major_V": 0.0,
           "fcd": True, "fcd_period": 0.05, "step": 0.05}
    cfg.update(cfg_extra or {})
    r = sim.run(cfg, NET, WORK, freeflow=None, sim_end=200.0, gen_end=150.0,
                analysis=(0.0, 200.0))
    rundir, fcd = r["_rundir"], r["_fcd_path"]
    ni = sim.net_info(os.path.join(NET, netname + ".net.xml"))
    Lmin = ni["len"]["min_in"]
    rows = []
    # NOTE: clear ONLY the <timestep> elements.  Clearing every element on its own
    # end event wipes the <vehicle> attributes before the parent <timestep> end
    # event fires, silently yielding an empty trace.
    for _, el in ET.iterparse(fcd, events=("end",)):
        if el.tag != "timestep":
            continue
        t = float(el.get("time"))
        for v in el.findall("vehicle"):
            if v.get("id") != "probe":
                continue
            lane = v.get("lane")
            pos = float(v.get("pos"))
            spd = float(v.get("speed"))
            if lane.startswith("min_in"):
                rows.append((t, Lmin - pos, spd, "min_in"))
            elif lane.startswith(":C"):
                rows.append((t, -pos, spd, "internal"))
        el.clear()
    shutil.rmtree(rundir, ignore_errors=True)
    return rows, Lmin, ni


def summarize(rows):
    """Where does the probe slow down, how slow does it get, and where is the
    speed minimum measured from the stop line?"""
    on = [r for r in rows if r[3] == "min_in"]
    if not on:
        return None
    d = np.array([r[1] for r in on])
    s = np.array([r[2] for r in on])
    order = np.argsort(-d)          # far -> near
    d, s = d[order], s[order]
    vmax = float(s.max())
    imin = int(np.argmin(s))
    # first point (approaching) where speed drops 0.5 m/s below the cruise speed
    cruise = float(np.median(s[d > 150]))
    below = np.where((s < cruise - 0.5) & (d > 0))[0]
    onset_d = float(d[below[0]]) if below.size else None
    return {"cruise_speed": cruise, "max_speed": vmax,
            "min_speed": float(s[imin]), "d_at_min_speed": float(d[imin]),
            "decel_onset_dist_m": onset_d,
            "stopped": bool(s.min() < 0.1),
            "n_samples": int(d.size)}


def main():
    os.makedirs(RAW, exist_ok=True)
    os.makedirs(WORK, exist_ok=True)
    print("building calibration nets ...")
    build_calib_nets()
    majvis = build_majvis_net()

    # ---------------- A1 + A2 -------------------------------------------------
    prof = []
    for v in FINE + [None]:
        for ctrl, pre in (("yield", "cal_y"), ("stop", "cal_s")):
            tag = ("%s_%s" % (pre, ("%g" % v).replace(".", "_"))) if v is not None else pre + "_default"
            rows, Lmin, ni = fcd_profile(tag)
            s = summarize(rows)
            s.update({"control": ctrl, "visibility_set": v, "net": tag,
                      "min_in_length_m": Lmin,
                      "net_visibility_attr": ni["conn"][("min_in", "out_N", "0")]["visibility"]})
            prof.append(s)
            print("  %-18s vis=%-7s min_speed=%.3f @ d=%.2f m  onset=%s" %
                  (tag, v, s["min_speed"], s["d_at_min_speed"], s["decel_onset_dist_m"]))
    with open(os.path.join(RAW, "A_speed_profiles.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(prof[0].keys()))
        w.writeheader()
        w.writerows(prof)

    # capacity fingerprint for the same fine grid (yield + stop), used to pin the
    # default down a second, independent way
    ffy = sim.freeflow(NET, "cal_y_default", WORK)
    caps = []
    for v in FINE + [None]:
        for ctrl, pre in (("yield", "cal_y"), ("stop", "cal_s")):
            tag = ("%s_%s" % (pre, ("%g" % v).replace(".", "_"))) if v is not None else pre + "_default"
            r = sim.run({"net": tag, "tag": "Acap_" + tag, "seed": 11, "major_V": 800,
                         "minor_mode": "cap"}, NET, WORK, freeflow=ffy,
                        sim_end=1800.0, gen_end=1500.0, analysis=(300.0, 1500.0))
            caps.append({"control": ctrl, "visibility_set": v, "net": tag,
                         "cap_vph": r["minor_discharge_vph"],
                         "major_flow_vph": r["major_flow_vph_measured"],
                         "disch_hw_mean": r["minor_discharge_headway"]["mean"]})
    with open(os.path.join(RAW, "A_capacity_fingerprint.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(caps[0].keys()))
        w.writeheader()
        w.writerows(caps)

    # ---------------- A3 : does visibility do anything on MAJOR links? --------
    a3 = []
    ffm = sim.freeflow(NET, "stop_v7_5", WORK)
    for net, label in ((("stop_v7_5"), "minor_only_vis7.5"), ((majvis), "minor_AND_major_vis7.5")):
        for s in (11, 23, 37):
            r = sim.run({"net": net, "tag": "A3_%s_s%d" % (label, s), "seed": s,
                         "major_V": 800, "minor_mode": "cap"}, NET, WORK, freeflow=ffm)
            a3.append({"label": label, "net": net, "seed": s,
                       "cap_vph": r["minor_discharge_vph"],
                       "cap_late_vph": r["minor_discharge_late_vph"],
                       "major_flow_vph": r["major_flow_vph_measured"],
                       "maj_control_delay_mean": r["maj_control_delay"]["mean"]})
    with open(os.path.join(RAW, "A_major_link_visibility.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(a3[0].keys()))
        w.writeheader()
        w.writerows(a3)

    print("PART A done ->", RAW)
    shutil.rmtree(WORK, ignore_errors=True)


if __name__ == "__main__":
    main()
