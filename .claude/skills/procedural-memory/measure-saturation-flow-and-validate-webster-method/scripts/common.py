"""Shared definitions for the Webster-from-first-principles experiment.

Network: isolated 4-way signalised intersection, 1 through lane per approach,
300 m arms, 13.89 m/s (50 km/h).  Only THROUGH movements are ever given green
or demand, so there are no turning-conflict confounds anywhere in the study.

Link index map of cross.net.xml (16 controlled links):
   0 in_N->out_W (r)   1 in_N->out_S (s)   2 in_N->out_E (l)   3 in_N->out_N (t)
   4 in_E->out_N (r)   5 in_E->out_W (s)   6 in_E->out_S (l)   7 in_E->out_E (t)
   8 in_S->out_E (r)   9 in_S->out_N (s)  10 in_S->out_W (l)  11 in_S->out_S (t)
  12 in_W->out_S (r)  13 in_W->out_E (s)  14 in_W->out_N (l)  15 in_W->out_W (t)
"""
import os
import subprocess

SUMO_BIN_DIR = "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/bin"
SUMO = os.path.join(SUMO_BIN_DIR, "sumo")

EP = "/Users/liuqi/Desktop/simskill/episodic-memory/2026-07-31_11-15-00"
WORK = os.path.join(EP, "attempts/attempt-1/work")
OUT = os.path.join(EP, "outputs")
NET = os.path.join(WORK, "cross.net.xml")

SPEED_LIMIT = 13.89          # m/s, network free-flow speed
STEP_LENGTH = 0.1            # s, fine enough to resolve ~1.5 s headways
YELLOW = 4                   # s, matches tlsCycleAdaptation.py -y default
ALLRED = 0                   # s, matches tlsCycleAdaptation.py -a default

# ---- signal state strings (through movements only) ------------------------
def _st(green_idx):
    s = ["r"] * 16
    for i in green_idx:
        s[i] = "G"
    return "".join(s)


def _yl(green_idx):
    s = ["r"] * 16
    for i in green_idx:
        s[i] = "y"
    return "".join(s)


NS_THROUGH = (1, 9)          # in_N->out_S , in_S->out_N
EW_THROUGH = (5, 13)         # in_E->out_W , in_W->out_E

S_NS_G = _st(NS_THROUGH)
S_NS_Y = _yl(NS_THROUGH)
S_EW_G = _st(EW_THROUGH)
S_EW_Y = _yl(EW_THROUGH)


def tls_xml(g_ns, g_ew, tls_id="center", program="webster"):
    """Two-phase fixed-time program: NS green -> NS yellow -> EW green -> EW yellow."""
    return (
        '<additional>\n'
        '    <tlLogic id="%s" type="static" programID="%s" offset="0">\n'
        '        <phase duration="%g" state="%s"/>\n'
        '        <phase duration="%g" state="%s"/>\n'
        '        <phase duration="%g" state="%s"/>\n'
        '        <phase duration="%g" state="%s"/>\n'
        '    </tlLogic>\n'
        '</additional>\n'
        % (tls_id, program, g_ns, S_NS_G, YELLOW, S_NS_Y, g_ew, S_EW_G, YELLOW, S_EW_Y)
    )


def cycle_green_onsets(g_ns, g_ew, t_end, t_start=0.0):
    """Green-onset times of the NS phase (phase 0 starts at t=0)."""
    C = g_ns + YELLOW + g_ew + YELLOW
    onsets = []
    t = 0.0
    while t < t_end:
        if t >= t_start:
            onsets.append(t)
        t += C
    return onsets, C


# ---- vehicle type parameterisations ---------------------------------------
# name -> dict of vType attributes (Krauss default model)
VTYPES = {
    "base":       dict(tau=1.0, accel=2.6, decel=4.5, minGap=2.5, length=5.0),
    "tau0.8":     dict(tau=0.8, accel=2.6, decel=4.5, minGap=2.5, length=5.0),
    "tau1.4":     dict(tau=1.4, accel=2.6, decel=4.5, minGap=2.5, length=5.0),
    "accel1.2":   dict(tau=1.0, accel=1.2, decel=4.5, minGap=2.5, length=5.0),
    "minGap5.0":  dict(tau=1.0, accel=2.6, decel=4.5, minGap=5.0, length=5.0),
    "length7.5":  dict(tau=1.0, accel=2.6, decel=4.5, minGap=2.5, length=7.5),
}


def vtype_xml(name, attrs, sigma=0.0):
    a = " ".join('%s="%s"' % (k, v) for k, v in attrs.items())
    return ('    <vType id="%s" vClass="passenger" carFollowModel="Krauss" '
            'sigma="%g" maxSpeed="%g" %s/>\n' % (name, sigma, SPEED_LIMIT, a))


ROUTES = {          # through movements only
    "NS": "in_N out_S",
    "SN": "in_S out_N",
    "EW": "in_E out_W",
    "WE": "in_W out_E",
}


def run_sumo(args, label=""):
    cmd = [SUMO] + args
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("SUMO failed (%s)\nCMD: %s\nSTDERR:\n%s"
                           % (label, " ".join(cmd), p.stderr[-4000:]))
    return p.stdout, p.stderr
