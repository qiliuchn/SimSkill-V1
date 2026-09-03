#!/usr/bin/env python3
"""
counts_to_demand.py -- turn a field turning-movement count (TMC) into SUMO demand.

This is the reusable deliverable.  It reads ONLY field-observable inputs:

    * a TMC CSV      (intersection, approach, movement, bin_start_s, clock,
                      veh_count, heavy_count)  -- stop-bar DEPARTURE counts
    * an ATR CSV     (station, direction, bin_start_s, clock, veh_count,
                      heavy_count)             -- one mid-block station/direction
    * the compiled network (topology + routing only)
    * standard engineering parameters (K30, AADT, growth, PCE, balancing weight)
    * OPTIONALLY an E2 queue file, for the residual-queue correction

and writes a SUMO route file of 15-minute <flow> elements plus the route
definitions that realise them, together with a JSON report.

Each numbered step is a separately testable function (see test_c2d.py):

  (a) design_hour_from_profile   K = DHV/daily, D = directional split, with both
                                 an "observed peak hour" and a "K30 x AADT" path
  (b) peak_hour_factor           PHF = V / (4*V15max), peak hour located by a
                                 SLIDING 4-bin search (never assumed clock-aligned)
  (c) balance_link / balance_tmc TMC balancing between adjacent intersections
  (d) apply_hv_and_growth        heavy-vehicle PCE adjustment + growth factor
  (e) expand_paths + emit_flows  movement volumes -> path flows -> <flow> XML
  (f) queue_correct              demand = served + change in residual queue
"""
import argparse
import collections
import csv
import json
import os
import sys

MOVEMENTS = ("L", "T", "R")
DIR2MV = {"s": "T", "l": "L", "r": "R"}


# ---------------------------------------------------------------- IO ------
def read_tmc(path):
    tmc, bins = {}, set()
    with open(path) as f:
        for r in csv.DictReader(f):
            b0 = int(r["bin_start_s"])
            bins.add(b0)
            tmc[(r["intersection"], r["approach"], r["movement"], b0)] = \
                (float(r["veh_count"]), float(r["heavy_count"]))
    bins = sorted(bins)
    step = bins[1] - bins[0] if len(bins) > 1 else 900
    return tmc, bins, step


def read_atr(path):
    prof = {}
    with open(path) as f:
        for r in csv.DictReader(f):
            prof[(r["direction"], int(r["bin_start_s"]))] = \
                (float(r["veh_count"]), float(r["heavy_count"]))
    return prof


def approach_total(tmc, j, app, b):
    return sum(tmc.get((j, app, m, b), (0.0, 0.0))[0] for m in MOVEMENTS)


def to_series(tmc, bins, key):
    out = []
    for b in bins:
        s = 0.0
        for (j, a, m, bb), (c, _h) in tmc.items():
            if bb != b:
                continue
            if len(key) == 3 and (j, a, m) != key:
                continue
            if len(key) == 2 and (j, a) != key:
                continue
            if len(key) == 1 and (j,) != key:
                continue
            s += c
        out.append(s)
    return out


# --------------------------------------------------- (b) peak hour factor --
def peak_window(series, w=4):
    """Sliding-window search for the highest-volume w-bin window (NOT assumed
    clock-aligned).  Returns (start_index, window_volume)."""
    best, bi = -1.0, 0
    for i in range(0, max(len(series) - w + 1, 1)):
        s = sum(series[i:i + w])
        if s > best:
            best, bi = s, i
    return bi, best


def peak_hour_factor(series, w=4):
    i, V = peak_window(series, w)
    win = series[i:i + w]
    v15 = max(win) if win else 0.0
    return dict(start_bin=i, V=V, V15max=v15,
                PHF=(V / (w * v15)) if v15 > 0 else None, window=win)


