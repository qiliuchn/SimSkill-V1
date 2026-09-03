#!/usr/bin/env python3
"""
MFD-based PERIMETER GATING on a signalized grid, driven live over TraCI.

Two modes
---------
  --mode baseline : SUMO's own static tlLogic runs everywhere, untouched.
                    The script only *measures* (accumulation / production /
                    gate queues).
  --mode gated    : identical measurement, plus a perimeter controller that
                    throttles ONLY the into-core movements at the gate signals.

Control law (purely restrictive integral-free P controller)
-----------------------------------------------------------
    g_gate(k) = clip( g0 - K * (n(k) - n_set),  g_min,  g0 )

`g0` is the number of seconds per cycle during which the gate links are green
in the network's OWN program, measured from the compiled program -- so
`n_set` large enough that the law never binds reproduces the baseline signal
sequence *exactly* (see the non-binding negative control).  g_max is pinned to
g0 so gating can never give the core MORE inflow than the baseline; the
mechanism is one-sided by construction.

How the throttle is applied (surgical, phase-safe)
--------------------------------------------------
Gate links are derived from `traci.trafficlight.getControlledLinks()` -- every
controlled link whose OUTGOING edge is a gate edge (outside -> core), which in
general spans several phases (through movements in one phase, the turning
movements that also feed the core in the other).  Nothing else at the junction
is touched.

The gate TLS's own 4-phase program is replayed second-by-second by this script
(same phase order, same durations, offset 0).  Within each cycle we accumulate
the seconds during which gate links are green; once that reaches g_gate the
gate links (and only those) are driven to 'y' for the network's own clearance
duration and then to 'r' for the remainder of the cycle.  All other links keep
their programmed colour.  Consequences:
  * cycle length is unchanged (90 s) -- no coordination side effects,
  * vehicles leaving the core are never held,
  * green->green jumps are impossible; every gate shutdown passes through a
    real yellow,
  * with g_gate == g0 the emitted state sequence is identical to the static
    program, so the controller is a no-op.

Instrumentation (every simulation step, aggregated per control interval)
------------------------------------------------------------------------
  n(t)         : sum of traci.edge.getLastStepVehicleNumber over core edges
  production   : sum over core edges of n_e * v_e * step  [veh*m], reported per
                 interval as veh*km/h
  core outflow : vehicles that were on a core edge and are no longer
  gate queue   : halting vehicles on the incoming lanes of the gate links
  plus arrivals, teleports, running/pending counts
"""
import argparse
import csv
import json
import os
import sys

if "SUMO_HOME" in os.environ:
    sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import traci  # noqa: E402


GREEN = "gG"


