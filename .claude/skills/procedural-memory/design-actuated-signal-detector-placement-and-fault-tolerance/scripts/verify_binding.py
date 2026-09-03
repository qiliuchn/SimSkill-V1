#!/usr/bin/env python3
"""PROVE that hand-declared detectors really drive the actuated controller.

Motivation: this project has a documented precedent of a config flag
(`--tls.default-type` on an already-compiled net) silently doing nothing.  The
absence of an error is therefore NOT evidence that a custom-detector binding
took effect.  So every claim below is backed by a manipulation that MUST change
observable behaviour if the binding is live, plus a NEGATIVE CONTROL that shows
what a genuinely-ignored param looks like.

Variants (identical net, identical route file, identical seed -- ONLY the
detector declaration differs):

  V0_auto        no binding params at all -> SUMO auto-generates detectors
                 at detector-gap(2.0 s) x laneSpeed
  V1_custom30    all 8 lanes bound to hand-declared E1 loops, 30 m setback
  V2_far350      same, except the two MAJOR THROUGH lanes' loops are moved to
                 a 350 m setback (absurdly far upstream)
  V3_nodetector  same as V1 except the two major through lanes are
                 value="NO_DETECTOR"
  V4_close2      all loops at a 2 m setback
  V5_bogusid     V1 but the WC_0 binding points at a detector ID that does not
                 exist  -> expected to be a hard ERROR (proves the value is
                 resolved as a detector reference, not stored as free text)
  V6_junkkey     V1 PLUS an extra param whose key is not a lane ID
                 ("NOT_A_LANE_0") -> NEGATIVE CONTROL: must be byte-identical
                 to V1, demonstrating that unrecognised param keys really are
                 silently ignored in exactly the way the project precedent warns
                 about, and that the lane-ID key is what carries the meaning.

Verdict criterion: V1 must differ from V0, and V2/V3/V4 must each differ from
V1, in the *phase-duration trace*, not merely in a summary statistic.
"""
import hashlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.environ.get("SUMO_HOME", ""), "tools"))
import traci                                                    # noqa: E402
from tls_common import ALL_DET_LANES, APPROACH_LEN, GREEN_PHASES, build_program  # noqa: E402
import cfgutil                                                  # noqa: E402

MAJOR_THRU = ["EC_0", "WC_0"]
SEED, LEVEL = 1, "med"
MIN_DUR, MAX_DUR = 7.0, 50.0
END = 1800


def additional(path, setbacks=None, no_detector=(), extra_params=None,
               bogus=None, auto=False):
    lines = ['<additional>']
    params = {"max-gap": "3.0", "detector-gap": "2.0", "passing-time": "2.0"}
    if not auto:
        for ln in ALL_DET_LANES:
            if ln in no_detector:
                params[ln] = "NO_DETECTOR"
                continue
            pos = min(APPROACH_LEN - setbacks[ln], APPROACH_LEN - 0.2)
            lines.append(f'    <inductionLoop id="det_{ln}" lane="{ln}" '
                         f'pos="{pos:.2f}" period="100000" file="NUL"/>')
            params[ln] = "det_" + ln
        if bogus:
            params[bogus] = "THIS_DETECTOR_DOES_NOT_EXIST"
    params.update(extra_params or {})
    gp = {p: MIN_DUR for p in GREEN_PHASES}
    lines.append(build_program(gp, min_durs={p: MIN_DUR for p in GREEN_PHASES},
                               max_durs={p: MAX_DUR for p in GREEN_PHASES},
                               tls_type="actuated", params=params,
                               program_id="act"))
    lines.append('</additional>')
    open(path, "w").write("\n".join(lines) + "\n")


