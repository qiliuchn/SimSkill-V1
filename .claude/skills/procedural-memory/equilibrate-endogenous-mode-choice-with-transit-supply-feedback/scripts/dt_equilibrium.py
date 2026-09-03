"""Outer mode-split equilibrium loop (outside SUMO).

The decision variable is the car share p.  The Wardrop-across-modes condition is
    gap(p) = C_car(p) - C_transit(p) = 0      (interior equilibrium)
    gap(p) <= 0 at p = p_max                  (car-only corner)
    gap(p) >= 0 at p = p_min                  (transit-only corner)
with all costs MEASURED from SUMO raw output, never assumed.

IMPORTANT (discovered empirically in this episode, not assumed a priori):
gap(p) is NOT monotone once the Mohring feedback is switched on, so the system can
have MORE THAN ONE interior equilibrium.  A sign change from - to + as p rises is a
STABLE (attracting) equilibrium -- below it car is cheaper so travellers move right,
above it car is dearer so they move left.  A sign change from + to - is an UNSTABLE
(repelling) equilibrium: a tipping point beyond which the transit death-spiral runs to
the car-only corner.  We therefore SCAN first, classify every root, and only then
bisect -- a bare bisection on [0.01, 0.99] silently mislabels the whole thing.

Three routines:
  scan_gap       coarse grid of gap(p), with replications
  solve          scan -> classify roots -> bisect the stable root to |gap| <= tol
  msa_loop       natural day-to-day adjustment (MSA), used as the STABILITY probe
"""
import dt_runner as R


def _ev(net, n_total, p, seeds, feedback, tag, rule_kw, workers):
    r = R.eval_point(net, n_total, p, seeds, feedback=feedback, tagbase=tag,
                     rule_kw=rule_kw, workers=workers)
    r["gap"] = r["car_cost"] - r["transit_cost"]
    return r


def _row(it, r, extra=None):
    d = dict(iter=it, p_car=r["p_car"], n_car=r["n_car"], n_transit=r["n_transit"],
             headway=r["headway"], car_cost=r["car_cost"], car_cost_ci=r["car_cost_ci"],
             transit_cost=r["transit_cost"], transit_cost_ci=r["transit_cost_ci"],
             transit_wait=r["transit_wait"], transit_ivt=r["transit_ivt"],
             car_duration=r["car_duration"], car_departdelay=r["car_departdelay"],
             gap=r["gap"], person_hours=r["person_hours"], reps=r["reps"])
    if extra:
        d.update(extra)
    return d


def scan_gap(net, n_total, seeds, feedback, rule_kw, tag, grid, workers=8):
    out = []
    for p in grid:
        r = _ev(net, n_total, p, seeds, feedback, f"{tag}_sc{int(round(p*1000))}",
                rule_kw, workers)
        out.append((p, r))
    return out


def classify_roots(scan):
    """Return list of dicts describing each sign change in the scanned gap function."""
    roots = []
    for i in range(len(scan) - 1):
        p0, r0 = scan[i]
        p1, r1 = scan[i + 1]
        g0, g1 = r0["gap"], r1["gap"]
        if g0 < 0 <= g1:
            roots.append(dict(lo=p0, hi=p1, gap_lo=g0, gap_hi=g1, kind="stable"))
        elif g0 > 0 >= g1:
            roots.append(dict(lo=p0, hi=p1, gap_lo=g0, gap_hi=g1, kind="unstable"))
    return roots


def solve(net, n_total, seeds, feedback=True, rule_kw=None, tag="eq",
          grid=None, iters=12, tol=5.0, workers=8, verbose=True):
    """Full equilibrium solve.  Returns (equilibrium, trace, diagnostics)."""
    rule_kw = rule_kw or {}
    grid = grid or [round(0.05 + 0.05 * i, 3) for i in range(19)]   # 0.05 .. 0.95
    scan = scan_gap(net, n_total, seeds, feedback, rule_kw, tag, grid, workers)
    trace = [_row(0, r, dict(step="scan")) for _, r in scan]
    roots = classify_roots(scan)
    if verbose:
        print(f"  scan gap: " + "  ".join(f"{p:.2f}:{r['gap']:+.0f}" for p, r in scan))
        print(f"  roots: {roots}")

    diag = dict(roots=roots, n_roots=len(roots),
                n_stable=sum(1 for x in roots if x["kind"] == "stable"),
                n_unstable=sum(1 for x in roots if x["kind"] == "unstable"))

    stable = [x for x in roots if x["kind"] == "stable"]
    if not stable:
        # corner solution: pick whichever end the adjustment dynamic runs to
        if scan[-1][1]["gap"] < 0:
            eq = scan[-1][1]
            eq["corner"] = "car_only"
        else:
            eq = scan[0][1]
            eq["corner"] = "transit_only"
        eq["converged"] = True
        eq["equilibrium_type"] = "corner"
        return eq, trace, diag

    lo, hi = stable[0]["lo"], stable[0]["hi"]
    best = None
    for k in range(1, iters + 1):
        mid = 0.5 * (lo + hi)
        rm = _ev(net, n_total, mid, seeds, feedback, f"{tag}_b{k}", rule_kw, workers)
        trace.append(_row(k, rm, dict(step="bisect", lo=lo, hi=hi)))
        if verbose:
            print(f"  it{k:2d} p={mid:.4f} Ccar={rm['car_cost']:8.1f} "
                  f"Ctr={rm['transit_cost']:7.1f} gap={rm['gap']:+8.1f} H={rm['headway']:.0f}")
        if best is None or abs(rm["gap"]) < abs(best["gap"]):
            best = rm
        if abs(rm["gap"]) <= tol:
            break
        if rm["gap"] < 0:
            lo = mid
        else:
            hi = mid
    best["corner"] = None
    best["converged"] = abs(best["gap"]) <= tol
    best["equilibrium_type"] = "interior_stable"
    return best, trace, diag


def msa_loop(net, n_total, seeds, feedback=True, rule_kw=None, tag="msa", p0=0.5,
             iters=18, workers=8, verbose=True):
    """Natural day-to-day adjustment: travellers move towards whichever mode was
    cheaper yesterday, damped by the MSA 1/(k+1) step.  This is the STABILITY probe --
    it is the dynamic that a real fixed point has to be attracting under."""
    rule_kw = rule_kw or {}
    trace, p = [], p0
    for k in range(1, iters + 1):
        r = _ev(net, n_total, p, seeds, feedback, f"{tag}_i{k}", rule_kw, workers)
        y = 1.0 if r["gap"] < 0 else 0.0          # all-or-nothing auxiliary share
        p_next = min(0.99, max(0.01, p + (y - p) / (k + 1.0)))
        trace.append(_row(k, r, dict(step="msa", p_start=p0, p_next=p_next, aux=y)))
        if verbose:
            print(f"  msa{k:2d} p={p:.4f} Ccar={r['car_cost']:8.1f} Ctr={r['transit_cost']:7.1f} "
                  f"gap={r['gap']:+8.1f} H={r['headway']:.0f} -> p'={p_next:.4f}")
        p = p_next
    return trace
