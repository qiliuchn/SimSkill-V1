#!/usr/bin/env python3
"""
Diagnose the two state-serialization traps that rollout MPC (Controller B) walks
straight into, both flagged by
`build-rolling-horizon-traffic-forecast-with-state-warm-start`:

  T1  tlLogic phase bookkeeping is corrupted on a save/load round-trip
  T2  restoring a state's <flowState> onto a different route file silently
      double-counts demand

and establish whether a persistent SHADOW instance driven by
traci.simulation.saveState / loadState (rather than a fresh `sumo --load-state`
process per branch) is usable at all -- libsumo is not installed in this
environment, so an in-process fork is not available.
"""
import argparse
import json
import os
import sys
import time
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import SUMO, SUMO_HOME, PhaseModel  # noqa: E402

sys.path.append(os.path.join(SUMO_HOME, "tools"))
import traci  # noqa: E402

HOLD = 100000.0


def t1_phase_bookkeeping(net, routes, work):
    """Save at t=600 while mid-green, load into a shadow, and compare what the
    shadow reports about the traffic light against the truth."""
    os.makedirs(work, exist_ok=True)
    st = os.path.join(work, "t1.state.xml")
    base = [SUMO, "-n", net, "-r", routes, "--step-length", "0.5",
            "--no-step-log", "true", "--no-warnings", "true", "--end", "3600",
            "--save-state.precision", "6", "--save-state.rng", "true"]
    traci.start(base, label="t1main")
    m = traci.getConnection("t1main")
    tls = m.trafficlight.getIDList()[0]
    for _ in range(1200):
        m.simulationStep()
    truth = dict(t=m.simulation.getTime(), phase=m.trafficlight.getPhase(tls),
                 spent=m.trafficlight.getSpentDuration(tls),
                 next_switch=m.trafficlight.getNextSwitch(tls),
                 dur=m.trafficlight.getPhaseDuration(tls),
                 running=m.simulation.getMinExpectedNumber())
    m.simulation.saveState(st)
    m.close()

    traci.start(base, label="t1shadow")
    s = traci.getConnection("t1shadow")
    for _ in range(10):
        s.simulationStep()
    t_load0 = time.perf_counter()
    s.simulation.loadState(st)
    load_ms = (time.perf_counter() - t_load0) * 1000.0
    after = dict(t=s.simulation.getTime(), phase=s.trafficlight.getPhase(tls),
                 spent=s.trafficlight.getSpentDuration(tls),
                 next_switch=s.trafficlight.getNextSwitch(tls),
                 dur=s.trafficlight.getPhaseDuration(tls),
                 running=s.simulation.getMinExpectedNumber())
    # repeated round-trips from the same file (what a rollout actually does)
    times = []
    for _ in range(5):
        t0 = time.perf_counter()
        s.simulation.loadState(st)
        for _ in range(10):
            s.simulationStep()
        times.append((time.perf_counter() - t0) * 1000.0)
    repeat_ok = abs(s.simulation.getTime() - (truth["t"] + 5.0)) < 1e-6
    s.close()

    # what the raw state file records for the tlLogic
    raw = {}
    try:
        root = ET.parse(st).getroot()
        for el in root.iter("tlLogic"):
            raw = dict(el.attrib)
            break
    except Exception as e:
        raw = {"parse_error": str(e)}
    return dict(truth=truth, after_load=after, raw_tllogic_in_state=raw,
                first_load_ms=load_ms, repeat_cycle_ms=times,
                repeat_load_works=repeat_ok,
                phase_matches=truth["phase"] == after["phase"],
                spent_matches=abs(truth["spent"] - after["spent"]) < 1e-6,
                nextswitch_matches=abs(truth["next_switch"] - after["next_switch"]) < 1e-6)


