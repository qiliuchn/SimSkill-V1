"""ID-matching readers (AVI / ANPR / Bluetooth analogue) as a SECOND sensor type.

A link counter gives you one equation per station. An ID-matching reader gives you a
*subpath* observation for every ordered pair of readers a vehicle passes, so R readers
yield up to R(R-1) rows. That quadratic return is the whole economic story of a mixed
sensor portfolio, and it is also why a lone reader is worth nothing — see the exchange
rate note in SKILL.md.

Mechanism in SUMO:
  1. `instantInductionLoop` writes one record per vehicle passage INCLUDING `vehID` —
     SUMO's per-vehicle equivalent of a plate read. The aggregating `inductionLoop`
     loses identity and cannot be used for this.
  2. Records with `state="enter"` are deduplicated to (vehID, edge) -> first crossing
     time, giving each vehicle's observed reader sequence.
  3. Matching IDs across two readers r1, r2 gives the subpath flow
     f(r1->r2) = #vehicles seen at r1 and later at r2.
  4. Each subpath flow is one more linear observation of the OD vector:
     f(r1->r2) = sum_k P_sub[(r1,r2), k] x_k, with P_sub tabulated from the same
     reference router run that produced P. Readers simply add rows to the system.

VERIFY BEFORE USE: `verify_matching` must show the ID-matched flows reproduce the
route-implied subpath flows EXACTLY (max abs difference 0). Two independent sources are
being compared — SUMO's detector output versus the router's route file — so an exact
match is meaningful evidence, not a tautology. In the reference study: 969/969 ordered
reader pairs exact, and single-reader link counts exact on 123/123 links.
"""
import xml.etree.ElementTree as ET
from collections import defaultdict

import numpy as np


# ================================================================ detector plumbing
def build_reader_add(net, edges, path, out_file="instant.out.xml", pos_frac=0.5):
    """Write an additional-file placing an `instantInductionLoop` on every lane of every
    candidate edge. `net` is a sumolib net object.

    Note SUMO resolves the `file=` attribute relative to the additional file's own
    directory, not the process cwd — so copy this file into each run directory rather
    than pointing at it from elsewhere (the same gotcha `estimate-od-matrix-with-odme`
    documents for its edgeData additional file)."""
    with open(path, "w") as f:
        f.write("<additional>\n")
        for eid in edges:
            e = net.getEdge(eid)
            for li, lane in enumerate(e.getLanes()):
                f.write('    <instantInductionLoop id="rd|%s|%d" lane="%s" pos="%.1f" '
                        'file="%s"/>\n' % (eid, li, lane.getID(), e.getLength() * pos_frac,
                                           out_file))
        f.write("</additional>\n")
    return path


def read_passages(path):
    """instant-loop XML -> {vehID: [(edge, first_crossing_time), ...] sorted by time}.

    Only `state="enter"` records count, and only the FIRST crossing of each edge per
    vehicle — otherwise a vehicle that loops back inflates the subpath flow."""
    first = defaultdict(dict)
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag != "instantOut" or el.get("state") != "enter":
            el.clear()
            continue
        eid = el.get("id").split("|")[1]
        v, t = el.get("vehID"), float(el.get("time"))
        d = first[v]
        if eid not in d or t < d[eid]:
            d[eid] = t
        el.clear()
    return {v: sorted(d.items(), key=lambda kv: kv[1]) for v, d in first.items()}


# =================================================================== the ID matching
def subpath_counts_from_passages(seqs, keep=None):
    """ID matching proper: for each vehicle, every ORDERED pair of readers it was seen
    at, in crossing-time order. `keep` restricts to a set of reader pairs."""
    out = defaultdict(float)
    for _, seq in seqs.items():
        es = [e for e, _ in seq]
        for i in range(len(es)):
            for j in range(i + 1, len(es)):
                k = (es[i], es[j])
                if keep is None or k in keep:
                    out[k] += 1.0
    return out


