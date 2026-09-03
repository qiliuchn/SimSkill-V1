"""Testbed (c): unsignalized 1-lane-mainline + 1-lane-ramp merge -> SSM / collisions.

The ramp yields to the mainline at a priority junction (verified in net_verification.json),
so every ramp vehicle must find a gap -- a genuine conflict process, unlike pure
car-following, and the place where TTC/PET/DRAC and simulated collisions live.

SSM device configuration follows `analyze-intersection-safety-with-ssm`:
per-vType `has.ssm.device`, and the output path given per-run on the command line
(`--device.ssm.file`) rather than as a vType param.
"""
import os
import sys
import math
import shutil
import xml.etree.ElementTree as ET
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dtcommon import (NET, RUNS, SEEDS, cells, cell_id, cell_args, asl_value,
                      run_sumo, BASE_ARGS, read_tripinfo, summary_totals, read_ssm,
                      vtype_xml, DEFAULT_CAR, mean, sd, ci95, savejson, SSM_CAT)

MERGE = os.path.join(NET, "merge.net.xml")
END = 1800.0
MAIN_VPH, RAMP_VPH = 1100.0, 700.0
BASE = os.path.join(RUNS, "c_merge")
os.makedirs(BASE, exist_ok=True)


def write_demand(path, seed=11):
    """CRN demand: one fixed vehicle list reused by EVERY factorial cell."""
    import random
    rng = random.Random(seed)
    veh = []
    for name, edges, vph in (("m", "main_up main_dn", MAIN_VPH),
                             ("r", "ramp main_dn", RAMP_VPH)):
        t = 0.0
        i = 0
        h = 3600.0 / vph
        while t < END - 120:
            veh.append((t, '<vehicle id="%s%d" type="car" depart="%.2f" departSpeed="max" '
                           'departPos="base" departLane="0"><route edges="%s"/></vehicle>'
                        % (name, i, t, edges)))
            i += 1
            t += h * rng.uniform(0.4, 1.6)
    veh.sort()
    open(path, "w").write("<routes>\n" + "\n".join(v[1] for v in veh) + "\n</routes>")
    return len(veh)


DEMAND = os.path.join(BASE, "demand.rou.xml")
NVEH = write_demand(DEMAND)


def count_collisions(path):
    if not os.path.exists(path):
        return 0, []
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return 0, []
    cs = root.findall("collision")
    return len(cs), [dict(c.attrib) for c in cs[:5]]


def run_cell(job):
    c, seed = job
    d = os.path.join(BASE, "%s_s%d" % (cell_id(c), seed))
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    add = os.path.join(d, "add.xml")
    open(add, "w").write("<additional>%s</additional>"
                         % vtype_xml("car", DEFAULT_CAR, asl=asl_value(c), ssm=True))
    tri, smy = os.path.join(d, "tripinfo.xml"), os.path.join(d, "summary.xml")
    ssmf, colf = os.path.join(d, "ssm.xml"), os.path.join(d, "coll.xml")
    args = (["-n", MERGE, "-r", DEMAND, "-a", add,
             "--tripinfo-output", tri, "--summary-output", smy,
             "--device.ssm.file", ssmf, "--collision-output", colf,
             "--device.emissions.probability", "1.0",
             "--begin", "0", "--end", str(END),
             "--time-to-teleport", "300", "--max-depart-delay", "900",
             "--collision.action", "warn", "--collision.mingap-factor", "0",
             "--seed", str(seed)] + cell_args(c) + BASE_ARGS)
    r = run_sumo(args, cwd=d, tag=cell_id(c))
    if r["rc"] != 0:
        return dict(cell=cell_id(c), seed=seed, ok=False, err=r["err"][-600:])
    tot = summary_totals(smy)
    ti = read_tripinfo(tri)
    ssm = read_ssm(ssmf)
    ncol, colex = count_collisions(colf)
    ttc = [x["minTTC"] for x in ssm["conflicts"] if x.get("minTTC") is not None]
    pet = [x["PET"] for x in ssm["conflicts"] if x.get("PET") is not None]
    drac = [x["maxDRAC"] for x in ssm["conflicts"] if x.get("maxDRAC") is not None]
    cats = {}
    for x in ssm["conflicts"]:
        for k in (x["cats"] or ["none"]):
            cats[k] = cats.get(k, 0) + 1
    co2 = [float(x["em_CO2_abs"]) / 1e6 for x in ti if "em_CO2_abs" in x]
    dist = [float(x["routeLength"]) for x in ti]
    return dict(cell=cell_id(c), dt=float(c[0]), method=c[1], asl=c[2], seed=seed, ok=True,
                wall=r["wall"], rtf=END / r["wall"],
                n_conflicts=ssm["n"], cats=cats,
                n_ttc_lt_15=sum(1 for v in ttc if v < 1.5),
                n_ttc_lt_30=sum(1 for v in ttc if v < 3.0),
                min_ttc=min(ttc) if ttc else float("nan"),
                mean_ttc=mean(ttc), n_ttc=len(ttc),
                n_pet=len(pet), min_pet=min(pet) if pet else float("nan"),
                n_pet_lt_10=sum(1 for v in pet if v < 1.0), mean_pet=mean(pet),
                max_drac=max(drac) if drac else float("nan"),
                max_br=max(ssm["maxBR"]) if ssm["maxBR"] else float("nan"),
                collisions_log=ncol, collisions_summary=tot["collisions"],
                collision_examples=colex,
                teleports=tot["teleports"], n_completed=len(ti),
                still_running=tot["running"], inserted=tot["inserted"],
                not_inserted=tot["loaded"] - tot["inserted"],
                mean_dur=mean([float(x["duration"]) for x in ti]),
                mean_timeloss=mean([float(x["timeLoss"]) for x in ti]),
                co2_g_per_km=(sum(co2) * 1e6 / 1000.0) / (sum(dist) / 1000.0) if dist else float("nan"))


