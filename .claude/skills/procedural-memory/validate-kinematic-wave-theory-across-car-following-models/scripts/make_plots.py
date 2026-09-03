#!/usr/bin/env python3
"""All figures for the report.

Palette: the validated categorical instance from the `dataviz` skill
(`references/palette.md`, slots 1-5), checked with scripts/validate_palette.js:
ALL CHECKS PASS on the light surface (worst adjacent CVD dE 9.1 protan, normal-
vision dE 19.6).  The validator's contrast WARN for the aqua/yellow/magenta slots
is discharged by (a) a legend on every multi-series panel, (b) direct labels, and
(c) the full numeric table view in FINDINGS.md.

Colour follows the ENTITY (the car-following model), never its rank, and the slot
order is fixed across every figure.
"""
import os, sys, json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wave_lib as W

OUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D, P = os.path.join(OUT, 'data'), os.path.join(OUT, 'plots')
os.makedirs(P, exist_ok=True)

SURFACE, INK, INK2, MUTED, GRID = '#fcfcfb', '#0b0b0b', '#52514e', '#898781', '#e1e0d9'
CLR = {'Krauss': '#2a78d6', 'IDM': '#eb6834', 'EIDM': '#1baf7a',
       'ACC': '#eda100', 'W99': '#e87ba4'}
ORDER = ['Krauss', 'IDM', 'EIDM', 'ACC', 'W99']

plt.rcParams.update({
    'figure.facecolor': SURFACE, 'axes.facecolor': SURFACE,
    'savefig.facecolor': SURFACE, 'axes.edgecolor': '#c3c2b7',
    'axes.labelcolor': INK2, 'text.color': INK, 'xtick.color': MUTED,
    'ytick.color': MUTED, 'grid.color': GRID, 'grid.linewidth': 0.8,
    'axes.grid': True, 'axes.axisbelow': True, 'font.size': 9,
    'axes.titlesize': 10, 'legend.frameon': False, 'lines.linewidth': 2,
    'axes.spines.top': False, 'axes.spines.right': False,
})


def save(fig, name):
    fig.tight_layout()
    fig.savefig(os.path.join(P, name), dpi=150)
    plt.close(fig)
    print('wrote', name)


# ============================================================ FIG 1: FD panels ==
def fig_fd():
    cells = json.load(open(os.path.join(D, 'p1_ring_cells.json')))
    fits = json.load(open(os.path.join(D, 'p1_fd_fits.json')))
    th = fits['theory']
    fig, axes = plt.subplots(2, 3, figsize=(13.5, 7.6), sharex=True)
    for ax, m in zip(axes.flat, ORDER):
        c = CLR[m]
        f = fits['fits'][m]
        for pf, mk, fc, lbl in ((False, 'o', 'none', 'unperturbed'),
                                (True, 'o', c, 'after brake pulse')):
            s = sorted([x for x in cells if x['model'] == m and x['perturb'] == pf],
                       key=lambda z: z['k'])
            ax.plot([x['k'] for x in s], [x['q'] for x in s], mk, ms=4.5,
                    mfc=fc, mec=c, mew=1.3, ls='none', label=lbl, zorder=3)
        kk = np.linspace(0, f['k_jam_fit'], 200)
        tri = np.where(kk <= f['k_crit'], f['v_free_kmh'] * kk,
                       f['w_kmh'] * (f['k_jam_fit'] - kk))
        ax.plot(kk, tri, '-', color=c, lw=2, alpha=.85, label='fitted triangle', zorder=4)
        ka = np.linspace(0, th['k_jam_analytic'], 200)
        tria = np.where(ka <= th['k_crit_analytic'], th['v_free_analytic_ms'] * 3.6 * ka,
                        th['w_analytic_kmh'] * (th['k_jam_analytic'] - ka))
        ax.plot(ka, tria, ':', color=MUTED, lw=1.6, label='analytic triangle', zorder=2)
        ax.set_title(f'{m}   $q_{{max}}$={f["q_max"]:.0f}  $k_j$={f["k_jam_fit"]:.0f}  '
                     f'$w$={f["w_ms"]:.2f} m/s  $R^2_{{tri}}$={f["r2_triangle_overall"]:.3f}',
                     color=INK)
        ax.set_xlim(0, 140); ax.set_ylim(0, 3000)
        ax.legend(fontsize=7.5, loc='upper right', labelcolor=INK2)
    ax = axes.flat[5]
    for m in ORDER:
        f = fits['fits'][m]
        kk = np.linspace(0, f['k_jam_fit'], 200)
        tri = np.where(kk <= f['k_crit'], f['v_free_kmh'] * kk,
                       f['w_kmh'] * (f['k_jam_fit'] - kk))
        ax.plot(kk, tri, '-', color=CLR[m], label=m)
        # direct label placed on the congested branch, where the lines are well
        # separated -- labelling at the apex collided (all peaks are within 600 veh/h)
        kd = f['k_crit'] + 0.62 * (f['k_jam_fit'] - f['k_crit'])
        ax.annotate(m, (kd, f['w_kmh'] * (f['k_jam_fit'] - kd)),
                    textcoords='offset points', xytext=(3, 4), color=CLR[m],
                    fontsize=8.5, fontweight='bold')
    ax.plot(ka, tria, ':', color=MUTED, lw=1.6, label='analytic')
    ax.set_title('fitted triangles, all models', color=INK)
    ax.set_xlim(0, 140); ax.set_ylim(0, 3000)
    ax.legend(fontsize=7.5, labelcolor=INK2)
    for ax in axes[1]:
        ax.set_xlabel('density k  [veh/km]')
    for ax in axes[:, 0]:
        ax.set_ylabel('flow q  [veh/h]')
    fig.suptitle('Fig 1  Ring-road fundamental diagram per car-following model '
                 '(density controlled exactly by vehicle count, 1000 m single-lane ring)',
                 color=INK, fontsize=11, y=1.0)
    save(fig, 'fig1_fundamental_diagrams.png')


