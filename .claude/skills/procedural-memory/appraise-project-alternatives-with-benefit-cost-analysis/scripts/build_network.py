#!/usr/bin/env python3
"""
Build the signalized arterial test corridor used by the economic-appraisal workflow.

Two geometric variants on the SAME node/edge skeleton:
  * base : 5 signalized intersections, arterial = 2 lanes/direction (lefts share the
           left through lane), cross streets = 1 lane/direction.
  * bay  : identical, except that at the two "worst" intersections (given by
           --bay-junctions) every approach gets an EXCLUSIVE left-turn bay:
             - arterial approach: 2 lanes -> 3 lanes over the last <bay-length> m
               (lane0 through+right, lane1 through, lane2 LEFT ONLY)
             - cross approach:    1 lane  -> 2 lanes over the last <bay-length> m
               (lane0 through+right, lane1 LEFT ONLY)

Entry/exit edge IDs are IDENTICAL across variants (only the downstream end of an
approach is split), so one demand (trips) file is valid for both -> Common Random
Numbers across alternatives.

Usage:
  python build_network.py --variant base --out-dir OUT
  python build_network.py --variant bay --bay-junctions J2,J3 --bay-length 90 --out-dir OUT
"""
import argparse
import os
import subprocess
import sys

# --- corridor geometry -------------------------------------------------------
N_INT = 5
SPACING = 400.0          # m between signalized intersections
X0 = 0.0
CROSS_LEN = 300.0        # m of cross street on each side
APPROACH_W = 350.0       # arterial stub length beyond the end intersections
ART_SPEED = 13.89        # m/s (50 km/h)
CRS_SPEED = 11.11        # m/s (40 km/h)
ART_LANES = 2
CRS_LANES = 1
ART_PRIO = 4
CRS_PRIO = 2


def jx(i):
    """x-coordinate of intersection Ji (i = 1..5)."""
    return X0 + (i - 1) * SPACING