def subpath_counts_from_routes(rou_file, cand, keep=None):
    """The KNOWN subpath flows — the same quantity read straight off the route file.
    This is the independent reference `verify_matching` compares against."""
    cs = set(cand)
    out = defaultdict(float)
    for _, veh in ET.iterparse(rou_file, events=("end",)):
        if veh.tag != "vehicle":
            # GOTCHA: do NOT clear here. ET.iterparse fires the `end` event for the
            # nested <route> element BEFORE its parent <vehicle>; clearing the route
            # wipes its `edges` attribute, so veh.find("route").get("edges") then
            # returns None on the parent. This silently empties every subpath count.
            continue
        es = [e for e in veh.find("route").get("edges").split() if e in cs]
        for i in range(len(es)):
            for j in range(i + 1, len(es)):
                k = (es[i], es[j])
                if keep is None or k in keep:
                    out[k] += 1.0
        veh.clear()
    return out


def verify_matching(instant_out, rou_file, cand):
    """Compare ID-matched subpath flows against route-implied ones. Run this and report
    its numbers before any reader observation enters an estimator."""
    matched = subpath_counts_from_passages(read_passages(instant_out))
    known = subpath_counts_from_routes(rou_file, cand)
    keys = sorted(set(matched) | set(known))
    diffs = [abs(matched.get(k, 0.0) - known.get(k, 0.0)) for k in keys]
    n_exact = sum(1 for d in diffs if d == 0.0)
    return dict(n_pairs=len(keys), n_exact=n_exact,
                exact_pct=round(100.0 * n_exact / max(len(keys), 1), 2),
                max_abs_diff=float(max(diffs)) if diffs else 0.0,
                total_matched=float(sum(matched.values())),
                total_known=float(sum(known.values())))


# ============================================================ the extra P_sub rows
def build_Psub(ref_rou, cand, pairs, min_flow=0.0, seed_vec=None):
    """P_sub[(i,j), k] = share of OD pair k's trips passing candidate i then j.

    Built from the same reference router run that produced `P`, so reader rows and
    counter rows are consistent observations of one linear system and can simply be
    stacked. `min_flow` (with `seed_vec`) drops reader pairs whose seed-predicted flow is
    negligible — those rows are numerically noisy and inflate the candidate set for no
    information gain."""
    pidx = {tuple(p): i for i, p in enumerate(pairs)}
    cs = set(cand)
    hits = defaultdict(lambda: np.zeros(len(pairs)))
    n = np.zeros(len(pairs))
    for _, veh in ET.iterparse(ref_rou, events=("end",)):
        if veh.tag != "vehicle":
            # Same iterparse gotcha as above — do not clear the nested <route>.
            continue
        k = pidx.get((veh.get("fromTaz"), veh.get("toTaz")))
        if k is not None:
            n[k] += 1
            es = [e for e in veh.find("route").get("edges").split() if e in cs]
            for i in range(len(es)):
                for j in range(i + 1, len(es)):
                    hits[(es[i], es[j])][k] += 1.0
        veh.clear()
    keys = sorted(hits)
    Psub = np.array([hits[k] / np.maximum(n, 1) for k in keys])
    if min_flow > 0 and seed_vec is not None and len(keys):
        pred = Psub @ np.asarray(seed_vec, float)
        m = pred >= min_flow
        keys = [k for k, keep in zip(keys, m) if keep]
        Psub = Psub[m]
    return keys, Psub


# ================================================================ the exchange rate
def counter_equivalent(mix_err, counter_curve, budgets):
    """How many pure counters buy the same OD error as a mixed portfolio.

    `counter_curve[N]` is the all-counter OD error at N counters. Returns the smallest N
    whose error is <= `mix_err`, or `> max budget` when no all-counter design of any
    affordable size matches the mix — which is the interesting case, and the one the
    reference study hit at a 48-unit budget (7 readers + 27 counters was unmatchable by
    all 98 counters).

    Report the exchange rate PER BUDGET, never as a single constant. Measured, it was 0
    below ~48 units and ~6.3 counters/reader at 48, because R readers give only R(R-1)
    subpath rows — the quadratic return does not overtake the linear cost of the
    counters you gave up until R is around 6. A study that reports one number here is
    reporting an artefact of its chosen budget."""
    for n in sorted(budgets):
        if counter_curve.get(n, np.inf) <= mix_err:
            return n
    return "> %d (unreachable with counters alone)" % max(budgets)
