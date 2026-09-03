"""Run one simulated 'day' (one seed) of the freeway, optionally with an injected incident.

Incident = one or two stopped vehicles blocking the rightmost lane(s) at a randomly drawn
mid-segment location, injected live via TraCI (traci.vehicle.setStop). The matched
incident-free control day uses the SAME seed and the SAME harness (CRN), so the two arms
share identical traffic up to the injection instant.

Outputs per run:
  <rundir>/det.npz   station-aggregated detector series (volume / occupancy / speed)
  <rundir>/meta.json run metadata + incident ground truth + verification diagnostics
"""
import os, sys, json, random, shutil, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import *
sys.path.insert(0, SUMO_TOOLS)
import traci
import numpy as np
import xml.etree.ElementTree as ET
from build_detectors import build

NET = os.path.join(NET_DIR, "freeway.net.xml")
N_INTERVALS = int(SIM_END / DET_PERIOD)


# ----------------------------------------------------------------- detector aggregation
def aggregate_e1(path):
    """E1 XML -> per-station arrays. occupancy = mean over lanes (%);
    speed = flow-weighted HARMONIC mean over lanes (space-mean speed; using the raw
    `speed` field instead would bias travel-time-type estimates -- see
    traffic-state-estimation-sensor-bias-and-sensing-tradeoffs)."""
    vol = np.zeros((N_SEG, N_INTERVALS))
    occ = np.zeros((N_SEG, N_INTERVALS))
    nlan = np.zeros((N_SEG, N_INTERVALS))
    inv_sum = np.zeros((N_SEG, N_INTERVALS))   # sum over lanes of n/ v_harm
    nspd = np.zeros((N_SEG, N_INTERVALS))
    for _, iv in ET.iterparse(path, events=("end",)):
        if iv.tag != "interval":
            continue
        k = int(iv.get("id")[2:4])
        j = int(float(iv.get("begin")) // DET_PERIOD)
        if j >= N_INTERVALS:
            iv.clear(); continue
        n = float(iv.get("nVehContrib"))
        vol[k, j] += n
        occ[k, j] += float(iv.get("occupancy"))
        nlan[k, j] += 1
        hs = float(iv.get("harmonicMeanSpeed"))
        if n > 0 and hs > 0:
            inv_sum[k, j] += n / hs
            nspd[k, j] += n
        iv.clear()
    occ = np.where(nlan > 0, occ / np.maximum(nlan, 1), 0.0)
    spd = np.where(nspd > 0, nspd / np.maximum(inv_sum, 1e-9), np.nan)
    return vol, occ, spd


# ----------------------------------------------------------------- incident draw
def incident_rng(seed):
    """Hash the seed before seeding the Mersenne Twister: random.Random(k) for CONSECUTIVE
    integers k produces visibly correlated first draws (verified here -- the incident
    segment clustered heavily on a few values), which would bias spatial coverage."""
    import hashlib
    h = hashlib.sha256(f"aid-incident-{seed}".encode()).hexdigest()[:16]
    return random.Random(int(h, 16))


def draw_incident(rng):
    k = rng.randint(6, 22)                        # edge m06..m22  -> x in [1500, 5750)
    off = rng.uniform(60.0, SEG_LEN - 40.0)
    x = SEG_LEN * k + off
    n_block = rng.choice([1, 2])
    return {"edge": f"m{k:02d}", "seg": k, "offset": off, "x": x,
            "n_block": int(n_block), "lanes": list(range(n_block)),
            "t_start": float(rng.randint(INCIDENT_T_MIN, INCIDENT_T_MAX)),
            "dur": float(rng.randint(INCIDENT_DUR_MIN, INCIDENT_DUR_MAX))}


def pick_blocker(edge, seg, offset, lane_idx):
    """Choose a vehicle with enough lead distance to actually reach the stop point."""
    best, best_d = None, None
    for e in ([f"m{seg-1:02d}", edge] if seg > 0 else [edge]):
        try:
            vids = traci.edge.getLastStepVehicleIDs(e)
        except traci.TraCIException:
            continue
        for v in vids:
            try:
                li = traci.vehicle.getLaneIndex(v)
                p = traci.vehicle.getLanePosition(v)
            except traci.TraCIException:
                continue
            if li != lane_idx:
                continue
            d = (offset - p) if e == edge else (offset + traci.lane.getLength(f"{e}_{li}") - p)
            if 120.0 < d < 500.0 and (best_d is None or d < best_d):
                best, best_d = v, d
    return best


# ----------------------------------------------------------------- one run
def run(rundir, level, seed, arm, label=None):
    os.makedirs(rundir, exist_ok=True)
    e1 = os.path.join(rundir, "e1.xml")
    add = os.path.join(rundir, "det.add.xml")
    with open(add, "w") as f:
        f.write(build(e1))

    rng = incident_rng(seed)               # incident draw depends ONLY on seed -> matched pairs
    inc = draw_incident(rng)

    cmd = [SUMO_BIN, "-n", NET,
           "-r", os.path.join(DEMAND_DIR, f"demand_{level}.rou.xml"),
           "-a", add, "--begin", "0", "--end", str(SIM_END),
           "--seed", str(seed),
           "--time-to-teleport", "-1",          # freeway cannot deadlock; avoids manufacturing
           "--collision.action", "warn",        # teleports out of the incident queue itself
           "--no-step-log", "true", "--xml-validation", "never",
           "--summary-output", os.path.join(rundir, "summary.xml"),
           "--statistic-output", os.path.join(rundir, "stats.xml"),
           "--no-warnings", "true"]
    traci.start(cmd, label=label or rundir)
    conn = traci.getConnection(label or rundir)

    blockers, inj_t, resume_t = [], None, None
    gt_speed = []            # ground-truth mean speed on the incident edge, per 30 s
    gt_edge = inc["edge"]
    acc_spd, acc_n = 0.0, 0
    t = 0.0
    step = 1.0
    want = arm == "incident"
    while t < SIM_END:
        conn.simulationStep()
        t += step
        # --- incident injection
        if want and inj_t is None and t >= inc["t_start"]:
            got = []
            for li in inc["lanes"]:
                v = pick_blocker(inc["edge"], inc["seg"], inc["offset"], li)
                if v is not None and v not in got:
                    try:
                        conn.vehicle.setStop(v, inc["edge"], pos=inc["offset"],
                                             laneIndex=li, duration=inc["dur"], flags=0)
                        got.append(v)
                    except traci.TraCIException:
                        pass
            if len(got) == len(inc["lanes"]):
                blockers = got
                inj_t = t
            elif t > inc["t_start"] + 120:      # give up cleanly rather than silently mis-timing
                inj_t = -1.0
        # --- ground truth on the incident edge
        try:
            n = conn.edge.getLastStepVehicleNumber(gt_edge)
            acc_spd += conn.edge.getLastStepMeanSpeed(gt_edge) * n
            acc_n += n
        except traci.TraCIException:
            pass
        if int(t) % int(DET_PERIOD) == 0:
            gt_speed.append(acc_spd / acc_n if acc_n > 0 else np.nan)
            acc_spd, acc_n = 0.0, 0

    conn.close()

    vol, occ, spd = aggregate_e1(e1)
    np.savez_compressed(os.path.join(rundir, "det.npz"), vol=vol, occ=occ, spd=spd,
                        gt_speed=np.array(gt_speed))

    # summary / teleports / running-count freeze check
    running, teleports = [], 0
    for _, s in ET.iterparse(os.path.join(rundir, "summary.xml"), events=("end",)):
        if s.tag == "step":
            running.append(int(s.get("running")))
            teleports = max(teleports, int(s.get("teleports")))
            s.clear()
    st = ET.parse(os.path.join(rundir, "stats.xml")).getroot()
    veh = st.find("vehicles")
    coll_el = st.find("safety")

    meta = {"level": level, "seed": seed, "arm": arm,
            "incident": (inc if arm == "incident" else None),
            "injected_t": inj_t, "blockers": blockers,
            "inserted": int(veh.get("inserted")), "loaded": int(veh.get("loaded")),
            "running_end": int(veh.get("running")),
            "teleports": teleports,
            "collisions": int(coll_el.get("collisions")) if coll_el is not None else 0,
            "running_max": max(running), "running_last": running[-1],
            "running_tail_unique": len(set(running[-300:]))}
    with open(os.path.join(rundir, "meta.json"), "w") as f:
        json.dump(meta, f, indent=1)
    os.remove(e1)          # raw E1 XML is large; aggregated npz is the retained artifact
    return meta


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", default="moderate")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--arm", default="incident")
    ap.add_argument("--dir", default=os.path.join(RUNS_DIR, "_probe"))
    a = ap.parse_args()
    m = run(a.dir, a.level, a.seed, a.arm)
    print(json.dumps(m, indent=1))
