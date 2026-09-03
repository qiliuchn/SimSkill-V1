"""H5 (half-headway assumption), H6 (ridership vs coverage, distributional
incidence) and the per-segment generalized-cost decomposition.

Pure post-processing of runs already made -- no new simulation.
"""
import os, sys, json, math, statistics as st
from collections import defaultdict
import tspcore as T
from tspcore import WORK, ensure
import plans as P
import harness as H
import alloc as A

OUTJ = os.path.join(WORK, "h5_h6_post.json")
COVER_RADIUS = 400.0
COVER_MIN_FREQ_PER_H = 4.0          # a stop "counts" only if served >= 4 bus/h
BUDGET = int(os.environ.get("BUDGET", "24"))


# ---------------------------------------------------------------- H5 --------
def headway_cv(stop_rows):
    """Realised headway CV per line, pooled over stops (bunching measure per
    `demonstrate-and-control-bus-bunching`)."""
    byls = defaultdict(list)
    for r in stop_rows:
        byls[(r["line"], r["busStop"])].append(r["started"])
    per_line = defaultdict(list)
    for (line, stop), ts in byls.items():
        ts = sorted(t for t in ts if t >= 0)
        if len(ts) < 3:
            continue
        hs = [b - a for a, b in zip(ts, ts[1:])]
        per_line[line].extend(hs)
    out = {}
    for line, hs in per_line.items():
        if len(hs) < 3:
            continue
        m = st.mean(hs); sd = st.pstdev(hs)
        out[line] = dict(n=len(hs), mean_headway=m, sd=sd, cv=sd / m if m else None,
                         paired_share=sum(1 for h in hs if h < 0.25 * m) / len(hs))
    return out


def h5(run_dirs, plan_name, cycles, buses):
    rows = []
    agg_stop, agg_pers = [], []
    for d in run_dirs:
        with open(os.path.join(d, "stops.json")) as f:
            agg_stop.append(json.load(f))
        with open(os.path.join(d, "persons.json")) as f:
            agg_pers.append(json.load(f))
    cvs = [headway_cv(s) for s in agg_stop]
    lines = sorted(set().union(*[set(c) for c in cvs]))
    for l in lines:
        cv = st.mean([c[l]["cv"] for c in cvs if l in c])
        mh = st.mean([c[l]["mean_headway"] for c in cvs if l in c])
        pair = st.mean([c[l]["paired_share"] for c in cvs if l in c])
        h_nom = cycles[l] / buses[l]
        waits = []
        for pers in agg_pers:
            w = [p["wait"] for p in pers
                 if p["mode"] == "transit" and p["lines"] and
                 p["lines"][0].split(".")[0] == l]
            if w:
                waits.append(st.mean(w))
        realized = st.mean(waits) if waits else None
        rows.append(dict(line=l, plan=plan_name, buses=buses[l],
                         nominal_headway=h_nom, realized_mean_headway=mh,
                         headway_cv=cv, paired_share=pair,
                         half_headway=h_nom / 2.0,
                         corrected=(h_nom / 2.0) * (1 + cv ** 2),
                         realized_mean_wait=realized,
                         err_half=(realized - h_nom / 2.0) if realized else None,
                         err_corrected=(realized - (h_nom/2.0)*(1+cv**2)) if realized else None))
    return rows


# ---------------------------------------------------------------- H6 --------
def population_points():
    """The full synthetic travelling population (transit-market persons AND the
    car-choosing travellers) with their true origin coordinates."""
    with open(os.path.join(WORK, "person_meta.json")) as f:
        meta = json.load(f)
    net = T.Net(os.path.join(WORK, "base.net.xml"))
    pts = []
    for m in meta:
        e = m["oedge"]
        a, b = e[:2], e[2:]
        (ax, ay) = T.ncoord(*T.NODE_CR[a]); (bx, by) = T.ncoord(*T.NODE_CR[b])
        L = net.edge_len[e]
        f = min(1.0, m["opos"] / L)
        pts.append(dict(id=m["id"], x=ax + f*(bx-ax), y=ay + f*(by-ay),
                        zone=m["ozone"], car_avail=m["car_avail"]))
    return pts


def served_nodes(plan_name, buses, cycles):
    """Nodes with a stop served at >= COVER_MIN_FREQ_PER_H by at least one line."""
    net = T.Net(os.path.join(WORK, "base.net.xml"))
    plan = P.make_plan(plan_name, buses=buses)
    plan.cycles = cycles
    stops = T.plan_stops(plan, net)
    good = set()
    for sid, s in stops.items():
        for lid in s["lines"]:
            h = cycles[lid] / buses[lid]
            if 3600.0 / h >= COVER_MIN_FREQ_PER_H:
                good.add(s["node"]); break
    return good


