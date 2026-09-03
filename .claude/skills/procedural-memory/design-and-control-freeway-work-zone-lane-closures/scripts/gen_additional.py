"""Detector / output additional-file generation.

Detector `file=` paths are ABSOLUTISED (gotcha recorded in
`implement-coordinated-corridor-ramp-metering`: detector file paths resolve relative to
the additional file's own directory, so a shared additional file silently makes parallel
runs overwrite each other).  Every run gets its own additional file and output dir.

E1 stations
  det_disch_*   one per OPEN lane, 15 m before the end of the activity area (fE):
                the queue-discharge measurement point for work-zone capacity.
  det_up_*      one per lane at the start of the advance-warning area (fC): arrival rate.

E2 stations
  e2_s{ii}_{edge}_l{lane}  every ~500 m along the mainline, id convention taken from
  `implement-variable-speed-limits` so its speed-contour script's parser works.
  Plus e2_ctrl_* on the last 400 m of fC -- the dynamic-merge / VSL controller input.
"""
import os
import xml.etree.ElementTree as ET

import wz_common as W

E1_PERIOD = 60.0
E2_PERIOD = 60.0
EDGEDATA_PERIOD = 300.0
STATION_SPACING = 500.0


def _edge_lengths(netfile):
    t = W.net_lane_table(netfile)
    return {e: (lanes[0][1], len(lanes)) for e, lanes in t.items()}


def build(netfile, outdir, label, edgedata=True, emissions=True, e2=True,
          fcd_edges=None):
    os.makedirs(outdir, exist_ok=True)
    el = _edge_lengths(netfile)
    lines = ['<additional>']

    # ---------------- E1 discharge station (activity-area exit)
    fe_len, fe_n = el["fE"]
    for i in range(fe_n):
        lines.append(f'  <inductionLoop id="det_disch_l{i}" lane="fE_{i}" '
                     f'pos="{fe_len-15:.1f}" period="{E1_PERIOD}" '
                     f'file="{outdir}/e1_disch.xml" friendlyPos="true"/>')
    # ---------------- E1 upstream arrival station (start of advance warning)
    fc_len, fc_n = el["fC"]
    for i in range(fc_n):
        lines.append(f'  <inductionLoop id="det_up_l{i}" lane="fC_{i}" pos="20" '
                     f'period="{E1_PERIOD}" file="{outdir}/e1_up.xml" friendlyPos="true"/>')
    # ---------------- E1 on the detour arterial (diverted flow) and the on-ramp
    for eid in ("rOFF", "rON"):
        lines.append(f'  <inductionLoop id="det_{eid}" lane="{eid}_0" pos="20" '
                     f'period="{E1_PERIOD}" file="{outdir}/e1_ramp.xml" friendlyPos="true"/>')

    # ---------------- E2 corridor stations for the speed contour
    if e2:
        dist = 0.0
        s = 0
        for eid in W.MAINLINE_ORDER:
            L, n = el[eid]
            nst = max(1, int(round(L / STATION_SPACING)))
            seg = L / nst
            for k in range(nst):
                pos = k * seg
                length = min(seg, L - pos) - 1.0
                if length < 20:
                    continue
                for li in range(n):
                    lines.append(
                        f'  <laneAreaDetector id="e2_s{s:02d}_{eid}_l{li}" lane="{eid}_{li}" '
                        f'pos="{pos:.1f}" length="{length:.1f}" period="{E2_PERIOD}" '
                        f'file="{outdir}/e2.xml" friendlyPos="true"/>')
                s += 1
            dist += L
        # VSL / bottleneck-reporting input: last 400 m of the advance-warning area.
        for li in range(fc_n):
            lines.append(f'  <laneAreaDetector id="e2_ctrl_l{li}" lane="fC_{li}" '
                         f'pos="{max(0.0, fc_len-400):.1f}" length="395" period="{E2_PERIOD}" '
                         f'file="{outdir}/e2_ctrl.xml" friendlyPos="true"/>')
        # DYNAMIC-MERGE controller input: last 400 m of fB, i.e. UPSTREAM OF BOTH
        # candidate merge points.  The fC station above is downstream of the early-merge
        # bottleneck and reads free flow whenever early merge is active, which makes a
        # feedback controller that starts in EARLY mode structurally blind to its own
        # queue.  Verified: fC occupancy was 30-39% under do-nothing/late but only
        # 7-11% under early at the SAME demand.
        fb_len, fb_n = el["fB"]
        for li in range(fb_n):
            lines.append(f'  <laneAreaDetector id="e2_up_l{li}" lane="fB_{li}" '
                         f'pos="{max(0.0, fb_len-400):.1f}" length="395" period="{E2_PERIOD}" '
                         f'file="{outdir}/e2_up.xml" friendlyPos="true"/>')

    # ---------------- edgeData (traffic + emissions), withInternal for honest TSTT
    if edgedata:
        lines.append(f'  <edgeData id="ed" period="{EDGEDATA_PERIOD}" '
                     f'file="{outdir}/edgedata.xml" excludeEmpty="false" withInternal="true"/>')
    if emissions:
        lines.append(f'  <edgeData id="em" type="emissions" period="{EDGEDATA_PERIOD}" '
                     f'file="{outdir}/emissions.xml" excludeEmpty="true" withInternal="true"/>')
    lines.append('</additional>')

    path = os.path.join(outdir, f"add_{label}.add.xml")
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def station_distances(netfile):
    """{station_index: cumulative distance along the corridor} for the contour plot."""
    el = _edge_lengths(netfile)
    out = {}
    dist = 0.0
    s = 0
    for eid in W.MAINLINE_ORDER:
        L, n = el[eid]
        nst = max(1, int(round(L / STATION_SPACING)))
        seg = L / nst
        for k in range(nst):
            pos = k * seg
            length = min(seg, L - pos) - 1.0
            if length < 20:
                continue
            out[s] = dist + pos + length / 2.0
            s += 1
        dist += L
    return out