def build_plain_xml(out_dir, split_junctions, with_bays, bay_len):
    nodes, edges, conns = [], [], []

    # ---- nodes ----
    nodes.append(('W', X0 - APPROACH_W, 0.0, 'priority'))
    nodes.append(('E', jx(N_INT) + APPROACH_W, 0.0, 'priority'))
    for i in range(1, N_INT + 1):
        nodes.append((f'J{i}', jx(i), 0.0, 'traffic_light'))
        nodes.append((f'N{i}', jx(i), CROSS_LEN, 'priority'))
        nodes.append((f'S{i}', jx(i), -CROSS_LEN, 'priority'))

    # ---- helper to emit an edge, optionally split for a left-turn bay ----
    # An approach is (from_node, to_node, nlanes, speed, prio, unit_vector towards to_node)
    def add_approach(frm, to, nlanes, speed, prio, ux, uy, fx, fy, tx, ty, arterial):
        """Emit either one edge frm->to, or (if `to` is a split junction) a split pair.

        The split is applied to BOTH variants at the same locations, so the compiled
        approach lengths are identical across variants; the only difference is
        whether the downstream (bay) segment gains an extra, left-exclusive lane.
        """
        eid = f'{frm}_{to}'
        if to not in split_junctions:
            edges.append(dict(id=eid, frm=frm, to=to, lanes=nlanes,
                              speed=speed, prio=prio))
            return eid, nlanes, False
        # split: upstream part keeps the original id (so demand files stay valid)
        snode = f'{eid}_s'
        sx, sy = tx - ux * bay_len, ty - uy * bay_len
        nodes.append((snode, sx, sy, 'priority'))
        bay_id = f'{eid}_bay'
        bay_lanes = nlanes + 1 if with_bays else nlanes
        edges.append(dict(id=eid, frm=frm, to=snode, lanes=nlanes,
                          speed=speed, prio=prio))
        edges.append(dict(id=bay_id, frm=snode, to=to, lanes=bay_lanes,
                          speed=speed, prio=prio))
        # upstream -> bay lane mapping: rightmost lanes go straight across,
        # the existing leftmost lane also feeds the new exclusive left lane.
        for l in range(nlanes):
            conns.append((eid, bay_id, l, l))
        if with_bays:
            conns.append((eid, bay_id, nlanes - 1, bay_lanes - 1))
        return bay_id, bay_lanes, with_bays

    # ---- arterial ----
    art_nodes = ['W'] + [f'J{i}' for i in range(1, N_INT + 1)] + ['E']
    art_x = [X0 - APPROACH_W] + [jx(i) for i in range(1, N_INT + 1)] + [jx(N_INT) + APPROACH_W]
    # approach edge id (possibly the bay edge) feeding each junction, per direction
    eb_feed, wb_feed = {}, {}
    for k in range(len(art_nodes) - 1):
        a, b = art_nodes[k], art_nodes[k + 1]
        ax, bx = art_x[k], art_x[k + 1]
        # eastbound a->b
        fid, nl, isbay = add_approach(a, b, ART_LANES, ART_SPEED, ART_PRIO,
                                      1.0, 0.0, ax, 0.0, bx, 0.0, True)
        eb_feed[b] = (fid, nl)
        # westbound b->a
        fid, nl, isbay = add_approach(b, a, ART_LANES, ART_SPEED, ART_PRIO,
                                      -1.0, 0.0, bx, 0.0, ax, 0.0, True)
        wb_feed[a] = (fid, nl)

    # ---- cross streets ----
    sb_feed, nb_feed = {}, {}   # feeding Ji from N (southbound) / from S (northbound)
    for i in range(1, N_INT + 1):
        J, N, S = f'J{i}', f'N{i}', f'S{i}'
        x = jx(i)
        # southbound N->J
        fid, nl, isbay = add_approach(N, J, CRS_LANES, CRS_SPEED, CRS_PRIO,
                                      0.0, -1.0, x, CROSS_LEN, x, 0.0, False)
        sb_feed[J] = (fid, nl)
        # J->N (outgoing, never split)
        edges.append(dict(id=f'{J}_{N}', frm=J, to=N, lanes=CRS_LANES,
                          speed=CRS_SPEED, prio=CRS_PRIO))
        # northbound S->J
        fid, nl, isbay = add_approach(S, J, CRS_LANES, CRS_SPEED, CRS_PRIO,
                                      0.0, 1.0, x, -CROSS_LEN, x, 0.0, False)
        nb_feed[J] = (fid, nl)
        edges.append(dict(id=f'{J}_{S}', frm=J, to=S, lanes=CRS_LANES,
                          speed=CRS_SPEED, prio=CRS_PRIO))

    # ---- explicit turn connections at the bay junctions ----
    # For each approach at a bay junction we must enumerate ALL outgoing
    # connections, because specifying any connection from an edge overrides
    # netconvert's computed set for that edge.
    for J in (split_junctions if with_bays else []):
        i = int(J[1:])
        N, S = f'N{i}', f'S{i}'
        west = art_nodes[art_nodes.index(J) - 1]
        east = art_nodes[art_nodes.index(J) + 1]
        thru_e, thru_w = f'{J}_{east}', f'{J}_{west}'
        to_n, to_s = f'{J}_{N}', f'{J}_{S}'

        def emit(feed, through, left, right):
            eid, nl = feed
            left_lane = nl - 1
            # rightmost lane: through + right
            conns.append((eid, through, 0, 0))
            conns.append((eid, right, 0, 0))
            # middle through lanes (arterial only)
            for l in range(1, left_lane):
                conns.append((eid, through, l, min(l, _lanes_of(edges, through) - 1)))
            # exclusive left bay lane
            conns.append((eid, left, left_lane, _lanes_of(edges, left) - 1))

        emit(eb_feed[J], thru_e, to_n, to_s)   # eastbound: left=north, right=south
        emit(wb_feed[J], thru_w, to_s, to_n)   # westbound: left=south, right=north
        emit(sb_feed[J], to_s, thru_e, thru_w)  # southbound: left=east, right=west
        emit(nb_feed[J], to_n, thru_w, thru_e)  # northbound: left=west, right=east

    # ---- write plain XML ----
    os.makedirs(out_dir, exist_ok=True)
    nod = os.path.join(out_dir, 'corridor.nod.xml')
    edg = os.path.join(out_dir, 'corridor.edg.xml')
    con = os.path.join(out_dir, 'corridor.con.xml')
    with open(nod, 'w') as f:
        f.write('<nodes>\n')
        for nid, x, y, t in nodes:
            f.write(f'    <node id="{nid}" x="{x:.2f}" y="{y:.2f}" type="{t}"/>\n')
        f.write('</nodes>\n')
    with open(edg, 'w') as f:
        f.write('<edges>\n')
        for e in edges:
            f.write('    <edge id="{id}" from="{frm}" to="{to}" numLanes="{lanes}" '
                    'speed="{speed}" priority="{prio}"/>\n'.format(**e))
        f.write('</edges>\n')
    with open(con, 'w') as f:
        f.write('<connections>\n')
        for a, b, fl, tl in conns:
            f.write(f'    <connection from="{a}" to="{b}" fromLane="{fl}" toLane="{tl}"/>\n')
        f.write('</connections>\n')
    return nod, edg, con


def _lanes_of(edges, eid):
    for e in edges:
        if e['id'] == eid:
            return e['lanes']
    raise KeyError(eid)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--variant', choices=['base', 'bay'], required=True)
    ap.add_argument('--bay-junctions', default='J2,J3')
    ap.add_argument('--bay-length', type=float, default=90.0)
    ap.add_argument('--out-dir', required=True)
    args = ap.parse_args()

    splits = set(args.bay_junctions.split(','))
    nod, edg, con = build_plain_xml(args.out_dir, splits,
                                    args.variant == 'bay', args.bay_length)
    net = os.path.join(args.out_dir, f'corridor_{args.variant}.net.xml')
    cmd = ['netconvert', '-n', nod, '-e', edg, '-x', con, '-o', net,
           '--no-turnarounds', 'true',
           '--tls.default-type', 'static',
           '--tls.yellow.time', '4',
           '--tls.allred.time', '2',
           '--default.junctions.keep-clear', 'true',
           '--junctions.corner-detail', '5',
           '--no-internal-links', 'false']
    print(' '.join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    sys.stderr.write(r.stderr)
    if r.returncode != 0:
        sys.exit(f'netconvert failed for variant {args.variant}')
    print(f'wrote {net}')


if __name__ == '__main__':
    main()
