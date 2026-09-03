import sys, os, json
sys.path.insert(0, "/private/tmp/claude-501/-Users-liuqi-Desktop-simskill/07cb182d-88df-492d-b918-d753d888c5e5/scratchpad/bikeint/analysis")
from stats_lib import mean_ci, paired_diff_ci

ROOT = "/private/tmp/claude-501/-Users-liuqi-Desktop-simskill/07cb182d-88df-492d-b918-d753d888c5e5/scratchpad/bikeint"
OUT = os.path.join(ROOT, "outputs")
results = json.load(open(os.path.join(OUT, "sweep_results.json")))
ok = [r for r in results if r.get("rc", 0) == 0 and "error" not in r and "parse_error" not in r]

from collections import defaultdict
by_key = defaultdict(dict)  # (bike_level, rt_level, rep) -> {variant: result}
for r in ok:
    by_key[(r["bike_level"], r["rt_level"], r["rep"])][r["variant"]] = r

BIKE_LEVELS = sorted(set(r["bike_level"] for r in ok))
RT_LEVELS = sorted(set(r["rt_level"] for r in ok))


def right_hook_rate(r):
    n = r["ssm"]["cats"]["right-hook"]["n"]
    denom = r["right_turn_served"]["N"] + r["right_turn_served"]["S"]
    return 1000.0 * n / denom if denom else None


def all_conflict_rate_per_bike(r):
    n = r["ssm"]["car_bike_conflicts"]
    denom = r["bike"]["n"]
    return 1000.0 * n / denom if denom else None


def person_delay(r):
    cd, cn = r["car"]["timeLoss_mean"], r["car"]["n"]
    bd, bn = r["bike"]["timeLoss_mean"], r["bike"]["n"]
    pd, pn = r["ped"]["timeLoss_mean"], r["ped"]["n"]
    if None in (cd, bd, pd):
        return None
    tot_t = cd * cn * 1.2 + bd * bn + pd * pn
    tot_p = cn * 1.2 + bn + pn
    return tot_t / tot_p if tot_p else None


def paired(v1, v2, bike_level, rt_level, metric_fn):
    a, b = [], []
    for rep in range(20):
        key = (bike_level, rt_level, rep)
        if key not in by_key:
            continue
        d = by_key[key]
        if v1 in d and v2 in d:
            a.append(metric_fn(d[v1]))
            b.append(metric_fn(d[v2]))
    return paired_diff_ci(a, b), len(a)


answers = {}

# Q1: C vs E on right-hook conflict rate, per bike level (both rt levels pooled report separately)
q1 = []
for rt in RT_LEVELS:
    for bl in BIKE_LEVELS:
        diff_ci, n = paired("E", "C", bl, rt, right_hook_rate)  # E - C: positive means C has fewer conflicts (better)
        car_diff, _ = paired("C", "E", bl, rt, lambda r: r["car"]["timeLoss_mean"])  # C - E: positive means C costs more car delay
        ped_diff, _ = paired("C", "E", bl, rt, lambda r: r["ped"]["timeLoss_mean"])
        q1.append(dict(rt_level=rt, bike_level=bl, n_pairs=n,
                        conflict_rate_E_minus_C=diff_ci,
                        car_delay_cost_C_minus_E=car_diff,
                        ped_delay_cost_C_minus_E=ped_diff))
answers["Q1_C_vs_E_by_bike_level"] = q1

# Q2: does D eliminate conflicts vs merely convert to delay? person-delay breakeven vs C
q2 = []
for rt in RT_LEVELS:
    for bl in BIKE_LEVELS:
        conf_diff, n = paired("C", "D", bl, rt, right_hook_rate)  # C - D positive means D has fewer
        pdelay_diff, _ = paired("D", "C", bl, rt, person_delay)  # D - C: positive means D costs more person-delay
        q2.append(dict(rt_level=rt, bike_level=bl, n_pairs=n,
                        right_hook_rate_C_minus_D=conf_diff,
                        person_delay_D_minus_C=pdelay_diff))
answers["Q2_D_vs_C_by_bike_level"] = q2

# Q3: A (mixing) vs B (conventional) -- conflict COUNT vs SEVERITY (mean TTC, share TTC<1.5s)
def all_ttcs(r):
    out = []
    for cat in r["ssm"]["cats"].values():
        out += cat["ttc_vals"]
    return out


def frac_severe(r, thresh=1.5):
    vals = all_ttcs(r)
    return (sum(1 for t in vals if t < thresh) / len(vals)) if vals else None


def mean_ttc(r):
    vals = all_ttcs(r)
    return (sum(vals) / len(vals)) if vals else None


q3 = []
for rt in RT_LEVELS:
    for bl in BIKE_LEVELS:
        cnt_diff, n = paired("A", "B", bl, rt, lambda r: r["ssm"]["car_bike_conflicts"])
        severe_diff, _ = paired("A", "B", bl, rt, frac_severe)
        meanttc_diff, _ = paired("A", "B", bl, rt, mean_ttc)
        q3.append(dict(rt_level=rt, bike_level=bl, n_pairs=n,
                        conflict_count_A_minus_B=cnt_diff,
                        frac_ttc_below_1_5_A_minus_B=severe_diff,
                        mean_ttc_A_minus_B=meanttc_diff))
answers["Q3_A_vs_B_conflict_count_vs_severity"] = q3

# Q4: isolate radius vs setback (B, C_radius_only, C_setback_only, C) -- conflict rate + turn speed proxy
q4 = []
for rt in RT_LEVELS:
    for bl in BIKE_LEVELS:
        row = dict(rt_level=rt, bike_level=bl)
        for v in ["B", "C_radius_only", "C_setback_only", "C"]:
            vals = []
            for rep in range(20):
                key = (bl, rt, rep)
                if key in by_key and v in by_key[key]:
                    vals.append(right_hook_rate(by_key[key][v]))
            row[f"right_hook_rate_{v}"] = mean_ci(vals)
        q4.append(row)
answers["Q4_isolate_radius_vs_setback"] = q4

with open(os.path.join(OUT, "answers_raw.json"), "w") as f:
    json.dump(answers, f, indent=2)
print("Q1-Q4 computed and written to answers_raw.json")