# ------------------------------------------------------ (a) design hour ----
def design_hour_from_profile(atr, bins, method="observed", k30=None, aadt=None,
                             study_window_share=0.32, w=4):
    """K = DHV/daily and D = directional split, from a mid-block ATR profile.

    study_window_share : the fraction of an average day's traffic inside the
    counted window -- the count-expansion factor a real study takes from a
    permanent-count station.  daily = counted_total / study_window_share.
    """
    dirs = sorted({d for (d, _b) in atr})
    per_dir = {d: [atr.get((d, b), (0.0, 0.0))[0] for b in bins] for d in dirs}
    two_way = [sum(per_dir[d][i] for d in dirs) for i in range(len(bins))]
    i, V = peak_window(two_way, w)
    counted_total = sum(two_way)
    daily = counted_total / study_window_share
    peak_by_dir = {d: sum(per_dir[d][i:i + w]) for d in dirs}
    heavy_dir = max(peak_by_dir, key=lambda d: peak_by_dir[d])
    out = dict(directions=dirs, counted_total=counted_total,
               study_window_share=study_window_share, daily_equivalent=daily,
               peak_hour_start_bin=i, peak_hour_start_s=bins[i],
               DHV_observed=V, K_observed=(V / daily) if daily else None,
               D=(peak_by_dir[heavy_dir] / V) if V else None,
               heavy_direction=heavy_dir, peak_by_direction=peak_by_dir,
               two_way_profile=two_way, method=method)
    if method == "k30":
        if k30 is None or aadt is None:
            raise ValueError("method 'k30' requires --k30 and --aadt")
        out.update(K30=k30, AADT=aadt, DHV_design=k30 * aadt,
                   design_scale=(k30 * aadt) / V if V else 1.0)
    else:
        out.update(DHV_design=V, design_scale=1.0)
    return out


# ------------------------------------------------------ (c) TMC balancing --
def balance_link(U, A, w=0.5):
    """One directional link, one bin.
      U = counted DEPARTURES from the upstream intersection onto the link
      A = counted ARRIVALS at the downstream intersection on that approach
    Documented rule: balanced link volume B = w*U + (1-w)*A (confidence-weighted
    mean; w = 0.5 = equal confidence, the default when neither count is known to
    be more reliable).  The downstream approach's movements are then scaled so
    the approach total equals B, preserving its observed turn ratios."""
    B = w * U + (1.0 - w) * A
    denom = 0.5 * (U + A)
    return dict(U=U, A=A, B=B, imbalance=U - A,
                rel_imbalance=(U - A) / denom if denom > 0 else 0.0)


def balance_tmc(tmc, bins, links, w=0.5, travel_time=None, offset_correct=False,
                step=900):
    bal = dict(tmc)
    report = []
    for name, (ju, ups), (jd, appd) in links:
        tt = (travel_time or {}).get(name, 0.0)
        shift = int(round(tt / step)) if offset_correct else 0
        rows = []
        for k, b in enumerate(bins):
            U = sum(tmc.get((ju, a, m, b), (0.0, 0.0))[0] for (a, m) in ups)
            kd = k + shift
            bd = bins[kd] if 0 <= kd < len(bins) else None
            A = approach_total(tmc, jd, appd, bd) if bd is not None else 0.0
            r = balance_link(U, A, w)
            r.update(bin_start_s=b, downstream_bin_start_s=bd, link=name)
            rows.append(r)
            if bd is not None and A > 0:
                f = r["B"] / A
                for m in MOVEMENTS:
                    c, h = bal.get((jd, appd, m, bd), (0.0, 0.0))
                    bal[(jd, appd, m, bd)] = (c * f, h * f)
        tU, tA = sum(r["U"] for r in rows), sum(r["A"] for r in rows)
        report.append(dict(
            link=name, upstream_junction=ju, downstream="%s %s" % (jd, appd),
            total_U=tU, total_A=tA, total_imbalance=tU - tA,
            total_rel_imbalance=(tU - tA) / (0.5 * (tU + tA)) if tU + tA else 0.0,
            mean_abs_rel_imbalance=sum(abs(r["rel_imbalance"]) for r in rows) / len(rows),
            max_abs_imbalance=max(abs(r["imbalance"]) for r in rows),
            travel_time_s=tt, offset_corrected=bool(offset_correct), bins=rows))
    return bal, report


