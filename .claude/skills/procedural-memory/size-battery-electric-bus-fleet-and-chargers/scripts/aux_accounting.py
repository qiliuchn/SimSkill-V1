#!/usr/bin/env python3
"""
Validate the auxiliary-energy accounting by a paired aux=0 re-run.

Question: is the auxiliary (HVAC) energy simply `constantPowerIntake x time_in_network`?
Answer (this SUMO version): NO -- the naive product over-states the battery's auxiliary
draw, because on time steps where the vehicle is actively taking charge at a
chargingStation the constant power intake does not appear in `energyConsumed` at all.
On every other step it appears exactly (1 W over 1 s == 1/3600 Wh, to 4 decimals).
"""
import os, sys, json, statistics, collections
import xml.etree.ElementTree as ET


def stream(path, vid):
    t = 0.0
    for ev, el in ET.iterparse(path, events=("start", "end")):
        if ev == "start" and el.tag == "timestep":
            t = float(el.get("time"))
        elif ev == "end" and el.tag == "vehicle":
            if el.get("id") == vid:
                a = el.attrib
                yield t, (float(a["energyConsumed"]), float(a["speed"]),
                          a.get("chargingStationId"), float(a["energyCharged"]),
                          float(a["totalEnergyConsumed"]), float(a["totalEnergyRegenerated"]))
            el.clear()
        elif ev == "end" and el.tag == "timestep":
            el.clear()


def compare(dirA, dirB, aux_w=7000.0, vid="bus_0"):
    A = dict(stream(os.path.join(dirA, "battery.xml"), vid))
    B = dict(stream(os.path.join(dirB, "battery.xml"), vid))
    common = sorted(set(A) & set(B))
    per_step = aux_w / 3600.0
    cat = collections.defaultdict(list)
    zero_diff_charging = 0
    zero_diff_not_charging = 0
    for t in common:
        d = A[t][0] - B[t][0]
        charging = A[t][2] not in ("NULL", "", None)
        cat[("charging" if charging else "not charging")].append(d)
        if abs(d) < 1e-6:
            if charging:
                zero_diff_charging += 1
            else:
                zero_diff_not_charging += 1
    lastA, lastB = A[max(A)], B[max(B)]
    netA, netB = lastA[4] - lastA[5], lastB[4] - lastB[5]
    naive = per_step * len(A)
    return dict(
        vehicle=vid, n_steps=len(A), aux_w=aux_w, per_step_wh=round(per_step, 6),
        naive_P_times_time_wh=round(naive, 2),
        measured_aux_from_paired_run_wh=round(netA - netB, 2),
        ratio_measured_over_naive=round((netA - netB) / naive, 4),
        gross_consumed_aux_on_wh=round(lastA[4], 2),
        gross_consumed_aux_off_wh=round(lastB[4], 2),
        regenerated_aux_on_wh=round(lastA[5], 2),
        regenerated_aux_off_wh=round(lastB[5], 2),
        split_of_aux=dict(
            extra_gross_consumption_wh=round(lastA[4] - lastB[4], 2),
            lost_regeneration_wh=round(lastB[5] - lastA[5], 2),
            sum_wh=round((lastA[4] - lastB[4]) + (lastB[5] - lastA[5]), 2)),
        steps_where_the_two_runs_agree_exactly=dict(
            while_charging=zero_diff_charging, while_not_charging=zero_diff_not_charging),
        mean_per_step_difference=({k: round(statistics.mean(v), 6) for k, v in cat.items()}),
        unaccounted_wh=round(naive - (netA - netB), 2),
        unaccounted_equals_zero_diff_charging_steps=round(zero_diff_charging * per_step, 2),
        conclusion=("`constantPowerIntake` is charged to the battery on every step EXCEPT steps "
                    "on which the vehicle is actively taking charge at a chargingStation. "
                    "The residual between the naive P*t product and the paired-run measurement "
                    "equals exactly (number of such steps) x P/3600. Auxiliary energy must "
                    "therefore be measured on NET energy (consumed - regenerated) from a paired "
                    "aux=0 re-run, or computed as P x (time - charging time); using "
                    "P x time_in_network over-states it, and using the increase in "
                    "totalEnergyConsumed alone under-states it, because part of the auxiliary "
                    "load is paid for out of recuperated energy rather than out of new draw."))


if __name__ == "__main__":
    R = compare(sys.argv[1], sys.argv[2])
    json.dump(R, open(sys.argv[3], "w"), indent=1)
    print(json.dumps(R, indent=1))