def t1_external_drive(net, routes, work):
    """The bookkeeping probe that MATTERS for rollout MPC: sample the round trip
    at an instant when the green being held was started by TraCI a known number
    of seconds ago, NOT at t=0 where `spent == sim time` and any shadow would
    reproduce it without restoring anything.

    Attempt 1's probe fired only on the very first decision epoch (it was inside
    `if self.bookkeeping is None`), so every sample it collected had
    phase 0 held since t=0 -- a case that cannot distinguish a restored clock
    from a fresh one.  Here the main run is deliberately switched at a known
    time and sampled well after the switch.
    """
    os.makedirs(work, exist_ok=True)
    st = os.path.join(work, "t1x.state.xml")
    base = [SUMO, "-n", net, "-r", routes, "--step-length", "0.5",
            "--no-step-log", "true", "--no-warnings", "true", "--end", "3600",
            "--save-state.precision", "6", "--save-state.rng", "true"]
    traci.start(base, label="t1xmain")
    m = traci.getConnection("t1xmain")
    tls = m.trafficlight.getIDList()[0]
    pm = PhaseModel(net, tls)
    g0, g1 = pm.green_phases[0], pm.green_phases[1]
    # hold g0 externally, switch to g1 at a known instant, then sample later
    m.trafficlight.setPhase(tls, g0)
    m.trafficlight.setPhaseDuration(tls, HOLD)
    for _ in range(200):                       # 100 s on g0
        m.simulationStep()
    t_switch = m.simulation.getTime()
    m.trafficlight.setPhase(tls, g1)
    m.trafficlight.setPhaseDuration(tls, HOLD)
    samples = []
    for rep in range(3):
        for _ in range(16):                    # +8 s per sample
            m.simulationStep()
        now = m.simulation.getTime()
        truth = dict(t=now, phase=m.trafficlight.getPhase(tls),
                     spent=m.trafficlight.getSpentDuration(tls),
                     python_elapsed=now - t_switch)
        m.simulation.saveState(st)
        traci.start(base, label=f"t1xsh{rep}")
        s = traci.getConnection(f"t1xsh{rep}")
        s.simulation.loadState(st)
        shadow = dict(t=s.simulation.getTime(), phase=s.trafficlight.getPhase(tls),
                      spent=s.trafficlight.getSpentDuration(tls))
        s.close()
        samples.append(dict(main=truth, shadow=shadow,
                            phase_matches=truth["phase"] == shadow["phase"],
                            spent_matches=abs(truth["spent"] - shadow["spent"]) < 1e-6,
                            spent_error=shadow["spent"] - truth["spent"]))
    m.close()
    return dict(switch_time=t_switch, samples=samples,
                phase_always_matches=all(x["phase_matches"] for x in samples),
                spent_ever_matches=any(x["spent_matches"] for x in samples),
                shadow_spent_always_zero=all(abs(x["shadow"]["spent"]) < 1e-9
                                             for x in samples))


def make_flow_routes(path, veh_per_hour, route_edges, flow_id, begin):
    with open(path, "w") as f:
        f.write('<routes>\n  <vType id="car" maxSpeed="13.89"/>\n'
                f'  <route id="r" edges="{route_edges}"/>\n'
                f'  <flow id="{flow_id}" type="car" route="r" begin="{begin}" '
                f'end="3600" vehsPerHour="{veh_per_hour}"/>\n</routes>\n')