def coverage(plan_name, buses, cycles, pts):
    good = served_nodes(plan_name, buses, cycles)
    coords = [T.ncoord(*T.NODE_CR[n]) for n in good]
    n_cov = 0
    by_zone = defaultdict(lambda: [0, 0])
    by_car = defaultdict(lambda: [0, 0])
    for p in pts:
        d = min((math.hypot(p["x"]-cx, p["y"]-cy) for cx, cy in coords), default=1e9)
        c = d <= COVER_RADIUS
        n_cov += c
        by_zone[p["zone"]][0] += c; by_zone[p["zone"]][1] += 1
        by_car[p["car_avail"]][0] += c; by_car[p["car_avail"]][1] += 1
    return dict(share=n_cov/len(pts), n=len(pts), served_nodes=sorted(good),
                by_zone={T.ZONE_NAME[z]: v[0]/v[1] for z, v in by_zone.items()},
                by_car_avail={str(k): v[0]/v[1] for k, v in by_car.items()})


# -------------------------------------------------- incidence / decomposition
def incidence(run_dirs):
    with open(os.path.join(WORK, "person_meta.json")) as f:
        meta = {m["id"]: m for m in json.load(f)}
    zone_gc, zone_n = defaultdict(float), defaultdict(int)
    car_gc, car_n = defaultdict(float), defaultdict(int)
    seg = defaultdict(lambda: defaultdict(float))
    segn = defaultdict(int)
    for d in run_dirs:
        with open(os.path.join(d, "persons.json")) as f:
            pers = json.load(f)
        for p in pers:
            if not p["complete"]:
                continue
            m = meta.get(p["id"])
            if not m:
                continue
            g = T.gen_cost(p)
            zone_gc[m["ozone"]] += g; zone_n[m["ozone"]] += 1
            car_gc[m["car_avail"]] += g; car_n[m["car_avail"]] += 1
            key = ("car_avail" if m["car_avail"] else "no_car")
            seg[key]["access"] += p["access"] + p["egress"]
            seg[key]["wait"] += p["wait"]
            seg[key]["ivt"] += p["ivt"]
            seg[key]["xwalk"] += p["xwalk"]
            seg[key]["xwait"] += p["xwait"]
            seg[key]["transfers"] += p["n_transfers"]
            seg[key]["gc"] += g
            segn[key] += 1
            k2 = "CBD_bound" if m["dzone"] == T.CBD_ZONE else "non_CBD"
            for f2 in ("access", "wait", "ivt", "xwalk", "xwait"):
                seg[k2][f2] += p[f2] if f2 != "access" else p["access"] + p["egress"]
            seg[k2]["transfers"] += p["n_transfers"]; seg[k2]["gc"] += g
            segn[k2] += 1
    return dict(by_zone={T.ZONE_NAME[z]: zone_gc[z]/zone_n[z] for z in zone_gc},
                by_zone_n={T.ZONE_NAME[z]: zone_n[z] for z in zone_n},
                by_car_avail={str(k): car_gc[k]/car_n[k] for k in car_gc},
                by_car_avail_n={str(k): car_n[k] for k in car_n},
                segments={k: {f: v/segn[k] for f, v in d.items()} for k, d in seg.items()},
                segment_n=dict(segn))


