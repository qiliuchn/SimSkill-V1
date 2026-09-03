#!/usr/bin/env python3
"""
Enumerate, generate and execute every experimental arm, in parallel.

Arm families
  E1  H1  paradigm      tour vs trip, same 506 parcels               (2 x 8 seeds)
  E2  H2/H3/H7  restriction sweep, 2 families x 5 coverages          (10 x 8)
  E2b H3  restriction at 3x freight scale (concentration feedback)   (4 x 8)
  E3  H4  loading-bay supply sweep                                    (5 x 8)
  E3b H4  bay supply x freight scale (deficit self-reinforcement)     (6 x 8)
  E4  H5  fleet-consolidation sweep                                   (5 x 8)
  E5  H6  night-window shifting sweep                                 (5 x 8)
  E7      negative controls (zero freight / zero restriction)         (2 x 8)

Common Random Numbers: at a given seed every arm uses the byte-identical background
car route files; only the network permissions and the freight file differ.
"""
import os, sys, json, argparse, random, itertools, time
import xml.etree.ElementTree as ET
from concurrent.futures import ProcessPoolExecutor
from common import *   # noqa
import gen_freight as gf
import run_arm

ADDRS = json.load(open(os.path.join(DEMAND, "addresses.json")))
BAY_ORDER = None
NIGHT_OFFSET = 4200
NIGHT_SIM_END = 9000
NIGHT_VC_FACTOR = 0.15


def bay_ids(frac):
    global BAY_ORDER
    if BAY_ORDER is None:
        o = [a["id"] for a in ADDRS]
        random.Random(777).shuffle(o)
        BAY_ORDER = o
    return set(BAY_ORDER[:int(round(frac * len(BAY_ORDER)))])


def night_car_files(level, seed):
    """Build (once) a night car layer: same corridor structure, NIGHT_VC_FACTOR of
    the peak rate, departing in [NIGHT_OFFSET, NIGHT_OFFSET+3600]."""
    import gen_cars
    f = os.path.join(DEMAND, "cars_night_%s_s%d.rou.xml" % (level, seed))
    if not os.path.exists(f):
        ci = json.load(open(os.path.join(DEMAND, "car_index.json")))
        gC = ci["gC"]
        tmp = f + ".tmp"
        gen_cars.build_arterial_layer(DEMAND_LEVELS[level] * NIGHT_VC_FACTOR,
                                      seed + 500, tmp, gC)
        out = []
        for v in ET.parse(tmp).getroot():
            t = float(v.get("depart")) + NIGHT_OFFSET
            v.set("depart", "%.2f" % t)
            v.set("id", "n" + v.get("id"))
            out.append((t, ET.tostring(v, encoding="unicode")))
        out.sort()
        open(f, "w").write("<routes>\n%s\n</routes>\n" % "\n".join(x[1] for x in out))
        os.remove(tmp)
    return [f]


ARMS = []


def add_arm(**kw):
    ARMS.append(kw)


def build_arms():
    S = SEEDS
    # ---- E1  H1 tour vs trip -------------------------------------------------
    for para in ("tour", "trip"):
        for s in S:
            add_arm(exp="E1", arm="E1_%s_s%d" % (para, s), net="d_strict_0", level="mid",
                    seed=s, paradigm=para, fleet=("van", "van", "rigid"), scale=1,
                    bay_frac=0.0, night=0.0)
    # ---- E2  restriction sweep ----------------------------------------------
    for fam in ("strict", "hgv"):
        for cov in (0, 25, 50, 75, 100):
            for s in S:
                add_arm(exp="E2", arm="E2_%s%d_s%d" % (fam, cov, s),
                        net="d_%s_%d" % (fam, cov), level="mid", seed=s,
                        paradigm="tour", fleet=("van", "van", "rigid"), scale=1,
                        bay_frac=0.0, night=0.0, family=fam, coverage=cov)
    # ---- E2b restriction at 3x freight (concentration feedback) --------------
    for fam in ("strict", "hgv"):
        for cov in (0, 100):
            for s in S:
                add_arm(exp="E2b", arm="E2b_%s%d_x3_s%d" % (fam, cov, s),
                        net="d_%s_%d" % (fam, cov), level="mid", seed=s,
                        paradigm="tour", fleet=("van", "van", "rigid"), scale=3,
                        bay_frac=0.0, night=0.0, family=fam, coverage=cov)
    # ---- E3  loading-bay supply ---------------------------------------------
    for bf in (1.0, 0.75, 0.5, 0.25, 0.0):
        for s in S:
            add_arm(exp="E3", arm="E3_bay%d_s%d" % (round(bf * 100), s), net="d_strict_0",
                    level="mid", seed=s, paradigm="tour", fleet=("van", "van", "rigid"),
                    scale=1, bay_frac=bf, night=0.0)
    # ---- E3b bay supply x freight scale -------------------------------------
    for sc in (2, 3, 4):
        for bf in (1.0, 0.0):
            for s in S:
                add_arm(exp="E3b", arm="E3b_bay%d_x%d_s%d" % (round(bf * 100), sc, s),
                        net="d_strict_0", level="mid", seed=s, paradigm="tour",
                        fleet=("van", "van", "rigid"), scale=sc, bay_frac=bf, night=0.0)
    # ---- E4  consolidation ---------------------------------------------------
    # CONSOLIDATION means fewer, LARGER vehicles at equal parcel throughput, so the
    # per-tour stop budget must scale with vehicle size -- otherwise swapping the vType
    # leaves the tour count unchanged and nothing is actually consolidated.
    STOP_CAPS = {"van": 5, "rigid": 10, "semi": 15}
    mixes = {"allvan": ("van",), "van_rigid": ("van", "van", "rigid"),
             "allrigid": ("rigid",), "rigid_semi": ("rigid", "semi"),
             "allsemi": ("semi",)}
    for name, mix in mixes.items():
        for s in S:
            add_arm(exp="E4", arm="E4_%s_s%d" % (name, s), net="d_strict_0", level="mid",
                    seed=s, paradigm="tour", fleet=mix, scale=1, bay_frac=0.0,
                    night=0.0, mix=name, stop_caps=STOP_CAPS)
    # ---- E5  night-window shifting ------------------------------------------
    for nf in (0.0, 0.25, 0.5, 0.75, 1.0):
        for s in S:
            add_arm(exp="E5", arm="E5_night%d_s%d" % (round(nf * 100), s), net="d_strict_0",
                    level="mid", seed=s, paradigm="tour", fleet=("van", "van", "rigid"),
                    scale=1, bay_frac=0.0, night=nf, night_mode=True)
    # ---- E7  negative controls ----------------------------------------------
    for s in S:
        add_arm(exp="E7", arm="E7_nofreight_s%d" % s, net="d_strict_0", level="mid",
                seed=s, paradigm=None, fleet=(), scale=0, bay_frac=0.0, night=0.0)
        add_arm(exp="E7", arm="E7_caronly_s%d" % s, net="d_strict_0", level="mid",
                seed=s, paradigm=None, fleet=(), scale=0, bay_frac=0.0, night=0.0,
                caronly=True)
    return ARMS


