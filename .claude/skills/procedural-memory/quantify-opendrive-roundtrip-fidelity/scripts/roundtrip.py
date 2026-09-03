#!/usr/bin/env python3
"""
roundtrip.py -- SUMO network format round-trip driver + import-option sweep.

For each source .net.xml:
  1. export  : netconvert --sumo-net-file NET --opendrive-output NET.xodr
  2. reimport: netconvert --opendrive-files NET.xodr -o NET_<variant>_rt.net.xml
               for every variant in the option sweep
  3. diff    : scripts/netdiff.py  (geometric matching, IDs are not preserved)
  4. control : plain-XML round trip (--plain-output-prefix then recompile)
  5. also emits MATSiM / dlr-navteq to show the wider format landscape

All netconvert stderr is CAPTURED and summarised (warning classes + counts), never
discarded -- the warnings are the main diagnostic for what a conversion dropped.

Usage:
    python roundtrip.py --net ../nets/grid.net.xml --name grid --out-dir ../convert
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import netdiff  # noqa: E402


def find_bin(name):
    f = shutil.which(name)
    if f:
        return f
    s = shutil.which("sumo")
    if s and os.path.isfile(os.path.join(os.path.dirname(s), name)):
        return os.path.join(os.path.dirname(s), name)
    sh = os.environ.get("SUMO_HOME")
    if sh and os.path.isfile(os.path.join(sh, "bin", name)):
        return os.path.join(sh, "bin", name)
    sys.exit("cannot find " + name)


NETCONVERT = find_bin("netconvert")


def run(args, log):
    p = subprocess.run([NETCONVERT] + args, capture_output=True, text=True)
    txt = (p.stdout or "") + (p.stderr or "")
    open(log, "w").write(" ".join([NETCONVERT] + args) + "\n\n" + txt)
    return p.returncode, txt


def classify(txt):
    """Collapse netconvert messages into (class -> count). Handles both the
    per-instance form and netconvert's own 'N total messages of type: X' rollup."""
    c = Counter()
    for line in txt.splitlines():
        line = line.strip()
        m = re.match(r"Warning: (\d+) total messages of type: (.*)", line)
        if m:
            c[m.group(2)[:90]] += int(m.group(1))
            continue
        for pfx in ("Warning: ", "Error: "):
            if line.startswith(pfx):
                body = line[len(pfx):]
                # strip ids/numbers so instances collapse into one class
                body = re.sub(r"'[^']*'", "'%'", body)
                body = re.sub(r"[-+]?\d*\.?\d+", "#", body)
                c[pfx.strip(": ") + ": " + body[:90]] += 1
    return dict(c.most_common())


# ---- the import-option sweep -------------------------------------------------
VARIANTS = [
    ("default",            []),
    ("all-lanes",          ["--opendrive.import-all-lanes"]),
    ("internal-shapes",    ["--opendrive.internal-shapes"]),
    ("curve-res-0.5",      ["--opendrive.curve-resolution", "0.5"]),
    ("curve-res-10",       ["--opendrive.curve-resolution", "10"]),
    ("advance-stopline-20", ["--opendrive.advance-stopline", "20"]),
    ("ignore-widths",      ["--opendrive.ignore-widths"]),
    ("lane-shapes",        ["--opendrive.lane-shapes"]),
    ("geometry-remove",    ["--geometry.remove"]),
    ("junctions-join",     ["--junctions.join"]),
    ("tls-guess-signals",  ["--tls.guess-signals"]),
    ("signal-groups",      ["--opendrive.signal-groups"]),
    ("combo-geom",         ["--opendrive.internal-shapes",
                            "--opendrive.curve-resolution", "0.5"]),
    ("combo-alllanes-geom", ["--opendrive.import-all-lanes",
                             "--opendrive.internal-shapes",
                             "--opendrive.curve-resolution", "0.5"]),
    ("combo-best",         ["--opendrive.import-all-lanes",
                            "--opendrive.internal-shapes",
                            "--opendrive.curve-resolution", "0.5",
                            "--opendrive.advance-stopline", "20",
                            "--junctions.join", "--tls.guess-signals",
                            "--no-turnarounds"]),
    ("combo-best-nojoin",  ["--opendrive.import-all-lanes",
                            "--opendrive.internal-shapes",
                            "--opendrive.curve-resolution", "0.5",
                            "--opendrive.advance-stopline", "20",
                            "--no-turnarounds"]),
]