def main():
    cycles_all = H.load_json(H.CYCLE_FILE)
    demand_all = H.load_json(os.path.join(WORK, "linedemand.json"))
    s4 = H.load_json(os.path.join(WORK, "stage4_compare.json"))
    pts = population_points()
    out = dict(cover_radius=COVER_RADIUS, cover_min_freq_per_h=COVER_MIN_FREQ_PER_H,
               population=len(pts))

    print("=== H5: realized wait vs the half-headway assumption ===")
    print("%-11s %-6s %6s %10s %10s %8s %10s %12s %12s" % (
        "plan", "line", "buses", "h_nom(s)", "h_real(s)", "CV", "h/2", "(h/2)(1+CV2)",
        "realized wait"))
    h5rows = []
    for name, d in s4["summary"].items():
        rows = h5(d["dirs"], name, cycles_all[name], d["buses"])
        h5rows += rows
        for r in rows:
            print("%-11s %-6s %6d %10.1f %10.1f %8.3f %10.1f %12.1f %12.1f" % (
                name, r["line"], r["buses"], r["nominal_headway"],
                r["realized_mean_headway"], r["headway_cv"], r["half_headway"],
                r["corrected"], r["realized_mean_wait"]))
    out["h5"] = h5rows
    ok = [r for r in h5rows if r["realized_mean_wait"]]
    mae_half = st.mean([abs(r["err_half"]) for r in ok])
    mae_corr = st.mean([abs(r["err_corrected"]) for r in ok])
    bias_half = st.mean([r["err_half"] for r in ok])
    bias_corr = st.mean([r["err_corrected"] for r in ok])
    out["h5_summary"] = dict(n_lines=len(ok), mae_half=mae_half, mae_corrected=mae_corr,
                             bias_half=bias_half, bias_corrected=bias_corr,
                             mean_cv=st.mean([r["headway_cv"] for r in ok]))
    print(f"\n  across {len(ok)} lines: mean |error| using h/2 = {mae_half:.1f}s, "
          f"using (h/2)(1+CV^2) = {mae_corr:.1f}s; "
          f"bias {bias_half:+.1f}s vs {bias_corr:+.1f}s; mean CV "
          f"{st.mean([r['headway_cv'] for r in ok]):.3f}")

    print("\n=== H6: ridership vs coverage ===")
    cov = {}
    print("%-12s %10s %10s %12s %14s" % ("plan", "coverage", "riders", "GC(pax-h)",
                                         "GC/pax(s)"))
    for name, d in s4["summary"].items():
        c = coverage(name, d["buses"], cycles_all[name], pts)
        cov[name] = c
        print("%-12s %10.3f %10.1f %12.1f %14.1f" % (
            name, c["share"], d["ridership"], d["gc_total_mean"]/3600,
            d["gc_per_person_mean"]))
    out["coverage"] = cov

    # exchange rate between ridership and coverage across the three structures
    names = list(s4["summary"])
    ex = []
    for i in range(len(names)):
        for j in range(i+1, len(names)):
            a, b = names[i], names[j]
            dc = cov[a]["share"] - cov[b]["share"]
            dr = s4["summary"][a]["ridership"] - s4["summary"][b]["ridership"]
            ex.append(dict(pair=f"{a} vs {b}", d_coverage=dc, d_ridership=dr,
                           riders_per_coverage_point=(dr/(100*dc) if abs(dc) > 1e-9 else None)))
            print(f"  {a} vs {b}: dcoverage {dc:+.3f}, dridership {dr:+.1f} "
                  f"-> {dr/(100*dc) if abs(dc)>1e-9 else float('nan'):+.1f} riders per "
                  f"coverage point")
    out["ridership_coverage_exchange"] = ex

    print("\n=== distributional incidence (mean generalized cost, s) ===")
    inc = {}
    for name, d in s4["summary"].items():
        inc[name] = incidence(d["dirs"])
    out["incidence"] = inc
    zones = sorted(next(iter(inc.values()))["by_zone"])
    print("%-12s " % "plan" + " ".join(f"{z[:9]:>10s}" for z in zones))
    for name, v in inc.items():
        print("%-12s " % name + " ".join(f"{v['by_zone'].get(z, float('nan')):10.0f}"
                                         for z in zones))
    print("\nby car-availability group (1 = car available but travelling by transit):")
    for name, v in inc.items():
        print(f"  {name:12s} " + "  ".join(f"group{k}: {x:7.0f}s (n={v['by_car_avail_n'][k]})"
                                           for k, x in sorted(v["by_car_avail"].items())))
    print("\ngeneralized-cost decomposition by segment (mean s per completed rider):")
    hdr = ("plan", "segment", "access", "wait", "in-veh", "x-walk", "x-wait", "xfers", "GC")
    print("%-12s %-11s %8s %8s %8s %8s %8s %7s %9s" % hdr)
    for name, v in inc.items():
        for seg, s_ in v["segments"].items():
            print("%-12s %-11s %8.1f %8.1f %8.1f %8.1f %8.1f %7.3f %9.1f" % (
                name, seg, s_["access"], s_["wait"], s_["ivt"], s_["xwalk"],
                s_["xwait"], s_["transfers"], s_["gc"]))
    with open(OUTJ, "w") as f:
        json.dump(out, f, indent=1)
    print("\nwritten", OUTJ)


if __name__ == "__main__":
    main()