def prepare(a):
    """Generate the freight demand for one arm (cheap, done in the worker)."""
    if a.get("caronly"):
        # pure car-only baseline: no freight file, no containerStop infrastructure
        return None, None, None
    if a["scale"] == 0:
        # freight infrastructure present but ZERO freight vehicles -- the negative
        # control that must reproduce the car-only baseline exactly
        add = os.path.join(DEMAND, "f_%s.add.xml" % a["arm"])
        rou = os.path.join(DEMAND, "f_%s.rou.xml" % a["arm"])
        gf.write_containerstops(os.path.join(NET, "%s.net.xml" % a["net"]), ADDRS, add)
        open(rou, "w").write("<routes>\n</routes>\n")
        return add, rou, None
    netf = os.path.join(NET, "%s.net.xml" % a["net"])
    tag = a["arm"]
    add = os.path.join(DEMAND, "f_%s.add.xml" % tag)
    rou = os.path.join(DEMAND, "f_%s.rou.xml" % tag)
    lgp = os.path.join(DEMAND, "f_%s.ledger.json" % tag)
    lg = gf.generate(netf, ADDRS, add, rou, seed=a["seed"], fleet_mix=a["fleet"],
                     paradigm=a["paradigm"], freight_scale=a["scale"],
                     night_fraction=a["night"], night_offset=NIGHT_OFFSET,
                     bay_ids=bay_ids(a["bay_frac"]), ledger_path=lgp,
                     stop_caps=a.get("stop_caps"))
    return add, rou, lg


def run_one(a):
    t0 = time.time()
    add, rou, lg = prepare(a)
    extra, sim_end = [], SIM_END
    night = None
    if a.get("night_mode"):
        extra = night_car_files(a["level"], a["seed"])
        sim_end = NIGHT_SIM_END
        night = (0, DEMAND_END, NIGHT_OFFSET, NIGHT_OFFSET + DEMAND_END)
    d = run_arm.run(a["arm"], a["net"], a["level"], a["seed"], rou, add,
                    sim_end=sim_end, extra_car_files=extra, night=night)
    try:
        m = run_arm.extract(d, ledger=lg)
    except Exception as e:
        return dict(arm=a["arm"], error=str(e))
    m.update({k: v for k, v in a.items() if k not in ("fleet", "stop_caps")})
    m["fleet"] = "+".join(a["fleet"])
    m["wall_s"] = round(time.time() - t0, 1)
    # keep the raw evidence but compress the two big files (a re-analysis can gunzip)
    import gzip, shutil as _sh
    for big in ("tripinfo.xml",):
        f = os.path.join(d, big)
        if os.path.exists(f) and os.path.getsize(f) > 2_000_000:
            with open(f, "rb") as fi, gzip.open(f + ".gz", "wb", compresslevel=6) as fo:
                _sh.copyfileobj(fi, fo)
            os.remove(f)
    slim = {k: v for k, v in m.items() if not k.startswith("_")}
    json.dump(m, open(os.path.join(d, "metrics.json"), "w"), indent=1, default=str)
    return slim


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="comma-separated exp ids, e.g. E1,E2")
    ap.add_argument("--workers", type=int, default=9)
    a = ap.parse_args()
    arms = build_arms()
    if a.only:
        keep = set(a.only.split(","))
        arms = [x for x in arms if x["exp"] in keep]
    print("running %d arms on %d workers" % (len(arms), a.workers))
    res = []
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        for i, r in enumerate(ex.map(run_one, arms)):
            res.append(r)
            if (i + 1) % 20 == 0:
                print("  %d/%d  (%.0f s elapsed)" % (i + 1, len(arms), time.time() - t0))
    out = os.path.join(TAB, "arm_metrics%s.json" % ("_" + a.only.replace(",", "") if a.only else ""))
    json.dump(res, open(out, "w"), indent=1, default=str)
    bad = [r for r in res if "error" in r]
    print("done in %.0f s; %d arms, %d errors -> %s" % (time.time() - t0, len(res), len(bad), out))
    for b in bad[:5]:
        print("  ERROR", b)


if __name__ == "__main__":
    main()