# ------------------------------------------ (d) heavy vehicles and growth --
def apply_hv_and_growth(tmc, growth=1.0, pce=2.0):
    """Growth factor applied to the counts, plus the HCM heavy-vehicle adjustment
    factor f_HV = 1/(1 + P_HV*(E_T-1)) and the equivalent passenger-car volume."""
    out, pcu = {}, {}
    for k, (c, h) in tmc.items():
        c2, h2 = c * growth, h * growth
        p = (h2 / c2) if c2 > 0 else 0.0
        f_hv = 1.0 / (1.0 + p * (pce - 1.0))
        out[k] = (c2, h2)
        pcu[k] = dict(veh=c2, heavy=h2, P_HV=p, f_HV=f_hv, pcu=c2 / f_hv)
    return out, pcu


# ----------------------------------------------------------- topology -----
def load_net(net_path):
    sys.path.insert(0, os.path.join(os.environ["SUMO_HOME"], "tools"))
    import sumolib
    return sumolib.net.readNet(net_path)


def corridor_topology(net, approach_edge):
    """For every counted (J, approach, movement), resolve
         ('cont', nextJ, nextApp)  -- it feeds another counted approach, or
         ('exit', terminal_edge)   -- it leaves the counted corridor.
       Also returns every mid-block branch encountered on a link (an access
       point the intersection counts cannot see)."""
    approach_of = {e: k for k, e in approach_edge.items()}

    def outs(eid):
        return sorted(e.getID() for e in net.getEdge(eid).getOutgoing())

    def reaches(eid, depth=14):
        seen, stack = set(), [(eid, 0)]
        while stack:
            e, d = stack.pop()
            if e in approach_of:
                return True
            if d >= depth or e in seen:
                continue
            seen.add(e)
            stack.extend((n, d + 1) for n in outs(e))
        return False

    def ins(eid):
        return sorted(e.getID() for e in net.getEdge(eid).getIncoming())

    topo, midblock = {}, []
    mb_access = {}          # (downstream J, app) -> dict(out=[edges], into=[edges])
    for (j, app), aedge in approach_edge.items():
        edge = net.getEdge(aedge)
        for to_edge, conns in edge.getOutgoing().items():
            m = None
            for c in conns:
                m = DIR2MV.get(c.getDirection(), m)
            if m is None:
                continue
            cur, prev, hops = to_edge.getID(), aedge, 0
            mb_out, mb_in = [], []
            while True:
                if cur in approach_of:
                    topo[(j, app, m)] = ("cont",) + approach_of[cur]
                    if mb_out or mb_in:
                        a = mb_access.setdefault(approach_of[cur],
                                                 dict(out=[], into=[]))
                        for e in mb_out:
                            if e not in a["out"]:
                                a["out"].append(e)
                        for e in mb_in:
                            if e not in a["into"]:
                                a["into"].append(e)
                    break
                nxt = outs(cur)
                live = [e for e in nxt if reaches(e)]
                if hops >= 1:      # skip the junction itself: the edges entering
                    for e in ins(cur):   # the first hop are the junction approaches
                        if e != prev and e not in mb_in:
                            mb_in.append(e)
                if len(nxt) > 1:
                    keep = live[0] if live else None
                    for e in nxt:
                        if e != keep and e not in mb_out:
                            mb_out.append(e)
                    midblock.append(dict(link_after_edge=cur, branches=nxt,
                                         continuing=keep))
                if not live:
                    topo[(j, app, m)] = ("exit", cur)
                    break
                prev, cur, hops = cur, live[0], hops + 1
                if hops > 14:
                    topo[(j, app, m)] = ("exit", cur)
                    break
    return topo, midblock, mb_access