# ======================================================= FIG 2: speed-density ==
def fig_speed():
    cells = json.load(open(os.path.join(D, 'p1_ring_cells.json')))
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.4))
    for m in ORDER:
        s = sorted([x for x in cells if x['model'] == m and x['perturb']],
                   key=lambda z: z['k'])
        axes[0].plot([x['k'] for x in s], [x['v'] for x in s], '-o', ms=3,
                     color=CLR[m], label=m)
        axes[1].plot([x['v'] for x in s], [x['q'] for x in s], '-o', ms=3,
                     color=CLR[m], label=m)
    axes[0].set_xlabel('density k  [veh/km]'); axes[0].set_ylabel('space-mean speed  [m/s]')
    axes[0].set_title('speed-density', color=INK)
    axes[1].set_xlabel('space-mean speed  [m/s]'); axes[1].set_ylabel('flow q  [veh/h]')
    axes[1].set_title('flow-speed', color=INK)
    for ax in axes:
        ax.legend(fontsize=8, labelcolor=INK2)
    fig.suptitle('Fig 2  The other two projections of the same ring measurements '
                 '(perturbed branch)', color=INK, fontsize=11)
    save(fig, 'fig2_speed_density.png')


# ================================================= FIG 3: parameter -> feature ==
def fig_param():
    rows = json.load(open(os.path.join(D, 'p2_param_table.json')))
    factors = ['tau', 'minGap', 'length', 'sigma']
    feats = [('err_k_jam_pct', '$k_j$ error [%]'), ('err_w_pct', '$w$ error [%]'),
             ('err_q_max_pct', '$q_{max}$ error [%]')]
    fig, axes = plt.subplots(3, 4, figsize=(14, 8), sharey='row')
    for i, (fld, ylab) in enumerate(feats):
        for j, fac in enumerate(factors):
            ax = axes[i][j]
            for m in ['Krauss', 'IDM', 'EIDM']:
                s = sorted([r for r in rows if r['model'] == m and r['variant'] == fac],
                           key=lambda z: z['value'])
                if not s:
                    continue
                ax.plot([r['value'] for r in s], [r[fld] for r in s], '-o', ms=5,
                        color=CLR[m], label=m)
            ax.axhline(0, color='#c3c2b7', lw=1.2, zorder=1)
            ax.axhspan(-10, 10, color=GRID, alpha=.55, zorder=0)
            if i == 0:
                ax.set_title(f'sweep: {fac}', color=INK)
            if i == 2:
                ax.set_xlabel(fac)
            if j == 0:
                ax.set_ylabel(ylab)
    axes[0][0].legend(fontsize=8, labelcolor=INK2)
    fig.suptitle('Fig 3  Measured-minus-predicted error of the closed forms '
                 r'$k_j=1000/(len+gap)$,  $w=(len+gap)/\tau$,  '
                 r'$q_{max}=v_f/(v_f\tau+len+gap)$   (shaded band = $\pm$10%)',
                 color=INK, fontsize=11)
    save(fig, 'fig3_parameter_to_fd_feature.png')


