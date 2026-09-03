import xml.etree.ElementTree as ET

TREATMENTS = ["permissive", "protected", "protperm"]
OUT = "../outputs"

# left-turn flow -> its oncoming-through flow
ONCOMING = {"N_L": "S_T", "S_L": "N_T", "E_L": "W_T", "W_L": "E_T"}
# unordered set of left/oncoming pairs
LT_ONCOMING_PAIRS = {frozenset((l, t)) for l, t in ONCOMING.items()}
LEFT_FLOWS = set(ONCOMING.keys())

CROSSING = set(range(10, 18))
COLLISION = {111}

def flow_of(vid):
    return vid.rsplit(".", 1)[0]

def parse_tripinfo(path):
    root = ET.parse(path).getroot()
    all_wait, all_loss, all_dur = [], [], []
    left_wait, left_loss = [], []
    n_left = 0
    for ti in root.findall("tripinfo"):
        vid = ti.get("id"); fl = flow_of(vid)
        w = float(ti.get("waitingTime")); tl = float(ti.get("timeLoss")); d = float(ti.get("duration"))
        all_wait.append(w); all_loss.append(tl); all_dur.append(d)
        if fl in LEFT_FLOWS:
            left_wait.append(w); left_loss.append(tl); n_left += 1
    mean = lambda a: sum(a)/len(a) if a else 0.0
    return {
        "throughput": len(all_wait),
        "n_left": n_left,
        "mean_wait_all": mean(all_wait),
        "mean_timeloss_all": mean(all_loss),
        "mean_dur_all": mean(all_dur),
        "mean_wait_left": mean(left_wait),
        "mean_timeloss_left": mean(left_loss),
    }

def parse_ssm(path):
    root = ET.parse(path).getroot()
    total = 0
    lt_onc = 0            # left-turn vs its oncoming-through, any encounter type
    lt_onc_crossing = 0   # of those, crossing-type
    collisions = 0
    worst_ttc_lt = None
    worst_pet_lt = None
    for el in root:
        if el.tag != "conflict":
            continue
        total += 1
        ego = flow_of(el.get("ego")); foe = flow_of(el.get("foe"))
        pair = frozenset((ego, foe))
        # gather types + values
        types = set(); ttc = None; pet = None
        for m in el:
            t = m.get("type")
            if t not in (None, "NA"):
                types.add(int(t))
            if m.tag == "minTTC" and m.get("value") not in (None, "NA"):
                ttc = float(m.get("value"))
            if m.tag == "PET" and m.get("value") not in (None, "NA"):
                pet = float(m.get("value"))
        if types & COLLISION:
            collisions += 1
        if pair in LT_ONCOMING_PAIRS:
            lt_onc += 1
            if types & CROSSING:
                lt_onc_crossing += 1
            if ttc is not None and (worst_ttc_lt is None or ttc < worst_ttc_lt):
                worst_ttc_lt = ttc
            if pet is not None and (worst_pet_lt is None or pet < worst_pet_lt):
                worst_pet_lt = pet
    return {
        "total_conflicts": total,
        "lt_oncoming_conflicts": lt_onc,
        "lt_oncoming_crossing": lt_onc_crossing,
        "collisions": collisions,
        "worst_ttc_lt": worst_ttc_lt,
        "worst_pet_lt": worst_pet_lt,
    }

rows = {}
for T in TREATMENTS:
    ti = parse_tripinfo(f"{OUT}/tripinfo_{T}.xml")
    ss = parse_ssm(f"{OUT}/ssm_{T}.xml")
    rows[T] = {**ti, **ss}

# print comparison table
cols = [
    ("throughput", "Throughput (veh)", "{:d}"),
    ("mean_wait_left", "Mean LEFT-turn wait (s)", "{:.2f}"),
    ("mean_timeloss_left", "Mean LEFT-turn timeLoss (s)", "{:.2f}"),
    ("mean_wait_all", "Mean overall wait (s)", "{:.2f}"),
    ("mean_timeloss_all", "Mean overall delay/timeLoss (s)", "{:.2f}"),
    ("total_conflicts", "Total SSM conflicts", "{:d}"),
    ("lt_oncoming_conflicts", "LEFT-vs-oncoming-thru conflicts", "{:d}"),
    ("lt_oncoming_crossing", "  of which crossing-type", "{:d}"),
    ("collisions", "Simulated collisions", "{:d}"),
    ("worst_ttc_lt", "Worst TTC in LT-onc (s)", "{}"),
    ("worst_pet_lt", "Worst PET in LT-onc (s)", "{}"),
]
hdr = f"{'Metric':<34}" + "".join(f"{T:>14}" for T in TREATMENTS)
print(hdr); print("-"*len(hdr))
for key, label, fmt in cols:
    cells = ""
    for T in TREATMENTS:
        v = rows[T][key]
        cells += f"{(fmt.format(v) if v is not None else 'NA'):>14}"
    print(f"{label:<34}{cells}")

import json
print("\nRAW:", json.dumps(rows, indent=2))
