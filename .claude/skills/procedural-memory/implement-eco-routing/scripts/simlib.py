"""Simulation + output-parsing helpers shared by every stage of the study."""
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import NET, WORK, SIM_END, run, sumo_bin, classify_route  # noqa: E402


def write_edgedata_add(path, out_file, period=3600, begin=0, end=SIM_END, exclude_empty=False):
    """edgeData meandata definition. `file` is written ABSOLUTE on purpose:
    edgeData output paths resolve relative to the ADDITIONAL FILE's directory,
    not sumo's cwd -- a documented trap when running replications in parallel."""
    with open(path, "w") as f:
        f.write('<additional>\n')
        f.write('    <edgeData id="eco" type="emissions" file="%s" period="%d" begin="%d" end="%d" '
                'excludeEmpty="%s"/>\n' % (os.path.abspath(out_file), period, begin, end,
                                           "true" if exclude_empty else "false"))
        f.write('</additional>\n')
    return path


def run_sumo(routes, prefix, seed=1, extra=None, additional=None, tripinfo=True,
             emissions_edgedata=None, edge_period=SIM_END, summary=False, net=NET):
    """Plain (non-TraCI) sumo run. Returns dict of produced file paths."""
    outdir = os.path.dirname(os.path.abspath(prefix))
    os.makedirs(outdir, exist_ok=True)
    adds = list(additional or [])
    vt = os.path.join(WORK, "vtypes.add.xml")
    if os.path.exists(vt) and vt not in adds:
        adds.insert(0, vt)
    files = {}
    if emissions_edgedata:
        ed_out = prefix + "_edgeemis.xml"
        add = write_edgedata_add(prefix + "_edgedata.add.xml", ed_out, period=edge_period)
        adds.append(add)
        files["edge_emissions"] = ed_out
    cmd = [sumo_bin("sumo"), "-n", net, "-r", routes,
           "--seed", str(seed), "--end", str(SIM_END),
           "--device.emissions.probability", "1.0",
           "--time-to-teleport", "300",
           "--no-step-log", "true", "--duration-log.statistics", "true",
           "--xml-validation", "never"]
    if adds:
        cmd += ["-a", ",".join(adds)]
    if tripinfo:
        files["tripinfo"] = prefix + "_tripinfo.xml"
        cmd += ["--tripinfo-output", files["tripinfo"]]
    if summary:
        files["summary"] = prefix + "_summary.xml"
        cmd += ["--summary-output", files["summary"]]
    if extra:
        cmd += extra
    r = run(cmd)
    files["stderr"] = r.stderr
    files["stdout"] = r.stdout
    return files


# ---------------------------------------------------------------- parsing ---

def parse_tripinfo(path):
    """-> list of dicts with id, type, depart, departDelay, duration, routeLength,
    timeLoss, waitingTime, CO2 (mg), fuel (mg)."""
    out = []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag != "tripinfo":
            continue
        d = dict(id=el.get("id"), vtype=el.get("vType"),
                 depart=float(el.get("depart")),
                 departDelay=float(el.get("departDelay")),
                 duration=float(el.get("duration")),
                 routeLength=float(el.get("routeLength")),
                 timeLoss=float(el.get("timeLoss")),
                 waitingTime=float(el.get("waitingTime")),
                 arrival=float(el.get("arrival")))
        em = el.find("emissions")
        d["CO2"] = float(em.get("CO2_abs")) if em is not None else 0.0
        d["fuel"] = float(em.get("fuel_abs")) if em is not None else 0.0
        d["NOx"] = float(em.get("NOx_abs")) if em is not None else 0.0
        out.append(d)
        el.clear()
    return out


def parse_edge_emissions(path):
    """-> {interval_index: {'begin':b,'end':e,'edges':{eid:{attr:float}}}}"""
    res = []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag != "interval":
            continue
        edges = {}
        for e in el.findall("edge"):
            d = {}
            for k, v in e.attrib.items():
                if k == "id":
                    continue
                try:
                    d[k] = float(v)
                except ValueError:
                    pass
            edges[e.get("id")] = d
        res.append(dict(begin=float(el.get("begin")), end=float(el.get("end")), edges=edges))
        el.clear()
    return res


def parse_routes(path):
    """-> {vehID: (typeID, [edges])}; takes the LAST route in a routeDistribution."""
    veh = {}
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag != "vehicle":
            continue
        rds = el.findall("routeDistribution")
        if rds:
            routes = rds[-1].findall("route")
            # the *last* alternative is not necessarily the used one; prefer the
            # one flagged by `last` if present, else max probability.
            idx = rds[-1].get("last")
            r = routes[int(idx)] if idx is not None else routes[-1]
        else:
            r = el.find("route")
        veh[el.get("id")] = (el.get("type"), r.get("edges").split())
        el.clear()
    return veh


def route_shares(veh_routes, only_prefix="main."):
    from collections import Counter
    c = Counter()
    for vid, (ty, edges) in veh_routes.items():
        if only_prefix and not vid.startswith(only_prefix):
            continue
        c[classify_route(edges)] += 1
    tot = sum(c.values())
    return {k: v / tot for k, v in c.items()}, dict(c), tot


def count_teleports(stderr_text):
    return stderr_text.count("teleporting")
