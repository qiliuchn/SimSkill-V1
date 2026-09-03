#!/usr/bin/env python3
"""Run a closed-ring scenario under TraCI, writing FCD output.

All scenarios receive the SAME transient seed perturbation: at t=PERTURB_START one
designated vehicle brakes for PERTURB_DUR seconds, then is released back to pure IDM.
This is a one-shot disturbance (a driver tapping the brakes once), NOT a persistent
bottleneck -- at string-unstable density it grows into a sustained jam; at stable
density it decays. Identical seed across baseline / low-density / AV runs.

In mode 'av', exactly ONE vehicle (id 'av') runs a wave-damping controller:
it holds a smoothed target speed near the ring's running mean, refusing to chase
the stop-and-go oscillation. Default speedMode is kept so SUMO still guarantees the
commanded speed is collision-safe.

Usage:
  run_ring.py --net NET --rou ROU --fcd FCD --end T [--steplen 0.2]
              [--mode baseline|av] [--perturb-id ID] [--perturb-start S]
              [--perturb-dur D] [--perturb-speed V] [--warmup W]
"""
import os, sys, argparse
sys.path.insert(0, os.path.join(os.environ['SUMO_HOME'], 'tools'))
import traci

p = argparse.ArgumentParser()
p.add_argument('--net', required=True)
p.add_argument('--rou', required=True)
p.add_argument('--fcd', required=True)
p.add_argument('--end', type=float, required=True)
p.add_argument('--steplen', type=float, default=0.2)
p.add_argument('--mode', default='baseline', choices=['baseline', 'av'])
p.add_argument('--perturb-id', default='v11')
p.add_argument('--perturb-start', type=float, default=30.0)
p.add_argument('--perturb-dur', type=float, default=3.0)
p.add_argument('--perturb-speed', type=float, default=0.0)
p.add_argument('--warmup', type=float, default=0.0)   # AV control only engages after this
p.add_argument('--av-target', type=float, default=2.467)  # desired velocity U (ring equilibrium)
p.add_argument('--av-ctrl', default='hold', choices=['hold', 'followerstopper'])
args = p.parse_args()

sumo = ['sumo', '-n', args.net, '-r', args.rou,
        '--step-length', str(args.steplen),
        '--fcd-output', args.fcd,
        '--fcd-output.geo', 'false',
        '--begin', '0', '--end', str(args.end),
        '--no-step-log', 'true',
        '--collision.action', 'warn',        # never silently teleport away a jam
        '--time-to-teleport', '-1',           # DISABLE teleporting: a stopped car must stay
        '--step-method.ballistic', 'true']
traci.start(sumo)

# --- AV wave-damping controller: FollowerStopper (Stern et al. 2018) --------
# The AV holds a desired velocity U (the ring's homogeneous equilibrium speed) and
# smoothly REDUCES its command as the gap to its leader shrinks, using three
# speed-dependent gap thresholds. It never overshoots U and never brakes abruptly,
# so it refuses to participate in the accelerate-into-a-gap / slam-the-brakes cycle
# that propagates a stop-and-go wave -- it absorbs the wave and re-establishes a
# steady flow at U, which is HIGHER than the depressed jam-average speed.
AV = 'av'
U = args.av_target
DX0 = (2.5, 3.5, 4.5)          # base gap thresholds dx1_0<dx2_0<dx3_0 (m)
DEC = (1.5, 1.0, 0.5)          # deceleration rates a1>a2>a3 (m/s^2)

def followerstopper_cmd(v_av, v_lead, gap):
    dv = min(v_lead - v_av, 0.0)                       # only closing speed matters
    dx1 = DX0[0] + dv*dv/(2*DEC[0])
    dx2 = DX0[1] + dv*dv/(2*DEC[1])
    dx3 = DX0[2] + dv*dv/(2*DEC[2])
    vbar = min(max(v_lead, 0.0), U)
    if   gap <= dx1: return 0.0
    elif gap <= dx2: return vbar * (gap - dx1) / (dx2 - dx1)
    elif gap <= dx3: return vbar + (U - vbar) * (gap - dx2) / (dx3 - dx2)
    else:            return U

dt = args.steplen

pstart = args.perturb_start
pend   = args.perturb_start + args.perturb_dur
perturbed_active = False

step = 0
t = 0.0
while t < args.end - 1e-9:
    traci.simulationStep()
    t = traci.simulation.getTime()
    ids = set(traci.vehicle.getIDList())

    # ---- identical seed perturbation (one-shot brake pulse) ----
    if args.perturb_id in ids:
        if (not perturbed_active) and pstart <= t < pend:
            traci.vehicle.setSpeed(args.perturb_id, args.perturb_speed)
            perturbed_active = True
        elif perturbed_active and t >= pend:
            traci.vehicle.setSpeed(args.perturb_id, -1)   # release -> pure IDM
            perturbed_active = False

    # ---- single-AV wave-damping controller ----
    if args.mode == 'av' and AV in ids and t >= args.warmup:
        v_av = traci.vehicle.getSpeed(AV)
        if args.av_ctrl == 'followerstopper':
            lead = traci.vehicle.getLeader(AV, 200.0)   # (leaderID, gap) or None
            if lead is not None:
                lid, gap = lead
                v_lead = traci.vehicle.getSpeed(lid)
                cmd = followerstopper_cmd(v_av, v_lead, gap)
                traci.vehicle.setSpeed(AV, cmd)
        else:  # 'hold' : commit to a steady target = ring equilibrium speed U.
               # The AV refuses to accelerate past U into an opening gap and refuses
               # to brake below the safe speed SUMO's speedMode enforces -> it neither
               # amplifies nor transmits the oscillation, pacing the fleet toward the
               # uniform equilibrium (higher mean than the stop-and-go jam).
            traci.vehicle.setSpeed(AV, U)

    step += 1

traci.close()
print(f'done: {args.mode} steps={step} t={t:.1f} fcd={args.fcd}')
