#!/usr/bin/env python3
"""
THE VALIDITY TEST.

Evaluate perimeter gating (the intervention the `mfd-based-perimeter-gating`
memory page reports a -44.7% travel-time benefit for, alongside a -77.9% drop in
teleports) under three accounting conventions:

  A. default teleporting (--time-to-teleport 300), ALL completed trips
     -- the convention the original episode used
  B. default teleporting, TELEPORT-FREE trips only
  C. teleporting disabled (--time-to-teleport -1)

If the benefit under A is largely an artifact of SUMO rescuing its own baseline,
it should shrink or vanish under B and C.  Reported with per-seed directional
agreement, not just means.
"""
import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
TELE_RE = re.compile(r"Teleporting vehicle '([^']+)'")


def metrics(d):
    tele = set()
    lg = os.path.join(d, "sumo.log")
    if os.path.exists(lg):
        with open(lg, errors="replace") as fh:
            for line in fh:
                m = TELE_RE.search(line)
                if m:
                    tele.add(m.group(1))
    trips = []
    for _, el in ET.iterparse(os.path.join(d, "tripinfo.xml"), events=("end",)):
        if el.tag == "tripinfo":
            trips.append((el.get("id"), float(el.get("duration")),
                          float(el.get("timeLoss"))))
            el.clear()
    steps = []
    for _, el in ET.iterparse(os.path.join(d, "summary.xml"), events=("end",)):
        if el.tag == "step":
            steps.append({k: el.get(k) for k in
                          ("time", "running", "waiting", "inserted", "arrived",
                           "teleports", "meanSpeed")})
            el.clear()
    last = steps[-1]
    clr = None
    for s in steps:
        if float(s["time"]) > 60 and int(s["running"]) == 0 and \
           int(s["waiting"]) == 0 and int(s["inserted"]) > 0:
            clr = float(s["time"])
            break
    num = sum(int(s["running"]) * float(s["meanSpeed"]) for s in steps if int(s["running"]) > 0)
    den = sum(int(s["running"]) for s in steps if int(s["running"]) > 0)
    free = [t for t in trips if t[0] not in tele]
    return {
        "completed": len(trips),
        "teleports_cum": int(last["teleports"]),
        "teleport_vehicles": len(tele),
        "clearance_time": clr,
        "end_running": int(last["running"]),
        "end_waiting": int(last["waiting"]),
        "mean_net_speed": round(num / den, 4) if den else 0.0,
        "all_mean_duration": round(statistics.mean([t[1] for t in trips]), 2) if trips else None,
        "free_n": len(free),
        "free_mean_duration": round(statistics.mean([t[1] for t in free]), 2) if free else None,
    }


def job(spec):
    level, cfg, ttt, seed, work, end, nset, K, gmin = spec
    od = os.path.join(work, "runs", "validity", "%s_%s_ttt%s_s%d" % (level, cfg, ttt, seed))
    cmd = [sys.executable, os.path.join(HERE, "gating.py"),
           "--net", os.path.join(work, "grid.net.xml"),
           "--rou", os.path.join(work, "demand_%s_s%d.rou.xml" % (level, seed)),
           "--ttt", str(ttt), "--seed", str(seed), "--outdir", od,
           "--end", str(end), "--gating", "1" if cfg == "gated" else "0",
           "--nset", str(nset), "--K", str(K), "--gmin", str(gmin),
           "--label", "%s%s%s%d" % (level, cfg, ttt, seed)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        return {"level": level, "cfg": cfg, "ttt": str(ttt), "seed": seed,
                "error": p.stderr[-2000:]}
    r = metrics(od)
    meta = json.load(open(os.path.join(od, "gating_meta.json")))
    r.update(level=level, cfg=cfg, ttt=str(ttt), seed=seed,
             inert_violations=meta["inert_violations"])
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--end", type=float, default=10800)
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--nset", type=float, default=60)
    ap.add_argument("--K", type=float, default=1.5)
    ap.add_argument("--gmin", type=float, default=0.25)
    ap.add_argument("--jobs", type=int, default=6)
    a = ap.parse_args()

    specs = []
    for level in ["OS-A", "OS-B"]:
        for ttt in ["300", "-1"]:
            for cfg in ["base", "gated"]:
                for s in range(1, a.seeds + 1):
                    specs.append((level, cfg, ttt, s, a.work, a.end,
                                  a.nset, a.K, a.gmin))
    print("%d validity runs" % len(specs))
    res = []
    with ThreadPoolExecutor(max_workers=a.jobs) as ex:
        for i, r in enumerate(ex.map(job, specs)):
            res.append(r)
            if (i + 1) % 5 == 0:
                print("  %d/%d" % (i + 1, len(specs)), flush=True)
    json.dump(res, open(a.out, "w"), indent=1)
    errs = [r for r in res if "error" in r]
    print("errors: %d" % len(errs))
    for e in errs[:3]:
        print(e)


if __name__ == "__main__":
    sys.exit(main())
