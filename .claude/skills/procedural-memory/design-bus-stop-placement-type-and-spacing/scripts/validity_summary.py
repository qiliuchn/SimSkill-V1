"""Global validity audit across every run this study produced.

Reads every runs/<arm>/s<seed>/metrics.json and aggregates the four things that
must be checked before any of the headline numbers can be trusted:
  1. teleport artifacts        (summary `teleports`, cumulative -> max, never summed)
  2. completed vs still-running vehicles
  3. still-waiting / still-riding persons at the end of the simulation
  4. buses actually SERVED every scheduled stop (no skipped stops)
"""
import os
import glob
import json

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def main():
    tot = {"runs": 0, "teleports": 0, "teleport_warnings": 0,
           "cars": 0, "cars_unfinished": 0,
           "riders": 0, "riders_incomplete": 0, "riders_still_waiting": 0,
           "riders_still_riding": 0,
           "stop_events": 0, "stop_events_expected": 0, "missed_stop_services": 0,
           "runs_with_teleports": 0, "runs_with_unfinished_cars": 0,
           "runs_with_missed_stops": 0, "runs_with_nonzero_final_running": 0}
    worst = []
    for p in glob.glob(os.path.join(ROOT, "runs", "*", "s*", "metrics.json")):
        try:
            m = json.load(open(p))
        except Exception:
            continue
        tot["runs"] += 1
        tot["teleports"] += m.get("teleports", 0)
        tot["teleport_warnings"] += m.get("teleport_warnings", 0)
        tot["cars"] += m.get("n_cars", 0)
        tot["cars_unfinished"] += m.get("cars_unfinished", 0)
        tot["riders"] += m.get("n_riders", 0)
        tot["riders_incomplete"] += m.get("riders_incomplete", 0)
        tot["riders_still_waiting"] += m.get("riders_still_waiting", 0)
        tot["riders_still_riding"] += m.get("riders_still_riding", 0)
        tot["stop_events"] += m.get("stop_events", 0)
        tot["stop_events_expected"] += m.get("stop_events_expected", 0)
        tot["missed_stop_services"] += m.get("missed_stop_services", 0)
        tot["runs_with_teleports"] += int(m.get("teleports", 0) > 0)
        tot["runs_with_unfinished_cars"] += int(m.get("cars_unfinished", 0) > 0)
        tot["runs_with_missed_stops"] += int(m.get("missed_stop_services", 0) > 0)
        tot["runs_with_nonzero_final_running"] += int(m.get("final_running", 0) > 0)
        if m.get("teleports", 0) or m.get("missed_stop_services", 0) or m.get("cars_unfinished", 0):
            worst.append({"run": os.path.dirname(p), "teleports": m.get("teleports"),
                          "cars_unfinished": m.get("cars_unfinished"),
                          "missed": m.get("missed_stop_services")})
    tot["teleport_affected_share_of_car_trips"] = tot["teleports"] / max(tot["cars"], 1)
    tot["rider_incompletion_rate"] = tot["riders_incomplete"] / max(tot["riders"] + tot["riders_incomplete"], 1)
    tot["stop_service_completeness"] = tot["stop_events"] / max(tot["stop_events_expected"], 1)
    tot["problem_runs"] = worst[:50]
    json.dump(tot, open(os.path.join(ROOT, "results", "validity_summary.json"), "w"), indent=1)
    for k, v in tot.items():
        if k != "problem_runs":
            print(f"  {k:44s} {v}")
    print(f"  n problem runs listed: {len(worst)}")


if __name__ == "__main__":
    main()
