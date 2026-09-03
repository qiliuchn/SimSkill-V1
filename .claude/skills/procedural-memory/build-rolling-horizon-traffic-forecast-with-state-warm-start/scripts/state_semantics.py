"""PART 1 - Empirical determination of SUMO's --save-state / --load-state semantics.

Every claim in the report is produced by one of the numbered experiments below and
written to outputs/state_semantics/results.json plus the raw run directories.

Experiments (corridor scenario unless stated otherwise):
  E1  continuation identity: uninterrupted run vs save@T -> load@T -> continue,
      with and without --save-state.rng
  E2  inventory of what the state XML actually contains
  E3  pending/not-yet-inserted flow schedule: does a continuation re-insert the
      vehicles that the first leg already emitted?
  E4  --load-state.offset semantics
  E5  --load-state.remove-vehicles semantics
  E6  rerouting-device / route-choice state
  E7  micro state loaded into --mesosim (and meso state into micro)
  E8  traffic-light phase + phase clock, actuated detectors, E1/E2/E3
      accumulators -- on a dedicated signalised probe network
"""
import gzip
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter, OrderedDict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import *  # noqa

def xparse(path):
    """ET.parse that transparently accepts a gzip-compressed sibling.
    (Bulky raw evidence XML in outputs/ is stored gzipped.)"""
    if os.path.exists(path):
        return ET.parse(path)
    if os.path.exists(path + ".gz"):
        return ET.parse(gzip.open(path + ".gz"))
    raise FileNotFoundError(path)


def xexists(path):
    return os.path.exists(path) or os.path.exists(path + ".gz")


RES = {}
RUNS = os.path.join(STATE_DIR, "runs")
os.makedirs(RUNS, exist_ok=True)

NET = os.path.join(SCEN, "corridor.net.xml")
BASE_ROU = os.path.join(SCEN, "base.rou.xml")
INC_ROU = os.path.join(SCEN, "incident.rou.xml")

T_SPLIT = 5400.0        # save/load instant (inside recurrent congestion tail)
SEED = 11


def sh(args, cwd=None):
    p = subprocess.run(args, capture_output=True, text=True, cwd=cwd)
    return p


def run_sumo(tag, extra, begin=None, end=SIM_END, routes=(BASE_ROU, INC_ROU),
             adds=("sensors.add.xml", "edgedata.add.xml"), net=NET, seed=SEED):
    d = os.path.join(RUNS, tag)
    if os.path.exists(d):
        shutil.rmtree(d)
    os.makedirs(d)
    add = []
    for a in adds:
        if a == "edgedata.add.xml":
            # NOTE: an edgeData <file> path resolves relative to the ADDITIONAL
            # FILE's own directory, not the cwd -- so every run needs its own copy
            # with an absolute output path, otherwise all runs overwrite one file.
            q = os.path.join(d, "edgedata.add.xml")
            with open(q, "w") as f:
                f.write('<additional><edgeData id="gt" period="60" file="%s" '
                        'excludeEmpty="false"/></additional>'
                        % os.path.join(d, "edgedata.xml"))
            add.append(q)
        else:
            add.append(os.path.join(SCEN, a))
    cmd = [SUMO, "-n", net, "--end", str(end), "--seed", str(seed),
           "--time-to-teleport", "-1", "--no-step-log", "true",
           "--tripinfo-output", "tripinfo.xml", "--summary-output", "summary.xml",
           "--stop-output", "stops.xml", "--duration-log.statistics", "true"]
    if routes:
        cmd += ["-r", ",".join(routes)]
    if add:
        cmd += ["-a", ",".join(add)]
    if begin is not None:
        cmd += ["--begin", str(begin)]
    cmd += extra
    p = sh(cmd, cwd=d)
    with open(os.path.join(d, "cmd.txt"), "w") as f:
        f.write(" ".join(cmd) + "\n")
    with open(os.path.join(d, "stderr.txt"), "w") as f:
        f.write(p.stderr)
    with open(os.path.join(d, "stdout.txt"), "w") as f:
        f.write(p.stdout)
    return d, p


# ---------------------------------------------------------------- comparators
def summary_rows(d, t_min=None):
    r = xparse(os.path.join(d, "summary.xml")).getroot()
    out = OrderedDict()
    for s in r:
        t = float(s.get("time"))
        if t_min is not None and t < t_min:
            continue
        out[t] = tuple(s.get(k) for k in
                       ("running", "halting", "meanSpeed", "meanWaitingTime",
                        "inserted", "ended", "loaded"))
    return out


