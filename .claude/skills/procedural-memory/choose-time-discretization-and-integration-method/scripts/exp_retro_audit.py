"""RETRO-AUDIT: re-run three specific stored quantitative claims under the
reference discretization (dt=0.1 s, ballistic) and see whether they hold.

A1  semantic-memory/webster-method.md, "Measuring the tool's assumption" section:
    "SUMO's own measured default-vehicle discharge rate = 2191 veh/h/lane", used to
    conclude tlsCycleAdaptation's -H 2 default (1800 veh/h/lane) is "21.7% wrong"
    and costs "16-26% more simulated delay".
    -> re-measured by exp_b_signal.py across the whole factorial (see b_signal_runs.json);
       this script adds a high-replication confirmation at the two decisive cells and
       recomputes the -H mismatch under each convention.

A2  semantic-memory/surrogate-safety-measures.md, "Verified finding: signalization is
    not automatically safer": priority vs signalized 4-arm, ~280 veh/h/arm, substantially
    turning -> signalized had MORE conflicts (1766 vs 487), MORE severe conflicts
    (TTC<1.5s: 858 vs 124), a WORSE worst-TTC (0.20 vs 0.64) and MORE delay (11.78 vs 2.01 s).
    -> both variants re-run here under the legacy convention (dt=1, Euler, asl tied) and
       the reference convention (dt=0.1, ballistic, asl=1.0 s), CRN seeds, to test whether
       the RANKING (not the absolute numbers, whose testbed differs) is dt-robust.

A3  semantic-memory/vehicle-emissions-modeling.md: "stop-go driving raises per-km
    emission rates ... emissions concentrate on the busiest signalized approaches".
    -> the CO2 g/km ranking between the SAME two designs of A2, at both conventions.
"""
import os
import sys
import shutil
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dtcommon import (NET, RUNS, cell_args, asl_value, run_sumo, BASE_ARGS,
                      read_tripinfo, summary_totals, read_ssm, vtype_xml, DEFAULT_CAR,
                      mean, sd, ci95, paired_t, savejson)
import exp_b_signal as B                                     # noqa

BASE = os.path.join(RUNS, "retro")
os.makedirs(BASE, exist_ok=True)

# legacy_coarse : SUMO's plain default (dt=1 s, Euler, actionStepLength tied)
# legacy_fine   : the convention the stored saturation-flow claim was actually produced
#                 under -- `measure-saturation-flow-...` mandates --step-length 0.1 and
#                 sets no actionStepLength, so Euler + asl tied to 0.1 s.
# reference     : dt=0.1 s, ballistic, actionStepLength pinned at a 1 s reaction time.
# ref_tied      : dt=0.1 s, ballistic, asl tied (fine dt AND superhuman reaction time).
LEGACY = ("1", "euler", "tied")
LEGACY_FINE = ("0.1", "euler", "tied")
REFER = ("0.1", "ballistic", "pin1")
REF_TIED = ("0.1", "ballistic", "tied")
CONV = dict(legacy=LEGACY, legacy_fine=LEGACY_FINE, reference=REFER, ref_tied=REF_TIED)
CONVS = ("legacy", "legacy_fine", "reference", "ref_tied")
SEEDS8 = [2001, 2002, 2003, 2004, 2005, 2006, 2007, 2008]

# --------------------------------------------------------------------- A2/A3 demand
ARMS = ["N", "S", "E", "W"]
ARM_LEVELS = {"stored_280": 280.0, "light_160": 160.0}
END4 = 2400.0
TURN = dict(through=0.5, right=0.25, left=0.25)     # "substantially turning"
OPP = dict(N="S", S="N", E="W", W="E")
RIGHT = dict(N="E", E="S", S="W", W="N")
LEFT = dict(N="W", W="S", S="E", E="N")


def write_x4_demand(path, arm_vph, seed=17):
    import random
    rng = random.Random(seed)
    veh = []
    for a in ARMS:
        t, i = 0.0, 0
        h = 3600.0 / arm_vph
        while t < END4 - 200:
            u = rng.random()
            dst = OPP[a] if u < TURN["through"] else (
                RIGHT[a] if u < TURN["through"] + TURN["right"] else LEFT[a])
            veh.append((t, '<vehicle id="%s%d" type="car" depart="%.2f" departSpeed="max" '
                           'departLane="0"><route edges="%s_in %s_out"/></vehicle>'
                        % (a, i, t, a, dst)))
            i += 1
            t += h * rng.uniform(0.5, 1.5)
    veh.sort()
    open(path, "w").write("<routes>\n" + "\n".join(v[1] for v in veh) + "\n</routes>")
    return len(veh)


