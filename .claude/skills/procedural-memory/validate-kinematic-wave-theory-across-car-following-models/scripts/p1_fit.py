#!/usr/bin/env python3
"""PART 1b - aggregate the ring sweep over CRN replications, fit a triangular FD
per car-following model, and quantify how well a TRIANGLE actually describes each
model (that is the kinematic-wave-theory question, not just "what is capacity").
"""
import os, sys, json, math
import numpy as np

OUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEN, GAP, TAU, VF0 = 5.0, 2.5, 1.0, 30.0


def agg(points, key=('model', 'n_requested', 'perturb')):
    """Average the CRN replications within each cell; report the seed spread."""
    cells = {}
    for p in points:
        if 'error' in p:
            continue
        cells.setdefault(tuple(p[k] for k in key), []).append(p)
    out = []
    for kk, ps in cells.items():
        d = dict(zip(key, kk))
        for f in ('k', 'v', 'q', 'v_sd', 'halting_mean'):
            d[f] = float(np.mean([p[f] for p in ps]))
        d['q_seed_sd'] = float(np.std([p['q'] for p in ps], ddof=1)) if len(ps) > 1 else 0.0
        d['v_seed_sd'] = float(np.std([p['v'] for p in ps], ddof=1)) if len(ps) > 1 else 0.0
        d['n_reps'] = len(ps)
        out.append(d)
    return sorted(out, key=lambda d: (d['model'], d.get('perturb', True), d['k']))


def fit_model(pts, veh_len=LEN, min_gap=GAP):
    """pts: aggregated cells for ONE model (both perturbation branches merged)."""
    kk = np.array([p['k'] for p in pts])
    qq = np.array([p['q'] for p in pts])
    vv = np.array([p['v'] for p in pts])
    order = np.argsort(kk)
    kk, qq, vv = kk[order], qq[order], vv[order]

    vmax = vv.max()
    kpeak = kk[int(np.argmax(qq))]
    # FREE branch: the plateau-speed points below the flow peak.
    free = (vv >= 0.97 * vmax) & (kk <= kpeak)
    if free.sum() < 2:
        free = kk <= kpeak
    vf = float((kk[free] * qq[free]).sum() / (kk[free] ** 2).sum())   # OLS thru origin
    res_f = qq[free] - vf * kk[free]
    r2_free = 1 - float((res_f ** 2).sum()) / float(((qq[free] - qq[free].mean()) ** 2).sum())

    # CONGESTED branch: everything past the peak, excluding total-standstill points
    # (v<0.02 m/s) which carry no information about the slope w.
    cong = (kk > kpeak) & (vv > 0.02)
    A = np.vstack([kk[cong], np.ones(cong.sum())]).T
    (slope, icept), res, *_ = np.linalg.lstsq(A, qq[cong], rcond=None)
    w = -float(slope)
    kj = float(-icept / slope)
    pred = A @ np.array([slope, icept])
    r2_cong = 1 - float(((qq[cong] - pred) ** 2).sum()) / float(((qq[cong] - qq[cong].mean()) ** 2).sum())

    kc = w * kj / (vf + w)
    qmax = vf * kc

    # Robust free-flow speed: the space-mean speed at the LOWEST sampled density.
    # For a model with a curved (non-linear) free branch -- IDM -- the through-origin
    # OLS fit is biased low, so both figures are reported.
    v_free_lowk = float(vv[0])

    # Direct standstill measurement: lowest density whose mean speed is ~0.
    # A standstill is only a genuine JAM if the corresponding spacing is close to
    # the physical minimum (length+minGap).  A permanent full stop at a spacing far
    # ABOVE that minimum is a model/solver GRIDLOCK ARTIFACT, not jam density.
    zero = kk[vv < 0.02]
    kj_direct = float(zero.min()) if zero.size else float('nan')
    s_min = veh_len + min_gap
    spacing_at_standstill = (1000.0 / kj_direct) if kj_direct == kj_direct else float('nan')
    gridlock_artifact = bool(spacing_at_standstill == spacing_at_standstill
                             and spacing_at_standstill > 1.2 * s_min)
    cong_k_span = (float(kk[cong].min()), float(kk[cong].max())) if cong.sum() else (float('nan'),) * 2
    # extrapolation reach: how far past the last flowing point does the fit put k_j?


    # how much of the whole FD does the fitted triangle explain?
    tri = np.where(kk <= kc, vf * kk, np.maximum(w * (kj - kk), 0.0))
    r2_tri = 1 - float(((qq - tri) ** 2).sum()) / float(((qq - qq.mean()) ** 2).sum())
    mape_tri = float(np.mean(np.abs(qq - tri) / np.maximum(qq, 1.0)) * 100)

    return dict(v_free_kmh=vf, v_free_ms=vf / 3.6, r2_free_branch=r2_free,
                v_free_lowest_k_ms=v_free_lowk, k_lowest=float(kk[0]),
                w_kmh=w, w_ms=w / 3.6, k_jam_fit=kj, k_jam_standstill=kj_direct,
                k_crit=kc, q_max=qmax,
                q_max_observed=float(qq.max()),
                k_at_q_max_observed=float(kpeak),
                r2_cong_branch=r2_cong, r2_triangle_overall=r2_tri,
                mape_triangle_pct=mape_tri,
                n_free_pts=int(free.sum()), n_cong_pts=int(cong.sum()),
                cong_branch_k_span=cong_k_span,
                spacing_at_standstill_m=spacing_at_standstill,
                min_physical_spacing_m=s_min,
                gridlock_artifact=gridlock_artifact,
                kj_extrapolation_reach_vehkm=float(kj - cong_k_span[1]))


