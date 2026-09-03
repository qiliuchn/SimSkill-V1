"""Metrics extraction + small stats helpers shared by every experiment driver."""
import math
import statistics
import xml.etree.ElementTree as ET
from collections import defaultdict


def parse_tripinfo(path):
    """Return (cars: list[dict], trams: list[dict], persons: list[dict])."""
    cars, trams, persons = [], [], []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "tripinfo":
            d = dict(id=el.get("id"), vType=el.get("vType"),
                     depart=float(el.get("depart")), arrival=float(el.get("arrival")),
                     duration=float(el.get("duration")), waitingTime=float(el.get("waitingTime")),
                     timeLoss=float(el.get("timeLoss")), routeLength=float(el.get("routeLength")),
                     stopTime=float(el.get("stopTime", 0.0)))
            if el.get("vType") == "car":
                cars.append(d)
            elif el.get("vType") == "tram":
                trams.append(d)
            el.clear()
        elif el.tag == "personinfo":
            ride = el.find("ride")
            d = dict(id=el.get("id"), depart=float(el.get("depart")),
                     duration=float(el.get("duration")), waitingTime=float(el.get("waitingTime")),
                     timeLoss=float(el.get("timeLoss")),
                     ride_wait=float(ride.get("waitingTime")) if ride is not None else None,
                     ride_duration=float(ride.get("duration")) if ride is not None else None,
                     completed_ride=ride is not None)
            persons.append(d)
            el.clear()
    return cars, trams, persons


def parse_stopout(path):
    """Return list of dicts, one per tram stop event."""
    out = []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "stopinfo" and el.get("type") == "tram":
            out.append(dict(id=el.get("id"), lane=el.get("lane"), busStop=el.get("busStop"),
                            started=float(el.get("started")), ended=float(el.get("ended")),
                            dwell=float(el.get("ended")) - float(el.get("started"))))
            el.clear()
    return out


def headway_cv_at_terminal(stops, terminal_stop_id):
    """CV of headway (inter-tram gap) at a chosen terminal busStop id, from
    stop-output 'ended' timestamps (when the tram finished dwelling/departed)."""
    times = sorted(s["ended"] for s in stops if s["busStop"] == terminal_stop_id)
    if len(times) < 3:
        return dict(n=len(times), mean=float("nan"), sd=float("nan"), cv=float("nan"), gaps=[])
    gaps = [times[i + 1] - times[i] for i in range(len(times) - 1)]
    m = statistics.mean(gaps)
    s = statistics.stdev(gaps) if len(gaps) > 1 else 0.0
    return dict(n=len(gaps), mean=m, sd=s, cv=(s / m if m else float("nan")), gaps=gaps)


def mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.mean(xs) if xs else float("nan")


def ci95(xs):
    xs = [x for x in xs if x is not None and not (isinstance(x, float) and math.isnan(x))]
    n = len(xs)
    if n == 0:
        return dict(n=0, mean=float("nan"), sd=float("nan"), lo=float("nan"), hi=float("nan"), hw=float("nan"))
    m = statistics.mean(xs)
    if n < 2:
        return dict(n=n, mean=m, sd=0.0, lo=m, hi=m, hw=0.0)
    s = statistics.stdev(xs)
    # Student-t 95% half-width via normal approx table for small n (t~ n<=30)
    T = {2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776, 6: 2.571, 7: 2.447, 8: 2.365,
         9: 2.306, 10: 2.262, 11: 2.228, 12: 2.201, 15: 2.145, 20: 2.093, 30: 2.045}
    df = n - 1
    tval = T.get(df, 1.96 if df > 30 else T[min(T.keys(), key=lambda k: abs(k - df))])
    hw = tval * s / math.sqrt(n)
    return dict(n=n, mean=m, sd=s, lo=m - hw, hi=m + hw, hw=hw)


def summarize_run(tripinfo_path, stopout_path=None, terminal_eb=None, terminal_wb=None,
                   car_occupancy=1.2, tram_end=None):
    cars, trams, persons = parse_tripinfo(tripinfo_path)
    out = dict(
        n_cars=len(cars), n_trams=len(trams), n_persons=len(persons),
        n_persons_completed_ride=sum(1 for p in persons if p["completed_ride"]),
        car_mean_duration=mean([c["duration"] for c in cars]),
        car_mean_waiting=mean([c["waitingTime"] for c in cars]),
        car_mean_timeloss=mean([c["timeLoss"] for c in cars]),
        car_total_veh_hours=sum(c["duration"] for c in cars) / 3600.0,
        tram_mean_duration=mean([t["duration"] for t in trams]),
        tram_mean_waiting=mean([t["waitingTime"] for t in trams]),
        tram_mean_stoptime=mean([t["stopTime"] for t in trams]),
        tram_p90_duration=(sorted([t["duration"] for t in trams])[int(0.9 * (len(trams) - 1))]
                           if trams else float("nan")),
        tram_max_duration=max([t["duration"] for t in trams], default=float("nan")),
        person_mean_duration=mean([p["duration"] for p in persons]),
        person_mean_ridewait=mean([p["ride_wait"] for p in persons]),
        person_total_hours=sum(p["duration"] for p in persons) / 3600.0,
    )
    out["car_person_hours"] = out["car_total_veh_hours"] * car_occupancy
    out["transit_person_hours"] = out["person_total_hours"]
    out["total_person_hours"] = out["car_person_hours"] + out["transit_person_hours"]
    out["car_person_throughput"] = out["n_cars"] * car_occupancy
    out["transit_person_throughput"] = out["n_persons_completed_ride"]
    out["total_person_throughput"] = out["car_person_throughput"] + out["transit_person_throughput"]
    if stopout_path is not None:
        stops = parse_stopout(stopout_path)
        out["tram_dwell_mean"] = mean([s["dwell"] for s in stops])
        if terminal_eb:
            out["headway_cv_EB"] = headway_cv_at_terminal(stops, terminal_eb)["cv"]
        if terminal_wb:
            out["headway_cv_WB"] = headway_cv_at_terminal(stops, terminal_wb)["cv"]
    return out
