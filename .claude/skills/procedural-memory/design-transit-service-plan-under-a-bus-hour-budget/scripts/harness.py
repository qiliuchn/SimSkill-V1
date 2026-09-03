"""Evaluation harness: design -> (compile, route, simulate) -> metrics.

A "design" is (plan structure name, integer bus allocation per line).  Headways
are DERIVED from the measured cycle time C_l:  h_l = C_l / N_l.

Common random numbers: the network, the person demand, the car demand and the
duarouter routing of a given design are all deterministic; only `sumo --seed`
varies across replications.
"""
import os, sys, json, math, hashlib, statistics as st
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

import tspcore as T
from tspcore import WORK, ensure
import plans as P

DESIGNS = ensure(os.path.join(WORK, "designs"))
CYCLE_FILE = os.path.join(WORK, "cycles.json")
SPEED_FILE = os.path.join(WORK, "runspeeds.json")
CARS = os.path.join(WORK, "cars.rou.xml")
PERSONS = os.path.join(WORK, "persons.trips.xml")


def design_key(name, buses):
    s = name + "|" + ",".join(f"{k}={buses[k]}" for k in sorted(buses))
    return name + "_" + hashlib.md5(s.encode()).hexdigest()[:10]


def load_json(p, default=None):
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return default if default is not None else {}


def make(name, buses, cycles=None, net=None):
    plan = P.make_plan(name, buses=buses)
    cy = cycles if cycles is not None else load_json(CYCLE_FILE).get(name, {})
    plan.cycles = dict(cy)
    return plan


def prepare(name, buses, netfile=None, cycles=None, speeds=None, tag=None,
            reuse=False, persons=None):
    """Compile + intermodal-route one design.  Deterministic; done ONCE per
    design -- with reuse=True the files are only read, never rewritten, which is
    what makes it safe to fan the seeds out across processes."""
    net = T.Net(netfile or os.path.join(WORK, "base.net.xml"))
    plan = make(name, buses, cycles)
    sp = speeds if speeds is not None else load_json(SPEED_FILE).get(name, {})
    d = ensure(os.path.join(DESIGNS, tag or design_key(name, buses)))
    comp = T.compile_plan(plan, net, d, run_speed=sp, write=not reuse)
    routed = T.route_persons(net, comp, persons or PERSONS, d, threads=2,
                             reuse=reuse)
    return d, plan, comp, routed, net


def metrics(plan, res, pis=None):
    tri = res["tripinfo"]
    pis = pis if pis is not None else T.parse_personinfos(tri)
    comp = [p for p in pis if p["complete"]]
    inc = [p for p in pis if not p["complete"]]
    tr = [p for p in comp if p["mode"] == "transit"]
    wo = [p for p in comp if p["mode"] == "walk"]

    def s(key, rows): return sum(r[key] for r in rows)
    m = dict(
        n_persons=len(pis), n_complete=len(comp), n_incomplete=len(inc),
        n_stranded=sum(1 for p in pis if p["stranded"]),
        n_riders=len(tr), n_walkonly=len(wo),
        n_transfers=s("n_transfers", tr),
        sum_access=s("access", tr) + s("egress", tr),
        sum_wait=s("wait", tr), sum_ivt=s("ivt", tr),
        sum_xwalk=s("xwalk", tr), sum_xwait=s("xwait", tr),
        sum_walkonly=s("access", wo),
        # censored (still-travelling) accounting -- realised stages only, a lower bound
        inc_sum_access=s("access", inc) + s("egress", inc),
        inc_sum_wait=s("wait", inc), inc_sum_ivt=s("ivt", inc),
        inc_sum_xwalk=s("xwalk", inc), inc_sum_xwait=s("xwait", inc),
        inc_transfers=s("n_transfers", inc),
    )
    bus = T.parse_bus_tripinfo(tri)
    cy = T.measure_cycles(bus, plan)
    m["cycles"] = {k: (v["cycle"] if v["cycle"] else None) for k, v in cy.items()}
    m["cycles_C"] = {k: (v["C"] if v["C"] else None) for k, v in cy.items()}
    m["bus_veh_dispatched"] = len(bus)
    m["bus_veh_complete"] = sum(1 for b in bus if b["complete"])
    m["max_concurrent_total"] = T.max_concurrent(bus)
    m["max_concurrent_line"] = {L.id: T.max_concurrent(bus, L.id) for L in plan.lines}
    m["headways"] = {L.id: plan.headway(L.id) for L in plan.lines}
    m["buses"] = {L.id: L.buses for L in plan.lines}
    m.update(T.parse_car_stats(tri))
    m["teleports"] = T.teleports_from_summary(res["summary"])
    st_rows = T.parse_stopinfo(res.get("stopinfo"))
    board = defaultdict(int)
    for r in st_rows:
        board[r["line"]] += r["loaded"]
    m["boardings"] = dict(board)
    m["stopinfo_rows"] = len(st_rows)
    return m, pis, st_rows


