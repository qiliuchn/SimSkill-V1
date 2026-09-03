#!/usr/bin/env python3
"""
Parameterized 3 km, 4-lane (2/direction) suburban arterial corridor with 3
signalized intersections at 800 m spacing, a functioning outer bypass route,
and a driveway-density sweep, built on ONE shared geometry across three
median treatments (only the driveway-node connection pattern differs):

  undivided    -- driveway left-turns from/into the inside through lane
                  (direct crossing connections, netconvert-computed foes)
  twltl        -- sub-goal-1's verified DEFENSIBLE encoding: a discretized
                  chain of short (locally-sized) bidirectional left-turn
                  pockets, one per driveway (candidate C). NOT a continuous
                  median a vehicle can cruise along for a non-adjacent
                  driveway -- see repgoal1 caveat.
  raised       -- driveway lefts physically banned (right-in/right-out
                  only); periodic directional median U-turn crossovers at a
                  stated spacing, reusing the RCUT/Michigan-left mechanics.

Usage: build_corridor.py <variant: undivided|twltl|raised> <density: access
       points/km/side, e.g. 5/15/30/45> <outdir> [--consolidate N]
"""
import argparse
import os
import subprocess
import sys

LANES = 2
SPEED = 13.89          # 50 km/h arterial
BYPASS_SPEED = 11.11   # 40 km/h local frontage/bypass road
CORRIDOR_LEN = 3000.0
SIGNAL_X = [700.0, 1500.0, 2300.0]
SIGNAL_BUFFER = 45.0     # keep driveways this far from a signal node
CROSSOVER_X = [350.0, 1100.0, 1900.0, 2650.0]   # raised-median U-turn openings (~750-800m apart)
DRIVEWAY_OFFSET = 25.0   # lateral distance of driveway stub node from mainline
STUB_LEN = 30.0          # driveway stub edge length
CYCLE = 70.0
GREEN_MAIN = 46.0        # arterial through/right green (incl. permissive left)
YELLOW = 3.0
ALLRED = 2.0
GREEN_MINOR = CYCLE - GREEN_MAIN - 2 * (YELLOW + ALLRED)
DESIGN_SPEED = SPEED     # progression design speed


def eline(eid, a, b, nl, speed=SPEED, prio=3, shape=None, spread=None):
    s = f'  <edge id="{eid}" from="{a}" to="{b}" numLanes="{nl}" speed="{speed}" priority="{prio}"'
    if shape:
        s += f' shape="{shape}"'
    if spread:
        s += f' spreadType="{spread}"'
    return s + "/>\n"


def nline(nid, x, y, ntype="priority"):
    return f'  <node id="{nid}" x="{x:.3f}" y="{y:.3f}" type="{ntype}"/>\n'


def cline(a, b, fl, tl):
    return f'  <connection from="{a}" to="{b}" fromLane="{fl}" toLane="{tl}"/>\n'


def make_driveway_positions(density_per_km_per_side):
    """Evenly space n driveway pairs, keep them clear of each signal's
    junction footprint, AND enforce a minimum inter-driveway gap so the
    signal-clearance nudge itself can never collapse two distinct driveways
    onto the same coordinate (a real failure mode hit during development:
    naive nudging of several consecutive driveways toward the same signal
    buffer boundary silently merged them via duplicate coordinates --
    netconvert's own junction-joining never even had to fire, the bug was
    upstream of it). This is the explicit handling of close driveway-node
    spacing this study's corridor build requires."""
    n = max(1, round(density_per_km_per_side * (CORRIDOR_LEN / 1000.0)))
    min_gap = 12.0
    xs = [(i + 0.5) * CORRIDOR_LEN / n for i in range(n)]
    for sx in SIGNAL_X:
        for i, x in enumerate(xs):
            if abs(x - sx) < SIGNAL_BUFFER:
                xs[i] = sx - SIGNAL_BUFFER if x < sx else sx + SIGNAL_BUFFER
    xs.sort()
    # enforce minimum gap left-to-right, then right-to-left, to resolve any
    # collisions/crowding introduced by the signal nudge above
    for i in range(1, len(xs)):
        if xs[i] - xs[i - 1] < min_gap:
            xs[i] = xs[i - 1] + min_gap
    for i in range(len(xs) - 2, -1, -1):
        if xs[i + 1] - xs[i] < min_gap:
            xs[i] = xs[i + 1] - min_gap
    xs = [max(20.0, min(CORRIDOR_LEN - 20.0, round(x, 2))) for x in xs]
    return xs