# ========================================== FIG 4/5: annotated time-space plots ==
def _timespace(ax, fcd, t0, t1, xlo, xhi, color, every=3):
    veh = W.read_fcd(fcd)
    for i, (vid, (t, x, v)) in enumerate(veh.items()):
        if i % every:
            continue
        m = (t >= t0) & (t <= t1) & (x >= xlo) & (x <= xhi)
        if m.sum() > 2:
            ax.plot(t[m], x[m], '-', color=MUTED, lw=0.55, alpha=.75, zorder=2)
    return veh


def fig_timespace_incident():
    res = json.load(open(os.path.join(D, 'p3_waves.json')))
    fig, axes = plt.subplots(1, 4, figsize=(15, 4.3), sharey=True)
    for ax, m in zip(axes, ['Krauss', 'IDM', 'EIDM', 'ACC']):
        r = res[f'{m}|incident']
        ps = r['per_seed'][0]
        tb, tr = ps['per_cycle'][0]['red_on'], ps['per_cycle'][0]['green_on']
        _timespace(ax, os.path.join(OUT, 'runs', 'p3', f'inc_{m}_s42.fcd.xml'),
                   tb - 80, tr + 160, 800, 2500, CLR[m], every=2)
        for fr, lbl, st in ((ps['per_cycle'][0]['stop_front'], 'stopping front', '-'),
                            (ps['per_cycle'][0]['start_front'], 'start-up front', '--')):
            pts = np.array(fr['points'])
            ax.plot(pts[:, 0], pts[:, 1], 'o', ms=3.5, color=CLR[m], zorder=4)
            tt = np.linspace(fr['t_span'][0], fr['t_span'][1], 10)
            ax.plot(tt, fr['intercept'] + fr['speed_ms'] * tt, st, color=CLR[m], lw=2.2,
                    zorder=5, label=f'{lbl}: {fr["speed_ms"]:.2f} m/s ($R^2$={fr["r2"]:.3f})')
        ax.axvspan(tb, tr, color='#e1e0d9', alpha=.5, zorder=1)
        ax.axhline(2400, color='#c3c2b7', lw=1.2, ls=':')
        ax.set_title(f'{m}\nRH predicts stop {r["stop_front_predicted_ms"]:.2f}, '
                     f'start {r["start_front_predicted_ms"]:.2f} m/s', color=INK, fontsize=9)
        ax.set_xlabel('time [s]')
        ax.legend(fontsize=7, loc='lower left', labelcolor=INK2)
    axes[0].set_ylabel('position along link [m]')
    fig.suptitle('Fig 4  Incident (full single-lane blockage, shaded): FCD trajectories with '
                 'fitted wave fronts, vs Rankine-Hugoniot from each model\'s own FD',
                 color=INK, fontsize=11)
    save(fig, 'fig4_timespace_incident.png')