X4_DEMAND = {}
X4_N = {}
for _lab, _v in ARM_LEVELS.items():
    X4_DEMAND[_lab] = os.path.join(BASE, "x4_demand_%s.rou.xml" % _lab)
    X4_N[_lab] = write_x4_demand(X4_DEMAND[_lab], _v)


def x4_run(job):
    design, conv, seed, dem = job
    c = CONV[conv]
    d = os.path.join(BASE, "x4_%s_%s_%s_s%d" % (design, conv, dem, seed))
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    add = os.path.join(d, "add.xml")
    open(add, "w").write("<additional>%s</additional>"
                         % vtype_xml("car", DEFAULT_CAR, asl=asl_value(c), ssm=True))
    net = os.path.join(NET, "x4_%s.net.xml" % design)
    tri, smy = os.path.join(d, "tripinfo.xml"), os.path.join(d, "summary.xml")
    ssmf = os.path.join(d, "ssm.xml")
    r = run_sumo(["-n", net, "-r", X4_DEMAND[dem], "-a", add,
                  "--tripinfo-output", tri, "--summary-output", smy,
                  "--device.ssm.file", ssmf,
                  "--device.emissions.probability", "1.0",
                  "--begin", "0", "--end", str(END4),
                  "--time-to-teleport", "300", "--max-depart-delay", "900",
                  "--collision.action", "warn",
                  "--seed", str(seed)] + cell_args(c) + BASE_ARGS, cwd=d)
    if r["rc"] != 0:
        return dict(design=design, conv=conv, dem=dem, seed=seed, ok=False, err=r["err"][-500:])
    ti = read_tripinfo(tri)
    tot = summary_totals(smy)
    ssm = read_ssm(ssmf)
    ttc = [x["minTTC"] for x in ssm["conflicts"] if x.get("minTTC") is not None]
    pet = [x["PET"] for x in ssm["conflicts"] if x.get("PET") is not None]
    ttc_pos = [v for v in ttc if v > 0]
    pet_pos = [v for v in pet if v >= 0]
    cats = {}
    for x in ssm["conflicts"]:
        for k in (x["cats"] or ["none"]):
            cats[k] = cats.get(k, 0) + 1
    co2 = [float(x["em_CO2_abs"]) / 1e6 for x in ti if "em_CO2_abs" in x]
    dist = [float(x["routeLength"]) for x in ti]
    ncomp = len(ti)
    return dict(design=design, conv=conv, dem=dem, seed=seed, ok=True, wall=r["wall"],
                n_conflicts=ssm["n"], cats=cats,
                conflicts_per_veh=ssm["n"] / ncomp if ncomp else float("nan"),
                n_ttc_lt_15=sum(1 for v in ttc_pos if v < 1.5),
                ttc_lt_15_per_veh=sum(1 for v in ttc_pos if v < 1.5) / ncomp if ncomp else float("nan"),
                worst_ttc=min(ttc_pos) if ttc_pos else float("nan"),
                n_ssm_type111=cats.get("collision", 0),
                n_pet=len(pet_pos), worst_pet=min(pet_pos) if pet_pos else float("nan"),
                n_pet_neg=len(pet) - len(pet_pos),
                pet_per_veh=len(pet_pos) / ncomp if ncomp else float("nan"),
                n_pet_lt_10=sum(1 for v in pet_pos if v < 1.0),
                mean_wait=mean([float(x["waitingTime"]) for x in ti]),
                mean_timeloss=mean([float(x["timeLoss"]) for x in ti]),
                mean_dur=mean([float(x["duration"]) for x in ti]),
                co2_g_per_km=(sum(co2) * 1e6 / 1000.0) / (sum(dist) / 1000.0) if dist else float("nan"),
                n_completed=len(ti), still_running=tot["running"],
                not_inserted=tot["loaded"] - tot["inserted"],
                teleports=tot["teleports"], collisions=tot["collisions"])


# ------------------------------------------------------------------------- A1
def a1_run(job):
    conv, seed = job
    return B.run_cell((CONV[conv], seed))