class Builder:
    def __init__(self, variant, density, outdir, consolidate_factor=1):
        self.variant = variant
        self.density = density
        self.outdir = outdir
        self.consolidate = consolidate_factor  # >1: merge this many adjacent driveways into 1
        self.nodes = []
        self.edges = []
        self.cons = []
        self.driveway_info = []   # (x, node_ids...) for demand generation
        self.crossover_info = []  # x positions of raised-median crossovers actually built
        os.makedirs(outdir, exist_ok=True)

    # ---- boundary + mainline spine, split at every "feature" x -----------
    def build(self):
        raw_xs = make_driveway_positions(self.density)
        if self.consolidate > 1:
            # merge groups of `consolidate` adjacent driveways into one
            # node carrying their combined volume (sub-goal 6 remedy arm)
            merged = []
            for i in range(0, len(raw_xs), self.consolidate):
                grp = raw_xs[i:i + self.consolidate]
                merged.append((sum(grp) / len(grp), len(grp)))
            self.dwy_xs = merged   # (x, n_merged)
        else:
            self.dwy_xs = [(x, 1) for x in raw_xs]

        # feature x-list: boundaries, signals, driveways(, crossovers if raised) -> spine nodes
        dwy_x_set = {x for x, _ in self.dwy_xs}

        def clear(cx):
            return (all(abs(cx - x) >= 15.0 for x in dwy_x_set) and
                    all(abs(cx - sx) >= 15.0 for sx in SIGNAL_X))

        crossover_xs = []
        if self.variant == "raised":
            for cx0 in CROSSOVER_X:
                cx = cx0
                # every raised-median crossover must physically exist at its
                # stated spacing -- nudge (never silently drop) around any
                # nearby driveway/signal node until clear
                step = 1.0
                tries = 0
                while not clear(cx) and tries < 40:
                    cx = cx0 + (step if tries % 2 == 0 else -step)
                    step += 1.0
                    tries += 1
                crossover_xs.append(round(cx, 2))
        self.crossover_xs = crossover_xs
        feature_xs = sorted(set([0.0, CORRIDOR_LEN] + SIGNAL_X + list(dwy_x_set) + crossover_xs))
        self.spine = feature_xs

        # boundary nodes
        self.nodes.append(nline("W", 0.0, 0.0))
        self.nodes.append(nline("E", CORRIDOR_LEN, 0.0))

        # build mainline node objects for each interior feature x
        self.node_at = {}
        for x in feature_xs:
            if x in (0.0, CORRIDOR_LEN):
                continue
            if x in SIGNAL_X:
                nid = f"SIG{SIGNAL_X.index(x)+1}"
                self.nodes.append(nline(nid, x, 0.0, "traffic_light"))
                self.node_at[x] = ("signal", nid)
            elif x in self.crossover_xs:
                nid = f"X{self.crossover_xs.index(x)}"
                self.nodes.append(nline(nid, x, 0.0))
                self.node_at[x] = ("crossover", nid)
            else:
                # driveway -- undivided/raised: single node; twltl: Xu/Xd pocket triple
                idx = [i for i, (dx, _) in enumerate(self.dwy_xs) if dx == x][0]
                nid = f"D{idx}"
                if self.variant == "twltl":
                    spacing = self._local_spacing(x, feature_xs)
                    half = min(9.5, max(2.0, spacing / 2.0 - 2.0))
                    self.nodes.append(nline(f"{nid}u", x - half, 0.0))
                    self.nodes.append(nline(nid, x, 0.0))
                    self.nodes.append(nline(f"{nid}d", x + half, 0.0))
                    self.node_at[x] = ("twltl_dwy", nid, half)
                else:
                    self.nodes.append(nline(nid, x, 0.0))
                    self.node_at[x] = ("dwy", nid)

        # mainline edges linking consecutive spine nodes (EB and WB)
        self._build_mainline_and_driveways(feature_xs)
        self._build_bypass()
        self._build_signals()
        return self._compile()

    def _local_spacing(self, x, feature_xs):
        i = feature_xs.index(x)
        prev_gap = x - feature_xs[i - 1] if i > 0 else 200.0
        next_gap = feature_xs[i + 1] - x if i < len(feature_xs) - 1 else 200.0
        return min(prev_gap, next_gap)

    def _node_ends(self, x):
        """(west_facing_connector, east_facing_connector) ids at x -- for a
        plain node these are equal; for a twltl driveway node the mainline
        bypass attaches at the Xu (west) / Xd (east) flanking nodes instead
        of the driveway node itself."""
        if x == 0.0:
            return "W", "W"
        if x == CORRIDOR_LEN:
            return "E", "E"
        kind = self.node_at[x]
        if kind[0] == "twltl_dwy":
            return kind[1] + "u", kind[1] + "d"
        return kind[1], kind[1]

    def _build_mainline_and_driveways(self, feature_xs):
        for i in range(len(feature_xs) - 1):
            xa, xb = feature_xs[i], feature_xs[i + 1]
            _, east_of_a = self._node_ends(xa)
            west_of_b, _ = self._node_ends(xb)
            segn = f"{i}"
            self.edges.append(eline(f"EB_{segn}", east_of_a, west_of_b, LANES))
            self.edges.append(eline(f"WB_{segn}", west_of_b, east_of_a, LANES))

        # now wire each interior node's own connection pattern (driveway/signal)
        for x in feature_xs[1:-1]:
            self._wire_node(x, feature_xs)

    def _edge_ids_around(self, x, feature_xs):
        i = feature_xs.index(x)
        seg_before = i - 1
        seg_after = i
        return f"EB_{seg_before}", f"WB_{seg_before}", f"EB_{seg_after}", f"WB_{seg_after}"

    def _wire_node(self, x, feature_xs):
        kind = self.node_at[x]
        i = feature_xs.index(x)
        eb_in, wb_out, eb_out, wb_in = self._edge_ids_around(x, feature_xs)
        # eb_in: EB edge ENDING here (from the west) -> named EB_{seg_before}
        # eb_out: EB edge STARTING here (to the east) -> EB_{seg_after}
        # wb_in: WB edge ENDING here (from the east) -> WB_{seg_after} (WB flows east->west)
        # wb_out: WB edge STARTING here (to the west) -> WB_{seg_before}
        if kind[0] == "signal":
            nid = kind[1]
            for j in range(LANES):
                self.cons.append(cline(eb_in, eb_out, j, j))
                self.cons.append(cline(wb_in, wb_out, j, j))
            # minor street stub (very light/no demand; exists to justify signal control)
            self.nodes.append(nline(f"{nid}_N", x, 120.0))
            self.nodes.append(nline(f"{nid}_S", x, -120.0))
            self.edges.append(eline(f"MIN_IN_{nid}", f"{nid}_N", nid, 1, 11.11))
            self.edges.append(eline(f"MIN_OUT_{nid}", nid, f"{nid}_N", 1, 11.11))
            self.edges.append(eline(f"MIN_IN_{nid}_S", f"{nid}_S", nid, 1, 11.11))
            self.edges.append(eline(f"MIN_OUT_{nid}_S", nid, f"{nid}_S", 1, 11.11))
            self.cons.append(cline(f"MIN_IN_{nid}", eb_out, 0, 0))
            self.cons.append(cline(f"MIN_IN_{nid}", wb_out, 0, 1))
            self.cons.append(cline(f"MIN_IN_{nid}_S", wb_out, 0, 0))
            self.cons.append(cline(f"MIN_IN_{nid}_S", eb_out, 0, 1))
            self.signal_info = getattr(self, "signal_info", [])
            self.signal_info.append({"nid": nid, "x": x})
        elif kind[0] == "dwy":
            nid = kind[1]
            a, b = f"{nid}A", f"{nid}B"   # A = north (left-of-EB), B = south (left-of-WB)
            self.nodes.append(nline(a, x, DRIVEWAY_OFFSET))
            self.nodes.append(nline(b, x, -DRIVEWAY_OFFSET))
            self.edges.append(eline(f"IN_{a}", nid, a, 1, 8.33))
            self.edges.append(eline(f"OUT_{a}", a, nid, 1, 8.33))
            self.edges.append(eline(f"IN_{b}", nid, b, 1, 8.33))
            self.edges.append(eline(f"OUT_{b}", b, nid, 1, 8.33))
            for j in range(LANES):
                self.cons.append(cline(eb_in, eb_out, j, j))
                self.cons.append(cline(wb_in, wb_out, j, j))
            # right-in/out always legal
            self.cons.append(cline(wb_in, f"IN_{a}", 0, 0))
            self.cons.append(cline(f"OUT_{a}", wb_out, 0, 0))
            self.cons.append(cline(eb_in, f"IN_{b}", 0, 0))
            self.cons.append(cline(f"OUT_{b}", eb_out, 0, 0))
            if self.variant == "undivided":
                # left-in/out directly from/to the inside through lane (crosses opposing lanes)
                self.cons.append(cline(eb_in, f"IN_{a}", 1, 0))
                self.cons.append(cline(f"OUT_{a}", eb_out, 0, 1))
                self.cons.append(cline(wb_in, f"IN_{b}", 1, 0))
                self.cons.append(cline(f"OUT_{b}", wb_out, 0, 1))
            # raised: no left connections at all -- banned by omission
            n_merged = [nm for dx, nm in self.dwy_xs if dx == x][0]
            self.driveway_info.append({"nid": nid, "x": x, "kind": "dwy", "n_merged": n_merged,
                                        "eb_in": eb_in, "eb_out": eb_out, "wb_in": wb_in, "wb_out": wb_out})
        elif kind[0] == "twltl_dwy":
            nid, half = kind[1], kind[2]
            u, d = f"{nid}u", f"{nid}d"
            a, b = f"{nid}A", f"{nid}B"
            self.nodes.append(nline(a, x, DRIVEWAY_OFFSET))
            self.nodes.append(nline(b, x, -DRIVEWAY_OFFSET))
            self.edges.append(eline(f"IN_{a}", nid, a, 1, 8.33))
            self.edges.append(eline(f"OUT_{a}", a, nid, 1, 8.33))
            self.edges.append(eline(f"IN_{b}", nid, b, 1, 8.33))
            self.edges.append(eline(f"OUT_{b}", b, nid, 1, 8.33))
            # bypass (outer+inner through, 2 lanes) skirting the pocket
            self.edges.append(eline(f"EBY_{nid}", u, d, LANES))
            self.edges.append(eline(f"WBY_{nid}", d, u, LANES))
            for j in range(LANES):
                self.cons.append(cline(eb_in, f"EBY_{nid}", j, j))
                self.cons.append(cline(f"EBY_{nid}", eb_out, j, j))
                self.cons.append(cline(wb_in, f"WBY_{nid}", j, j))
                self.cons.append(cline(f"WBY_{nid}", wb_out, j, j))
            xu, xn, xd = x - half, x, x + half
            self.edges.append(eline(f"MEB_{nid}u", u, nid, 1, SPEED, 3, f"{xu:.2f},0.00 {xn:.2f},0.00", "center"))
            self.edges.append(eline(f"MEB_{nid}d", nid, d, 1, SPEED, 3, f"{xn:.2f},0.00 {xd:.2f},0.00", "center"))
            self.edges.append(eline(f"MWB_{nid}d", d, nid, 1, SPEED, 3, f"{xd:.2f},0.00 {xn:.2f},0.00", "center"))
            self.edges.append(eline(f"MWB_{nid}u", nid, u, 1, SPEED, 3, f"{xn:.2f},0.00 {xu:.2f},0.00", "center"))
            self.cons.append(cline(eb_in, f"MEB_{nid}u", 1, 0))
            self.cons.append(cline(f"MEB_{nid}d", eb_out, 0, 1))
            self.cons.append(cline(f"MEB_{nid}u", f"MEB_{nid}d", 0, 0))
            self.cons.append(cline(wb_in, f"MWB_{nid}d", 1, 0))
            self.cons.append(cline(f"MWB_{nid}u", wb_out, 0, 1))
            self.cons.append(cline(f"MWB_{nid}d", f"MWB_{nid}u", 0, 0))
            # pocket entry/exit -- A is the "left-from-EB / right-from-WB"
            # stub, B is "right-from-EB / left-from-WB" (matches the direct
            # right-in/out wiring above). The two LEFT movements per stub
            # each need the pocket edge that actually ARRIVES AT / LEAVES
            # FROM nid in the matching direction (verified bug found during
            # integration: an earlier version fed both stubs from the same
            # WB-arriving edge and left the EB-arriving edge unconnected,
            # silently forcing EB left-in trips onto a huge bypass detour --
            # caught by inspecting duarouter's realized routes, not assumed).
            self.cons.append(cline(f"MEB_{nid}u", f"IN_{a}", 0, 0))   # EB-arriving -> A (EB left-in)
            self.cons.append(cline(f"MWB_{nid}d", f"IN_{b}", 0, 0))   # WB-arriving -> B (WB left-in)
            self.cons.append(cline(f"OUT_{a}", f"MEB_{nid}d", 0, 0))  # A -> EB-leaving (A left-out to EB)
            self.cons.append(cline(f"OUT_{b}", f"MWB_{nid}u", 0, 0))  # B -> WB-leaving (B left-out to WB)
            # RIGHT-in/right-out (no crossing of opposing traffic needed --
            # BUG FIX, verified during sub-goal-4 analysis: the block above
            # only ever wires the four LEFT movements. With no right-turn
            # connection at all, duarouter had no legal path from the
            # near-side outside lane into the stub and was silently routing
            # every dwy_in_right/out_right trip the entire way around the
            # outer bypass loop (confirmed by inspecting realized routes in
            # rou_twltl.xml: e.g. dwy_in_right_D9_2348's route began with
            # "BY_EB WB_18 ..." -- a >2km detour with no error or warning).
            # Real TWLTL right-in/out never touches the median lane at all;
            # this discretized single-lane pocket has no separate outside-
            # lane path into the stub, so the least-wrong fix reuses the
            # SAME short pocket-approach/exit lane the left-turn movement
            # uses, fed additionally from the outside lane (a 2-to-1 merge)
            # and released onto the outside lane on exit (a 1-to-2 diverge)
            # instead of the inside lane the through-pocket movement uses.
            # This is a genuine, disclosed representational compromise of
            # the discretized-pocket encoding: right-turn driveway traffic
            # briefly shares the pocket-approach lane with left-turners
            # rather than staying fully independent of the median, which
            # inflates "median-related" SSM conflict counts for twltl with
            # some right-turn merge conflicts -- reported as such, not
            # hidden, in the final analysis.
            self.cons.append(cline(eb_in, f"MEB_{nid}u", 0, 0))        # EB outside lane also feeds pocket-approach
            self.cons.append(cline(f"MEB_{nid}u", f"IN_{b}", 0, 0))    # EB-arriving -> B (EB right-in)
            self.cons.append(cline(wb_in, f"MWB_{nid}d", 0, 0))        # WB outside lane also feeds pocket-approach
            self.cons.append(cline(f"MWB_{nid}d", f"IN_{a}", 0, 0))    # WB-arriving -> A (WB right-in)
            self.cons.append(cline(f"OUT_{a}", f"MWB_{nid}u", 0, 0))   # A -> WB-leaving (A right-out to WB)
            self.cons.append(cline(f"MWB_{nid}u", wb_out, 0, 0))       # pocket-exit -> WB outside lane
            self.cons.append(cline(f"OUT_{b}", f"MEB_{nid}d", 0, 0))   # B -> EB-leaving (B right-out to EB)
            self.cons.append(cline(f"MEB_{nid}d", eb_out, 0, 0))       # pocket-exit -> EB outside lane
            n_merged = [nm for dx, nm in self.dwy_xs if dx == x][0]
            self.driveway_info.append({"nid": nid, "x": x, "kind": "twltl_dwy", "n_merged": n_merged,
                                        "eb_in": eb_in, "eb_out": eb_out, "wb_in": wb_in, "wb_out": wb_out})
        elif kind[0] == "crossover":
            # directional median U-turn opening (RCUT/Michigan-left mechanics
            # from design-restricted-crossing-uturn-and-michigan-left-intersections,
            # reused here as a corridor-wide raised-median policy rather than
            # a single junction's design): through movements pass straight,
            # plus an explicit U-turn connection each way.
            nid = kind[1]
            for j in range(LANES):
                self.cons.append(cline(eb_in, eb_out, j, j))
                self.cons.append(cline(wb_in, wb_out, j, j))
            self.cons.append(cline(eb_in, wb_out, 1, 1))   # EB->WB U-turn
            self.cons.append(cline(wb_in, eb_out, 1, 1))   # WB->EB U-turn
            self.crossover_info.append({"nid": nid, "x": x})

    def _build_bypass(self):
        y = 600.0
        self.nodes.append(nline("BYW", 0.0, y))
        self.nodes.append(nline("BYE", CORRIDOR_LEN, y))
        self.edges.append(eline("BY_EB", "W", "E", 1, BYPASS_SPEED, 1,
                                 f"0.00,0.00 0.00,{y:.1f} {CORRIDOR_LEN:.1f},{y:.1f} {CORRIDOR_LEN:.1f},0.00"))
        self.edges.append(eline("BY_WB", "E", "W", 1, BYPASS_SPEED, 1,
                                 f"{CORRIDOR_LEN:.1f},0.00 {CORRIDOR_LEN:.1f},{y:.1f} 0.00,{y:.1f} 0.00,0.00"))
        # W/E boundary connections (mainline first/last segment <-> bypass)
        # are left to netconvert's own default connection generation
        # (--no-turnarounds true suppresses the degenerate same-node loop).

    def _build_signals(self):
        for idx, sx in enumerate(SIGNAL_X):
            nid = f"SIG{idx+1}"
            offset = (sx / DESIGN_SPEED) % CYCLE
            self.signal_programs = getattr(self, "signal_programs", [])
            self.signal_programs.append((nid, offset))

    def _compile(self):
        with open(f"{self.outdir}/n.nod.xml", "w") as f:
            f.write("<nodes>\n" + "".join(self.nodes) + "</nodes>\n")
        with open(f"{self.outdir}/n.edg.xml", "w") as f:
            f.write("<edges>\n" + "".join(self.edges) + "</edges>\n")
        with open(f"{self.outdir}/n.con.xml", "w") as f:
            f.write("<connections>\n" + "".join(self.cons) + "</connections>\n")
        args = ["netconvert",
                "--node-files", f"{self.outdir}/n.nod.xml",
                "--edge-files", f"{self.outdir}/n.edg.xml",
                "--connection-files", f"{self.outdir}/n.con.xml",
                "--no-turnarounds", "true",
                "--junctions.corner-detail", "0",
                "--geometry.avoid-overlap", "false",
                "--tls.guess", "false",
                "-o", f"{self.outdir}/net.net.xml"]
        r = subprocess.run(args, capture_output=True, text=True)
        with open(f"{self.outdir}/netconvert.log", "w") as f:
            f.write(" ".join(args) + "\n\n" + r.stdout + "\n" + r.stderr)
        return r.returncode, r.stdout + r.stderr


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("variant", choices=["undivided", "twltl", "raised"])
    ap.add_argument("density", type=float)
    ap.add_argument("outdir")
    ap.add_argument("--consolidate", type=int, default=1)
    a = ap.parse_args()
    b = Builder(a.variant, a.density, a.outdir, a.consolidate)
    rc, log = b.build()
    print(f"variant={a.variant} density={a.density} consolidate={a.consolidate} -> rc={rc}")
    print(f"  #driveway features={len(b.dwy_xs)}  #nodes={len(b.nodes)}  #edges={len(b.edges)}  #cons={len(b.cons)}")
    for line in log.splitlines():
        if "rror" in line:
            print("   ", line)
    import json
    meta = {
        "variant": a.variant, "density": a.density, "consolidate": a.consolidate,
        "driveways": b.driveway_info,
        "signals": getattr(b, "signal_info", []),
        "crossovers": b.crossover_info,
        "corridor_len": CORRIDOR_LEN,
    }
    with open(os.path.join(a.outdir, "meta.json"), "w") as f:
        json.dump(meta, f, indent=1)
