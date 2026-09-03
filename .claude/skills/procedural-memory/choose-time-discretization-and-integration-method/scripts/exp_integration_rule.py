"""Minimal, decisive verification of SUMO's position-update contract.

A single vehicle accelerating from rest at constant a on a free lane has the EXACT
solution x(t) = 0.5*a*t^2 while a is unsaturated.  Comparing SUMO's reported position
against that closed form isolates the integrator with no traffic-flow confound.

Two non-obvious behaviours are tested (both turned out TRUE):
  G1  vType actionStepLength STRICTLY GREATER than --step-length silently switches the
      Euler run to the exact (ballistic-equivalent) position update.
  G2  merely SUPPLYING --default.action-step-length on the command line -- even with the
      value 0, which is its own documented default -- does the same thing.
"""
import os
import sys
import shutil
import xml.etree.ElementTree as ET
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dtcommon import NET, RUNS, run_sumo, BASE_ARGS, savejson   # noqa

APPR = os.path.join(NET, "appr.net.xml")
A, DECEL = 2.6, 4.5
D = os.path.join(RUNS, "integration_rule")


def trace(f):
    r = []
    for _, el in ET.iterparse(f, events=("end",)):
        if el.tag == "timestep":
            t = float(el.attrib["time"])
            for v in el:
                r.append((t, float(v.attrib["pos"]), float(v.attrib["speed"])))
            el.clear()
    return r


def one(tag, dt, ballistic, vtype_asl=None, cli_asl="ABSENT"):
    d = os.path.join(D, tag)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    aslattr = '' if vtype_asl is None else ' actionStepLength="%g"' % vtype_asl
    open(os.path.join(d, "v.rou.xml"), "w").write(
        '<routes><vType id="c" accel="%g" decel="%g" sigma="0" length="5" minGap="2.5" '
        'maxSpeed="30" tau="1" speedDev="0" speedFactor="1"%s/>'
        '<vehicle id="p" type="c" depart="0" departSpeed="0" departPos="0">'
        '<route edges="ein eout"/></vehicle></routes>' % (A, DECEL, aslattr))
    f = os.path.join(d, "f.xml")
    args = ["-n", APPR, "-r", os.path.join(d, "v.rou.xml"), "--fcd-output", f,
            "--begin", "0", "--end", "6", "--step-length", str(dt)] + BASE_ARGS
    if ballistic:
        args += ["--step-method.ballistic", "true"]
    if cli_asl != "ABSENT":
        args += ["--default.action-step-length", str(cli_asl)]
    r = run_sumo(args, cwd=d)
    if r["rc"] != 0:
        return dict(tag=tag, ok=False, err=r["err"][-300:])
    tr = trace(f)
    rows = []
    for t, x, s in tr:
        if 0 < t <= 5.0:                    # a is unsaturated up to v_lane/a = 5.34 s
            rows.append(dict(t=t, x_sumo=x, x_exact=0.5 * A * t * t,
                             x_euler=sum(A * dt * k * dt for k in range(1, int(round(t / dt)) + 1)),
                             err=x - 0.5 * A * t * t))
    return dict(tag=tag, ok=True, dt=dt, ballistic=ballistic, vtype_asl=vtype_asl,
                cli_asl=cli_asl, rows=rows,
                err_at_1s=[r_["err"] for r_ in rows if abs(r_["t"] - 1.0) < 1e-9],
                max_abs_err=max(abs(r_["err"]) for r_ in rows) if rows else None,
                rule=("EXACT/ballistic" if max(abs(r_["err"]) for r_ in rows) < 0.02
                      else "EULER (x += v_new*dt)"))


if __name__ == "__main__":
    cases = []
    for dt in (1.0, 0.5, 0.25, 0.1):
        cases.append(one("dt%g_euler" % dt, dt, False))
        cases.append(one("dt%g_ball" % dt, dt, True))
        cases.append(one("dt%g_euler_vtypeasl_eq" % dt, dt, False, vtype_asl=dt))
        cases.append(one("dt%g_euler_vtypeasl_1" % dt, dt, False, vtype_asl=1.0))
        cases.append(one("dt%g_euler_cliasl_0" % dt, dt, False, cli_asl=0))
    savejson("integration_rule_probe.json", cases)
    print("%-32s %8s %14s  %s" % ("case", "maxErr", "err@t=1s", "inferred rule"))
    for c in cases:
        if not c.get("ok"):
            print(c)
            continue
        print("%-32s %8.4f %14.4f  %s" % (c["tag"], c["max_abs_err"],
                                          c["err_at_1s"][0] if c["err_at_1s"] else float("nan"),
                                          c["rule"]))
    print("\nG1 (vType actionStepLength > step-length turns Euler into exact update):",
          all(c["rule"].startswith("EXACT") for c in cases
              if c["ok"] and c["vtype_asl"] == 1.0 and c["dt"] < 1.0))
    print("G2 (--default.action-step-length 0 turns Euler into exact update):",
          all(c["rule"].startswith("EXACT") for c in cases if c["ok"] and c["cli_asl"] == 0))
    print("control: vType actionStepLength == step-length leaves Euler intact:",
          all(c["rule"].startswith("EULER") for c in cases
              if c["ok"] and c["vtype_asl"] is not None and c["vtype_asl"] == c["dt"]))