TI_FIELDS = ("depart", "arrival", "duration", "routeLength", "timeLoss",
             "waitingTime", "departDelay", "speedFactor")


def tripinfo(d):
    p = os.path.join(d, "tripinfo.xml")
    if not os.path.exists(p):
        return {}
    r = xparse(p).getroot()
    return {t.get("id"): tuple(t.get(k) for k in TI_FIELDS) for t in r}


def edgedata(d, t_min=None):
    p = os.path.join(d, "edgedata.xml")
    if not os.path.exists(p):
        return {}
    r = xparse(p).getroot()
    out = {}
    for iv in r:
        b = float(iv.get("begin"))
        if t_min is not None and b < t_min:
            continue
        for e in iv:
            out[(b, e.get("id"))] = (e.get("speed"), e.get("sampledSeconds"),
                                     e.get("left"), e.get("entered"))
    return out


def cmp_dicts(a, b, label):
    ka, kb = set(a), set(b)
    common = ka & kb
    diff = [k for k in common if a[k] != b[k]]
    return {"label": label, "n_a": len(ka), "n_b": len(kb),
            "only_a": len(ka - kb), "only_b": len(kb - ka),
            "n_common": len(common), "n_differing": len(diff),
            "identical": (ka == kb and not diff),
            "first_diffs": [[str(k), str(a[k]), str(b[k])] for k in sorted(diff, key=str)[:5]]}


def open_state(path):
    op = gzip.open if path.endswith(".gz") else open
    with op(path, "rb") as f:
        return f.read()


# ================================================================= E1 + E3
def exp_continuation():
    out = {}
    for rng_flag, tag in ((False, "norng"), (True, "rng")):
        extra_save = ["--save-state.times", str(int(T_SPLIT)),
                      "--save-state.prefix", "st", "--save-state.suffix", ".xml"]
        if rng_flag:
            extra_save.append("--save-state.rng")

        # (a) uninterrupted reference run, which ALSO writes the state
        dref, _ = run_sumo(f"E1_{tag}_ref", extra_save)
        # (b) first leg only: 0 -> T
        # NOTE: --save-state.times T does NOT fire if --end == T ("the save-state
        # time will not be used before simulation end"); the leg must run 1 step past T.
        dleg, _ = run_sumo(f"E1_{tag}_leg1", extra_save, end=int(T_SPLIT) + 1)
        st = os.path.join(dleg, f"st_{int(T_SPLIT)}.00.xml")
        assert os.path.exists(st), sorted(os.listdir(dleg))
        # (c) continuation from the state
        dcon, pcon = run_sumo(f"E1_{tag}_cont", ["--load-state", st])

        res = {
            "state_file": st,
            "state_bytes": os.path.getsize(st),
            "ref_state_equals_leg1_state": open_state(
                os.path.join(dref, f"st_{int(T_SPLIT)}.00.xml")) == open_state(st),
            "summary_after_T": cmp_dicts(summary_rows(dref, T_SPLIT),
                                         summary_rows(dcon, T_SPLIT), "summary t>=T"),
            "edgedata_after_T": cmp_dicts(edgedata(dref, T_SPLIT),
                                          edgedata(dcon, T_SPLIT), "edgeData bins t>=T"),
        }
        # tripinfo: only vehicles that ARRIVE after T can be compared
        ta = {k: v for k, v in tripinfo(dref).items() if float(v[1]) >= T_SPLIT}
        tb = tripinfo(dcon)
        res["tripinfo_arrivals_after_T"] = cmp_dicts(ta, tb, "tripinfo arrival>=T")
        res["continuation_stderr_head"] = open(
            os.path.join(dcon, "stderr.txt")).read()[:1500]
        out[tag] = res
    return out


# ================================================================= E2 inventory
def exp_inventory():
    st = os.path.join(RUNS, "E1_rng_leg1", f"st_{int(T_SPLIT)}.00.xml")
    root = xparse(st).getroot()
    kinds = Counter(ch.tag for ch in root)
    sample = {}
    for ch in root:
        if ch.tag not in sample:
            sample[ch.tag] = {"attrib": ch.attrib,
                              "children": Counter(g.tag for g in ch)}
    # also the no-rng state for the delta
    st0 = os.path.join(RUNS, "E1_norng_leg1", f"st_{int(T_SPLIT)}.00.xml")
    kinds0 = Counter(ET.parse(st0).getroot().tag for _ in [0])
    root0 = ET.parse(st0).getroot()
    kinds0 = Counter(ch.tag for ch in root0)
    veh = [ch for ch in root if ch.tag == "vehicle"]
    return {
        "root_tag": root.tag,
        "root_attrib": root.attrib,
        "element_counts_with_rng": dict(kinds),
        "element_counts_without_rng": dict(kinds0),
        "elements_only_present_with_rng": sorted(set(kinds) - set(kinds0)),
        "example_elements": {k: {"attrib": v["attrib"], "children": dict(v["children"])}
                             for k, v in sample.items()},
        "n_vehicles_in_state": len(veh),
        "vehicle_attribute_names": sorted(veh[0].attrib) if veh else [],
        "example_vehicle": veh[0].attrib if veh else {},
    }