class GateController:
    """Replays a gate junction's own program and throttles its into-core links."""

    def __init__(self, tls_id, gate_edges):
        self.tls_id = tls_id
        links = traci.trafficlight.getControlledLinks(tls_id)
        self.gate_idx = []
        for i, lk in enumerate(links):
            if not lk:
                continue
            out_lane = lk[0][1]
            if out_lane and out_lane.rsplit("_", 1)[0] in gate_edges:
                self.gate_idx.append(i)
        if not self.gate_idx:
            raise RuntimeError(f"{tls_id}: no controlled link feeds a gate edge")

        logic = traci.trafficlight.getAllProgramLogics(tls_id)[0]
        self.phases = [(float(p.duration), p.state) for p in logic.phases]
        self.cycle = sum(d for d, _ in self.phases)
        self.in_lanes = sorted({lk[0][0] for i, lk in enumerate(links)
                                if lk and i in self.gate_idx})

        # baseline gate-green seconds per cycle
        self.g0 = 0.0
        for d, s in self.phases:
            if any(s[i] in GREEN for i in self.gate_idx):
                self.g0 += d
        # clearance duration used when shutting the gate: the shortest
        # non-green phase in the junction's own program (its real yellow time)
        ylens = [d for d, s in self.phases
                 if all(s[i] not in GREEN for i in self.gate_idx)]
        self.yellow = min(ylens) if ylens else 3.0

        self.g_gate = self.g0          # start unrestricted (ratio r = 1)

    # -- programmed (unmodified) phase at a given offset into the cycle -------
    def _phase_at(self, tau):
        acc = 0.0
        for k, (d, s) in enumerate(self.phases):
            if tau < acc + d:
                return k, tau - acc, d, s
            acc += d
        k = len(self.phases) - 1
        d, s = self.phases[k]
        return k, d, d, s

    def set_target(self, g_gate):
        self.g_gate = g_gate

    def ratio(self):
        return self.g_gate / self.g0

    def binding(self):
        return self.g_gate < self.g0 - 1e-6

    def step(self, t, step_len):
        """Emit this step's signal state. Returns True if the gate was throttled.

        The junction's own programme is replayed verbatim.  In every phase in
        which the gate links are green, they are allowed r*d seconds of that
        phase's d seconds (r = g_gate/g0, the same ratio in every phase, so the
        throttle is order-independent), then driven to yellow for the
        programme's own clearance time and red for the phase remainder.  With
        r == 1 the branch is unreachable and the emitted sequence is byte-for-
        byte the static programme.
        """
        tau = t % self.cycle
        _, tip, d, state = self._phase_at(tau)
        r = self.ratio()

        throttled = False
        if any(state[i] in GREEN for i in self.gate_idx):
            allow = r * d
            if allow < d - 1e-9 and tip >= allow - 1e-9:
                elapsed = tip - allow
                colour = "y" if elapsed < self.yellow else "r"
                s = list(state)
                for i in self.gate_idx:
                    if state[i] in GREEN:   # only links that would have been green
                        s[i] = colour
                state = "".join(s)
                throttled = True

        traci.trafficlight.setRedYellowGreenState(self.tls_id, state)
        return throttled


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", required=True)
    ap.add_argument("--routes", required=True)
    ap.add_argument("--additional", required=True)
    ap.add_argument("--core-gate", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--mode", choices=["baseline", "gated"], default="baseline")
    ap.add_argument("--n-set", type=float, default=1e9)
    ap.add_argument("--gain", type=float, default=0.8, help="K, seconds of gate green removed per excess vehicle")
    ap.add_argument("--g-min", type=float, default=8.0)
    ap.add_argument("--interval", type=float, default=60.0)
    ap.add_argument("--step-length", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-time", type=float, default=12000.0)
    ap.add_argument("--sumo-bin", default=None)
    ap.add_argument("--light", action="store_true",
                    help="skip the bulky vehroute/summary outputs (seed replications)")
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    cg = json.load(open(args.core_gate))
    core_edges = cg["core_edges"]
    gate_edges = set(cg["gate_edges"])

    sumo_bin = args.sumo_bin or os.path.join(os.environ.get("SUMO_HOME", ""), "bin", "sumo")
    cmd = [
        sumo_bin,
        "-n", args.net,
        "-r", args.routes,
        "-a", args.additional,
        "--tripinfo-output", os.path.join(args.outdir, "tripinfo.xml"),
        "--statistic-output", os.path.join(args.outdir, "statistics.xml"),
        "--step-length", str(args.step_length),
        "--seed", str(args.seed),
        "--time-to-teleport", "300",
        "--no-step-log", "true",
        "--duration-log.statistics", "true",
        "--xml-validation", "never",
        # NOTE: no <rerouter>, no --device.rerouting.* -> routes are fixed.
    ]
    if not args.light:
        cmd += [
            "--summary-output", os.path.join(args.outdir, "summary.xml"),
            "--vehroute-output", os.path.join(args.outdir, "vehroutes.xml"),
            "--vehroute-output.exit-times", "true",
        ]
    traci.start(cmd, label=args.label)

    ctrls = {}
    if args.mode == "gated":
        for tls in cg["gate_junctions"]:
            ctrls[tls] = GateController(tls, gate_edges)

    # measurement subscriptions
    VEHNUM, MEANSPEED, VEHIDS = 0x10, 0x11, 0x12
    for e in core_edges:
        traci.edge.subscribe(e, [VEHNUM, MEANSPEED, VEHIDS])

    gate_in_lanes = sorted({l for c in ctrls.values() for l in c.in_lanes})
    if not gate_in_lanes:  # baseline still needs the same measurement points
        tmp = {}
        for tls in cg["gate_junctions"]:
            links = traci.trafficlight.getControlledLinks(tls)
            for lk in links:
                if lk and lk[0][1] and lk[0][1].rsplit("_", 1)[0] in gate_edges:
                    tmp[lk[0][0]] = True
        gate_in_lanes = sorted(tmp)

    rows = []
    step_len = args.step_length
    t = 0.0
    nxt = args.interval
    acc_sum = 0.0          # sum of n over steps in interval
    acc_max = 0.0
    prod_vehm = 0.0
    nsteps = 0
    prev_core_ids = set()
    core_out = 0
    arrived_cum = 0
    arrived_prev = 0
    teleport_cum = 0
    throttle_steps = 0
    g_current = None

    while traci.simulation.getMinExpectedNumber() > 0 and t < args.max_time:
        # ---- apply control BEFORE stepping ----
        for c in ctrls.values():
            if c.step(t, step_len):
                throttle_steps += 1

        traci.simulationStep()
        t = traci.simulation.getTime()
        nsteps += 1

        n = 0
        vm = 0.0
        ids = set()
        for e in core_edges:
            r = traci.edge.getSubscriptionResults(e)
            ne = r[VEHNUM]
            n += ne
            vm += ne * r[MEANSPEED] * step_len
            ids.update(r[VEHIDS])
        acc_sum += n
        acc_max = max(acc_max, n)
        prod_vehm += vm
        core_out += len(prev_core_ids - ids)
        prev_core_ids = ids

        arrived_cum += traci.simulation.getArrivedNumber()
        teleport_cum += traci.simulation.getStartingTeleportNumber()

        if t >= nxt - 1e-9:
            n_mean = acc_sum / max(nsteps, 1)
            prod = prod_vehm * 3.6 / args.interval        # veh*km/h
            qlen = sum(traci.lane.getLastStepHaltingNumber(l) for l in gate_in_lanes)
            qwait = sum(traci.lane.getWaitingTime(l) for l in gate_in_lanes)
            pending = traci.simulation.getPendingVehicles()
            rows.append({
                "t_end": round(t, 1),
                "n_mean": round(n_mean, 3),
                "n_end": n,
                "n_max": acc_max,
                "production_vehkm_h": round(prod, 3),
                "core_outflow_veh": core_out,
                "arrived_cum": arrived_cum,
                "arrived_interval": arrived_cum - arrived_prev,
                "teleports_cum": teleport_cum,
                "running": traci.vehicle.getIDCount(),
                "pending_insertion": len(pending),
                "gate_queue_halting": qlen,
                "gate_queue_waiting_s": round(qwait, 1),
                "g_gate_s": round(g_current, 2) if g_current is not None else "",
                "throttle_steps_cum": throttle_steps,
            })
            arrived_prev = arrived_cum
            # ---- feedback update ----
            if ctrls:
                any_c = next(iter(ctrls.values()))
                g = any_c.g0 - args.gain * (n_mean - args.n_set)
                g = max(args.g_min, min(any_c.g0, g))
                g_current = g
                for c in ctrls.values():
                    c.set_target(g)
            acc_sum = 0.0
            prod_vehm = 0.0
            nsteps = 0
            core_out = 0
            nxt += args.interval

    sim_end = t
    traci.close()

    csv_path = os.path.join(args.outdir, "accumulation_production.csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    meta = {
        "label": args.label, "mode": args.mode, "n_set": args.n_set,
        "gain": args.gain, "g_min": args.g_min, "interval": args.interval,
        "seed": args.seed, "sim_end": sim_end,
        "throttle_steps": throttle_steps,
        "binding_intervals": (
            sum(1 for r in rows if r["g_gate_s"] != ""
                and r["g_gate_s"] < next(iter(ctrls.values())).g0 - 1e-6)
            if ctrls else 0),
        "gate_g0_s": (next(iter(ctrls.values())).g0 if ctrls else None),
        "gate_cycle_s": (next(iter(ctrls.values())).cycle if ctrls else None),
        "gate_yellow_s": (next(iter(ctrls.values())).yellow if ctrls else None),
        "n_gate_links": {k: len(c.gate_idx) for k, c in ctrls.items()},
        "core_total_lane_km": cg["core_total_lane_km"],
    }
    json.dump(meta, open(os.path.join(args.outdir, "run_meta.json"), "w"), indent=2)
    print(f"[{args.label}] end={sim_end:.0f}s arrived={arrived_cum} "
          f"teleports={teleport_cum} n_max={max(r['n_max'] for r in rows)} "
          f"throttle_steps={throttle_steps}")


if __name__ == "__main__":
    main()