# -------------------------------------------------- (e) path expansion ----
def expand_paths(tmc, bins, topo, entries, mb_access=None, trust=None):
    """Forward propagation of counted movement volumes into PATH flows.

    A stream entering the corridor at a counted boundary approach is split at
    each junction by that approach's OBSERVED turn ratios; the sub-streams that
    stay on the corridor are carried to the next junction.  At every downstream
    approach the propagated arrival volume P is reconciled against the counted
    (balanced) approach total A: all incoming streams are scaled by A/P.  The
    residual A-P is the MID-BLOCK source (+) or sink (-) on that link, which the
    intersection counts cannot see, and is reported per link per bin.

    Returns (paths, reconciliation).
    """
    nb = len(bins)
    # dependency graph: which (J,app) feeds which (J,app)
    feeders = collections.defaultdict(list)
    for (j, app, m), d in topo.items():
        if d[0] == "cont":
            feeders[(d[1], d[2])].append((j, app, m))
    all_app = sorted({(k[0], k[1]) for k in topo})
    # topological order
    order, done = [], set()
    pending = list(all_app)
    while pending:
        progressed = False
        for ap in list(pending):
            if all((f[0], f[1]) in done for f in feeders.get(ap, [])):
                order.append(ap)
                done.add(ap)
                pending.remove(ap)
                progressed = True
        if not progressed:
            order.extend(pending)
            break

    inflow = collections.defaultdict(list)      # (J,app) -> [(seq, vol[])]
    for ap in entries:
        inflow[ap].append(([], [approach_total(tmc, ap[0], ap[1], b) for b in bins], None))

    paths, recon = {}, []
    for (j, app) in order:
        streams = inflow.get((j, app), [])
        A = [approach_total(tmc, j, app, b) for b in bins]
        P = [sum(s[1][k] for s in streams) for k in range(nb)]
        f = [(A[k] / P[k]) if P[k] > 1e-9 else (1.0 if A[k] <= 1e-9 else None)
             for k in range(nb)]
        # An approach fed by a queue-constrained upstream approach is itself
        # METERED: its counted volume is a capacity, not a demand, and must not be
        # used to rescale (re-truncate) an already queue-corrected upstream stream.
        for k in range(nb):
            if trust and (j, app, k) in trust:
                f[k] = 1.0
        if (j, app) not in entries:
            recon.append(dict(approach="%s %s" % (j, app),
                              propagated_total=sum(P), counted_total=sum(A),
                              midblock_net=sum(A) - sum(P),
                              per_bin_midblock=[A[k] - P[k] for k in range(nb)],
                              scale_factor=[None if f[k] is None else round(f[k], 5)
                                            for k in range(nb)],
                              materialised=bool((mb_access or {}).get((j, app)))))
        # if nothing propagated but something was counted, treat the whole
        # approach as an unmodelled source and seed it directly
        if all(p <= 1e-9 for p in P) and any(a > 1e-9 for a in A) and streams == []:
            streams = [([], A)]
            f = [1.0] * nb
        # ---- materialise the mid-block source/sink EXPLICITLY where the network
        # exposes an access point, instead of silently rescaling upstream streams
        acc = (mb_access or {}).get((j, app), {})
        mb_sink_edge = acc.get("out", [None])[0] if acc.get("out") else None
        mb_src_edge = acc.get("into", [None])[0] if acc.get("into") else None
        mb_taken = [0.0] * nb
        if (j, app) not in entries:
            for k in range(nb):
                d = A[k] - P[k]
                if d < 0 and mb_sink_edge and P[k] > 1e-9:
                    mb_taken[k] = -d / P[k]          # fraction diverted mid-block
                    f[k] = 1.0
                elif d > 0 and mb_src_edge:
                    streams = streams + [([], [d if kk == k else 0.0
                                               for kk in range(nb)],
                                          ("MB", mb_src_edge))]
                    f[k] = 1.0
        streams = [(x[0], x[1], x[2] if len(x) > 2 else None) for x in streams]
        hv = []
        for b in bins:
            tot = approach_total(tmc, j, app, b)
            h = sum(tmc.get((j, app, m, b), (0.0, 0.0))[1] for m in MOVEMENTS)
            hv.append(h / tot if tot > 0 else 0.0)
        for (seq, vol, ovr) in streams:
            svol = [vol[k] * (f[k] if f[k] is not None else 1.0) for k in range(nb)]
            if mb_sink_edge and any(mb_taken):
                div = [svol[k] * mb_taken[k] for k in range(nb)]
                if sum(div) > 1e-9 and seq:
                    key = "|".join("%s.%s.%s" % t for t in seq) + "|MB.OUT"
                    p = paths.setdefault(key, dict(
                        seq=list(seq), vol=[0.0] * nb, heavy=[0.0] * nb,
                        origin=tuple(seq[0][:2]), dest_edge=mb_sink_edge,
                        midblock="sink"))
                    for k in range(nb):
                        p["vol"][k] += div[k]
                        p["heavy"][k] += div[k] * hv[k]
                svol = [svol[k] - div[k] for k in range(nb)]
            for m in MOVEMENTS:
                share = [0.0] * nb
                for k, b in enumerate(bins):
                    tot = approach_total(tmc, j, app, b)
                    if tot > 0:
                        share[k] = svol[k] * tmc.get((j, app, m, b), (0.0, 0.0))[0] / tot
                if sum(share) <= 1e-9:
                    continue
                nseq = seq + [(j, app, m)]
                d = topo.get((j, app, m))
                if d is None:
                    continue
                if d[0] == "cont":
                    inflow[(d[1], d[2])].append((nseq, share, ovr))
                else:
                    key = "|".join("%s.%s.%s" % t for t in nseq) + ("@MB" if ovr else "")
                    p = paths.setdefault(key, dict(
                        seq=nseq, vol=[0.0] * nb, heavy=[0.0] * nb,
                        origin=(ovr if ovr else tuple(nseq[0][:2])),
                        dest_edge=d[1]))
                    for k in range(nb):
                        p["vol"][k] += share[k]
                        p["heavy"][k] += share[k] * hv[k]
    return paths, recon


