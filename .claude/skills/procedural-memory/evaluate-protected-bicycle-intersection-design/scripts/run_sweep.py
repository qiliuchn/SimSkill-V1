import sys, os, json, subprocess, hashlib, re, xml.etree.ElementTree as ET, statistics as st
from concurrent.futures import ProcessPoolExecutor, as_completed

sys.path.insert(0, "/private/tmp/claude-501/-Users-liuqi-Desktop-simskill/07cb182d-88df-492d-b918-d753d888c5e5/scratchpad/bikeint/lib")
sys.path.insert(0, "/private/tmp/claude-501/-Users-liuqi-Desktop-simskill/07cb182d-88df-492d-b918-d753d888c5e5/scratchpad/bikeint/demand")
import net_lib as nl
import demand_gen as dg

ROOT = "/private/tmp/claude-501/-Users-liuqi-Desktop-simskill/07cb182d-88df-492d-b918-d753d888c5e5/scratchpad/bikeint"
NET_DIR = os.path.join(ROOT, "net")
DEM_DIR = os.path.join(ROOT, "demand", "cells")
OUT_DIR = os.path.join(ROOT, "outputs", "runs")
ADD = os.path.join(ROOT, "sim", "vtypes.add.xml")
os.makedirs(DEM_DIR, exist_ok=True)
os.makedirs(OUT_DIR, exist_ok=True)

MANIFEST = json.load(open(os.path.join(NET_DIR, "manifest.json")))

BIKE_LEVELS = [50, 200, 400, 600]
RT_LEVELS = [100, 300]
REPS_MAIN = 5
REPS_ISO = 3
MAIN_VARIANTS = ["A", "B", "C", "D", "E"]
ISO_VARIANTS = ["C_radius_only", "C_setback_only"]

SIM_END = 4500  # 3600s demand horizon + 900s drain
CHECKPOINT = os.path.join(ROOT, "outputs", "sweep_checkpoint.jsonl")


def cell_seed(bike_level, rt_level, rep):
    s = f"{bike_level}_{rt_level}_{rep}"
    return int(hashlib.sha256(s.encode()).hexdigest()[:8], 16)


def ensure_demand(bike_level, rt_level, rep):
    path = os.path.join(DEM_DIR, f"bk{bike_level}_rt{rt_level}_rep{rep}.rou.xml")
    if not os.path.exists(path):
        dg.build_demand(bike_level, rt_level, seed=cell_seed(bike_level, rt_level, rep), out_path=path)
    return path


def parse_tripinfo(path):
    """Aggregate per-mode records; classify vehicle id -> (mode, approach, movement)."""
    id_re = re.compile(r"^(car|bike)_([NESW])_(through|left|right)_(\d+)$")
    ped_re = re.compile(r"^ped_([NESW])_(\d)_(\d+)$")
    cars = []
    bikes = []
    peds = []
    right_turn_counts = {"N": 0, "S": 0, "E": 0, "W": 0}
    left_turn_counts = {"N": 0, "S": 0, "E": 0, "W": 0}
    for _, elem in ET.iterparse(path, events=("end",)):
        if elem.tag == "tripinfo":
            vid = elem.get("id")
            m = id_re.match(vid)
            rec = dict(id=vid, duration=float(elem.get("duration")), routeLength=float(elem.get("routeLength")),
                       waitingTime=float(elem.get("waitingTime")), timeLoss=float(elem.get("timeLoss")),
                       departDelay=float(elem.get("departDelay")), waitingCount=float(elem.get("waitingCount", 0)))
            if m:
                mode, approach, movement, seq = m.groups()
                rec["approach"] = approach; rec["movement"] = movement
                if mode == "car":
                    cars.append(rec)
                    if movement == "right":
                        right_turn_counts[approach] += 1
                    elif movement == "left":
                        left_turn_counts[approach] += 1
                else:
                    bikes.append(rec)
            elem.clear()
        elif elem.tag == "personinfo":
            pid = elem.get("id")
            walk = elem.find("walk")
            if walk is not None:
                peds.append(dict(id=pid, duration=float(walk.get("duration", 0)),
                                  timeLoss=float(walk.get("timeLoss", 0)),
                                  routeLength=float(walk.get("routeLength", 0))))
            elem.clear()
    return cars, bikes, peds, right_turn_counts, left_turn_counts


def summarize(records, keys=("duration", "waitingTime", "timeLoss", "waitingCount")):
    out = {"n": len(records)}
    for k in keys:
        vals = [r[k] for r in records if k in r]
        out[f"{k}_mean"] = round(st.mean(vals), 3) if vals else None
        out[f"{k}_stdev"] = round(st.pstdev(vals), 3) if len(vals) > 1 else 0.0
    return out