if __name__ == "__main__":
    jobs = [(c, s) for c in cells() for s in SEEDS]
    print("testbed (c): %d runs, demand=%d veh" % (len(jobs), NVEH))
    with ProcessPoolExecutor(max_workers=8) as ex:
        rows = list(ex.map(run_cell, jobs))
    savejson("c_merge_runs.json", rows)
    bad = [r for r in rows if not r.get("ok")]
    print("failed:", len(bad), bad[:1])
    print("\n%-24s %14s %12s %9s %9s %8s %7s %6s" %
          ("cell", "conflicts", "TTC<1.5s", "minTTC", "minPET", "coll", "tele", "compl"))
    agg = {}
    for c in cells():
        cid = cell_id(c)
        rr = [r for r in rows if r.get("ok") and r["cell"] == cid]
        if not rr:
            continue
        m, h = ci95([r["n_conflicts"] for r in rr])
        m2, h2 = ci95([r["n_ttc_lt_15"] for r in rr])
        allcats = {}
        for r in rr:
            for k, v in r["cats"].items():
                allcats[k] = allcats.get(k, 0) + v / len(rr)
        agg[cid] = dict(n_conflicts=m, n_conflicts_ci=h, n_ttc_lt_15=m2, n_ttc_lt_15_ci=h2,
                        min_ttc=mean([r["min_ttc"] for r in rr]),
                        mean_ttc=mean([r["mean_ttc"] for r in rr]),
                        n_pet=mean([r["n_pet"] for r in rr]),
                        min_pet=mean([r["min_pet"] for r in rr]),
                        mean_pet=mean([r["mean_pet"] for r in rr]),
                        n_pet_lt_10=mean([r["n_pet_lt_10"] for r in rr]),
                        max_drac=mean([r["max_drac"] for r in rr]),
                        collisions=mean([r["collisions_log"] for r in rr]),
                        collisions_total=sum(r["collisions_log"] for r in rr),
                        teleports=sum(r["teleports"] for r in rr),
                        n_completed=mean([r["n_completed"] for r in rr]),
                        still_running=mean([r["still_running"] for r in rr]),
                        not_inserted=mean([r["not_inserted"] for r in rr]),
                        mean_timeloss=mean([r["mean_timeloss"] for r in rr]),
                        co2_g_per_km=mean([r["co2_g_per_km"] for r in rr]),
                        wall=mean([r["wall"] for r in rr]), cats=allcats)
        print("%-24s %8.1f+-%4.1f %7.1f+-%3.1f %9.3f %9.3f %8.1f %7d %6.0f" %
              (cid, m, h, m2, h2, agg[cid]["min_ttc"], agg[cid]["min_pet"],
               agg[cid]["collisions"], agg[cid]["teleports"], agg[cid]["n_completed"]))
    savejson("c_merge_agg.json", agg)