def path_movement_volumes(paths, nb):
    out = {}
    for p in paths.values():
        for (j, a, m) in p["seq"]:
            arr = out.setdefault((j, a, m), [0.0] * nb)
            for k in range(nb):
                arr[k] += p["vol"][k]
    return out


# ------------------------------------------------------------ emission ----
VTYPES = """  <vType id="car" vClass="passenger" length="5.0" minGap="2.5" accel="2.6"
         decel="4.5" sigma="0.5" tau="1.0" speedFactor="normc(1.00,0.10,0.85,1.15)"
         lcKeepRight="0"/>
  <vType id="hgv" vClass="truck" length="12.0" minGap="3.0" accel="1.3"
         decel="3.5" sigma="0.5" tau="1.2" maxSpeed="25.0"
         speedFactor="normc(0.95,0.08,0.80,1.10)" lcKeepRight="0"/>
"""


def emit_flows(paths, bins, step, net, origin_edge_map, out_path, scale=None):
    routes, rows, keymap = {}, [], {}
    for i, (key, p) in enumerate(sorted(paths.items())):
        rid = "P%03d" % i
        keymap[key] = rid
        o = (p["origin"][1] if p["origin"][0] == "MB"
             else origin_edge_map["%s|%s" % p["origin"]])
        path, _c = net.getShortestPath(net.getEdge(o), net.getEdge(p["dest_edge"]))
        if path is None:
            raise RuntimeError("no route %s -> %s for %s" % (o, p["dest_edge"], key))
        routes[rid] = [e.getID() for e in path]
        sc = (scale or {}).get(key, 1.0)
        for k, b in enumerate(bins):
            s = sc[k] if isinstance(sc, (list, tuple)) else sc
            v = p["vol"][k] * s
            if v <= 1e-6:
                continue
            hv = min(p["heavy"][k] * s, v)
            rate = v / float(step)
            for vt, sub in (("car", v - hv), ("hgv", hv)):
                if sub <= 1e-9:
                    continue
                rows.append((b, '  <flow id="%s.%s.%d" type="%s" route="r_%s" begin="%d" '
                                'end="%d" period="exp(%.8f)" departLane="free" '
                                'departSpeed="max"/>'
                                % (rid, vt, k, vt, rid, b, b + step, rate * sub / v)))
    rows.sort(key=lambda x: x[0])
    with open(out_path, "w") as f:
        f.write("<routes>\n" + VTYPES)
        for rid in sorted(routes):
            f.write('  <route id="r_%s" edges="%s"/>\n' % (rid, " ".join(routes[rid])))
        for _b, line in rows:
            f.write(line + "\n")
        f.write("</routes>\n")
    return keymap, routes, len(rows)


