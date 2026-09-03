"""Parse a SUMO tripinfo file, separating <tripinfo> (vehicles) from
<personinfo> (pedestrians), and report mean metrics + throughput for each.

Usage: python parse_tripinfo_by_mode.py path/to/tripinfo.xml
"""
import sys
import json
import xml.etree.ElementTree as ET


def parse(path):
    veh_dur, veh_wait, veh_loss = [], [], []
    ped_dur, ped_wait, ped_loss, ped_travel = [], [], [], []
    for _, el in ET.iterparse(path):
        if el.tag == "tripinfo":
            veh_dur.append(float(el.get("duration")))
            veh_wait.append(float(el.get("waitingTime")))
            veh_loss.append(float(el.get("timeLoss")))
            el.clear()
        elif el.tag == "personinfo":
            ped_dur.append(float(el.get("duration")))
            ped_wait.append(float(el.get("waitingTime")))
            tl = el.get("timeLoss")
            ped_loss.append(float(tl) if tl is not None else 0.0)
            tt = el.get("traveltime")
            ped_travel.append(float(tt) if tt is not None else float(el.get("duration")))
            el.clear()

    def mean(x):
        return round(sum(x) / len(x), 2) if x else None

    return {
        "n_vehicles_completed": len(veh_dur),
        "veh_mean_duration_s": mean(veh_dur),
        "veh_mean_waiting_s": mean(veh_wait),
        "veh_mean_timeloss_s": mean(veh_loss),
        "n_persons_completed": len(ped_dur),
        "ped_mean_duration_s": mean(ped_dur),
        "ped_mean_waiting_s": mean(ped_wait),
        "ped_mean_walktime_s": mean(ped_travel),
        "ped_mean_timeloss_s": mean(ped_loss),
    }


if __name__ == "__main__":
    print(json.dumps(parse(sys.argv[1]), indent=2))