def gc_total(m, p_transfer=T.P_TRANSFER, include_incomplete=False):
    """Total passenger generalized time (seconds) for completed travellers."""
    g = (T.W_ACCESS * m["sum_access"] + T.W_WAIT * m["sum_wait"]
         + T.W_IVT * m["sum_ivt"] + T.W_XWALK * m["sum_xwalk"]
         + T.W_XWAIT * m["sum_xwait"] + p_transfer * m["n_transfers"]
         + T.W_WALKONLY * m["sum_walkonly"])
    if include_incomplete:
        g += (T.W_ACCESS * m["inc_sum_access"] + T.W_WAIT * m["inc_sum_wait"]
              + T.W_IVT * m["inc_sum_ivt"] + T.W_XWALK * m["inc_sum_xwalk"]
              + T.W_XWAIT * m["inc_sum_xwait"] + p_transfer * m["inc_transfers"])
    return g


def gc_per_person(m, p_transfer=T.P_TRANSFER):
    return gc_total(m, p_transfer) / max(1, m["n_complete"])


# ---------------------------------------------------------------------------
def _run_one(args):
    (name, buses, seed, netfile, cycles, speeds, tag, keep_persons) = args[:8]
    persons = args[8] if len(args) > 8 else None
    cars = args[9] if len(args) > 9 else None
    try:
        d, plan, comp, routed, net = prepare(name, buses, netfile, cycles,
                                             speeds, tag, reuse=True,
                                             persons=persons)
        od = os.path.join(d, f"seed{seed}")
        res = T.simulate(net, comp, routed, [cars or CARS], od, seed=seed)
        m, pis, st_rows = metrics(plan, res)
        m["seed"] = seed; m["design"] = tag or design_key(name, buses); m["plan"] = name
        m["dir"] = od
        with open(os.path.join(od, "metrics.json"), "w") as f:
            json.dump(m, f, indent=1)
        if keep_persons:
            with open(os.path.join(od, "persons.json"), "w") as f:
                json.dump(pis, f)
            with open(os.path.join(od, "stops.json"), "w") as f:
                json.dump(st_rows, f)
        else:
            for fn in ("tripinfo.xml", "stopinfo.xml", "summary.xml"):
                fp = os.path.join(od, fn)
                if os.path.exists(fp):
                    os.remove(fp)
        return m
    except Exception as e:
        import traceback
        return dict(error=str(e), tb=traceback.format_exc(), seed=seed, plan=name)


class Budget:
    """Hard evaluation-budget counter (optimize-under-simulation-noise pattern)."""
    def __init__(self, cap, log_path):
        self.cap, self.n = cap, 0
        self.log = log_path
        with open(self.log, "w") as f:
            f.write("eval_index,tag,seed,objective,best_so_far\n")
        self.best = float("inf")

    def take(self, k=1):
        if self.n + k > self.cap:
            raise RuntimeError(f"BudgetExhausted: {self.n}+{k} > {self.cap}")
        self.n += k

    def record(self, tag, seed, obj):
        self.best = min(self.best, obj)
        with open(self.log, "a") as f:
            f.write(f"{self.n},{tag},{seed},{obj:.1f},{self.best:.1f}\n")


def evaluate_many(jobs, workers=8):
    """jobs: list of (name, buses, seed, netfile, cycles, speeds, tag, keep).

    Every distinct design is compiled and intermodally routed SERIALLY first --
    two workers writing the same persons.routed.rou.xml produced a truncated
    file and a hard SUMO parse error ("input ended before all started tags were
    ended").  Only the simulations fan out.
    """
    seen = set()
    for j in jobs:
        (name, buses, seed, netfile, cycles, speeds, tag, keep) = j[:8]
        persons = j[8] if len(j) > 8 else None
        t = tag or design_key(name, buses)
        if t in seen:
            continue
        seen.add(t)
        prepare(name, buses, netfile, cycles, speeds, t, reuse=False,
                persons=persons)
    out = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for m in ex.map(_run_one, jobs):
            if "error" in m:
                sys.stderr.write(m["tb"] + "\n")
            out.append(m)
    return out