# ------------------------------------------- (f) residual-queue correction -
def queue_correct(tmc, bins, step, queue_csv, queue_map, pending_csv=None,
                  pending_approach=None, metric="storage"):
    """demand_bin = served_count + (Q_end_of_bin - Q_start_of_bin)

    metric="storage" (default and correct):  Q is the number of vehicles PRESENT
      on the approach at the bin boundary (E2 `LAST_STEP_VEHICLE_NUMBER` over a
      detector chain spanning the WHOLE approach).  Then served + dQ is exactly
      the input-output (cumulative-count) identity and recovers demand exactly,
      provided the detector spans the whole approach.
    metric="jam":  Q is the E2 residual jam length (mean per-cycle minimum).
      Kept for comparison -- it measures the STANDING jam, not the storage, and
      badly under-states demand once the queue becomes a long crawling queue
      rather than a compact stopped platoon.

    queue_map: {"J|app": [E2 detector ids that together cover that approach]}
    """
    col = "n_end_veh" if metric == "storage" else "q_resid_veh"
    q = {}
    with open(queue_csv) as f:
        for r in csv.DictReader(f):
            if r.get(col, "") == "":
                continue
            q[(int(r["bin"]), r["det"])] = float(r[col])
    pend = {}
    if pending_csv:
        with open(pending_csv) as f:
            for r in csv.DictReader(f):
                pend[int(float(r["time"]) // step) - 1] = float(r["n_pending_insertion"])

    aq = {}
    for key, dets in queue_map.items():
        j, app = key.split("|")
        for k in range(len(bins)):
            v = sum(q.get((k, d), 0.0) for d in dets)
            if pending_approach and key == pending_approach:
                v += pend.get(k, 0.0)
            aq[(j, app, k)] = v

    out, rep = dict(tmc), []
    for key in queue_map:
        j, app = key.split("|")
        for k, b in enumerate(bins):
            q0 = aq.get((j, app, k - 1), 0.0) if k > 0 else 0.0
            q1 = aq.get((j, app, k), 0.0)
            dq = q1 - q0
            served = approach_total(tmc, j, app, b)
            if served <= 0:
                continue
            f = max((served + dq) / served, 0.0)
            for m in MOVEMENTS:
                c, h = tmc.get((j, app, m, b), (0.0, 0.0))
                out[(j, app, m, b)] = (c * f, h * f)
            rep.append(dict(junction=j, approach=app, bin=k, bin_start_s=b,
                            metric=metric, served=served, q_start=q0, q_end=q1,
                            delta_q=dq, corrected=served + dq, factor=f))
    return out, rep


# ------------------------------------------------------------------ main --
def build(args):
    cfg = json.load(open(args.config))
    approach_edge = {tuple(k.split("|")): v for k, v in cfg["approach_edge"].items()}
    entries = [tuple(x) for x in cfg["entries"]]
    links = [(L["name"], (L["up_j"], [tuple(x) for x in L["up_mv"]]),
              (L["down_j"], L["down_app"])) for L in cfg["links"]]

    tmc, bins, step = read_tmc(args.tmc)
    atr = read_atr(args.atr)
    rep = dict(inputs=dict(tmc=args.tmc, atr=args.atr, net=args.net),
               params={k: v for k, v in vars(args).items()})

    dh = design_hour_from_profile(atr, bins, args.design_hour, args.k30, args.aadt,
                                  args.study_window_share)
    rep["design_hour"] = dh

    if args.queue_correction:
        tmc, qrep = queue_correct(tmc, bins, step, args.queue_correction,
                                  cfg["queue_map"], args.queue_include_pending,
                                  cfg.get("pending_approach"), args.queue_metric)
        rep["queue_correction"] = qrep

    phf = {}
    for (j, app) in sorted({(k[0], k[1]) for k in tmc}):
        phf["%s %s" % (j, app)] = peak_hour_factor(to_series(tmc, bins, (j, app)))
    for j in sorted({k[0] for k in tmc}):
        phf[j] = peak_hour_factor(to_series(tmc, bins, (j,)))
    rep["phf"] = phf

    bal, breport = balance_tmc(tmc, bins, links, args.balance_weight,
                               cfg.get("travel_time"), args.offset_correct, step)
    rep["balancing"] = breport

    g = args.growth * dh["design_scale"]
    bal, pcu = apply_hv_and_growth(bal, g, args.pce)
    rep["growth_applied"] = g
    rep["pce"] = args.pce
    mid_bin = bins[len(bins) // 2]
    rep["hv_adjustment_midbin"] = {
        "%s %s %s" % k[:3]: dict(P_HV=round(v["P_HV"], 4), f_HV=round(v["f_HV"], 4),
                                 veh=round(v["veh"], 1), pcu=round(v["pcu"], 1))
        for k, v in pcu.items() if k[3] == mid_bin}

    net = load_net(args.net)
    topo, midblock, mb_access = corridor_topology(net, approach_edge)
    rep["topology"] = {"|".join(k): list(v) for k, v in topo.items()}
    rep["midblock_branches_in_network"] = midblock

    rep["midblock_access"] = {"%s|%s" % k: v for k, v in mb_access.items()}
    trust = set()
    if args.trust_propagation and rep.get("queue_correction"):
        qf = {(r["junction"], r["approach"], r["bin"]): r["factor"]
              for r in rep["queue_correction"]}
        feed = collections.defaultdict(list)
        for (jj, aa, mm), dd in topo.items():
            if dd[0] == "cont":
                feed[(dd[1], dd[2])].append((jj, aa))
        for (jd, ad), ups in feed.items():
            for k in range(len(bins)):
                if any(qf.get((ju, au, k), 1.0) > 1.02 for (ju, au) in ups):
                    trust.add((jd, ad, k))
        rep["trusted_propagation_approach_bins"] = sorted(
            "%s %s bin%d" % t for t in trust)
    paths, recon = expand_paths(bal, bins, topo, entries, mb_access, trust)
    rep["midblock_reconciliation"] = recon

    scale = json.load(open(args.scale_file)) if args.scale_file else None
    keymap, routes, nflows = emit_flows(paths, bins, step, net,
                                        cfg["origin_edge_map"], args.out, scale)
    rep["n_paths"], rep["n_flows"] = len(paths), nflows
    rep["route_ids"] = keymap
    rep["paths"] = {k: dict(seq=["%s %s %s" % t for t in p["seq"]],
                            total=sum(p["vol"]), per_bin=p["vol"])
                    for k, p in paths.items()}
    rep["recovered_movement_volumes"] = {
        "%s|%s|%s" % k: v for k, v in path_movement_volumes(paths, len(bins)).items()}
    rep["bins"] = bins
    with open(args.report, "w") as f:
        json.dump(rep, f, indent=1)
    return rep


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tmc", required=True)
    ap.add_argument("--atr", required=True)
    ap.add_argument("--net", required=True)
    ap.add_argument("--config", required=True, help="corridor JSON config")
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--design-hour", choices=("observed", "k30"), default="observed")
    ap.add_argument("--k30", type=float, default=None)
    ap.add_argument("--aadt", type=float, default=None)
    ap.add_argument("--study-window-share", type=float, default=0.32)
    ap.add_argument("--growth", type=float, default=1.0)
    ap.add_argument("--pce", type=float, default=2.0)
    ap.add_argument("--balance-weight", type=float, default=0.5)
    ap.add_argument("--offset-correct", action="store_true")
    ap.add_argument("--queue-correction", default=None)
    ap.add_argument("--queue-metric", choices=("storage", "jam"), default="storage")
    ap.add_argument("--trust-propagation", action="store_true",
                    help="do not rescale a downstream approach to its counted "
                         "volume when its upstream approach was queue-corrected")
    ap.add_argument("--queue-include-pending", default=None)
    ap.add_argument("--scale-file", default=None)
    args = ap.parse_args()
    rep = build(args)
    print("wrote %s (%d paths, %d flows) and %s"
          % (args.out, rep["n_paths"], rep["n_flows"], args.report))


if __name__ == "__main__":
    main()