def classify_ssm(path):
    """Return list of conflict dicts with movement-pair classification, filtered to car-bike pairs,
       plus raw counts by encounter type and by pair-category."""
    id_re = re.compile(r"^(car|bike)_([NESW])_(through|left|right)_(\d+)$")
    cats = {"right-hook": [], "left-cross": [], "through-through": [], "other-car-bike": []}
    all_conflicts = 0
    car_bike_conflicts = 0
    seen = set()
    for _, elem in ET.iterparse(path, events=("end",)):
        if elem.tag == "conflict":
            ego, foe = elem.get("ego"), elem.get("foe")
            begin = elem.get("begin")
            dedupe_key = (frozenset((ego, foe)), begin)
            if dedupe_key in seen:
                elem.clear()
                continue
            seen.add(dedupe_key)
            all_conflicts += 1
            me, mf = id_re.match(ego), id_re.match(foe)
            if me and mf:
                modes = {me.group(1), mf.group(1)}
                if modes == {"car", "bike"}:
                    car_bike_conflicts += 1
                    carm = me if me.group(1) == "car" else mf
                    bikm = me if me.group(1) == "bike" else mf
                    car_mv = carm.group(3)
                    bike_mv = bikm.group(3)
                    minttc = elem.find("minTTC")
                    pet = elem.find("PET")
                    ttc_val = float(minttc.get("value")) if minttc is not None and minttc.get("value") not in (None, "NA") else None
                    pet_val = float(pet.get("value")) if pet is not None and pet.get("value") not in (None, "NA") else None
                    rec = dict(ego=ego, foe=foe, car_mv=car_mv, bike_mv=bike_mv, ttc=ttc_val, pet=pet_val)
                    if car_mv == "right" and bike_mv == "through":
                        cats["right-hook"].append(rec)
                    elif car_mv == "left" and bike_mv == "through":
                        cats["left-cross"].append(rec)
                    elif car_mv == "through" and bike_mv == "through":
                        cats["through-through"].append(rec)
                    else:
                        cats["other-car-bike"].append(rec)
            elem.clear()
    return dict(all_conflicts=all_conflicts, car_bike_conflicts=car_bike_conflicts, cats=cats)


def parse_summary(path):
    last = None
    for _, elem in ET.iterparse(path, events=("end",)):
        if elem.tag == "step":
            last = elem.attrib
    if last is None:
        return {}
    return dict(collisions=int(last.get("collisions", 0)), teleports=int(last.get("teleports", 0)),
                ended=int(last.get("ended", 0)), loaded=int(last.get("loaded", 0)))


def run_one(variant, bike_level, rt_level, rep, rou_path):
    net = MANIFEST[variant]["net"]
    tag = f"{variant}_bk{bike_level}_rt{rt_level}_rep{rep}"
    outdir = os.path.join(OUT_DIR, tag)
    os.makedirs(outdir, exist_ok=True)
    trip = os.path.join(outdir, "tripinfo.xml")
    summ = os.path.join(outdir, "summary.xml")
    ssm = os.path.join(outdir, "ssm.xml")
    seed = cell_seed(bike_level, rt_level, rep)
    result = dict(variant=variant, bike_level=bike_level, rt_level=rt_level, rep=rep, rc=-99)
    cmd = [nl.SUMO_BIN, "-n", net, "-r", rou_path, "-a", ADD,
           "--tripinfo-output", trip, "--summary-output", summ,
           "--device.ssm.file", ssm,
           "--lateral-resolution", "0.8", "--step-length", "0.5",
           "--time-to-teleport", "-1", "--collision.action", "warn",
           "--no-step-log", "true", "--seed", str(seed % 30000),
           "--begin", "0", "--end", str(SIM_END)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        result["rc"] = r.returncode
        if r.returncode != 0:
            result["error"] = r.stderr[-2000:]
            return result
    except subprocess.TimeoutExpired:
        result["error"] = "TIMEOUT after 180s"
        return result
    except Exception as e:
        result["error"] = f"EXC: {e}"
        return result
    try:
        cars, bikes, peds, rtc, ltc = parse_tripinfo(trip)
        result["car"] = summarize(cars)
        result["bike"] = summarize(bikes)
        result["ped"] = summarize(peds)
        result["right_turn_served"] = rtc
        result["left_turn_served"] = ltc
        result["ssm"] = classify_ssm(ssm)
        for k, v in result["ssm"]["cats"].items():
            result["ssm"]["cats"][k] = dict(n=len(v),
                                             ttc_vals=[c["ttc"] for c in v if c["ttc"] is not None],
                                             pet_vals=[c["pet"] for c in v if c["pet"] is not None])
        result["summary"] = parse_summary(summ)
    except Exception as e:
        result["parse_error"] = str(e)
    # cleanup raw XML to save disk
    for p in (trip, summ, ssm):
        try:
            os.remove(p)
        except OSError:
            pass
    try:
        os.rmdir(outdir)
    except OSError:
        pass
    return result


def job_list():
    jobs = []
    for bike_level in BIKE_LEVELS:
        for rt_level in RT_LEVELS:
            for rep in range(REPS_MAIN):
                rou = ensure_demand(bike_level, rt_level, rep)
                for v in MAIN_VARIANTS:
                    jobs.append((v, bike_level, rt_level, rep, rou))
                if rep < REPS_ISO:
                    for v in ISO_VARIANTS:
                        jobs.append((v, bike_level, rt_level, rep, rou))
    return jobs


if __name__ == "__main__":
    jobs = job_list()
    print("total jobs:", len(jobs), flush=True)
    results = []
    ckpt_f = open(CHECKPOINT, "w")
    with ProcessPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(run_one, *j[:4], j[4]): j for j in jobs}
        done = 0
        for fut in as_completed(futs):
            j = futs[fut]
            try:
                res = fut.result()
            except Exception as e:
                res = dict(variant=j[0], bike_level=j[1], rt_level=j[2], rep=j[3], rc=-1, error=f"FUTURE_EXC: {e}")
            results.append(res)
            ckpt_f.write(json.dumps(res) + "\n")
            ckpt_f.flush()
            done += 1
            if done % 10 == 0:
                print(f"{done}/{len(jobs)} done", flush=True)
    ckpt_f.close()
    with open(os.path.join(ROOT, "outputs", "sweep_results.json"), "w") as f:
        json.dump(results, f)
    nfail = sum(1 for r in results if r.get("rc", 0) != 0)
    print("DONE. failures:", nfail, "of", len(results), flush=True)