# ================================================================= E3 flows
def exp_flow_schedule():
    """Does the continuation re-insert the vehicles the first leg already emitted?"""
    dref = os.path.join(RUNS, "E1_rng_ref")
    dcon = os.path.join(RUNS, "E1_rng_cont")
    dleg = os.path.join(RUNS, "E1_rng_leg1")

    def last_summary(d):
        r = xparse(os.path.join(d, "summary.xml")).getroot()
        s = list(r)[-1]
        return {k: s.get(k) for k in ("time", "loaded", "inserted", "ended", "running")}

    st = xparse(os.path.join(dleg, f"st_{int(T_SPLIT)}.00.xml")).getroot()
    flowstate = [ch.attrib for ch in st if ch.tag in ("flowState", "flow")]
    # what does the continuation's FIRST summary row say?
    rc = xparse(os.path.join(dcon, "summary.xml")).getroot()
    first = list(rc)[0]
    return {
        "ref_final": last_summary(dref),
        "cont_final": last_summary(dcon),
        "leg1_final": last_summary(dleg),
        "cont_first_summary_row": {k: first.get(k) for k in
                                   ("time", "loaded", "inserted", "ended", "running")},
        "flowState_elements_in_state": flowstate,
        "note": ("If the continuation's cumulative 'inserted' at the end matches the "
                 "reference's, the flow schedule was restored and NOT replayed."),
    }


# ================================================================= E4 offset
def exp_offset():
    st = os.path.join(RUNS, "E1_rng_leg1", f"st_{int(T_SPLIT)}.00.xml")
    out = {}
    for off in (0, 1800, -1800):
        d, p = run_sumo(f"E4_offset_{off}", ["--load-state", st,
                                             "--load-state.offset", str(off)],
                        end=SIM_END + max(0, off))
        r = os.path.join(d, "summary.xml")
        info = {"returncode": p.returncode, "stderr": p.stderr[:600]}
        if os.path.exists(r) and os.path.getsize(r) > 0:
            try:
                rows = list(xparse(r).getroot())
                info["first_time"] = rows[0].get("time") if rows else None
                info["last_time"] = rows[-1].get("time") if rows else None
                info["first_running"] = rows[0].get("running") if rows else None
                ti = tripinfo(d)
                deps = sorted(float(v[0]) for v in ti.values())
                info["n_tripinfo"] = len(ti)
                info["min_depart_in_tripinfo"] = deps[0] if deps else None
            except ET.ParseError as e:
                info["parse_error"] = str(e)
        out[str(off)] = info
    return out


# ================================================================= E5 remove
def exp_remove_vehicles():
    st = os.path.join(RUNS, "E1_rng_leg1", f"st_{int(T_SPLIT)}.00.xml")
    root = xparse(st).getroot()
    vids = [ch.get("id") for ch in root if ch.tag == "vehicle"]
    victims = vids[:10]
    d, p = run_sumo("E5_remove", ["--load-state", st,
                                  "--load-state.remove-vehicles", ",".join(victims)])
    dbase = os.path.join(RUNS, "E1_rng_cont")
    tb, tr = tripinfo(dbase), tripinfo(d)
    return {
        "n_vehicles_in_state": len(vids),
        "removed_ids": victims,
        "removed_ids_present_in_baseline_tripinfo": [v for v in victims if v in tb],
        "removed_ids_present_in_removed_tripinfo": [v for v in victims if v in tr],
        "returncode": p.returncode,
        "stderr_head": p.stderr[:600],
        "summary_after_T_vs_baseline": cmp_dicts(summary_rows(dbase, T_SPLIT),
                                                 summary_rows(d, T_SPLIT), "summary"),
        "n_tripinfo_baseline": len(tb), "n_tripinfo_removed": len(tr),
    }