def cmp_block(rows, conv, key, dem):
    """paired (CRN) prio-vs-tls comparison for one metric under one convention."""
    p = [r[key] for r in sorted([x for x in rows if x["conv"] == conv and x["dem"] == dem
                                 and x["design"] == "prio"], key=lambda z: z["seed"])]
    t = [r[key] for r in sorted([x for x in rows if x["conv"] == conv and x["dem"] == dem
                                 and x["design"] == "tls"], key=lambda z: z["seed"])]
    md, hw, tt, sig = paired_t(t, p)          # tls - prio
    return dict(prio=mean(p), tls=mean(t), diff_tls_minus_prio=md, ci95=hw,
                t=tt, significant=bool(sig),
                verdict=("tls_worse" if md > 0 else "tls_better") if sig else "no_sig_diff")


if __name__ == "__main__":
    out = {}

    # ---------------- A1
    print("A1  saturation flow (stored claim 2191 veh/h/lane; tlsCycleAdaptation -H 2 == 1800)")
    jobs = [(cv, sd_) for cv in CONVS for sd_ in SEEDS8]
    with ProcessPoolExecutor(max_workers=8) as ex:
        a1 = list(ex.map(a1_run, jobs))
    for r, (cv, sd_) in zip(a1, jobs):
        r["conv"] = cv
    a1res = {}
    for cv in CONVS:
        rr = [r for r in a1 if r.get("ok") and r["conv"] == cv]
        m, h = ci95([r["sat_flow"] for r in rr])
        m2, h2 = ci95([r["lost_time"] for r in rr])
        a1res[cv] = dict(sat_flow=m, sat_flow_ci=h, lost_time=m2, lost_time_ci=h2, n=len(rr),
                         stored_claim=2191.0, rel_to_stored_pct=(m - 2191.0) / 2191.0 * 100,
                         tool_default_1800_mismatch_pct=(m - 1800.0) / 1800.0 * 100.0)
        print("   %-12s s=%7.1f +-%5.1f veh/h/ln  l1=%5.2f+-%.2f  vs stored 2191: %+6.1f%%"
              "   vs tool -H2 (1800): %+6.1f%%"
              % (cv, m, h, m2, h2, a1res[cv]["rel_to_stored_pct"],
                 a1res[cv]["tool_default_1800_mismatch_pct"]))
    out["A1"] = dict(runs=[{k: v for k, v in r.items() if k not in ("hn", "alt_windows")}
                           for r in a1], summary=a1res)

    # ---------------- A2 / A3
    print("\nA2/A3  priority vs signalized 4-arm, 50/25/25 through/right/left")
    jobs = [(dz, cv, sd_, dem) for dz in ("prio", "tls") for cv in CONVS
            for dem in ARM_LEVELS for sd_ in SEEDS8[:6]]
    with ProcessPoolExecutor(max_workers=8) as ex:
        x4 = list(ex.map(x4_run, jobs))
    bad = [r for r in x4 if not r.get("ok")]
    print("   failed:", len(bad), bad[:1])
    x4 = [r for r in x4 if r.get("ok")]
    savejson("retro_x4_runs.json", x4)
    metrics = ["n_conflicts", "conflicts_per_veh", "n_ttc_lt_15", "ttc_lt_15_per_veh",
               "worst_ttc", "n_pet", "pet_per_veh", "n_pet_lt_10", "worst_pet",
               "mean_wait", "mean_timeloss", "co2_g_per_km", "n_completed",
               "collisions", "n_ssm_type111", "teleports"]
    a2 = {}
    for dem in ARM_LEVELS:
        a2[dem] = {}
        print("   ==== demand %s (%d veh) ====" % (dem, X4_N[dem]))
        for cv in CONVS:
            a2[dem][cv] = {m: cmp_block(x4, cv, m, dem) for m in metrics}
            print("     -- %s --" % cv)
            for m in metrics:
                b = a2[dem][cv][m]
                print("        %-18s prio=%10.3f tls=%10.3f diff=%+10.3f +-%8.3f  %s"
                      % (m, b["prio"], b["tls"], b["diff_tls_minus_prio"], b["ci95"],
                         b["verdict"]))
    out["A2_A3"] = dict(comparisons=a2, demand_veh=X4_N, arm_levels=ARM_LEVELS,
                        stored_claim=dict(conflicts=(487, 1766), ttc_lt_15=(124, 858),
                                          worst_ttc=(0.64, 0.20), mean_wait=(2.01, 11.78),
                                          note="(priority, signalized) at ~280 veh/h/arm"))
    savejson("retro_audit.json", out)
    print("\nwritten -> outputs/tables/retro_audit.json")