def score(d):
    """Composite fidelity score in [0,1]; higher = closer reconstruction.
    Deliberately includes signal-PROGRAM and lane-ROLE fidelity, not just
    topology counts -- a topology-only score saturates at 1.0 on the synthetic
    nets and hides the fact that the signal plan was silently regenerated."""
    m, o, r, t = d["matching"], d["orig"], d["roundtrip"], d["tls"]
    s = {}
    s["edge_match"] = m["edge_match_rate"]
    s["junction_match"] = m["junction_match_rate"]
    s["lane_km"] = max(0.0, 1 - abs(r["lane_km"] - o["lane_km"]) / max(1e-9, o["lane_km"]))
    s["connections"] = max(0.0, 1 - abs(r["connections"] - o["connections"]) / max(1, o["connections"]))
    s["junction_type_mix"] = 1 - 0.5 * sum(
        abs(r["junctions_by_type"].get(k, 0) - o["junctions_by_type"].get(k, 0))
        for k in set(o["junctions_by_type"]) | set(r["junctions_by_type"])
    ) / max(1, sum(o["junctions_by_type"].values()))
    s["junction_type_mix"] = max(0.0, s["junction_type_mix"])
    # lane role fidelity (sidewalk vs carriageway vs bike vs blocked)
    ro, rr = o["lane_km_by_role"], r["lane_km_by_role"]
    tot = sum(ro.values()) or 1.0
    s["lane_roles"] = max(0.0, 1 - sum(abs(rr[k] - ro[k]) for k in ro) / (2 * tot))
    if o["tlLogic"]:
        s["tls_count"] = min(1.0, r["tlLogic"] / o["tlLogic"])
        s["tls_program"] = (t["state_strings_identical"] / o["tlLogic"])
    if o["roundabout_decls"]:
        s["roundabouts"] = min(1.0, r["roundabout_decls"] / o["roundabout_decls"])
    ld = m["edge_len_diff_pct"]
    if ld["n"]:
        s["edge_len"] = max(0.0, 1 - ld["abs_mean"] / 100.0)
    return round(sum(s.values()) / len(s), 4), {k: round(v, 4) for k, v in s.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--junc-tol", type=float, default=25.0)
    ap.add_argument("--edge-tol", type=float, default=25.0)
    a = ap.parse_args()

    od = os.path.abspath(a.out_dir)
    os.makedirs(od, exist_ok=True)
    os.makedirs(os.path.join(od, "logs"), exist_ok=True)
    net = os.path.abspath(a.net)
    res = {"name": a.name, "source_net": net, "variants": {}}

    # ---- 1. OpenDRIVE export
    xodr = os.path.join(od, a.name + ".xodr")
    rc, txt = run(["--sumo-net-file", net, "--opendrive-output", xodr],
                  os.path.join(od, "logs", a.name + "_export.log"))
    res["export"] = {"rc": rc, "file": xodr,
                     "bytes": os.path.getsize(xodr) if os.path.exists(xodr) else 0,
                     "messages": classify(txt)}
    if rc != 0:
        json.dump(res, open(os.path.join(od, a.name + "_roundtrip.json"), "w"), indent=1)
        sys.exit("export failed for " + a.name)

    # ---- 2/3. reimport sweep + diff
    for vname, opts in VARIANTS:
        out = os.path.join(od, f"{a.name}_rt_{vname}.net.xml")
        rc, txt = run(["--opendrive-files", xodr, "-o", out] + opts,
                      os.path.join(od, "logs", f"{a.name}_rt_{vname}.log"))
        rec = {"opts": opts, "rc": rc, "messages": classify(txt)}
        if rc == 0 and os.path.exists(out):
            try:
                d = netdiff.diff(net, out, a.junc_tol, a.edge_tol)
                rec["diff"] = d
                rec["score"], rec["score_parts"] = score(d)
            except Exception as e:  # noqa: BLE001
                rec["diff_error"] = repr(e)
        res["variants"][vname] = rec
        print(f"[{a.name}] {vname:22s} rc={rc} score={rec.get('score')}")

    # ---- 4. CONTROL: plain-XML round trip (near-lossless reference)
    pp = os.path.join(od, a.name + "_plain")
    rc, txt = run(["--sumo-net-file", net, "--plain-output-prefix", pp],
                  os.path.join(od, "logs", a.name + "_plain_export.log"))
    plain_msgs = classify(txt)
    # VERIFIED GOTCHA: feeding the auto-written .typ.xml back in re-triggers
    # sidewalk/bike-lane GUESSING (sidewalkWidth/bikeLaneWidth live in the type
    # file), inflating the recompiled net.  The faithful control omits it.
    for tag, use_typ in [("CONTROL-plainxml", False), ("CONTROL-plainxml-withtyp", True)]:
        out = os.path.join(od, f"{a.name}_rt_{tag}.net.xml")
        args = ["--node-files", pp + ".nod.xml", "--edge-files", pp + ".edg.xml",
                "--connection-files", pp + ".con.xml", "-o", out]
        if os.path.exists(pp + ".tll.xml"):
            args = ["--tllogic-files", pp + ".tll.xml"] + args
        if use_typ and os.path.exists(pp + ".typ.xml"):
            args = ["--type-files", pp + ".typ.xml"] + args
        rc2, txt2 = run(args, os.path.join(od, "logs", f"{a.name}_{tag}.log"))
        rec = {"opts": args[:-2], "rc": rc2, "messages": {**plain_msgs, **classify(txt2)}}
        if rc2 == 0 and os.path.exists(out):
            d = netdiff.diff(net, out, a.junc_tol, a.edge_tol)
            rec["diff"] = d
            rec["score"], rec["score_parts"] = score(d)
        res["variants"][tag] = rec
        print(f"[{a.name}] {tag:26s} rc={rc2} score={rec.get('score')}")

    # ---- 5. other exchange formats (one-way, informational)
    other = {}
    mx = os.path.join(od, a.name + "_matsim.xml")
    rc, txt = run(["--sumo-net-file", net, "--matsim-output", mx],
                  os.path.join(od, "logs", a.name + "_matsim.log"))
    other["matsim"] = {"rc": rc, "file": mx,
                       "bytes": os.path.getsize(mx) if os.path.exists(mx) else 0,
                       "messages": classify(txt)}
    dn = os.path.join(od, a.name + "_navteq")
    rc, txt = run(["--sumo-net-file", net, "--dlr-navteq-output", dn],
                  os.path.join(od, "logs", a.name + "_navteq.log"))
    other["dlr_navteq"] = {"rc": rc, "prefix": dn,
                           "files": sorted(os.path.basename(f) for f in
                                           __import__("glob").glob(dn + "*")),
                           "messages": classify(txt)}
    res["other_formats"] = other

    json.dump(res, open(os.path.join(od, a.name + "_roundtrip.json"), "w"),
              indent=1, default=str)
    print("wrote", os.path.join(od, a.name + "_roundtrip.json"))


if __name__ == "__main__":
    main()