def bistability(cells):
    """Per model: largest |q_unperturbed - q_perturbed| over the density grid."""
    out = {}
    by = {}
    for c in cells:
        by.setdefault((c['model'], c['n_requested']), {})[c['perturb']] = c
    for (m, n), d in by.items():
        if True in d and False in d:
            qp, qn = d[True]['q'], d[False]['q']
            gap = qn - qp
            rec = out.setdefault(m, dict(max_abs_gap_vehh=0.0, at_k=None,
                                         q_unperturbed=None, q_perturbed=None,
                                         rel_pct=0.0, n_densities_gap_gt_2pct=0))
            if abs(gap) > 0.02 * max(qp, qn, 1):
                rec['n_densities_gap_gt_2pct'] += 1
            if abs(gap) > abs(rec['max_abs_gap_vehh']):
                rec.update(max_abs_gap_vehh=gap, at_k=d[True]['k'],
                           q_unperturbed=qn, q_perturbed=qp,
                           rel_pct=100.0 * gap / max(qp, 1e-9))
    return out


def main():
    pts = json.load(open(os.path.join(OUT, 'data', 'p1_ring_points.json')))
    cells = agg(pts)
    models = sorted(set(c['model'] for c in cells))
    fits = {m: fit_model([c for c in cells if c['model'] == m]) for m in models}
    # also fit each perturbation branch separately
    fits_branch = {}
    for m in models:
        for pflag, lbl in ((True, 'perturbed'), (False, 'unperturbed')):
            sub = [c for c in cells if c['model'] == m and c['perturb'] == pflag]
            fits_branch[f'{m}|{lbl}'] = fit_model(sub)

    theory = dict(k_jam_analytic=1000.0 / (LEN + GAP),
                  w_analytic_ms=(LEN + GAP) / TAU,
                  w_analytic_kmh=(LEN + GAP) / TAU * 3.6,
                  q_max_analytic=VF0 / (VF0 * TAU + LEN + GAP) * 3600,
                  v_free_analytic_ms=VF0,
                  k_crit_analytic=VF0 / (VF0 * TAU + LEN + GAP) * 3600 / (VF0 * 3.6))

    res = dict(theory=theory, fits=fits, fits_by_branch=fits_branch,
               bistability=bistability(cells))
    json.dump(res, open(os.path.join(OUT, 'data', 'p1_fd_fits.json'), 'w'), indent=2)
    json.dump(cells, open(os.path.join(OUT, 'data', 'p1_ring_cells.json'), 'w'), indent=1)

    print('ANALYTIC (length=5, minGap=2.5, tau=1.0, v_f=30 m/s):')
    for k, v in theory.items():
        print(f'   {k:24s} {v:9.2f}')
    print()
    hdr = f'{"model":7s} {"v_f m/s":>8s} {"q_max":>8s} {"k_c":>7s} {"k_j fit":>8s} {"k_j 0-spd":>9s} {"w m/s":>7s} {"w km/h":>7s} {"R2free":>7s} {"R2cong":>7s} {"R2tri":>7s}'
    print(hdr); print('-' * len(hdr))
    for m in models:
        f = fits[m]
        print(f'{m:7s} {f["v_free_ms"]:8.2f} {f["q_max"]:8.0f} {f["k_crit"]:7.1f} '
              f'{f["k_jam_fit"]:8.1f} {f["k_jam_standstill"]:9.1f} {f["w_ms"]:7.2f} '
              f'{f["w_kmh"]:7.2f} {f["r2_free_branch"]:7.4f} {f["r2_cong_branch"]:7.4f} '
              f'{f["r2_triangle_overall"]:7.4f}')
    print()
    print(f'{"model":7s} {"cong-k span":>16s} {"kj extrap reach":>16s} {"standstill spacing":>19s} {"gridlock?":>10s}')
    for m in models:
        f=fits[m]
        print(f'{m:7s} {str(tuple(round(x) for x in f["cong_branch_k_span"])):>16s} '
              f'{f["kj_extrapolation_reach_vehkm"]:16.1f} {f["spacing_at_standstill_m"]:19.2f} '
              f'{str(f["gridlock_artifact"]):>10s}')
    print('\nBISTABILITY (unperturbed minus perturbed flow at same density):')
    for m, b in res['bistability'].items():
        print(f'  {m:7s} max gap {b["max_abs_gap_vehh"]:8.1f} veh/h '
              f'({b["rel_pct"]:+6.1f}%) at k={b["at_k"]:.0f} veh/km; '
              f'{b["n_densities_gap_gt_2pct"]} densities with >2% gap')


if __name__ == '__main__':
    main()