def fig_timespace_signal():
    res = json.load(open(os.path.join(D, 'p3_waves.json')))
    fig, axes = plt.subplots(1, 4, figsize=(15, 4.3), sharey=True)
    for ax, m in zip(axes, ['Krauss', 'IDM', 'EIDM', 'ACC']):
        r = res[f'{m}|signal']
        ps = r['per_seed'][0]
        cyc = ps['per_cycle'][2]
        red, grn = cyc['red_on'], cyc['green_on']
        _timespace(ax, os.path.join(OUT, 'runs', 'p3', f'sig_{m}_s42.fcd.xml'),
                   red - 90, grn + 90, 1500, 2050, CLR[m], every=1)
        for fr, lbl, st in ((cyc['stop_front'], 'stopping front', '-'),
                            (cyc['start_front'], 'start-up front', '--')):
            if not fr.get('points'):
                continue
            pts = np.array(fr['points'])
            ax.plot(pts[:, 0], pts[:, 1], 'o', ms=3.5, color=CLR[m], zorder=4)
            tt = np.linspace(fr['t_span'][0], fr['t_span'][1], 10)
            ax.plot(tt, fr['intercept'] + fr['speed_ms'] * tt, st, color=CLR[m], lw=2.2,
                    zorder=5, label=f'{lbl}: {fr["speed_ms"]:.2f} m/s ($R^2$={fr["r2"]:.3f})')
        ax.axvspan(red, grn, color='#e1e0d9', alpha=.5, zorder=1)
        ax.axhline(2000, color='#c3c2b7', lw=1.2, ls=':')
        ax.set_title(f'{m}\nRH predicts stop {r["stop_front_predicted_ms"]:.2f}, '
                     f'start {r["start_front_predicted_ms"]:.2f} m/s', color=INK, fontsize=9)
        ax.set_xlabel('time [s]')
        ax.legend(fontsize=7, loc='lower left', labelcolor=INK2)
    axes[0].set_ylabel('position along approach [m]')
    fig.suptitle('Fig 5  Signalised link (red interval shaded, stop line dotted): FCD '
                 'trajectories with fitted stopping and start-up waves', color=INK, fontsize=11)
    save(fig, 'fig5_timespace_signal.png')


# ============================================================ FIG 6: cap drop ==
def fig_capdrop():
    s = json.load(open(os.path.join(D, 'p4_capacity_drop.json')))
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.6))
    for ax, kind, ttl in ((axes[0], 'lanedrop', '2 -> 1 lane drop  (lane changing present)'),
                          (axes[1], 'speeddrop',
                           '1 lane, 30 -> 10 m/s speed drop  (NO lane changing)')):
        for m in ['Krauss', 'IDM', 'EIDM', 'ACC']:
            r = s[f'{kind}|{m}']
            ax.plot([x['demand'] for x in r['rows']], [x['q_bn'] for x in r['rows']],
                    '-o', ms=4, color=CLR[m],
                    label=f'{m}  drop {r["capacity_drop_pct"]:+.1f}%')
        lim = ax.get_xlim()
        ax.plot(lim, lim, ':', color=MUTED, lw=1.4, label='flow = demand')
        ax.set_xlim(lim)
        ax.set_xlabel('offered demand [veh/h]'); ax.set_ylabel('bottleneck discharge [veh/h]')
        ax.set_title(ttl, color=INK, fontsize=9.5)
        ax.legend(fontsize=7.5, labelcolor=INK2)
    fig.suptitle('Fig 6  Two-capacity test: the gap between the last point on the '
                 '"flow = demand" line and the post-breakdown plateau IS the capacity drop',
                 color=INK, fontsize=11)
    save(fig, 'fig6_capacity_drop.png')


# ==================================================== FIG 7: moving bottleneck ==
def fig_mb():
    rows = json.load(open(os.path.join(D, 'p5_moving_bottleneck.json')))
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.6))
    for ax, lanes, ttl in ((axes[0], 1, '1 lane: platoon flow behind the truck\n'
                                        'vs the FD point with chord slope $u$'),
                           (axes[1], 2, '2 lanes: discharge past the truck\n'
                                        r'vs Newell $q_d=\max_k[q-uk]/(1-u/v_f)$')):
        for m in ['Krauss', 'IDM', 'EIDM', 'ACC']:
            s = [r for r in rows if r['lanes'] == lanes and r['model'] == m]
            us = [r['u_ms'] for r in s]
            ax.plot(us, [r['q_predicted'] for r in s], ':', color=CLR[m], lw=1.6)
            ax.plot(us, [r['q_measured_saturated'] for r in s], '-o', ms=6,
                    color=CLR[m], label=m)
        ax.set_xlabel('truck speed u [m/s]'); ax.set_ylabel('saturated flow [veh/h]')
        ax.set_title(ttl, color=INK, fontsize=9.5)
        ax.legend(fontsize=8, labelcolor=INK2,
                  title='solid = measured, dotted = theory', title_fontsize=7.5)
    fig.suptitle('Fig 7  Moving bottleneck: measured vs Newell prediction from each '
                 "model's own ring FD", color=INK, fontsize=11)
    save(fig, 'fig7_moving_bottleneck.png')


