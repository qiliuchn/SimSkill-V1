#!/usr/bin/env python3
"""
Verify the keep-clear treatment changes ACTUAL junction-blocking behaviour, not
just configuration intent.

Method: re-run selected cells with an <edgeData withInternal="true"> collector.
Internal edges (ids beginning ':') ARE the junction boxes.  Two behavioural
signatures distinguish the arms:

  box_occupancy_veh_s : total sampledSeconds accumulated on internal edges
                        (vehicle-seconds physically standing/moving inside
                        junction boxes)
  box_standing_veh_s  : the part of that at near-zero speed -- i.e. vehicles
                        STOPPED inside the box, which is precisely what
                        keepClear=true is supposed to prevent.

Per this project's convention the edgeData `file` attribute resolves relative to
the ADDITIONAL file's own directory, so each run gets its own .add.xml written
into its own output directory with a bare relative filename.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

ADD = """<additional>
    <edgeData id="ed" file="edgedata.out.xml" freq="%(freq)d" withInternal="true"
              excludeEmpty="false" minSamples="0"/>
</additional>
"""


def sumo_bin(n="sumo"):
    p = shutil.which(n)
    if not p:
        raise RuntimeError("no sumo")
    return p


def one(netfile, roufile, ttt, seed, outdir, end, freq=300):
    os.makedirs(outdir, exist_ok=True)
    addf = os.path.join(outdir, "ed.add.xml")
    with open(addf, "w") as fh:
        fh.write(ADD % {"freq": freq})
    cmd = [sumo_bin(), "-n", netfile, "-r", roufile, "-a", addf,
           "--end", str(end), "--seed", str(seed), "--time-to-teleport", str(ttt),
           "--summary-output", os.path.join(outdir, "summary.xml"),
           "--summary-output.period", "10",
           "--tripinfo-output", os.path.join(outdir, "tripinfo.xml"),
           "--log", os.path.join(outdir, "sumo.log"),
           "--no-step-log", "true", "--xml-validation", "never"]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-3000:])

    edf = os.path.join(outdir, "edgedata.out.xml")
    box_s = 0.0
    box_stand_s = 0.0
    norm_s = 0.0
    n_int = 0
    seen = set()
    for _, el in ET.iterparse(edf, events=("end",)):
        if el.tag != "edge":
            continue
        eid = el.get("id")
        ss = float(el.get("sampledSeconds") or 0.0)
        spd = el.get("speed")
        spd = float(spd) if spd is not None else None
        if eid.startswith(":"):
            if eid not in seen:
                seen.add(eid)
                n_int += 1
            box_s += ss
            # vehicle-seconds spent inside the box at crawl speed (<0.5 m/s)
            if spd is not None and spd < 0.5:
                box_stand_s += ss
        else:
            norm_s += ss
        el.clear()
    return {"net": os.path.basename(netfile), "ttt": ttt, "seed": seed,
            "internal_edges_seen": n_int,
            "box_occupancy_veh_s": round(box_s, 1),
            "box_standing_veh_s": round(box_stand_s, 1),
            "normal_edge_veh_s": round(norm_s, 1),
            "box_share_of_all_veh_s": round(box_s / (box_s + norm_s), 5) if (box_s + norm_s) else 0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--end", type=float, default=10800)
    args = ap.parse_args()
    W = args.work
    rows = []
    for level in ["LOW", "OS-A", "OS-B"]:
        for arm, net in [("kc_on", "grid.net.xml"), ("kc_off", "grid_kcoff.net.xml")]:
            for ttt in ["300"]:
                for seed in range(1, args.seeds + 1):
                    od = os.path.join(W, "runs", "probe",
                                      "%s_%s_ttt%s_s%d" % (level, arm, ttt, seed))
                    r = one(os.path.join(W, net),
                            os.path.join(W, "demand_%s_s%d.rou.xml" % (level, seed)),
                            ttt, seed, od, args.end)
                    r.update(level=level, arm=arm)
                    rows.append(r)
                    print(r, flush=True)
    with open(args.out, "w") as fh:
        json.dump(rows, fh, indent=1)

    # summary
    from collections import defaultdict
    g = defaultdict(list)
    for r in rows:
        g[(r["level"], r["arm"])].append(r)
    print("\n%-6s %-7s %18s %18s %14s" % ("level", "arm", "box_occ_veh_s",
                                          "box_STANDING_veh_s", "box_share"))
    for k in sorted(g):
        v = g[k]
        print("%-6s %-7s %18.1f %18.1f %14.5f" % (
            k[0], k[1],
            sum(x["box_occupancy_veh_s"] for x in v) / len(v),
            sum(x["box_standing_veh_s"] for x in v) / len(v),
            sum(x["box_share_of_all_veh_s"] for x in v) / len(v)))


if __name__ == "__main__":
    sys.exit(main())