def run(tag, wd, **kw):
    os.makedirs(wd, exist_ok=True)
    addf = os.path.join(wd, "cell.add.xml")
    additional(addf, **kw)
    cmd = ["sumo", "-n", cfgutil.NET, "-r", cfgutil.rou(LEVEL, SEED),
           "-a", addf, "--begin", "0", "--end", str(END), "--step-length", "1",
           "--time-to-teleport", "180", "--no-step-log", "true",
           "--tripinfo-output", os.path.join(wd, "tripinfo.xml"),
           "--seed", str(SEED), "--message-log", os.path.join(wd, "msg.log"),
           "--error-log", os.path.join(wd, "err.log")]
    # first: a plain (non-TraCI) run so we capture load-time errors/warnings
    r = subprocess.run(cmd, capture_output=True, text=True)
    stderr = r.stderr
    if r.returncode != 0:
        return dict(tag=tag, failed=True, returncode=r.returncode,
                    stderr=stderr.strip()[:1500])

    # then the TraCI run for the phase trace
    traci.start(cmd, label=tag)
    c = traci.getConnection(tag)
    c.trafficlight.setProgram("C", "act")
    trace, cur, gstart = [], c.trafficlight.getPhase("C"), 0.0
    t = 0.0
    while t < END:
        c.simulationStep()
        t = c.simulation.getTime()
        ph = c.trafficlight.getPhase("C")
        if ph != cur:
            if cur in GREEN_PHASES:
                trace.append((GREEN_PHASES[cur]["name"], round(t - gstart, 1)))
            gstart, cur = t, ph
    c.close()
    open(os.path.join(wd, "phase_trace.txt"), "w").write(
        "\n".join(f"{n}\t{d}" for n, d in trace) + "\n")
    per = {}
    for n, d in trace:
        per.setdefault(n, []).append(d)
    return dict(
        tag=tag, failed=False,
        trace_sha1=hashlib.sha1(repr(trace).encode()).hexdigest()[:16],
        n_greens=len(trace),
        mean_green={k: round(sum(v) / len(v), 2) for k, v in per.items()},
        n_cycles={k: len(v) for k, v in per.items()},
        warn_no_ctrl_det=sum(1 for l in stderr.splitlines()
                             if "has no controlling detector" in l),
        warn_mindur_short=[l.strip() for l in stderr.splitlines()
                           if "is too short for a detector gap" in l],
    )


def main(base):
    os.makedirs(base, exist_ok=True)
    sb30 = {ln: 30.0 for ln in ALL_DET_LANES}
    sbfar = dict(sb30, **{ln: 350.0 for ln in MAJOR_THRU})
    sb2 = {ln: 2.0 for ln in ALL_DET_LANES}

    res = []
    res.append(run("V0_auto", f"{base}/V0_auto", auto=True))
    res.append(run("V1_custom30", f"{base}/V1_custom30", setbacks=sb30))
    res.append(run("V2_far350", f"{base}/V2_far350", setbacks=sbfar))
    res.append(run("V3_nodetector", f"{base}/V3_nodetector", setbacks=sb30,
                   no_detector=MAJOR_THRU))
    res.append(run("V4_close2", f"{base}/V4_close2", setbacks=sb2))
    res.append(run("V5_bogusid", f"{base}/V5_bogusid", setbacks=sb30,
                   bogus="WC_0"))
    res.append(run("V6_junkkey", f"{base}/V6_junkkey", setbacks=sb30,
                   extra_params={"NOT_A_LANE_0": "det_WC_0"}))

    by = {r["tag"]: r for r in res}
    v1 = by["V1_custom30"]
    verdict = {}
    if not v1["failed"]:
        verdict["V1_differs_from_auto_V0"] = (
            not by["V0_auto"]["failed"]
            and by["V0_auto"]["trace_sha1"] != v1["trace_sha1"])
        for t in ("V2_far350", "V3_nodetector", "V4_close2"):
            verdict[f"{t}_differs_from_V1"] = (
                not by[t]["failed"] and by[t]["trace_sha1"] != v1["trace_sha1"])
        verdict["V5_bogusid_is_hard_error"] = by["V5_bogusid"]["failed"]
        verdict["V6_junkkey_identical_to_V1"] = (
            not by["V6_junkkey"]["failed"]
            and by["V6_junkkey"]["trace_sha1"] == v1["trace_sha1"])
    verdict["BINDING_VERIFIED"] = all(verdict.values())
    out = dict(results=res, verdict=verdict)
    json.dump(out, open(os.path.join(base, "binding_verification.json"), "w"),
              indent=2)
    for r in res:
        if r["failed"]:
            print(f"{r['tag']:15s} FAILED rc={r['returncode']}: "
                  f"{r['stderr'][:200]}")
        else:
            print(f"{r['tag']:15s} sha={r['trace_sha1']} greens={r['n_greens']:3d} "
                  f"meanGreen={r['mean_green']} noCtrlDetWarn={r['warn_no_ctrl_det']}")
    print("\nVERDICT:", json.dumps(verdict, indent=2))
    return out


if __name__ == "__main__":
    main(sys.argv[1])