def t2_flowstate(net, work, fork_t=600.0, vph=900, window=120.0):
    """Rebuild the memory page's actual scenario and test whether stripping
    <flowState> fixes or breaks it.

    The scenario that produces double counting is a FORECAST fork: the ground
    truth is a <flow> that has been running since t=0, and the forecast's own
    route file re-declares THE SAME flow id with `begin` set to the fork time
    (that is what a forecaster writes -- it does not want to replay the past).
    Restoring <flowState> then leaves the pre-fork schedule live *as well as*
    the newly-parsed flow, and the window gets served twice.

    Attempt 1's version of this test used two DIFFERENT flow ids (`f_A`, `f_B`)
    both with `begin="0"`, so the fork never exercised double counting at all:
    the inflation it reported was the new flow back-filling the 600 s of
    insertions it had "missed" while the state was being made.  That was a
    test-construction artifact and its conclusion is withdrawn.
    """
    os.makedirs(work, exist_ok=True)
    truth_rou = os.path.join(work, "t2_truth.rou.xml")      # ground truth chain
    fc_rou = os.path.join(work, "t2_forecast.rou.xml")      # forecast's own file
    backfill_rou = os.path.join(work, "t2_backfill.rou.xml")  # attempt-1 style
    fcdiff_rou = os.path.join(work, "t2_fcdiff.rou.xml")      # own id, own begin
    make_flow_routes(truth_rou, vph, "in_C_N out_C_S", "f", 0)
    make_flow_routes(fc_rou, vph, "in_C_N out_C_S", "f", int(fork_t))
    make_flow_routes(backfill_rou, vph, "in_C_N out_C_S", "f_B", 0)
    make_flow_routes(fcdiff_rou, vph, "in_C_N out_C_S", "f_B", int(fork_t))
    st = os.path.join(work, "t2.state.xml")
    base = [SUMO, "-n", net, "--step-length", "0.5", "--no-step-log", "true",
            "--no-warnings", "true", "--end", "3600", "--save-state.precision", "6"]
    traci.start(base + ["-r", truth_rou], label="t2main")
    m = traci.getConnection("t2main")
    for _ in range(int(fork_t / 0.5)):
        m.simulationStep()
    m.simulation.saveState(st)
    n_at_save = m.simulation.getDepartedNumber()
    m.close()

    def fork(state_file, route_file, label):
        traci.start(base + ["-r", route_file], label=label)
        s = traci.getConnection(label)
        s.simulation.loadState(state_file)
        dep, ids_all = 0, []
        for _ in range(int(window / 0.5)):
            s.simulationStep()
            ids = s.simulation.getDepartedIDList()
            dep += len(ids)
            ids_all.extend(ids)
        s.close()
        # split ids by flow id and by the flow's own running index: the restored
        # <flowState> continues the pre-fork counter (index >= `done` at save),
        # a freshly parsed flow starts again from 0, so the two sources are
        # separable even when they share a flow id.
        byflow, lo_idx, hi_idx = {}, 0, 0
        for i in ids_all:
            k, _, sfx = i.rpartition(".")
            byflow[k] = byflow.get(k, 0) + 1
            try:
                n = int(sfx)
            except ValueError:
                continue
            if n < split_index:
                lo_idx += 1          # fresh counter -> newly parsed flow
            else:
                hi_idx += 1          # continued counter -> restored flowState
        return dict(departed=dep, by_flow=byflow, ids=ids_all[:6] + ids_all[-3:],
                    from_fresh_counter=lo_idx, from_restored_counter=hi_idx)

    stripped = os.path.join(work, "t2_stripped.state.xml")
    tree = ET.parse(st)
    root = tree.getroot()
    n_flowstate = 0
    flowstate_attrs = []
    for el in list(root):
        if el.tag == "flowState":
            flowstate_attrs.append(dict(el.attrib))
            root.remove(el)
            n_flowstate += 1
    tree.write(stripped)
    split_index = int(flowstate_attrs[0].get("index", 0)) if flowstate_attrs else 0

    expected = vph * window / 3600.0
    res = dict(
        n_flowstate_elements=n_flowstate,
        flowstate_attrs=flowstate_attrs,
        n_departed_at_save=n_at_save,
        expected_departures_in_window=expected,
        # -- the memory page's scenario: fork onto the forecast's own file ------
        # (a) forecast file re-declares the SAME flow id, begin at the fork
        forecast_fork_unstripped=fork(st, fc_rou, "t2fc"),
        forecast_fork_stripped=fork(stripped, fc_rou, "t2fcs"),
        # (b) forecast file uses its OWN flow id, begin at the fork -- this is
        #     the configuration that double-counts on the CLI path
        forecast_diffid_unstripped=fork(st, fcdiff_rou, "t2fd"),
        forecast_diffid_stripped=fork(stripped, fcdiff_rou, "t2fds"),
        # -- continuing the SAME chain: stripping must be skipped here ---------
        same_file_unstripped=fork(st, truth_rou, "t2same"),
        same_file_stripped=fork(stripped, truth_rou, "t2samestrip"),
        # -- attempt-1's construction, kept to document why it showed nothing --
        a1_different_flow_id_unstripped=fork(st, backfill_rou, "t2a1"),
        a1_different_flow_id_stripped=fork(stripped, backfill_rou, "t2a1s"),
    )
    for k in list(res):
        if isinstance(res[k], dict) and "departed" in res[k]:
            res[k]["inflation_pct"] = 100.0 * (res[k]["departed"] - expected) / expected
    return res


