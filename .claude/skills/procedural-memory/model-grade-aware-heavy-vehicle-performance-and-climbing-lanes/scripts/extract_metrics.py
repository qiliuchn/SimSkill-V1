#!/usr/bin/env python3
"""Parse one cell's raw SUMO outputs (tripinfo/edgeData/laneData/collisions/
stats/profile_bins) into a flat metrics dict. Robust to missing/partial
files -- returns None fields rather than raising, so a sweep of many cells
can tolerate a handful of odd cases without losing the whole batch."""
import json
import math
import os
import statistics
import xml.etree.ElementTree as ET

WARMUP = 300.0


def _safe_parse(path):
    try:
        return ET.parse(path).getroot()
    except Exception:
        return None


def extract(meta):
    sim_end = None
    out = {k: meta[k] for k in ("tag", "grade_pct", "grade_len_km", "variant", "direction",
                                 "volume_vph", "truck_pct_nominal", "truck_pct_realized",
                                 "seed", "model", "ratio", "wall_seconds", "traci_call_count")}

    # ---- tripinfo ----
    root = _safe_parse(meta["tripinfo_path"])
    car_speeds, car_tl, truck_speeds, truck_tl = [], [], [], []
    n_unfinished = 0
    n_total = 0
    if root is not None:
        for tp in root.findall("tripinfo"):
            n_total += 1
            depart = float(tp.get("depart"))
            if depart < WARMUP:
                continue
            vap = tp.get("vaporized", "")
            if vap not in ("", None):
                n_unfinished += 1
                continue
            dur = float(tp.get("duration"))
            rl = float(tp.get("routeLength"))
            tl = float(tp.get("timeLoss"))
            if dur <= 0:
                continue
            speed_kmh = (rl / dur) * 3.6
            vtype = tp.get("vType") or ""
            # NOTE: speedFactor="normc(...)" makes SUMO clone a per-vehicle vType
            # named "<baseType>@<vehID>" (e.g. "hvt@hv_4") -- match by prefix, not
            # equality, or every truck/car row silently fails the filter and the
            # truck-side statistics come back empty despite trucks completing fine.
            if vtype.startswith("hvt"):
                truck_speeds.append(speed_kmh)
                truck_tl.append(tl)
            else:
                car_speeds.append(speed_kmh)
                car_tl.append(tl)
    out["n_car_completed"] = len(car_speeds)
    out["n_truck_completed"] = len(truck_speeds)
    out["n_unfinished_or_vaporized"] = n_unfinished
    out["n_total_generated"] = n_total
    out["car_mean_speed_kmh"] = round(statistics.mean(car_speeds), 3) if car_speeds else None
    out["car_speed_stdev_kmh"] = round(statistics.pstdev(car_speeds), 3) if len(car_speeds) > 1 else None
    out["car_mean_timeloss_s"] = round(statistics.mean(car_tl), 3) if car_tl else None
    out["truck_mean_speed_kmh"] = round(statistics.mean(truck_speeds), 3) if truck_speeds else None
    out["truck_speed_stdev_kmh"] = round(statistics.pstdev(truck_speeds), 3) if len(truck_speeds) > 1 else None
    out["truck_mean_timeloss_s"] = round(statistics.mean(truck_tl), 3) if truck_tl else None
    if out["car_mean_speed_kmh"] and out["truck_mean_speed_kmh"]:
        out["car_truck_speed_diff_kmh"] = round(out["car_mean_speed_kmh"] - out["truck_mean_speed_kmh"], 3)
    else:
        out["car_truck_speed_diff_kmh"] = None
    all_speeds = car_speeds + truck_speeds
    out["all_veh_speed_stdev_kmh"] = round(statistics.pstdev(all_speeds), 3) if len(all_speeds) > 1 else None

    # ---- collisions ----
    croot = _safe_parse(meta["collisions_path"])
    out["n_collisions"] = len(croot.findall("collision")) if croot is not None else None

    # ---- stats (teleports etc.) ----
    sroot = _safe_parse(meta.get("stats_path", ""))
    out["n_teleports"] = None
    if sroot is not None:
        veh = sroot.find("vehicleTripStatistics")
        safety = sroot.find("safety")
        if safety is not None:
            out["n_collisions_stats"] = safety.get("collisions")
            out["n_teleports"] = safety.get("teleports") if safety.get("teleports") is not None else None
        te = sroot.find("teleports")
        if te is not None:
            out["n_teleports"] = te.get("total")

    # ---- edgeData: throughput (served flow) on departure edge, steady state ----
    eroot = _safe_parse(meta["edgedata_all_path"])
    dep_flows = []
    grade_speeds_all = []
    if eroot is not None:
        for interval in eroot.findall("interval"):
            begin = float(interval.get("begin"))
            if begin < WARMUP:
                continue
            for edge in interval.findall("edge"):
                if edge.get("id") == "departure" and edge.get("flow") is not None:
                    dep_flows.append(float(edge.get("flow")))
                if edge.get("id") == "grade" and edge.get("speed") is not None:
                    grade_speeds_all.append(float(edge.get("speed")))
    out["served_flow_vph_mean"] = round(statistics.mean(dep_flows), 1) if dep_flows else None
    out["served_flow_vph_max"] = round(max(dep_flows), 1) if dep_flows else None
    out["grade_edge_mean_speed_kmh_allveh"] = round(statistics.mean(grade_speeds_all) * 3.6, 2) if grade_speeds_all else None

    # ---- edgeData truck-filtered: crawl speed on the grade edge ----
    etroot = _safe_parse(meta["edgedata_truck_path"])
    grade_truck_speeds = []
    approach_truck_speeds = []
    if etroot is not None:
        for interval in etroot.findall("interval"):
            begin = float(interval.get("begin"))
            if begin < WARMUP:
                continue
            for edge in interval.findall("edge"):
                if edge.get("id") == "grade" and edge.get("speed") is not None:
                    grade_truck_speeds.append(float(edge.get("speed")))
                if edge.get("id") == "approach" and edge.get("speed") is not None:
                    approach_truck_speeds.append(float(edge.get("speed")))
    out["truck_grade_edge_speed_kmh"] = round(statistics.mean(grade_truck_speeds) * 3.6, 2) if grade_truck_speeds else None
    out["truck_approach_edge_speed_kmh"] = round(statistics.mean(approach_truck_speeds) * 3.6, 2) if approach_truck_speeds else None

    # ---- fine-grained profile (grade_aware only): crawl speed + AASHTO location/magnitude ----
    out["profile_crawl_speed_kmh"] = None
    out["profile_max_reduction_kmh"] = None
    out["profile_max_reduction_location_m"] = None
    out["profile_aashto_15kmh_exceeded"] = None
    pb = meta.get("profile_bins")
    if pb and pb.get("mean_speed_by_bin"):
        speeds = pb["mean_speed_by_bin"]
        counts = pb["count_by_bin"]
        bw = pb["bin_width_m"]
        valid = [(i, s) for i, (s, c) in enumerate(zip(speeds, counts)) if s is not None and c and c >= 3]
        if valid:
            entry_candidates = [s for (i, s) in valid if i * bw < 3200]  # approach region
            entry_speed = max(entry_candidates) if entry_candidates else valid[0][1]
            min_i, min_s = min(valid, key=lambda x: x[1])
            out["profile_crawl_speed_kmh"] = round(min_s * 3.6, 2)
            reduction_ms = entry_speed - min_s
            out["profile_max_reduction_kmh"] = round(reduction_ms * 3.6, 2)
            out["profile_max_reduction_location_m"] = min_i * bw
            out["profile_aashto_15kmh_exceeded"] = bool(reduction_ms * 3.6 >= 15.0)

    # ---- lane utilization (all + truck) on the 3-lane extent ----
    def lane_shares(path, edge_prefix="grade"):
        r = _safe_parse(path)
        if r is None:
            return None
        tot = {}
        for interval in r.findall("interval"):
            begin = float(interval.get("begin"))
            if begin < WARMUP:
                continue
            for lane in interval.findall(".//lane"):  # lanes nest under <edge> within <interval>
                lid = lane.get("id")
                if not lid.startswith(edge_prefix + "_"):
                    continue
                ss = float(lane.get("sampledSeconds") or 0.0)
                tot[lid] = tot.get(lid, 0.0) + ss
        total = sum(tot.values())
        if total <= 0:
            return None
        return {lid: round(100.0 * v / total, 2) for lid, v in tot.items()}

    out["lane_share_all_grade_edge"] = lane_shares(meta["lanedata_path"], "grade")
    out["lane_share_truck_grade_edge"] = lane_shares(meta.get("lanedata_truck_path", ""), "grade")

    return out


if __name__ == "__main__":
    import sys
    meta_path = sys.argv[1]
    meta = json.load(open(meta_path))
    print(json.dumps(extract(meta), indent=2))