# ================================================================= E6 rerouting
def exp_rerouting_device():
    """Is rerouting-device state (edge-weight memory / period phase) saved?"""
    dev = ["--device.rerouting.probability", "1.0",
           "--device.rerouting.period", "300",
           "--device.rerouting.adaptation-interval", "10",
           "--device.rerouting.adaptation-steps", "18"]
    extra_save = ["--save-state.times", str(int(T_SPLIT)), "--save-state.prefix", "st",
                  "--save-state.suffix", ".xml", "--save-state.rng"]
    dref, _ = run_sumo("E6_ref", dev + extra_save)
    dleg, _ = run_sumo("E6_leg1", dev + extra_save, end=int(T_SPLIT) + 1)
    st = os.path.join(dleg, f"st_{int(T_SPLIT)}.00.xml")
    dcon, _ = run_sumo("E6_cont", dev + ["--load-state", st])
    root = xparse(st).getroot()
    veh = [ch for ch in root if ch.tag == "vehicle"]
    return {
        "state_element_counts": dict(Counter(ch.tag for ch in root)),
        "vehicle_has_device_child": dict(Counter(
            g.tag for v in veh for g in v)) if veh else {},
        "vehicle_attrs_sample": veh[0].attrib if veh else {},
        "summary_after_T": cmp_dicts(summary_rows(dref, T_SPLIT),
                                     summary_rows(dcon, T_SPLIT), "summary t>=T"),
        "edgedata_after_T": cmp_dicts(edgedata(dref, T_SPLIT),
                                      edgedata(dcon, T_SPLIT), "edgeData t>=T"),
    }


# ================================================================= E7 meso
def exp_meso_cross():
    micro_st = os.path.join(RUNS, "E1_rng_leg1", f"st_{int(T_SPLIT)}.00.xml")
    out = {}
    d, p = run_sumo("E7_micro_state_into_meso",
                    ["--load-state", micro_st, "--mesosim", "--meso-junction-control"])
    out["micro_state_into_meso"] = {"returncode": p.returncode,
                                    "stderr_head": p.stderr[:900],
                                    "stdout_head": p.stdout[:400]}
    # meso leg1 producing a meso state
    dml, pml = run_sumo("E7_meso_leg1",
                        ["--mesosim", "--meso-junction-control",
                         "--save-state.times", str(int(T_SPLIT)),
                         "--save-state.prefix", "st", "--save-state.suffix", ".xml",
                         "--save-state.rng"], end=int(T_SPLIT) + 1)
    mst = os.path.join(dml, f"st_{int(T_SPLIT)}.00.xml")
    out["meso_leg1_ok"] = os.path.exists(mst)
    if os.path.exists(mst):
        r = ET.parse(mst).getroot()
        out["meso_state_element_counts"] = dict(Counter(ch.tag for ch in r))
        veh = [c for c in r if c.tag == "vehicle"]
        out["meso_state_vehicle_attrs"] = sorted(veh[0].attrib) if veh else []
        out["meso_state_bytes"] = os.path.getsize(mst)
        out["micro_state_bytes"] = os.path.getsize(micro_st)
        d2, p2 = run_sumo("E7_meso_state_into_micro", ["--load-state", mst])
        out["meso_state_into_micro"] = {"returncode": p2.returncode,
                                        "stderr_head": p2.stderr[:900]}
        d3, p3 = run_sumo("E7_meso_cont",
                          ["--mesosim", "--meso-junction-control", "--load-state", mst])
        dmr, _ = run_sumo("E7_meso_ref",
                          ["--mesosim", "--meso-junction-control",
                           "--save-state.times", str(int(T_SPLIT)),
                           "--save-state.prefix", "st", "--save-state.suffix", ".xml",
                           "--save-state.rng"])
        out["meso_continuation"] = {
            "returncode": p3.returncode,
            "summary_after_T": cmp_dicts(summary_rows(dmr, T_SPLIT),
                                         summary_rows(d3, T_SPLIT), "summary t>=T"),
        }
    return out


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    todo = OrderedDict([
        ("E1_continuation", exp_continuation),
        ("E2_inventory", exp_inventory),
        ("E3_flow_schedule", exp_flow_schedule),
        ("E4_offset", exp_offset),
        ("E5_remove_vehicles", exp_remove_vehicles),
        ("E6_rerouting_device", exp_rerouting_device),
        ("E7_meso_cross", exp_meso_cross),
    ])
    for k, fn in todo.items():
        if which != "all" and which != k:
            continue
        print("running", k, flush=True)
        RES[k] = fn()
    p = os.path.join(STATE_DIR, "results.json" if which == "all"
                     else f"results_{which}.json")
    with open(p, "w") as f:
        json.dump(RES, f, indent=2, default=str)
    print("wrote", p)