def t2b_cli_loadstate(net, work, fork_t=600.0, vph=900, window=120.0):
    """Same fork matrix, but through the CLI `--load-state` path in a FRESH sumo
    process rather than TraCI's simulation.loadState on a warm process.

    These are not obviously the same code path -- a warm process has already
    parsed and instantiated the route file's flows before the state arrives,
    a cold one parses them alongside the state -- so the trap is measured on
    both rather than assumed to transfer.
    """
    import subprocess
    os.makedirs(work, exist_ok=True)
    truth_rou = os.path.join(work, "t2_truth.rou.xml")
    fc_rou = os.path.join(work, "t2_forecast.rou.xml")
    backfill_rou = os.path.join(work, "t2_backfill.rou.xml")     # id f_B, begin 0
    fcdiff_rou = os.path.join(work, "t2_fcdiff.rou.xml")         # id f_B, begin fork
    make_flow_routes(truth_rou, vph, "in_C_N out_C_S", "f", 0)
    make_flow_routes(fc_rou, vph, "in_C_N out_C_S", "f", int(fork_t))
    make_flow_routes(backfill_rou, vph, "in_C_N out_C_S", "f_B", 0)
    make_flow_routes(fcdiff_rou, vph, "in_C_N out_C_S", "f_B", int(fork_t))
    st = os.path.join(work, "t2cli.state.xml")
    # make the state with a plain CLI run so no TraCI is involved anywhere
    subprocess.run([SUMO, "-n", net, "-r", truth_rou, "--step-length", "0.5",
                    "--no-step-log", "true", "--no-warnings", "true",
                    "--end", str(fork_t + 1.0), "--save-state.times", str(fork_t),
                    "--save-state.precision", "6", "--save-state.files", st],
                   check=True, capture_output=True)
    stripped = os.path.join(work, "t2cli_stripped.state.xml")
    tree = ET.parse(st)
    root = tree.getroot()
    fs = []
    for el in list(root):
        if el.tag == "flowState":
            fs.append(dict(el.attrib))
            root.remove(el)
    tree.write(stripped)
    split_index = int(fs[0].get("index", 0)) if fs else 0

    def cli_fork(state_file, route_file, tag):
        ti = os.path.join(work, f"t2cli_{tag}.tripinfo.xml")
        subprocess.run([SUMO, "-n", net, "-r", route_file, "--step-length", "0.5",
                        "--no-step-log", "true", "--no-warnings", "true",
                        "--load-state", state_file, "--end", str(fork_t + window),
                        "--tripinfo-output", ti,
                        "--tripinfo-output.write-unfinished", "true"],
                       check=True, capture_output=True)
        dep, byflow, lo, hi = 0, {}, 0, 0
        for _, el in ET.iterparse(ti, events=("end",)):
            if el.tag != "tripinfo":
                continue
            t = float(el.get("depart"))
            if t >= fork_t - 1e-6:
                dep += 1
                k, _, sfx = el.get("id").rpartition(".")
                byflow[k] = byflow.get(k, 0) + 1
                try:
                    lo += int(sfx) < split_index
                    hi += int(sfx) >= split_index
                except ValueError:
                    pass
            el.clear()
        return dict(departed=dep, by_flow=byflow,
                    from_fresh_counter=lo, from_restored_counter=hi,
                    inflation_pct=100.0 * (dep - vph * window / 3600.0) /
                    (vph * window / 3600.0))

    return dict(
        flowstate_attrs=fs, expected_departures_in_window=vph * window / 3600.0,
        sameid_forecastbegin_unstripped=cli_fork(st, fc_rou, "sfu"),
        sameid_forecastbegin_stripped=cli_fork(stripped, fc_rou, "sfs"),
        sameid_begin0_unstripped=cli_fork(st, truth_rou, "s0u"),
        sameid_begin0_stripped=cli_fork(stripped, truth_rou, "s0s"),
        diffid_forecastbegin_unstripped=cli_fork(st, fcdiff_rou, "dfu"),
        diffid_forecastbegin_stripped=cli_fork(stripped, fcdiff_rou, "dfs"),
        diffid_begin0_unstripped=cli_fork(st, backfill_rou, "d0u"),
        diffid_begin0_stripped=cli_fork(stripped, backfill_rou, "d0s"))


def t3_explicit_vehicles(net, routes, work):
    """This study's own demand uses explicit <vehicle> elements, so a state
    should contain NO <flowState> at all -- verify, rather than assume."""
    os.makedirs(work, exist_ok=True)
    st = os.path.join(work, "t3.state.xml")
    traci.start([SUMO, "-n", net, "-r", routes, "--step-length", "0.5",
                 "--no-step-log", "true", "--no-warnings", "true", "--end", "3600",
                 "--save-state.precision", "6"], label="t3")
    m = traci.getConnection("t3")
    for _ in range(1200):
        m.simulationStep()
    m.simulation.saveState(st)
    m.close()
    root = ET.parse(st).getroot()
    tags = {}
    for el in root:
        tags[el.tag] = tags.get(el.tag, 0) + 1
    return dict(state_top_level_tags=tags,
                has_flowState="flowState" in tags,
                size_kb=os.path.getsize(st) / 1024.0)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", required=True)
    ap.add_argument("--routes", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    res = {}
    res["T1_phase_bookkeeping"] = t1_phase_bookkeeping(a.net, a.routes, a.work)
    res["T1b_external_drive"] = t1_external_drive(a.net, a.routes, a.work)
    res["T2_flowstate"] = t2_flowstate(a.net, a.work)
    res["T2b_cli_loadstate"] = t2b_cli_loadstate(a.net, a.work)
    res["T3_explicit_vehicles"] = t3_explicit_vehicles(a.net, a.routes, a.work)
    json.dump(res, open(a.out, "w"), indent=1)
    print(json.dumps(res, indent=1))