# ======================================================== FIG 8: consequence ===
def fig_consequence():
    c = json.load(open(os.path.join(D, 'p6_consequence.json')))
    ms = c['models']
    names = ['Krauss', 'IDM', 'EIDM', 'ACC']
    fig, axes = plt.subplots(1, 4, figsize=(14, 4.2))
    panels = [('q_max', lambda m: ms[m]['fd']['q_max'], 'capacity $q_{max}$ [veh/h]',
               'MATCHED by construction'),
              ('v_f', lambda m: ms[m]['fd']['v_free_lowest_k_ms'],
               'free-flow speed [m/s]', 'MATCHED by construction'),
              ('w', lambda m: ms[m]['fd']['w_ms'], 'backward wave $w$ [m/s]',
               'still differs'),
              ('kj', lambda m: ms[m]['fd']['k_jam_fit'], 'jam density $k_j$ [veh/km]',
               'still differs')]
    for ax, (key, fn, ylab, note) in zip(axes, panels):
        vals = [fn(m) for m in names]
        ax.bar(names, vals, color=[CLR[m] for m in names], width=.62)
        for i, v in enumerate(vals):
            ax.text(i, v, f'{v:.1f}' if v < 100 else f'{v:.0f}', ha='center',
                    va='bottom', fontsize=8.5, color=INK)
        ax.set_ylabel(ylab)
        ax.set_title(note, color=INK2, fontsize=9)
        ax.grid(axis='x', visible=False)
        ax.set_ylim(0, max(vals) * 1.22)
    fig.suptitle('Fig 8a  Four models tuned (via tau) to the SAME capacity and the same '
                 'free-flow speed still disagree on w and $k_j$', color=INK, fontsize=11)
    save(fig, 'fig8a_matched_models.png')

    fig, ax = plt.subplots(figsize=(7.6, 4.4))
    xs = np.arange(len(names))
    meas = [ms[m]['spillback_time_measured_s'] for m in names]
    pred = [ms[m]['spillback_time_predicted_s'] for m in names]
    clr = [ms[m]['clearance_time_measured_s'] for m in names]
    ax.bar(xs - .22, meas, .2, color=[CLR[m] for m in names], label='spillback (measured)')
    ax.bar(xs, pred, .2, color=[CLR[m] for m in names], alpha=.42,
           label='spillback (kinematic-wave prediction)')
    ax.bar(xs + .22, clr, .2, color=[CLR[m] for m in names], alpha=.2,
           edgecolor=[CLR[m] for m in names], label='incident clearance (measured)')
    for i in range(len(names)):
        ax.text(xs[i] - .22, meas[i], f'{meas[i]:.0f}', ha='center', va='bottom', fontsize=8)
        ax.text(xs[i] + .22, clr[i], f'{clr[i]:.0f}', ha='center', va='bottom', fontsize=8)
    ax.set_xticks(xs); ax.set_xticklabels(names)
    ax.set_ylabel('time [s]'); ax.grid(axis='x', visible=False)
    ax.legend(fontsize=8, labelcolor=INK2)
    ax.set_title('Fig 8b  Same capacity, same free-flow speed -> different answers:\n'
                 'time for an incident queue to spill back 600 m, and to clear',
                 color=INK, fontsize=10)
    save(fig, 'fig8b_consequence.png')


if __name__ == '__main__':
    fig_fd(); fig_speed(); fig_param()
    fig_timespace_incident(); fig_timespace_signal()
    fig_capdrop(); fig_mb(); fig_consequence()
